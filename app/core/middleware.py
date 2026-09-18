from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import get_settings
from app.core.security import PANEL_SESSION_COOKIE


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allowed(self, key: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - window:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True

    def clear(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)


_limiter = SlidingWindowLimiter()


class ApplicationSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        client = request.client.host if request.client else "unknown"
        path = request.url.path
        login_key = f"login:{client}"
        if path == "/api/auth/session" and request.method == "POST":
            if not _limiter.allowed(
                login_key, settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds
            ):
                return JSONResponse({"detail": "Too many authentication attempts"}, status_code=429, headers={"Retry-After": str(settings.login_rate_limit_window_seconds)})
        elif path in {"/fleet/active", "/routes/preview", "/trafegus/vehicles/consult"}:
            if not _limiter.allowed(
                f"sensitive:{client}:{path}", settings.sensitive_rate_limit_attempts, settings.sensitive_rate_limit_window_seconds
            ):
                return JSONResponse({"detail": "Too many requests"}, status_code=429, headers={"Retry-After": str(settings.sensitive_rate_limit_window_seconds)})

        if not settings.development and request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.cookies.get(PANEL_SESSION_COOKIE):
            origin = request.headers.get("origin")
            allowed = {value.strip() for value in settings.frontend_origins.split(",") if value.strip()}
            if not origin or origin not in allowed:
                return JSONResponse({"detail": "Request origin is not allowed"}, status_code=403)

        response = await call_next(request)
        if path == "/api/auth/session" and request.method == "POST" and response.status_code < 400:
            _limiter.clear(login_key)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "geolocation=(self), camera=(), microphone=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "script-src 'self' https://cdn.jsdelivr.net; img-src 'self' data:; frame-ancestors 'none'"
            if settings.development else "default-src 'none'; frame-ancestors 'none'",
        )
        if not settings.development:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
