from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.api import operations as operations_api
from app.api import traffic as traffic_api
from app.core.config import get_settings
from app.core.security import (
    PANEL_SESSION_COOKIE, Permission, Principal, Role, create_panel_session, hash_password,
    require_permission,
)
from app.storage.migrations import migrate_database
from app.storage.users import UserRepository


READ_CASES = [
    ("get", "/integrations/status", None, "dashboard:read"),
    ("get", "/operations/trips/missing", None, "trips:read"),
    ("get", "/tracking/drivers/active", None, "drivers:read"),
    ("get", "/traffic/incidents/missing", None, "incidents:read"),
    ("get", "/operations/exceptions", None, "stops:read"),
]

MUTATION_CASES = [
    ("put", "/operations/trips/missing/plan", {}, "trips:edit"),
    ("post", "/operations/trips/missing/actions", {
        "action": "finalize", "justification": "Finalizacao confirmada",
    }, "trips:finalize"),
    ("post", "/operations/trips/missing/actions", {
        "action": "reopen", "justification": "Reabertura confirmada",
    }, "trips:reopen"),
    ("post", "/operations/trips/missing/actions", {
        "action": "correct_times", "justification": "Horario corrigido",
    }, "trips:status-correct"),
    ("post", "/operations/trips/missing/actions", {
        "action": "undo_detection", "justification": "Deteccao desfeita",
    }, "trips:status-correct"),
    ("post", "/operations/trips/missing/route", {"route_id": "missing"}, "trips:assign-route"),
    ("post", "/operations/trips/missing/driver-association", {
        "action": "remove", "confirmed": True, "operator": "forged",
        "justification": "Associacao removida",
    }, "trips:assign-driver"),
    ("post", "/operations/trips/missing/report", None, "reports:generate"),
    ("post", "/api/trips/missing/public-link", {}, "public-links:manage"),
    ("post", "/operations/stops/999/justification", {
        "reason": "OTHER", "justification": "Parada confirmada",
    }, "stops:justify"),
    ("post", "/traffic/manual", {
        "route_id": "missing", "description": "Ocorrencia confirmada",
        "latitude": -23.0, "longitude": -46.0,
        "started_at": "2026-08-13T10:00:00-03:00",
        "expires_at": "2026-08-13T11:00:00-03:00",
        "information_source": "Central", "responsible_user": "forged",
        "justification": "Registro operacional",
    }, "incidents:create"),
    ("patch", "/traffic/manual/missing", {
        "changes": {}, "action": "CONFIRMED", "justification": "Confirmacao estrutural",
        "user": "forged",
    }, "incidents:edit-structural"),
    ("post", "/routes/preview", {}, "integrations:invoke"),
    ("post", "/operations/return-candidates/999/decision", {
        "decision": "LATER", "operator": "forged",
    }, "trips:edit"),
]

ROLE_CODES = ("ADMIN", "GR", "MONITORING")


def _configure(database, monkeypatch) -> None:
    migrate_database(database)
    settings = get_settings()
    monkeypatch.setattr(settings, "operations_database_path", database)
    monkeypatch.setattr(settings, "panel_session_secret", "granular-authorization-secret-32-bytes")
    monkeypatch.setattr(settings, "panel_users_file", None)
    monkeypatch.setattr(settings, "panel_admin_username", "")
    monkeypatch.setattr(settings, "panel_admin_password_hash", "")
    monkeypatch.setattr(settings, "public_trip_token_pepper", "test-public-trip-pepper")
    for permission in Permission:
        main_module.app.dependency_overrides.pop(require_permission(permission), None)


def _client_for(database, role_code: str) -> tuple[TestClient, Principal]:
    repository = UserRepository(database)
    username = f"phase2.{role_code.lower()}"
    identity = repository.create(
        username=username, display_name=f"Phase 2 {role_code}",
        password_hash=hash_password("phase-2-password"), role_code=role_code,
    )
    principal = Principal(
        identity.username, Role(role_code), user_id=identity.id,
        display_name=identity.display_name,
        permissions=frozenset(Permission(code) for code in identity.permissions),
    )
    token, _ = create_panel_session(principal)
    client = TestClient(main_module.app)
    client.cookies.set(PANEL_SESSION_COOKIE, token)
    return client, principal


@pytest.mark.parametrize("method,path,payload,permission", READ_CASES + MUTATION_CASES)
@pytest.mark.parametrize("role_code", ROLE_CODES)
def test_endpoint_method_role_matrix(
    tmp_path, monkeypatch, role_code, method, path, payload, permission,
) -> None:
    database = tmp_path / f"{role_code}.sqlite"
    _configure(database, monkeypatch)
    client, principal = _client_for(database, role_code)
    response = client.request(method, path, json=payload)
    if principal.has_permission(permission):
        assert response.status_code not in {401, 403}, (method, path, role_code, response.text)
    else:
        assert response.status_code == 403, (method, path, role_code, response.text)


@pytest.mark.parametrize("method,path,payload,_permission", MUTATION_CASES)
def test_mutations_are_401_without_a_session(
    tmp_path, monkeypatch, method, path, payload, _permission,
) -> None:
    _configure(tmp_path / "anonymous.sqlite", monkeypatch)
    response = TestClient(main_module.app).request(method, path, json=payload)
    assert response.status_code == 401, (method, path, response.text)


