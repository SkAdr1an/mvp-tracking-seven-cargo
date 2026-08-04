from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.public_trip import get_public_trip_service
from app.core.config import get_settings
from app.main import app
from app.services.public_trip import PublicTripService
from app.storage.operations import OperationsRepository
from scripts.migrate_driver_mobile_location import migrate


@pytest.fixture
def mobile_portal(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "public_trip_token_pepper", "mobile-test-pepper")
    monkeypatch.setattr(settings, "driver_mobile_location_enabled", True)
    monkeypatch.setattr(settings, "driver_mobile_location_min_interval_seconds", 15)
    monkeypatch.setattr(settings, "driver_mobile_location_max_per_minute", 6)
    monkeypatch.setattr(settings, "driver_mobile_location_max_accuracy_m", 1000)
    monkeypatch.setattr(settings, "driver_mobile_location_stale_minutes", 10)
    monkeypatch.setattr(settings, "driver_mobile_location_divergence_km", 5)
    database = tmp_path / "mobile.db"
    repository = OperationsRepository(database)
    repository.upsert_route({
        "id": "route-1", "name": "Rota de teste", "origin_name": "Origem",
        "origin_latitude": -20, "origin_longitude": -44, "destination_name": "Destino",
        "destination_latitude": -19, "destination_longitude": -43,
        "origin_radius_m": 500, "destination_radius_m": 500,
        "origin_exit_radius_m": 650, "destination_exit_radius_m": 650,
        "origin_dwell_minutes": 10, "destination_dwell_minutes": 10,
        "destination_finish_minutes": 30, "stop_speed_max_kmh": 5,
        "consecutive_readings": 2, "sla_minutes": None,
        "active": True, "match_terms": [],
    })
    repository.ensure_trip("trip-a", "ABC1D23", "provider-a", "route-1")
    repository.ensure_trip("trip-b", "DEF4G56", "provider-b", "route-1")
    migrate(database)
    service = PublicTripService(repository)
    _, token = service.create_link("trip-a", None, "test")
    app.dependency_overrides[get_public_trip_service] = lambda: service
    yield TestClient(app), service, repository, token
    app.dependency_overrides.pop(get_public_trip_service, None)


def payload(**changes):
    return {
        "latitude": -19.5, "longitude": -43.5, "accuracy_m": 25,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    } | changes


def test_mobile_position_is_separate_token_scoped_and_does_not_change_trip_state(mobile_portal):
    client, _, repository, token = mobile_portal
    before = repository.trip("trip-a")
    response = client.post(f"/api/public/trips/{token}/positions", json=payload(trip_key="trip-b"))
    assert response.status_code == 202
    assert response.json()["source"] == "LINK_MOTORISTA"
    after = repository.trip("trip-a")
    assert after["state"] == before["state"] == "PROGRAMADA"
    assert after["last_latitude"] == before["last_latitude"]
    with repository.connect() as connection:
        position = connection.execute(
            "SELECT trip_key,source,latitude FROM operational_positions"
        ).fetchone()
        metadata = connection.execute(
            "SELECT accuracy_m,public_link_id,received_at FROM portal_mobile_position_metadata"
        ).fetchone()
    assert dict(position) == {"trip_key": "trip-a", "source": "LINK_MOTORISTA", "latitude": -19.5}
    assert metadata["accuracy_m"] == 25
    assert metadata["received_at"]


def test_invalid_expired_revoked_and_finished_links_cannot_submit(mobile_portal):
    client, service, repository, token = mobile_portal
    assert client.post("/api/public/trips/invalid-token/positions", json=payload()).status_code == 404
    with repository.connect() as connection:
        connection.execute(
            "UPDATE public_trip_links SET expires_at=? WHERE token_hash=?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), service.token_hash(token)),
        )
    expired = client.post(f"/api/public/trips/{token}/positions", json=payload())
    assert expired.status_code == 410
    assert expired.json()["reason"] == "expired"
    _, second = service.create_link("trip-a", None, "test")
    service.revoke_link("trip-a", "test")
    revoked = client.post(f"/api/public/trips/{second}/positions", json=payload())
    assert revoked.status_code == 410
    assert revoked.json()["reason"] == "revoked"
    _, third = service.create_link("trip-a", None, "test")
    repository.update_trip("trip-a", state="FINALIZADA_NO_SISTEMA")
    response = client.post(f"/api/public/trips/{third}/positions", json=payload())
    assert response.status_code == 410
    assert response.json()["reason"] == "trip_finished"


