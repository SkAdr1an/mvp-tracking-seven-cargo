from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from fastapi import Cookie, Depends, Header, HTTPException

from app.core.config import get_settings
from app.storage.sqlite_runtime import connect_existing_database
from app.storage.users import UserRepository


PANEL_SESSION_COOKIE = "seven_panel_session"


class Role(StrEnum):
    ADMIN = "ADMIN"
    GR = "GR"
    MONITORING = "MONITORING"
    MANAGER = "Gestor"
    OPERATIONS = "Operacional"
    TRACKING = "Tracking"
    REGISTRATION = "Cadastro"
    FINANCE = "Financeiro"
    READ_ONLY = "Consulta"


class Permission(StrEnum):
    DASHBOARD_READ = "dashboard:read"
    TRIPS_READ = "trips:read"
    DRIVERS_READ = "drivers:read"
    INCIDENTS_READ = "incidents:read"
    STOPS_READ = "stops:read"
    TRIPS_EDIT = "trips:edit"
    TRIPS_STATUS_CORRECT = "trips:status-correct"
    TRIPS_FINALIZE = "trips:finalize"
    TRIPS_CANCEL = "trips:cancel"
    TRIPS_ARCHIVE = "trips:archive"
    TRIPS_REOPEN = "trips:reopen"
    TRIPS_ASSIGN_ROUTE = "trips:assign-route"
    TRIPS_ASSIGN_DRIVER = "trips:assign-driver"
    REPORTS_GENERATE = "reports:generate"
    PUBLIC_LINKS_MANAGE = "public-links:manage"
    OBSERVATIONS_CREATE = "observations:create"
    OBSERVATIONS_CORRECT_OWN = "observations:correct-own"
    OBSERVATIONS_VOID_ANY = "observations:void-any"
    STOPS_JUSTIFY = "stops:justify"
    INCIDENTS_CREATE = "incidents:create"
    INCIDENTS_EDIT_STRUCTURAL = "incidents:edit-structural"
    INTEGRATIONS_INVOKE = "integrations:invoke"
    AUDIT_READ_OPERATIONAL = "audit:read-operational"
    AUDIT_READ_FULL = "audit:read-full"
    USERS_READ = "users:read"
    USERS_MANAGE = "users:manage"
    ROLES_MANAGE = "roles:manage"
    SETTINGS_READ = "settings:read"
    SETTINGS_MANAGE = "settings:manage"

    # Transitional names used by the existing endpoint guards. Phase 2 will
    # replace them at each boundary with the specific permission above.
    OPERATIONAL_READ = "trips:read"
    OPERATIONAL_WRITE = "trips:edit"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    Role.GR: frozenset({
        Permission.DASHBOARD_READ, Permission.TRIPS_READ, Permission.DRIVERS_READ,
        Permission.INCIDENTS_READ, Permission.STOPS_READ, Permission.TRIPS_EDIT,
        Permission.TRIPS_STATUS_CORRECT, Permission.TRIPS_FINALIZE, Permission.TRIPS_CANCEL,
        Permission.TRIPS_ARCHIVE, Permission.TRIPS_REOPEN, Permission.TRIPS_ASSIGN_ROUTE,
        Permission.TRIPS_ASSIGN_DRIVER, Permission.REPORTS_GENERATE,
        Permission.PUBLIC_LINKS_MANAGE, Permission.OBSERVATIONS_CREATE,
        Permission.OBSERVATIONS_CORRECT_OWN, Permission.STOPS_JUSTIFY,
        Permission.INCIDENTS_CREATE, Permission.INCIDENTS_EDIT_STRUCTURAL,
        Permission.INTEGRATIONS_INVOKE, Permission.AUDIT_READ_OPERATIONAL,
    }),
    Role.MONITORING: frozenset({
        Permission.DASHBOARD_READ, Permission.TRIPS_READ, Permission.DRIVERS_READ,
        Permission.INCIDENTS_READ, Permission.STOPS_READ, Permission.OBSERVATIONS_CREATE,
        Permission.OBSERVATIONS_CORRECT_OWN, Permission.STOPS_JUSTIFY,
        Permission.INCIDENTS_CREATE, Permission.AUDIT_READ_OPERATIONAL,
    }),
    Role.MANAGER: frozenset(),
    Role.OPERATIONS: frozenset(),
    Role.TRACKING: frozenset(),
    Role.REGISTRATION: frozenset(),
    Role.FINANCE: frozenset(),
    Role.READ_ONLY: frozenset(),
}


