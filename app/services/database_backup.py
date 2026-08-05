from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class BackupResult:
    path: str
    created_at: str
    size_bytes: int
    sha256: str
    integrity: str


class DatabaseBackupService:
    """Create transactionally consistent SQLite backups without stopping writers."""

    def __init__(self, database_path: str | Path, backup_directory: str | Path) -> None:
        self.database_path = Path(database_path).resolve()
        self.backup_directory = Path(backup_directory).resolve()

    def create(self, *, label: str = "automatic") -> BackupResult:
        if not self.database_path.is_file():
            raise FileNotFoundError(self.database_path)
        safe_label = "".join(char for char in label.lower() if char.isalnum() or char in "-_")[:40]
        if not safe_label:
            safe_label = "backup"
        self.backup_directory.mkdir(parents=True, exist_ok=True)
        created = datetime.now(timezone.utc)
        destination = self.backup_directory / (
            f"operations-{safe_label}-{created.strftime('%Y%m%dT%H%M%SZ')}.sqlite"
        )
        source = sqlite3.connect(
            f"file:{self.database_path.as_posix()}?mode=ro", uri=True, timeout=30
        )
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        integrity = self._integrity(destination)
        if integrity != "ok":
            destination.unlink(missing_ok=True)
            raise RuntimeError(f"Backup integrity failed: {integrity}")
        result = BackupResult(
            path=str(destination),
            created_at=created.isoformat(),
            size_bytes=destination.stat().st_size,
            sha256=self._sha256(destination),
            integrity=integrity,
        )
        destination.with_suffix(".manifest.json").write_text(
            json.dumps(asdict(result), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return result

    def enforce_retention(
        self, *, daily: int = 7, weekly: int = 4, monthly: int = 6
    ) -> list[str]:
        """Keep recent daily, weekly and monthly recovery points.

        Files not selected by any retention bucket are removed. Manifests follow their
        corresponding database file.
        """
        backups = sorted(
            self.backup_directory.glob("operations-*.sqlite"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        keep: set[Path] = set(backups[: max(daily, 0)])
        weekly_seen: set[tuple[int, int]] = set()
        monthly_seen: set[tuple[int, int]] = set()
        for path in backups:
            stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            week = stamp.isocalendar()[:2]
            month = (stamp.year, stamp.month)
            if len(weekly_seen) < max(weekly, 0) and week not in weekly_seen:
                weekly_seen.add(week)
                keep.add(path)
            if len(monthly_seen) < max(monthly, 0) and month not in monthly_seen:
                monthly_seen.add(month)
                keep.add(path)
        removed: list[str] = []
        for path in backups:
            if path in keep:
                continue
            path.unlink()
            path.with_suffix(".manifest.json").unlink(missing_ok=True)
            removed.append(str(path))
        return removed

    @staticmethod
    def verify(path: str | Path, expected_sha256: str | None = None) -> dict[str, object]:
        candidate = Path(path).resolve()
        integrity = DatabaseBackupService._integrity(candidate)
        sha256 = DatabaseBackupService._sha256(candidate)
        return {
            "path": str(candidate),
            "exists": candidate.is_file(),
            "integrity": integrity,
            "sha256": sha256,
            "checksum_matches": expected_sha256 is None or sha256 == expected_sha256,
        }

    @staticmethod
    def _integrity(path: Path) -> str:
        # The backup is closed and immutable at this point. Immutable read mode
        # prevents SQLite from creating -wal/-shm sidecars during verification.
        connection = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True
        )
        try:
            return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            connection.close()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
