import sqlite3

from app.storage.weekly_programming import WeeklyProgrammingRepository


def test_weekly_programming_state_survives_repository_reopen(tmp_path):
    database = tmp_path / "operations.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """CREATE TABLE weekly_programming_state(
                id INTEGER PRIMARY KEY CHECK(id=1), week TEXT NOT NULL,
                file_name TEXT NOT NULL, sheet_name TEXT NOT NULL,
                rows_json TEXT NOT NULL, imported_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, online_fetched_at TEXT
            );"""
        )
    row = {"id": "row-1", "week": "LHW37", "lt": "LT-1"}
    WeeklyProgrammingRepository(database).save(
        week="LHW37", file_name="ceva.xlsx", sheet_name="LHW37", rows=[row]
    )
    restored = WeeklyProgrammingRepository(database).load()
    assert restored is not None
    assert restored["rows"] == [row]
    assert restored["file_name"] == "ceva.xlsx"


def test_online_update_keeps_original_import_timestamp(tmp_path):
    database = tmp_path / "operations.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """CREATE TABLE weekly_programming_state(
                id INTEGER PRIMARY KEY CHECK(id=1), week TEXT NOT NULL,
                file_name TEXT NOT NULL, sheet_name TEXT NOT NULL,
                rows_json TEXT NOT NULL, imported_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, online_fetched_at TEXT
            );"""
        )
    repository = WeeklyProgrammingRepository(database)
    first = repository.save(week="LHW37", file_name="ceva.xlsx", sheet_name="LHW37", rows=[])
    second = repository.save(
        week="LHW37", file_name="ceva.xlsx", sheet_name="LHW37", rows=[],
        online_fetched_at="2026-09-10T18:00:00+00:00",
    )
    assert second["imported_at"] == first["imported_at"]
    assert second["online_fetched_at"] == "2026-09-10T18:00:00+00:00"
