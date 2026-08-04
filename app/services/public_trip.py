from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import get_settings
from app.schemas.public_trip import PublicTripResponse
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


class PublicTripUnavailable(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
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
        token_hash = self.token_hash(token)
        link = self.repository.by_hash(token_hash)
        self._development_log(
            "Public link lookup database=%s trip_id=%s hash_hint=%s found=%s",
            self.operations.database_path,
            link["trip_key"] if link else "unknown",
            token_hash[:8],
            bool(link),
        )
        now = datetime.now(timezone.utc)
        if not link:
            raise PublicTripUnavailable("invalid_token")
        trip = self.operations.trip(link["trip_key"])
        if trip and is_final_trip_state(trip.get("state")):
            self.repository.revoke_finished_trip(link["trip_key"])
            raise PublicTripUnavailable("trip_finished")
        expires_at = _parse_datetime(link.get("expires_at")) if link else None
        if link and expires_at and expires_at <= now:
            self.repository.expire(link["id"])
            raise PublicTripUnavailable("expired")
        if link.get("revoked_at") or not bool(link["active"]):
            raise PublicTripUnavailable("revoked")
        if not trip:
            raise PublicTripUnavailable("invalid_token")
        return PublicTripResponse.model_validate(self._public_payload(trip)), link["id"]

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
            history = self.operations.position_history(trip_key, 1)
            latest_source = history[-1].get("source") if history else None
            position = {
                "latitude": trip["last_latitude"],
                "longitude": trip["last_longitude"],
                "speed_kmh": max(trip["last_speed_kmh"], 0) if trip.get("last_speed_kmh") is not None else None,
                "recorded_at": _optional_datetime(
                    trip.get("last_position_at"), "last_position_at", trip_key
                ) or updated,
                "source": self._public_position_source(latest_source),
            }
        settings = get_settings()
        instructions = [
            item.strip() for item in settings.public_trip_instructions.splitlines() if item.strip()
        ]
        return {
            "driver_name": trip.get("current_driver") or "Motorista não informado",
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

    @staticmethod
    def _public_position_source(source: Any) -> str:
        normalized = str(source or "").strip().upper()
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
            return {"latitude": float(lat), "longitude": float(lon)}
        except (TypeError, ValueError):
            return None

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
