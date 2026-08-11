from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.middleware import _limiter
from app.core.security import PANEL_SESSION_COOKIE, Role, hash_password
from app.main import app
from app.storage.migrations import migrate_database


def _write_users(path, *, active=True, role=Role.ADMIN, password="first-password-123"):
    path.write_text(json.dumps({"users": [{
        "username": "session-user", "password_hash": hash_password(password),
        "role": role.value, "active": active,
    }]}), encoding="utf-8")


def _configured_client(tmp_path, monkeypatch):
    database = tmp_path / "sessions.sqlite"
    migrate_database(database)
    users = tmp_path / "users.json"
    _write_users(users)
    settings = get_settings()
    monkeypatch.setattr(settings, "operations_database_path", database)
    monkeypatch.setattr(settings, "panel_users_file", users)
    monkeypatch.setattr(settings, "panel_admin_username", "")
    monkeypatch.setattr(settings, "panel_admin_password_hash", "")
    monkeypatch.setattr(settings, "panel_session_secret", "session-revocation-test-secret-32-bytes")
    _limiter.clear("login:testclient")
    return TestClient(app), users


def _login(client):
    response = client.post("/api/auth/session", json={
        "username": "session-user", "password": "first-password-123",
    })
    assert response.status_code == 200
    return response.cookies.get(PANEL_SESSION_COOKIE)


def test_logout_revokes_captured_cookie_and_survives_new_client(tmp_path, monkeypatch):
    client, _ = _configured_client(tmp_path, monkeypatch)
    captured = _login(client)
    assert client.delete("/api/auth/session").status_code == 204
    replay = TestClient(app)
    replay.cookies.set(PANEL_SESSION_COOKIE, captured)
    assert replay.get("/api/auth/me").status_code == 401


def test_user_state_role_and_password_changes_invalidate_session(tmp_path, monkeypatch):
    client, users = _configured_client(tmp_path, monkeypatch)
    token = _login(client)
    for change in (
        {"active": False, "role": Role.ADMIN, "password": "first-password-123"},
        {"active": True, "role": Role.READ_ONLY, "password": "first-password-123"},
        {"active": True, "role": Role.ADMIN, "password": "changed-password-123"},
    ):
        _write_users(users, **change)
        probe = TestClient(app)
        probe.cookies.set(PANEL_SESSION_COOKIE, token)
        assert probe.get("/api/auth/me").status_code == 401
        _write_users(users)
        token = _login(client)


def test_tampered_opaque_token_is_rejected(tmp_path, monkeypatch):
    client, _ = _configured_client(tmp_path, monkeypatch)
    token = _login(client)
    client.cookies.set(PANEL_SESSION_COOKIE, token[:-1] + ("A" if token[-1] != "A" else "B"))
    assert client.get("/api/auth/me").status_code == 401
