from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UP = PROJECT_ROOT / "migrations" / "007_driver_mobile_location.sql"
DOWN = PROJECT_ROOT / "migrations" / "007_driver_mobile_location.down.sql"


def migrate(database: str | Path, *, reverse: bool = False) -> None:
    path = Path(database).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    script = (DOWN if reverse else UP).read_text(encoding="utf-8")
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript("BEGIN IMMEDIATE;\n" + script + "\nCOMMIT;")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Driver mobile location migration")
    parser.add_argument("database", type=Path)
    parser.add_argument("--reverse", action="store_true")
    args = parser.parse_args()
    migrate(args.database, reverse=args.reverse)
    print(f"{'Reverted' if args.reverse else 'Applied'} migration 007: {args.database.resolve()}")


if __name__ == "__main__":
    main()
