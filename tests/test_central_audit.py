from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import (
    PANEL_SESSION_COOKIE, Permission, Principal, Role, create_panel_session, hash_password,
)
from app.main import app
from app.services.audit import AuditAction, AuditService
from app.storage.migrations import SCHEMA_VERSION, migrate_database
from app.storage.users import UserRepository


def principal() -> Principal:
    return Principal("maria", Role.GR, display_name="Maria Souza")


def test_schema_13_creates_append_only_audit_indexes(tmp_path):
    database = tmp_path / "operations.db"
    migrate_database(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 13
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(audit_events)")}
        assert {"idx_audit_events_occurred_at", "idx_audit_events_actor_time",
                "idx_audit_events_trip_time", "idx_audit_events_action_time",
                "idx_audit_events_resource"} <= indexes
    assert SCHEMA_VERSION == 13
    migrate_database(database)


def test_audit_snapshots_before_after_and_sanitizes_recursively(tmp_path):
    database = tmp_path / "operations.db"
    migrate_database(database)
    service = AuditService(database)
    service.record(
        principal(), AuditAction.TRIP_STATUS_CORRECTED, "trip", resource_id="T-1",
        trip_key="T-1", before={"arrival_at": "old", "password_hash": "never"},
        after={"arrival_at": "new", "nested": {"api_key": "never", "ok": True}},
        metadata={"session_token": "never", "source": "panel"}, justification="Correção validada",
    )
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT * FROM audit_events").fetchone()
        columns = [value[0] for value in connection.execute("SELECT * FROM audit_events").description]
    event = dict(zip(columns, row))
    serialized = json.dumps(event)
    assert "never" not in serialized
    assert event["actor_user_id"] is None
    assert event["actor_username_snapshot"] == "maria"
    assert event["actor_display_name_snapshot"] == "Maria Souza"
    assert event["actor_role_snapshot"] == "GR"
    assert json.loads(event["before_json"]) == {"arrival_at": "old"}
    assert json.loads(event["after_json"]) == {"arrival_at": "new", "nested": {"ok": True}}


def test_existing_user_fk_is_enforced(tmp_path):
    database = tmp_path / "operations.db"
    migrate_database(database)
    actor = Principal("missing", Role.ADMIN, user_id="not-a-user")
    with pytest.raises(sqlite3.IntegrityError):
        AuditService(database).record(actor, AuditAction.USER_UPDATED, "user", resource_id="x")


def test_operational_query_excludes_administrative_events(tmp_path):
    database = tmp_path / "operations.db"
    migrate_database(database)
    service = AuditService(database)
    service.record(principal(), AuditAction.TRIP_PLAN_UPDATED, "trip", trip_key="T-1")
    service.record(principal(), AuditAction.USER_UPDATED, "user", trip_key="T-1")
    result = service.query(trip_key="T-1", operational_only=True)
    assert [event["action_type"] for event in result["events"]] == ["TRIP_PLAN_UPDATED"]


def test_failed_login_has_no_invented_actor(tmp_path):
    database = tmp_path / "operations.db"
    migrate_database(database)
    AuditService(database).record_login_failure("attempted.user")
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT actor_user_id,actor_username_snapshot,actor_role_snapshot FROM audit_events"
        ).fetchone()
    assert row == (None, "attempted.user", "UNKNOWN")


def test_required_user_audit_failure_rolls_back_mutation(tmp_path):
    database = tmp_path / "operations.db"
    migrate_database(database)

    def fail_audit(_connection, _created):
        raise sqlite3.OperationalError("synthetic audit failure")

    with pytest.raises(sqlite3.OperationalError, match="synthetic audit failure"):
        UserRepository(database).create(
            username="rollback.user", display_name="Rollback User",
            password_hash="scrypt$synthetic", role_code="MONITORING", audit=fail_audit,
        )
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT 1 FROM users WHERE username='rollback.user'"
        ).fetchone() is None
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0


def test_import_time_singletons_are_bound_to_disposable_test_database():
    from app.core.config import get_settings
    from app.services.route_deviation import route_deviation_service
    from app.services.traffic_monitoring import traffic_repository
    from app.services.trip_operations import trip_operations_service

    expected = str(get_settings().operations_database_path.resolve())
    assert trip_operations_service.repository.database_path == expected
    assert route_deviation_service.repository.database_path == expected
    assert traffic_repository.operations.database_path == expected


@pytest.mark.parametrize(
    "role,full_status,operational_status",
    [("ADMIN", 200, 200), ("GR", 403, 200), ("MONITORING", 403, 200)],
)
def test_audit_endpoints_keep_permission_boundaries(
    role, full_status, operational_status, monkeypatch,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "panel_session_secret", "audit-test-session-secret-32-bytes")
    monkeypatch.setattr(settings, "panel_users_file", None)
    database = settings.operations_database_path
    identity = UserRepository(database).create(
        username=f"audit.{role.lower()}", display_name=f"Audit {role}",
        password_hash=hash_password("audit-permission-password"), role_code=role,
    )
    principal_value = Principal(
        identity.username, Role(role), user_id=identity.id,
        display_name=identity.display_name,
        permissions=frozenset(Permission(code) for code in identity.permissions),
    )
    token, _ = create_panel_session(principal_value)
    client = TestClient(app)
    client.cookies.set(PANEL_SESSION_COOKIE, token)
    assert client.get("/api/audit").status_code == full_status
    assert client.get("/operations/trips/T-1/audit").status_code == operational_status


def test_audit_endpoints_require_authentication():
    client = TestClient(app)
    assert client.get("/api/audit").status_code == 401
    assert client.get("/operations/trips/T-1/audit").status_code == 401
