from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.public_trip import get_public_trip_service
from app.core.config import get_settings
from app.core.security import hash_password
from app.main import app
from app.services.public_trip import PublicTripService
from app.services.trip_operations import TripOperationsService
from app.storage.operations import OperationsRepository
from scripts.migrate_public_trip import migrate


@pytest.fixture
def portal(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "public_trip_internal_api_key", "internal-test-key")
    monkeypatch.setattr(settings, "public_trip_token_pepper", "test-pepper")
    monkeypatch.setattr(settings, "public_trip_base_url", "https://portal.example/viagem")
    monkeypatch.setattr(settings, "public_trip_contact_name", "Central Seven Cargo")
    monkeypatch.setattr(settings, "public_trip_contact_phone", "31999999999")
    monkeypatch.setattr(settings, "public_trip_instructions", "Pare somente em local seguro.\nLigue em caso de emergência.")
    repository = OperationsRepository(tmp_path / "portal.db")
    repository.upsert_route({
        "id": "route-1",
        "name": "Betim para Jaboatão",
        "origin_name": "Betim/MG",
        "origin_latitude": -19.98,
        "origin_longitude": -44.26,
        "destination_name": "Jaboatão/PE",
        "destination_latitude": -8.20,
        "destination_longitude": -34.96,
        "origin_radius_m": 500,
        "destination_radius_m": 1000,
        "origin_exit_radius_m": 650,
        "destination_exit_radius_m": 1150,
        "origin_dwell_minutes": 10,
        "destination_dwell_minutes": 10,
        "destination_finish_minutes": 30,
        "stop_speed_max_kmh": 5,
        "consecutive_readings": 2,
        "sla_minutes": 1440,
        "active": True,
        "match_terms": [],
    })
    repository.ensure_trip("secret-trip-key", "ABC1D23", "provider-99", "route-1")
    now = datetime.now(timezone.utc)
    repository.update_trip(
        "secret-trip-key",
        state="EM_VIAGEM",
        current_driver="João da Silva",
        trailer_plate="DEF4G56",
        loaded_at=(now - timedelta(hours=3)).isoformat(),
        last_position_at=now.isoformat(),
        last_latitude=-18.5,
        last_longitude=-42.1,
        last_speed_kmh=62,
    )
    service = PublicTripService(repository)
    app.dependency_overrides[get_public_trip_service] = lambda: service
    yield TestClient(app), service, repository
    app.dependency_overrides.pop(get_public_trip_service, None)


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer internal-test-key"}


def test_internal_endpoints_require_configured_bearer_token(portal):
    client, _, _ = portal
    assert client.post("/api/trips/secret-trip-key/public-link", json={}).status_code == 401
    assert client.get("/api/trips/secret-trip-key/public-link").status_code == 401
    assert client.delete("/api/trips/secret-trip-key/public-link").status_code == 401


def test_internal_endpoints_remain_closed_when_server_key_is_empty(portal, monkeypatch):
    client, _, _ = portal
    monkeypatch.setattr(get_settings(), "public_trip_internal_api_key", "")
    response = client.post(
        "/api/trips/secret-trip-key/public-link",
        headers={"Authorization": "Bearer any-value"},
        json={},
    )
    assert response.status_code == 401


def test_tracking_device_key_cannot_administer_public_links(portal, monkeypatch):
    client, _, _ = portal
    monkeypatch.setattr(get_settings(), "tracking_api_key", "device-tracking-key")
    response = client.post(
        "/api/trips/secret-trip-key/public-link",
        headers={"Authorization": "Bearer device-tracking-key"},
        json={},
    )
    assert response.status_code == 401


