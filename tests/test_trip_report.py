from __future__ import annotations

from datetime import datetime, timezone

from app.services.journey_observation import JourneyObservationService
from app.services.trip_report import TripReportService
from app.storage.operations import OperationsRepository


def test_report_preserves_unavailable_delay_and_generates_unicode_html(tmp_path):
    repository = OperationsRepository(tmp_path / "operations.db")
    repository.ensure_trip("trip-1", "ABC1D23", "1", None)
    JourneyObservationService(repository)
    now = datetime.now(timezone.utc).isoformat()
    repository.add_position("trip-1", -20, -44, None, now, "test", None, None)
    result = TripReportService(repository, tmp_path / "reports").generate("trip-1")
    html = open(result.html_path, encoding="utf-8").read()
    assert "Relatório automático" in html
    assert "Indisponível" in html
    assert result.evidence_level == "UNAVAILABLE"
