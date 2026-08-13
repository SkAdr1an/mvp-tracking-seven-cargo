from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.api import operations as operations_api
from app.core.config import get_settings
from app.core.security import (
    PANEL_SESSION_COOKIE, Permission, Principal, Role, create_panel_session, hash_password,
    require_permission,
)
from app.services.operational_observations import (
    ObservationConflict, ObservationType, OperationalObservationService,
)
from app.services.trip_operations import TripOperationsService
from app.services.trip_report import TripReportService
from app.storage.migrations import SCHEMA_VERSION, migrate_database, validate_database_schema
from app.storage.operations import OperationsRepository
from app.storage.users import UserRepository


EXPECTED_INDEXES = {
    "idx_operational_observations_trip_time",
    "idx_operational_observations_author_time",
    "idx_operational_observations_stop",
}


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _downgrade_to_eleven(database) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE operational_observations")
        connection.execute("DELETE FROM schema_migrations")
        connection.execute(
            "INSERT INTO schema_migrations(version,applied_at) VALUES(11,'legacy')"
        )


def _runtime(database, monkeypatch) -> TripOperationsService:
    migrate_database(database)
    settings = get_settings()
    monkeypatch.setattr(settings, "operations_database_path", database)
    monkeypatch.setattr(settings, "panel_session_secret", "phase-three-session-secret-32-bytes")
    monkeypatch.setattr(settings, "panel_users_file", None)
    monkeypatch.setattr(settings, "panel_admin_username", "")
    monkeypatch.setattr(settings, "panel_admin_password_hash", "")
    for permission in Permission:
        main_module.app.dependency_overrides.pop(require_permission(permission), None)
    service = TripOperationsService(OperationsRepository(database))
    monkeypatch.setattr(operations_api, "trip_operations_service", service)
    return service


def _trip(repository: OperationsRepository, key: str) -> None:
    repository.ensure_trip(key, "ABC1D23", key, None)


def _identity(database, username: str, role_code: str = "MONITORING"):
    identity = UserRepository(database).create(
        username=username, display_name=f"Nome {username}",
        password_hash=hash_password("phase-three-password"), role_code=role_code,
    )
    return Principal(
        identity.username, Role(role_code), user_id=identity.id,
        display_name=identity.display_name,
        permissions=frozenset(Permission(code) for code in identity.permissions),
    )


def _client(principal: Principal) -> TestClient:
    token, _ = create_panel_session(principal)
    client = TestClient(main_module.app)
    client.cookies.set(PANEL_SESSION_COOKIE, token)
    return client


def _create_payload(**updates):
    value = {
        "observation_type": "GENERAL",
        "content": "Motorista contatado pela central.",
        "occurred_at": "2026-08-13T15:52:00-03:00",
        "include_in_report": True,
    }
    value.update(updates)
    return value


def _stop(database, trip_key: str) -> int:
    with sqlite3.connect(database) as connection:
        cursor = connection.execute(
            """INSERT INTO operational_stops(
               trip_key,started_at,duration_minutes,latitude,longitude,sample_count,
               classification,status,confidence,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,'OPEN',?,?,?)""",
            (trip_key, "2026-08-13T15:00:00+00:00", 10, -23, -46, 2,
             "ATTENTION", "HIGH", "now", "now"),
        )
        return int(cursor.lastrowid)