def test_authenticated_panel_session_can_administer_links(portal, monkeypatch):
    client, _, _ = portal
    settings = get_settings()
    monkeypatch.setattr(settings, "panel_admin_username", "operador")
    monkeypatch.setattr(settings, "panel_admin_password_hash", hash_password("senha-forte-123"))
    monkeypatch.setattr(settings, "panel_session_secret", "segredo-de-sessao-com-mais-de-32-bytes")
    login = client.post(
        "/api/auth/session",
        json={"username": "operador", "password": "senha-forte-123"},
    )
    assert login.status_code == 200
    assert login.json()["authenticated"] is True
    cookie = login.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    created = client.post("/api/trips/secret-trip-key/public-link", json={})
    assert created.status_code == 201
    status = client.get("/api/trips/secret-trip-key/public-link")
    assert status.status_code == 200
    assert status.json()["created_by"] == "operador"
    assert client.delete("/api/trips/secret-trip-key/public-link").status_code == 204
    assert client.delete("/api/auth/session").status_code == 204


def test_authenticated_user_endpoint_revalidates_cookie_session(portal, monkeypatch):
    client, _, _ = portal
    settings = get_settings()
    monkeypatch.setattr(settings, "panel_admin_username", "admin")
    monkeypatch.setattr(settings, "panel_admin_password_hash", hash_password("secret-admin-123"))
    monkeypatch.setattr(settings, "panel_session_secret", "segredo-de-sessao-com-mais-de-32-bytes")

    assert client.get("/api/auth/me").status_code == 401
    login = client.post(
        "/api/auth/session",
        json={"username": "admin", "password": "secret-admin-123"},
    )
    assert login.status_code == 200
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "admin"
    assert client.delete("/api/auth/session").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/trips/secret-trip-key/public-link").status_code == 401


def test_valid_panel_session_precedes_invalid_bearer_for_all_link_actions(portal, monkeypatch):
    client, _, _ = portal
    settings = get_settings()
    monkeypatch.setattr(settings, "panel_admin_username", "operador")
    monkeypatch.setattr(settings, "panel_admin_password_hash", hash_password("senha-forte-123"))
    monkeypatch.setattr(settings, "panel_session_secret", "segredo-de-sessao-com-mais-de-32-bytes")
    login = client.post(
        "/api/auth/session",
        json={"username": "operador", "password": "senha-forte-123"},
    )
    assert login.status_code == 200
    invalid_bearer = {"Authorization": "Bearer invalid-and-stale"}
    created = client.post(
        "/api/trips/secret-trip-key/public-link",
        headers=invalid_bearer,
        json={},
    )
    assert created.status_code == 201
    assert client.get(
        "/api/trips/secret-trip-key/public-link",
        headers=invalid_bearer,
    ).status_code == 200
    assert client.delete(
        "/api/trips/secret-trip-key/public-link",
        headers=invalid_bearer,
    ).status_code == 204


def test_invalid_panel_credentials_do_not_create_session(portal, monkeypatch):
    client, _, _ = portal
    settings = get_settings()
    monkeypatch.setattr(settings, "panel_admin_username", "operador")
    monkeypatch.setattr(settings, "panel_admin_password_hash", hash_password("senha-forte-123"))
    monkeypatch.setattr(settings, "panel_session_secret", "segredo-de-sessao-com-mais-de-32-bytes")
    response = client.post(
        "/api/auth/session",
        json={"username": "operador", "password": "incorreta"},
    )
    assert response.status_code == 401
    assert client.post("/api/trips/secret-trip-key/public-link", json={}).status_code == 401


def test_create_returns_token_once_and_database_stores_only_hash(portal):
    client, service, repository = portal
    response = client.post("/api/trips/secret-trip-key/public-link", headers=auth(), json={})
    assert response.status_code == 201
    body = response.json()
    token = body["url"].rsplit("/", 1)[1]
    assert len(token) >= 43
    with repository.connect() as connection:
        row = connection.execute("SELECT * FROM public_trip_links").fetchone()
    assert token not in dict(row).values()
    assert row["token_hash"] == service.token_hash(token)
    status = client.get("/api/trips/secret-trip-key/public-link", headers=auth())
    assert status.status_code == 200
    assert "url" not in status.json()
    assert "token" not in status.json()


