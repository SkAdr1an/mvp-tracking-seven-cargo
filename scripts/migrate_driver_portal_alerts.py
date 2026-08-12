from __future__ import annotations

import argparse
from pathlib import Path

from app.storage.sqlite_runtime import connect_existing_database

PROJECT_ROOT = Path(__file__).resolve().parents[1]
UP = PROJECT_ROOT / "migrations" / "008_driver_portal_alerts.sql"
DOWN = PROJECT_ROOT / "migrations" / "008_driver_portal_alerts.down.sql"


def migrate(database: str | Path, *, reverse: bool = False) -> None:
    # Reuse the transaction/integrity behavior without coupling migration numbers.
    path = Path(database).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = connect_existing_database(path)
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + (DOWN if reverse else UP).read_text(encoding="utf-8") + "\nCOMMIT;")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite integrity check failed")
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--reverse", action="store_true")
    args = parser.parse_args()
    migrate(args.database, reverse=args.reverse)
    print(f"{'Reverted' if args.reverse else 'Applied'} migration 008: {args.database.resolve()}")


if __name__ == "__main__":
    main()
