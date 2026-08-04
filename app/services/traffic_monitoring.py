from __future__ import annotations

import asyncio
import hashlib
import math
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import get_settings
from app.integrations.tomtom import AuthError, RateLimitError, TomTomClient, UnavailableError, UpstreamError
from app.services.route_profiles import BETIM_JABOATAO
from app.services.trip_operations import trip_operations_service
from app.storage.traffic import TrafficRepository, now_utc


ROUTE_GEOMETRIES: dict[str, list[tuple[float, float]]] = {"betim-jaboatao": list(BETIM_JABOATAO.coordinates)}
ICON_CATEGORIES = {1:"ACIDENTE",2:"OUTRO",3:"OUTRO",4:"OUTRO",5:"OUTRO",6:"CONGESTIONAMENTO",7:"INTERDICAO",8:"VIA_FECHADA",9:"OBRA",10:"OUTRO",11:"RISCO_CLIMATICO",14:"OUTRO"}


def haversine(a: tuple[float,float], b: tuple[float,float]) -> float:
    radius=6371.0; p1,p2=math.radians(a[0]),math.radians(b[0]); dp=p2-p1; dl=math.radians(b[1]-a[1]); value=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2; return radius*2*math.atan2(math.sqrt(value),math.sqrt(1-value))


def densify(points: list[tuple[float,float]], spacing_km: float) -> list[tuple[float,float]]:
    result=[points[0]]
    for start,end in zip(points,points[1:]):
        distance=haversine(start,end); parts=max(math.ceil(distance/max(spacing_km,1)),1)
        result.extend((start[0]+(end[0]-start[0])*i/parts,start[1]+(end[1]-start[1])*i/parts) for i in range(1,parts+1))
    return result


def route_projection(point: tuple[float,float], route: list[tuple[float,float]]) -> tuple[float,float]:
    """Retorna progresso e distância lateral aproximados, ambos em km."""
    best=(0.0,float("inf")); cumulative=0.0; lat_scale=111.0
    for a,b in zip(route,route[1:]):
        lon_scale=111.0*math.cos(math.radians((a[0]+b[0])/2)); vx=(b[1]-a[1])*lon_scale; vy=(b[0]-a[0])*lat_scale; wx=(point[1]-a[1])*lon_scale; wy=(point[0]-a[0])*lat_scale; length2=vx*vx+vy*vy; t=max(0,min(1,(wx*vx+wy*vy)/length2)) if length2 else 0; lateral=math.hypot(wx-t*vx,wy-t*vy); segment=math.sqrt(length2)
        if lateral<best[1]: best=(cumulative+t*segment,lateral)
        cumulative+=segment
    return best


