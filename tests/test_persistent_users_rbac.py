from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.core.config import get_settings
from app.core.security import (
    PANEL_SESSION_COOKIE,
    Permission,
    Principal,
    Role,
    create_panel_session,
    hash_password,
    validate_panel_session,
)
from app.storage.migrations import SCHEMA_VERSION, migrate_database, validate_database_schema
from app.storage.users import UserRepository
from app.scripts.import_legacy_panel_user import import_legacy_user


ROLE_MATRIX = {
    "ADMIN": {permission.value for permission in Permission},
    "GR": {
        "dashboard:read", "trips:read", "drivers:read", "incidents:read", "stops:read",
        "trips:edit", "trips:status-correct", "trips:finalize", "trips:cancel",
        "trips:archive", "trips:reopen", "trips:assign-route", "trips:assign-driver",
        "reports:generate", "public-links:manage", "observations:create",
        "observations:correct-own", "stops:justify", "incidents:create",
        "incidents:edit-structural", "integrations:invoke", "audit:read-operational",
    },
    "MONITORING": {
        "dashboard:read", "trips:read", "drivers:read", "incidents:read", "stops:read",
        "observations:create", "observations:correct-own", "stops:justify",
        "incidents:create", "audit:read-operational", "trips:status-correct",
        "reports:generate", "public-links:manage",
    },
}


def digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def downgrade_to_schema_ten(database) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("ALTER TABLE panel_sessions DROP COLUMN role_code_snapshot")
        connection.execute("ALTER TABLE panel_sessions DROP COLUMN user_id")
        connection.execute("DROP TABLE role_permissions")
        connection.execute("DROP TABLE users")
        connection.execute("DROP TABLE permissions")
        connection.execute("DROP TABLE roles")
        connection.execute("DELETE FROM schema_migrations")
        connection.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(10,'legacy')")


def configure_runtime(database, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "operations_database_path", database)
    monkeypatch.setattr(settings, "panel_session_secret", "persistent-rbac-session-secret-32-bytes")
    monkeypatch.setattr(settings, "panel_admin_username", "")
    monkeypatch.setattr(settings, "panel_admin_password_hash", "")
    monkeypatch.setattr(settings, "panel_users_file", None)


def create_user(repository: UserRepository, username: str, role: str):
    return repository.create(
        username=username, display_name=f"Nome {username}",
        password_hash=hash_password(f"password-{username}-secure"), role_code=role,
    )


def test_new_database_has_rbac_schema_seeds_and_exact_matrix(tmp_path) -> None:
    database = tmp_path / "new.sqlite"
    migrate_database(database)
    validate_database_schema(database)
    with sqlite3.connect(database) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"users", "roles", "permissions", "role_permissions"} <= tables
        assert {row[0] for row in connection.execute("SELECT code FROM roles")} == set(ROLE_MATRIX)
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        permissions = {row[0] for row in connection.execute("SELECT code FROM permissions")}
        assert permissions == ROLE_MATRIX["ADMIN"]
        assert "trips:delete-physical" not in permissions
        for role, expected in ROLE_MATRIX.items():
            actual = {row[0] for row in connection.execute(
                """SELECT p.code FROM permissions p JOIN role_permissions rp ON rp.permission_id=p.id
                   WHERE rp.role_id=?""", (role,)
            )}
            assert actual == expected
        columns = {row[1] for row in connection.execute("PRAGMA table_info(panel_sessions)")}
        assert {"user_id", "role_code_snapshot"} <= columns
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == SCHEMA_VERSION


