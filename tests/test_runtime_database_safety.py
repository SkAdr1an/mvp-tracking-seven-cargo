from __future__ import annotations

import sqlite3
import threading

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import validate_panel_session
from app.main import app
from app.storage.migrations import DatabaseSchemaError, migrate_database
from app.storage.operations import OperationsRepository
from app.storage.sqlite_runtime import connect_existing_database


def _configure_safe_runtime(monkeypatch: pytest.MonkeyPatch, database) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "operations_database_path", database)
    monkeypatch.setattr(settings, "public_trip_token_pepper", "synthetic-runtime-pepper")
    monkeypatch.setattr(settings, "fleet_collector_enabled", False)
    monkeypatch.setattr(settings, "traffic_collector_enabled", False)
    monkeypatch.setattr(settings, "operations_backup_enabled", False)


def test_runtime_connector_refuses_missing_file(tmp_path):
    database = tmp_path / "missing.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        connect_existing_database(database)
    assert not database.exists()


def test_runtime_refuses_missing_volume_file(tmp_path):
    volume = tmp_path / "mounted-volume"
    volume.mkdir()
    database = volume / "operations.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        connect_existing_database(database)
    assert not database.exists()


def test_repository_refuses_missing_file_without_creating_it(tmp_path):
    database = tmp_path / "repository.sqlite"
    repository = object.__new__(OperationsRepository)
    repository.database_path = str(database)
    repository._lock = threading.RLock()
    with pytest.raises(sqlite3.OperationalError):
        repository.routes()
    assert not database.exists()


def test_authentication_fails_closed_after_database_loss(tmp_path, monkeypatch):
    database = tmp_path / "authentication.sqlite"
    migrate_database(database)
    _configure_safe_runtime(monkeypatch, database)
    database.unlink()
    assert validate_panel_session("synthetic-token") is None
    assert not database.exists()


def test_startup_refuses_missing_database_without_creating_it(tmp_path, monkeypatch):
    database = tmp_path / "startup.sqlite"
    _configure_safe_runtime(monkeypatch, database)
    with pytest.raises(DatabaseSchemaError, match="not migrated"):
        with TestClient(app):
            pass
    assert not database.exists()


def test_health_fails_safely_after_database_loss(tmp_path, monkeypatch):
    database = tmp_path / "health.sqlite"
    migrate_database(database)
    _configure_safe_runtime(monkeypatch, database)
    with TestClient(app) as client:
        database.unlink()
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json() == {"detail": "Operational database unavailable"}
    assert not database.exists()


def test_explicit_migration_is_required_for_recovery(tmp_path):
    database = tmp_path / "recovery.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        connect_existing_database(database)
    migrate_database(database)
    with connect_existing_database(database, read_only=True) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_production_configuration_smoke_uses_disposable_database(tmp_path, monkeypatch):
    database = tmp_path / "production-smoke.sqlite"
    migrate_database(database)
    _configure_safe_runtime(monkeypatch, database)
    settings = get_settings()
    monkeypatch.setattr(settings, "app_environment", "production")
    monkeypatch.setattr(settings, "panel_cookie_secure", True)
    monkeypatch.setattr(settings, "force_https", True)
    monkeypatch.setattr(settings, "frontend_origins", "https://panel.example.com")
    monkeypatch.setattr(settings, "allowed_hosts", "panel.example.com,testserver")
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
