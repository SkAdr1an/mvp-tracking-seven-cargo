from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.services.database_backup import DatabaseBackupService


def test_backup_is_consistent_verified_and_manifested(tmp_path):
    source = tmp_path / "operations.db"
    connection = sqlite3.connect(source)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE evidence(id INTEGER PRIMARY KEY, value TEXT)")
    connection.execute("INSERT INTO evidence(value) VALUES('persisted')")
    connection.commit()

    service = DatabaseBackupService(source, tmp_path / "backups")
    result = service.create(label="Before Risky Change")

    assert result.integrity == "ok"
    assert result.size_bytes > 0
    assert not Path(f"{result.path}-wal").exists()
    assert not Path(f"{result.path}-shm").exists()
    assert "before-risky-change" not in result.path  # spaces are removed, not guessed
    backup = sqlite3.connect(f"file:{result.path}?mode=ro", uri=True)
    assert backup.execute("SELECT value FROM evidence").fetchone()[0] == "persisted"
    backup.close()
    manifest = json.loads((tmp_path / "backups" / (result.path.split("\\")[-1].replace(".sqlite", ".manifest.json"))).read_text())
    assert manifest["sha256"] == result.sha256
    assert service.verify(result.path, result.sha256)["checksum_matches"] is True
    connection.close()


def test_retention_removes_unselected_old_backups(tmp_path):
    source = tmp_path / "operations.db"
    sqlite3.connect(source).close()
    service = DatabaseBackupService(source, tmp_path / "backups")
    created = [service.create(label=f"copy-{index}") for index in range(4)]
    removed = service.enforce_retention(daily=1, weekly=0, monthly=0)
    assert len(removed) == 3
    assert service.verify(created[-1].path)["integrity"] == "ok"
