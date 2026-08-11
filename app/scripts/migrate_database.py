from __future__ import annotations

from app.core.config import get_settings
from app.storage.migrations import migrate_database


def main() -> None:
    path = get_settings().operations_database_path
    migrate_database(path)
    print("Database schema is ready.")


if __name__ == "__main__":
    main()
