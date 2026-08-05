from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import get_settings
from app.schemas.public_trip import MobilePositionRequest, PublicTripResponse
from app.storage.operations import OperationsRepository
from app.storage.public_trip import PublicTripRepository


PUBLIC_STATUS = {
    "PROGRAMADA": "Programada",
    "NA_ORIGEM": "Na origem",
    "EM_CARREGAMENTO": "Em carregamento",
    "EM_VIAGEM": "Em viagem",
    "NO_DESTINO": "No destino",
    "FINALIZADA_NO_SISTEMA": "Finalizada",
    "REABERTA_MANUALMENTE": "Em acompanhamento",
    "RETORNO_SEVEN_CONFIRMADO": "Retorno em andamento",
    "RETORNO_CONCLUIDO": "Retorno concluído",
}

FINAL_TRIP_STATES = frozenset({"FINALIZADA_NO_SISTEMA", "RETORNO_CONCLUIDO"})
logger = logging.getLogger(__name__)


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return round(radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value)), 3)


class PublicTripUnavailable(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class MobileLocationRejected(Exception):
    def __init__(self, reason: str, *, retry_after: int | None = None) -> None:
        self.reason = reason
        self.retry_after = retry_after
        super().__init__(reason)


def is_final_trip_state(state: str | None) -> bool:
    return state in FINAL_TRIP_STATES


def revoke_links_for_finished_trip(operations: OperationsRepository, trip_key: str) -> int:
    return PublicTripRepository(operations).revoke_finished_trip(trip_key)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _optional_datetime(value: Any, field: str, trip_key: str) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return _parse_datetime(str(value))
    except (TypeError, ValueError):
        logger.warning(
            "Public trip ignored invalid optional datetime trip_id=%s field=%s value_type=%s",
            trip_key,
            field,
            type(value).__name__,
        )
        return None


class PublicTripService:
    def __init__(self, operations: OperationsRepository) -> None:
        self.operations = operations
        self.repository = PublicTripRepository(operations)

    @staticmethod
    def token_hash(token: str) -> str:
        settings = get_settings()
        settings.validate_public_trip_runtime()
        pepper = settings.public_trip_token_pepper.encode("utf-8")
        raw = token.encode("ascii")
        return hmac.new(pepper, raw, hashlib.sha256).hexdigest()

    def create_link(
        self, trip_key: str, expires_at: datetime | None, created_by: str | None
    ) -> tuple[dict[str, Any], str]:
        trip = self.operations.trip(trip_key)
        if trip is None:
            raise KeyError(trip_key)
        if is_final_trip_state(trip.get("state")):
            raise ValueError("Finished trips cannot create a public link")
        now = datetime.now(timezone.utc)
        expiry = expires_at
        if expiry is None:
            expiry = now + timedelta(hours=max(get_settings().public_trip_default_ttl_hours, 1))
        elif expiry.tzinfo is None:
            raise ValueError("Expiration must include a timezone")
        else:
            expiry = expiry.astimezone(timezone.utc)
        if expiry <= now:
            raise ValueError("Expiration must be in the future")
        token = secrets.token_urlsafe(32)
        token_hash = self.token_hash(token)
        value = self.repository.create({
            "id": str(uuid.uuid4()),
            "trip_key": trip_key,
            "token_hash": token_hash,
            "created_at": now.isoformat(),
            "expires_at": expiry.isoformat(),
            "created_by": created_by,
        })
        persisted = self.repository.by_hash(token_hash)
        if not persisted or persisted["id"] != value["id"]:
            raise RuntimeError("Public link persistence could not be confirmed")
        self._development_log(
            "Public link persisted database=%s trip_id=%s hash_hint=%s persisted=true",
            self.operations.database_path,
            trip_key,
            token_hash[:8],
        )
        return value, token

    def link_status(self, trip_key: str) -> dict[str, Any] | None:
        if self.operations.trip(trip_key) is None:
            raise KeyError(trip_key)
        link = self.repository.latest_for_trip(trip_key)
        expires_at = _parse_datetime(link.get("expires_at")) if link else None
        if link and bool(link["active"]) and expires_at and expires_at <= datetime.now(timezone.utc):
            self.repository.expire(link["id"])
            link["active"] = 0
        return link

    def revoke_link(self, trip_key: str, actor: str | None) -> bool:
        if self.operations.trip(trip_key) is None:
            raise KeyError(trip_key)
        return self.repository.revoke(trip_key, actor) is not None

    def resolve(self, token: str) -> tuple[PublicTripResponse, str]:
        link, trip = self._resolve_active_link(token)
        token_hash = self.token_hash(token)
        self._development_log(
            "Public link lookup database=%s trip_id=%s hash_hint=%s found=%s",
            self.operations.database_path,
            link["trip_key"] if link else "unknown",
            token_hash[:8],
            bool(link),
        )
        return PublicTripResponse.model_validate(self._public_payload(trip)), link["id"]

    def _resolve_active_link(self, token: str) -> tuple[dict[str, Any], dict[str, Any]]:
        link = self.repository.by_hash(self.token_hash(token))
        if not link:
            raise PublicTripUnavailable("invalid_token")
        trip = self.operations.trip(link["trip_key"])
        if trip and is_final_trip_state(trip.get("state")):
            self.repository.revoke_finished_trip(link["trip_key"])
            raise PublicTripUnavailable("trip_finished")
        expires_at = _parse_datetime(link.get("expires_at"))
        if expires_at and expires_at <= datetime.now(timezone.utc):
            self.repository.expire(link["id"])
            raise PublicTripUnavailable("expired")
        if link.get("revoked_at") or not bool(link["active"]):
            raise PublicTripUnavailable("revoked")
        if not trip:
            raise PublicTripUnavailable("invalid_token")
        return link, trip

    def accept_mobile_position(self, token: str, payload: MobilePositionRequest) -> dict[str, Any]:
        settings = get_settings()
        link, trip = self._resolve_active_link(token)
        if not settings.driver_portal_feature_allowed(
            trip["trip_key"], settings.driver_mobile_location_enabled
        ):
            raise MobileLocationRejected("feature_disabled")
        if not self.repository.mobile_schema_available():
            raise MobileLocationRejected("feature_unavailable")
        if not self._normalize_coordinate({
            "latitude": payload.latitude, "longitude": payload.longitude,
        }):
            raise MobileLocationRejected("invalid_coordinates")
        if payload.accuracy_m > settings.driver_mobile_location_max_accuracy_m:
            raise MobileLocationRejected("accuracy_too_low")
        received = datetime.now(timezone.utc)
        client_at = payload.recorded_at
        if client_at and client_at.tzinfo is None:
            raise MobileLocationRejected("invalid_client_time")
        if client_at and client_at.astimezone(timezone.utc) > received + timedelta(minutes=5):
            raise MobileLocationRejected("invalid_client_time")
        fingerprint = hashlib.sha256(
            f"{trip['trip_key']}|{payload.latitude:.6f}|{payload.longitude:.6f}|{received.isoformat()}".encode()
        ).hexdigest()
        try:
            self.repository.save_mobile_position(
                trip_key=trip["trip_key"], link_id=link["id"], fingerprint=fingerprint,
                latitude=payload.latitude, longitude=payload.longitude,
                accuracy_m=payload.accuracy_m,
                client_recorded_at=client_at.astimezone(timezone.utc).isoformat() if client_at else None,
                received_at=received.isoformat(),
                min_interval_seconds=max(settings.driver_mobile_location_min_interval_seconds, 1),
                max_per_minute=max(settings.driver_mobile_location_max_per_minute, 1),
            )
        except ValueError as exc:
            if str(exc).startswith("rate_"):
                raise MobileLocationRejected(
                    "rate_limited", retry_after=int(str(exc).rsplit(":", 1)[-1])
                ) from exc
            raise
        return {"accepted": True, "received_at": received, "source": "LINK_MOTORISTA"}

    @staticmethod
    def _development_log(message: str, *args: Any) -> None:
        if get_settings().development:
            logger.info(message, *args)

    def status_payload(self, link: dict[str, Any]) -> dict[str, Any]:
        expires = _parse_datetime(link.get("expires_at"))
        active = bool(link["active"]) and not link.get("revoked_at")
        if expires and expires <= datetime.now(timezone.utc):
            active = False
        return {
            "id": link["id"],
            "created_at": link["created_at"],
            "expires_at": link.get("expires_at"),
            "revoked_at": link.get("revoked_at"),
            "active": active,
            "last_access_at": link.get("last_access_at"),
            "access_count": link["access_count"],
            "created_by": link.get("created_by"),
        }

    def _public_payload(self, trip: dict[str, Any]) -> dict[str, Any]:
        trip_key = str(trip.get("trip_key") or "unknown")
        self._development_log("Public trip assembly started trip_id=%s stage=load_optional_data", trip_key)
        route = self.operations.route(trip["route_id"]) if trip.get("route_id") else None
        origin_place, destination_place = self._public_route_places(trip.get("route_id"), route)
        diagnostic = self.operations.diagnostic(trip_key)
        geometry, important_points = self._geometry(trip.get("route_id"))
        updated = _optional_datetime(
            trip.get("last_position_at") or trip.get("updated_at"),
            "last_position_at",
            trip_key,
        )
        if updated is None:
            updated = datetime.now(timezone.utc)
        stale = (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)) > timedelta(
            minutes=max(get_settings().fleet_position_fresh_minutes, 1)
        )
        position = None
        if trip.get("last_latitude") is not None and trip.get("last_longitude") is not None:
            normalized_position = self._normalize_coordinate({
                "latitude": trip.get("last_latitude"),
                "longitude": trip.get("last_longitude"),
            })
            if normalized_position:
                history = self.operations.position_history(trip_key, 1)
                latest_source = history[-1].get("source") if history else None
                position = {
                    **normalized_position,
                    "speed_kmh": max(trip["last_speed_kmh"], 0) if trip.get("last_speed_kmh") is not None else None,
                    "recorded_at": _optional_datetime(
                        trip.get("last_position_at"), "last_position_at", trip_key
                    ) or updated,
                    "source": self._public_position_source(latest_source),
                }
            else:
                logger.warning(
                    "Public trip ignored unavailable position trip_id=%s source=tracker reason=invalid_coordinate",
                    trip_key,
                )
        settings = get_settings()
        sources = self._location_sources(trip_key)
        instructions = [
            item.strip() for item in settings.public_trip_instructions.splitlines() if item.strip()
        ]
        return {
            "driver_name": trip.get("current_driver") or "Motorista não informado",
            "trip_reference": str(trip.get("provider_trip_id") or "").strip() or None,
            "route": {
                "name": route.get("name") if route else None,
                "origin": {
                    **origin_place,
                },
                "destination": {
                    **destination_place,
                },
                "geometry": geometry,
                "important_points": important_points,
            },
            "public_status": PUBLIC_STATUS.get(trip.get("state"), "Em acompanhamento"),
            "loaded_at": _optional_datetime(
                trip.get("loaded_at") or trip.get("started_at"), "loaded_at", trip_key
            ),
            "estimated_arrival_at": _optional_datetime(
                diagnostic.get("eta_at") if diagnostic else None, "eta_at", trip_key
            ),
            "estimated_arrival_updated_at": (
                _optional_datetime(
                    diagnostic.get("calculated_at") or diagnostic.get("updated_at"),
                    "diagnostic_updated_at",
                    trip_key,
                ) if diagnostic else None
            ),
            "last_updated_at": updated,
            "stale": stale,
            "finished": is_final_trip_state(trip.get("state")),
            "vehicle": {
                "plate": trip.get("plate"),
                "trailer_plate": trip.get("trailer_plate"),
            },
            "latest_position": position,
            "location_sources": sources,
            "mobile_location_enabled": bool(
                settings.driver_portal_feature_allowed(
                    trip_key, settings.driver_mobile_location_enabled
                ) and self.repository.mobile_schema_available()
            ),
            "portal_alerts_enabled": settings.driver_portal_feature_allowed(
                trip_key, settings.driver_portal_alerts_enabled
            ),
            "operational_instructions": instructions,
            "central_contact": {
                "name": settings.public_trip_contact_name,
                "phone": settings.public_trip_contact_phone or None,
            },
            "notices": [
                {
                    "title": item.get("public_title") or "Aviso da rota",
                    "description": item.get("public_description") or item["description"],
                    "severity": item["severity"],
                    "updated_at": item["updated_at"],
                }
                for item in self.repository.public_incidents(trip_key, trip.get("route_id"))
                if item.get("description") and item.get("severity") and item.get("updated_at")
            ],
        }

    def _location_sources(self, trip_key: str) -> dict[str, Any]:
        settings = get_settings()
        if not self.repository.mobile_schema_available():
            return {"trafegus": None, "mobile": None, "difference_km": None, "situation": "UNAVAILABLE"}
        primary = self.repository.latest_position_by_source(trip_key, mobile=False)
        mobile = self.repository.latest_position_by_source(trip_key, mobile=True)
        now = datetime.now(timezone.utc)

        def present(value: dict[str, Any] | None, label: str) -> dict[str, Any] | None:
            if not value:
                logger.info(
                    "Public trip location source unavailable trip_id=%s source=%s",
                    trip_key,
                    "mobile" if label == "Celular do motorista" else "tracker",
                )
                return None
            coordinate = self._normalize_coordinate(value)
            if not coordinate:
                logger.warning(
                    "Public trip ignored unavailable source trip_id=%s source=%s reason=invalid_coordinate",
                    trip_key,
                    "mobile" if label == "Celular do motorista" else "tracker",
                )
                return None
            try:
                recorded = _parse_datetime(value.get("recorded_at"))
            except (TypeError, ValueError):
                recorded = None
            age = max(0, int((now - recorded.astimezone(timezone.utc)).total_seconds())) if recorded else 0
            stale_after = (
                settings.fleet_position_fresh_minutes if label == "Rastreador do veículo"
                else settings.driver_mobile_location_stale_minutes
            ) * 60
            return {
                **coordinate,
                "speed_kmh": value.get("speed_kmh"), "recorded_at": recorded,
                "source": label, "accuracy_m": value.get("accuracy_m"),
                "age_seconds": age, "status": "STALE" if age > stale_after else "CURRENT",
            }

        trafegus = present(primary, "Rastreador do veículo")
        cellular = present(mobile, "Celular do motorista")
        difference = None
        if trafegus and cellular:
            difference = _distance_km(
                trafegus["latitude"], trafegus["longitude"],
                cellular["latitude"], cellular["longitude"],
            )
        if trafegus and trafegus["status"] == "CURRENT":
            situation = "DIVERGENT" if difference is not None and difference > settings.driver_mobile_location_divergence_km else "TRAFEGUS_PRIMARY"
        elif cellular and cellular["status"] == "CURRENT":
            situation = "MOBILE_COMPLEMENTARY"
        else:
            situation = "NO_COMMUNICATION"
        return {"trafegus": trafegus, "mobile": cellular, "difference_km": difference, "situation": situation}

    @staticmethod
    def _public_position_source(source: Any) -> str:
        normalized = str(source or "").strip().upper()
        if "SIMULACAO" in normalized:
            return "Posição fictícia de demonstração"
        if normalized == "LINK_MOTORISTA":
            return "Celular do motorista"
        if normalized:
            return "Rastreador do veículo"
        return "Fonte não informada"

    def _geometry(self, route_id: str | None) -> tuple[list[dict[str, float]], list[dict[str, Any]]]:
        if not route_id:
            return [], []
        with self.operations.connect() as connection:
            row = connection.execute(
                """SELECT geometry_json,mandatory_points_json FROM route_geometry_versions
                   WHERE route_id=? AND active=1 ORDER BY id DESC LIMIT 1""",
                (route_id,),
            ).fetchone()
        if not row:
            return [], []
        try:
            geometry = json.loads(row["geometry_json"] or "[]")
            mandatory = json.loads(row["mandatory_points_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            logger.warning("Public trip ignored invalid route geometry route_id=%s", route_id)
            return [], []
        geometry = geometry if isinstance(geometry, list) else []
        mandatory = mandatory if isinstance(mandatory, list) else []
        points = []
        for item in mandatory:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("description")
            if not isinstance(name, str) or not name.strip():
                continue
            coordinate = self._normalize_coordinate(item)
            if coordinate:
                points.append({"name": name.strip(), "coordinate": coordinate})
        return [point for item in geometry if (point := self._normalize_coordinate(item))], points

    @staticmethod
    def _normalize_coordinate(value: Any) -> dict[str, float] | None:
        if isinstance(value, dict):
            lat = value.get("latitude", value.get("lat"))
            lon = value.get("longitude", value.get("lon"))
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            lat, lon = value[0], value[1]
        else:
            return None
        try:
            latitude, longitude = float(lat), float(lon)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            return None
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            return None
        if latitude == 0 and longitude == 0:
            return None
        return {"latitude": latitude, "longitude": longitude}

    @staticmethod
    def _route_coordinate(route: dict[str, Any] | None, prefix: str) -> dict[str, float] | None:
        if not route:
            return None
        return PublicTripService._normalize_coordinate({
            "latitude": route.get(f"{prefix}_latitude"),
            "longitude": route.get(f"{prefix}_longitude"),
        })

    def _public_route_places(
        self, route_id: str | None, route: dict[str, Any] | None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        linked = None
        if route_id:
            try:
                with self.operations.connect() as connection:
                    linked = connection.execute(
                        """SELECT os.name origin_name,os.latitude origin_latitude,
                                  os.longitude origin_longitude,
                                  ds.name destination_name,ds.latitude destination_latitude,
                                  ds.longitude destination_longitude
                           FROM route_site_links l
                           JOIN operational_sites os ON os.id=l.origin_site_id
                           JOIN operational_sites ds ON ds.id=l.destination_site_id
                           WHERE l.route_id=? LIMIT 1""",
                        (route_id,),
                    ).fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc).lower():
                    raise
        endpoint_labels = self._route_endpoint_labels(route)
        places = []
        for prefix, endpoint_label in zip(("origin", "destination"), endpoint_labels):
            city, state = self._city_state(endpoint_label)
            site_name = linked[f"{prefix}_name"] if linked else None
            public_name = self._public_site_name(site_name, state)
            if not public_name:
                public_name = endpoint_label or "Não informado"
            coordinate = (
                self._normalize_coordinate({
                    "latitude": linked[f"{prefix}_latitude"],
                    "longitude": linked[f"{prefix}_longitude"],
                })
                if linked else self._route_coordinate(route, prefix)
            )
            places.append({
                "name": public_name,
                "city": city,
                "state": state,
                "coordinate": coordinate,
            })
        return places[0], places[1]

    @staticmethod
    def _route_endpoint_labels(route: dict[str, Any] | None) -> tuple[str | None, str | None]:
        if not route:
            return None, None
        route_name = str(route.get("name") or "")
        parts = re.split(r"\s*(?:→|->)\s*", route_name, maxsplit=1)
        if len(parts) == 2:
            return parts[0].strip() or None, parts[1].strip() or None
        return (
            PublicTripService._safe_endpoint_label(route.get("origin_name")),
            PublicTripService._safe_endpoint_label(route.get("destination_name")),
        )

    @staticmethod
    def _safe_endpoint_label(value: Any) -> str | None:
        text = str(value or "").strip()
        matches = re.findall(r"([^,·]+?)/([A-Z]{2})(?:\b|$)", text, flags=re.IGNORECASE)
        if not matches:
            return None
        city, state = matches[-1]
        city = re.split(r"[-–]", city)[-1].strip()
        return f"{city}/{state.upper()}" if city else None

    @staticmethod
    def _city_state(value: str | None) -> tuple[str | None, str | None]:
        match = re.fullmatch(r"\s*(.+?)\s*/\s*([A-Z]{2})\s*", value or "", re.IGNORECASE)
        return (match.group(1).strip(), match.group(2).upper()) if match else (None, None)

    @staticmethod
    def _public_site_name(value: Any, state: str | None) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        text = re.sub(r"/[A-Z]{2}\s*$", "", text, flags=re.IGNORECASE)
        words = re.sub(r"[_-]+", " ", text).split()
        if state and len(words) > 1 and words[1].upper() == state:
            words.pop(1)
        acronyms = {"SOC", "CD", "HUB", "WNE", "XPT", "MB", "FBS"}
        display = " ".join(
            word.upper() if word.upper() in acronyms else word.capitalize()
            for word in words
        )
        return display or None
