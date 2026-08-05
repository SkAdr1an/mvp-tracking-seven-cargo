from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.storage.operations import OperationsRepository


def test_plan_is_auditable_and_eta_changes_append_history(tmp_path):
    repository = OperationsRepository(tmp_path / "operations.db")
    repository.ensure_trip("trip-1", "ABC1D23", "1", None)
    start = datetime.now(timezone.utc)
    plan = repository.save_plan(
        "trip-1",
        {
            "scheduled_start_at": start.isoformat(),
            "scheduled_arrival_at": (start + timedelta(hours=30)).isoformat(),
            "customer_commitment_at": (start + timedelta(hours=32)).isoformat(),
            "planned_loading_minutes": 60,
            "planned_stops_minutes": 90,
            "operational_buffer_minutes": 120,
            "source": "SEVEN",
            "notes": "Planejamento operacional aprovado",
        },
        "gestor-1",
    )
    assert plan["updated_by"] == "gestor-1"
    diagnostic = {
        "trip_key": "trip-1", "eta_at": (start + timedelta(hours=31)).isoformat(),
        "window_start_at": None, "window_end_at": None,
        "client_eta_at": plan["customer_commitment_at"],
        "commitment_delta_minutes": -60, "trend": "DENTRO_DO_PRAZO",
        "confidence": "HIGH", "classification": "NORMAL", "remaining_minutes": 1200,
        "stopped_minutes": 0, "method_version": "test-v1", "factors": [],
        "confidence_reasons": [], "risks": [], "recommendations": [], "scenarios": {},
        "status_explanation": "Teste", "last_reliable": None,
        "calculated_at": start.isoformat(),
    }
    repository.save_diagnostic(diagnostic)
    repository.save_diagnostic(diagnostic)
    assert len(repository.eta_history("trip-1")) == 1
    diagnostic["commitment_delta_minutes"] = 30
    diagnostic["classification"] = "ATENCAO"
    repository.save_diagnostic(diagnostic)
    assert len(repository.eta_history("trip-1")) == 2
