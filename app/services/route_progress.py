from __future__ import annotations

import math
import json
from datetime import datetime, timezone
from typing import Any

from app.services.route_deviation import route_deviation_service
from app.storage.operations import OperationsRepository


class RouteProgressService:
    def __init__(self, repository: OperationsRepository):
        self.repository=repository;self._cache:dict[str,tuple[str,list[tuple[float,float]],list[float]]]={}

    def calculate(self,trip_key:str,route_id:str|None,latitude:float,longitude:float,speed_kmh:float|None,position_at:str|None,stale:bool)->dict[str,Any]|None:
        if not route_id:return None
        prepared=self._prepared(route_id)
        if not prepared:return self._fallback(trip_key,"geometry_unavailable",position_at,speed_kmh)
        version,points,cumulative=prepared;previous=self.repository.route_progress(trip_key);total=cumulative[-1]
        advanced,lateral=self._project(latitude,longitude,points,cumulative,previous)
        # Oscilação de GPS não reduz o avanço. Um retorno relevante exige duas posições
        # recentes coerentes abaixo do último marco para ser aceito.
        if previous and advanced<previous["advanced_distance_km"]:
            drop=previous["advanced_distance_km"]-advanced
            if drop<2 or not self._confirmed_return(trip_key,points,cumulative,advanced):advanced=previous["advanced_distance_km"]
        advanced=max(0,min(advanced,total));remaining=max(total-advanced,0)
        route = self.repository.route(route_id)
        destination_distance = None
        if route:
            destination_distance = self._distance(
                (latitude, longitude),
                (float(route["destination_latitude"]), float(route["destination_longitude"])),
            )
            # A projection can snap to a late/crossing segment even while the
            # vehicle is clearly far from the destination. Direct distance is a
            # conservative lower bound for the remaining route in that case.
            if destination_distance * 1000 > float(route["destination_radius_m"]):
                remaining = max(remaining, destination_distance)
                guarded_advanced = min(advanced, max(total - remaining, 0))
                prior_advanced = float(previous["advanced_distance_km"]) if previous else None
                if (
                    prior_advanced is not None
                    and 0 < prior_advanced - guarded_advanced < 2
                    and prior_advanced < total - 0.1
                ):
                    advanced = prior_advanced
                else:
                    advanced = guarded_advanced
        progress=max(0,min(advanced/total*100 if total else 0,100))
        geometry=self._geometry(route_id);corridor=float((geometry or {}).get("corridor_m",300));outside=lateral*1000>corridor
        route_state="STALE" if stale else "OUTSIDE" if outside else "ON_ROUTE"
        confidence="LOW" if stale else "MEDIUM" if outside else "HIGH"
        speed_state="STALE" if stale else "UNAVAILABLE" if speed_kmh is None else "CURRENT"
        value={"trip_key":trip_key,"route_id":route_id,"geometry_version":version,"total_distance_km":round(total,1),"advanced_distance_km":round(advanced,1),"remaining_distance_km":round(remaining,1),"progress_percent":round(progress,1),"return_distance_km":round(lateral,1) if outside else None,"route_state":route_state,"confidence":confidence,"position_at":position_at,"speed_kmh":None if stale else speed_kmh,"speed_state":speed_state}
        reliable=not stale and confidence in {"HIGH","MEDIUM"}
        value["last_reliable"]=value.copy() if reliable else (previous or {}).get("last_reliable")
        if stale and value["last_reliable"]:
            for key in ("total_distance_km","advanced_distance_km","remaining_distance_km","progress_percent","return_distance_km","geometry_version"):value[key]=value["last_reliable"].get(key,value[key])
        return self.repository.save_route_progress(value)

    def _prepared(self,route_id):
        geometry=self._geometry(route_id)
        if not geometry:return None
        cached=self._cache.get(route_id)
        if cached and cached[0]==geometry["version"]:return cached
        points=[(float(item["latitude"]),float(item["longitude"])) for item in geometry["geometry"]];cumulative=[0.0]
        for a,b in zip(points,points[1:]):cumulative.append(cumulative[-1]+self._distance(a,b))
        result=(geometry["version"],points,cumulative);self._cache[route_id]=result;return result

    def _geometry(self,route_id):
        with self.repository.connect() as connection:row=connection.execute("SELECT version,geometry_json,corridor_m FROM route_geometry_versions WHERE route_id=? AND active=1 ORDER BY id DESC LIMIT 1",(route_id,)).fetchone()
        return {"version":row["version"],"geometry":json.loads(row["geometry_json"]),"corridor_m":row["corridor_m"]} if row else None

    def _project(self,latitude,longitude,points,cumulative,previous):
        best=(0.0,float("inf"));start=0;end=len(points)-1
        if previous:
            prior=float(previous["advanced_distance_km"]);start=max(self._index(cumulative,prior-15)-5,0);end=min(self._index(cumulative,prior+350)+5,len(points)-1)
        for index in range(start,end):
            a,b=points[index],points[index+1];lat_scale=111.0;lon_scale=111.0*math.cos(math.radians((a[0]+b[0]+latitude)/3));vx=(b[1]-a[1])*lon_scale;vy=(b[0]-a[0])*lat_scale;wx=(longitude-a[1])*lon_scale;wy=(latitude-a[0])*lat_scale;length2=vx*vx+vy*vy;t=max(0,min(1,(wx*vx+wy*vy)/length2)) if length2 else 0;lateral=math.hypot(wx-t*vx,wy-t*vy);advanced=cumulative[index]+t*(cumulative[index+1]-cumulative[index])
            if lateral<best[1]:best=(advanced,lateral)
        return best

    def _confirmed_return(self,trip_key,points,cumulative,current):
        history=self.repository.position_history(trip_key,3)
        if len(history)<2:return False
        projections=[self._project(item["latitude"],item["longitude"],points,cumulative,None)[0] for item in history[-2:]]
        return all(value<=current+2 for value in projections)
    @staticmethod
    def _index(values,target):
        lo,hi=0,len(values)-1
        while lo<hi:
            mid=(lo+hi)//2
            if values[mid]<target:lo=mid+1
            else:hi=mid
        return lo
    @staticmethod
    def _distance(a,b):
        radius=6371;lat1,lat2=map(math.radians,(a[0],b[0]));dlat=lat2-lat1;dlon=math.radians(b[1]-a[1]);x=math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2;return radius*2*math.atan2(math.sqrt(x),math.sqrt(1-x))
    def _fallback(self,trip_key,reason,position_at,speed):
        previous=self.repository.route_progress(trip_key)
        if not previous:return {"confidence":"UNAVAILABLE","reason":reason,"position_at":position_at,"speed_kmh":speed,"speed_state":"UNAVAILABLE"}
        previous.update(confidence="LOW",route_state="STALE",reason=reason,speed_kmh=None,speed_state="STALE");return previous


route_progress_service=RouteProgressService(route_deviation_service.repository)
