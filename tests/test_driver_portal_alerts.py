from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.public_trip import get_public_trip_service
from app.core.config import get_settings
from app.main import app
from app.services.fleet_tracking import fleet_tracking_service
from app.services.public_trip import PublicTripService
from app.storage.operations import OperationsRepository, utc_now
from app.storage.traffic import TrafficRepository
from scripts.migrate_driver_mobile_location import migrate as migrate_mobile
from scripts.migrate_driver_portal_alerts import migrate as migrate_alerts


@pytest.fixture
def alert_portal(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "public_trip_token_pepper", "alert-test-pepper")
    monkeypatch.setattr(settings, "driver_portal_alerts_enabled", True)
    monkeypatch.setattr(settings, "driver_alert_max_age_minutes", 180)
    monkeypatch.setattr(settings, "driver_alert_route_corridor_km", 5)
    database = tmp_path / "alerts.db"
    repository = OperationsRepository(database)
    repository.upsert_route({
        "id": "route-alert", "name": "Rota alerta", "origin_name": "Origem",
        "origin_latitude": 0, "origin_longitude": 0, "destination_name": "Destino",
        "destination_latitude": 0, "destination_longitude": 1,
        "origin_radius_m": 500, "destination_radius_m": 500,
        "origin_exit_radius_m": 650, "destination_exit_radius_m": 650,
        "origin_dwell_minutes": 10, "destination_dwell_minutes": 10,
        "destination_finish_minutes": 30, "stop_speed_max_kmh": 5,
        "consecutive_readings": 2, "sla_minutes": None, "active": True, "match_terms": [],
    })
    repository.ensure_trip("trip-alert", "ABC1D23", "provider", "route-alert")
    with repository.connect() as connection:
        geometry = [{"latitude": 0, "longitude": index / 100} for index in range(101)]
        connection.execute(
            """INSERT INTO route_geometry_versions(route_id,version,source,geometry_json,
               mandatory_points_json,corridor_m,segment_tolerances_json,active,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            ("route-alert", "v1", "test", json.dumps(geometry), "[]", 5000, "[]", 1, utc_now()),
        )
    traffic = TrafficRepository(repository)
    migrate_mobile(database); migrate_alerts(database)
    service = PublicTripService(repository)
    _, token = service.create_link("trip-alert", None, "test")
    app.dependency_overrides[get_public_trip_service] = lambda: service
    old_snapshot = fleet_tracking_service._snapshot
    yield TestClient(app), service, repository, traffic, token
    fleet_tracking_service._snapshot = old_snapshot
    app.dependency_overrides.pop(get_public_trip_service, None)


def add_position(repository, longitude: float, at: datetime | None = None):
    repository.add_position(
        "trip-alert", 0, longitude, 50, (at or datetime.now(timezone.utc)).isoformat(),
        "trafegus:fleet", None, None,
    )


def add_incident(traffic, incident_id: str, longitude: float, *, severity="ATENCAO", category="CONGESTIONAMENTO", updated=None, expires=None):
    now = datetime.now(timezone.utc)
    traffic.upsert_incident({
        "id": incident_id, "route_id": "route-alert", "category": category,
        "severity": severity, "original_type": "test", "source": "TomTom Traffic Incidents",
        "description": "Ocorrência de teste", "road_name": "BR-TESTE", "direction": "Destino",
        "latitude": 0, "longitude": longitude,
        "geometry": {"type": "Point", "coordinates": [longitude, 0]},
        "length_m": 100, "delay_seconds": 1080, "delay_already_in_eta": True,
        "started_at": now.isoformat(), "updated_at": (updated or now).isoformat(),
        "expires_at": (expires or now + timedelta(hours=1)).isoformat(), "status": "ACTIVE",
        "manual": False, "information_source": "test", "responsible_user": None,
        "affected_vehicles": [{"trip_key": "trip-alert", "plate": "ABC1D23"}],
        "provider_payload": {},
    })
    with traffic.operations.connect() as connection:
        connection.execute(
            "UPDATE traffic_incidents SET publicly_visible=1,public_title='Alerta',public_description='Trânsito lento à frente' WHERE id=?",
            (incident_id,),
        )


def test_only_ahead_same_corridor_current_events_are_returned(alert_portal):
    client, _, repository, traffic, token = alert_portal
    add_position(repository, .50)
    add_incident(traffic, "ahead", .55)
    add_incident(traffic, "behind", .45)
    add_incident(traffic, "other-road", .55)
    with repository.connect() as connection:
        connection.execute("UPDATE traffic_incidents SET latitude=.2 WHERE id='other-road'")
    response = client.get(f"/api/public/trips/{token}/alerts")
    assert response.status_code == 200
    alerts = response.json()["alerts"]
    assert [item["id"] for item in alerts] == ["incident:ahead"]
    assert 5 < alerts[0]["distance_km"] < 6
    assert alerts[0]["delay_minutes"] == 18
    assert alerts[0]["source"] == "TomTom Traffic Incidents"


def test_old_closed_and_unreliable_time_events_are_discarded(alert_portal):
    client, _, repository, traffic, token = alert_portal
    add_position(repository, .50)
    add_incident(traffic, "old", .55, updated=datetime.now(timezone.utc) - timedelta(hours=4))
    add_incident(traffic, "closed", .56)
    with repository.connect() as connection:
        connection.execute("UPDATE traffic_incidents SET status='EXPIRED' WHERE id='closed'")
        connection.execute("UPDATE traffic_incidents SET updated_at='invalid' WHERE id='old'")
    assert client.get(f"/api/public/trips/{token}/alerts").json()["alerts"] == []


def test_dedup_reinforcement_and_severity_change_are_persisted(alert_portal):
    client, _, repository, traffic, token = alert_portal
    add_position(repository, .50)
    add_incident(traffic, "changing", .56)
    first = client.get(f"/api/public/trips/{token}/alerts").json()["alerts"][0]
    second = client.get(f"/api/public/trips/{token}/alerts").json()["alerts"][0]
    assert first["presentation"] == "NEW" and first["distance_band"] == "FIRST"
    assert second["presentation"] == "ACTIVE"
    add_position(repository, .545, datetime.now(timezone.utc) + timedelta(seconds=1))
    reinforced = client.get(f"/api/public/trips/{token}/alerts").json()["alerts"][0]
    assert reinforced["presentation"] == "REINFORCED"
    with repository.connect() as connection:
        connection.execute("UPDATE traffic_incidents SET severity='CRITICO' WHERE id='changing'")
    updated = client.get(f"/api/public/trips/{token}/alerts").json()["alerts"][0]
    assert updated["presentation"] == "UPDATED"
    with repository.connect() as connection:
        row = connection.execute("SELECT presentation_count FROM portal_alert_presentations").fetchone()
    assert row["presentation_count"] == 3


def test_feature_disabled_invalid_link_and_degraded_integrations_are_safe(alert_portal, monkeypatch):
    client, _, repository, traffic, token = alert_portal
    assert client.get("/api/public/trips/invalid/alerts").status_code == 404
    add_position(repository, .50); add_incident(traffic, "ahead", .55)
    traffic.save_health("tomtom_traffic_incidents", "DEGRADED", None, None, 0, "temporary")
    value = client.get(f"/api/public/trips/{token}/alerts").json()
    assert value["integrations"]["traffic"] == "DEGRADED"
    monkeypatch.setattr(get_settings(), "driver_portal_alerts_enabled", False)
    disabled = client.get(f"/api/public/trips/{token}/alerts").json()
    assert disabled["enabled"] is False and disabled["alerts"] == []


def test_cached_weather_and_active_deviation_are_reused_without_external_calls(alert_portal):
    client, _, repository, _, token = alert_portal
    now = datetime.now(timezone.utc)
    add_position(repository, .50)
    fleet_tracking_service._snapshot = {
        "generated_at": now.isoformat(), "trips": [{
            "operational": {"trip_key": "trip-alert"}, "api_status": {"openweather": "connected"},
            "weather_risks": [{"type": "heavy_rain", "severity": "high", "description": "chuva forte",
                               "position": {"latitude": 0, "longitude": .60}, "source": "OpenWeather forecast"}],
        }],
    }
    with repository.connect() as connection:
        connection.execute(
            """INSERT INTO route_deviations(trip_key,plate,route_id,geometry_version,status,level,
               started_at,exit_latitude,exit_longitude,last_outside_at,current_distance_m,
               max_distance_m,related_incidents_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("trip-alert", "ABC1D23", "route-alert", "v1", "ACTIVE", "INITIAL", now.isoformat(),
             0, .5, now.isoformat(), 500, 500, "[]", now.isoformat()),
        )
    alerts = client.get(f"/api/public/trips/{token}/alerts").json()["alerts"]
    assert {item["type"] for item in alerts} == {"CHUVA_FORTE", "DESVIO_CONFIRMADO"}
