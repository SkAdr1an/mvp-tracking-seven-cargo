from __future__ import annotations

import hashlib
import inspect
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services.journey_observation import JourneyObservationService
from app.services.operational_sites import OperationalSiteService
from app.services.trip_operations import TripOperationsService
from app.storage.angellira import AngelLiraRepository
from app.storage.migrations import (
    DatabaseSchemaError,
    REQUIRED_INDEXES,
    REQUIRED_TABLES,
    SCHEMA_VERSION,
    migrate_database,
    validate_database_schema,
)
from app.storage.operations import OperationsRepository


JOURNEY_TABLES = {
    "communication_gaps",
    "journey_observation_trackers",
    "operational_exceptions",
    "operational_stops",
    "stop_evidence_events",
}
JOURNEY_INDEXES = {
    "idx_operational_exceptions_status",
    "idx_operational_stops_trip_time",
}


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _schema(connection: sqlite3.Connection) -> tuple[tuple[str, str, str], ...]:
    return tuple(connection.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE type IN ('table', 'index') ORDER BY type, name"
    ))


def _objects(database) -> tuple[set[str], set[str]]:
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        tables = {
            str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        indexes = {
            str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
    return tables, indexes


def _downgrade_marker_to_version_nine(database) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM schema_migrations")
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES(9, 'legacy')"
        )


def test_new_database_contains_journey_schema_and_required_indexes(tmp_path):
    database = tmp_path / "new.sqlite"
    migrate_database(database)
    tables, indexes = _objects(database)
    assert JOURNEY_TABLES <= tables
    assert JOURNEY_INDEXES <= indexes
    assert JOURNEY_TABLES <= REQUIRED_TABLES
    assert JOURNEY_INDEXES <= REQUIRED_INDEXES
    validate_database_schema(database)


def test_version_nine_database_without_journey_schema_is_upgraded(tmp_path):
    database = tmp_path / "legacy-without-journey.sqlite"
    migrate_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE communication_gaps")
        connection.execute("DROP TABLE journey_observation_trackers")
        connection.execute("DROP TABLE operational_exceptions")
        connection.execute("DROP TABLE operational_stops")
        connection.execute("DROP TABLE stop_evidence_events")
    _downgrade_marker_to_version_nine(database)

    migrate_database(database)

    tables, indexes = _objects(database)
    assert JOURNEY_TABLES <= tables
    assert JOURNEY_INDEXES <= indexes
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 10


def test_existing_journey_schema_and_operational_data_are_preserved(tmp_path):
    database = tmp_path / "legacy-with-journey.sqlite"
    migrate_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO communication_gaps("
            "trip_key,started_at,ended_at,duration_minutes,start_latitude,start_longitude,"
            "end_latitude,end_longitude,displacement_km,interpretation,created_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("trip-a", "start", "end", 30, 0, 0, 1, 1, 10, "PRESERVED", "created"),
        )
        connection.execute(
            "INSERT INTO route_configs("
            "id,name,origin_name,origin_latitude,origin_longitude,destination_name,"
            "destination_latitude,destination_longitude,created_at,updated_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("preserved", "Preserved", "A", 0, 0, "B", 1, 1, "created", "unchanged"),
        )
    _downgrade_marker_to_version_nine(database)

    migrate_database(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT interpretation FROM communication_gaps WHERE trip_key='trip-a'"
        ).fetchone()[0] == "PRESERVED"
        assert connection.execute(
            "SELECT updated_at FROM route_configs WHERE id='preserved'"
        ).fetchone()[0] == "unchanged"


def test_version_nine_upgrade_failure_rolls_back_journey_schema(tmp_path):
    database = tmp_path / "legacy-rollback.sqlite"
    migrate_database(database)
    with sqlite3.connect(database) as connection:
        for table in JOURNEY_TABLES:
            connection.execute(f'DROP TABLE "{table}"')
    _downgrade_marker_to_version_nine(database)
    before_hash = _digest(database)
    before_objects = _objects(database)

    with pytest.raises(sqlite3.OperationalError):
        migrate_database(database, failure_probe=True)

    assert _digest(database) == before_hash
    assert _objects(database) == before_objects
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 9


@pytest.mark.runtime_schema_invariance
def test_service_construction_is_byte_and_schema_idempotent(tmp_path):
    database = tmp_path / "construction.sqlite"
    migrate_database(database)
    repository = OperationsRepository(database)
    with sqlite3.connect(database) as connection:
        before_schema = _schema(connection)
        before_schema_version = connection.execute("PRAGMA schema_version").fetchone()[0]
        before_changes = connection.total_changes
        before_counts = {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in JOURNEY_TABLES
        }
    before_hash = _digest(database)

    JourneyObservationService(repository)
    TripOperationsService(repository)
    OperationsRepository(database)
    AngelLiraRepository(database)
    OperationalSiteService(database)

    assert _digest(database) == before_hash
    with sqlite3.connect(database) as connection:
        assert _schema(connection) == before_schema
        assert connection.execute("PRAGMA schema_version").fetchone()[0] == before_schema_version
        assert connection.total_changes == before_changes == 0
        assert {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in JOURNEY_TABLES
        } == before_counts


@pytest.mark.runtime_schema_invariance
def test_missing_journey_schema_is_rejected_without_repair(tmp_path, monkeypatch):
    database = tmp_path / "missing-journey.sqlite"
    migrate_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE communication_gaps")
    before_hash = _digest(database)
    before_objects = _objects(database)

    with pytest.raises(RuntimeError, match="Journey observation schema is unavailable"):
        JourneyObservationService(OperationsRepository(database))

    assert _digest(database) == before_hash
    assert _objects(database) == before_objects
    with pytest.raises(DatabaseSchemaError, match="missing required tables"):
        validate_database_schema(database)

    settings = get_settings()
    monkeypatch.setattr(settings, "operations_database_path", database)
    monkeypatch.setattr(settings, "public_trip_token_pepper", "synthetic-runtime-pepper")
    monkeypatch.setattr(settings, "fleet_collector_enabled", False)
    monkeypatch.setattr(settings, "traffic_collector_enabled", False)
    monkeypatch.setattr(settings, "operations_backup_enabled", False)
    with pytest.raises(DatabaseSchemaError, match="missing required tables"):
        with TestClient(app):
            pass
    assert _digest(database) == before_hash
    assert _objects(database) == before_objects


def test_journey_runtime_contains_no_schema_ddl() -> None:
    source = inspect.getsource(__import__(
        "app.services.journey_observation", fromlist=["JourneyObservationService"]
    )).upper()
    for forbidden in ("CREATE TABLE", "CREATE INDEX", "ALTER TABLE", "DROP TABLE", "EXECUTESCRIPT"):
        assert forbidden not in source


def test_required_journey_index_is_validated(tmp_path):
    database = tmp_path / "missing-index.sqlite"
    migrate_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP INDEX idx_operational_stops_trip_time")
    with pytest.raises(DatabaseSchemaError, match="missing required indexes"):
        validate_database_schema(database)
