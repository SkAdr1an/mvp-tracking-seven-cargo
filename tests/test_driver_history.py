from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.driver_history import DriverHistoryService
from app.storage.feature_migrations import apply_migration_009, rollback_migration_009
from app.storage.operations import OperationsRepository


@pytest.fixture
def history(tmp_path: Path) -> tuple[OperationsRepository, DriverHistoryService]:
    repository = OperationsRepository(tmp_path / "operations.db")
    apply_migration_009(repository.database_path, disposable=True)
    return repository, DriverHistoryService(repository)


def trip(repository: OperationsRepository, key: str, driver: str | None = "Maria Silva", *, state: str = "FINALIZADA_NO_SISTEMA", hours_ago: int = 1) -> None:
    repository.ensure_trip(key, f"ABC{key[-1]}D23", key.removeprefix("trip-"), None)
    repository.update_trip(key, current_driver=driver, state=state,
                           started_at=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat(),
                           finished_at=(datetime.now(timezone.utc)-timedelta(hours=hours_ago)).isoformat() if state == "FINALIZADA_NO_SISTEMA" else None)


def good_evaluation() -> dict[str, str]:
    return {"communication":"boa", "procedures":"cumpriu", "tracking_collaboration":"boa",
            "time_mark":"conforme", "professional_behavior":"bom", "recommendation":"recomendado"}


def test_driver_with_and_without_trips_and_incomplete_legacy_record(history):
    repository, service = history
    trip(repository, "trip-1")
    trip(repository, "trip-2", driver=None)
    assert service.sync_trip("trip-1") is not None
    listed = service.drivers()
    assert listed["total"] == 1
    assert listed["items"][0]["total_trips"] == 1
    with repository.connect() as connection:
        now = datetime.now(timezone.utc).isoformat()
        connection.execute("INSERT INTO driver_profiles(id,name,identity_status,created_at,updated_at) VALUES('drv-empty','Sem Viagens','PENDING',?,?)", (now, now))
    assert service.profile("drv-empty")["total_trips"] == 0


def test_same_names_remain_distinct_by_internal_id_and_cpf(history):
    repository, service = history
    now = datetime.now(timezone.utc).isoformat()
    with repository.connect() as connection:
        connection.execute("INSERT INTO driver_profiles(id,cpf,name,identity_status,created_at,updated_at) VALUES('drv-a','11111111111','José Igual','VERIFIED',?,?)", (now, now))
        connection.execute("INSERT INTO driver_profiles(id,cpf,name,identity_status,created_at,updated_at) VALUES('drv-b','22222222222','José Igual','VERIFIED',?,?)", (now, now))
    assert service.profile("11111111111")["id"] == "drv-a"
    assert service.profile("drv-b")["cpf_masked"] == "***.***.***-22"
    assert service.drivers(search="José")["total"] == 2


def test_finalized_trip_is_pending_then_evaluation_is_unique(history):
    repository, service = history
    trip(repository, "trip-3")
    record = service.sync_trip("trip-3")
    assert record and record["closed"] == 1
    assert service.pending()["total"] == 1
    evaluation = service.evaluate("trip-3", good_evaluation(), "operador")
    assert evaluation["responsible"] == "operador"
    assert service.pending()["total"] == 0
    with pytest.raises(ValueError, match="já possui"):
        service.evaluate("trip-3", good_evaluation(), "outro")


def test_negative_evaluation_requires_justification(history):
    repository, service = history
    trip(repository, "trip-4"); service.sync_trip("trip-4")
    values = good_evaluation() | {"recommendation":"com_ressalvas"}
    with pytest.raises(ValueError, match="Justificativa"):
        service.evaluate("trip-4", values, "operador")
    values["justification"] = "Comunicação precisa melhorar"
    assert service.evaluate("trip-4", values, "operador")["recommendation"] == "com_ressalvas"


