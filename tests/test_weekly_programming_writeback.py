import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import weekly_programming


def _database(tmp_path):
    path = tmp_path / "operations.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE driver_profiles(id TEXT PRIMARY KEY, name TEXT, phone TEXT, cpf TEXT)"
    )
    connection.execute(
        "INSERT INTO driver_profiles VALUES(?,?,?,?)",
        ("drv-real", "Motorista Real", "11999990000", "12345678901"),
    )
    connection.commit()
    connection.close()
    return path


def _capture(monkeypatch, database_path):
    calls = []

    class Writeback:
        def update_lt(self, **kwargs):
            calls.append(kwargs)
            return {"lt": kwargs["lt"], "updated_fields": sorted(kwargs["values"])}

    monkeypatch.setattr(
        weekly_programming,
        "get_settings",
        lambda: SimpleNamespace(
            operations_database_path=database_path,
            weekly_writeback_enabled=True,
        ),
    )
    monkeypatch.setattr(weekly_programming, "GoogleSheetsWriteback", Writeback)
    return calls


def test_writeback_is_disabled_by_default(monkeypatch, tmp_path):
    path = _database(tmp_path)
    monkeypatch.setattr(
        weekly_programming,
        "get_settings",
        lambda: SimpleNamespace(
            operations_database_path=path,
            weekly_writeback_enabled=False,
        ),
    )
    payload = weekly_programming.WeeklyProgrammingWriteback(
        lt="LT-1", sheet_name="LHW38", driver_id="drv-real",
        event="DRIVER_SELECTED",
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(weekly_programming.writeback_weekly_programming(payload))
    assert error.value.status_code == 503


def test_driver_selection_writes_only_authoritative_name(monkeypatch, tmp_path):
    calls = _capture(monkeypatch, _database(tmp_path))
    payload = weekly_programming.WeeklyProgrammingWriteback(
        lt="LT-1", sheet_name="LHW38", driver_id="drv-real",
        driver="Nome adulterado", phone="000", cpf="000", event="DRIVER_SELECTED",
    )
    asyncio.run(weekly_programming.writeback_weekly_programming(payload))
    assert calls[0]["values"] == {"driver": "Motorista Real"}


def test_route_release_writes_complete_authoritative_data(monkeypatch, tmp_path):
    calls = _capture(monkeypatch, _database(tmp_path))
    payload = weekly_programming.WeeklyProgrammingWriteback(
        lt="LT-1", sheet_name="LHW38", driver_id="drv-real",
        truck="ABC1D23", trailer="XYZ9H87", event="ROUTE_RELEASED",
    )
    asyncio.run(weekly_programming.writeback_weekly_programming(payload))
    assert calls[0]["values"] == {
        "driver": "Motorista Real", "truck": "ABC1D23", "trailer": "XYZ9H87",
        "phone": "11999990000", "cpf": "12345678901",
    }


def test_route_release_rejects_incomplete_driver(monkeypatch, tmp_path):
    path = _database(tmp_path)
    connection = sqlite3.connect(path)
    connection.execute("UPDATE driver_profiles SET phone = NULL WHERE id = 'drv-real'")
    connection.commit()
    connection.close()
    calls = _capture(monkeypatch, path)
    payload = weekly_programming.WeeklyProgrammingWriteback(
        lt="LT-1", sheet_name="LHW38", driver_id="drv-real",
        truck="ABC1D23", trailer="XYZ9H87", event="ROUTE_RELEASED",
    )
    with pytest.raises(HTTPException, match="telefone"):
        asyncio.run(weekly_programming.writeback_weekly_programming(payload))
    assert calls == []


def test_route_release_rejects_invalid_vehicle_plates(monkeypatch, tmp_path):
    calls = _capture(monkeypatch, _database(tmp_path))
    payload = weekly_programming.WeeklyProgrammingWriteback(
        lt="LT-1", sheet_name="LHW38", driver_id="drv-real",
        truck="ADRIAN", trailer="XYZ9H87", event="ROUTE_RELEASED",
    )
    with pytest.raises(HTTPException, match="Placa inválida: cavalo"):
        asyncio.run(weekly_programming.writeback_weekly_programming(payload))
    assert calls == []