@dataclass(frozen=True)
class Principal:
    username: str
    role: Role
    user_id: str | None = None
    display_name: str | None = None
    permissions: frozenset[Permission] = frozenset()

    def has_permission(self, permission: Permission | str) -> bool:
        requested = Permission(permission)
        effective = self.permissions or ROLE_PERMISSIONS.get(self.role, frozenset())
        return requested in effective


LEGACY_ROLE_CODES = {
    "Administrador": Role.ADMIN,
    "Gestor": Role.GR,
    "Operacional": Role.MONITORING,
    "Tracking": Role.MONITORING,
    "Cadastro": Role.REGISTRATION,
    "Financeiro": Role.FINANCE,
    "Consulta": Role.READ_ONLY,
}


def parse_role(value: str) -> Role:
    if value in LEGACY_ROLE_CODES:
        return LEGACY_ROLE_CODES[value]
    try:
        return Role(value)
    except ValueError:
        raise


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${_encode(salt)}${_encode(derived)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=_decode(salt), n=int(n), r=int(r), p=int(p), dklen=32
        )
        return hmac.compare_digest(actual, _decode(expected))
    except (ValueError, TypeError):
        return False


def configured_admin() -> Principal | None:
    settings = get_settings()
    if not settings.panel_admin_username or not settings.panel_admin_password_hash:
        return None
    try:
        role = parse_role(settings.panel_admin_role)
    except ValueError:
        return None
    return Principal(
        settings.panel_admin_username, role, display_name=settings.panel_admin_username,
        permissions=ROLE_PERMISSIONS.get(role, frozenset()),
    )


def legacy_configured_user(username: str) -> tuple[Principal, str] | None:
    settings = get_settings()
    if settings.panel_users_file:
        try:
            payload = json.loads(settings.panel_users_file.read_text(encoding="utf-8"))
            matches = [value for value in payload.get("users", []) if value.get("username") == username and value.get("active", True)]
            if len(matches) != 1:
                return None
            value = matches[0]
            encoded = str(value.get("password_hash", ""))
            if not encoded.startswith("scrypt$"):
                return None
            role = parse_role(str(value["role"]))
            return Principal(
                username, role, display_name=str(value.get("display_name") or username),
                permissions=ROLE_PERMISSIONS.get(role, frozenset()),
            ), encoded
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None
    admin = configured_admin()
    if admin and hmac.compare_digest(username, admin.username):
        return admin, settings.panel_admin_password_hash
    return None


def configured_user(username: str) -> tuple[Principal, str] | None:
    settings = get_settings()
    try:
        credentials = UserRepository(settings.operations_database_path).credentials_by_username(username)
    except (OSError, sqlite3.Error):
        credentials = None
    if credentials is not None:
        if not credentials.identity.active:
            return None
        identity = credentials.identity
        try:
            role = parse_role(identity.role_code)
            permissions = frozenset(Permission(code) for code in identity.permissions)
        except ValueError:
            return None
        return Principal(
            identity.username, role, user_id=identity.id, display_name=identity.display_name,
            permissions=permissions,
        ), credentials.password_hash
    return legacy_configured_user(username)