def test_punctuality_adjustment_preserves_automatic_value(history):
    repository, service = history
    trip(repository, "trip-5"); service.sync_trip("trip-5")
    adjustment = service.adjust_punctuality("trip-5", "ON_TIME", "TRAFFIC", "Interdição", "Rodovia bloqueada", None, "operador")
    stored = service.trips(adjustment["trip_key"] if False else service.drivers()["items"][0]["id"])["items"][0]
    assert stored["automatic_punctuality"] == "UNAVAILABLE"
    assert stored["considered_punctuality"] == "ON_TIME"
    assert adjustment["original_value"] == "UNAVAILABLE"


def test_overdue_reopened_idempotent_and_provider_independent(history, monkeypatch):
    repository, service = history
    trip(repository, "trip-6", hours_ago=30)
    first = service.sync_trip("trip-6")
    second = service.sync_trip("trip-6")
    assert first["trip_key"] == second["trip_key"]
    assert service.pending(overdue=True)["items"][0]["situation"] == "OVERDUE"
    repository.update_trip("trip-6", state="REABERTA_MANUALMENTE", finished_at=None)
    service.sync_trip("trip-6")
    assert service.pending()["total"] == 0
    monkeypatch.setattr("app.integrations.trafegus.TrafegusClient.__init__", lambda self, *a, **k: (_ for _ in ()).throw(AssertionError("external call")))
    assert service.profile(first["driver_id"])["total_trips"] == 1


def test_filters_pagination_sensitive_pdf_and_migration_rollback(history, tmp_path: Path):
    repository, service = history
    trip(repository, "trip-7"); record = service.sync_trip("trip-7")
    assert service.trips(record["driver_id"], status="FINALIZADA_NO_SISTEMA", page_size=1)["total"] == 1
    html = service.report_html(record["driver_id"], service.trips(record["driver_id"])["items"])
    assert "SEVEN CARGO" in html and "Observações internas" not in html
    migration_db = tmp_path / "migration.db"
    migrated = OperationsRepository(migration_db); apply_migration_009(migration_db, disposable=True)
    rollback_migration_009(migration_db, disposable=True)
    with migrated.connect() as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "driver_profiles" not in names and "operational_trips" in names


def test_same_name_is_never_automatically_merged(history):
    repository, service = history
    trip(repository, "trip-a", driver="Nome Igual"); trip(repository, "trip-b", driver="Nome Igual")
    first, second = service.sync_trip("trip-a"), service.sync_trip("trip-b")
    assert first["driver_id"] != second["driver_id"]
    assert service.profile(first["driver_id"])["identity_status"] == "PENDING"


def test_manual_identity_link_and_correction_are_auditable(history):
    repository, service = history
    trip(repository, "trip-c", driver="Maria A"); trip(repository, "trip-d", driver="Maria B")
    first, second = service.sync_trip("trip-c"), service.sync_trip("trip-d")
    linked = service.link_identity("trip-c", target_driver_id=None, cpf="123.456.789-01", name="Maria Correta", source="documento", justification="Documento conferido", responsible="operador")
    corrected = service.link_identity("trip-d", target_driver_id=linked["id"], cpf="12345678901", name="Maria Corrigida", source="revisão", justification="Vínculo corrigido", responsible="supervisor")
    assert corrected["id"] == linked["id"] and corrected["cpf_masked"].endswith("01")
    changed = service.correct_trip_metadata("trip-c", customer=None, evaluation_responsible=None, justification="Campos indisponíveis", responsible="operador")
    assert changed["customer"] is None and changed["evaluation_responsible"] is None
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM driver_identity_links").fetchone()[0] == 2
        assert connection.execute("SELECT previous_driver_id FROM driver_identity_links ORDER BY id DESC").fetchone()[0] == second["driver_id"]


def test_duplicate_cpf_is_rejected(history):
    repository, service = history
    trip(repository, "trip-e"); trip(repository, "trip-f")
    service.sync_trip("trip-e"); second = service.sync_trip("trip-f")
    service.link_identity("trip-e", target_driver_id=None, cpf="12345678901", name="Primeira", source="cadastro", justification="Cadastro validado", responsible="operador")
    with pytest.raises(sqlite3.IntegrityError):
        service.update_profile(second["driver_id"], cpf="12345678901", phone=None, name="Segunda")
