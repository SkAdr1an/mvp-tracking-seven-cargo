from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.security import require_panel_session
from app.services.driver_history import DriverHistoryService
from app.services.pdf_renderer import PdfRenderError, render_html_to_pdf
from app.services.trip_operations import trip_operations_service


router = APIRouter(prefix="/api/driver-history", tags=["driver-history"])


def service() -> DriverHistoryService:
    history = DriverHistoryService(trip_operations_service.repository)
    if not history.available():
        raise HTTPException(503, "Histórico de motoristas indisponível: migração 009 pendente")
    return history


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    cpf: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=30)


class EvaluationRequest(BaseModel):
    communication: Literal["ruim", "regular", "boa", "excelente"]
    procedures: Literal["nao_cumpriu", "parcial", "cumpriu"]
    tracking_collaboration: Literal["ruim", "regular", "boa", "excelente"]
    time_mark: Literal["nao_conforme", "parcial", "conforme"]
    professional_behavior: Literal["ruim", "regular", "bom", "excelente"]
    recommendation: Literal["recomendado", "com_ressalvas", "nao_recomendado"]
    internal_note: str | None = Field(default=None, max_length=2000)
    justification: str | None = Field(default=None, max_length=2000)


class PunctualityRequest(BaseModel):
    considered_value: Literal["ON_TIME", "LATE", "UNAVAILABLE"]
    category: Literal["DRIVER", "TRAFFIC", "WEATHER", "MECHANICAL", "CUSTOMER", "LOAD_UNLOAD", "SCHEDULING", "OTHER"]
    reason: str = Field(min_length=2, max_length=300)
    justification: str = Field(min_length=5, max_length=2000)
    evidence: str | None = Field(default=None, max_length=1000)


class NoteRequest(BaseModel):
    note: str = Field(min_length=3, max_length=2000)


class IdentityLinkRequest(BaseModel):
    target_driver_id: str | None = None
    cpf: str | None = Field(default=None, max_length=20)
    name: str = Field(min_length=2, max_length=150)
    source: str = Field(min_length=2, max_length=100)
    justification: str = Field(min_length=5, max_length=1000)


class TripMetadataRequest(BaseModel):
    customer: str | None = Field(default=None, max_length=150)
    evaluation_responsible: str | None = Field(default=None, max_length=150)
    justification: str = Field(min_length=5, max_length=1000)


@router.get("/drivers")
def list_drivers(search: str = "", page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                 _operator: str = Depends(require_panel_session)) -> dict:
    return service().drivers(search=search, page=page, page_size=page_size)


@router.get("/drivers/{driver_id}")
def driver_profile(driver_id: str, _operator: str = Depends(require_panel_session)) -> dict:
    try: return service().profile(driver_id)
    except KeyError as exc: raise HTTPException(404, "Motorista não encontrado") from exc


@router.patch("/drivers/{driver_id}")
def update_driver(driver_id: str, payload: ProfileUpdate, _operator: str = Depends(require_panel_session)) -> dict:
    try: return service().update_profile(driver_id, **payload.model_dump())
    except KeyError as exc: raise HTTPException(404, "Motorista não encontrado") from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/drivers/{driver_id}/trips")
def driver_trips(driver_id: str, start: str | None = None, end: str | None = None, route: str | None = None,
                 customer: str | None = None, status: str | None = None, page: int = Query(1, ge=1),
                 page_size: int = Query(25, ge=1, le=100), _operator: str = Depends(require_panel_session)) -> dict:
    return service().trips(driver_id, start=start, end=end, route=route, customer=customer, status=status, page=page, page_size=page_size)


@router.get("/pending-evaluations")
def pending_evaluations(responsible: str | None = None, start: str | None = None, end: str | None = None,
                        customer: str | None = None, route: str | None = None, overdue: bool | None = None,
                        page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                        _operator: str = Depends(require_panel_session)) -> dict:
    return service().pending(overdue_hours=get_settings().driver_evaluation_due_hours, responsible=responsible,
                             start=start, end=end, customer=customer, route=route, overdue=overdue, page=page, page_size=page_size)


@router.post("/trips/{trip_key}/evaluation", status_code=201)
def evaluate_trip(trip_key: str, payload: EvaluationRequest, operator: str = Depends(require_panel_session)) -> dict:
    try: return service().evaluate(trip_key, payload.model_dump(), operator)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.post("/trips/{trip_key}/punctuality-adjustments", status_code=201)
def adjust_punctuality(trip_key: str, payload: PunctualityRequest, operator: str = Depends(require_panel_session)) -> dict:
    try: return service().adjust_punctuality(trip_key, payload.considered_value, payload.category, payload.reason, payload.justification, payload.evidence, operator)
    except KeyError as exc: raise HTTPException(404, "Viagem não encontrada") from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.post("/drivers/{driver_id}/notes", status_code=201)
def add_note(driver_id: str, payload: NoteRequest, operator: str = Depends(require_panel_session)) -> dict:
    try: return service().add_note(driver_id, payload.note, operator)
    except KeyError as exc: raise HTTPException(404, "Motorista não encontrado") from exc


@router.post("/trips/{trip_key}/identity-link")
def link_identity(trip_key: str, payload: IdentityLinkRequest, operator: str = Depends(require_panel_session)) -> dict:
    try: return service().link_identity(trip_key, responsible=operator, **payload.model_dump())
    except KeyError as exc: raise HTTPException(404, "Viagem não encontrada") from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.patch("/trips/{trip_key}/metadata")
def correct_metadata(trip_key: str, payload: TripMetadataRequest, operator: str = Depends(require_panel_session)) -> dict:
    try: return service().correct_trip_metadata(trip_key, responsible=operator, **payload.model_dump())
    except KeyError as exc: raise HTTPException(404, "Viagem não encontrada") from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/drivers/{driver_id}/report.pdf", response_class=FileResponse)
def download_report(background_tasks: BackgroundTasks, driver_id: str, start: str | None = None,
                    end: str | None = None, route: str | None = None, customer: str | None = None,
                    status: str | None = None, include_sensitive: bool = False,
                    _operator: str = Depends(require_panel_session)) -> FileResponse:
    folder = Path(tempfile.mkdtemp(prefix="seven-driver-report-"))
    try:
        values = service().trips(driver_id, start=start, end=end, route=route, customer=customer, status=status, page=1, page_size=10000)
        html_path = folder / "report.html"
        html_path.write_text(service().report_html(driver_id, values["items"], include_sensitive=include_sensitive,
            filters={"início":start,"fim":end,"rota":route,"cliente":customer,"status":status}), encoding="utf-8")
        pdf_path = render_html_to_pdf(html_path)
    except KeyError as exc:
        shutil.rmtree(folder, ignore_errors=True); raise HTTPException(404, "Motorista não encontrado") from exc
    except PdfRenderError as exc:
        shutil.rmtree(folder, ignore_errors=True); raise HTTPException(503, str(exc)) from exc
    background_tasks.add_task(shutil.rmtree, folder, True)
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"historico-{driver_id}.pdf", background=background_tasks)