def _user_fingerprint(principal: Principal, password_hash: str) -> str:
    permission_codes = ",".join(sorted(value.value for value in principal.permissions))
    value = (
        f"{principal.user_id or ''}\0{principal.username}\0{principal.display_name or ''}\0"
        f"{principal.role.value}\0{permission_codes}\0{password_hash}"
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _legacy_user_fingerprint(principal: Principal, password_hash: str, stored_role: str) -> str:
    value = f"{principal.username}\0{stored_role}\0{password_hash}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def persistent_users_configured() -> bool:
    try:
        return UserRepository(get_settings().operations_database_path).has_active_users()
    except (OSError, sqlite3.Error):
        return False


def create_panel_session(principal: Principal) -> tuple[str, int]:
    settings = get_settings()
    if len(settings.panel_session_secret) < 32:
        raise RuntimeError("Panel session secret is not configured")
    configured = configured_user(principal.username)
    if configured is None or configured[0].role != principal.role:
        raise RuntimeError("Panel user is not active")
    issued_at = int(time.time())
    expires_at = issued_at + max(settings.panel_session_ttl_hours, 1) * 3600
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    session_id = secrets.token_hex(16)
    try:
        with connect_existing_database(settings.operations_database_path) as connection:
            connection.execute("DELETE FROM panel_sessions WHERE expires_at <= ?", (issued_at,))
            connection.execute(
                """INSERT INTO panel_sessions(
                       id, token_hash, username, role, user_fingerprint,
                       created_at, expires_at, revoked_at, user_id, role_code_snapshot
                   ) VALUES(?,?,?,?,?,?,?,NULL,?,?)""",
                (
                    session_id,
                    token_hash,
                    principal.username,
                    principal.role.value,
                    _user_fingerprint(configured[0], configured[1]),
                    issued_at,
                    expires_at,
                    principal.user_id,
                    principal.role.value,
                ),
            )
    except sqlite3.Error as exc:
        raise RuntimeError("Panel session storage unavailable") from exc
    return token, expires_at


def validate_panel_session(token: str | None) -> Principal | None:
    settings = get_settings()
    if not token or len(settings.panel_session_secret) < 32:
        return None
    try:
        now = int(time.time())
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        with connect_existing_database(settings.operations_database_path) as connection:
            row = connection.execute(
                """SELECT username, role, user_fingerprint, expires_at, revoked_at,
                          user_id, role_code_snapshot
                   FROM panel_sessions WHERE token_hash=?""",
                (token_hash,),
            ).fetchone()
        if not row or row[4] is not None or int(row[3]) <= now:
            return None
        configured = (
            configured_user(str(row[0])) if row[5] is not None
            else legacy_configured_user(str(row[0]))
        )
        if configured is None:
            return None
        principal, password_hash = configured
        # Rows created before schema 11 have neither persistent identity nor a
        # normalized role snapshot. New sessions for a legacy-configured user
        # still use the stronger current fingerprint.
        legacy_session = row[5] is None and row[6] is None
        expected_role = parse_role(str(row[6] or row[1]))
        fingerprint = (
            _legacy_user_fingerprint(principal, password_hash, str(row[1]))
            if legacy_session else _user_fingerprint(principal, password_hash)
        )
        if principal.role != expected_role or not hmac.compare_digest(fingerprint, str(row[2])):
            return None
        return principal
    except (ValueError, TypeError, sqlite3.Error, UnicodeEncodeError):
        return None


def revoke_panel_session(token: str | None) -> None:
    if not token:
        return
    settings = get_settings()
    try:
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        with connect_existing_database(settings.operations_database_path) as connection:
            connection.execute(
                "UPDATE panel_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                (int(time.time()), token_hash),
            )
    except (sqlite3.Error, UnicodeEncodeError) as exc:
        raise RuntimeError("Unable to revoke panel session") from exc


def require_panel_session(session: str | None = Cookie(default=None, alias=PANEL_SESSION_COOKIE)) -> Principal:
    principal = validate_panel_session(session)
    if not principal:
        raise HTTPException(status_code=401, detail="Panel authentication required")
    return principal


def require_panel_username(principal: Principal = Depends(require_panel_session)) -> str:
    return principal.username


@lru_cache
def require_permission(permission: Permission | str):
    requested = Permission(permission)
    def dependency(principal: Principal = Depends(require_panel_session)) -> Principal:
        if not principal.has_permission(requested):
            raise HTTPException(status_code=403, detail="Permission denied")
        return principal
    return dependency


def require_internal_api_key(
    authorization: str | None = Header(default=None),
    session: str | None = Cookie(default=None, alias=PANEL_SESSION_COOKIE),
) -> str:
    principal = validate_panel_session(session)
    if principal:
        if not principal.has_permission(Permission.PUBLIC_LINKS_MANAGE):
            raise HTTPException(status_code=403, detail="Permission denied")
        return principal.username
    configured = get_settings().public_trip_internal_api_key
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not configured or not supplied or not hmac.compare_digest(supplied, configured):
        raise HTTPException(status_code=401, detail="Invalid internal credentials")
    return "api-token"
