from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys

import pytest

from app.storage.migrations import (
    DatabaseSchemaError, SCHEMA_VERSION, migrate_database, validate_database_schema,
)


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_import_does_not_create_database(tmp_path):
    database = tmp_path / "must-not-exist.sqlite"
    environment = {**os.environ, "OPERATIONS_DATABASE_PATH": str(database), "PYTHONPATH": os.getcwd()}
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"], cwd=os.getcwd(), env=environment,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not database.exists()


def test_migration_is_versioned_and_byte_idempotent(tmp_path):
    database = tmp_path / "new.sqlite"
    migrate_database(database)
    validate_database_schema(database)
    first = _digest(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO route_configs(id,name,origin_name,origin_latitude,origin_longitude,destination_name,destination_latitude,destination_longitude,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("audit", "Audit", "A", 0, 0, "B", 1, 1, "created", "unchanged"),
        )
    before_repeat = _digest(database)
    migrate_database(database)
    assert _digest(database) == before_repeat
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT updated_at FROM route_configs WHERE id='audit'").fetchone()[0] == "unchanged"
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert first != before_repeat


def test_intermediate_failure_rolls_back_entire_schema(tmp_path):
    database = tmp_path / "failed.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        migrate_database(database, failure_probe=True)
    with sqlite3.connect(database) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == set()


def test_validation_rejects_missing_and_incompatible_schema(tmp_path):
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(DatabaseSchemaError, match="not migrated"):
        validate_database_schema(missing)
    incompatible = tmp_path / "incompatible.sqlite"
    sqlite3.connect(incompatible).close()
    with pytest.raises(DatabaseSchemaError, match="missing required tables"):
        validate_database_schema(incompatible)


def test_backend_refuses_unmigrated_database_and_starts_after_migration(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.core.config import get_settings
    from app.main import app

    database = tmp_path / "runtime.sqlite"
    settings = get_settings()
    monkeypatch.setattr(settings, "operations_database_path", database)
    monkeypatch.setattr(settings, "public_trip_token_pepper", "synthetic-runtime-pepper")
    monkeypatch.setattr(settings, "fleet_collector_enabled", False)
    monkeypatch.setattr(settings, "traffic_collector_enabled", False)
    monkeypatch.setattr(settings, "operations_backup_enabled", False)
    with pytest.raises(DatabaseSchemaError, match="not migrated"):
        with TestClient(app):
            pass
    assert not database.exists()
    migrate_database(database)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
