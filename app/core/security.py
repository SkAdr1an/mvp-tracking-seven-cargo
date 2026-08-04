from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from fastapi import Cookie, Header, HTTPException

from app.core.config import get_settings


PANEL_SESSION_COOKIE = "seven_panel_session"


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_panel_session(username: str) -> tuple[str, int]:
    settings = get_settings()
    if not settings.panel_session_secret:
        raise RuntimeError("Panel session secret is not configured")
    issued_at = int(time.time())
    expires_at = issued_at + max(settings.panel_session_ttl_hours, 1) * 3600
    payload = _encode(json.dumps(
        {"sub": username, "iat": issued_at, "exp": expires_at},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8"))
    signature = _encode(hmac.new(
        settings.panel_session_secret.encode("utf-8"),
        payload.encode("ascii"),
        hashlib.sha256,
    ).digest())
    return f"{payload}.{signature}", expires_at


def validate_panel_session(token: str | None) -> str | None:
    settings = get_settings()
    if not token or not settings.panel_session_secret:
        return None
    try:
        payload, signature = token.split(".", 1)
        expected = _encode(hmac.new(
            settings.panel_session_secret.encode("utf-8"),
            payload.encode("ascii"),
            hashlib.sha256,
        ).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(_decode(payload))
        username = data.get("sub")
        issued_at = int(data.get("iat", 0))
        expires_at = int(data.get("exp", 0))
        now = int(time.time())
        if (
            not isinstance(username, str)
            or not username
            or issued_at <= 0
            or issued_at > now + 60
            or expires_at <= now
            or expires_at <= issued_at
        ):
            return None
        return username
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def require_panel_session(
    session: str | None = Cookie(default=None, alias=PANEL_SESSION_COOKIE),
) -> str:
    username = validate_panel_session(session)
    if not username:
        raise HTTPException(status_code=401, detail="Panel authentication required")
    return username


def require_internal_api_key(
    authorization: str | None = Header(default=None),
    session: str | None = Cookie(default=None, alias=PANEL_SESSION_COOKIE),
) -> str:
    """Allow a signed panel session or the dedicated server-to-server key."""
    username = validate_panel_session(session)
    if username:
        return username
    configured = get_settings().public_trip_internal_api_key
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not configured or not supplied or not hmac.compare_digest(supplied, configured):
        raise HTTPException(status_code=401, detail="Invalid internal credentials")
    return "api-token"