@pytest.mark.parametrize("action", ["finalize", "reopen"])
def test_privileged_trip_action_permission_is_checked_before_mutation(tmp_path, monkeypatch, action) -> None:
    database = tmp_path / f"action-{action}.sqlite"
    _configure(database, monkeypatch)
    client, _ = _client_for(database, "MONITORING")
    calls: list[str] = []
    monkeypatch.setattr(
        operations_api.trip_operations_service, "manual_action",
        lambda *args, **kwargs: calls.append(action),
    )
    response = client.post(
        "/operations/trips/forbidden/actions",
        json={"action": action, "justification": "Operacao nao autorizada"},
    )
    assert response.status_code == 403
    assert calls == []


def test_monitoring_status_correction_records_authenticated_actor(tmp_path, monkeypatch) -> None:
    database = tmp_path / "monitoring-correction.sqlite"
    _configure(database, monkeypatch)
    client, principal = _client_for(database, "MONITORING")
    captured: dict[str, object] = {}
    monkeypatch.setattr(operations_api.trip_operations_service, "manual_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(operations_api.trip_operations_service, "detail", lambda *_: {"trip_key": "audited-trip"})
    monkeypatch.setattr(
        operations_api, "_audit",
        lambda actor, action, resource, **values: captured.update({
            "actor": actor, "action": action.value, "resource": resource, **values,
        }),
    )

    response = client.post(
        "/operations/trips/audited-trip/actions",
        json={
            "action": "correct_times",
            "justification": "Correção operacional identificada",
            "corrections": {"started_at": "2026-08-27T12:00:00+00:00"},
        },
    )

    assert response.status_code == 200
    assert captured["actor"] == principal
    assert captured["action"] == "TRIP_STATUS_CORRECTED"
    assert captured["resource"] == "trip"
    assert captured["trip_key"] == "audited-trip"
    assert captured["justification"] == "Correção operacional identificada"


def test_incident_identity_comes_from_session_not_payload(tmp_path, monkeypatch) -> None:
    database = tmp_path / "identity.sqlite"
    _configure(database, monkeypatch)
    client, principal = _client_for(database, "MONITORING")
    captured: dict[str, object] = {}
    monkeypatch.setattr(traffic_api.traffic_monitoring_service.repository.operations, "route", lambda _: {"id": "route"})
    monkeypatch.setattr(
        traffic_api.traffic_monitoring_service, "create_manual",
        lambda values: captured.update(values) or values,
    )
    response = client.post("/traffic/manual", json={
        "route_id": "route", "description": "Ocorrencia operacional",
        "latitude": -23.0, "longitude": -46.0,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "information_source": "Central", "responsible_user": "admin.forged",
        "operator": "admin.forged", "role": "ADMIN", "permission": "users:manage",
        "justification": "Registro confirmado",
    })
    assert response.status_code == 201
    assert captured["responsible_user"] == principal.username
    assert captured["responsible_user"] != "admin.forged"


def test_legacy_admin_receives_compatible_permissions(tmp_path, monkeypatch) -> None:
    database = tmp_path / "legacy.sqlite"
    _configure(database, monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "panel_admin_username", "legacy.phase2")
    monkeypatch.setattr(settings, "panel_admin_password_hash", hash_password("legacy-password"))
    monkeypatch.setattr(settings, "panel_admin_role", "Administrador")
    client = TestClient(main_module.app)
    login = client.post(
        "/api/auth/session", json={"username": "legacy.phase2", "password": "legacy-password"},
    )
    assert login.status_code == 200
    assert set(login.json()["permissions"]) == {permission.value for permission in Permission}
    assert client.get("/angellira/admin").status_code != 403


def test_persistent_identity_with_no_grants_does_not_fall_back_to_role_defaults() -> None:
    principal = Principal(
        "no.grants", Role.ADMIN, user_id="persistent-id", permissions=frozenset(),
    )
    assert not principal.has_permission(Permission.TRIPS_READ)


def test_gr_cannot_manage_users_roles_or_settings() -> None:
    principal = Principal("gr", Role.GR)
    for permission in (
        Permission.USERS_READ, Permission.USERS_MANAGE, Permission.ROLES_MANAGE,
        Permission.SETTINGS_READ, Permission.SETTINGS_MANAGE,
    ):
        assert not principal.has_permission(permission)


def test_legacy_permission_aliases_are_only_compatibility_names() -> None:
    assert Permission.OPERATIONAL_READ is Permission.TRIPS_READ
    assert Permission.OPERATIONAL_WRITE is Permission.TRIPS_EDIT
    router_sources = "\n".join(
        (Path(main_module.__file__).parent / relative).read_text(encoding="utf-8")
        for relative in (
            "api/operations.py", "api/route_monitoring.py", "api/traffic.py",
            "api/operational_sites.py", "api/angellira.py", "integrations/driver_tracking.py",
        )
    )
    assert "Permission.OPERATIONAL_READ" not in router_sources
    assert "Permission.OPERATIONAL_WRITE" not in router_sources
    assert "require_panel_username" not in router_sources