def incident_point(geometry: dict[str,Any]) -> tuple[float,float] | None:
    coords=geometry.get("coordinates") or []
    if geometry.get("type")=="Point" and len(coords)>=2: return float(coords[1]),float(coords[0])
    if coords and isinstance(coords[0],list):
        middle=coords[len(coords)//2]; return (float(middle[1]),float(middle[0])) if len(middle)>=2 else None
    return None


def normalize_incident(raw: dict[str,Any], route_id: str, ttl_minutes: int) -> dict[str,Any] | None:
    properties=raw.get("properties") or {}; geometry=raw.get("geometry") or {}; point=incident_point(geometry)
    if not point: return None
    icon=int(properties.get("iconCategory") or 0); magnitude=int(properties.get("magnitudeOfDelay") or 0); events=properties.get("events") or []
    category=ICON_CATEGORIES.get(icon,"OUTRO"); description=(events[0].get("description") if events and isinstance(events[0],dict) else None) or properties.get("from") or "Ocorrência de trânsito"
    updated=properties.get("lastReportTime") or now_utc(); expires=properties.get("endTime") or (datetime.now(timezone.utc)+timedelta(minutes=ttl_minutes)).isoformat(); incident_id=str(properties.get("id") or hashlib.sha256(f"{route_id}|{category}|{point[0]:.5f}|{point[1]:.5f}".encode()).hexdigest()[:24])
    severity="CRITICO" if magnitude>=3 or category=="VIA_FECHADA" else "ATENCAO" if magnitude>=1 or category in {"ACIDENTE","OBRA","INTERDICAO","CONGESTIONAMENTO"} else "INFORMATIVO"
    return {"id":f"tomtom:{incident_id}","route_id":route_id,"category":category,"severity":severity,"original_type":str(icon),"source":"TomTom Traffic Incidents","description":str(description)[:300],"road_name":", ".join(properties.get("roadNumbers") or []) or properties.get("from"),"direction":properties.get("to"),"latitude":point[0],"longitude":point[1],"geometry":geometry,"length_m":properties.get("length"),"delay_seconds":properties.get("delay"),"delay_already_in_eta":True,"started_at":properties.get("startTime"),"updated_at":updated,"expires_at":expires,"status":"ACTIVE","manual":False,"information_source":"TomTom","responsible_user":None,"affected_vehicles":[],"provider_payload":{"iconCategory":icon,"magnitudeOfDelay":magnitude,"probabilityOfOccurrence":properties.get("probabilityOfOccurrence")}}


def associate_incident(incident: dict[str,Any], trips: list[dict[str,Any]], route: list[tuple[float,float]], corridor_km: float) -> list[dict[str,Any]]:
    event_progress,event_lateral=route_projection((incident["latitude"],incident["longitude"]),route)
    if event_lateral>corridor_km: return []
    affected=[]
    for trip in trips:
        position=trip.get("position") or {}; lat=position.get("latitude"); lon=position.get("longitude")
        if lat is None or lon is None: continue
        vehicle_progress,vehicle_lateral=route_projection((lat,lon),route)
        distance=event_progress-vehicle_progress
        if vehicle_lateral<=corridor_km and distance>=-1:
            affected.append({"trip_key":(trip.get("operational") or {}).get("trip_key"),"plate":trip.get("plate"),"distance_along_route_km":round(max(distance,0),1),"severity":incident["severity"],"reported_delay_seconds":incident.get("delay_seconds"),"eta_adjustment_applied":False})
    return affected


class TrafficMonitoringService:
    def __init__(self, repository: TrafficRepository, client: TomTomClient | None=None) -> None:
        self.repository=repository; self.client=client or TomTomClient(); self._lock=asyncio.Lock()

    async def collect(self, trips: list[dict[str,Any]]) -> dict[str,Any]:
        if self._lock.locked(): return {"status":"busy"}
        async with self._lock:
            settings=get_settings(); total_requests=0; total_incidents=0; statuses=[]
            for route_id,geometry in ROUTE_GEOMETRIES.items():
                route_trips=[
                    trip for trip in trips
                    if (trip.get("operational") or {}).get("route_id")==route_id
                    and (trip.get("operational") or {}).get("state") not in {
                        "FINALIZADA_NO_SISTEMA", "RETORNO_CONCLUIDO"
                    }
                    and ((trip.get("operational") or {}).get("return_candidate") or {}).get("state")
                    not in {"AGUARDANDO_CONFIRMACAO", "RETORNO_EXTERNO"}
                ]
                if not route_trips: continue
                samples=densify(geometry,settings.traffic_query_spacing_km); progress=[route_projection(((trip.get("position") or {}).get("latitude",999),(trip.get("position") or {}).get("longitude",999)),geometry)[0] for trip in route_trips]
                ranked=[]
                for point in samples:
                    point_progress=route_projection(point,geometry)[0]
                    distances=[point_progress-position for position in progress if -20<=point_progress-position<=settings.traffic_lookahead_km]
                    if distances: ranked.append((min(abs(distance) for distance in distances),point))
                query_points=[point for _,point in sorted(ranked,key=lambda item:item[0])[:max(settings.traffic_max_incident_calls_per_cycle,1)]]
                seen: dict[str,dict[str,Any]]={}; started=time.perf_counter(); error=None
                for point in query_points:
                    lat_radius=max(settings.traffic_query_spacing_km/2,settings.traffic_corridor_km)/111; lon_radius=lat_radius/max(math.cos(math.radians(point[0])),.2); bbox=(point[1]-lon_radius,point[0]-lat_radius,point[1]+lon_radius,point[0]+lat_radius)
                    try:
                        payload=await self._retry(lambda: self.client.get_traffic_incidents(bbox)); total_requests+=1
                        for raw in payload.get("incidents") or []:
                            incident=normalize_incident(raw,route_id,settings.traffic_incident_default_ttl_minutes)
                            if not incident: continue
                            _,lateral=route_projection((incident["latitude"],incident["longitude"]),geometry)
                            if lateral<=settings.traffic_corridor_km: seen[incident["id"]]=incident
                    except (AuthError,RateLimitError,UnavailableError,UpstreamError) as exc:
                        error=type(exc).__name__; statuses.append("DEGRADED"); break
                for incident in seen.values(): incident["affected_vehicles"]=associate_incident(incident,route_trips,geometry,settings.traffic_corridor_km); self.repository.upsert_incident(incident)
                total_incidents+=len(seen); status="OPERATIONAL" if not error else "DEGRADED"; statuses.append(status); latency=round((time.perf_counter()-started)*1000); self.repository.save_snapshot(route_id,status,len(query_points),len(seen),latency,error,{"strategy":"vehicle_lookahead_corridor","corridor_km":settings.traffic_corridor_km}); self.repository.save_health("tomtom_traffic_incidents",status,200 if not error else None,latency,len(seen),"ok" if not error else error)
            self.repository.expire(); return {"status":"DEGRADED" if "DEGRADED" in statuses else "OPERATIONAL","request_count":total_requests,"incident_count":total_incidents}

    async def validate_flow(self, latitude: float, longitude: float) -> dict[str,Any]:
        try:
            payload=await self.client.get_flow_segment(latitude,longitude); telemetry=payload.get("_telemetry") or {}; count=int(bool(payload.get("flowSegmentData"))); self.repository.save_health("tomtom_traffic_flow","OPERATIONAL",200,telemetry.get("latency_ms"),count,"ok"); return {"status":"OPERATIONAL","result_count":count,**telemetry}
        except (AuthError,RateLimitError,UnavailableError,UpstreamError) as exc:
            self.repository.save_health("tomtom_traffic_flow","UNAVAILABLE",getattr(exc,"status_code",None),None,0,type(exc).__name__); return {"status":"UNAVAILABLE","result_count":0,"message":type(exc).__name__}

    async def _retry(self, call):
        for attempt in range(2):
            try: return await call()
            except (UnavailableError,RateLimitError):
                if attempt: raise
                await asyncio.sleep(.25)

    def create_manual(self, data: dict[str,Any]) -> dict[str,Any]:
        now=now_utc(); incident={**data,"id":f"manual:{uuid.uuid4()}","original_type":data["category"],"source":"Operação manual","geometry":{"type":"Point","coordinates":[data["longitude"],data["latitude"]]},"length_m":None,"delay_seconds":None,"delay_already_in_eta":False,"updated_at":now,"status":"ACTIVE","manual":True,"affected_vehicles":[],"provider_payload":{},"created_at":now}
        route=ROUTE_GEOMETRIES.get(data["route_id"]); trips=[]
        if route: incident["affected_vehicles"]=associate_incident(incident,trips,route,get_settings().traffic_corridor_km)
        self.repository.upsert_incident(incident); self.repository.update_manual(incident["id"],{"status":"ACTIVE"},"CREATED",data["responsible_user"],data["justification"]); return self.repository.incident(incident["id"]) or incident


traffic_repository=TrafficRepository(trip_operations_service.repository)
traffic_monitoring_service=TrafficMonitoringService(traffic_repository)
