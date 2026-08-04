"""One-way TomTom -> OpenRouteService routing fallback."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from typing import Any

from app.integrations.openrouteservice import OpenRouteServiceClient
from app.integrations.tomtom import (
    AuthError, RateLimitError, TomTomClient, UnavailableError, UpstreamError,
)


class InvalidRouteGeometry(RuntimeError):
    pass


class RoutingProvidersFailed(RuntimeError):
    def __init__(self, primary: Exception | None, fallback: Exception) -> None:
        super().__init__("All routing providers failed")
        self.primary_error = _sanitized(primary) if primary else None
        self.fallback_error = _sanitized(fallback)


class RoutingProviderService:
    _inflight: dict[str, asyncio.Task[dict[str, Any]]] = {}

    def __init__(self, tomtom=None, openrouteservice=None) -> None:
        self.tomtom = tomtom or TomTomClient()
        self.openrouteservice = openrouteservice or OpenRouteServiceClient()

    async def get_route(self, origin: str, destination: str, *, skip_tomtom: bool = False,
                        request_context: str = "unspecified", **options: Any) -> dict[str, Any]:
        key = hashlib.sha256(json.dumps(
            [origin, destination, skip_tomtom, sorted(options.items())],
            default=str, separators=(",", ":"),
        ).encode()).hexdigest()
        existing = self._inflight.get(key)
        if existing is not None:
            return await asyncio.shield(existing)
        task = asyncio.create_task(self._get_route_once(
            origin, destination, skip_tomtom=skip_tomtom,
            request_context=request_context, **options,
        ))
        self._inflight[key] = task
        try:
            return await asyncio.shield(task)
        finally:
            if self._inflight.get(key) is task:
                self._inflight.pop(key, None)

    async def _get_route_once(self, origin: str, destination: str, *, skip_tomtom: bool,
                              request_context: str, **options: Any) -> dict[str, Any]:
        primary_error: Exception | None = None
        if not skip_tomtom:
            try:
                payload = await self.tomtom.get_route(
                    origin, destination, request_context=request_context, **options
                )
                validate_route_geometry(payload)
                payload.setdefault("_provider", "TomTom")
                return payload
            except Exception as exc:
                if not _fallback_allowed(exc):
                    raise
                primary_error = exc
        try:
            payload = await self.openrouteservice.get_route(
                origin, destination, request_context=request_context, **options
            )
            validate_route_geometry(payload)
            payload.setdefault("_provider", "OpenRouteService")
            if primary_error is not None:
                payload["_fallback_from"] = _sanitized(primary_error)
            return payload
        except Exception as fallback_error:
            raise RoutingProvidersFailed(primary_error, fallback_error) from fallback_error


def validate_route_geometry(payload: dict[str, Any]) -> list[dict[str, float]]:
    route = (payload.get("routes") or [{}])[0]
    points = [point for leg in route.get("legs") or [] for point in leg.get("points") or []]
    if len(points) < 2:
        raise InvalidRouteGeometry("Routing response has no valid road geometry")
    for point in points:
        latitude, longitude = point.get("latitude"), point.get("longitude")
        if not (isinstance(latitude, (int, float)) and isinstance(longitude, (int, float))
                and math.isfinite(latitude) and math.isfinite(longitude)
                and -90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise InvalidRouteGeometry("Routing response contains invalid coordinates")
    return points


def _fallback_allowed(exc: Exception) -> bool:
    if isinstance(exc, (AuthError, RateLimitError, UnavailableError, InvalidRouteGeometry)):
        return True
    return isinstance(exc, UpstreamError) and (
        exc.status_code in {401, 403, 429} or bool(exc.status_code and exc.status_code >= 500)
    )


def _sanitized(exc: Exception | None) -> dict[str, Any] | None:
    if exc is None:
        return None
    return {
        "type": type(exc).__name__,
        "provider": getattr(exc, "provider", None),
        "http_status": getattr(exc, "status_code", None),
        "code": getattr(exc, "code", None),
        "message": str(exc)[:300],
    }
