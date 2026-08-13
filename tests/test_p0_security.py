from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app import main as main_module
from app.core import security
from app.core.config import get_settings
from app.core.middleware import _limiter
from app.core.security import Permission, Principal, Role, create_panel_session, hash_password, require_permission
from app.storage.migrations import migrate_database


@pytest.fixture(autouse=True)
def isolated_security_database(tmp_path, monkeypatch):
    database = tmp_path / "security.sqlite"
    migrate_database(database)
    monkeypatch.setattr(get_settings(), "operations_database_path", database)


def real_security_boundary():
    for permission in Permission:
        main_module.app.dependency_overrides.pop(require_permission(permission), None)


def configure_admin(monkeypatch, password: str = "correct-horse-123"):
    settings = get_settings()
    monkeypatch.setattr(settings, "panel_admin_username", "security-admin")
    monkeypatch.setattr(settings, "panel_admin_password_hash", hash_password(password))
    monkeypatch.setattr(settings, "panel_admin_role", Role.ADMIN.value)
    monkeypatch.setattr(settings, "panel_session_secret", "security-test-session-secret-with-32-bytes")
    return settings


def test_anonymous_operational_and_external_endpoints_are_blocked(monkeypatch):
    real_security_boundary()
    called = False

    async def forbidden_external_call(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("external client must not be called")

    monkeypatch.setattr(main_module.fleet_tracking_service, "get_snapshot", forbidden_external_call)
    client = TestClient(main_module.app)
    for method, path, payload in (
        ("get", "/fleet/active", None), ("get", "/integrations/status", None),
        ("get", "/operations/routes", None), ("get", "/traffic/incidents", None),
        ("get", "/deviations/active", None), ("get", "/angellira/admin", None),
        ("get", "/operational-sites", None), ("post", "/routes/preview", {}),
        ("post", "/trafegus/vehicles/consult", {"plate": "ABC1D23"}),
    ):
        assert client.request(method, path, json=payload).status_code == 401, path
    assert called is False


def test_login_logout_hash_and_session_role(monkeypatch):
    configure_admin(monkeypatch); _limiter.clear("login:testclient")
    client = TestClient(main_module.app)
    assert client.post("/api/auth/session", json={"username": "security-admin", "password": "wrong-password"}).status_code == 401
    login = client.post("/api/auth/session", json={"username": "security-admin", "password": "correct-horse-123"})
    assert login.status_code == 200 and login.json()["role"] == Role.ADMIN.value
    assert "correct-horse-123" not in get_settings().panel_admin_password_hash
    assert "httponly" in login.headers["set-cookie"].lower() and "samesite=strict" in login.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").status_code == 200
    assert client.delete("/api/auth/session").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_expired_session_is_rejected(monkeypatch):
    configure_admin(monkeypatch); issued = 2_000_000_000
    monkeypatch.setattr(security.time, "time", lambda: issued)
    token, _ = create_panel_session(Principal("security-admin", Role.ADMIN))
    monkeypatch.setattr(security.time, "time", lambda: issued + 9 * 3600)
    client = TestClient(main_module.app); client.cookies.set(security.PANEL_SESSION_COOKIE, token)
    assert client.get("/api/auth/me").status_code == 401


def test_authenticated_unapproved_role_receives_403(monkeypatch):
    settings = configure_admin(monkeypatch); real_security_boundary()
    monkeypatch.setattr(settings, "panel_admin_username", "read-user")
    monkeypatch.setattr(settings, "panel_admin_role", Role.READ_ONLY.value)
    token, _ = create_panel_session(Principal("read-user", Role.READ_ONLY))
    client = TestClient(main_module.app); client.cookies.set(security.PANEL_SESSION_COOKIE, token)
    assert client.get("/operations/routes").status_code == 403
    assert client.get("/fleet/active").status_code == 403


def test_login_rate_limiting(monkeypatch):
    settings = configure_admin(monkeypatch)
    monkeypatch.setattr(settings, "login_rate_limit_attempts", 3)
    _limiter.clear("login:testclient"); client = TestClient(main_module.app)
    statuses = [client.post("/api/auth/session", json={"username": "invalid", "password": "invalid-password"}).status_code for _ in range(4)]
    assert statuses == [401, 401, 401, 429]


def test_cors_and_production_csrf(monkeypatch):
    settings = configure_admin(monkeypatch)
    client = TestClient(main_module.app)
    allowed = client.options("/operations/routes", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    denied = client.options("/operations/routes", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert denied.headers.get("access-control-allow-origin") is None
    monkeypatch.setattr(settings, "app_environment", "production")
    token, _ = create_panel_session(Principal("security-admin", Role.ADMIN)); client.cookies.set(security.PANEL_SESSION_COOKIE, token)
    assert client.delete("/api/auth/session", headers={"Origin": "https://evil.example"}).status_code == 403


def test_security_headers_are_present():
    response = TestClient(main_module.app).get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
