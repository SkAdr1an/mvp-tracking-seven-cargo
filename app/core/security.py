from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from fastapi import Cookie, Depends, Header, HTTPException

from app.core.config import get_settings


PANEL_SESSION_COOKIE = "seven_panel_session"


class Role(StrEnum):
    ADMIN = "Administrador"
    MANAGER = "Gestor"
    OPERATIONS = "Operacional"
    TRACKING = "Tracking"
    REGISTRATION = "Cadastro"
    FINANCE = "Financeiro"
    READ_ONLY = "Consulta"


class Permission(StrEnum):
    OPERATIONAL_READ = "operational:read"
    OPERATIONAL_WRITE = "operational:write"
    INTEGRATIONS_INVOKE = "integrations:invoke"
    PUBLIC_LINKS_MANAGE = "public-links:manage"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
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
        role = Role(settings.panel_admin_role)
    except ValueError:
        return None
    return Principal(settings.panel_admin_username, role)


def configured_user(username: str) -> tuple[Principal, str] | None:
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
            return Principal(username, Role(value["role"])), encoded
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None
    admin = configured_admin()
    if admin and hmac.compare_digest(username, admin.username):
        return admin, settings.panel_admin_password_hash
    return None


def create_panel_session(principal: Principal) -> tuple[str, int]:
    settings = get_settings()
    if len(settings.panel_session_secret) < 32:
        raise RuntimeError("Panel session secret is not configured")
    issued_at = int(time.time())
    expires_at = issued_at + max(settings.panel_session_ttl_hours, 1) * 3600
    payload = _encode(json.dumps(
        {"sub": principal.username, "role": principal.role.value, "iat": issued_at, "exp": expires_at},
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8"))
    signature = _encode(hmac.new(settings.panel_session_secret.encode(), payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{signature}", expires_at


def validate_panel_session(token: str | None) -> Principal | None:
    settings = get_settings()
    if not token or len(settings.panel_session_secret) < 32:
        return None
    try:
        payload, signature = token.split(".", 1)
        expected = _encode(hmac.new(settings.panel_session_secret.encode(), payload.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(_decode(payload))
        now = int(time.time())
        principal = Principal(str(data["sub"]), Role(data["role"]))
        if not principal.username or int(data["iat"]) <= 0 or int(data["iat"]) > now + 60 or int(data["exp"]) <= now:
            return None
        return principal
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def require_panel_session(session: str | None = Cookie(default=None, alias=PANEL_SESSION_COOKIE)) -> Principal:
    principal = validate_panel_session(session)
    if not principal:
        raise HTTPException(status_code=401, detail="Panel authentication required")
    return principal


def require_panel_username(principal: Principal = Depends(require_panel_session)) -> str:
    return principal.username


@lru_cache
def require_permission(permission: Permission):
    def dependency(principal: Principal = Depends(require_panel_session)) -> Principal:
        if permission not in ROLE_PERMISSIONS.get(principal.role, frozenset()):
            raise HTTPException(status_code=403, detail="Permission denied")
        return principal
    return dependency


def require_internal_api_key(
    authorization: str | None = Header(default=None),
    session: str | None = Cookie(default=None, alias=PANEL_SESSION_COOKIE),
) -> str:
    principal = validate_panel_session(session)
    if principal:
        if Permission.PUBLIC_LINKS_MANAGE not in ROLE_PERMISSIONS.get(principal.role, frozenset()):
            raise HTTPException(status_code=403, detail="Permission denied")
        return principal.username
    configured = get_settings().public_trip_internal_api_key
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not configured or not supplied or not hmac.compare_digest(supplied, configured):
        raise HTTPException(status_code=401, detail="Invalid internal credentials")
    return "api-token"
