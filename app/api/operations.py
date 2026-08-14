from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.core.security import (
    Permission, Principal, enforce_permission, require_panel_session, require_permission,
)
from app.core.config import get_settings
from app.services.trip_operations import trip_operations_service
from app.services.operational_observations import (
    ObservationConflict, ObservationType, OperationalObservationService,
    PersistentIdentityRequired,
)
from app.services.audit import AuditAction, AuditService


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


class ObservationCreateRequest(BaseModel):
    observation_type: ObservationType
    content: str = Field(min_length=1, max_length=4000)
    occurred_at: datetime
    stop_id: int | None = Field(default=None, ge=1)
    include_in_report: bool = True

    @model_validator(mode="after")
    def validate_observation(self):
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must include timezone")
        if not self.content.strip():
            raise ValueError("content must not be empty")
        return self


class ObservationCorrectionRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=5, max_length=1000)


class ObservationVoidRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


def _observation_service() -> OperationalObservationService:
    return OperationalObservationService(trip_operations_service.repository.database_path)


def _audit(principal: Principal, action: AuditAction, resource_type: str, **values: Any) -> None:
    AuditService(trip_operations_service.repository.database_path).record(
        principal, action, resource_type, **values
    )


def _observation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PersistentIdentityRequired):
        return HTTPException(status_code=409, detail="Persistent user identity required")
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail="Observation belongs to another author")
    if isinstance(exc, ObservationConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="Trip, stop or observation not found")
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/routes", dependencies=[Depends(require_permission(Permission.TRIPS_READ))])
async def list_routes(active_only: bool = Query(default=False)) -> dict[str, Any]:
    return {"routes": trip_operations_service.repository.routes(active_only=active_only)}


@router.get("/trips/{trip_key}", dependencies=[Depends(require_permission(Permission.TRIPS_READ))])
async def trip_detail(trip_key: str) -> dict[str, Any]:
    detail = trip_operations_service.detail(trip_key)
    if detail is None:
        raise HTTPException(status_code=404, detail="Viagem operacional não encontrada")
    return detail


@router.get("/diagnostics/{trip_key}", dependencies=[Depends(require_permission(Permission.TRIPS_READ))])
async def trip_diagnostic(trip_key: str) -> dict[str, Any]:
    value = trip_operations_service.repository.diagnostic(trip_key)
    if value is None:
        raise HTTPException(status_code=404, detail="Diagnóstico operacional não disponível")
    return value


@router.get("/trips/{trip_key}/plan", dependencies=[Depends(require_permission(Permission.TRIPS_READ))])
async def trip_plan(trip_key: str) -> dict[str, Any]:
    if not trip_operations_service.repository.trip(trip_key):
        raise HTTPException(status_code=404, detail="Viagem operacional não encontrada")
    return {"plan": trip_operations_service.repository.plan(trip_key)}


@router.put("/trips/{trip_key}/plan")
async def update_trip_plan(
    trip_key: str,
    payload: TripPlanRequest,
    principal: Principal = Depends(require_permission(Permission.TRIPS_EDIT)),
) -> dict[str, Any]:
    try:
        values = payload.model_dump(mode="json")
        before = trip_operations_service.repository.plan(trip_key)
        result = trip_operations_service.repository.save_plan(trip_key, values, principal.username)
        _audit(principal, AuditAction.TRIP_PLAN_UPDATED, "trip", resource_id=trip_key,
               trip_key=trip_key, before=before, after=result)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Viagem operacional não encontrada") from exc


@router.get("/trips/{trip_key}/eta-history", dependencies=[Depends(require_permission(Permission.TRIPS_READ))])
async def trip_eta_history(
    trip_key: str, limit: int = Query(default=100, ge=1, le=1000)
) -> dict[str, Any]:
    if not trip_operations_service.repository.trip(trip_key):
        raise HTTPException(status_code=404, detail="Viagem operacional não encontrada")
    return {"history": trip_operations_service.repository.eta_history(trip_key, limit)}


@router.get("/trips/{trip_key}/observations")
async def list_observations(
    trip_key: str,
    _principal: Principal = Depends(require_permission(Permission.TRIPS_READ)),
) -> dict[str, Any]:
    try:
        return {"observations": _observation_service().list_for_trip(trip_key)}
    except (KeyError, ValueError) as exc:
        raise _observation_error(exc) from exc


@router.post("/trips/{trip_key}/observations", status_code=201)
async def create_observation(
    trip_key: str,
    payload: ObservationCreateRequest,
    principal: Principal = Depends(require_permission(Permission.OBSERVATIONS_CREATE)),
) -> dict[str, Any]:
    try:
        result = _observation_service().create(
            trip_key=trip_key, observation_type=payload.observation_type,
            content=payload.content, occurred_at=payload.occurred_at, principal=principal,
            stop_id=payload.stop_id, include_in_report=payload.include_in_report,
        )
        _audit(principal, AuditAction.OBSERVATION_CREATED, "observation",
               resource_id=result["id"], trip_key=trip_key,
               after={"observation_type": result["type"],
                      "include_in_report": result["include_in_report"]})
        return result
    except (KeyError, ValueError) as exc:
        raise _observation_error(exc) from exc


@router.post("/observations/{observation_id}/correction")
async def correct_observation(
    observation_id: str,
    payload: ObservationCorrectionRequest,
    principal: Principal = Depends(require_permission(Permission.OBSERVATIONS_CORRECT_OWN)),
) -> dict[str, Any]:
    try:
        result = _observation_service().correct(
            observation_id, content=payload.content, reason=payload.reason, principal=principal,
        )
        current = result["observation"]
        _audit(principal, AuditAction.OBSERVATION_CORRECTED, "observation",
               resource_id=current["id"], trip_key=current["trip_key"],
               before={"observation_id": observation_id}, after={"observation_id": current["id"]},
               justification=payload.reason)
        return result
    except (KeyError, ValueError, PermissionError) as exc:
        raise _observation_error(exc) from exc


