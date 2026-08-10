from __future__ import annotations

import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPERATIONAL_DATABASE = (PROJECT_ROOT / "data" / "operations.db").resolve()
MIGRATION_009 = PROJECT_ROOT / "migrations" / "009_driver_history_evaluations.sql"
ROLLBACK_009 = PROJECT_ROOT / "migrations" / "009_driver_history_evaluations.down.sql"
REQUIRED_009_TABLES = {
    "driver_profiles", "driver_trip_history", "driver_evaluations",
    "driver_evaluation_history", "punctuality_adjustments", "driver_internal_notes",
    "driver_identity_links", "driver_trip_history_changes",
}


def migration_009_pending(database_path: str | Path) -> bool:
    with sqlite3.connect(Path(database_path)) as connection:
        present = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return not REQUIRED_009_TABLES.issubset(present)


def apply_migration_009(database_path: str | Path, *, disposable: bool = False) -> None:
    target = Path(database_path).resolve()
    if target == OPERATIONAL_DATABASE or not disposable:
        raise RuntimeError("Migration 009 requires an explicitly disposable database")
    with sqlite3.connect(target) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(MIGRATION_009.read_text(encoding="utf-8"))


def rollback_migration_009(database_path: str | Path, *, disposable: bool = False) -> None:
    target = Path(database_path).resolve()
    if target == OPERATIONAL_DATABASE or not disposable:
        raise RuntimeError("Migration 009 rollback requires an explicitly disposable database")
    with sqlite3.connect(target) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(ROLLBACK_009.read_text(encoding="utf-8"))
