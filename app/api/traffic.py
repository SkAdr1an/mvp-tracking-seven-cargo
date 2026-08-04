from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from app.services.traffic_monitoring import ROUTE_GEOMETRIES, traffic_monitoring_service, traffic_repository
from app.services.route_deviation import route_deviation_service


router=APIRouter(prefix="/traffic",tags=["traffic"])


class ManualIncidentRequest(BaseModel):
    route_id: str
    category: Literal["ACIDENTE","CONGESTIONAMENTO","TRANSITO_LENTO","OBRA","INTERDICAO","VIA_FECHADA","RISCO_CLIMATICO","OCORRENCIA_MANUAL","OUTRO"] = "OCORRENCIA_MANUAL"
    description: str = Field(min_length=5,max_length=500)
    latitude: float = Field(ge=-90,le=90)
    longitude: float = Field(ge=-180,le=180)
    direction: str | None=None
    severity: Literal["INFORMATIVO","ATENCAO","CRITICO"]="ATENCAO"
    started_at: str
    expires_at: str
    information_source: str = Field(min_length=3,max_length=200)
    responsible_user: str = Field(min_length=2,max_length=100)
    justification: str = Field(min_length=5,max_length=500)
    road_name: str | None=None

    @model_validator(mode="after")
    def validate_expiration(self):
        start=datetime.fromisoformat(self.started_at.replace("Z","+00:00")); end=datetime.fromisoformat(self.expires_at.replace("Z","+00:00"))
        if start.tzinfo is None or end.tzinfo is None: raise ValueError("Horários devem conter timezone")
        if end<=start: raise ValueError("A expiração deve ser posterior ao início")
        return self


class ManualUpdateRequest(BaseModel):
    changes: dict[str,Any]=Field(default_factory=dict)
    action: Literal["EDITED","CONFIRMED","CLOSED","DISCARDED"]
    justification: str=Field(min_length=5,max_length=500)
    user: str=Field(min_length=2,max_length=100)


@router.get("/incidents")
async def incidents(route_id: str|None=None,bbox: str|None=None,include_inactive: bool=False):
    parsed=None
    if bbox:
        try: parsed=tuple(float(value) for value in bbox.split(","))
        except ValueError as exc: raise HTTPException(422,"bbox inválido") from exc
        if len(parsed)!=4: raise HTTPException(422,"bbox deve conter quatro valores")
    values=traffic_repository.incidents(route_id,parsed,include_inactive)
    counts={key:0 for key in ("ACIDENTE","OBRA_INTERDICAO","TRECHO_LENTO","RISCO_CLIMATICO","MANUAL")}
    for item in values:
        if item["category"]=="ACIDENTE": counts["ACIDENTE"]+=1
        if item["category"] in {"OBRA","INTERDICAO","VIA_FECHADA"}: counts["OBRA_INTERDICAO"]+=1
        if item["category"] in {"CONGESTIONAMENTO","TRANSITO_LENTO"}: counts["TRECHO_LENTO"]+=1
        if item["category"]=="RISCO_CLIMATICO": counts["RISCO_CLIMATICO"]+=1
        if item["manual"]: counts["MANUAL"]+=1
    snapshot=traffic_repository.latest_snapshot(route_id)
    routes=[]
    for route in traffic_repository.operations.routes(active_only=True):
        official = route_deviation_service.geometry(route["id"])
        points = official["geometry"] if official else [{"latitude":lat,"longitude":lon} for lat,lon in ROUTE_GEOMETRIES.get(route["id"],[])]
        if len(points) > 1800:
            step = (len(points) + 1799) // 1800
            points = points[::step] + ([points[-1]] if points[-1] not in points[::step] else [])
        routes.append({
            **route,"geometry":points,
            "geometry_version": official.get("version") if official else None,
            "geometry_source": official.get("source") if official else None,
            "geometry_provider": official.get("provider") if official else None,
            "distance_m": official.get("distance_m") if official else None,
            "duration_seconds": official.get("duration_seconds") if official else None,
        })
    return {"incidents":values,"counts":counts,"snapshot":snapshot,"routes":routes,"generated_at":datetime.now(timezone.utc).isoformat()}


@router.get("/incidents/{incident_id}")
async def incident_detail(incident_id: str):
    value=traffic_repository.incident(incident_id)
    if not value: raise HTTPException(404,"Ocorrência não encontrada")
    return value


@router.get("/incidents/{incident_id}/vehicles")
async def affected_vehicles(incident_id: str):
    value=traffic_repository.incident(incident_id)
    if not value: raise HTTPException(404,"Ocorrência não encontrada")
    return {"incident_id":incident_id,"vehicles":value["affected_vehicles"]}


@router.post("/manual",status_code=201)
async def create_manual(payload: ManualIncidentRequest):
    if not traffic_monitoring_service.repository.operations.route(payload.route_id): raise HTTPException(404,"Rota não encontrada")
    return traffic_monitoring_service.create_manual(payload.model_dump())


@router.patch("/manual/{incident_id}")
async def update_manual(incident_id: str,payload: ManualUpdateRequest):
    changes=dict(payload.changes)
    if payload.action=="CONFIRMED": changes["status"]="CONFIRMED"
    elif payload.action=="CLOSED": changes["status"]="CLOSED"
    elif payload.action=="DISCARDED": changes["status"]="DISCARDED"
    try: return traffic_repository.update_manual(incident_id,changes,payload.action,payload.user,payload.justification)
    except KeyError as exc: raise HTTPException(404,"Ocorrência não encontrada") from exc
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc


@router.get("/health")
async def traffic_health():
    health=traffic_repository.health(); states=[value["status"] for value in health.values()]
    overall="OPERATIONAL" if states and all(state=="OPERATIONAL" for state in states) else "PARTIAL" if "OPERATIONAL" in states else "UNAVAILABLE" if states else "DEGRADED"
    return {"status":overall,"services":health}
