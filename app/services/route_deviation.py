from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from app.integrations.tomtom import TomTomClient
from app.services.traffic_monitoring import haversine, route_projection
from app.services.trip_operations import trip_operations_service
from app.storage.operations import OperationsRepository, utc_now
from app.services.routing_provider import RoutingProviderService, validate_route_geometry

MANDATORY_POINTS=[(-19.9821111,-44.2662371),(-16.166198,-42.319719),(-15.805844,-41.366608),(-14.883843,-40.809014),(-8.207594,-34.963157)]
ROUTE_ID="betim-jaboatao"; ROUTE_VERSION="tomtom-mandatory-v1"
MAX_IMPLIED_SPEED_KMH = 160.0
MAX_GAP_HOURS = 6.0
MAX_GAP_DISTANCE_KM = 30.0
FUTURE_TOLERANCE_MINUTES = 5.0


class RouteDeviationService:
    def __init__(self,repository:OperationsRepository): self.repository=repository

    async def ensure_geometry(
        self,client:TomTomClient|None=None,*,allow_external:bool=False
    )->dict[str,Any]:
        existing=self.geometry(ROUTE_ID)
        if existing:return existing
        if not allow_external:
            return {}
        provider=RoutingProviderService(client or TomTomClient()); origin=":".join(f"{lat},{lon}" for lat,lon in MANDATORY_POINTS[:-1]); destination=f"{MANDATORY_POINTS[-1][0]},{MANDATORY_POINTS[-1][1]}"
        payload=await provider.get_route(
            origin,destination,travel_mode="truck",include_traffic=False,
            request_context=f"geometry_bootstrap:{ROUTE_ID}",
        )
        points=validate_route_geometry(payload)
        if len(points)<100:raise RuntimeError("Geometria operacional insuficiente")
        with self.repository.connect() as connection:
            connection.execute("UPDATE route_geometry_versions SET active=0 WHERE route_id=?",(ROUTE_ID,))
            connection.execute("INSERT INTO route_geometry_versions(route_id,version,source,geometry_json,mandatory_points_json,corridor_m,segment_tolerances_json,active,created_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(route_id,version) DO UPDATE SET geometry_json=excluded.geometry_json,active=1",
                               (ROUTE_ID,ROUTE_VERSION,f"{payload.get('_provider') or 'Routing provider'} truck profile with mandatory control points",json.dumps(points),json.dumps(MANDATORY_POINTS),300,"[]",1,utc_now()))
        return self.geometry(ROUTE_ID) or {}

    def geometry(self,route_id:str,version:str|None=None)->dict[str,Any]|None:
        with self.repository.connect() as connection:
            if version: row=connection.execute("SELECT * FROM route_geometry_versions WHERE route_id=? AND version=?",(route_id,version)).fetchone()
            else: row=connection.execute("SELECT * FROM route_geometry_versions WHERE route_id=? AND active=1 ORDER BY id DESC LIMIT 1",(route_id,)).fetchone()
        if not row:return None
        value=dict(row);value["geometry"]=json.loads(value.pop("geometry_json"));value["mandatory_points"]=json.loads(value.pop("mandatory_points_json"));value["segment_tolerances"]=json.loads(value.pop("segment_tolerances_json"));value["active"]=bool(value["active"]);return value

    def process(self,trip_key:str,plate:str,route_id:str|None,latitude:float,longitude:float,recorded_at:str)->dict[str,Any]|None:
        if not route_id:return None
        geometry=self.geometry(route_id)
        if geometry:
            route=[(point["latitude"],point["longitude"]) for point in geometry["geometry"]];_,distance_km=route_projection((latitude,longitude),route);distance_m=distance_km*1000;tolerance=self._tolerance(geometry,route,(latitude,longitude))
        else:return None
        outside=distance_m>tolerance
        with self.repository.connect() as connection:
            tracker=connection.execute("SELECT * FROM route_deviation_trackers WHERE trip_key=?",(trip_key,)).fetchone();active=connection.execute("SELECT * FROM route_deviations WHERE trip_key=? AND status='ACTIVE' ORDER BY id DESC LIMIT 1",(trip_key,)).fetchone()
            outside_count=(tracker["outside_count"] if tracker else 0);inside_count=(tracker["inside_count"] if tracker else 0);first_at=tracker["first_outside_at"] if tracker else None;first_lat=tracker["first_outside_latitude"] if tracker else None;first_lon=tracker["first_outside_longitude"] if tracker else None
            if outside:
                outside_count+=1;inside_count=0
                if outside_count==1:first_at,first_lat,first_lon=recorded_at,latitude,longitude
            else:
                inside_count+=1;outside_count=0
                if not active:first_at=first_lat=first_lon=None
            connection.execute("INSERT INTO route_deviation_trackers(trip_key,outside_count,inside_count,first_outside_at,first_outside_latitude,first_outside_longitude,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(trip_key) DO UPDATE SET outside_count=excluded.outside_count,inside_count=excluded.inside_count,first_outside_at=excluded.first_outside_at,first_outside_latitude=excluded.first_outside_latitude,first_outside_longitude=excluded.first_outside_longitude,updated_at=excluded.updated_at",(trip_key,outside_count,inside_count,first_at,first_lat,first_lon,recorded_at))
            if outside and not active and outside_count>=2:
                related=self._related(float(first_lat),float(first_lon),route_id);cursor=connection.execute("INSERT INTO route_deviations(trip_key,plate,route_id,geometry_version,status,level,started_at,exit_latitude,exit_longitude,last_outside_at,current_distance_m,max_distance_m,related_incidents_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(trip_key,plate,route_id,geometry["version"],"ACTIVE","INITIAL",first_at,first_lat,first_lon,recorded_at,distance_m,distance_m,json.dumps(related),utc_now()));active=connection.execute("SELECT * FROM route_deviations WHERE id=?",(cursor.lastrowid,)).fetchone();self._event(connection,active["id"],"DEVIATION_CONFIRMED",recorded_at,"INITIAL",distance_m)
            elif active and outside:
                level=self._level(active["started_at"],recorded_at);connection.execute("UPDATE route_deviations SET last_outside_at=?,current_distance_m=?,max_distance_m=MAX(max_distance_m,?),level=? WHERE id=?",(recorded_at,distance_m,distance_m,level,active["id"]));
                if level!=active["level"]:self._event(connection,active["id"],"LEVEL_CHANGED",recorded_at,level,distance_m)
            elif active and not outside and inside_count>=2:
                connection.execute("UPDATE route_deviations SET status='RETURNED',returned_at=?,current_distance_m=? WHERE id=?",(recorded_at,distance_m,active["id"]));self._event(connection,active["id"],"RETURN_CONFIRMED",recorded_at,active["level"],distance_m);active=None
        return self.active_for_trip(trip_key)

    def active_for_trip(self,trip_key:str)->dict[str,Any]|None:
        trip=self.repository.trip(trip_key)
        if trip and trip.get("state") in {"FINALIZADA_NO_SISTEMA","RETORNO_CONCLUIDO"}:return None
        with self.repository.connect() as connection:row=connection.execute("SELECT * FROM route_deviations WHERE trip_key=? AND status='ACTIVE' ORDER BY id DESC LIMIT 1",(trip_key,)).fetchone()
        return self._deviation(row) if row else None

    def active(self)->list[dict[str,Any]]:
        with self.repository.connect() as connection:rows=connection.execute("SELECT d.* FROM route_deviations d JOIN operational_trips t ON t.trip_key=d.trip_key WHERE d.status='ACTIVE' AND t.state NOT IN ('FINALIZADA_NO_SISTEMA','RETORNO_CONCLUIDO') ORDER BY d.started_at").fetchall()
        return [self._deviation(row) for row in rows]

    def history(self,trip_key:str)->list[dict[str,Any]]:
        with self.repository.connect() as connection:rows=connection.execute("SELECT * FROM route_deviations WHERE trip_key=? ORDER BY started_at DESC",(trip_key,)).fetchall()
        return [self._deviation(row) for row in rows]

    def acknowledge(self,deviation_id:int,user:str,reason:str,justification:str)->dict[str,Any]:
        now=utc_now()
        with self.repository.connect() as connection:
            row=connection.execute("SELECT * FROM route_deviations WHERE id=?",(deviation_id,)).fetchone()
            if not row:raise KeyError(deviation_id)
            connection.execute("UPDATE route_deviations SET acknowledged_at=?,acknowledged_by=?,reason=?,justification=? WHERE id=?",(now,user,reason,justification,deviation_id));self._event(connection,deviation_id,"ACKNOWLEDGED",now,row["level"],row["current_distance_m"],user,justification,{"reason":reason})
        return self.deviation(deviation_id)

    def close(self,deviation_id:int,user:str,justification:str)->dict[str,Any]:
        now=utc_now()
        with self.repository.connect() as connection:
            row=connection.execute("SELECT * FROM route_deviations WHERE id=?",(deviation_id,)).fetchone()
            if not row:raise KeyError(deviation_id)
            connection.execute("UPDATE route_deviations SET status='MANUALLY_CLOSED',manually_closed_at=? WHERE id=?",(now,deviation_id));self._event(connection,deviation_id,"MANUALLY_CLOSED",now,row["level"],row["current_distance_m"],user,justification)
        return self.deviation(deviation_id)

    def deviation(self,deviation_id:int)->dict[str,Any]:
        with self.repository.connect() as connection:row=connection.execute("SELECT * FROM route_deviations WHERE id=?",(deviation_id,)).fetchone();events=connection.execute("SELECT * FROM route_deviation_events WHERE deviation_id=? ORDER BY occurred_at",(deviation_id,)).fetchall()
        value=self._deviation(row);value["events"]=[dict(event)|{"metadata":json.loads(event["metadata_json"])} for event in events]
        for event in value["events"]:event.pop("metadata_json",None)
        return value

    def path(self,trip_key:str,max_points:int=700)->list[list[dict[str,Any]]]:
        return self.path_diagnostic(trip_key,max_points)["segments"]

    def path_diagnostic(self,trip_key:str,max_points:int=700)->dict[str,Any]:
        raw=self.repository.raw_position_history(trip_key,2000)
        points=[point for point in raw if point["accepted"]]
        outliers=[{"id":point["id"],"recorded_at":point["recorded_at"],
                   "reason":point["rejection_reason"] or "rejected"}
                  for point in raw if not point["accepted"]]
        now=datetime.now(timezone.utc)
        segments:list[list[dict[str,Any]]]=[];current:list[dict[str,Any]]=[]
        for index,point in enumerate(points):
            recorded=datetime.fromisoformat(point["recorded_at"])
            if recorded>now+timedelta(minutes=FUTURE_TOLERANCE_MINUTES):
                outliers.append({"id":point["id"],"recorded_at":point["recorded_at"],"reason":"future_timestamp"})
                continue
            if 0<index<len(points)-1 and self._isolated_jump(points[index-1],point,points[index+1]):
                outliers.append({"id":point["id"],"recorded_at":point["recorded_at"],
                                 "reason":"isolated_geographic_jump"})
                if len(current)>1:segments.append(current)
                current=[]
                continue
            if current:
                previous=current[-1];hours=(datetime.fromisoformat(point["recorded_at"])-datetime.fromisoformat(previous["recorded_at"])).total_seconds()/3600
                distance=haversine((previous["latitude"],previous["longitude"]),(point["latitude"],point["longitude"]))
                if hours<=0 or distance/max(hours,1/3600)>MAX_IMPLIED_SPEED_KMH or (hours>MAX_GAP_HOURS and distance>MAX_GAP_DISTANCE_KM):
                    outliers.append({"id":point["id"],"recorded_at":point["recorded_at"],
                                     "reason":"non_contiguous_segment"})
                    if len(current)>1:segments.append(current)
                    current=[]
            current.append({key:value for key,value in point.items()
                            if key not in {"id","accepted","rejection_reason"}})
        if len(current)>1:segments.append(current)
        total=sum(len(segment) for segment in segments)
        if total>max_points:
            step=max(math.ceil(total/max_points),1)
            segments=[segment[::step]+([segment[-1]] if segment[-1] not in segment[::step] else [])
                      for segment in segments]
        return {"segments":segments,"outliers":outliers,"raw_position_count":len(raw),
                "derived_position_count":sum(len(segment) for segment in segments)}

    @staticmethod
    def _isolated_jump(previous,current,nxt):
        def leg(a,b):
            hours=(datetime.fromisoformat(b["recorded_at"])-datetime.fromisoformat(a["recorded_at"])).total_seconds()/3600
            distance=haversine((a["latitude"],a["longitude"]),(b["latitude"],b["longitude"]))
            return distance/max(hours,1/3600) if hours>0 else float("inf")
        return (leg(previous,current)>MAX_IMPLIED_SPEED_KMH
                and leg(current,nxt)>MAX_IMPLIED_SPEED_KMH
                and leg(previous,nxt)<=MAX_IMPLIED_SPEED_KMH)

    @staticmethod
    def _level(started_at:str,now:str)->str:
        elapsed=(datetime.fromisoformat(now)-datetime.fromisoformat(started_at)).total_seconds()/60
        return "MAXIMUM" if elapsed>=60 else "MODERATE" if elapsed>=30 else "INITIAL"
    @staticmethod
    def _tolerance(geometry,route,point):
        progress,_=route_projection(point,route)
        for item in geometry["segment_tolerances"]:
            if item.get("from_km",0)<=progress<=item.get("to_km",0):return float(item["tolerance_m"])
        return float(geometry["corridor_m"])
    @staticmethod
    def _event(connection,deviation_id,event_type,occurred_at,level,distance,user=None,justification=None,metadata=None):connection.execute("INSERT INTO route_deviation_events(deviation_id,event_type,occurred_at,level,distance_m,user_name,justification,metadata_json) VALUES(?,?,?,?,?,?,?,?)",(deviation_id,event_type,occurred_at,level,distance,user,justification,json.dumps(metadata or {})))
    @staticmethod
    def _deviation(row):
        value=dict(row);value["related_incidents"]=json.loads(value.pop("related_incidents_json"));return value
    @staticmethod
    def _related(latitude,longitude,route_id):
        try:
            from app.services.traffic_monitoring import traffic_repository
            return [item["id"] for item in traffic_repository.incidents(route_id) if haversine((latitude,longitude),(item["latitude"],item["longitude"]))<=10][:5]
        except Exception:return []


route_deviation_service=RouteDeviationService(trip_operations_service.repository)