def test_token_survives_repository_and_service_restart(portal):
    client, service, repository = portal
    created = client.post(
        "/api/trips/secret-trip-key/public-link", headers=auth(), json={}
    )
    token = created.json()["url"].rsplit("/", 1)[1]
    original_hash = service.token_hash(token)

    restarted_repository = OperationsRepository(repository.database_path)
    restarted_service = PublicTripService(restarted_repository)
    persisted = restarted_service.repository.by_hash(restarted_service.token_hash(token))
    payload, link_id = restarted_service.resolve(token)

    assert restarted_service.token_hash(token) == original_hash
    assert persisted is not None
    assert persisted["id"] == link_id
    assert payload.driver_name == "João da Silva"


def test_runtime_database_path_is_absolute_and_missing_pepper_fails(portal, monkeypatch):
    _, service, _ = portal
    assert Path(service.operations.database_path).is_absolute()
    settings = get_settings()
    monkeypatch.setattr(settings, "public_trip_token_pepper", "")
    with pytest.raises(RuntimeError, match="PUBLIC_TRIP_TOKEN_PEPPER"):
        service.token_hash("A" * 43)


def test_public_dto_is_scoped_and_contains_no_internal_fields(portal):
    client, _, repository = portal
    repository.add_event(
        "secret-trip-key",
        "INTERNAL_NOTE",
        datetime.now(timezone.utc).isoformat(),
        "internal",
        "CPF 123.456.789-00, frete 10000 e margem 25%",
        metadata={"documento": "classified"},
        operator="finance-admin",
    )
    created = client.post("/api/trips/secret-trip-key/public-link", headers=auth(), json={}).json()
    token = created["url"].rsplit("/", 1)[1]
    response = client.get(f"/api/public/trips/{token}")
    assert response.status_code == 200
    body = response.json()
    assert body["driver_name"] == "João da Silva"
    assert body["trip_reference"] == "provider-99"
    assert body["route"]["origin"]["name"] == "Betim/MG"
    assert body["route"]["destination"]["name"] == "Jaboatão/PE"
    assert body["vehicle"] == {"plate": "ABC1D23", "trailer_plate": "DEF4G56"}
    assert body["latest_position"]["latitude"] == -18.5
    assert body["central_contact"]["phone"] == "31999999999"
    assert body["finished"] is False
    assert "estimated_arrival_updated_at" in body


def test_public_portal_rejects_zero_zero_and_invalid_coordinates_without_logging_values(portal, caplog):
    client, _, repository = portal
    with repository.connect() as connection:
        connection.execute(
            "UPDATE operational_trips SET last_latitude=0,last_longitude=0 WHERE trip_key='secret-trip-key'"
        )
        connection.execute(
            "UPDATE route_configs SET origin_latitude=0,origin_longitude=0,destination_latitude=95 WHERE id='route-1'"
        )
        connection.execute("DELETE FROM operational_positions WHERE trip_key='secret-trip-key'")
    created = client.post("/api/trips/secret-trip-key/public-link", headers=auth(), json={}).json()
    token = created["url"].rsplit("/", 1)[1]
    with caplog.at_level(logging.WARNING):
        body = client.get(f"/api/public/trips/{token}").json()
    assert body["latest_position"] is None
    assert body["route"]["origin"]["coordinate"] is None
    assert body["route"]["destination"]["coordinate"] is None
    assert "source=tracker reason=invalid_coordinate" in caplog.text
    assert "latitude" not in caplog.text and "longitude" not in caplog.text
    assert token not in caplog.text
    serialized = str(body).lower()
    for forbidden in (
        "trip_key", "provider_trip_id", "token_hash", "created_by", "cpf",
        "documento", "frete", "custo", "margem", "driver_source", "operator",
    ):
        assert forbidden not in serialized


def test_demo_position_source_is_explicitly_identified_as_fictitious() -> None:
    assert PublicTripService._public_position_source("trafegus:simulacao") == "Posição fictícia de demonstração"
    assert PublicTripService._public_position_source("trafegus:fleet") == "Rastreador do veículo"


