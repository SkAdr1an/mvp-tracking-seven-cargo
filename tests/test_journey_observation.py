from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.journey_observation import JourneyObservationService
from app.storage.operations import OperationsRepository


def _position(repository, key, when, lat, lon):
    repository.add_position(key, lat, lon, 0, when.isoformat(), "test", None, None)


def test_stops_gaps_justification_and_reconciliation_are_persisted(tmp_path):
    repository = OperationsRepository(tmp_path / "operations.db")
    repository.ensure_trip("trip-1", "ABC1D23", "1", None)
    service = JourneyObservationService(repository)
    start = datetime.now(timezone.utc) - timedelta(hours=2)
    _position(repository, "trip-1", start, -20.0, -44.0); service.observe("trip-1")
    _position(repository, "trip-1", start + timedelta(minutes=15), -20.0001, -44.0001); service.observe("trip-1")
    stops = service.stops("trip-1")
    assert stops[0]["classification"] == "ATTENTION"
    justified = service.justify_stop(stops[0]["id"], "REST", "Descanso confirmado", "operator-1")
    assert justified["confirmed_by"] == "operator-1"
    _position(repository, "trip-1", start + timedelta(minutes=60), -19.9, -43.9); service.observe("trip-1")
    repository.update_trip(
        "trip-1", last_position_at=(start + timedelta(minutes=60)).isoformat(),
        last_latitude=-19.9, last_longitude=-43.9,
    )
    assert service.gaps("trip-1")[0]["interpretation"] == "MOVEMENT_UNOBSERVED"
    exceptions = service.reconcile(stale_minutes=30)
    codes = {item["code"] for item in exceptions}
    assert "ROUTE_NOT_ASSIGNED" in codes
    assert "STALE_POSITION" in codes
    assert "STATE_POSITION_MISMATCH" in codes
