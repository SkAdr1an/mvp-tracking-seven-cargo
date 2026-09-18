from __future__ import annotations

import asyncio
import hashlib
import json
import math
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import get_settings
from app.integrations.azure_maps import (AzureMapsAuthError, AzureMapsClient, AzureMapsError,
                                         AzureMapsRateLimitError, AzureMapsUnavailableError,
                                         normalize_azure_incident)
from app.integrations.tomtom import AuthError, RateLimitError, TomTomClient, UnavailableError, UpstreamError
from app.services.route_profiles import BETIM_JABOATAO
from app.services.trip_operations import trip_operations_service
from app.storage.traffic import TrafficRepository, now_utc


ROUTE_GEOMETRIES: dict[str, list[tuple[float, float]]] = {"betim-jaboatao": list(BETIM_JABOATAO.coordinates)}
ICON_CATEGORIES = {1:"ACIDENTE",2:"OUTRO",3:"OUTRO",4:"OUTRO",5:"OUTRO",6:"CONGESTIONAMENTO",7:"INTERDICAO",8:"VIA_FECHADA",9:"OBRA",10:"OUTRO",11:"RISCO_CLIMATICO",14:"OUTRO"}
ORBIS_ICON_CATEGORIES = {"accident":"ACIDENTE","jam":"CONGESTIONAMENTO","laneclosed":"INTERDICAO","roadclosed":"VIA_FECHADA","roadworks":"OBRA","fog":"RISCO_CLIMATICO","rain":"RISCO_CLIMATICO","ice":"RISCO_CLIMATICO","wind":"RISCO_CLIMATICO","flooding":"RISCO_CLIMATICO","dangerousconditions":"RISCO_CLIMATICO"}
INSUFFICIENT_FUNDS_COOLDOWN_SECONDS = 3600
RATE_LIMIT_COOLDOWN_SECONDS = 300
TEMPORARY_ERROR_COOLDOWN_SECONDS = 120
MAX_TRAFFIC_GEOMETRY_POINTS = 5_000
MAX_INCIDENT_GEOMETRY_POINTS = 100


def haversine(a: tuple[float,float], b: tuple[float,float]) -> float:
    radius=6371.0; p1,p2=math.radians(a[0]),math.radians(b[0]); dp=p2-p1; dl=math.radians(b[1]-a[1]); value=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2; return radius*2*math.atan2(math.sqrt(value),math.sqrt(1-value))


def densify(points: list[tuple[float,float]], spacing_km: float) -> list[tuple[float,float]]:
    result=[points[0]]
    for start,end in zip(points,points[1:]):
        distance=haversine(start,end); parts=max(math.ceil(distance/max(spacing_km,1)),1)
        result.extend((start[0]+(end[0]-start[0])*i/parts,start[1]+(end[1]-start[1])*i/parts) for i in range(1,parts+1))
    return result


def bounded_route(
    points: list[tuple[float, float]], max_points: int = MAX_TRAFFIC_GEOMETRY_POINTS
) -> list[tuple[float, float]]:
    """Bound CPU work without mutating or rewriting persisted route geometry."""
    if len(points) <= max_points:
        return points
    step = max(math.ceil((len(points) - 1) / (max_points - 1)), 1)
    sampled = points[::step]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled


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


def incident_geometry_points(incident: dict[str,Any]) -> list[tuple[float,float]]:
    """Return every usable GeoJSON coordinate as (latitude, longitude)."""
    geometry=incident.get("geometry") or {}; coordinates=geometry.get("coordinates") or []
    points: list[tuple[float,float]]=[]
    def visit(value: Any) -> None:
        if isinstance(value,(list,tuple)) and len(value)>=2 and all(isinstance(item,(int,float)) for item in value[:2]):
            points.append((float(value[1]),float(value[0])))
        elif isinstance(value,(list,tuple)):
            for item in value: visit(item)
    visit(coordinates)
    if not points and incident.get("latitude") is not None and incident.get("longitude") is not None:
        points.append((float(incident["latitude"]),float(incident["longitude"])))
    if len(points) > MAX_INCIDENT_GEOMETRY_POINTS:
        step = max(math.ceil((len(points) - 1) / (MAX_INCIDENT_GEOMETRY_POINTS - 1)), 1)
        sampled = points[::step]
        if sampled[-1] != points[-1]: sampled.append(points[-1])
        return sampled
    return points