def test_invalid_expired_and_revoked_tokens_return_safe_specific_reasons(portal):
    client, service, repository = portal
    invalid = "A" * 43
    invalid_response = client.get(f"/api/public/trips/{invalid}")
    assert invalid_response.status_code == 404
    assert invalid_response.json() == {
        "detail": "Link de viagem inválido.",
        "reason": "invalid_token",
    }

    link, expired_token = service.create_link(
        "secret-trip-key", datetime.now(timezone.utc) + timedelta(minutes=1), "test"
    )
    assert link
    with service.operations.connect() as connection:
        connection.execute(
            "UPDATE public_trip_links SET expires_at=? WHERE id=?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), link["id"]),
        )
    expired_response = client.get(f"/api/public/trips/{expired_token}")
    assert expired_response.status_code == 410
    assert expired_response.json()["reason"] == "expired"
    expired_status = client.get("/api/trips/secret-trip-key/public-link", headers=auth())
    assert expired_status.status_code == 200
    assert expired_status.json()["active"] is False
    with repository.connect() as connection:
        stored = connection.execute(
            "SELECT active FROM public_trip_links WHERE id=?", (link["id"],)
        ).fetchone()
    assert stored["active"] == 0

    created = client.post("/api/trips/secret-trip-key/public-link", headers=auth(), json={}).json()
    token = created["url"].rsplit("/", 1)[1]
    assert client.delete("/api/trips/secret-trip-key/public-link", headers=auth()).status_code == 204
    revoked_response = client.get(f"/api/public/trips/{token}")
    assert revoked_response.status_code == 410
    assert revoked_response.json()["reason"] == "revoked"
    revoked_status = client.get("/api/trips/secret-trip-key/public-link", headers=auth())
    assert revoked_status.status_code == 200
    assert revoked_status.json()["active"] is False
    assert revoked_status.json()["revoked_at"] is not None


def test_access_updates_usage_and_rotation_invalidates_previous_token(portal):
    client, _, _ = portal
    first = client.post("/api/trips/secret-trip-key/public-link", headers=auth(), json={}).json()
    first_token = first["url"].rsplit("/", 1)[1]
    second = client.post("/api/trips/secret-trip-key/public-link", headers=auth(), json={}).json()
    second_token = second["url"].rsplit("/", 1)[1]
    assert first_token != second_token
    rotated = client.get(f"/api/public/trips/{first_token}")
    assert rotated.status_code == 410
    assert rotated.json()["reason"] == "revoked"
    assert client.get(f"/api/public/trips/{second_token}").status_code == 200
    status = client.get("/api/trips/secret-trip-key/public-link", headers=auth()).json()
    assert status["access_count"] == 1
    assert status["last_access_at"] is not None


def test_tokens_are_independent_and_not_derived_from_trip_id(portal):
    _, service, _ = portal
    _, first = service.create_link("secret-trip-key", None, "test")
    _, second = service.create_link("secret-trip-key", None, "test")
    assert first != second
    assert "secret-trip-key" not in first
    assert hashlib.sha256(first.encode()).hexdigest() != hashlib.sha256(second.encode()).hexdigest()


def test_token_is_bound_to_exactly_one_trip_and_tampering_does_not_cross_access(portal):
    client, service, repository = portal
    repository.ensure_trip("other-secret-trip", "ZZZ9Z99", "provider-100", "route-1")
    repository.update_trip("other-secret-trip", current_driver="Outro Motorista", state="EM_VIAGEM")
    _, first_token = service.create_link("secret-trip-key", None, "test")
    _, second_token = service.create_link("other-secret-trip", None, "test")

    assert client.get(f"/api/public/trips/{first_token}").json()["driver_name"] == "João da Silva"
    assert client.get(f"/api/public/trips/{second_token}").json()["driver_name"] == "Outro Motorista"
    tampered = first_token[:-1] + ("A" if first_token[-1] != "A" else "B")
    assert client.get(f"/api/public/trips/{tampered}").status_code == 404