def test_migration_twelve_new_upgrade_idempotence_and_rollback(tmp_path) -> None:
    database = tmp_path / "migration.sqlite"
    migrate_database(database)
    validate_database_schema(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 12
        indexes = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
        assert EXPECTED_INDEXES <= indexes
        foreign_keys = {row[2] for row in connection.execute(
            "PRAGMA foreign_key_list(operational_observations)"
        )}
        assert {"operational_trips", "operational_stops", "users", "operational_observations"} <= foreign_keys
        connection.execute(
            """INSERT INTO operational_trips(trip_key,plate,state,created_at,updated_at)
               VALUES('preserved','ABC1D23','PROGRAMADA','before','before')"""
        )
    first = _digest(database)
    migrate_database(database)
    assert _digest(database) == first

    _downgrade_to_eleven(database)
    before_failure = _digest(database)
    with pytest.raises(sqlite3.OperationalError):
        migrate_database(database, failure_probe=True)
    assert _digest(database) == before_failure
    migrate_database(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT plate FROM operational_trips WHERE trip_key='preserved'"
        ).fetchone()[0] == "ABC1D23"


@pytest.mark.parametrize("role_code", ["ADMIN", "GR", "MONITORING"])
def test_all_official_roles_create_with_nominal_session_author(
    tmp_path, monkeypatch, role_code,
) -> None:
    database = tmp_path / f"create-{role_code}.sqlite"
    service = _runtime(database, monkeypatch)
    _trip(service.repository, "trip-1")
    principal = _identity(database, f"author.{role_code.lower()}", role_code)
    payload = _create_payload(
        user_id="forged", username="forged", display_name="Forged", role="ADMIN",
        operator="forged",
    )
    response = _client(principal).post("/operations/trips/trip-1/observations", json=payload)
    assert response.status_code == 201
    assert response.json()["author"] == {
        "user_id": principal.user_id,
        "username": principal.username,
        "display_name": principal.display_name,
        "role": role_code,
        "role_label": {"ADMIN": "Administrador", "GR": "GR", "MONITORING": "Monitoramento"}[role_code],
    }


def test_create_authentication_permission_legacy_and_validation_boundaries(tmp_path, monkeypatch) -> None:
    database = tmp_path / "boundaries.sqlite"
    service = _runtime(database, monkeypatch)
    _trip(service.repository, "trip-1")
    endpoint = "/operations/trips/trip-1/observations"
    assert TestClient(main_module.app).post(endpoint, json=_create_payload()).status_code == 401

    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM role_permissions WHERE role_id='MONITORING' AND permission_id='observations:create'"
        )
    assert _client(_identity(database, "without.permission")).post(
        endpoint, json=_create_payload()
    ).status_code == 403

    settings = get_settings()
    monkeypatch.setattr(settings, "panel_admin_username", "legacy.observer")
    monkeypatch.setattr(settings, "panel_admin_password_hash", hash_password("legacy-password"))
    monkeypatch.setattr(settings, "panel_admin_role", "Administrador")
    legacy = TestClient(main_module.app)
    assert legacy.post(
        "/api/auth/session", json={"username": "legacy.observer", "password": "legacy-password"}
    ).status_code == 200
    assert legacy.post(endpoint, json=_create_payload()).status_code == 409

    admin = _client(_identity(database, "validation.admin", "ADMIN"))
    assert admin.post(endpoint, json=_create_payload(content="   ")).status_code == 422
    assert admin.post(endpoint, json=_create_payload(observation_type="ARBITRARY")).status_code == 422
    assert admin.post(
        "/operations/trips/missing/observations", json=_create_payload()
    ).status_code == 404


def test_stop_observation_requires_same_trip_and_preserves_stop_evidence(tmp_path, monkeypatch) -> None:
    database = tmp_path / "stops.sqlite"
    service = _runtime(database, monkeypatch)
    _trip(service.repository, "trip-a")
    _trip(service.repository, "trip-b")
    stop_a, stop_b = _stop(database, "trip-a"), _stop(database, "trip-b")
    with sqlite3.connect(database) as connection:
        connection.execute(
            """INSERT INTO stop_evidence_events(stop_id,action,operator,justification,occurred_at)
               VALUES(?,?,?,?,?)""", (stop_a, "JUSTIFIED", "legacy", "Formal evidence", "now")
        )
    client = _client(_identity(database, "stop.author"))
    good = client.post(
        "/operations/trips/trip-a/observations",
        json=_create_payload(observation_type="STOP", stop_id=stop_a),
    )
    assert good.status_code == 201 and good.json()["stop_id"] == stop_a
    assert client.post(
        "/operations/trips/trip-a/observations",
        json=_create_payload(observation_type="STOP", stop_id=stop_b),
    ).status_code == 409
    assert client.post(
        "/operations/trips/trip-a/observations",
        json=_create_payload(observation_type="STOP"),
    ).status_code == 422
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM stop_evidence_events").fetchone()[0] == 1


def test_read_order_snapshots_and_inactive_author_remain_available(tmp_path, monkeypatch) -> None:
    database = tmp_path / "read.sqlite"
    service = _runtime(database, monkeypatch)
    _trip(service.repository, "trip-1")
    principal = _identity(database, "snapshot.author")
    observations = OperationalObservationService(database)
    late = observations.create(
        trip_key="trip-1", observation_type=ObservationType.GENERAL, content="Late",
        occurred_at=datetime(2026, 8, 13, 18, tzinfo=timezone.utc), principal=principal,
    )
    early = observations.create(
        trip_key="trip-1", observation_type=ObservationType.DRIVER_CONTACT, content="Early",
        occurred_at=datetime(2026, 8, 13, 17, tzinfo=timezone.utc), principal=principal,
    )
    UserRepository(database).inactivate(principal.user_id)
    reader = _client(_identity(database, "active.reader", "GR"))
    response = reader.get("/operations/trips/trip-1/observations")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["observations"]] == [early["id"], late["id"]]
    assert response.json()["observations"][0]["author"]["display_name"] == principal.display_name


def test_read_requires_trips_read(tmp_path, monkeypatch) -> None:
    database = tmp_path / "read-permission.sqlite"
    service = _runtime(database, monkeypatch)
    _trip(service.repository, "trip-1")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM role_permissions WHERE role_id='MONITORING' AND permission_id='trips:read'"
        )
    response = _client(_identity(database, "restricted.reader")).get(
        "/operations/trips/trip-1/observations"
    )
    assert response.status_code == 403


