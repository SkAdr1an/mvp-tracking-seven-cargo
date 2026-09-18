from __future__ import annotations

import base64
import binascii
import hashlib
import re
import shutil
import tempfile
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.security import Permission, Principal, Role, require_panel_session, require_permission
from app.services.driver_history import DriverHistoryService
from app.services.operational_observations import ObservationType, OperationalObservationService
from app.services.pdf_renderer import PdfRenderError, render_html_to_pdf
from app.services.trip_operations import trip_operations_service


router = APIRouter(prefix="/api/driver-history", tags=["driver-history"])


def _report_filename(driver_name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", driver_name).encode("ascii", "ignore").decode("ascii")
    slug = "-".join("".join(
        character.lower() if character.isalnum() else " " for character in ascii_name
    ).split())
    return f"historico-motorista-{slug or 'sem-nome'}.pdf"


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

class ReportCorrectionRequest(BaseModel):
    field: str = Field(min_length=3, max_length=100)
    value: str = Field(max_length=500)
    justification: str = Field(min_length=5, max_length=1000)

class EvidenceAttachment(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    mime_type: Literal["image/jpeg", "image/png"]
    data_base64: str = Field(min_length=4, max_length=7_500_000)

class ReportNoteRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    attachments: list[EvidenceAttachment] = Field(default_factory=list, max_length=4)

class DriverMasterImportRow(BaseModel):
    source_row: int = Field(ge=1)
    status: str | None = Field(default=None, max_length=100)
    registration_date: str | None = Field(default=None, max_length=10)
    name: str = Field(default="", max_length=150)
    primary_phone: str | None = Field(default=None, max_length=30)
    emergency_phone: str | None = Field(default=None, max_length=30)
    cpf: str | None = Field(default=None, max_length=20)
    client_operation: str | None = Field(default=None, max_length=150)
    routes: list[str] = Field(default_factory=list, max_length=100)
    vehicle_profile: str | None = Field(default=None, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=20)

class DriverMasterImportRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    rows: list[DriverMasterImportRow] = Field(min_length=1, max_length=5000)


@router.get("/drivers")
def list_drivers(search: str = "", page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                 _operator: str = Depends(require_panel_session)) -> dict:
    return service().drivers(search=search, page=page, page_size=page_size)


@router.get("/master")
def master_drivers(search: str = "", status: str = "", client_operation: str = "",
                   vehicle_profile: str = "", route: str = "", page: int = Query(1, ge=1),
                   page_size: int = Query(50, ge=1, le=100),
                   _principal=Depends(require_permission(Permission.DRIVERS_READ))) -> dict:
    return service().master_drivers(search=search, status=status, client_operation=client_operation,
                                    vehicle_profile=vehicle_profile, route=route, page=page, page_size=page_size)

@router.post("/master/import/preview")
def preview_master_import(payload: DriverMasterImportRequest,
                          _principal=Depends(require_permission(Permission.TRIPS_EDIT))) -> dict:
    result = service().preview_master_import(file_name=payload.file_name,
                                             rows=[row.model_dump() for row in payload.rows])
    for item in result["items"]: item.pop("row", None)
    return result

@router.post("/master/import")
def import_master(payload: DriverMasterImportRequest,
                  _principal=Depends(require_permission(Permission.TRIPS_EDIT))) -> dict:
    return service().import_master(file_name=payload.file_name,
                                   rows=[row.model_dump() for row in payload.rows])


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


@router.get("/trips/{trip_key}/report-preview")
def report_preview(trip_key: str, _principal: Principal = Depends(require_panel_session)) -> dict:
    try: return service().report_preview(trip_key)
    except KeyError as exc: raise HTTPException(404, "Viagem não encontrada") from exc


@router.post("/trips/{trip_key}/report-corrections")
def correct_report(trip_key: str, payload: ReportCorrectionRequest,
                   principal: Principal = Depends(require_panel_session)) -> dict:
    if principal.role not in {Role.GR, Role.ADMIN}:
        raise HTTPException(403, "Somente GR ou Administrador pode corrigir o relatório")
    try:
        return service().correct_report_field(
            trip_key, field=payload.field, value=payload.value,
            justification=payload.justification,
            responsible=principal.display_name or principal.username,
        )
    except KeyError as exc: raise HTTPException(404, "Viagem ou campo não encontrado") from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.post("/trips/{trip_key}/report-notes")
def create_report_note(trip_key: str, payload: ReportNoteRequest,
                       principal: Principal = Depends(require_panel_session)) -> dict:
    if principal.role not in {Role.GR, Role.ADMIN}:
        raise HTTPException(403, "Somente GR ou Administrador pode incluir anotações")
    evidence_dir = Path(get_settings().operations_database_path).resolve().parent / "report-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    attachments = []
    try:
        for attachment in payload.attachments:
            try: content = base64.b64decode(attachment.data_base64, validate=True)
            except (binascii.Error, ValueError) as exc: raise HTTPException(422, "Imagem inválida") from exc
            if len(content) > 5_000_000: raise HTTPException(422, "Cada imagem deve ter no máximo 5 MB")
            jpeg = content.startswith(b"\xff\xd8\xff") and attachment.mime_type == "image/jpeg"
            png = content.startswith(b"\x89PNG\r\n\x1a\n") and attachment.mime_type == "image/png"
            if not (jpeg or png): raise HTTPException(422, "O conteúdo não corresponde a uma imagem JPEG ou PNG")
            suffix = ".jpg" if jpeg else ".png"
            identifier = uuid.uuid4().hex
            path = evidence_dir / f"{identifier}{suffix}"
            path.write_bytes(content); saved.append(path)
            attachments.append({"id":identifier,"name":attachment.name,"mime_type":attachment.mime_type,
                                "size":len(content),"sha256":hashlib.sha256(content).hexdigest(),"file":path.name})
        observation = OperationalObservationService(get_settings().operations_database_path).create(
            trip_key=trip_key, observation_type=ObservationType.OPERATIONAL_NOTE,
            content=payload.content, occurred_at=datetime.now(timezone.utc), principal=principal,
            include_in_report=True, metadata={"report_attachments":attachments} if attachments else None,
        )
        return observation
    except Exception:
        for path in saved: path.unlink(missing_ok=True)
        raise


@router.get("/evidence/{attachment_id}", response_class=FileResponse)
def report_evidence(attachment_id: str, _principal: Principal = Depends(require_panel_session)) -> FileResponse:
    if not re.fullmatch(r"[a-f0-9]{32}", attachment_id): raise HTTPException(404, "Evidência não encontrada")
    folder = Path(get_settings().operations_database_path).resolve().parent / "report-evidence"
    matches = [path for suffix in (".jpg", ".png") if (path := folder / f"{attachment_id}{suffix}").is_file()]
    if len(matches) != 1: raise HTTPException(404, "Evidência não encontrada")
    return FileResponse(matches[0], media_type="image/jpeg" if matches[0].suffix == ".jpg" else "image/png")


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
        history = service()
        profile = history.profile(driver_id)
        values = history.trips(driver_id, start=start, end=end, route=route, customer=customer, status=status, page=1, page_size=10000)
        html_path = folder / "report.html"
        html_path.write_text(history.report_html(driver_id, values["items"], include_sensitive=include_sensitive,
            filters={"início":start,"fim":end,"rota":route,"cliente":customer,"status":status}), encoding="utf-8")
        pdf_path = render_html_to_pdf(html_path)
    except KeyError as exc:
        shutil.rmtree(folder, ignore_errors=True); raise HTTPException(404, "Motorista não encontrado") from exc
    except PdfRenderError as exc:
        shutil.rmtree(folder, ignore_errors=True); raise HTTPException(503, str(exc)) from exc
    background_tasks.add_task(shutil.rmtree, folder, True)
    return FileResponse(pdf_path, media_type="application/pdf", filename=_report_filename(profile["name"]),
                        content_disposition_type="attachment", background=background_tasks)