def test_schema_ten_upgrade_preserves_operational_data_and_old_session(tmp_path) -> None:
    database = tmp_path / "schema-ten.sqlite"
    migrate_database(database)
    downgrade_to_schema_ten(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """INSERT INTO operational_trips(trip_key,plate,state,created_at,updated_at)
               VALUES('preserved-trip','ABC1D23','PROGRAMADA','before','before')"""
        )
        connection.execute(
            """INSERT INTO panel_sessions(id,token_hash,username,role,user_fingerprint,created_at,expires_at)
               VALUES('old','hash','legacy','Administrador','fingerprint',1,9999999999)"""
        )
    migrate_database(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT plate FROM operational_trips WHERE trip_key='preserved-trip'").fetchone()[0] == "ABC1D23"
        assert connection.execute("SELECT username,user_id,role_code_snapshot FROM panel_sessions WHERE id='old'").fetchone() == ("legacy", None, None)


def test_migration_is_idempotent_and_rolls_back_upgrade_failure(tmp_path) -> None:
    database = tmp_path / "repeat.sqlite"
    migrate_database(database)
    first = digest(database)
    migrate_database(database)
    assert digest(database) == first
    downgrade_to_schema_ten(database)
    before = digest(database)
    with pytest.raises(sqlite3.OperationalError):
        migrate_database(database, failure_probe=True)
    assert digest(database) == before


def test_user_constraints_active_inactive_and_no_physical_delete_api(tmp_path) -> None:
    database = tmp_path / "users.sqlite"
    migrate_database(database)
    repository = UserRepository(database)
    user = create_user(repository, "first.user", "GR")
    assert user.active and repository.by_id(user.id) == user
    with pytest.raises(ValueError):
        create_user(repository, "FIRST.USER", "GR")
    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO users(id,username,display_name,password_hash,status,role_id,
                   created_at,updated_at,password_changed_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                ("bad", "bad", "Bad", "scrypt$bad", "DISABLED", "GR", "now", "now", "now"),
            )
    inactive = repository.inactivate(user.id)
    assert inactive.status == "INACTIVE" and inactive.id == user.id
    assert not hasattr(repository, "delete")


@pytest.mark.parametrize("role_code", ["ADMIN", "GR", "MONITORING"])
def test_persistent_principal_propagates_identity_and_permissions(tmp_path, monkeypatch, role_code) -> None:
    database = tmp_path / f"{role_code}.sqlite"
    migrate_database(database)
    configure_runtime(database, monkeypatch)
    repository = UserRepository(database)
    user = create_user(repository, f"user.{role_code.lower()}", role_code)
    token, _ = create_panel_session(Principal(
        user.username, Role(role_code), user_id=user.id, display_name=user.display_name,
        permissions=frozenset(Permission(value) for value in user.permissions),
    ))
    principal = validate_panel_session(token)
    assert principal is not None
    assert principal.user_id == user.id
    assert principal.display_name == user.display_name
    assert {value.value for value in principal.permissions} == ROLE_MATRIX[role_code]
    client = TestClient(main_module.app)
    client.cookies.set(PANEL_SESSION_COOKIE, token)
    payload = client.get("/api/auth/me").json()
    assert payload["user_id"] == user.id and payload["display_name"] == user.display_name
    assert set(payload["permissions"]) == ROLE_MATRIX[role_code]
    assert "password_hash" not in payload


def test_inactive_user_cannot_authenticate_and_identity_mutations_invalidate_sessions(tmp_path, monkeypatch) -> None:
    database = tmp_path / "invalidation.sqlite"
    migrate_database(database)
    configure_runtime(database, monkeypatch)
    repository = UserRepository(database)
    for action in ("role", "password", "inactive"):
        user = create_user(repository, f"user.{action}", "GR")
        principal = Principal(
            user.username, Role.GR, user_id=user.id, display_name=user.display_name,
            permissions=frozenset(Permission(value) for value in user.permissions),
        )
        token, _ = create_panel_session(principal)
        assert validate_panel_session(token) is not None
        if action == "role":
            repository.change_role(user.id, "MONITORING")
        elif action == "password":
            repository.change_password(user.id, hash_password("replacement-password-secure"))
        else:
            repository.inactivate(user.id)
        assert validate_panel_session(token) is None
    inactive = repository.credentials_by_username("user.inactive")
    assert inactive is not None and not inactive.identity.active
    client = TestClient(main_module.app)
    assert client.post("/api/auth/session", json={
        "username": "user.inactive", "password": "password-user.inactive-secure",
    }).status_code == 401


def test_legacy_admin_and_users_file_remain_compatible(tmp_path, monkeypatch) -> None:
    database = tmp_path / "legacy.sqlite"
    migrate_database(database)
    settings = get_settings()
    monkeypatch.setattr(settings, "operations_database_path", database)
    monkeypatch.setattr(settings, "panel_session_secret", "legacy-compatible-session-secret-32")
    monkeypatch.setattr(settings, "panel_users_file", None)
    monkeypatch.setattr(settings, "panel_admin_username", "legacy.admin")
    monkeypatch.setattr(settings, "panel_admin_password_hash", hash_password("legacy-admin-password"))
    monkeypatch.setattr(settings, "panel_admin_role", "Administrador")
    client = TestClient(main_module.app)
    response = client.post("/api/auth/session", json={"username": "legacy.admin", "password": "legacy-admin-password"})
    assert response.status_code == 200 and response.json()["role"] == "ADMIN"

    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({"users": [{
        "username": "legacy.gr", "display_name": "Legacy GR",
        "password_hash": hash_password("legacy-file-password"), "role": "Gestor", "active": True,
    }]}), encoding="utf-8")
    monkeypatch.setattr(settings, "panel_users_file", users_file)
    response = TestClient(main_module.app).post(
        "/api/auth/session", json={"username": "legacy.gr", "password": "legacy-file-password"},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "GR" and response.json()["display_name"] == "Legacy GR"


def test_migrated_pre_v11_session_without_user_id_still_validates(tmp_path, monkeypatch) -> None:
    database = tmp_path / "old-session.sqlite"
    migrate_database(database)
    settings = get_settings()
    monkeypatch.setattr(settings, "operations_database_path", database)
    monkeypatch.setattr(settings, "panel_session_secret", "old-session-compatible-secret-32-bytes")
    monkeypatch.setattr(settings, "panel_users_file", None)
    monkeypatch.setattr(settings, "panel_admin_username", "old.admin")
    password_hash = hash_password("old-session-password")
    monkeypatch.setattr(settings, "panel_admin_password_hash", password_hash)
    monkeypatch.setattr(settings, "panel_admin_role", "Administrador")
    raw_token = "legacy-opaque-token"
    token_hash = hashlib.sha256(raw_token.encode("ascii")).hexdigest()
    fingerprint = hashlib.sha256(f"old.admin\0Administrador\0{password_hash}".encode()).hexdigest()
    with sqlite3.connect(database) as connection:
        connection.execute(
            """INSERT INTO panel_sessions(id,token_hash,username,role,user_fingerprint,
               created_at,expires_at,revoked_at,user_id,role_code_snapshot)
               VALUES('legacy',?,?,?,?,9999999998,9999999999,NULL,NULL,NULL)""",
            (token_hash, "old.admin", "Administrador", fingerprint),
        )
    principal = validate_panel_session(raw_token)
    assert principal is not None and principal.username == "old.admin" and principal.role == Role.ADMIN


def test_safe_user_objects_and_session_api_never_expose_password_hash(tmp_path) -> None:
    database = tmp_path / "safe.sqlite"
    migrate_database(database)
    repository = UserRepository(database)
    user = create_user(repository, "safe.user", "MONITORING")
    assert "password" not in repr(user).lower()
    assert not hasattr(repository.by_id(user.id), "password_hash")


def test_legacy_import_is_explicit_and_does_not_expose_or_invent_credentials(tmp_path, monkeypatch) -> None:
    database = tmp_path / "import.sqlite"
    migrate_database(database)
    settings = get_settings()
    monkeypatch.setattr(settings, "operations_database_path", database)
    monkeypatch.setattr(settings, "panel_users_file", None)
    monkeypatch.setattr(settings, "panel_session_secret", "legacy-import-session-secret-32-bytes")
    monkeypatch.setattr(settings, "panel_admin_username", "legacy.import")
    monkeypatch.setattr(settings, "panel_admin_password_hash", hash_password("legacy-import-password"))
    monkeypatch.setattr(settings, "panel_admin_role", "Administrador")
    repository = UserRepository(database)
    assert repository.by_username("legacy.import") is None
    legacy_login = TestClient(main_module.app).post(
        "/api/auth/session",
        json={"username": "legacy.import", "password": "legacy-import-password"},
    )
    legacy_token = legacy_login.cookies.get(PANEL_SESSION_COOKIE)
    assert legacy_login.status_code == 200 and legacy_token
    user_id = import_legacy_user("legacy.import", "Administrador Inicial")
    assert validate_panel_session(legacy_token) is None
    imported = repository.by_id(user_id)
    assert imported is not None and imported.role_code == "ADMIN"
    assert not hasattr(imported, "password_hash")
    repository.create(
        username="backup.admin", display_name="Backup Admin",
        password_hash=hash_password("backup-admin-password"), role_code="ADMIN",
    )
    repository.inactivate(user_id)
    blocked = TestClient(main_module.app).post(
        "/api/auth/session",
        json={"username": "legacy.import", "password": "legacy-import-password"},
    )
    assert blocked.status_code == 401
    with pytest.raises(RuntimeError, match="already exists"):
        import_legacy_user("legacy.import", "Administrador Inicial")
