from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.security import require_panel_session
from app.services.trip_operations import trip_operations_service


router = APIRouter(prefix="/operations", tags=["operations"])


class ManualActionRequest(BaseModel):
    action: Literal["finalize", "reopen", "undo_detection", "correct_times"]
    justification: str = Field(min_length=5, max_length=500)
    operator: str = Field(default="operator", min_length=2, max_length=100)
    corrections: dict[str, str | None] = Field(default_factory=dict)


class RouteAssignmentRequest(BaseModel):
    route_id: str = Field(min_length=1, max_length=100)


class ReturnDecisionRequest(BaseModel):
    decision: Literal["YES", "NO", "LATER"]
    operator: str = Field(default="operator", min_length=2, max_length=100)
    justification: str | None = Field(default=None, max_length=500)


@router.get("/routes")
async def list_routes(active_only: bool = Query(default=False)) -> dict[str, Any]:
    return {"routes": trip_operations_service.repository.routes(active_only=active_only)}


@router.get("/trips/{trip_key}")
async def trip_detail(trip_key: str) -> dict[str, Any]:
    detail = trip_operations_service.detail(trip_key)
    if detail is None:
        raise HTTPException(status_code=404, detail="Viagem operacional não encontrada")
    return detail


@router.get("/diagnostics/{trip_key}")
async def trip_diagnostic(trip_key: str) -> dict[str, Any]:
    value = trip_operations_service.repository.diagnostic(trip_key)
    if value is None:
        raise HTTPException(status_code=404, detail="Diagnóstico operacional não disponível")
    return value


@router.post("/trips/{trip_key}/actions")
async def manual_action(
    trip_key: str,
    payload: ManualActionRequest,
    _operator: str = Depends(require_panel_session),
) -> dict[str, Any]:
    try:
        trip_operations_service.manual_action(
            trip_key, payload.action, payload.justification, payload.operator, payload.corrections
        )
        return trip_operations_service.detail(trip_key) or {}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Viagem operacional não encontrada") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/trips/{trip_key}/route")
async def assign_route(trip_key: str, payload: RouteAssignmentRequest) -> dict[str, Any]:
    route = trip_operations_service.repository.route(payload.route_id)
    if not route or not route["active"]:
        raise HTTPException(status_code=404, detail="Rota ativa não encontrada")
    try:
        trip_operations_service.repository.update_trip(trip_key, route_id=payload.route_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Viagem operacional não encontrada") from exc
    return trip_operations_service.detail(trip_key) or {}


@router.post("/return-candidates/{candidate_id}/decision")
async def decide_return(candidate_id: int, payload: ReturnDecisionRequest) -> dict[str, Any]:
    if payload.decision in {"YES", "NO"} and len((payload.justification or "").strip()) < 5:
        raise HTTPException(status_code=422, detail="Informe uma justificativa com pelo menos 5 caracteres")
    try:
        candidate = trip_operations_service.return_tracking.decide(
            candidate_id, payload.decision, payload.operator.strip(),
            (payload.justification or "").strip() or None,
        )
        detail_key = candidate.get("return_trip_key") or candidate["parent_trip_key"]
        return trip_operations_service.detail(detail_key) or {"return_candidate": candidate}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Possível retorno não encontrado") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