def test_correction_preserves_original_and_is_restricted_to_author(tmp_path, monkeypatch) -> None:
    database = tmp_path / "correction.sqlite"
    service = _runtime(database, monkeypatch)
    _trip(service.repository, "trip-1")
    author = _identity(database, "original.author")
    other = _identity(database, "other.author")
    observation = OperationalObservationService(database).create(
        trip_key="trip-1", observation_type=ObservationType.OPERATIONAL_NOTE,
        content="Original content", occurred_at=datetime.now(timezone.utc), principal=author,
    )
    endpoint = f"/operations/observations/{observation['id']}/correction"
    assert _client(other).post(endpoint, json={
        "content": "Other content", "reason": "Unauthorized correction",
    }).status_code == 403
    assert _client(author).post(endpoint, json={
        "content": "Corrected content", "reason": "Information clarified",
    }).status_code == 200
    assert _client(author).post(endpoint, json={
        "content": "Again", "reason": "",
    }).status_code == 422
    history = OperationalObservationService(database).list_for_trip("trip-1")
    assert [(item["status"], item["content"]) for item in history] == [
        ("CORRECTED", "Original content"), ("ACTIVE", "Corrected content"),
    ]
    assert history[0]["correction"]["reason"] == "Information clarified"
    assert history[1]["correction"]["supersedes_observation_id"] == observation["id"]


def test_void_requires_admin_permission_and_never_deletes(tmp_path, monkeypatch) -> None:
    database = tmp_path / "void.sqlite"
    service = _runtime(database, monkeypatch)
    _trip(service.repository, "trip-1")
    monitoring = _identity(database, "void.monitoring")
    observation = OperationalObservationService(database).create(
        trip_key="trip-1", observation_type=ObservationType.INCIDENT,
        content="To be voided", occurred_at=datetime.now(timezone.utc), principal=monitoring,
    )
    endpoint = f"/operations/observations/{observation['id']}/void"
    assert _client(monitoring).post(endpoint, json={"reason": "Not allowed"}).status_code == 403
    admin = _client(_identity(database, "void.admin", "ADMIN"))
    assert admin.post(endpoint, json={"reason": ""}).status_code == 422
    response = admin.post(endpoint, json={"reason": "Invalid operational entry"})
    assert response.status_code == 200 and response.json()["status"] == "VOIDED"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT status,void_reason FROM operational_observations WHERE id=?", (observation["id"],)
        ).fetchone() == ("VOIDED", "Invalid operational entry")


def test_report_includes_only_active_selected_observations_and_escapes_html(tmp_path, monkeypatch) -> None:
    database = tmp_path / "report.sqlite"
    service = _runtime(database, monkeypatch)
    _trip(service.repository, "trip-1")
    author = _identity(database, "report.author", "MONITORING")
    admin = _identity(database, "report.admin", "ADMIN")
    observations = OperationalObservationService(database)
    visible = observations.create(
        trip_key="trip-1", observation_type=ObservationType.STOP,
        content="<script>alert(1)</script> Parada para refeição",
        occurred_at=datetime.now(timezone.utc), principal=author, stop_id=_stop(database, "trip-1"),
    )
    hidden = observations.create(
        trip_key="trip-1", observation_type=ObservationType.GENERAL, content="Hidden note",
        occurred_at=datetime.now(timezone.utc) + timedelta(minutes=1), principal=author,
        include_in_report=False,
    )
    corrected = observations.create(
        trip_key="trip-1", observation_type=ObservationType.GENERAL, content="Old version",
        occurred_at=datetime.now(timezone.utc) + timedelta(minutes=2), principal=author,
    )
    observations.correct(
        corrected["id"], content="Current version", reason="Clarified text", principal=author,
    )
    voided = observations.create(
        trip_key="trip-1", observation_type=ObservationType.INCIDENT, content="Voided note",
        occurred_at=datetime.now(timezone.utc) + timedelta(minutes=3), principal=author,
    )
    observations.void(voided["id"], reason="Invalid note", principal=admin)

    result = TripReportService(service.repository, tmp_path / "reports").generate("trip-1")
    rendered = open(result.html_path, encoding="utf-8").read()
    assert "Parada para refeição" in rendered and "&lt;script&gt;" in rendered
    assert "Nome report.author" in rendered and "Monitoramento" in rendered
    assert "Current version" in rendered
    for excluded in ("Hidden note", "Old version", "Voided note", author.user_id, admin.user_id):
        assert excluded not in rendered
    evidence = TripReportService(service.repository, tmp_path / "reports").evidence("trip-1")
    assert {item["id"] for item in evidence["operational_observations"]} == {
        visible["id"], next(item["id"] for item in observations.list_for_trip("trip-1")
                            if item["content"] == "Current version"),
    }
