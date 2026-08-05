import hashlib
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "data/backups/operations-consistent-before-operational-sites-20260730-115918.db"
CURRENT = ROOT / "data/operations.db"


def table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def counts(connection: sqlite3.Connection) -> dict[str, int]:
    names = table_names(connection)
    return {
        name: connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        for name in sorted(names)
        if name != "sqlite_sequence"
    }


with sqlite3.connect(BACKUP) as before, sqlite3.connect(CURRENT) as after:
    old_counts = counts(before)
    new_counts = counts(after)
    preserved = {
        name: (old_counts[name], new_counts.get(name))
        for name in old_counts
    }
    print(json.dumps({"preserved_table_counts": preserved}, ensure_ascii=False))
    print(
        json.dumps(
            {
                "sites": after.execute(
                    "SELECT COUNT(*) FROM operational_sites"
                ).fetchone()[0],
                "aliases": after.execute(
                    "SELECT COUNT(*) FROM operational_site_aliases"
                ).fetchone()[0],
                "states": after.execute(
                    "SELECT COUNT(*) FROM vehicle_site_states"
                ).fetchone()[0],
                "integrity": after.execute("PRAGMA integrity_check").fetchone()[0],
            },
            ensure_ascii=False,
        )
    )

print("backup_sha256", hashlib.sha256(BACKUP.read_bytes()).hexdigest())
