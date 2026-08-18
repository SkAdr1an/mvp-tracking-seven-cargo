import logging
import hashlib
import sqlite3
import time
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import get_settings
from app.storage.sqlite_runtime import connect_existing_database

logger = logging.getLogger(__name__)


def _tomtom_error_code(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return None
    detail = payload.get("detailedError") if isinstance(payload, dict) else None
    code = detail.get("code") if isinstance(detail, dict) else None
    return str(code)[:80] if code else None


class AuthError(Exception):
    """Raised when the provider rejects the API key."""

    def __init__(self, message: str, status_code: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class RateLimitError(Exception):
    """Raised when the provider reports a rate limit."""

    def __init__(self, message: str, status_code: int = 429, code: str = "RATE_LIMIT") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class UnavailableError(Exception):
    """Raised when the provider is unavailable or times out."""


class UpstreamError(Exception):
    def __init__(self, provider: str, status_code: int | None, message: str) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.message = message


class TomTomClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or get_settings().tomtom_api_key
        self.base_url = "https://api.tomtom.com"

    async def get_route(
        self,
        origin: str,
        destination: str,
        travel_mode: str = "car",
        include_traffic: bool = False,
        departure_at: str | None = None,
        request_context: str = "unspecified",
    ) -> dict[str, Any]:
        if not self.api_key:
            raise AuthError("TOMTOM_API_KEY not configured")

        started = time.perf_counter()
        fingerprint = hashlib.sha256(
            f"{origin}|{destination}|{travel_mode}|{include_traffic}".encode()
        ).hexdigest()
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/routing/1/calculateRoute/{origin}:{destination}/json",
                    params={
                        "key": self.api_key,
                        "routeType": "fastest",
                        "travelMode": travel_mode,
                        "traffic": "true" if include_traffic else "false",
                        "departAt": departure_at or "now",
                        "computeTravelTimeFor": "all",
                    },
                )
            except httpx.TimeoutException as exc:
                self._record_routing_usage(
                    fingerprint, request_context, travel_mode, include_traffic,
                    None, "TIMEOUT", started,
                )
                raise UnavailableError("TomTom timeout") from exc
            except httpx.RequestError as exc:
                self._record_routing_usage(
                    fingerprint, request_context, travel_mode, include_traffic,
                    None, "UNAVAILABLE", started,
                )
                raise UnavailableError("TomTom unavailable") from exc

            if response.status_code in {401, 403}:
                code = _tomtom_error_code(response)
                self._record_routing_usage(
                    fingerprint, request_context, travel_mode, include_traffic,
                    response.status_code, code or "AUTH_ERROR", started,
                )
                raise AuthError(
                    "TomTom authentication or entitlement failed",
                    response.status_code,
                    code or "AUTH_ERROR",
                )
            if response.status_code == 429:
                self._record_routing_usage(
                    fingerprint, request_context, travel_mode, include_traffic,
                    429, "RATE_LIMIT", started,
                )
                raise RateLimitError("TomTom rate limit exceeded")
            if response.status_code >= 500:
                self._record_routing_usage(
                    fingerprint, request_context, travel_mode, include_traffic,
                    response.status_code, "UNAVAILABLE", started,
                )
                raise UnavailableError("TomTom service unavailable")

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                body_text = response.text or ""
                sanitized_body = body_text[:300]
                logger.warning(
                    "TomTom upstream error | status=%s | body=%s",
                    response.status_code,
                    sanitized_body,
                )
                raise UpstreamError(
                    provider="TomTom",
                    status_code=response.status_code,
                    message=sanitized_body or "TomTom request failed",
                ) from exc

            payload = response.json()
            self._record_routing_usage(
                fingerprint, request_context, travel_mode, include_traffic,
                response.status_code, "SUCCESS", started,
            )
            return payload

    @staticmethod
    def _record_routing_usage(
        fingerprint: str,
        context: str,
        travel_mode: str,
        include_traffic: bool,
        http_status: int | None,
        result: str,
        started: float,
    ) -> None:
        """Persist only consumption metadata; coordinates and credentials are excluded."""
        try:
            path = get_settings().operations_database_path
            connection = connect_existing_database(path, timeout=5)
            connection.execute(
                """INSERT INTO routing_api_usage
                   (request_fingerprint,context,travel_mode,traffic_enabled,
                    http_status,result,latency_ms,occurred_at)
                   VALUES(?,?,?,?,?,?,?,datetime('now'))""",
                (
                    fingerprint, context[:80], travel_mode, int(include_traffic),
                    http_status, result[:80],
                    round((time.perf_counter() - started) * 1000),
                ),
            )
            connection.commit()
            connection.close()
        except Exception:
            logger.warning("Unable to persist TomTom Routing usage metadata")

    async def get_geocode(self, query: str) -> dict[str, Any]:
        if not self.api_key:
            raise AuthError("TOMTOM_API_KEY not configured")

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/search/2/geocode/{quote(query, safe='')}.json",
                    params={"key": self.api_key},
                )
            except httpx.TimeoutException as exc:
                raise UnavailableError("TomTom timeout") from exc
            except httpx.RequestError as exc:
                raise UnavailableError("TomTom unavailable") from exc

            if response.status_code in {401, 403}:
                raise AuthError("TomTom authentication failed")
            if response.status_code == 429:
                raise RateLimitError("TomTom rate limit exceeded")
            if response.status_code >= 500:
                raise UnavailableError("TomTom service unavailable")

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                body_text = response.text or ""
                sanitized_body = body_text[:300]
                logger.warning(
                    "TomTom upstream error | status=%s | body=%s",
                    response.status_code,
                    sanitized_body,
                )
                raise UpstreamError(
                    provider="TomTom",
                    status_code=response.status_code,
                    message=sanitized_body or "TomTom request failed",
                ) from exc

            return response.json()

    async def get_traffic_incidents(self, bbox: tuple[float, float, float, float]) -> dict[str, Any]:
        """Consulta Incident Details v5 sem expor a chave ou respostas em logs."""
        return await self._traffic_get(
            "/traffic/services/5/incidentDetails",
            {
                "bbox": ",".join(f"{value:.6f}" for value in bbox),
                "fields": "{incidents{type,geometry{type,coordinates},properties{id,iconCategory,magnitudeOfDelay,startTime,endTime,from,to,length,delay,roadNumbers,timeValidity,events{code,description,iconCategory},probabilityOfOccurrence,lastReportTime}}}",
            },
            "TomTom Traffic Incidents",
        )

    async def get_flow_segment(self, latitude: float, longitude: float) -> dict[str, Any]:
        """Consulta o segmento de fluxo mais próximo pela Traffic Flow v4."""
        return await self._traffic_get(
            "/traffic/services/4/flowSegmentData/absolute/10/json",
            {"point": f"{latitude:.6f},{longitude:.6f}", "unit": "kmph"},
            "TomTom Traffic Flow",
        )

    async def _traffic_get(self, path: str, params: dict[str, Any], provider: str) -> dict[str, Any]:
        if not self.api_key:
            raise AuthError("TOMTOM_API_KEY not configured")
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=12.0) as client:
            try:
                response = await client.get(f"{self.base_url}{path}", params={**params, "key": self.api_key})
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                raise UnavailableError(f"{provider} unavailable") from exc
        if response.status_code in {401, 403}:
            code = _tomtom_error_code(response) or "AUTH_ERROR"
            raise AuthError(
                f"{provider} authentication or entitlement failed",
                response.status_code,
                code,
            )
        if response.status_code == 429:
            raise RateLimitError(f"{provider} rate limit exceeded")
        if response.status_code >= 500:
            raise UnavailableError(f"{provider} unavailable")
        if response.status_code != 200:
            raise UpstreamError(provider, response.status_code, f"HTTP {response.status_code}")
        payload = response.json()
        payload["_telemetry"] = {"status": response.status_code, "latency_ms": round((time.perf_counter() - started) * 1000)}
        return payload
