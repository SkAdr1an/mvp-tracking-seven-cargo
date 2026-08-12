from fastapi.testclient import TestClient
import pytest

from app.core.config import get_settings
from app.main import app
from app.storage.migrations import migrate_database


def test_health_endpoint(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "health.sqlite"
    migrate_database(database)
    settings = get_settings()
    monkeypatch.setattr(settings, "operations_database_path", database)
    monkeypatch.setattr(settings, "public_trip_token_pepper", "synthetic-health-pepper")
    monkeypatch.setattr(settings, "fleet_collector_enabled", False)
    monkeypatch.setattr(settings, "traffic_collector_enabled", False)
    monkeypatch.setattr(settings, "operations_backup_enabled", False)
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
