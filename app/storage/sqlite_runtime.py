from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_existing_database(
    database_path: str | Path,
    *,
    timeout: float = 10,
    check_same_thread: bool = True,
    read_only: bool = False,
) -> sqlite3.Connection:
    """Open an existing SQLite database without ever creating the file."""
    if str(database_path) == ":memory:":
        return sqlite3.connect(
            ":memory:", timeout=timeout, check_same_thread=check_same_thread
        )
    path = Path(database_path).resolve()
    mode = "ro" if read_only else "rw"
    return sqlite3.connect(
        f"file:{path.as_posix()}?mode={mode}",
        uri=True,
        timeout=timeout,
        check_same_thread=check_same_thread,
    )
