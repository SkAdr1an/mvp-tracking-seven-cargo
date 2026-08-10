from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import driver_history as api_module
from app.api.driver_history import router
from app.core.security import require_panel_session
from app.storage.feature_migrations import apply_migration_009
from app.storage.operations import OperationsRepository


def app_for(repository: OperationsRepository, monkeypatch, *, authenticated: bool = True) -> TestClient:
    monkeypatch.setattr(api_module.trip_operations_service, "repository", repository)
    app = FastAPI(); app.include_router(router)
    if authenticated: app.dependency_overrides[require_panel_session] = lambda: "homologador"
    return TestClient(app)


def test_history_route_is_registered_and_empty_database_is_200(tmp_path: Path, monkeypatch):
    repository = OperationsRepository(tmp_path / "empty.sqlite")
    apply_migration_009(repository.database_path, disposable=True)
    client = app_for(repository, monkeypatch)
    response = client.get("/api/driver-history/drivers")
    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "page_size": 25, "total": 0}


def test_history_requires_panel_permission(tmp_path: Path, monkeypatch):
    repository = OperationsRepository(tmp_path / "permission.sqlite")
    apply_migration_009(repository.database_path, disposable=True)
    assert app_for(repository, monkeypatch, authenticated=False).get("/api/driver-history/drivers").status_code == 401


def test_pending_migration_is_clear_503_not_404(tmp_path: Path, monkeypatch):
    repository = OperationsRepository(tmp_path / "pending.sqlite")
    response = app_for(repository, monkeypatch).get("/api/driver-history/drivers")
    assert response.status_code == 503
    assert "migração 009 pendente" in response.json()["detail"]


def test_empty_history_request_does_not_backfill(tmp_path: Path, monkeypatch):
    repository = OperationsRepository(tmp_path / "no-backfill.sqlite")
    repository.ensure_trip("legacy-trip", "AAA1A11", "1", None)
    repository.update_trip("legacy-trip", current_driver="Nome Legado", state="FINALIZADA_NO_SISTEMA")
    apply_migration_009(repository.database_path, disposable=True)
    response = app_for(repository, monkeypatch).get("/api/driver-history/drivers")
    assert response.status_code == 200 and response.json()["total"] == 0
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM driver_trip_history").fetchone()[0] == 0
