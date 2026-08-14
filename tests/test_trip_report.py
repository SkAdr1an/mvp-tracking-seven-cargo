from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.core.security import Principal, Role
from app.services.journey_observation import JourneyObservationService
from app.services.trip_lifecycle import TripLifecycleService
from app.services.trip_report import TripReportService
from app.storage.operations import OperationsRepository
from app.storage.migrations import migrate_database


def test_report_preserves_unavailable_delay_and_generates_unicode_html(tmp_path):
    database = tmp_path / "operations.db"
    migrate_database(database)
    repository = OperationsRepository(database)
    repository.ensure_trip("trip-1", "ABC1D23", "1", None)
    JourneyObservationService(repository)
    now = datetime.now(timezone.utc).isoformat()
    repository.add_position("trip-1", -20, -44, None, now, "test", None, None)
    result = TripReportService(repository, tmp_path / "reports").generate("trip-1")
    html = open(result.html_path, encoding="utf-8").read()
    assert "Relatório automático" in html
    assert "Indisponível" in html
    assert result.evidence_level == "UNAVAILABLE"


def test_report_endpoint_returns_pdf_without_internal_paths(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.core.security import Permission, Principal, Role, require_permission
    from app.main import app
    from app.services.trip_report import GeneratedReport, TripReportService

    pdf = tmp_path / "private" / "report.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    monkeypatch.setattr(
        TripReportService,
        "generate",
        lambda self, trip_key: GeneratedReport(
            html_path=str(tmp_path / "private" / "report.html"),
            json_path=str(tmp_path / "private" / "evidence.json"),
            pdf_path=str(pdf), generated_at="2026-08-11T00:00:00+00:00",
            sha256="synthetic", evidence_level="CALCULATED",
        ),
    )
    principal = Principal("audit-admin", Role.ADMIN)
    app.dependency_overrides[require_permission(Permission.REPORTS_GENERATE)] = lambda: principal
    try:
        response = TestClient(app).post("/operations/trips/trip-1/report")
    finally:
        app.dependency_overrides.pop(require_permission(Permission.REPORTS_GENERATE), None)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert "relatorio-viagem-trip-1.pdf" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF-")
    assert str(tmp_path).encode() not in response.content


def test_report_renders_nominal_trip_lifecycle_without_technical_user_id(tmp_path):
    database = tmp_path / "lifecycle-report.sqlite"
    migrate_database(database)
    repository = OperationsRepository(database)
    repository.ensure_trip("trip-cancelled", "ABC1D23", "provider-report", None)
    actor = Principal("gr.report", Role.GR, display_name="Gestora de Risco")
    lifecycle = TripLifecycleService(repository)
    lifecycle.cancel("trip-cancelled", "Carga recusada pelo destinatário", actor)
    lifecycle.archive("trip-cancelled", "Operação encerrada e conferida", actor)

    generated = TripReportService(repository, tmp_path / "reports").generate("trip-cancelled")
    rendered = Path(generated.html_path).read_text(encoding="utf-8")

    assert "Viagem cancelada" in rendered
    assert "Carga recusada pelo destinatário" in rendered
    assert "Viagem arquivada" in rendered
    assert "Operação encerrada e conferida" in rendered
    assert "Gestora de Risco" in rendered and "GR" in rendered
    assert "cancelled_by_user_id" not in rendered
