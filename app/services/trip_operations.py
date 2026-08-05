from __future__ import annotations

import math
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.public_trip import is_final_trip_state, revoke_links_for_finished_trip
from app.storage.operations import OperationsRepository


logger = logging.getLogger(__name__)


TRIP_STATES = {
    "PROGRAMADA", "NA_ORIGEM", "EM_CARREGAMENTO", "EM_VIAGEM",
    "NO_DESTINO", "FINALIZADA_NO_SISTEMA", "REABERTA_MANUALMENTE",
    "RETORNO_SEVEN_CONFIRMADO", "RETORNO_CONCLUIDO",
}

BETIM_JABOATAO_ROUTE = {
    "id": "betim-jaboatao",
    "name": "Betim/MG → Jaboatão dos Guararapes/PE",
    "origin_name": "SOC_MG_BETIM SHOPEE · Av. das Palmeiras, 347 - Pedreira, Betim/MG",
    "origin_latitude": -19.9821111,
    "origin_longitude": -44.2662371,
    "destination_name": "Destino operacional Jaboatão dos Guararapes/PE",
    "destination_latitude": -8.207594,
    "destination_longitude": -34.963157,
    "origin_radius_m": 500,
    "destination_radius_m": 1000,
    "origin_exit_radius_m": 650,
    "destination_exit_radius_m": 1150,
    "origin_dwell_minutes": 10,
    "destination_dwell_minutes": 10,
    "destination_finish_minutes": 30,
    "stop_speed_max_kmh": 5,
    "consecutive_readings": 2,
    "sla_minutes": None,
    "active": True,
    "match_terms": ["BETIM", "JABOATAO"],
}

SAO_BERNARDO_CONTAGEM_ROUTE = {
    "id": "sao-bernardo-contagem-manual",
    "name": "São Bernardo do Campo/SP → Contagem/MG",
    "origin_name": "CEVA_SHOPEE - SÃO BERNARDO DO CAMPO/SP",
    "origin_latitude": -23.7194577598,
    "origin_longitude": -46.6007399558,
    "destination_name": "CEVA_SHOPEE - CONTAGEM/MG",
    "destination_latitude": -19.8795139836,
    "destination_longitude": -44.0570640564,
    "origin_radius_m": 500,
    "destination_radius_m": 500,
    "origin_exit_radius_m": 650,
    "destination_exit_radius_m": 650,
    "origin_dwell_minutes": 10,
    "destination_dwell_minutes": 10,
    "destination_finish_minutes": 30,
    "stop_speed_max_kmh": 5,
    "consecutive_readings": 2,
    "sla_minutes": 31 * 60,
    "operational_duration_minutes": 31 * 60,
    "is_express": False,
    "active": True,
    # Cadastro manual e direcional: o sentido inverso não é inferido.
    "match_terms": [
        "CEVA_SHOPEE - SÃO BERNARDO DO CAMPO/SP",
        "CEVA_SHOPEE - CONTAGEM/MG",
    ],
}


@dataclass(frozen=True)
class PositionUpdate:
    plate: str
    latitude: float
    longitude: float
    recorded_at: datetime
    source: str
    trip_id: str | None = None
    speed_kmh: float | None = None
    route_id: str | None = None
    route_description: str | None = None