def test_two_trips_are_fully_isolated_from_query_and_body_tampering(portal):
    client, service, repository = portal
    repository.upsert_route({
        "id": "route-2", "name": "Exclusive route B",
        "origin_name": "Origin B", "origin_latitude": -23.5, "origin_longitude": -46.6,
        "destination_name": "Destination B", "destination_latitude": -22.9,
        "destination_longitude": -43.2, "origin_radius_m": 500,
        "destination_radius_m": 1000, "origin_exit_radius_m": 650,
        "destination_exit_radius_m": 1150, "origin_dwell_minutes": 10,
        "destination_dwell_minutes": 10, "destination_finish_minutes": 30,
        "stop_speed_max_kmh": 5, "consecutive_readings": 2, "sla_minutes": 600,
        "active": True, "match_terms": [],
    })
    with repository.connect() as connection:
        connection.execute(
            """INSERT INTO route_geometry_versions
               (route_id,version,source,geometry_json,mandatory_points_json,corridor_m,
                segment_tolerances_json,active,created_at) VALUES(?,?,?,?,?,?,?,?,?)""",
            ("route-2", "isolated-b", "test", json.dumps([
                {"latitude": -23.5, "longitude": -46.6},
                {"latitude": -22.9, "longitude": -43.2},
            ]), "[]", 300, "[]", 1, datetime.now(timezone.utc).isoformat()),
        )
    repository.ensure_trip("trip-b", "ZZZ9Z99", "provider-b", "route-2")
    repository.update_trip(
        "trip-b", current_driver="Driver B", state="EM_VIAGEM",
        last_latitude=-23.4, last_longitude=-46.5,
        last_position_at=datetime.now(timezone.utc).isoformat(),
    )
    _, token_a = service.create_link("secret-trip-key", None, "test")
    _, token_b = service.create_link("trip-b", None, "test")

    trip_a = client.request(
        "GET", f"/api/public/trips/{token_a}?trip_id=trip-b",
        json={"trip_id": "trip-b"},
    ).json()
    trip_b = client.get(f"/api/public/trips/{token_b}?trip_id=secret-trip-key").json()

    assert trip_a["vehicle"]["plate"] == "ABC1D23"
    assert trip_a["latest_position"]["latitude"] == -18.5
    assert trip_b["driver_name"] == "Driver B"
    assert trip_b["vehicle"]["plate"] == "ZZZ9Z99"
    assert trip_b["latest_position"]["latitude"] == -23.4
    assert trip_b["route"]["name"] == "Exclusive route B"
    assert trip_b["route"]["geometry"] != trip_a["route"]["geometry"]
    assert "Driver B" not in str(trip_a)
    assert "ZZZ9Z99" not in str(trip_a)
    assert "ABC1D23" not in str(trip_b)


