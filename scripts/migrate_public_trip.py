"""Apply the public trip portal migration idempotently.

Usage:
    python scripts/migrate_public_trip.py
"""

from pathlib import Path

from app.core.config import get_settings
from app.storage.operations import OperationsRepository
from app.storage.public_trip import PublicTripRepository
from app.storage.traffic import TrafficRepository


def migrate(database_path: str | Path | None = None) -> None:
    operations = OperationsRepository(database_path or get_settings().operations_database_path)
    PublicTripRepository(operations)
    TrafficRepository(operations)


def main() -> None:
    migrate()
    print("Public trip portal migration applied.")


if __name__ == "__main__":
    main()