def _utc(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _norm(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return re.sub(r"\s+", " ", "".join(char for char in normalized if not unicodedata.combining(char))).strip().upper()


def _route_endpoints(description: str | None) -> tuple[str, str] | None:
    parts = re.split(r"\s*(?:→|A†’|->|>| PARA | X )\s*", _norm(description), maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 and all(parts) else None


def _endpoint_has(endpoint: str, *terms: str) -> bool:
    return all(_norm(term) in endpoint for term in terms)


def distance_meters(latitude: float, longitude: float, target_latitude: float, target_longitude: float) -> float:
    radius = 6_371_000.0
    lat1, lat2 = math.radians(latitude), math.radians(target_latitude)
    dlat = lat2 - lat1
    dlon = math.radians(target_longitude - longitude)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class TripOperationsService:
    def __init__(self, repository: OperationsRepository) -> None:
        self.repository = repository
        from app.services.return_tracking import ReturnTrackingService
        self.return_tracking = ReturnTrackingService(repository)
        if self.repository.route(BETIM_JABOATAO_ROUTE["id"]) is None:
            self.repository.upsert_route(BETIM_JABOATAO_ROUTE)
        if self.repository.route(SAO_BERNARDO_CONTAGEM_ROUTE["id"]) is None:
            self.repository.upsert_route(SAO_BERNARDO_CONTAGEM_ROUTE)

    def recognize_route(self, description: str | None, explicit_route_id: str | None = None) -> dict[str, Any]:
        if explicit_route_id:
            route = self.repository.route(explicit_route_id)
            active = bool(route and route["active"])
            return {"status": "RECOGNIZED" if active else "UNIDENTIFIED",
                    "route": route if active else None, "method": "explicit_route_id",
                    "reason": "explicit_active_route" if active else "explicit_route_missing_or_inactive"}
        routes = {route["id"]: route for route in self.repository.routes(active_only=True)}
        endpoints = _route_endpoints(description)
        if not endpoints:
            normalized_description = _norm(description)
            ordered_matches = []
            for route in routes.values():
                terms = [_norm(term) for term in route.get("match_terms", []) if term]
                if len(terms) != 2:
                    continue
                origin_index = normalized_description.find(terms[0])
                destination_index = normalized_description.find(terms[1], origin_index + len(terms[0]))
                if origin_index >= 0 and destination_index > origin_index:
                    ordered_matches.append(route)
            if len(ordered_matches) == 1:
                return {"status": "RECOGNIZED", "route": ordered_matches[0],
                        "method": "configured_ordered_description_terms",
                        "reason": "unique_ordered_match_without_separator"}
            if len(ordered_matches) > 1:
                return {"status": "AMBIGUOUS", "route": None,
                        "method": "configured_ordered_description_terms",
                        "reason": "multiple_ordered_matches_without_separator"}
            return {"status": "UNIDENTIFIED", "route": None, "method": "provider_description",
                    "reason": "direction_not_parseable"}
        origin, destination = endpoints
        if _endpoint_has(origin, "BETIM") and _endpoint_has(destination, "JABOATAO"):
            return {"status": "RECOGNIZED", "route": routes.get(BETIM_JABOATAO_ROUTE["id"]),
                    "method": "provider_endpoints", "reason": "betim_to_jaboatao"}
        if _endpoint_has(origin, "JABOATAO") and _endpoint_has(destination, "BETIM"):
            route = routes.get("jaboatao-betim")
            return {"status": "RECOGNIZED" if route else "GEOMETRY_PENDING", "route": route,
                    "method": "provider_endpoints",
                    "reason": "jaboatao_to_betim" if route else "reverse_direction_not_registered"}
        if (_endpoint_has(origin, "SAO BERNARDO") and _endpoint_has(destination, "CONTAGEM")
                and ("CEVA" in origin or "SHOPEE" in origin)):
            return {"status": "RECOGNIZED", "route": routes.get(SAO_BERNARDO_CONTAGEM_ROUTE["id"]),
                    "method": "provider_endpoints", "reason": "sao_bernardo_to_contagem"}
        if _endpoint_has(origin, "CONTAGEM") and _endpoint_has(destination, "SAO BERNARDO"):
            return {"status": "GEOMETRY_PENDING", "route": None, "method": "provider_endpoints",
                    "reason": "reverse_direction_inactive"}
        generic_matches = []
        for route in routes.values():
            terms = [_norm(term) for term in route.get("match_terms", []) if term]
            if len(terms) == 2 and terms[0] in origin and terms[1] in destination:
                generic_matches.append(route)
        if len(generic_matches) == 1:
            return {"status": "RECOGNIZED", "route": generic_matches[0],
                    "method": "configured_directional_terms", "reason": "unique_ordered_match"}
        if len(generic_matches) > 1:
            return {"status": "AMBIGUOUS", "route": None,
                    "method": "configured_directional_terms", "reason": "multiple_ordered_matches"}
        return {"status": "UNIDENTIFIED", "route": None, "method": "provider_endpoints",
                "reason": "no_registered_directional_route"}

    def match_route(self, description: str | None, explicit_route_id: str | None = None) -> dict[str, Any] | None:
        return self.recognize_route(description, explicit_route_id)["route"]

    @staticmethod
    def trip_key(plate: str, trip_id: str | None) -> str:
        return f"trafegus:{trip_id}" if trip_id else f"plate:{_norm(plate)}"

    def reconcile_driver(
        self, plate: str, trip_id: str | None, trip_candidates: list[str],
        vehicle_candidates: list[str], source: str = "trafegus",
    ) -> dict[str, Any]:
        key = self.trip_key(plate, trip_id)
        trip = self.repository.ensure_trip(key, plate, trip_id, None)
        vehicle = sorted({_norm_name(name) for name in vehicle_candidates if _norm_name(name)})
        registered = sorted({_norm_name(name) for name in trip_candidates if _norm_name(name)})
        previous = trip.get("current_driver")
        divergence = len(vehicle) > 1 or (not vehicle and len(registered) > 1)

        if len(vehicle) == 1:
            selected = vehicle[0]
            reliable_source = f"{source}:vehicle_association"
        elif previous:
            selected = previous
            reliable_source = trip.get("driver_source") or "history:last_reliable"
        elif len(registered) == 1:
            selected = registered[0]
            reliable_source = f"{source}:trip_registration"
        else:
            selected = None
            divergence = bool(vehicle or registered)
            reliable_source = None

        # Um cadastro atual único é confiável e vence a viagem antiga; a diferença
        # gera troca, não divergência. Só múltiplos vínculos sem vencedor confiável
        # permanecem ambíguos.

        now = datetime.now(timezone.utc).isoformat()
        historical_previous = previous or (
            registered[0] if len(registered) == 1 and selected and registered[0] != selected else None
        )
        if selected and previous != selected:
            self.repository.update_trip(
                key, previous_driver=historical_previous, current_driver=selected,
                driver_source=reliable_source, driver_divergence=int(divergence), driver_updated_at=now,
            )
            self.repository.add_event(
                key, "DRIVER_CHANGED" if historical_previous else "DRIVER_LINKED", now, source,
                "Troca de condutor identificada" if historical_previous else "Condutor confiável identificado",
                metadata={"previous_driver": historical_previous, "current_driver": selected, "plate": plate,
                          "information_origin": reliable_source},
                idempotency_key=f"driver:{key}:{_norm(historical_previous)}:{_norm(selected)}:{now}",
            )
        else:
            self.repository.update_trip(
                key, driver_divergence=int(divergence),
                **({"driver_source": reliable_source} if reliable_source else {}),
            )
        if divergence:
            self.repository.add_event(
                key, "DRIVER_DIVERGENCE", now, source, "Divergência de condutor",
                metadata={"plate": plate, "candidate_count": len(vehicle) + len(registered)},
                idempotency_key=f"driver-divergence:{key}:{now[:13]}",
            )
        current = self.repository.trip(key) or {}
        return {
            "current_driver": current.get("current_driver"),
            "previous_driver": current.get("previous_driver"),
            "driver_source": current.get("driver_source"),
            "driver_divergence": current.get("driver_divergence", False),
            "driver_changed": bool(historical_previous and selected and historical_previous != selected),
        }

    def process_position(self, update: PositionUpdate) -> dict[str, Any]:
        recorded = _utc(update.recorded_at)
        recorded_at = recorded.isoformat()
        key = self.trip_key(update.plate, update.trip_id)
        recognition = self.recognize_route(update.route_description, update.route_id)
        route = recognition["route"]
        trip = self.repository.ensure_trip(key, update.plate, update.trip_id, route["id"] if route else None)
        initial_state = trip.get("state")
        if not (-90 <= update.latitude <= 90 and -180 <= update.longitude <= 180):
            return {
                "accepted": False,
                "reason": "invalid_coordinate",
                "trip": self.repository.trip(key),
            }
        if not route and trip.get("route_id") and not update.route_description:
            route = self.repository.route(trip["route_id"])
        if not route:
            inserted, _ = self.repository.add_position(
                key, update.latitude, update.longitude, update.speed_kmh, recorded_at,
                update.source, None, None, accepted=False, rejection_reason="route_not_assigned",
            )
            return {"accepted": inserted, "reason": "route_not_assigned",
                    "trip": self.repository.trip(key), "route_recognition": recognition}

        origin_distance = distance_meters(
            update.latitude, update.longitude, route["origin_latitude"], route["origin_longitude"]
        )
        destination_distance = distance_meters(
            update.latitude, update.longitude, route["destination_latitude"], route["destination_longitude"]
        )
        last_at = _utc(trip["last_position_at"]) if trip.get("last_position_at") else None
        if last_at and recorded <= last_at:
            reason = "duplicate_or_out_of_order"
            inserted, _ = self.repository.add_position(
                key, update.latitude, update.longitude, update.speed_kmh, recorded_at, update.source,
                origin_distance, destination_distance, accepted=False, rejection_reason=reason,
            )
            return {"accepted": False, "duplicate": not inserted, "reason": reason, "trip": self.repository.trip(key)}

        inserted, fingerprint = self.repository.add_position(
            key, update.latitude, update.longitude, update.speed_kmh, recorded_at, update.source,
            origin_distance, destination_distance,
        )
        if not inserted:
            return {"accepted": False, "duplicate": True, "reason": "duplicate", "trip": self.repository.trip(key)}

        fields: dict[str, Any] = {
            "last_position_at": recorded_at, "last_latitude": update.latitude,
            "last_longitude": update.longitude, "last_speed_kmh": update.speed_kmh,
        }
        state = trip["state"]
        required = max(int(route["consecutive_readings"]), 1)
        inside_origin = origin_distance <= route["origin_radius_m"]
        outside_origin = origin_distance >= route["origin_exit_radius_m"]
        inside_destination = destination_distance <= route["destination_radius_m"]
        outside_destination = destination_distance >= route["destination_exit_radius_m"]
        stopped = update.speed_kmh is None or update.speed_kmh <= route["stop_speed_max_kmh"]

        if state in {"PROGRAMADA", "REABERTA_MANUALMENTE"}:
            if inside_origin:
                count = int(trip.get("origin_candidate_count") or 0) + 1
                candidate = trip.get("origin_candidate_at") or recorded_at
                fields.update(origin_candidate_count=count, origin_candidate_at=candidate)
                if count >= required:
                    state = self._transition(key, state, "NA_ORIGEM", "ORIGIN_ENTERED", candidate,
                                             update.source, "Chegou para carregamento", fingerprint)
                    fields.update(state=state, origin_entered_at=candidate)
            else:
                fields.update(origin_candidate_count=0, origin_candidate_at=None)

        if state == "NA_ORIGEM":
            entered = _utc(fields.get("origin_entered_at") or trip.get("origin_entered_at") or recorded_at)
            if inside_origin and (recorded - entered).total_seconds() >= route["origin_dwell_minutes"] * 60:
                state = self._transition(key, state, "EM_CARREGAMENTO", "ORIGIN_PRESENCE_CONFIRMED",
                                         recorded_at, update.source, "Presença na origem confirmada", fingerprint,
                                         {"entered_at": entered.isoformat()})
                fields.update(state=state, arrived_origin_at=entered.isoformat())
            elif outside_origin:
                fields.update(state="PROGRAMADA", origin_candidate_count=0, origin_candidate_at=None,
                              origin_entered_at=None)
                self.repository.add_event(
                    key, "ORIGIN_ENTRY_DISCARDED", recorded_at, update.source,
                    "Entrada momentânea na origem descartada", "NA_ORIGEM", "PROGRAMADA",
                    idempotency_key=f"discard-origin:{fingerprint}",
                )
                state = "PROGRAMADA"

        if state == "EM_CARREGAMENTO":
            if outside_origin:
                count = int(trip.get("origin_exit_count") or 0) + 1
                candidate = trip.get("origin_exit_candidate_at") or recorded_at
                fields.update(origin_exit_count=count, origin_exit_candidate_at=candidate)
                if count >= required:
                    state = self._transition(key, state, "EM_VIAGEM", "TRIP_STARTED", candidate,
                                             update.source, "Viagem iniciada", fingerprint)
                    fields.update(state=state, started_at=candidate)
            else:
                fields.update(origin_exit_count=0, origin_exit_candidate_at=None)

        if state == "EM_VIAGEM":
            if inside_destination:
                count = int(trip.get("destination_candidate_count") or 0) + 1
                candidate = trip.get("destination_candidate_at") or recorded_at
                fields.update(destination_candidate_count=count, destination_candidate_at=candidate)
                if count >= required:
                    state = self._transition(key, state, "NO_DESTINO", "DESTINATION_ENTERED", candidate,
                                             update.source, "Chegou ao destino", fingerprint)
                    fields.update(state=state, destination_entered_at=candidate)
            else:
                fields.update(destination_candidate_count=0, destination_candidate_at=None)

        if state == "NO_DESTINO":
            entered = _utc(fields.get("destination_entered_at") or trip.get("destination_entered_at") or recorded_at)
            arrived = fields.get("arrived_destination_at") or trip.get("arrived_destination_at")
            dwell_minutes = (recorded - entered).total_seconds() / 60
            if not arrived and inside_destination and stopped and dwell_minutes >= route["destination_dwell_minutes"]:
                fields["arrived_destination_at"] = entered.isoformat()
                arrived = entered.isoformat()
                self.repository.add_event(
                    key, "DESTINATION_PRESENCE_CONFIRMED", recorded_at, update.source,
                    "Permanência no destino confirmada", "NO_DESTINO", "NO_DESTINO",
                    metadata={"entered_at": entered.isoformat(), "dwell_minutes": round(dwell_minutes, 1)},
                    idempotency_key=f"destination-confirmed:{key}:{entered.isoformat()}",
                )
            if arrived and inside_destination and stopped and dwell_minutes >= route["destination_finish_minutes"]:
                state = self._transition(key, state, "FINALIZADA_NO_SISTEMA", "TRIP_AUTO_FINISHED",
                                         recorded_at, "system:geofence", "Finalizada automaticamente somente no sistema",
                                         fingerprint, {"trafegus_mutated": False})
                fields.update(state=state, finished_at=recorded_at, finish_type="automatic")
            elif not arrived and outside_destination:
                count = int(trip.get("destination_exit_count") or 0) + 1
                fields["destination_exit_count"] = count
                if count >= required:
                    fields.update(state="EM_VIAGEM", destination_candidate_count=0,
                                  destination_candidate_at=None, destination_entered_at=None,
                                  destination_exit_count=0)
                    self.repository.add_event(
                        key, "DESTINATION_PASSAGE_DISCARDED", recorded_at, update.source,
                        "Passagem rápida próxima ao destino descartada", "NO_DESTINO", "EM_VIAGEM",
                        idempotency_key=f"discard-destination:{fingerprint}",
                    )
                    state = "EM_VIAGEM"
            else:
                fields["destination_exit_count"] = 0

        result = self.repository.update_trip(key, **fields)
        from app.services.journey_observation import get_journey_observation_service
        get_journey_observation_service(self.repository).observe(key)
        if is_final_trip_state(result.get("state")):
            revoke_links_for_finished_trip(self.repository, key)
            if not is_final_trip_state(initial_state):
                self._generate_automatic_report(key)
        return_trip = None
        deviation = None
        if result["state"] == "FINALIZADA_NO_SISTEMA":
            return_trip = self.return_tracking.observe(
                result, route, update.latitude, update.longitude, recorded_at, update.source
            )
        else:
            from app.services.route_deviation import route_deviation_service
            deviation = route_deviation_service.process(
                key, update.plate, route["id"], update.latitude, update.longitude, recorded_at
            )
        return {"accepted": True, "origin_distance_m": round(origin_distance, 1),
                "destination_distance_m": round(destination_distance, 1), "trip": return_trip or result,
                "parent_trip": result if return_trip else None,
                "deviation": deviation}

    def manual_action(
        self, trip_key: str, action: str, justification: str, operator: str,
        corrections: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
        trip = self.repository.trip(trip_key)
        if not trip:
            raise KeyError(trip_key)
        if len(justification.strip()) < 5:
            raise ValueError("A justificativa deve ter pelo menos 5 caracteres")
        now = datetime.now(timezone.utc).isoformat()
        previous = trip["state"]
        fields: dict[str, Any] = {}
        if action == "finalize":
            if previous == "FINALIZADA_NO_SISTEMA":
                return trip
            fields = {"state": "FINALIZADA_NO_SISTEMA", "finished_at": now, "finish_type": "manual"}
        elif action == "reopen":
            fields = {"state": "REABERTA_MANUALMENTE", "finished_at": None, "finish_type": None}
        elif action == "undo_detection":
            if previous == "NO_DESTINO":
                fields = {"state": "EM_VIAGEM", "destination_entered_at": None,
                          "arrived_destination_at": None, "destination_candidate_at": None,
                          "destination_candidate_count": 0, "destination_exit_count": 0}
            else:
                fields = {"state": "PROGRAMADA", "origin_entered_at": None,
                          "arrived_origin_at": None, "origin_candidate_at": None,
                          "origin_candidate_count": 0, "origin_exit_candidate_at": None,
                          "origin_exit_count": 0}
        elif action == "correct_times":
            allowed = {"arrived_origin_at", "started_at", "arrived_destination_at", "finished_at"}
            fields = {key: (_utc(value).isoformat() if value else None)
                      for key, value in (corrections or {}).items() if key in allowed}
            if not fields:
                raise ValueError("Informe ao menos um horário para correção")
        else:
            raise ValueError("Ação manual inválida")
        updated = self.repository.update_trip(trip_key, **fields)
        if is_final_trip_state(updated.get("state")):
            revoke_links_for_finished_trip(self.repository, trip_key)
        self.repository.add_event(
            trip_key, f"MANUAL_{action.upper()}", now, "operator", "Ação manual do operador",
            previous, updated["state"], metadata={"changes": fields, "trafegus_mutated": False},
            justification=justification.strip(), operator=operator.strip() or "operator",
            idempotency_key=f"manual:{trip_key}:{action}:{now}",
        )
        if is_final_trip_state(updated.get("state")) and not is_final_trip_state(previous):
            self._generate_automatic_report(trip_key)
        return self.repository.trip(trip_key) or updated

    def _generate_automatic_report(self, trip_key: str) -> None:
        """Persist the final evidence package without jeopardizing trip processing."""
        try:
            from app.services.trip_report import TripReportService

            TripReportService(
                self.repository, get_settings().automatic_reports_directory
            ).generate(trip_key)
        except Exception:
            logger.exception("Automatic report generation failed for trip %s", trip_key)

    def detail(self, trip_key: str) -> dict[str, Any] | None:
        trip = self.repository.trip(trip_key)
        if not trip:
            return None
        trip["route"] = self.repository.route(trip["route_id"]) if trip.get("route_id") else None
        trip["events"] = self.repository.events(trip_key)
        trip["geofences"] = self._geofence_status(trip)
        trip["diagnostic"] = self.repository.diagnostic(trip_key)
        trip["plan"] = self.repository.plan(trip_key)
        trip["eta_history"] = self.repository.eta_history(trip_key, 50)
        from app.services.journey_observation import get_journey_observation_service
        observation = get_journey_observation_service(self.repository)
        trip["stops"] = observation.stops(trip_key)
        trip["communication_gaps"] = observation.gaps(trip_key)
        candidate = self.repository.return_candidate(trip_key)
        if not candidate:
            with self.repository.connect() as connection:
                row = connection.execute(
                    "SELECT parent_trip_key FROM return_candidates WHERE return_trip_key=?", (trip_key,)
                ).fetchone()
            candidate = self.repository.return_candidate(row["parent_trip_key"]) if row else None
        trip["return_candidate"] = candidate
        if candidate and candidate.get("return_trip_key") and candidate["return_trip_key"] != trip_key:
            trip["return_trip"] = self.repository.trip(candidate["return_trip_key"])
        return trip

    def _transition(
        self, trip_key: str, previous: str, new: str, event_type: str, occurred_at: str,
        source: str, description: str, fingerprint: str, metadata: dict[str, Any] | None = None,
    ) -> str:
        self.repository.add_event(
            trip_key, event_type, occurred_at, source, description, previous, new,
            metadata=metadata, idempotency_key=f"transition:{event_type}:{fingerprint}",
        )
        return new

    def _geofence_status(self, trip: dict[str, Any]) -> dict[str, Any]:
        route = self.repository.route(trip["route_id"]) if trip.get("route_id") else None
        if not route or trip.get("last_latitude") is None:
            return {"origin": "unknown", "destination": "unknown", "time_inside_minutes": None}
        origin_distance = distance_meters(trip["last_latitude"], trip["last_longitude"],
                                          route["origin_latitude"], route["origin_longitude"])
        destination_distance = distance_meters(trip["last_latitude"], trip["last_longitude"],
                                               route["destination_latitude"], route["destination_longitude"])
        entered_at = trip.get("destination_entered_at") if destination_distance <= route["destination_radius_m"] else trip.get("origin_entered_at")
        minutes = None
        if entered_at and trip.get("last_position_at"):
            minutes = max((_utc(trip["last_position_at"]) - _utc(entered_at)).total_seconds() / 60, 0)
        return {
            "origin": "inside" if origin_distance <= route["origin_radius_m"] else "outside",
            "destination": "inside" if destination_distance <= route["destination_radius_m"] else "outside",
            "origin_distance_m": round(origin_distance, 1),
            "destination_distance_m": round(destination_distance, 1),
            "time_inside_minutes": round(minutes, 1) if minutes is not None else None,
        }


def _norm_name(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", " ", str(value)).strip() or None


def _default_service() -> TripOperationsService:
    path = Path(get_settings().operations_database_path)
    return TripOperationsService(OperationsRepository(path))


trip_operations_service = _default_service()