def test_invalid_coordinates_low_accuracy_and_abuse_are_rejected(mobile_portal):
    client, _, repository, token = mobile_portal
    assert client.post(f"/api/public/trips/{token}/positions", json=payload(latitude=91)).status_code == 422
    low = client.post(f"/api/public/trips/{token}/positions", json=payload(accuracy_m=1500))
    assert low.status_code == 422
    assert low.json()["reason"] == "accuracy_too_low"
    assert client.post(f"/api/public/trips/{token}/positions", json=payload()).status_code == 202
    limited = client.post(f"/api/public/trips/{token}/positions", json=payload(latitude=-19.51))
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM operational_positions").fetchone()[0] == 1


def test_feature_is_off_by_default_and_source_priority_is_explicit(mobile_portal, monkeypatch):
    client, _, repository, token = mobile_portal
    now = datetime.now(timezone.utc)
    repository.add_position(
        "trip-a", -19.5001, -43.5001, 50, now.isoformat(), "trafegus:fleet",
        None, None,
    )
    assert client.post(f"/api/public/trips/{token}/positions", json=payload()).status_code == 202
    current = client.get(f"/api/public/trips/{token}").json()
    assert current["location_sources"]["situation"] == "TRAFEGUS_PRIMARY"
    assert current["location_sources"]["mobile"]["accuracy_m"] == 25
    assert current["location_sources"]["difference_km"] < 1
    monkeypatch.setattr(get_settings(), "driver_mobile_location_enabled", False)
    disabled = client.post(f"/api/public/trips/{token}/positions", json=payload(latitude=-19.6))
    assert disabled.status_code == 404
    assert client.get(f"/api/public/trips/{token}").json()["mobile_location_enabled"] is False


def test_stale_trafegus_makes_current_mobile_complementary(mobile_portal):
    client, _, repository, token = mobile_portal
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    repository.add_position(
        "trip-a", -19.6, -43.6, 40, old.isoformat(), "trafegus:fleet", None, None,
    )
    assert client.post(f"/api/public/trips/{token}/positions", json=payload()).status_code == 202
    sources = client.get(f"/api/public/trips/{token}").json()["location_sources"]
    assert sources["trafegus"]["status"] == "STALE"
    assert sources["mobile"]["status"] == "CURRENT"
    assert sources["situation"] == "MOBILE_COMPLEMENTARY"


def test_current_sources_far_apart_are_flagged_as_divergent(mobile_portal):
    client, _, repository, token = mobile_portal
    repository.add_position(
        "trip-a", -18.0, -42.0, 50, datetime.now(timezone.utc).isoformat(),
        "trafegus:fleet", None, None,
    )
    assert client.post(f"/api/public/trips/{token}/positions", json=payload()).status_code == 202
    sources = client.get(f"/api/public/trips/{token}").json()["location_sources"]
    assert sources["difference_km"] > 5
    assert sources["situation"] == "DIVERGENT"


def test_migration_applies_and_reverses_without_changing_existing_rows(tmp_path):
    database = tmp_path / "migration.db"
    repository = OperationsRepository(database)
    repository.ensure_trip("trip", "ABC1D23", None, None)
    with repository.connect() as connection:
        before = connection.execute("SELECT COUNT(*) FROM operational_trips").fetchone()[0]
    migrate(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='portal_mobile_position_metadata'"
        ).fetchone()[0] == 1
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    migrate(database, reverse=True)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM operational_trips").fetchone()[0] == before
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='portal_mobile_position_metadata'"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
