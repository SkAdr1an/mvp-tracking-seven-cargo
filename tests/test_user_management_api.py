from __future__ import annotations

from fastapi.testclient import TestClient

from app import main as main_module
from app.core.config import get_settings
from app.core.security import (
    PANEL_SESSION_COOKIE,
    Permission,
    Principal,
    Role,
    configured_user,
    create_panel_session,
    hash_password,
    validate_panel_session,
)
from app.storage.migrations import migrate_database
from app.storage.users import UserRepository


def setup_runtime(tmp_path, monkeypatch):
    database = tmp_path / "users.sqlite"
    migrate_database(database)
    settings = get_settings()
    monkeypatch.setattr(settings, "operations_database_path", database)
    monkeypatch.setattr(settings, "panel_session_secret", "phase-four-session-secret-32-bytes")
    monkeypatch.setattr(settings, "panel_users_file", None)
    monkeypatch.setattr(settings, "panel_admin_username", "")
    monkeypatch.setattr(settings, "panel_admin_password_hash", "")
    return database


def principal(database, username, role):
    identity = UserRepository(database).create(
        username=username,
        display_name=username,
        password_hash=hash_password("valid-password-123"),
        role_code=role,
    )
    return Principal(
        identity.username,
        Role(role),
        user_id=identity.id,
        display_name=identity.display_name,
        permissions=frozenset(Permission(value) for value in identity.permissions),
    )


def client_for(user):
    token, _ = create_panel_session(user)
    client = TestClient(main_module.app)
    client.cookies.set(PANEL_SESSION_COOKIE, token)
    return client


def test_user_admin_crud_security_and_no_hash(tmp_path, monkeypatch):
    database = setup_runtime(tmp_path, monkeypatch)
    admin = principal(database, "admin.one", "ADMIN")
    gr = principal(database, "gr.one", "GR")
    monitoring = principal(database, "monitor.one", "MONITORING")

    assert TestClient(main_module.app).get("/api/users").status_code == 401
    assert client_for(gr).get("/api/users").status_code == 403
    assert client_for(monitoring).get("/api/users").status_code == 403

    client = client_for(admin)
    created = client.post(
        "/api/users",
        json={
            "display_name": "Novo Usuário",
            "username": "new.user",
            "role": "MONITORING",
            "password": "initial-pass-123",
        },
    )
    assert created.status_code == 201
    assert "password_hash" not in created.text.lower()
    user_id = created.json()["id"]

    listed = client.get("/api/users")
    assert listed.status_code == 200
    assert any(item["id"] == user_id for item in listed.json()["users"])
    assert "password_hash" not in listed.text.lower()
    assert client.post(
        "/api/users",
        json={
            "display_name": "Duplicado",
            "username": "new.user",
            "role": "GR",
            "password": "initial-pass-123",
        },
    ).status_code == 409
    assert client.post(
        "/api/users",
        json={
            "display_name": "Curta",
            "username": "short.pass",
            "role": "GR",
            "password": "short",
        },
    ).status_code == 422
    assert client.post(
        "/api/users",
        json={
            "display_name": "Perfil",
            "username": "bad.role",
            "role": "ROOT",
            "password": "initial-pass-123",
        },
    ).status_code == 422

    active_user = principal(database, "active.session", "MONITORING")
    active_token, _ = create_panel_session(active_user)
    assert client.post(f"/api/users/{active_user.user_id}/deactivate").status_code == 200
    assert validate_panel_session(active_token) is None
    assert client.post(f"/api/users/{active_user.user_id}/activate").json()["status"] == "ACTIVE"

    role_token, _ = create_panel_session(active_user)
    assert client.patch(f"/api/users/{active_user.user_id}", json={"role": "GR"}).json()["role"] == "GR"
    assert validate_panel_session(role_token) is None

    configured = configured_user("active.session")
    assert configured is not None
    active_user = configured[0]
    password_token, _ = create_panel_session(active_user)
    reset = client.post(
        f"/api/users/{active_user.user_id}/reset-password",
        json={"password": "replacement-pass-123"},
    )
    assert reset.status_code == 200
    assert validate_panel_session(password_token) is None


def test_last_admin_and_legacy_admin_protections(tmp_path, monkeypatch):
    database = setup_runtime(tmp_path, monkeypatch)
    admin = principal(database, "only.admin", "ADMIN")
    client = client_for(admin)
    assert client.post(f"/api/users/{admin.user_id}/deactivate").status_code == 409
    assert client.patch(f"/api/users/{admin.user_id}", json={"role": "GR"}).status_code == 409

    settings = get_settings()
    monkeypatch.setattr(settings, "panel_admin_username", "legacy.admin")
    monkeypatch.setattr(settings, "panel_admin_password_hash", hash_password("legacy-password-123"))
    monkeypatch.setattr(settings, "panel_admin_role", "Administrador")
    legacy = TestClient(main_module.app)
    assert legacy.post(
        "/api/auth/session",
        json={"username": "legacy.admin", "password": "legacy-password-123"},
    ).status_code == 200
    assert legacy.get("/api/users").status_code == 409
