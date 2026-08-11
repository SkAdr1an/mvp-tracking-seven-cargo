from __future__ import annotations

from app.core.config import get_settings
from app.storage.angellira import AngelLiraRepository
from app.storage.operations import OperationsRepository
from app.storage.public_trip import PublicTripRepository
from app.storage.traffic import TrafficRepository
from scripts.migrate_driver_mobile_location import migrate as migrate_mobile
from scripts.migrate_driver_portal_alerts import migrate as migrate_alerts


def main() -> None:
    path = get_settings().operations_database_path
    operations = OperationsRepository(path)
    PublicTripRepository(operations)
    TrafficRepository(operations)
    AngelLiraRepository(path)
    migrate_mobile(path)
    migrate_alerts(path)
    print("Database schema is ready.")


if __name__ == "__main__":
    main()