def incident_route_projection(incident: dict[str,Any], route: list[tuple[float,float]]) -> tuple[float,float]:
    projections=(route_projection(point,route) for point in incident_geometry_points(incident))
    return min(projections,key=lambda value:value[1],default=(0.0,float("inf")))


def remaining_route(route: list[tuple[float,float]], progress_km: float) -> list[tuple[float,float]]:
    if len(route)<2 or progress_km<=0: return route
    cumulative=0.0
    for index,(start,end) in enumerate(zip(route,route[1:])):
        lon_scale=111.0*math.cos(math.radians((start[0]+end[0])/2))
        length=math.hypot((end[1]-start[1])*lon_scale,(end[0]-start[0])*111.0)
        if cumulative+length>=progress_km:
            ratio=min(max((progress_km-cumulative)/length if length else 0,0),1)
            cut=(start[0]+(end[0]-start[0])*ratio,start[1]+(end[1]-start[1])*ratio)
            return [cut,*route[index+1:]]
        cumulative+=length
    return [route[-2],route[-1]]


def normalize_incident(raw: dict[str,Any], route_id: str, ttl_minutes: int) -> dict[str,Any] | None:
    properties=raw.get("properties") or {}; geometry=raw.get("geometry") or {}; point=incident_point(geometry)
    if not point: return None
    raw_icon=properties.get("iconCategory") or 0
    try: icon: int | str=int(raw_icon)
    except (TypeError,ValueError): icon=str(raw_icon)
    magnitude=int(properties.get("magnitudeOfDelay") or 0); events=properties.get("events") or []
    category=(ICON_CATEGORIES.get(icon,"OUTRO") if isinstance(icon,int) else ORBIS_ICON_CATEGORIES.get(icon.lower(),"OUTRO")); description=(events[0].get("description") if events and isinstance(events[0],dict) else None) or properties.get("from") or "Ocorrência de trânsito"
    updated=properties.get("lastReportTime") or now_utc(); expires=properties.get("endTime") or (datetime.now(timezone.utc)+timedelta(minutes=ttl_minutes)).isoformat(); incident_id=str(properties.get("id") or hashlib.sha256(f"{route_id}|{category}|{point[0]:.5f}|{point[1]:.5f}".encode()).hexdigest()[:24])
    severity="CRITICO" if magnitude>=3 or category=="VIA_FECHADA" else "ATENCAO" if magnitude>=1 or category in {"ACIDENTE","OBRA","INTERDICAO","CONGESTIONAMENTO"} else "INFORMATIVO"
    return {"id":f"tomtom:{incident_id}","route_id":route_id,"category":category,"severity":severity,"original_type":str(icon),"source":"TomTom Traffic Incidents","description":str(description)[:300],"road_name":", ".join(properties.get("roadNumbers") or []) or properties.get("from"),"direction":properties.get("to"),"latitude":point[0],"longitude":point[1],"geometry":geometry,"length_m":properties.get("length"),"delay_seconds":properties.get("delay"),"delay_already_in_eta":True,"started_at":properties.get("startTime"),"updated_at":updated,"expires_at":expires,"status":"ACTIVE","manual":False,"information_source":"TomTom","responsible_user":None,"affected_vehicles":[],"provider_payload":{"iconCategory":icon,"magnitudeOfDelay":magnitude,"probabilityOfOccurrence":properties.get("probabilityOfOccurrence")}}


def associate_incident(incident: dict[str,Any], trips: list[dict[str,Any]], route: list[tuple[float,float]], corridor_km: float) -> list[dict[str,Any]]:
    event_progress,event_lateral=incident_route_projection(incident,route)
    if event_lateral>corridor_km: return []
    affected=[]
    for trip in trips:
        position=trip.get("position") or {}; lat=position.get("latitude"); lon=position.get("longitude")
        if lat is None or lon is None: continue
        vehicle_progress,vehicle_lateral=route_projection((lat,lon),route)
        distance=event_progress-vehicle_progress
        if vehicle_lateral<=corridor_km and distance>=0:
            affected.append({"trip_key":(trip.get("operational") or {}).get("trip_key"),"plate":trip.get("plate"),"distance_along_route_km":round(max(distance,0),1),"severity":incident["severity"],"reported_delay_seconds":incident.get("delay_seconds"),"eta_adjustment_applied":False})
    return affected


