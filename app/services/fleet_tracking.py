"""Snapshot operacional da frota com Trafegus como fonte primária."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any
from pathlib import Path

from app.core.config import get_settings
from app.integrations.tomtom import AuthError, RateLimitError, TomTomClient, UnavailableError, UpstreamError
from app.integrations.trafegus import TrafegusClient, TrafegusError
from app.integrations.weather import WeatherClient
from app.services.trip_operations import PositionUpdate, trip_operations_service
from app.services.route_progress import route_progress_service
from app.services.operational_diagnostic import OperationalDiagnosticService
from app.services.operational_sites import operational_site_service
from app.services.routing_provider import RoutingProviderService, RoutingProvidersFailed


_SENSITIVE_PARTS = ("senha", "password", "token", "documento", "cpf", "cnpj", "chassi", "renavam")
logger = logging.getLogger(__name__)
_TRIP_ID_KEYS = ("viagemId", "id_viagem", "viagem_id", "codigo_viagem", "codigoViagem", "idViagem", "viag_codigo")
_SLA_KEYS = (
    "viag_previsao_fim", "previsao_fim_recalculada", "previsao_chegada", "previsao_fim", "data_previsao_fim", "data_fim_prevista",
    "data_prevista_chegada", "sla", "sla_chegada", "data_entrega_prevista",
)
_SCHEDULED_START_KEYS = (
    "viag_previsao_inicio", "previsao_inicio_recalculada", "previsao_inicio",
    "data_previsao_inicio", "data_inicio_prevista", "data_prevista_saida",
    "inicio_previsto", "saida_prevista",
)


class FleetTrackingService:
    def __init__(self, cache_ttl_seconds: int = 60) -> None:
        self.cache_ttl_seconds = cache_ttl_seconds
        self._snapshot: dict[str, Any] | None = None
        self._snapshot_at = 0.0
        self._lock = asyncio.Lock()
        self._weather_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.last_trafegus_success_at: str | None = None
        self.last_trafegus_error_at: str | None = None
        self.last_trafegus_error: str | None = None
        self.last_trafegus_http_status: int | None = None
        self.last_trafegus_request_count: int | None = None
        self.diagnostics = OperationalDiagnosticService(trip_operations_service.repository)

    def cached_trip(self, trip_key: str) -> dict[str, Any] | None:
        """Return already collected data without triggering any external integration."""
        if not self._snapshot:
            return None
        for trip in self._snapshot.get("trips") or []:
            if (trip.get("operational") or {}).get("trip_key") == trip_key:
                result = deepcopy(trip)
                result["portal_snapshot_generated_at"] = self._snapshot.get("generated_at")
                return result
        return None

    def trafegus_health(self) -> dict[str, Any]:
        client = TrafegusClient()
        configured = bool(client.username and client.password and client.document)
        if not configured:
            status = "not_configured"
        elif self.last_trafegus_error_at and (not self.last_trafegus_success_at or self.last_trafegus_error_at > self.last_trafegus_success_at):
            status = "unavailable" if self._snapshot is None else "degraded"
        elif self.last_trafegus_success_at:
            status = "operational"
        else:
            status = "checking"
        return {"status": status, "last_success_at": self.last_trafegus_success_at,
                "last_error_at": self.last_trafegus_error_at, "message": self.last_trafegus_error,
                "http_status": self.last_trafegus_http_status,
                "request_count": self.last_trafegus_request_count,
                "interval_seconds": get_settings().fleet_collector_interval_seconds}

    @staticmethod
    def _read_shared_snapshot(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not isinstance(value.get("trips"), list):
                return None
            value["cache"] = {"hit": True, "shared": True}
            return value
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _write_shared_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(
                json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _shared_snapshot_path() -> Path:
        return get_settings().operations_database_path.parent / "fleet-snapshot.json"

    async def get_snapshot(self, force: bool = False) -> dict[str, Any]:
        settings = get_settings()
        if not settings.fleet_collector_enabled:
            shared = await asyncio.to_thread(
                self._read_shared_snapshot, self._shared_snapshot_path()
            )
            if shared is not None:
                self._snapshot = deepcopy(shared)
                self._snapshot_at = time.monotonic()
                return shared
        if not force and self._snapshot and time.monotonic() - self._snapshot_at < self.cache_ttl_seconds:
            result = deepcopy(self._snapshot)
            result["cache"] = {"hit": True, "age_seconds": round(time.monotonic() - self._snapshot_at, 1)}
            return result
        async with self._lock:
            if not force and self._snapshot and time.monotonic() - self._snapshot_at < self.cache_ttl_seconds:
                result = deepcopy(self._snapshot)
                result["cache"] = {
                    "hit": True,
                    "age_seconds": round(time.monotonic() - self._snapshot_at, 1),
                }
                return result
            try:
                raw = await TrafegusClient().active_trips_with_details()
                telemetry=raw.get("_telemetry") or {}
                self.last_trafegus_http_status=telemetry.get("http_status")
                self.last_trafegus_request_count=telemetry.get("request_count")
                self.last_trafegus_success_at = datetime.now(timezone.utc).isoformat()
                self.last_trafegus_error = None
                # Normalization performs SQLite work and can trigger automatic
                # Chromium report rendering on a trip state transition.
                trips = await asyncio.to_thread(self._normalize_trips, raw)
                operational_site_service.recognize_trips(trips)
                await self._enrich_trips(trips)
                snapshot = self._build_snapshot(trips)
                from app.services.journey_observation import get_journey_observation_service
                get_journey_observation_service(trip_operations_service.repository).reconcile(
                    get_settings().fleet_position_fresh_minutes
                )
                self._snapshot = deepcopy(snapshot)
                self._snapshot_at = time.monotonic()
                await asyncio.to_thread(
                    self._write_shared_snapshot, self._shared_snapshot_path(), snapshot
                )
                snapshot["cache"] = {"hit": False, "age_seconds": 0}
                return snapshot
            except TrafegusError as exc:
                self.last_trafegus_error_at = datetime.now(timezone.utc).isoformat()
                self.last_trafegus_error = str(exc)
                self.last_trafegus_http_status = exc.http_status
                logger.exception(
                    "Falha Trafegus phase=%s category=%s http_status=%s",
                    exc.phase,
                    exc.category,
                    exc.http_status,
                )
                if self._snapshot:
                    stale = deepcopy(self._snapshot)
                    stale["source_status"] = "stale"
                    stale["warning"] = str(exc)
                    stale["cache"] = {"hit": True, "stale": True, "age_seconds": round(time.monotonic() - self._snapshot_at, 1)}
                    return stale
                raise

    def _normalize_trips(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        positions_result = raw.get("positions") or {}
        payload = positions_result.get("data") if positions_result.get("ok") else {}
        records = _active_records(payload)
        details = raw.get("trip_details") or {}
        vehicles = raw.get("vehicle_details") or {}
        normalized: list[dict[str, Any]] = []
        for record in records:
            positions = _as_records(record.get("posicoesViagem") or record.get("posicoes_viagem"))
            if not positions:
                positions = [record]
            for position in positions:
                plate = _plate(position.get("placa") or record.get("placa"))
                if not plate:
                    continue
                metadata = _first_trip((details.get(plate) or {}).get("data"))
                vehicle_metadata = (vehicles.get(plate) or {}).get("data") or {}
                coordinate = _coordinate(position)
                communicated_at = _parse_datetime(
                    position.get("dataPosicao") or position.get("data_posicao")
                    or position.get("dataComunicacao") or position.get("data_comunicacao")
                )
                speed_kmh = _speed(position)
                if speed_kmh is None:
                    speed_kmh = _speed(record)
                trip_id = _first_value(record, _TRIP_ID_KEYS) or _first_value(metadata, _TRIP_ID_KEYS)
                existing_trip = trip_operations_service.repository.trip(
                    trip_operations_service.trip_key(
                        plate, str(trip_id) if trip_id not in (None, "") else None
                    )
                )
                if existing_trip and (
                    existing_trip.get("state") in {"FINALIZADA_NO_SISTEMA", "RETORNO_CONCLUIDO", "CANCELADA"}
                    or existing_trip.get("archived_at")
                ):
                    continue
                destination = _destination(metadata)
                sla = _first_datetime(metadata, _SLA_KEYS)
                scheduled_start = _first_datetime(metadata, _SCHEDULED_START_KEYS)
                route_description = _route_description(metadata)
                driver_status = trip_operations_service.reconcile_driver(
                    plate=plate,
                    trip_id=str(trip_id) if trip_id not in (None, "") else None,
                    trip_candidates=_trip_driver_candidates(position, metadata),
                    vehicle_candidates=_vehicle_driver_candidates(vehicle_metadata),
                )
                if driver_status.get("current_driver"):
                    from app.services.driver_history import DriverHistoryService
                    DriverHistoryService(trip_operations_service.repository).sync_trip(
                        trip_operations_service.trip_key(plate, str(trip_id) if trip_id not in (None, "") else None),
                        source="trafegus:trip-discovery",
                    )
                driver = driver_status.get("current_driver") or _driver_name(position, metadata)
                item = {
                    "trip_id": str(trip_id) if trip_id not in (None, "") else None,
                    "plate": plate,
                    "trailer_plate": _plate(position.get("placaCarreta") or position.get("placa_carreta")),
                    "driver": driver or "Não informado",
                    "route": route_description,
                    "position": coordinate,
                    "speed_kmh": speed_kmh,
                    "location_description": _safe_text(position.get("descricaoLocal") or position.get("descricao_local")),
                    "communicated_at": communicated_at.isoformat() if communicated_at else None,
                    "stale": _is_stale(communicated_at, get_settings().fleet_position_fresh_minutes),
                    "stale_minutes": round((datetime.now(timezone.utc) - communicated_at).total_seconds() / 60, 1) if communicated_at else None,
                    "status": _safe_text(position.get("statusCarga") or position.get("status_carga") or "EM ROTA"),
                    "tracker": _safe_text(position.get("rastreadora") or position.get("tecnologia") or position.get("descricaoSistema")),
                    "destination": destination,
                    "sla_at": sla.isoformat() if sla else None,
                    "prediction": {"status": "unavailable", "reason": "Destino ou posição indisponível"},
                    "weather_risks": [],
                    "api_status": {"trafegus": "connected", "tomtom": "not_checked", "openweather": "not_checked"},
                    **driver_status,
                }
                if coordinate and communicated_at:
                    operation = trip_operations_service.process_position(PositionUpdate(
                        plate=plate,
                        trip_id=item["trip_id"],
                        latitude=coordinate["latitude"],
                        longitude=coordinate["longitude"],
                        speed_kmh=speed_kmh,
                        recorded_at=communicated_at,
                        source="trafegus",
                        route_description=route_description,
                    ))
                    item["operational"] = operation.get("trip")
                    item["route_recognition"] = operation.get("route_recognition") or (
                        trip_operations_service.recognize_route(route_description)
                    )
                    if item["operational"]:
                        self._sync_provider_plan(item["operational"]["trip_key"], scheduled_start, sla)
                        detail = trip_operations_service.detail(item["operational"]["trip_key"])
                        if detail:
                            item["operational"] = detail
                            if detail.get("state") in {"RETORNO_SEVEN_CONFIRMADO", "RETORNO_CONCLUIDO"}:
                                return_route = detail.get("route") or {}
                                item["destination"] = {
                                    "description": return_route.get("destination_name"),
                                    "position": {
                                        "latitude": return_route.get("destination_latitude"),
                                        "longitude": return_route.get("destination_longitude"),
                                    },
                                }
                else:
                    item["operational"] = trip_operations_service.repository.trip(
                        trip_operations_service.trip_key(plate, item["trip_id"])
                    )
                operation=item.get("operational") or {}
                recognition = item.get("route_recognition") or trip_operations_service.recognize_route(route_description)
                item["route_recognition"] = {key: value for key, value in recognition.items() if key != "route"}
                effective_route_id = (
                    recognition.get("route", {}).get("id")
                    if recognition.get("status") == "RECOGNIZED"
                    else None
                )
                if coordinate:
                    item["route_progress"]=route_progress_service.calculate(
                        operation.get("trip_key") or trip_operations_service.trip_key(plate,item["trip_id"]),
                        effective_route_id,coordinate["latitude"],coordinate["longitude"],
                        item["speed_kmh"],item["communicated_at"],item["stale"],
                    )
                else:item["route_progress"]=None
                progress = item.get("route_progress") or {}
                issue_code = None
                if recognition.get("status") in {"UNIDENTIFIED", "AMBIGUOUS"}:
                    issue_code = "ROUTE_NOT_RECOGNIZED"
                elif recognition.get("status") == "GEOMETRY_PENDING" or progress.get("reason") == "geometry_unavailable":
                    issue_code = "ROUTE_GEOMETRY_UNAVAILABLE"
                elif not coordinate:
                    issue_code = "POSITION_UNAVAILABLE"
                if issue_code:
                    logger.warning(
                        "Operational data unavailable code=%s trip_key=%s plate=%s route_id=%s",
                        issue_code,
                        operation.get("trip_key") or trip_operations_service.trip_key(plate,item["trip_id"]),
                        plate,
                        effective_route_id,
                    )
                item["dedup_key"] = _dedup_key(item)
                normalized.append(item)
        return _deduplicate(normalized)

    @staticmethod
    def _sync_provider_plan(trip_key: str, scheduled_start: datetime | None, sla: datetime | None) -> None:
        if not scheduled_start and not sla:
            return
        repository = trip_operations_service.repository
        current = repository.plan(trip_key) or {}
        incoming_start = scheduled_start.isoformat() if scheduled_start else current.get("scheduled_start_at")
        incoming_arrival = sla.isoformat() if sla else current.get("scheduled_arrival_at")
        if current.get("source") not in {None, "TRAFEGUS"}:
            if incoming_start and incoming_start != current.get("scheduled_start_at"):
                repository.add_event(
                    trip_key, "SCHEDULE_SOURCE_DIVERGENCE", datetime.now(timezone.utc).isoformat(),
                    "trafegus", "Horário do Trafegus diverge da reprogramação manual",
                    metadata={"trafegus_scheduled_start_at": incoming_start,
                              "manual_scheduled_start_at": current.get("scheduled_start_at")},
                    idempotency_key=f"schedule-divergence:{trip_key}:{incoming_start}",
                )
            return
        values = {
            "scheduled_start_at": incoming_start,
            "scheduled_arrival_at": incoming_arrival,
            "customer_commitment_at": sla.isoformat() if sla else current.get("customer_commitment_at"),
            "planned_loading_minutes": current.get("planned_loading_minutes") or 0,
            "planned_stops_minutes": current.get("planned_stops_minutes") or 0,
            "operational_buffer_minutes": current.get("operational_buffer_minutes") or 0,
            "source": "TRAFEGUS", "notes": "Sincronizado automaticamente do Trafegus",
        }
        if any(values.get(key) != current.get(key) for key in ("scheduled_start_at", "scheduled_arrival_at", "customer_commitment_at")):
            repository.save_plan(trip_key, values, "system:trafegus")

    async def _enrich_trips(self, trips: list[dict[str, Any]]) -> None:
        semaphore = asyncio.Semaphore(3)

        async def enrich(trip: dict[str, Any]) -> None:
            operation = trip.get("operational") or {}
            candidate = operation.get("return_candidate") or {}
            if operation.get("state") == "FINALIZADA_NO_SISTEMA" or candidate.get("state") in {
                "AGUARDANDO_CONFIRMACAO", "RETORNO_EXTERNO"
            }:
                trip["prediction"] = {
                    "status": "not_applicable",
                    "reason": "Viagem encerrada ou retorno aguardando decisão operacional",
                }
                return
            if not trip.get("position"):
                return
            if not get_settings().fleet_routing_enabled:
                async with semaphore:
                    await self._weather_from_persisted_route(trip)
                trip["prediction"] = {
                    "status": "unavailable",
                    "reason": "Roteamento automático por viagem desativado para controle de consumo",
                }
                trip["api_status"]["tomtom"] = "automatic_routing_disabled"
                return
            if not (trip.get("destination") or {}).get("position"):
                return
            async with semaphore:
                await self._enrich_prediction(trip)

        await asyncio.gather(*(enrich(trip) for trip in trips))
        from app.services.traffic_monitoring import traffic_repository
        from app.services.route_deviation import route_deviation_service
        from app.services.operational_observations import OperationalObservationService
        observation_service = OperationalObservationService(trip_operations_service.repository.database_path)
        all_incidents = traffic_repository.incidents()
        for trip in trips:
            operation = trip.get("operational") or {}
            plan = operation.get("plan") or {}
            planned_commitment = plan.get("customer_commitment_at") or plan.get("scheduled_arrival_at")
            if planned_commitment:
                trip["sla_at"] = planned_commitment
                trip.setdefault("prediction", {})["sla_at"] = planned_commitment
            relevant = [
                incident for incident in all_incidents
                if any(
                    vehicle.get("trip_key") == operation.get("trip_key")
                    or vehicle.get("plate") == trip.get("plate")
                    for vehicle in incident.get("affected_vehicles") or []
                )
            ]
            trip["diagnostic"] = self.diagnostics.calculate(
                trip, relevant, route_deviation_service.active_for_trip(operation.get("trip_key"))
                if operation.get("trip_key") else None,
            )
            self._ensure_operational_classification(trip)
            if operation.get("trip_key") and not operation.get("started_at"):
                observations = observation_service.list_for_trip(operation["trip_key"])
                critical = next((item for item in observations if item.get("status") == "ACTIVE"
                                 and (item.get("metadata") or {}).get("critical_impact")), None)
                classification = "CRITICA" if critical else (
                    "NORMAL" if _parse_datetime(plan.get("scheduled_start_at"))
                    and _parse_datetime(plan.get("scheduled_start_at")) > datetime.now(timezone.utc)
                    else "ATENCAO"
                )
                trip["prediction"]["classification"] = classification
                trip["prediction"]["classification_source"] = "pre_departure_operational_state"
                if trip.get("diagnostic"):
                    trip["diagnostic"]["classification"] = classification
                    trip["diagnostic"]["status_explanation"] = (
                        f"Impacto operacional registrado: {critical['content']}"
                        if critical else "Veículo ainda não teve saída confirmada; o relógio de trânsito não foi iniciado."
                    )

    async def _weather_from_persisted_route(self, trip: dict[str, Any]) -> None:
        """Enrich weather without enabling per-trip external routing."""
        from app.services.route_deviation import route_deviation_service

        operation = trip.get("operational") or {}
        route_id = operation.get("route_id")
        persisted = route_deviation_service.geometry(str(route_id)) if route_id else None
        points = (persisted or {}).get("geometry") or []
        valid = [
            {"latitude": float(point["latitude"]), "longitude": float(point["longitude"])}
            for point in points
            if isinstance(point, dict)
            and isinstance(point.get("latitude"), (int, float))
            and isinstance(point.get("longitude"), (int, float))
        ]
        if len(valid) < 3:
            trip["api_status"]["openweather"] = "not_checked"
            trip["api_status"]["openweather_reason"] = "route_geometry_unavailable"
            return
        progress = trip.get("route_progress") or {}
        percent = progress.get("progress_percent")
        if isinstance(percent, (int, float)) and 0 <= percent <= 100:
            start = min(round((len(valid) - 1) * percent / 100), len(valid) - 3)
            valid = valid[max(start, 0):]
        remaining_km = progress.get("remaining_distance_km")
        remaining_minutes = max(float(remaining_km), 0) / 55 * 60 if isinstance(remaining_km, (int, float)) else 0
        await self._weather_along_route(trip, valid, remaining_minutes)

    @staticmethod
    def _ensure_operational_classification(trip: dict[str, Any]) -> None:
        """Keep SLA filters usable when the routing provider is unavailable."""
        prediction = trip.setdefault("prediction", {})
        if prediction.get("classification"):
            return

        diagnostic = trip.get("diagnostic") or {}
        diagnostic_classification = diagnostic.get("classification")
        if diagnostic_classification:
            prediction["classification"] = diagnostic_classification
            prediction["classification_source"] = "operational_diagnostic"
            if not prediction.get("eta_at") and diagnostic.get("eta_at"):
                prediction["eta_at"] = diagnostic["eta_at"]
            if prediction.get("delay_minutes") is None:
                delta = diagnostic.get("commitment_delta_minutes")
                prediction["delay_minutes"] = round(max(float(delta), 0), 1) if delta is not None else None
            return

        sla = _parse_datetime(trip.get("sla_at") or prediction.get("sla_at"))
        prediction["classification"] = (
            "CRITICA" if sla and sla <= datetime.now(timezone.utc) else "ATENCAO"
        )
        prediction["classification_source"] = "sla_fallback"
        prediction.setdefault("sla_at", sla.isoformat() if sla else None)

    async def _enrich_prediction(self, trip: dict[str, Any]) -> None:
        origin = trip["position"]
        destination = trip["destination"]["position"]
        try:
            payload = await RoutingProviderService().get_route(
                f"{origin['latitude']},{origin['longitude']}",
                f"{destination['latitude']},{destination['longitude']}",
                travel_mode="truck",
                include_traffic=True,
                departure_at="now",
                request_context="fleet_prediction",
            )
            route = (payload.get("routes") or [{}])[0]
            summary = route.get("summary") or {}
            distance_km = float(summary.get("lengthInMeters") or 0) / 1000
            provider_minutes = float(summary.get("travelTimeInSeconds") or 0) / 60
            live_delay = float(summary.get("trafficDelayInSeconds") or 0) / 60
            fleet_minutes = distance_km / 55 * 60 if distance_km else provider_minutes
            remaining_minutes = max(provider_minutes, fleet_minutes + live_delay)
            eta = datetime.now(timezone.utc) + timedelta(minutes=remaining_minutes)
            sla = _parse_datetime(trip.get("sla_at"))
            delta_minutes = (eta - sla).total_seconds() / 60 if sla else None
            classification = _classify(delta_minutes, remaining_minutes)
            trip["prediction"] = {
                "status": "available",
                "classification": classification,
                "remaining_distance_km": round(distance_km, 1),
                "provider_minutes": round(provider_minutes, 1),
                "fleet_speed_kmh": 55,
                "remaining_minutes": round(remaining_minutes, 1),
                "live_traffic_delay_minutes": round(live_delay, 1),
                "eta_at": eta.isoformat(),
                "sla_at": sla.isoformat() if sla else None,
                "delay_minutes": round(max(delta_minutes or 0, 0), 1) if sla else None,
                "sla_margin_minutes": round(-delta_minutes, 1) if sla else None,
            }
            trip["api_status"]["tomtom"] = "connected"
            points = _route_points(route)
            await self._weather_along_route(trip, points, remaining_minutes)
        except (AuthError, RateLimitError, UnavailableError, UpstreamError, RoutingProvidersFailed) as exc:
            trip["api_status"]["tomtom"] = _provider_error_name(exc)
            trip["prediction"] = {"status": "unavailable", "reason": "TomTom indisponível; posição Trafegus preservada"}

    async def _weather_along_route(self, trip: dict[str, Any], points: list[dict[str, float]], remaining_minutes: float) -> None:
        sampled = _sample_points(points, 3)
        if not sampled:
            trip["api_status"]["openweather"] = "not_checked"
            return
        risks: list[dict[str, Any]] = []
        try:
            for index, point in enumerate(sampled, 1):
                fraction = index / (len(sampled) + 1)
                passage = datetime.now(timezone.utc) + timedelta(minutes=remaining_minutes * fraction)
                forecast = await self._forecast(point["latitude"], point["longitude"], passage)
                risk = _weather_risk(forecast, passage, point)
                if risk:
                    risks.append(risk)
            trip["weather_risks"] = risks
            trip["api_status"]["openweather"] = "connected"
        except (AuthError, RateLimitError, UnavailableError):
            trip["api_status"]["openweather"] = "unavailable"

    async def _forecast(self, latitude: float, longitude: float, passage: datetime) -> dict[str, Any]:
        bucket = int(passage.timestamp() // 10800)
        key = f"{latitude:.2f}:{longitude:.2f}:{bucket}"
        cached = self._weather_cache.get(key)
        if cached and time.monotonic() - cached[0] < 900:
            return cached[1]
        payload = await WeatherClient().get_forecast_by_coords(latitude, longitude)
        items = payload.get("list") or []
        selected = min(items, key=lambda item: abs(float(item.get("dt") or 0) - passage.timestamp()), default={})
        self._weather_cache[key] = (time.monotonic(), selected)
        return selected

    @staticmethod
    def _build_snapshot(trips: list[dict[str, Any]]) -> dict[str, Any]:
        counts = {"total": len(trips), "normal": 0, "attention": 0, "critical": 0, "stale": 0, "weather_risks": 0}
        for trip in trips:
            classification = (trip.get("prediction") or {}).get("classification")
            if classification == "NORMAL": counts["normal"] += 1
            elif classification == "ATENCAO": counts["attention"] += 1
            elif classification == "CRITICA": counts["critical"] += 1
            if trip.get("stale"): counts["stale"] += 1
            counts["weather_risks"] += len(trip.get("weather_risks") or [])
        return {
            "source": "trafegus",
            "source_status": "connected",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "counts": counts,
            "trips": trips,
        }


def _active_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        for key in ("viagem", "viagens", "success", "data"):
            if key in value:
                found = _active_records(value[key])
                if found: return found
        if "posicoesViagem" in value or "posicoes_viagem" in value:
            return [value]
        result: list[dict[str, Any]] = []
        for item in value.values(): result.extend(_active_records(item))
        return result
    if isinstance(value, list):
        result: list[dict[str, Any]] = []
        for item in value: result.extend(_active_records(item))
        return result
    return []


def _as_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict): return [value]
    if isinstance(value, list): return [item for item in value if isinstance(item, dict)]
    return []


def _first_trip(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        for key in ("viagens", "viagem", "success", "data"):
            if key in value:
                found = _first_trip(value[key])
                if found: return found
        return value
    if isinstance(value, list): return _first_trip(value[0]) if value else {}
    return {}


def _safe_text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)): return None
    return str(value).strip() or None


def _plate(value: Any) -> str | None:
    candidate = re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()
    return candidate if re.fullmatch(r"[A-Z]{3}[0-9][A-Z0-9][0-9]{2}", candidate) else None


def _coordinate(record: dict[str, Any]) -> dict[str, float] | None:
    raw = record.get("coordenada")
    if isinstance(raw, str):
        parts = re.findall(r"-?\d+(?:\.\d+)?", raw)
        if len(parts) >= 2:
            return {"latitude": float(parts[0]), "longitude": float(parts[1])}
    lat = record.get("latitude") or record.get("lat") or record.get("refe_latitude") or record.get("latitude_baixa")
    lon = record.get("longitude") or record.get("lon") or record.get("lng") or record.get("refe_longitude") or record.get("longitude_baixa")
    try: return {"latitude": float(lat), "longitude": float(lon)}
    except (TypeError, ValueError): return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime): parsed = value
    elif not value: return None
    else:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = None
        for fmt in (None, "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.fromisoformat(text) if fmt is None else datetime.strptime(text, fmt)
                break
            except ValueError: continue
        if parsed is None: return None
    return parsed.replace(tzinfo=timezone(timedelta(hours=-3))).astimezone(timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _first_value(record: dict[str, Any] | None, keys: tuple[str, ...]) -> Any:
    if not isinstance(record, dict): return None
    normalized = {str(key).lower(): value for key, value in record.items()}
    for key in keys:
        value = normalized.get(key.lower())
        if value not in (None, ""): return value
    return None


def _first_datetime(record: dict[str, Any], keys: tuple[str, ...]) -> datetime | None:
    direct = _parse_datetime(_first_value(record, keys))
    if direct: return direct
    for value in record.values():
        if isinstance(value, dict):
            found = _first_datetime(value, keys)
            if found: return found
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    found = _first_datetime(item, keys)
                    if found: return found
    return None


def _destination(record: dict[str, Any]) -> dict[str, Any] | None:
    explicit = record.get("destino")
    if isinstance(explicit, dict):
        position = _coordinate(explicit)
        if position:
            return {
                "description": _safe_text(explicit.get("vloc_descricao") or explicit.get("cidade")) or "Destino",
                "position": position,
            }
    candidates: list[dict[str, Any]] = []
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            kind = str(value.get("tipo_parada") or value.get("tipo") or value.get("tipoLocal") or "").upper()
            if "DESTINO" in kind or "ENTREGA" in kind: candidates.append(value)
            for item in value.values(): walk(item)
        elif isinstance(value, list):
            for item in value: walk(item)
    walk(record)
    direct = {
        "latitude": record.get("latitude_destino") or record.get("destino_latitude"),
        "longitude": record.get("longitude_destino") or record.get("destino_longitude"),
        "description": record.get("destino") or record.get("descricao_destino"),
    }
    candidates = candidates or ([direct] if direct["latitude"] and direct["longitude"] else [])
    if not candidates: return None
    chosen = candidates[-1]
    position = _coordinate(chosen)
    if not position: return None
    return {"description": _safe_text(chosen.get("descricao") or chosen.get("nome") or chosen.get("endereco") or direct["description"]) or "Destino", "position": position}


def _route_description(record: dict[str, Any]) -> str | None:
    described = _safe_text(record.get("rota_descricao") or record.get("descricaoRota"))
    if described:
        return described
    origin_data = record.get("origem") or record.get("descricao_origem")
    destination_data = record.get("destino") or record.get("descricao_destino")
    origin = _safe_text(origin_data.get("vloc_descricao") or origin_data.get("cidade")) if isinstance(origin_data, dict) else _safe_text(origin_data)
    destination = _safe_text(destination_data.get("vloc_descricao") or destination_data.get("cidade")) if isinstance(destination_data, dict) else _safe_text(destination_data)
    return f"{origin} → {destination}" if origin and destination else destination or origin


def _driver_name(position: dict[str, Any], metadata: dict[str, Any]) -> str | None:
    direct = _safe_text(position.get("motorista") or metadata.get("motorista"))
    if direct:
        return direct
    for driver in metadata.get("motoristas") or []:
        if isinstance(driver, dict):
            name = _safe_text(driver.get("nome_moto") or driver.get("nome"))
            if name:
                return name
    return None


def _trip_driver_candidates(position: dict[str, Any], metadata: dict[str, Any]) -> list[str]:
    result: list[str] = []
    direct = _safe_text(position.get("motorista") or position.get("condutor"))
    if direct:
        result.append(direct)
    drivers = metadata.get("motoristas") or []
    if isinstance(drivers, dict):
        drivers = [drivers]
    for driver in drivers:
        if isinstance(driver, dict):
            name = _safe_text(driver.get("nome_moto") or driver.get("nome") or driver.get("motorista"))
            if name:
                result.append(name)
    return result


def _vehicle_driver_candidates(value: Any) -> list[str]:
    vehicle = value.get("veiculo") if isinstance(value, dict) else None
    if isinstance(vehicle, list):
        vehicle = vehicle[0] if vehicle else None
    if not isinstance(vehicle, dict):
        return []
    drivers = vehicle.get("motoristas") or vehicle.get("condutores") or []
    if isinstance(drivers, dict):
        drivers = [drivers]
    result: list[str] = []
    for driver in drivers:
        if isinstance(driver, dict):
            name = _safe_text(driver.get("nome") or driver.get("nome_moto") or driver.get("motorista"))
            if name:
                result.append(name)
    return result


def _speed(position: dict[str, Any]) -> float | None:
    normalized={str(key).lower().replace("_",""):value for key,value in position.items()}
    value=next((normalized[key] for key in ("velocidade","speed","velocidadekmh","velocidadeatual","velocidadeposicao") if normalized.get(key) is not None),None)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _dedup_key(item: dict[str, Any]) -> str:
    if item.get("trip_id"): return f"trip:{item['trip_id']}"
    return "fallback:" + "|".join(str(item.get(key) or "") for key in ("plate", "driver", "communicated_at"))


def _deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen: dict[str, dict[str, Any]] = {}
    for item in items:
        key = item["dedup_key"]
        existing = chosen.get(key)
        if not existing or str(item.get("communicated_at") or "") > str(existing.get("communicated_at") or ""):
            chosen[key] = item
    return list(chosen.values())


def _is_stale(value: datetime | None, threshold_minutes: int = 15) -> bool:
    return value is None or datetime.now(timezone.utc) - value > timedelta(minutes=threshold_minutes)


def _classify(delta_minutes: float | None, remaining_minutes: float) -> str:
    if delta_minutes is None: return "ATENCAO"
    if delta_minutes > 0: return "CRITICA"
    if -delta_minutes <= max(60, remaining_minutes * 0.1): return "ATENCAO"
    return "NORMAL"


def _route_points(route: dict[str, Any]) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    for leg in route.get("legs") or []:
        for point in leg.get("points") or []:
            try: points.append({"latitude": float(point["latitude"]), "longitude": float(point["longitude"])})
            except (KeyError, TypeError, ValueError): continue
    return points


def _sample_points(points: list[dict[str, float]], count: int) -> list[dict[str, float]]:
    if len(points) < 3: return []
    return [points[round(index * (len(points) - 1) / (count + 1))] for index in range(1, count + 1)]


def _weather_risk(item: dict[str, Any], passage: datetime, point: dict[str, float]) -> dict[str, Any] | None:
    weather = (item.get("weather") or [{}])[0]
    main = item.get("main") or {}
    rain = item.get("rain") or {}
    wind = item.get("wind") or {}
    visibility = item.get("visibility")
    code = int(weather.get("id") or 0)
    rain_mm = float(rain.get("3h") or 0)
    risk_type = None
    severity = "medium"
    if 200 <= code < 300: risk_type, severity = "thunderstorm", "high"
    elif rain_mm >= 10 or 500 <= code < 600: risk_type, severity = "heavy_rain" if rain_mm >= 10 else "rain", "high" if rain_mm >= 10 else "medium"
    elif visibility is not None and float(visibility) < 1000: risk_type, severity = "low_visibility", "high"
    elif 700 <= code < 800: risk_type = "low_visibility"
    elif float(wind.get("speed") or 0) >= 15: risk_type, severity = "strong_wind", "high"
    if not risk_type: return None
    return {
        "type": risk_type,
        "severity": severity,
        "description": _safe_text(weather.get("description")) or risk_type,
        "passage_at": passage.isoformat(),
        "position": point,
        "temperature_c": main.get("temp"),
        "rain_3h_mm": rain_mm,
        "visibility_m": visibility,
        "source": "OpenWeather forecast",
    }


def _provider_error_name(exc: Exception) -> str:
    if isinstance(exc, AuthError): return "authentication_error"
    if isinstance(exc, RateLimitError): return "rate_limit_error"
    return "unavailable"


fleet_tracking_service = FleetTrackingService()
