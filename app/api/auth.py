from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.security import (
    PANEL_SESSION_COOKIE,
    Principal,
    configured_user,
    create_panel_session,
    revoke_panel_session,
    require_panel_session,
    verify_password,
)


router = APIRouter(prefix="/api/auth", tags=["panel-authentication"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)


class SessionResponse(BaseModel):
    authenticated: bool = True
    username: str
    role: str
    expires_at: datetime | None = None


@router.post("/session", response_model=SessionResponse)
async def login(payload: LoginRequest, response: Response) -> SessionResponse:
    settings = get_settings()
    if (
        (not settings.panel_users_file and (not settings.panel_admin_username or not settings.panel_admin_password_hash))
        or len(settings.panel_session_secret) < 32
    ):
        raise HTTPException(status_code=503, detail="Panel authentication is not configured")
    configured = configured_user(payload.username)
    admin = configured[0] if configured else None
    valid_user = admin is not None
    valid_password = verify_password(payload.password, configured[1] if configured else settings.panel_admin_password_hash)
    if not valid_user or not valid_password:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    assert admin is not None
    token, expires_at = create_panel_session(admin)
    response.set_cookie(
        PANEL_SESSION_COOKIE,
        token,
        max_age=max(expires_at - int(datetime.now(timezone.utc).timestamp()), 0),
        httponly=True,
        secure=settings.panel_cookie_secure,
        samesite="strict",
        path="/",
    )
    return SessionResponse(
        username=payload.username,
        role=admin.role.value,
        expires_at=datetime.fromtimestamp(expires_at, timezone.utc),
    )


@router.get("/session", response_model=SessionResponse)
async def session(principal: Principal = Depends(require_panel_session)) -> SessionResponse:
    return SessionResponse(username=principal.username, role=principal.role.value)


@router.get("/me", response_model=SessionResponse)
async def authenticated_user(principal: Principal = Depends(require_panel_session)) -> SessionResponse:
    """Revalida a sessão HttpOnly antes de restaurar o estado autenticado."""
    return SessionResponse(username=principal.username, role=principal.role.value)


@router.delete("/session", status_code=204)
async def logout(
    response: Response,
    _principal: Principal = Depends(require_panel_session),
    session_token: str | None = Cookie(default=None, alias=PANEL_SESSION_COOKIE),
) -> Response:
    revoke_panel_session(session_token)
    response.delete_cookie(PANEL_SESSION_COOKIE, path="/")
    response.status_code = 204
    return response