class TrafficMonitoringService:
    def __init__(self, repository: TrafficRepository, client: TomTomClient | None=None,
                 azure_client: AzureMapsClient | None=None) -> None:
        self.repository=repository; self._tomtom_client_injected=client is not None; self.client=client or TomTomClient(); self.azure_client=azure_client or AzureMapsClient(); self._lock=asyncio.Lock()
        self._cooldown_until=0.0; self._cooldown_status: str | None=None
        self._response_cache: dict[tuple[Any,...],tuple[float,dict[str,Any]]]={}
        try:
            health=self.repository.health().get("tomtom_traffic_incidents") or {}
        except sqlite3.OperationalError:
            # Importing the application must not create or require the runtime database.
            health={}
        if health.get("status")=="INSUFFICIENT_FUNDS" and health.get("checked_at"):
            try:
                checked=datetime.fromisoformat(str(health["checked_at"]).replace("Z","+00:00")); elapsed=(datetime.now(timezone.utc)-checked).total_seconds()
                remaining=INSUFFICIENT_FUNDS_COOLDOWN_SECONDS-elapsed
                if remaining>0: self._cooldown_status="INSUFFICIENT_FUNDS"; self._cooldown_until=time.monotonic()+remaining
            except (TypeError,ValueError):
                pass

    def _active_route_geometries(self) -> tuple[dict[str,list[tuple[float,float]]],list[str]]:
        geometries: dict[str,list[tuple[float,float]]]={}; missing=[]
        for route in self.repository.operations.routes(active_only=True):
            route_id=route["id"]
            with self.repository.operations.connect() as connection:
                row=connection.execute("SELECT geometry_json FROM route_geometry_versions WHERE route_id=? AND active=1 ORDER BY id DESC LIMIT 1",(route_id,)).fetchone()
            points=[]
            if row:
                for point in json.loads(row["geometry_json"]):
                    if isinstance(point,dict) and point.get("latitude") is not None and point.get("longitude") is not None: points.append((float(point["latitude"]),float(point["longitude"])))
                    elif isinstance(point,(list,tuple)) and len(point)>=2: points.append((float(point[0]),float(point[1])))
            if len(points)>=2: geometries[route_id]=points
            else: missing.append(route_id)
        return geometries,missing

    @staticmethod
    def _query_boxes(geometry: list[tuple[float,float]], spacing_km: float, corridor_km: float) -> list[tuple[float,float,float,float]]:
        boxes=[]; seen=set()
        for latitude,longitude in densify(geometry,spacing_km):
            lat_radius=max(spacing_km/2,corridor_km)/111; lon_radius=lat_radius/max(math.cos(math.radians(latitude)),.2)
            bbox=(longitude-lon_radius,latitude-lat_radius,longitude+lon_radius,latitude+lat_radius); key=tuple(round(value,4) for value in bbox)
            if key not in seen: seen.add(key); boxes.append(bbox)
        return boxes

    @staticmethod
    def _failure(exc: Exception) -> tuple[str,int | None,str,int]:
        code=str(getattr(exc,"code","") or type(exc).__name__); http_status=getattr(exc,"status_code",None)
        if code.lower()=="insufficientfunds": return "INSUFFICIENT_FUNDS",http_status,"InsufficientFunds",INSUFFICIENT_FUNDS_COOLDOWN_SECONDS
        if isinstance(exc,RateLimitError): return "RATE_LIMITED",http_status,"RateLimitError",RATE_LIMIT_COOLDOWN_SECONDS
        return "ERROR",http_status,type(exc).__name__,TEMPORARY_ERROR_COOLDOWN_SECONDS

    @staticmethod
    def _azure_failure(exc: AzureMapsError) -> tuple[str,int | None,str]:
        if isinstance(exc,AzureMapsAuthError): return ("NOT_CONFIGURED" if exc.category=="not_configured" else "AUTH_ERROR"),exc.http_status,exc.category
        if isinstance(exc,AzureMapsRateLimitError): return "RATE_LIMITED",exc.http_status,exc.category
        if isinstance(exc,AzureMapsUnavailableError): return "DEGRADED",exc.http_status,exc.category
        return "ERROR",exc.http_status,exc.category

    async def collect(self, trips: list[dict[str,Any]]) -> dict[str,Any]:
        if self._lock.locked(): return {"status":"busy"}
        async with self._lock:
            settings=get_settings(); cycle_started=time.perf_counter(); total_requests=0; total_incidents=0; total_received=0; total_duplicates=0; statuses=[]; providers_used:set[str]=set()
            geometries,missing=self._active_route_geometries()
            for route_id in missing: self.repository.save_snapshot(route_id,"DEGRADED",0,0,None,"route_geometry_unavailable",{"strategy":"persisted_active_geometry"})
            if not geometries:
                self.repository.save_health("tomtom_traffic_incidents","NOT_CONFIGURED",None,None,0,"route_geometry_unavailable"); self.repository.expire()
                return {"status":"NOT_CONFIGURED","request_count":0,"incident_count":0}
            tomtom_available=bool(settings.tomtom_api_key) or self._tomtom_client_injected
            provider="azure" if time.monotonic()<self._cooldown_until or not tomtom_available else "tomtom"
            if provider=="azure" and not settings.azure_maps_subscription_key:
                self.repository.save_health("azure_maps_traffic_incidents","NOT_CONFIGURED",None,None,0,"subscription_key_missing")
                self.repository.expire()
                return {"status":"NOT_CONFIGURED","provider":"azure","request_count":0,"incident_count":0}
            remaining=max(settings.traffic_max_incident_calls_per_cycle,1)
            route_items=list(geometries.items())
            for route_index,(route_id,geometry) in enumerate(route_items):
                geometry=bounded_route(geometry)
                route_trips=[
                    trip for trip in trips
                    if (trip.get("operational") or {}).get("route_id")==route_id
                    and (trip.get("operational") or {}).get("state") not in {
                        "FINALIZADA_NO_SISTEMA", "RETORNO_CONCLUIDO"
                    }
                    and ((trip.get("operational") or {}).get("return_candidate") or {}).get("state")
                    not in {"AGUARDANDO_CONFIRMACAO", "RETORNO_EXTERNO"}
                ]
                if not route_trips:
                    self.repository.expire_irrelevant(route_id)
                    continue
                vehicle_progresses=[]
                for trip in route_trips:
                    position=trip.get("position") or {}
                    if position.get("latitude") is not None and position.get("longitude") is not None:
                        progress,lateral=route_projection((float(position["latitude"]),float(position["longitude"])),geometry)
                        if lateral<=settings.traffic_route_corridor_meters/1000: vehicle_progresses.append(progress)
                if not vehicle_progresses:
                    continue
                query_geometry=remaining_route(geometry,min(vehicle_progresses))
                corridor_km=settings.traffic_route_corridor_meters/1000
                routes_left=len(route_items)-route_index
                route_budget=max(1,remaining//routes_left)
                query_boxes=self._query_boxes(query_geometry,settings.traffic_query_spacing_km,corridor_km)[:route_budget]
                seen: dict[str,dict[str,Any]]={}; started=time.perf_counter(); error=None
                route_requests=0; http_status=None; status="OPERATIONAL"; route_provider=provider; received=0; duplicate_count=0
                for bbox in query_boxes:
                    try:
                        cache_key=(route_provider,*tuple(round(value,4) for value in bbox)); cached=self._response_cache.get(cache_key)
                        if cached and cached[0]>time.monotonic(): payload=cached[1]
                        else:
                            route_requests+=1; total_requests+=1; remaining-=1
                            if route_provider=="azure": payload=await self._retry_azure(lambda: self.azure_client.get_traffic_incidents(bbox))
                            else: payload=await self._retry(lambda: self.client.get_traffic_incidents(bbox))
                            self._response_cache[cache_key]=(time.monotonic()+min(settings.traffic_collector_interval_seconds,60),payload)
                        raw_incidents=payload.get("features") if route_provider=="azure" else payload.get("incidents")
                        for raw in raw_incidents or []:
                            received+=1
                            incident=(normalize_azure_incident(raw,route_id,settings.traffic_incident_default_ttl_minutes) if route_provider=="azure" else normalize_incident(raw,route_id,settings.traffic_incident_default_ttl_minutes))
                            if not incident: continue
                            affected=associate_incident(incident,route_trips,geometry,corridor_km)
                            if affected:
                                incident["affected_vehicles"]=affected
                                if incident["id"] in seen: duplicate_count+=1
                                seen[incident["id"]]=incident
                    except (AuthError,RateLimitError,UnavailableError,UpstreamError) as exc:
                        status,http_status,error,cooldown=self._failure(exc); self._cooldown_status=status; self._cooldown_until=time.monotonic()+cooldown
                        self.repository.save_health("tomtom_traffic_incidents",status,http_status,None,0,error)
                        if settings.azure_maps_subscription_key and not seen and remaining>0:
                            route_provider="azure"; provider="azure"
                            try:
                                route_requests+=1; total_requests+=1; remaining-=1
                                payload=await self._retry_azure(lambda: self.azure_client.get_traffic_incidents(bbox))
                                for raw in payload.get("features") or []:
                                    received+=1; incident=normalize_azure_incident(raw,route_id,settings.traffic_incident_default_ttl_minutes)
                                    if not incident: continue
                                    affected=associate_incident(incident,route_trips,geometry,corridor_km)
                                    if affected:
                                        incident["affected_vehicles"]=affected
                                        if incident["id"] in seen: duplicate_count+=1
                                        seen[incident["id"]]=incident
                                status="OPERATIONAL"; error=None; http_status=200
                                continue
                            except AzureMapsError as azure_exc:
                                status,http_status,error=self._azure_failure(azure_exc)
                        break
                    except AzureMapsError as exc:
                        status,http_status,error=self._azure_failure(exc); break
                for incident in seen.values(): self.repository.upsert_incident(incident)
                if status=="OPERATIONAL":
                    source="Azure Maps Traffic Incidents" if route_provider=="azure" else "TomTom Traffic Incidents"
                    self.repository.expire_irrelevant(route_id,source,set(seen))
                total_incidents+=len(seen); total_received+=received; total_duplicates+=duplicate_count; providers_used.add(route_provider); statuses.append(status); latency=round((time.perf_counter()-started)*1000); self.repository.save_snapshot(route_id,status,route_requests,len(seen),latency,error,{"strategy":"persisted_route_bbox_segments","corridor_m":settings.traffic_route_corridor_meters,"provider":route_provider,"received":received,"duplicates":duplicate_count,"bbox_count":len(query_boxes)}); health_provider="azure_maps_traffic_incidents" if route_provider=="azure" else "tomtom_traffic_incidents"; self.repository.save_health(health_provider,status,200 if not error else http_status,latency,len(seen),"ok" if not error else error)
                if error or remaining<=0: break
            self.repository.expire(); final=next((value for value in ("AUTH_ERROR","RATE_LIMITED","ERROR","DEGRADED","NOT_CONFIGURED","INSUFFICIENT_FUNDS") if value in statuses),"OPERATIONAL")
            if "azure" in providers_used:
                self.repository.save_health("azure_maps_traffic_incidents",final,200 if final=="OPERATIONAL" else None,round((time.perf_counter()-cycle_started)*1000),total_incidents,"ok" if final=="OPERATIONAL" else final)
            return {"status":final,"provider":provider,"request_count":total_requests,"received_count":total_received,"duplicate_count":total_duplicates,"incident_count":total_incidents}

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

    async def _retry_azure(self, call):
        for attempt in range(2):
            try: return await call()
            except AzureMapsUnavailableError:
                if attempt: raise
                await asyncio.sleep(.25)

    def create_manual(self, data: dict[str,Any]) -> dict[str,Any]:
        now=now_utc(); incident={**data,"id":f"manual:{uuid.uuid4()}","original_type":data["category"],"source":"Operação manual","geometry":{"type":"Point","coordinates":[data["longitude"],data["latitude"]]},"length_m":None,"delay_seconds":None,"delay_already_in_eta":False,"updated_at":now,"status":"ACTIVE","manual":True,"affected_vehicles":[],"provider_payload":{},"created_at":now}
        route=ROUTE_GEOMETRIES.get(data["route_id"]); trips=[]
        if route: incident["affected_vehicles"]=associate_incident(incident,trips,route,get_settings().traffic_route_corridor_meters/1000)
        self.repository.upsert_incident(incident); self.repository.update_manual(incident["id"],{"status":"ACTIVE"},"CREATED",data["responsible_user"],data["justification"]); return self.repository.incident(incident["id"]) or incident


traffic_repository=TrafficRepository(trip_operations_service.repository)
traffic_monitoring_service=TrafficMonitoringService(traffic_repository)
