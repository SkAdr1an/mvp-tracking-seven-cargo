from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.storage.sqlite_runtime import connect_existing_database


USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_username(value: str) -> str:
    normalized = value.strip().lower()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("Username must use 3-100 lowercase letters, numbers, dots, underscores or hyphens")
    return normalized


@dataclass(frozen=True)
class UserIdentity:
    id: str
    username: str
    display_name: str
    status: str
    role_code: str
    permissions: frozenset[str]

    @property
    def active(self) -> bool:
        return self.status == "ACTIVE"


@dataclass(frozen=True)
class UserCredentials:
    identity: UserIdentity
    password_hash: str


class UserRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(Path(database_path).resolve())

    def _connect(self) -> sqlite3.Connection:
        connection = connect_existing_database(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _identity(connection: sqlite3.Connection, row: sqlite3.Row) -> UserIdentity:
        permissions = frozenset(
            str(value[0])
            for value in connection.execute(
                """SELECT p.code FROM permissions p
                   JOIN role_permissions rp ON rp.permission_id=p.id
                   WHERE rp.role_id=? ORDER BY p.code""",
                (row["role_id"],),
            )
        )
        return UserIdentity(
            id=str(row["id"]), username=str(row["username"]),
            display_name=str(row["display_name"]), status=str(row["status"]),
            role_code=str(row["role_id"]), permissions=permissions,
        )

    def by_id(self, user_id: str) -> UserIdentity | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            return self._identity(connection, row) if row else None

    def has_active_users(self) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM users WHERE status='ACTIVE' LIMIT 1"
            ).fetchone() is not None

    def by_username(self, username: str) -> UserIdentity | None:
        try:
            normalized = normalize_username(username)
        except ValueError:
            return None
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE username=?", (normalized,)).fetchone()
            return self._identity(connection, row) if row else None

    def credentials_by_username(self, username: str) -> UserCredentials | None:
        try:
            normalized = normalize_username(username)
        except ValueError:
            return None
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE username=?", (normalized,)).fetchone()
            if not row:
                return None
            return UserCredentials(self._identity(connection, row), str(row["password_hash"]))

    def create(
        self, *, username: str, display_name: str, password_hash: str, role_code: str,
        created_by_user_id: str | None = None, user_id: str | None = None,
    ) -> UserIdentity:
        normalized = normalize_username(username)
        name = display_name.strip()
        if not name:
            raise ValueError("Display name is required")
        if not password_hash.startswith("scrypt$"):
            raise ValueError("Password hash must use scrypt")
        now = utc_now()
        identifier = user_id or str(uuid.uuid4())
        with self._connect() as connection:
            try:
                connection.execute(
                    """INSERT INTO users(
                       id,username,display_name,password_hash,status,role_id,created_at,
                       created_by_user_id,updated_at,updated_by_user_id,password_changed_at
                       ) VALUES(?,?,?,?,'ACTIVE',?,?,?,?,?,?)""",
                    (identifier, normalized, name, password_hash, role_code, now,
                     created_by_user_id, now, created_by_user_id, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("User could not be created") from exc
            row = connection.execute("SELECT * FROM users WHERE id=?", (identifier,)).fetchone()
            assert row is not None
            return self._identity(connection, row)

    def change_password(self, user_id: str, password_hash: str, actor_user_id: str | None = None) -> UserIdentity:
        if not password_hash.startswith("scrypt$"):
            raise ValueError("Password hash must use scrypt")
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE users SET password_hash=?,password_changed_at=?,updated_at=?,updated_by_user_id=? WHERE id=?",
                (password_hash, now, now, actor_user_id, user_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(user_id)
            self._revoke_sessions(connection, user_id)
            row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            assert row is not None
            return self._identity(connection, row)

    def change_role(self, user_id: str, role_code: str, actor_user_id: str | None = None) -> UserIdentity:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE users SET role_id=?,updated_at=?,updated_by_user_id=? WHERE id=?",
                (role_code, now, actor_user_id, user_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(user_id)
            self._revoke_sessions(connection, user_id)
            row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            assert row is not None
            return self._identity(connection, row)

    def inactivate(self, user_id: str, actor_user_id: str | None = None) -> UserIdentity:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE users SET status='INACTIVE',inactivated_at=?,inactivated_by_user_id=?,
                   updated_at=?,updated_by_user_id=? WHERE id=? AND status='ACTIVE'""",
                (now, actor_user_id, now, actor_user_id, user_id),
            )
            if cursor.rowcount != 1:
                if not connection.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
                    raise KeyError(user_id)
            self._revoke_sessions(connection, user_id)
            row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            assert row is not None
            return self._identity(connection, row)

    def revoke_sessions(self, user_id: str) -> None:
        with self._connect() as connection:
            if not connection.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
                raise KeyError(user_id)
            self._revoke_sessions(connection, user_id)

    def revoke_legacy_sessions(self, username: str) -> None:
        normalized = normalize_username(username)
        with self._connect() as connection:
            connection.execute(
                """UPDATE panel_sessions SET revoked_at=?
                   WHERE user_id IS NULL AND lower(trim(username))=? AND revoked_at IS NULL""",
                (int(datetime.now(timezone.utc).timestamp()), normalized),
            )

    @staticmethod
    def _revoke_sessions(connection: sqlite3.Connection, user_id: str) -> None:
        connection.execute(
            "UPDATE panel_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
            (int(datetime.now(timezone.utc).timestamp()), user_id),
        )