@router.post("/observations/{observation_id}/void")
async def void_observation(
    observation_id: str,
    payload: ObservationVoidRequest,
    principal: Principal = Depends(require_permission(Permission.OBSERVATIONS_VOID_ANY)),
) -> dict[str, Any]:
    try:
        result = _observation_service().void(
            observation_id, reason=payload.reason, principal=principal,
        )
        _audit(principal, AuditAction.OBSERVATION_VOIDED, "observation",
               resource_id=observation_id, trip_key=result["trip_key"],
               before={"status": "ACTIVE"}, after={"status": "VOIDED"},
               justification=payload.reason)
        return result
    except (KeyError, ValueError) as exc:
        raise _observation_error(exc) from exc


@router.get("/exceptions", dependencies=[Depends(require_permission(Permission.STOPS_READ))])
async def operational_exceptions() -> dict[str, Any]:
    from app.services.journey_observation import get_journey_observation_service
    service = get_journey_observation_service(trip_operations_service.repository)
    return {"exceptions": service.reconcile()}


@router.post("/stops/{stop_id}/justification")
async def justify_stop(
    stop_id: int,
    payload: StopJustificationRequest,
    principal: Principal = Depends(require_permission(Permission.STOPS_JUSTIFY)),
) -> dict[str, Any]:
    from app.services.journey_observation import get_journey_observation_service
    try:
        result = get_journey_observation_service(
            trip_operations_service.repository
        ).justify_stop(stop_id, payload.reason, payload.justification, principal.username)
        _audit(principal, AuditAction.STOP_JUSTIFIED, "stop", resource_id=stop_id,
               trip_key=result["trip_key"], after={"reason": payload.reason},
               justification=payload.justification)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Parada não encontrada") from exc


@router.get("/trips/{trip_key}/report-data", dependencies=[Depends(require_permission(Permission.TRIPS_READ))])
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
    principal: Principal = Depends(require_permission(Permission.REPORTS_GENERATE)),
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
        AuditService(trip_operations_service.repository.database_path).record_optional(
            principal, AuditAction.REPORT_GENERATED, "trip_report", resource_id=trip_key,
            trip_key=trip_key, metadata={"format": "PDF", "success": True})
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
    principal: Principal = Depends(require_panel_session),
) -> dict[str, Any]:
    action_permissions = {
        "finalize": Permission.TRIPS_FINALIZE,
        "reopen": Permission.TRIPS_REOPEN,
        "undo_detection": Permission.TRIPS_STATUS_CORRECT,
        "correct_times": Permission.TRIPS_STATUS_CORRECT,
    }
    enforce_permission(principal, action_permissions[payload.action])
    try:
        trip_operations_service.manual_action(
            trip_key, payload.action, payload.justification, principal.username, payload.corrections
        )
        mapped = {
            "finalize": AuditAction.TRIP_FINALIZED, "reopen": AuditAction.TRIP_REOPENED,
            "undo_detection": AuditAction.TRIP_STATUS_CORRECTED,
            "correct_times": AuditAction.TRIP_STATUS_CORRECTED,
        }
        _audit(principal, mapped[payload.action], "trip", resource_id=trip_key,
               trip_key=trip_key, after={"action": payload.action,
                                         "corrections": payload.corrections},
               justification=payload.justification)
        return trip_operations_service.detail(trip_key) or {}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Viagem operacional não encontrada") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/trips/{trip_key}/route")
async def assign_route(
    trip_key: str,
    payload: RouteAssignmentRequest,
    principal: Principal = Depends(require_permission(Permission.TRIPS_ASSIGN_ROUTE)),
) -> dict[str, Any]:
    route = trip_operations_service.repository.route(payload.route_id)
    if not route or not route["active"]:
        raise HTTPException(status_code=404, detail="Rota ativa não encontrada")
    try:
        before = trip_operations_service.repository.trip(trip_key) or {}
        trip_operations_service.repository.update_trip(trip_key, route_id=payload.route_id)
        _audit(principal, AuditAction.TRIP_ROUTE_ASSIGNED, "trip", resource_id=trip_key,
               trip_key=trip_key, before={"route_id": before.get("route_id")},
               after={"route_id": payload.route_id})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Viagem operacional não encontrada") from exc
    return trip_operations_service.detail(trip_key) or {}


@router.post("/return-candidates/{candidate_id}/decision")
async def decide_return(
    candidate_id: int,
    payload: ReturnDecisionRequest,
    principal: Principal = Depends(require_permission(Permission.TRIPS_EDIT)),
) -> dict[str, Any]:
    if payload.decision in {"YES", "NO"} and len((payload.justification or "").strip()) < 5:
        raise HTTPException(status_code=422, detail="Informe uma justificativa com pelo menos 5 caracteres")
    try:
        candidate = trip_operations_service.return_tracking.decide(
            candidate_id, payload.decision, principal.username,
            (payload.justification or "").strip() or None,
        )
        _audit(principal, AuditAction.TRIP_RETURN_DECISION, "return_candidate",
               resource_id=candidate_id, trip_key=candidate.get("parent_trip_key"),
               after={"decision": payload.decision}, justification=payload.justification)
        detail_key = candidate.get("return_trip_key") or candidate["parent_trip_key"]
        return trip_operations_service.detail(detail_key) or {"return_candidate": candidate}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Possível retorno não encontrado") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
