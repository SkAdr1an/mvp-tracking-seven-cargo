from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.core.config import PROJECT_ROOT, get_settings
from app.services.database_backup import DatabaseBackupService


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and verify an operations backup")
    parser.add_argument("--label", default="manual")
    parser.add_argument("--directory", type=Path, default=PROJECT_ROOT / "data" / "backups")
    parser.add_argument("--daily", type=int, default=7)
    parser.add_argument("--weekly", type=int, default=4)
    parser.add_argument("--monthly", type=int, default=6)
    args = parser.parse_args()
    service = DatabaseBackupService(get_settings().operations_database_path, args.directory)
    result = service.create(label=args.label)
    removed = service.enforce_retention(
        daily=args.daily, weekly=args.weekly, monthly=args.monthly
    )
    print(json.dumps({"backup": asdict(result), "removed": removed}, indent=2))


if __name__ == "__main__":
    main()
