from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.core.security import Permission, require_panel_username, require_permission
from app.core.config import get_settings
from app.services.trip_operations import trip_operations_service


router = APIRouter(prefix="/operations", tags=["operations"], dependencies=[Depends(require_permission(Permission.OPERATIONAL_READ))])


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


class TripPlanRequest(BaseModel):
    scheduled_start_at: datetime | None = None
    scheduled_arrival_at: datetime | None = None
    customer_commitment_at: datetime | None = None
    planned_loading_minutes: float = Field(default=0, ge=0, le=1440)
    planned_stops_minutes: float = Field(default=0, ge=0, le=2880)
    operational_buffer_minutes: float = Field(default=0, ge=0, le=1440)
    source: Literal["SEVEN", "CLIENT", "TRAFEGUS"] = "SEVEN"
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_schedule(self):
        dates = (
            self.scheduled_start_at, self.scheduled_arrival_at,
            self.customer_commitment_at,
        )
        if any(value is not None and value.tzinfo is None for value in dates):
            raise ValueError("Horários do planejamento devem conter timezone")
        if (
            self.scheduled_start_at and self.scheduled_arrival_at
            and self.scheduled_arrival_at <= self.scheduled_start_at
        ):
            raise ValueError("Chegada planejada deve ser posterior à saída")
        return self


class StopJustificationRequest(BaseModel):
    reason: Literal["FUEL", "MEAL", "REST", "MAINTENANCE", "INSPECTION", "LOAD", "UNLOAD", "TRAFFIC", "BLOCKAGE", "OTHER"]
    justification: str = Field(min_length=5, max_length=1000)


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


@router.get("/trips/{trip_key}/plan")
async def trip_plan(trip_key: str) -> dict[str, Any]:
    if not trip_operations_service.repository.trip(trip_key):
        raise HTTPException(status_code=404, detail="Viagem operacional não encontrada")
    return {"plan": trip_operations_service.repository.plan(trip_key)}


@router.put("/trips/{trip_key}/plan")
async def update_trip_plan(
    trip_key: str,
    payload: TripPlanRequest,
    operator: str = Depends(require_panel_username),
) -> dict[str, Any]:
    try:
        values = payload.model_dump(mode="json")
        return trip_operations_service.repository.save_plan(trip_key, values, operator)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Viagem operacional não encontrada") from exc


@router.get("/trips/{trip_key}/eta-history")
async def trip_eta_history(
    trip_key: str, limit: int = Query(default=100, ge=1, le=1000)
) -> dict[str, Any]:
    if not trip_operations_service.repository.trip(trip_key):
        raise HTTPException(status_code=404, detail="Viagem operacional não encontrada")
    return {"history": trip_operations_service.repository.eta_history(trip_key, limit)}


@router.get("/exceptions")
async def operational_exceptions() -> dict[str, Any]:
    from app.services.journey_observation import get_journey_observation_service
    service = get_journey_observation_service(trip_operations_service.repository)
    return {"exceptions": service.reconcile()}


@router.post("/stops/{stop_id}/justification")
async def justify_stop(
    stop_id: int,
    payload: StopJustificationRequest,
    operator: str = Depends(require_panel_username),
) -> dict[str, Any]:
    from app.services.journey_observation import get_journey_observation_service
    try:
        return get_journey_observation_service(
            trip_operations_service.repository
        ).justify_stop(stop_id, payload.reason, payload.justification, operator)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Parada não encontrada") from exc


@router.get("/trips/{trip_key}/report-data")
async def report_data(trip_key: str) -> dict[str, Any]:
    from app.services.trip_report import TripReportService
    try:
        return TripReportService(
            trip_operations_service.repository, get_settings().automatic_reports_directory
        ).evidence(trip_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Viagem operacional não encontrada") from exc


@router.post("/trips/{trip_key}/report")
async def generate_report(
    trip_key: str,
    _operator: str = Depends(require_panel_username),
) -> FileResponse:
    import re
    from pathlib import Path
    from app.services.trip_report import TripReportService
    try:
        result = TripReportService(
            trip_operations_service.repository, get_settings().automatic_reports_directory
        ).generate(trip_key)
        pdf_path = Path(result.pdf_path) if result.pdf_path else None
        if not pdf_path or not pdf_path.is_file():
            raise HTTPException(status_code=503, detail="Não foi possível gerar o PDF neste momento")
        with pdf_path.open("rb") as generated_pdf:
            if generated_pdf.read(5) != b"%PDF-":
                raise HTTPException(status_code=503, detail="Não foi possível gerar o PDF neste momento")
        safe_key = re.sub(r"[^A-Za-z0-9_-]+", "-", trip_key).strip("-")[:80] or "viagem"
        return FileResponse(pdf_path, media_type="application/pdf", filename=f"relatorio-viagem-{safe_key}.pdf")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Viagem operacional não encontrada") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Não foi possível gerar o relatório neste momento") from exc


@router.post("/trips/{trip_key}/actions")
async def manual_action(
    trip_key: str,
    payload: ManualActionRequest,
    operator: str = Depends(require_panel_username),
) -> dict[str, Any]:
    try:
        trip_operations_service.manual_action(
            trip_key, payload.action, payload.justification, operator, payload.corrections
        )
        return trip_operations_service.detail(trip_key) or {}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Viagem operacional não encontrada") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/trips/{trip_key}/route")
async def assign_route(
    trip_key: str,
    payload: RouteAssignmentRequest,
    _operator: str = Depends(require_panel_username),
) -> dict[str, Any]:
    route = trip_operations_service.repository.route(payload.route_id)
    if not route or not route["active"]:
        raise HTTPException(status_code=404, detail="Rota ativa não encontrada")
    try:
        trip_operations_service.repository.update_trip(trip_key, route_id=payload.route_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Viagem operacional não encontrada") from exc
    return trip_operations_service.detail(trip_key) or {}


@router.post("/return-candidates/{candidate_id}/decision")
async def decide_return(
    candidate_id: int,
    payload: ReturnDecisionRequest,
    operator: str = Depends(require_panel_username),
) -> dict[str, Any]:
    if payload.decision in {"YES", "NO"} and len((payload.justification or "").strip()) < 5:
        raise HTTPException(status_code=422, detail="Informe uma justificativa com pelo menos 5 caracteres")
    try:
        candidate = trip_operations_service.return_tracking.decide(
            candidate_id, payload.decision, operator,
            (payload.justification or "").strip() or None,
        )
        detail_key = candidate.get("return_trip_key") or candidate["parent_trip_key"]
        return trip_operations_service.detail(detail_key) or {"return_candidate": candidate}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Possível retorno não encontrado") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
