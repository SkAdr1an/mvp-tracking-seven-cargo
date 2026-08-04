"""Idempotent catalog of authorized directional road routes."""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any

from app.integrations.tomtom import TomTomClient
from app.services.routing_provider import RoutingProviderService, RoutingProvidersFailed, validate_route_geometry
from app.services.operational_sites import operational_site_service
from app.services.trip_operations import trip_operations_service
from app.storage.operations import utc_now


GEOMETRY_VERSION = "routing-truck-v1"
GEOMETRY_SOURCE = "Road routing truck profile; direct origin and destination"

ROUTE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "sao-bernardo-contagem-manual",
        "name": "São Bernardo do Campo/SP → Contagem/MG",
        "origin_site_id": "soc-sp-sao-bernardo-ceva",
        "destination_site_id": "cd-shopee-fbs-contagem",
        "sla_minutes": 31 * 60,
        "match_terms": ["SÃO BERNARDO DO CAMPO", "CONTAGEM"],
    },
    {
        "id": "contagem-guarulhos-cumbica",
        "name": "Contagem/MG → Guarulhos/SP",
        "origin_site_id": "cd-shopee-fbs-contagem",
        "destination_site_id": "hub-shopee-cumbica-guarulhos",
        "sla_minutes": 840,
        "match_terms": ["CONTAGEM", "GUARULHOS"],
    },
    {
        "id": "jaboatao-palmares",
        "name": "Jaboatão dos Guararapes/PE → Palmares/PE",
        "origin_site_id": "soc-pe-jaboatao",
        "destination_site_id": "xpt-pe-palmares",
        "sla_minutes": 210,
        "match_terms": ["JABOATAO", "PALMARES"],
    },
    {
        "id": "palmares-jaboatao",
        "name": "Palmares/PE → Jaboatão dos Guararapes/PE",
        "origin_site_id": "xpt-pe-palmares",
        "destination_site_id": "soc-pe-jaboatao",
        "sla_minutes": 210,
        "match_terms": ["PALMARES", "JABOATAO"],
    },
    {
        "id": "jaboatao-betim",
        "name": "Jaboatão dos Guararapes/PE → Betim/MG",
        "origin_site_id": "soc-pe-jaboatao",
        "destination_site_id": "soc-mg-betim",
        "sla_minutes": None,
        "match_terms": ["JABOATAO", "BETIM"],
    },
    {
        "id": "cariacica-cabo-santo-agostinho",
        "name": "Cariacica/ES → Cabo de Santo Agostinho/PE",
        "origin_site_id": "mb-importacao-matriz-cariacica",
        "destination_site_id": "wne-cabo-santo-agostinho",
        "sla_minutes": None,
        "match_terms": ["CARIACICA", "CABO DE SANTO AGOSTINHO"],
    },
    {
        "id": "cariacica-benevides",
        "name": "Cariacica/ES → Benevides/PA",
        "origin_site_id": "mb-importacao-matriz-cariacica",
        "destination_site_id": "wnorte-benevides",
        "sla_minutes": None,
        "match_terms": ["MB IMPORTAÇÃO MATRIZ - CARIACICA", "WNORTE - BENEVIDES"],
    },
)


