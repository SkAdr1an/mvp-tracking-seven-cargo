from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.core.security import Role, legacy_configured_user
from app.storage.migrations import validate_database_schema
from app.storage.users import UserRepository


OFFICIAL_ROLES = {Role.ADMIN, Role.GR, Role.MONITORING}


def import_legacy_user(username: str, display_name: str) -> str:
    settings = get_settings()
    validate_database_schema(settings.operations_database_path)
    configured = legacy_configured_user(username)
    if configured is None:
        raise RuntimeError("Legacy user is not configured or active")
    principal, password_hash = configured
    if principal.role not in OFFICIAL_ROLES:
        raise RuntimeError("Legacy user role does not map to an official role")
    repository = UserRepository(settings.operations_database_path)
    if repository.by_username(username):
        raise RuntimeError("Persistent user already exists")
    user = repository.create(
        username=username, display_name=display_name,
        password_hash=password_hash, role_code=principal.role.value,
    )
    repository.revoke_legacy_sessions(username)
    return user.id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import one explicitly selected legacy panel user into persistent storage."
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args()
    import_legacy_user(args.username, args.display_name)
    print("Legacy panel user imported successfully.")


if __name__ == "__main__":
    main()
