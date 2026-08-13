from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.route_deviation import route_deviation_service
from app.services.trip_operations import trip_operations_service
from app.storage.operations import utc_now
from app.core.security import Permission, Principal, require_permission

router = APIRouter(tags=["route-monitoring"])


class AcknowledgeRequest(BaseModel):
    user: str = Field(min_length=2, max_length=100)
    reason: Literal["TRAFFIC", "WEATHER", "OPERATIONAL", "SECURITY", "OTHER"]
    justification: str = Field(min_length=5, max_length=500)


class CloseRequest(BaseModel):
    user: str = Field(min_length=2, max_length=100)
    justification: str = Field(min_length=5, max_length=500)
    confirmed: bool


class DriverAssociationRequest(BaseModel):
    action: Literal["correct", "remove"]
    confirmed: bool
    operator: str = Field(min_length=2, max_length=100)
    justification: str = Field(min_length=5, max_length=500)
    new_driver: str | None = Field(default=None, max_length=150)


@router.get("/routes/{route_id}/geometry", dependencies=[Depends(require_permission(Permission.TRIPS_READ))])
async def route_geometry(route_id: str, max_points: int = Query(default=1800, ge=100, le=5000)):
    value = route_deviation_service.geometry(route_id)
    if not value:
        raise HTTPException(404, "Geometria operacional não encontrada")
    full = value["geometry"]
    step = max((len(full) + max_points - 1) // max_points, 1)
    value["point_count"] = len(full)
    value["geometry"] = full[::step] + ([full[-1]] if full[-1] not in full[::step] else [])
    return value


@router.get("/routes/{route_id}/paths", dependencies=[Depends(require_permission(Permission.TRIPS_READ))])
async def route_paths(route_id: str, max_points_per_trip: int = Query(default=700, ge=20, le=1500)):
    trips = [trip for trip in trip_operations_service.repository.trips() if trip.get("route_id") == route_id]
    active = {item["trip_key"]: item for item in route_deviation_service.active()}
    paths = []
    for trip in trips:
        diagnostic = route_deviation_service.path_diagnostic(trip["trip_key"], max_points_per_trip)
        paths.append({"trip_key": trip["trip_key"], "plate": trip["plate"], "route_id": route_id,
                      **diagnostic, "deviation": active.get(trip["trip_key"])})
    return {"paths": paths}


@router.get("/routes/paths", dependencies=[Depends(require_permission(Permission.TRIPS_READ))])
async def all_route_paths(max_points_per_trip: int = Query(default=700, ge=20, le=1500)):
    active = {item["trip_key"]: item for item in route_deviation_service.active()}
    paths = []
    for trip in trip_operations_service.repository.trips():
        diagnostic = route_deviation_service.path_diagnostic(trip["trip_key"], max_points_per_trip)
        if not diagnostic["segments"] and not diagnostic["outliers"]:
            continue
        paths.append({"trip_key": trip["trip_key"], "plate": trip["plate"],
                      "route_id": trip.get("route_id"), **diagnostic,
                      "deviation": active.get(trip["trip_key"])})
    return {"paths": paths}


@router.get("/deviations/active", dependencies=[Depends(require_permission(Permission.INCIDENTS_READ))])
async def active_deviations():
    return {"deviations": route_deviation_service.active()}


@router.get("/deviations/trips/{trip_key}", dependencies=[Depends(require_permission(Permission.INCIDENTS_READ))])
async def deviation_history(trip_key: str):
    return {"deviations": route_deviation_service.history(trip_key)}


@router.post("/deviations/{deviation_id}/acknowledge")
async def acknowledge(
    deviation_id: int,
    payload: AcknowledgeRequest,
    principal: Principal = Depends(require_permission(Permission.INCIDENTS_EDIT_STRUCTURAL)),
):
    try:
        return route_deviation_service.acknowledge(
            deviation_id, principal.username, payload.reason, payload.justification
        )
    except KeyError as exc:
        raise HTTPException(404, "Desvio não encontrado") from exc


@router.post("/deviations/{deviation_id}/close")
async def close(
    deviation_id: int,
    payload: CloseRequest,
    principal: Principal = Depends(require_permission(Permission.INCIDENTS_EDIT_STRUCTURAL)),
):
    if not payload.confirmed:
        raise HTTPException(422, "Confirmação explícita obrigatória")
    try:
        return route_deviation_service.close(deviation_id, principal.username, payload.justification)
    except KeyError as exc:
        raise HTTPException(404, "Desvio não encontrado") from exc


@router.post("/operations/trips/{trip_key}/driver-association")
async def change_driver_association(
    trip_key: str,
    payload: DriverAssociationRequest,
    principal: Principal = Depends(require_permission(Permission.TRIPS_ASSIGN_DRIVER)),
):
    if not payload.confirmed:
        raise HTTPException(422, "Confirmação explícita obrigatória")
    trip = trip_operations_service.repository.trip(trip_key)
    if not trip:
        raise HTTPException(404, "Viagem operacional não encontrada")
    if payload.action == "correct" and not (payload.new_driver or "").strip():
        raise HTTPException(422, "Informe o motorista correto")
    previous = trip.get("current_driver")
    current = payload.new_driver.strip() if payload.action == "correct" and payload.new_driver else None
    updated = trip_operations_service.repository.update_trip(
        trip_key, previous_driver=previous, current_driver=current,
        driver_source="manual:audited_correction", driver_divergence=0, driver_updated_at=utc_now(),
    )
    trip_operations_service.repository.add_event(
        trip_key, "DRIVER_ASSOCIATION_CORRECTED" if current else "DRIVER_ASSOCIATION_REMOVED",
        utc_now(), "operator", "Associação de motorista alterada com confirmação explícita",
        metadata={"previous_driver": previous, "current_driver": current},
        justification=payload.justification, operator=principal.username,
    )
    return updated
