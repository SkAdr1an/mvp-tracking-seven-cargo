from __future__ import annotations

import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.security import (
    PANEL_SESSION_COOKIE,
    create_panel_session,
    require_panel_session,
)


router = APIRouter(prefix="/api/auth", tags=["panel-authentication"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)


class SessionResponse(BaseModel):
    authenticated: bool = True
    username: str
    expires_at: datetime | None = None


@router.post("/session", response_model=SessionResponse)
async def login(payload: LoginRequest, response: Response) -> SessionResponse:
    settings = get_settings()
    if (
        not settings.panel_admin_username
        or not settings.panel_admin_password
        or len(settings.panel_session_secret) < 32
    ):
        raise HTTPException(status_code=503, detail="Panel authentication is not configured")
    valid_user = hmac.compare_digest(payload.username, settings.panel_admin_username)
    valid_password = hmac.compare_digest(payload.password, settings.panel_admin_password)
    if not valid_user or not valid_password:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token, expires_at = create_panel_session(payload.username)
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
        expires_at=datetime.fromtimestamp(expires_at, timezone.utc),
    )


@router.get("/session", response_model=SessionResponse)
async def session(username: str = Depends(require_panel_session)) -> SessionResponse:
    return SessionResponse(username=username)


@router.get("/me", response_model=SessionResponse)
async def authenticated_user(username: str = Depends(require_panel_session)) -> SessionResponse:
    """Revalida a sessão HttpOnly antes de restaurar o estado autenticado."""
    return SessionResponse(username=username)


@router.delete("/session", status_code=204)
async def logout(response: Response) -> Response:
    response.delete_cookie(PANEL_SESSION_COOKIE, path="/")
    response.status_code = 204
    return response
