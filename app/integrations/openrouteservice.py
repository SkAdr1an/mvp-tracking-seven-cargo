"""OpenRouteService routing contingency client."""

from __future__ import annotations

import hashlib
import math
import sqlite3
import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.storage.sqlite_runtime import connect_existing_database
from app.integrations.tomtom import AuthError, RateLimitError, UnavailableError, UpstreamError


class OpenRouteServiceClient:
    base_url = "https://api.openrouteservice.org"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or get_settings().openrouteservice_api_key

    async def get_route(
        self,
        origin: str,
        destination: str,
        *,
        travel_mode: str = "truck",
        include_traffic: bool = False,
        departure_at: str | None = None,
        request_context: str = "unspecified",
    ) -> dict[str, Any]:
        del include_traffic, departure_at
        if not self.api_key:
            raise AuthError("OPENROUTESERVICE_API_KEY not configured", 401, "NOT_CONFIGURED")
        if travel_mode != "truck":
            raise ValueError("OpenRouteService contingency only accepts truck routing")
        coordinates = _coordinates(origin, destination)
        fingerprint = hashlib.sha256(
            f"{origin}|{destination}|driving-hgv".encode()
        ).hexdigest()
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self.base_url}/v2/directions/driving-hgv/geojson",
                    headers={"Authorization": self.api_key, "Content-Type": "application/json"},
                    json={"coordinates": coordinates},
                )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            self._audit(fingerprint, request_context, None, "UNAVAILABLE", started)
            raise UnavailableError("OpenRouteService unavailable") from exc
        code = _error_code(response)
        if response.status_code in {401, 403}:
            self._audit(fingerprint, request_context, response.status_code, code or "AUTH_ERROR", started)
            raise AuthError("OpenRouteService authentication failed", response.status_code, code)
        if response.status_code == 429:
            self._audit(fingerprint, request_context, 429, code or "RATE_LIMIT", started)
            raise RateLimitError("OpenRouteService rate limit exceeded")
        if response.status_code >= 500:
            self._audit(fingerprint, request_context, response.status_code, code or "UNAVAILABLE", started)
            raise UnavailableError("OpenRouteService unavailable")
        if response.status_code != 200:
            self._audit(fingerprint, request_context, response.status_code, code or "INVALID_REQUEST", started)
            raise UpstreamError("OpenRouteService", response.status_code, code or "Request rejected")
        payload = _normalize(response.json())
        self._audit(fingerprint, request_context, 200, "SUCCESS", started)
        return payload

    @staticmethod
    def _audit(fingerprint: str, context: str, status: int | None, result: str, started: float) -> None:
        try:
            connection = connect_existing_database(
                get_settings().operations_database_path, timeout=5
            )
            connection.execute(
                """INSERT INTO routing_api_usage
                   (request_fingerprint,context,travel_mode,traffic_enabled,http_status,
                    result,latency_ms,occurred_at,provider)
                   VALUES(?,?,?,?,?,?,?,datetime('now'),'openrouteservice')""",
                (fingerprint, context[:80], "truck", 0, status, result[:80],
                 round((time.perf_counter() - started) * 1000)),
            )
            connection.commit()
            connection.close()
        except Exception:
            pass


def _coordinates(origin: str, destination: str) -> list[list[float]]:
    values = [*origin.split(":"), destination]
    result: list[list[float]] = []
    for value in values:
        try:
            latitude, longitude = (float(item) for item in value.split(","))
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid routing coordinates") from exc
        if not (math.isfinite(latitude) and math.isfinite(longitude)
                and -90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("Invalid routing coordinates")
        result.append([longitude, latitude])
    return result


def _normalize(payload: dict[str, Any]) -> dict[str, Any]:
    feature = (payload.get("features") or [{}])[0]
    feature_geometry = feature.get("geometry") or {}
    geometry = feature_geometry.get("coordinates") or []
    points = [{"latitude": float(item[1]), "longitude": float(item[0])} for item in geometry]
    summary = (feature.get("properties") or {}).get("summary") or {}
    return {"routes": [{"legs": [{"points": points}], "summary": {
        "lengthInMeters": summary.get("distance", 0),
        "travelTimeInSeconds": summary.get("duration", 0),
        "trafficDelayInSeconds": 0,
    }}], "_provider": "OpenRouteService", "_validation": {
        "collection_type": payload.get("type"),
        "geometry_type": feature_geometry.get("type"),
        "feature_count": len(payload.get("features") or []),
    }}


def _error_code(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        value = error.get("code") or error.get("message")
    else:
        value = error
    return str(value)[:80] if value else None
