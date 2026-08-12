from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

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


def test_integrity_failure_before_commit_rolls_back_everything(tmp_path, monkeypatch):
    database = tmp_path / "integrity-failed.sqlite"
    from app.storage import migrations

    results = iter(("ok", "corrupt"))
    monkeypatch.setattr(migrations, "_integrity_result", lambda _connection: next(results))
    with pytest.raises(DatabaseSchemaError, match="integrity"):
        migrate_database(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall() == []


def test_foreign_key_failure_before_commit_rolls_back_everything(tmp_path):
    database = tmp_path / "foreign-key-failed.sqlite"
    with pytest.raises(DatabaseSchemaError, match="Foreign-key"):
        migrate_database(database, foreign_key_failure_probe=True)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall() == []


def test_invalid_source_is_rejected_without_changes(tmp_path):
    database = tmp_path / "invalid-source.sqlite"
    migrate_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "INSERT INTO public_trip_links(id,trip_key,token_hash,created_at) VALUES(?,?,?,?)",
            ("orphan", "missing-trip", "orphan-hash", "now"),
        )
        connection.execute("DELETE FROM schema_migrations")
    before = _digest(database)
    with pytest.raises(DatabaseSchemaError, match="Foreign-key"):
        migrate_database(database)
    assert _digest(database) == before


def test_concurrent_migrations_are_serialized_and_idempotent(tmp_path):
    database = tmp_path / "concurrent.sqlite"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: migrate_database(database), range(2)))
    assert results == [None, None]
    validate_database_schema(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version=?", (SCHEMA_VERSION,)
        ).fetchone()[0] == 1


def test_future_schema_version_is_rejected_without_changes(tmp_path):
    database = tmp_path / "future.sqlite"
    migrate_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES(?, ?)",
            (SCHEMA_VERSION + 1, "future"),
        )
    before = _digest(database)
    with pytest.raises(DatabaseSchemaError, match="newer than supported"):
        migrate_database(database)
    assert _digest(database) == before


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