def test_public_places_use_only_sites_linked_to_authorized_trip_route(portal):
    client, service, repository = portal
    now = datetime.now(timezone.utc).isoformat()
    with repository.connect() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS operational_sites (
               id TEXT PRIMARY KEY,name TEXT NOT NULL,operation TEXT NOT NULL,
               latitude REAL NOT NULL,longitude REAL NOT NULL,active INTEGER NOT NULL DEFAULT 1)"""
        )
        connection.executemany(
                "INSERT INTO operational_sites(id,name,operation,latitude,longitude,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            [
                    ("site-origin", "SOC_MG_BETIM/MG", "test", -19.98, -44.26, now, now),
                    ("site-destination", "SoC_PE_JABOATAO DOS GUARARAPES/PE", "test", -8.20, -34.96, now, now),
                    ("site-other", "CD_SP_OUTRA_VIAGEM/SP", "test", -23.5, -46.6, now, now),
            ],
        )
        connection.execute(
            """INSERT INTO route_site_links
               (route_id,origin_site_id,destination_site_id,created_at,updated_at)
               VALUES(?,?,?,?,?)""",
            ("route-1", "site-origin", "site-destination", now, now),
        )
        connection.execute(
            "UPDATE route_configs SET name=? WHERE id=?",
            ("Betim/MG → Jaboatão dos Guararapes/PE", "route-1"),
        )
    _, token = service.create_link("secret-trip-key", None, "test")
    body = client.get(f"/api/public/trips/{token}").json()

    assert body["route"]["origin"] == {
        "name": "SOC Betim", "city": "Betim", "state": "MG",
        "coordinate": {"latitude": -19.98, "longitude": -44.26},
    }
    assert body["route"]["destination"] == {
        "name": "SOC Jaboatao Dos Guararapes",
        "city": "Jaboatão dos Guararapes", "state": "PE",
        "coordinate": {"latitude": -8.2, "longitude": -34.96},
    }
    serialized = str(body)
    assert "site-origin" not in serialized
    assert "site-destination" not in serialized
    assert "site-other" not in serialized
    assert "Outra Viagem" not in serialized


def test_generated_url_token_can_be_read_immediately(portal):
    client, _, _ = portal
    created = client.post(
        "/api/trips/secret-trip-key/public-link", headers=auth(), json={}
    )
    token = created.json()["url"].rsplit("/", 1)[1]
    response = client.get(f"/api/public/trips/{token}")
    assert response.status_code == 200
    assert response.json()["driver_name"] == "João da Silva"
    assert response.json()["route"]["origin"]["name"] == "Betim/MG"
    assert response.json()["route"]["destination"]["name"] == "Jaboatão/PE"


def test_trip_without_eta_or_location_remains_available(portal):
    client, service, repository = portal
    repository.ensure_trip("sparse-trip", "GHI7J89", "provider-sparse", None)
    repository.update_trip(
        "sparse-trip",
        state="PROGRAMADA",
        current_driver="Motorista sem posição",
    )
    _, token = service.create_link("sparse-trip", None, "test")
    response = client.get(f"/api/public/trips/{token}")
    assert response.status_code == 200
    body = response.json()
    assert body["estimated_arrival_at"] is None
    assert body["latest_position"] is None
    assert body["route"]["geometry"] == []


def test_unnamed_route_control_points_are_not_exposed_as_public_markers(portal):
    client, service, repository = portal
    with repository.connect() as connection:
        connection.execute(
            """INSERT INTO route_geometry_versions
               (route_id,version,source,geometry_json,mandatory_points_json,corridor_m,
                segment_tolerances_json,active,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                "route-1",
                "tomtom-mandatory-list-regression",
                "test",
                json.dumps([[-19.98, -44.26], [-8.20, -34.96]]),
                json.dumps([
                    [-19.98, -44.26],
                    [-16.16, -42.31],
                    [-8.20, -34.96],
                    {"name": "Parada operacional validada", "latitude": -12.5, "longitude": -39.1},
                    {"description": "", "latitude": -13.0, "longitude": -40.0},
                ]),
                300,
                "[]",
                1,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    _, token = service.create_link("secret-trip-key", None, "test")
    response = client.get(f"/api/public/trips/{token}")
    assert response.status_code == 200
    body = response.json()
    assert body["route"]["important_points"] == [
        {
            "name": "Parada operacional validada",
            "coordinate": {"latitude": -12.5, "longitude": -39.1},
        },
    ]


def test_optional_vehicle_phone_diagnostic_and_dates_do_not_break_public_trip(portal, monkeypatch):
    client, service, repository = portal
    original_trip = repository.trip

    def sparse_vehicle(trip_key):
        trip = original_trip(trip_key)
        if trip:
            trip["plate"] = None
            trip["last_position_at"] = "not-a-date"
            trip["updated_at"] = "also-not-a-date"
        return trip

    monkeypatch.setattr(service.operations, "trip", sparse_vehicle)
    monkeypatch.setattr(get_settings(), "public_trip_contact_phone", "")
    _, token = service.create_link("secret-trip-key", None, "test")
    response = client.get(f"/api/public/trips/{token}")
    assert response.status_code == 200
    body = response.json()
    assert body["vehicle"]["plate"] is None
    assert body["central_contact"]["phone"] is None
    assert body["estimated_arrival_at"] is None


def test_external_integrations_are_not_called_during_public_lookup(portal, monkeypatch):
    client, service, _ = portal

    def external_failure(*_args, **_kwargs):
        raise RuntimeError("external integration unavailable")

    monkeypatch.setattr("app.integrations.tomtom.TomTomClient.get_route", external_failure)
    monkeypatch.setattr("app.integrations.weather.WeatherClient.get_current_weather", external_failure)
    monkeypatch.setattr("app.integrations.trafegus.TrafegusClient.get_incidents", external_failure)
    _, token = service.create_link("secret-trip-key", None, "test")
    assert client.get(f"/api/public/trips/{token}").status_code == 200


def test_access_audit_failure_does_not_break_public_response(portal, monkeypatch, caplog):
    client, service, _ = portal
    _, token = service.create_link("secret-trip-key", None, "test")

    def audit_failure(_link_id):
        raise RuntimeError("audit database temporarily unavailable")

    monkeypatch.setattr(service.repository, "record_access", audit_failure)
    with caplog.at_level(logging.ERROR, logger="app.api.public_trip"):
        response = client.get(f"/api/public/trips/{token}")
    assert response.status_code == 200
    assert "Public trip access audit failed" in caplog.text


def test_finishing_trip_revokes_active_link_and_returns_410(portal):
    client, service, repository = portal
    _, token = service.create_link("secret-trip-key", None, "test")
    operations = TripOperationsService(repository)
    operations.manual_action(
        "secret-trip-key",
        "finalize",
        operator="operador",
        justification="Entrega concluída no destino",
    )

    response = client.get(f"/api/public/trips/{token}")
    assert response.status_code == 410
    assert response.json() == {
        "detail": "Esta viagem foi finalizada e o link não está mais disponível.",
        "reason": "trip_finished",
    }
    with repository.connect() as connection:
        link = connection.execute(
            "SELECT active,revoked_at FROM public_trip_links WHERE token_hash=?",
            (service.token_hash(token),),
        ).fetchone()
        event = connection.execute(
            """SELECT event_type FROM public_trip_link_events
               WHERE public_link_id=(
                 SELECT id FROM public_trip_links WHERE token_hash=?
               ) ORDER BY id DESC LIMIT 1""",
            (service.token_hash(token),),
        ).fetchone()
    assert link["active"] == 0
    assert link["revoked_at"] is not None
    assert event["event_type"] == "TRIP_FINISHED"
    new_link = client.post(
        "/api/trips/secret-trip-key/public-link", headers=auth(), json={}
    )
    assert new_link.status_code == 422


def test_missing_trip_has_consistent_internal_404(portal):
    client, _, _ = portal
    for method in ("post", "get", "delete"):
        response = getattr(client, method)(
            "/api/trips/missing-trip/public-link",
            headers=auth(),
            **({"json": {}} if method == "post" else {}),
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "Trip not found"}


def test_unexpected_error_logs_only_token_fingerprint(portal, caplog):
    client, service, _ = portal
    token = "S" * 43

    def fail(_: str):
        raise RuntimeError("database unavailable")

    service.resolve = fail
    with caplog.at_level(logging.ERROR, logger="app.api.public_trip"):
        response = client.get(f"/api/public/trips/{token}")
    assert response.status_code == 500
    assert response.json() == {"detail": "Public trip temporarily unavailable"}
    assert token not in caplog.text
    assert hashlib.sha256(token.encode()).hexdigest()[:8] in caplog.text


def test_migration_runner_is_idempotent(tmp_path):
    database = tmp_path / "migration.db"
    migrate(database)
    migrate(database)
    repository = OperationsRepository(database)
    with repository.connect() as connection:
        tables = {
            row["name"] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        trip_columns = {row["name"] for row in connection.execute("PRAGMA table_info(operational_trips)")}
        incident_columns = {row["name"] for row in connection.execute("PRAGMA table_info(traffic_incidents)")}
        indexes = {
            row["name"] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
    assert {"public_trip_links", "public_trip_link_events"} <= tables
    assert {"loaded_at", "trailer_plate"} <= trip_columns
    assert {"publicly_visible", "public_title", "public_description"} <= incident_columns
    assert "idx_incidents_public_route" in indexes
