import asyncio

import pytest
from fastapi import HTTPException

from app.api import users
from app.core.security import Permission, Principal, Role, hash_password
from app.storage.users import UserIdentity


ADMIN_ID = "admin-1"
TARGET_ID = "user-2"
ADMIN_PASSWORD = "senha-atual-segura"


def principal() -> Principal:
    return Principal(
        "admin", Role.ADMIN, user_id=ADMIN_ID, display_name="Administrador",
        permissions=frozenset({Permission.USERS_MANAGE}),
    )


class RepositoryStub:
    def __init__(self) -> None:
        self.deleted: str | None = None

    def by_id(self, user_id: str) -> UserIdentity | None:
        if user_id != TARGET_ID:
            return None
        return UserIdentity(TARGET_ID, "operador", "Operador", "ACTIVE", "MONITORING", frozenset())

    def purge_permanently(self, user_id: str, audit=None) -> None:
        self.deleted = user_id


def credentials():
    return principal(), hash_password(ADMIN_PASSWORD)


def test_permanent_delete_uses_fixed_creator_password(monkeypatch):
    repository = RepositoryStub()
    monkeypatch.setattr(users, "_repository", lambda: repository)
    monkeypatch.setattr(users, "get_settings", lambda: type("Settings", (), {
        "creator_delete_password_hash": hash_password(ADMIN_PASSWORD),
    })())

    result = asyncio.run(users.permanently_delete_user(
        TARGET_ID, users.PermanentDeleteRequest(creator_password=ADMIN_PASSWORD), principal(),
    ))

    assert result == {"deleted": True}
    assert repository.deleted == TARGET_ID


def test_permanent_delete_rejects_wrong_creator_password(monkeypatch):
    monkeypatch.setattr(users, "get_settings", lambda: type("Settings", (), {
        "creator_delete_password_hash": hash_password(ADMIN_PASSWORD),
    })())

    with pytest.raises(HTTPException) as error:
        asyncio.run(users.permanently_delete_user(
            TARGET_ID, users.PermanentDeleteRequest(creator_password="senha-incorreta"), principal(),
        ))

    assert error.value.status_code == 403
    assert error.value.detail == "Senha exclusiva de exclusão incorreta"


def test_permanent_delete_rejects_own_account():
    with pytest.raises(HTTPException) as error:
        asyncio.run(users.permanently_delete_user(
            ADMIN_ID, users.PermanentDeleteRequest(creator_password=ADMIN_PASSWORD), principal(),
        ))

    assert error.value.status_code == 409
