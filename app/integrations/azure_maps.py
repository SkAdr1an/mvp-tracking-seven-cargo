from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import get_settings


logger = logging.getLogger(__name__)


class AzureMapsError(RuntimeError):
    def __init__(self, message: str, *, category: str, http_status: int | None = None) -> None:
        super().__init__(message)
        self.category = category
        self.http_status = http_status


class AzureMapsAuthError(AzureMapsError):
    pass


class AzureMapsRateLimitError(AzureMapsError):
    pass


class AzureMapsUnavailableError(AzureMapsError):
    pass


class AzureMapsClient:
    """Read-only Azure Maps Traffic Incidents v2025-01-01 client."""

    api_version = "2025-01-01"

    def __init__(self, subscription_key: str | None = None, base_url: str | None = None) -> None:
        settings = get_settings()
        self.subscription_key = subscription_key or settings.azure_maps_subscription_key
        self.base_url = (base_url or settings.azure_maps_api_url).rstrip("/")
        self.timeout = max(float(settings.azure_maps_timeout_seconds), 1.0)

    async def get_traffic_incidents(self, bbox: tuple[float, float, float, float]) -> dict[str, Any]:
        if not self.subscription_key:
            raise AzureMapsAuthError("Azure Maps subscription key is not configured", category="not_configured")
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/traffic/incident",
                    params={"api-version": self.api_version, "bbox": ",".join(f"{value:.6f}" for value in bbox)},
                    headers={"subscription-key": self.subscription_key, "Accept": "application/geo+json, application/json"},
                )
            except httpx.TimeoutException as exc:
                raise AzureMapsUnavailableError("Azure Maps request timed out", category="timeout") from exc
            except httpx.RequestError as exc:
                raise AzureMapsUnavailableError("Azure Maps network request failed", category="network") from exc
        if response.status_code in {401, 403}:
            raise AzureMapsAuthError("Azure Maps authentication or entitlement rejected", category="auth", http_status=response.status_code)
        if response.status_code == 429:
            raise AzureMapsRateLimitError("Azure Maps rate limit exceeded", category="rate_limited", http_status=429)
        if response.status_code >= 500:
            raise AzureMapsUnavailableError("Azure Maps service unavailable", category="upstream", http_status=response.status_code)
        if response.status_code != 200:
            raise AzureMapsError("Azure Maps request rejected", category="request", http_status=response.status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            raise AzureMapsError("Azure Maps returned invalid JSON", category="contract", http_status=200) from exc
        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
            raise AzureMapsError("Azure Maps returned an incompatible payload", category="contract", http_status=200)
        return payload


AZURE_CATEGORIES = {
    "accident": "ACIDENTE",
    "construction": "OBRA",
    "roadclosure": "VIA_FECHADA",
    "roadclosed": "VIA_FECHADA",
    "congestion": "CONGESTIONAMENTO",
    "disabledvehicle": "VEICULO_PARADO",
    "stoppedvehicle": "VEICULO_PARADO",
    "vehiclestopped": "VEICULO_PARADO",
    "roadhazard": "RISCO_VIA",
    "hazard": "RISCO_VIA",
    "dangerousconditions": "RISCO_VIA",
    "hazardousconditions": "RISCO_VIA",
    "weather": "RISCO_CLIMATICO",
}


def normalize_azure_incident(raw: dict[str, Any], route_id: str, ttl_minutes: int) -> dict[str, Any] | None:
    properties = raw.get("properties") or {}
    geometry = raw.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    while coordinates and isinstance(coordinates[0], (list, tuple)):
        coordinates = coordinates[len(coordinates) // 2]
    if len(coordinates) < 2:
        return None
    try:
        longitude, latitude = float(coordinates[0]), float(coordinates[1])
    except (TypeError, ValueError):
        return None
    original_type = str(properties.get("incidentType") or "Other")
    category = AZURE_CATEGORIES.get(original_type.lower().replace("_", "").replace(" ", ""), "OUTRO")
    if properties.get("isRoadClosed") is True:
        category = "VIA_FECHADA"
    try:
        provider_severity = int(properties.get("severity") or 0)
    except (TypeError, ValueError):
        provider_severity = 0
    severity = "CRITICO" if provider_severity >= 3 or properties.get("isRoadClosed") is True else "ATENCAO" if provider_severity >= 1 or category in {"ACIDENTE", "OBRA", "CONGESTIONAMENTO", "VEICULO_PARADO", "RISCO_VIA"} else "INFORMATIVO"
    now = datetime.now(timezone.utc)
    expires_at = properties.get("endTime") or (now + timedelta(minutes=ttl_minutes)).isoformat()
    try:
        expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= now:
            return None
    except ValueError:
        expires_at = (now + timedelta(minutes=ttl_minutes)).isoformat()
    raw_id = raw.get("id") or hashlib.sha256(f"{original_type}|{latitude:.5f}|{longitude:.5f}".encode()).hexdigest()[:24]
    delay = properties.get("delay")
    try:
        delay_seconds = float(delay) if delay is not None else None
    except (TypeError, ValueError):
        delay_seconds = None
    return {
        "id": f"azure:{raw_id}", "route_id": route_id, "category": category, "severity": severity,
        "original_type": original_type, "source": "Azure Maps Traffic Incidents",
        "description": str(properties.get("description") or properties.get("title") or "Ocorrência de trânsito")[:300],
        "road_name": properties.get("title"), "direction": None, "latitude": latitude, "longitude": longitude,
        "geometry": geometry, "length_m": None, "delay_seconds": delay_seconds, "delay_already_in_eta": False,
        "started_at": properties.get("startTime"), "updated_at": properties.get("lastModifiedTime") or now.isoformat(),
        "expires_at": expires_at, "status": "ACTIVE", "manual": False, "information_source": "Azure Maps",
        "responsible_user": None, "affected_vehicles": [],
        "provider_payload": {"incidentType": original_type, "severity": provider_severity,
                             "isRoadClosed": bool(properties.get("isRoadClosed")),
                             "isTrafficJam": bool(properties.get("isTrafficJam")), "delay": delay_seconds},
    }
