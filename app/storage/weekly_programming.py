from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.storage.sqlite_runtime import connect_existing_database


class WeeklyProgrammingRepository:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    def load(self) -> dict[str, Any] | None:
        with connect_existing_database(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT week,file_name,sheet_name,rows_json,imported_at,updated_at,online_fetched_at "
                "FROM weekly_programming_state WHERE id=1"
            ).fetchone()
        if not row:
            return None
        return {
            "week": row["week"], "file_name": row["file_name"],
            "sheet_name": row["sheet_name"], "rows": json.loads(row["rows_json"]),
            "imported_at": row["imported_at"], "updated_at": row["updated_at"],
            "online_fetched_at": row["online_fetched_at"],
        }

    def save(self, *, week: str, file_name: str, sheet_name: str,
             rows: list[dict[str, Any]], imported_at: str | None = None,
             online_fetched_at: str | None = None) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with connect_existing_database(self.database_path) as connection:
            previous = connection.execute(
                "SELECT imported_at FROM weekly_programming_state WHERE id=1"
            ).fetchone()
            original_imported_at = imported_at or (previous[0] if previous else now)
            connection.execute(
                """INSERT INTO weekly_programming_state(
                       id,week,file_name,sheet_name,rows_json,imported_at,updated_at,online_fetched_at
                   ) VALUES(1,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     week=excluded.week,file_name=excluded.file_name,sheet_name=excluded.sheet_name,
                     rows_json=excluded.rows_json,imported_at=excluded.imported_at,
                     updated_at=excluded.updated_at,online_fetched_at=excluded.online_fetched_at""",
                (week, file_name, sheet_name, json.dumps(rows, ensure_ascii=False),
                 original_imported_at, now, online_fetched_at),
            )
            connection.commit()
        return self.load()  # type: ignore[return-value]