class OperationalRouteCatalog:
    def __init__(self, repository=None, site_service=None) -> None:
        self.repository = repository or trip_operations_service.repository
        self.site_service = site_service or operational_site_service
        self._provision_lock = asyncio.Lock()

    def _site(self, site_id: str) -> dict[str, Any]:
        sites = {site["id"]: site for site in self.site_service.sites()}
        site = sites.get(site_id)
        if site is None:
            raise RuntimeError(f"CD operacional ativo não encontrado: {site_id}")
        return site

    @staticmethod
    def _route(spec: dict[str, Any], origin: dict[str, Any], destination: dict[str, Any]) -> dict[str, Any]:
        return {
            **spec,
            "origin_name": origin["name"],
            "origin_latitude": origin["latitude"],
            "origin_longitude": origin["longitude"],
            "destination_name": destination["name"],
            "destination_latitude": destination["latitude"],
            "destination_longitude": destination["longitude"],
            "origin_radius_m": origin["entry_radius_m"],
            "destination_radius_m": destination["entry_radius_m"],
            "origin_exit_radius_m": origin["exit_radius_m"],
            "destination_exit_radius_m": destination["exit_radius_m"],
            "origin_dwell_minutes": 10,
            "destination_dwell_minutes": 10,
            "destination_finish_minutes": 30,
            "stop_speed_max_kmh": 5,
            "consecutive_readings": 2,
            "operational_duration_minutes": spec["sla_minutes"],
            "is_express": False,
            "active": True,
        }

    async def ensure_routes(
        self,
        client: TomTomClient | None = None,
        fallback_client=None,
        *,
        explicit: bool = False,
        refresh_existing: bool = False,
    ) -> list[dict[str, Any]]:
        async with self._provision_lock:
            return await self._ensure_routes_locked(
                client, fallback_client, explicit=explicit, refresh_existing=refresh_existing
            )

    async def _ensure_routes_locked(
        self,
        client: TomTomClient | None,
        fallback_client,
        *,
        explicit: bool,
        refresh_existing: bool,
    ) -> list[dict[str, Any]]:
        provider = RoutingProviderService(client or TomTomClient(), fallback_client)
        results: list[dict[str, Any]] = []
        self._link_preserved_routes()
        tomtom_blocked = self._automatic_routing_blocked()
        for spec in ROUTE_SPECS:
            origin = self._site(spec["origin_site_id"])
            destination = self._site(spec["destination_site_id"])
            route = self._route(spec, origin, destination)
            with self.repository.connect() as connection:
                existing = connection.execute(
                    """SELECT id,geometry_json FROM route_geometry_versions
                       WHERE route_id=? AND active=1 ORDER BY id DESC LIMIT 1""",
                    (spec["id"],),
                ).fetchone()
            created = not self._valid_stored_geometry(existing) or refresh_existing
            if created and not explicit and self._attempt_limit_reached(spec["id"]):
                results.append({
                    "route_id": spec["id"],
                    "geometry_created": False,
                    "status": "attempt_limit_reached",
                })
                continue
            if created:
                origin_value = f"{origin['latitude']},{origin['longitude']}"
                destination_value = f"{destination['latitude']},{destination['longitude']}"
                try:
                    payload = await provider.get_route(
                        origin_value,
                        destination_value,
                        travel_mode="truck",
                        include_traffic=False,
                        request_context=f"catalog_provision:{spec['id']}",
                        skip_tomtom=tomtom_blocked,
                    )
                except Exception as exc:
                    primary = getattr(exc, "primary_error", None) or {}
                    failure_status = primary.get("http_status") or getattr(exc, "status_code", None)
                    failure_code = primary.get("code") or getattr(exc, "code", type(exc).__name__)
                    sanitized = (
                        json.dumps({"primary": exc.primary_error, "fallback": exc.fallback_error})
                        if isinstance(exc, RoutingProvidersFailed) else str(exc)
                    )
                    self._record_attempt(
                        spec["id"], "FAILED", failure_status,
                        failure_code, sanitized,
                    )
                    if failure_status in {403, 429}:
                        self._record_attempt(
                            "__global__", "BLOCKED", failure_status,
                            failure_code, str(exc),
                        )
                    raise
                points = validate_route_geometry(payload)
                distance_m, duration_seconds = self._route_metrics(payload, points)
                fallback = payload.get("_fallback_from") or {}
                if fallback.get("http_status") in {403, 429}:
                    self._record_attempt(
                        "__global__", "BLOCKED", fallback["http_status"],
                        fallback.get("code"), fallback.get("message") or "TomTom blocked",
                    )
                    tomtom_blocked = True
                endpoints = [
                    [origin["latitude"], origin["longitude"]],
                    [destination["latitude"], destination["longitude"]],
                ]
                with self.repository.connect() as connection:
                    connection.execute(
                        "UPDATE route_geometry_versions SET active=0 WHERE route_id=?",
                        (spec["id"],),
                    )
                    connection.execute(
                        """INSERT INTO route_geometry_versions
                           (route_id,version,source,geometry_json,mandatory_points_json,
                            corridor_m,segment_tolerances_json,active,created_at,
                            provider,distance_m,duration_seconds)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(route_id,version) DO UPDATE SET
                             source=excluded.source,geometry_json=excluded.geometry_json,
                             mandatory_points_json=excluded.mandatory_points_json,
                             provider=excluded.provider,distance_m=excluded.distance_m,
                             duration_seconds=excluded.duration_seconds,active=1""",
                        (
                            spec["id"], GEOMETRY_VERSION,
                            "openrouteservice-driving-hgv" if payload.get("_provider") == "OpenRouteService" else "tomtom-truck",
                            json.dumps(points), json.dumps(endpoints), 300, "[]", 1, utc_now(),
                            payload.get("_provider") or "TomTom", distance_m, duration_seconds,
                        ),
                    )
                self._record_attempt(
                    spec["id"], "SUCCESS", 200, "SUCCESS",
                    f"{len(points)} geometry points persisted",
                )
            self.repository.upsert_route(route)
            self._link_sites(
                spec["id"], spec["origin_site_id"], spec["destination_site_id"]
            )
            results.append({"route_id": spec["id"], "geometry_created": created})
        return results

    @staticmethod
    def _route_metrics(payload: dict[str, Any], points: list[dict[str, float]]) -> tuple[float, float]:
        route = (payload.get("routes") or [{}])[0]
        summary = route.get("summary") or {}
        distance_m = float(summary.get("lengthInMeters") or 0)
        duration_seconds = float(summary.get("travelTimeInSeconds") or 0)
        if not (math.isfinite(distance_m) and distance_m > 0
                and math.isfinite(duration_seconds) and duration_seconds > 0):
            raise RuntimeError("Routing response has invalid distance or duration")
        direct = _distance_m(points[0], points[-1])
        if direct > 0 and not (distance_m >= direct * 0.8 and distance_m <= direct * 4):
            raise RuntimeError("Routing distance is not plausible for its endpoints")
        return distance_m, duration_seconds

    @staticmethod
    def _valid_stored_geometry(row) -> bool:
        if not row:
            return False
        try:
            points = json.loads(row["geometry_json"])
            validate_route_geometry({"routes": [{"legs": [{"points": points}]}]})
            return True
        except (TypeError, ValueError, json.JSONDecodeError, RuntimeError):
            return False

    def _automatic_routing_blocked(self) -> bool:
        with self.repository.connect() as connection:
            row = connection.execute(
                """SELECT status,http_status FROM routing_provision_attempts
                   WHERE route_id='__global__'"""
            ).fetchone()
        return bool(row and row["status"] == "BLOCKED" and row["http_status"] in {403, 429})

    def _attempt_limit_reached(self, route_id: str) -> bool:
        with self.repository.connect() as connection:
            row = connection.execute(
                """SELECT attempt_count,status FROM routing_provision_attempts
                   WHERE route_id=?""",
                (route_id,),
            ).fetchone()
        return bool(row and row["attempt_count"] >= 1 and row["status"] != "SUCCESS")

    def _record_attempt(
        self,
        route_id: str,
        status: str,
        http_status: int | None,
        error_code: str | None,
        message: str,
    ) -> None:
        now = utc_now()
        with self.repository.connect() as connection:
            connection.execute(
                """INSERT INTO routing_provision_attempts
                   (route_id,attempt_count,status,http_status,error_code,message,
                    last_attempt_at,updated_at)
                   VALUES(?,1,?,?,?,?,?,?)
                   ON CONFLICT(route_id) DO UPDATE SET
                     attempt_count=routing_provision_attempts.attempt_count+1,
                     status=excluded.status,http_status=excluded.http_status,
                     error_code=excluded.error_code,message=excluded.message,
                     last_attempt_at=excluded.last_attempt_at,
                     updated_at=excluded.updated_at""",
                (
                    route_id, status, http_status, (error_code or "")[:80],
                    message[:300], now, now,
                ),
            )

    def _link_preserved_routes(self) -> None:
        with self.repository.connect() as connection:
            connection.execute(
                """UPDATE route_configs
                   SET origin_site_id='soc-mg-betim',
                       destination_site_id='soc-pe-jaboatao'
                   WHERE id='betim-jaboatao'"""
            )
            connection.execute(
                """UPDATE route_configs
                   SET origin_site_id='soc-sp-sao-bernardo-ceva',
                       destination_site_id='cd-shopee-fbs-contagem'
                   WHERE id='sao-bernardo-contagem-manual'"""
            )
        if self.repository.route("betim-jaboatao"):
            self._link_sites("betim-jaboatao", "soc-mg-betim", "soc-pe-jaboatao")
        if self.repository.route("sao-bernardo-contagem-manual"):
            self._link_sites(
                "sao-bernardo-contagem-manual",
                "soc-sp-sao-bernardo-ceva",
                "cd-shopee-fbs-contagem",
            )

    def _link_sites(self, route_id: str, origin_site_id: str, destination_site_id: str) -> None:
        now = utc_now()
        with self.repository.connect() as connection:
            connection.execute(
                """INSERT INTO route_site_links
                   (route_id,origin_site_id,destination_site_id,created_at,updated_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(route_id) DO UPDATE SET
                     origin_site_id=excluded.origin_site_id,
                     destination_site_id=excluded.destination_site_id,
                     updated_at=excluded.updated_at""",
                (route_id, origin_site_id, destination_site_id, now, now),
            )


operational_route_catalog = OperationalRouteCatalog()


def _distance_m(first: dict[str, float], last: dict[str, float]) -> float:
    radius = 6_371_008.8
    phi1, phi2 = math.radians(first["latitude"]), math.radians(last["latitude"])
    dphi = phi2 - phi1
    dlambda = math.radians(last["longitude"] - first["longitude"])
    value = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))
