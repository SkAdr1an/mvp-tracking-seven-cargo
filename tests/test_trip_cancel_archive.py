from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.core.security import Permission, Principal, Role, require_panel_session
from app.main import app
from app.services.trip_operations import trip_operations_service
from app.services.trip_lifecycle import TripLifecycleConflict, TripLifecycleService
from app.storage.operations import OperationsRepository


def _service(tmp_path):
    repository = OperationsRepository(tmp_path / "phase6.sqlite")
    repository.ensure_trip("trip-6", "ABC1D23", "provider-6", None)
    return repository, TripLifecycleService(repository)


def test_cancel_is_atomic_audited_and_revokes_public_link(tmp_path):
    repository, service = _service(tmp_path)
    with repository.connect() as connection:
        connection.execute(
            """INSERT INTO public_trip_links
               (id,trip_key,token_hash,created_at,active,created_by)
               VALUES('link-6','trip-6','hash-6','2026-08-14T10:00:00+00:00',1,'maria')"""
        )

    result = service.cancel(
        "trip-6", "Carga recusada pelo cliente", Principal("maria", Role.GR, display_name="Maria"),
    )

    assert result["state"] == "CANCELADA"
    assert result["cancelled_at"]
    assert result["cancelled_by_user_id"] is None
    assert result["cancelled_reason"] == "Carga recusada pelo cliente"
    with repository.connect() as connection:
        assert connection.execute("SELECT active FROM public_trip_links WHERE id='link-6'").fetchone()[0] == 0
        assert connection.execute(
            "SELECT event_type FROM public_trip_link_events WHERE public_link_id='link-6'"
        ).fetchone()[0] == "TRIP_CANCELLED"
        audit = connection.execute(
            "SELECT action_type,before_json,after_json FROM audit_events WHERE trip_key='trip-6'"
        ).fetchone()
        assert audit[0] == "TRIP_CANCELLED"
        assert '"state": "PROGRAMADA"' in audit[1]
        assert '"state": "CANCELADA"' in audit[2]
    assert repository.events("trip-6")[0]["event_type"] == "TRIP_CANCELLED"


def test_cancel_rolls_back_trip_event_link_and_audit_together(tmp_path, monkeypatch):
    repository, service = _service(tmp_path)
    with repository.connect() as connection:
        connection.execute(
            """INSERT INTO public_trip_links(id,trip_key,token_hash,created_at,active)
               VALUES('link-rollback','trip-6','hash-rollback','2026-08-14T10:00:00+00:00',1)"""
        )
    monkeypatch.setattr(service.audit, "record", lambda *args, **kwargs: (_ for _ in ()).throw(sqlite3.Error("audit fail")))

    with pytest.raises(sqlite3.Error, match="audit fail"):
        service.cancel("trip-6", "Falha transacional simulada", Principal("admin", Role.ADMIN))

    assert repository.trip("trip-6")["state"] == "PROGRAMADA"
    assert repository.events("trip-6") == []
    with repository.connect() as connection:
        assert connection.execute("SELECT active FROM public_trip_links WHERE id='link-rollback'").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM audit_events WHERE trip_key='trip-6'").fetchone()[0] == 0


def test_cancel_rejects_finished_or_already_cancelled_trip(tmp_path):
    repository, service = _service(tmp_path)
    repository.update_trip("trip-6", state="FINALIZADA_NO_SISTEMA")
    with pytest.raises(TripLifecycleConflict, match="finalizada"):
        service.cancel("trip-6", "Tentativa inválida de cancelamento", Principal("admin", Role.ADMIN))
    repository.update_trip("trip-6", state="CANCELADA")
    with pytest.raises(TripLifecycleConflict, match="já está cancelada"):
        service.cancel("trip-6", "Tentativa duplicada de cancelamento", Principal("admin", Role.ADMIN))


def test_provider_upsert_cannot_resurrect_or_touch_cancelled_trip(tmp_path):
    repository, service = _service(tmp_path)
    cancelled = service.cancel(
        "trip-6", "Operação cancelada pelo cliente", Principal("admin", Role.ADMIN)
    )
    repository.ensure_trip("trip-6", "ABC1D23", "provider-new", "route-new")
    after = repository.trip("trip-6")
    assert after["state"] == "CANCELADA"
    assert after["updated_at"] == cancelled["updated_at"]
    assert after["route_id"] is None


def test_archive_hides_from_default_list_preserves_detail_and_can_unarchive(tmp_path):
    repository, service = _service(tmp_path)
    repository.update_trip("trip-6", state="FINALIZADA_NO_SISTEMA")
    actor = Principal("maria", Role.GR)

    archived = service.archive("trip-6", "Histórico encerrado e conferido", actor)
    assert archived["archived_at"]
    assert repository.trips() == []
    assert repository.trips(include_archived=True)[0]["trip_key"] == "trip-6"
    assert repository.trip("trip-6")["state"] == "FINALIZADA_NO_SISTEMA"

    restored = service.unarchive("trip-6", "Reabertura de consulta operacional", actor)
    assert restored["archived_at"] is None
    assert repository.trips()[0]["trip_key"] == "trip-6"
    assert [event["event_type"] for event in repository.events("trip-6")] == [
        "TRIP_UNARCHIVED", "TRIP_ARCHIVED",
    ]


def test_archive_rejects_active_trip_without_changing_history(tmp_path):
    repository, service = _service(tmp_path)
    with pytest.raises(TripLifecycleConflict, match="encerradas"):
        service.archive("trip-6", "Ainda está em operação ativa", Principal("admin", Role.ADMIN))
    assert repository.trip("trip-6")["archived_at"] is None
    assert repository.events("trip-6") == []


def test_lifecycle_endpoints_keep_permission_boundary_and_conflict_status():
    repository = trip_operations_service.repository
    repository.ensure_trip("trip-api-6", "API1A23", "api-6", None)
    client = TestClient(app)
    monitoring = Principal("monitor", Role.MONITORING)
    app.dependency_overrides[require_panel_session] = lambda: monitoring
    try:
        assert client.post(
            "/operations/trips/trip-api-6/cancel", json={"reason": "Cliente recusou a carga"}
        ).status_code == 403
    finally:
        app.dependency_overrides.pop(require_panel_session, None)

    gr = Principal("gr-user", Role.GR)
    app.dependency_overrides[require_panel_session] = lambda: gr
    try:
        first = client.post(
            "/operations/trips/trip-api-6/cancel", json={"reason": "Cliente recusou a carga"}
        )
        assert first.status_code == 200
        assert first.json()["state"] == "CANCELADA"
        assert client.post(
            "/operations/trips/trip-api-6/cancel", json={"reason": "Tentativa de repetição"}
        ).status_code == 409
    finally:
        app.dependency_overrides.pop(require_panel_session, None)
