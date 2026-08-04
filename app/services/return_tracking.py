from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any

from app.core.config import get_settings
from app.services.public_trip import is_final_trip_state, revoke_links_for_finished_trip
from app.storage.operations import OperationsRepository, utc_now


RETURN_ROUTE_ID = "jaboatao-betim-return"


class ReturnTrackingService:
    """Detecta deslocamentos de retorno usando somente posições já coletadas."""

    def __init__(self, repository: OperationsRepository) -> None:
        self.repository = repository

    def observe(
        self, parent: dict[str, Any], route: dict[str, Any], latitude: float,
        longitude: float, recorded_at: str, source: str,
    ) -> dict[str, Any] | None:
        candidate = self.repository.return_candidate(parent["trip_key"])
        if candidate and candidate["state"] == "RETORNO_SEVEN_CONFIRMADO":
            return self._record_confirmed(candidate, parent, latitude, longitude, recorded_at, source)
        if candidate:
            return None
        if parent.get("state") != "FINALIZADA_NO_SISTEMA" or not parent.get("finished_at"):
            return None
        arrival_at = parent.get("arrived_destination_at") or parent.get("destination_entered_at")
        if not arrival_at:
            return None
        geometry = self._geometry(route["id"])
        if not geometry:
            return None
        points = [(float(p["latitude"]), float(p["longitude"])) for p in geometry["geometry"]]
        progress, lateral_km = route_projection((latitude, longitude), points)
        total_progress = route_projection(points[-1], points)[0]
        destination_distance_m = _distance_m(
            latitude, longitude, route["destination_latitude"], route["destination_longitude"]
        )
        tracker = self.repository.return_tracker(parent["trip_key"]) or {}
        outside = destination_distance_m >= float(route["destination_exit_radius_m"])
        outside_count = int(tracker.get("outside_count") or 0) + 1 if outside else 0
        departure_at = tracker.get("departure_at")
        departure_progress = tracker.get("departure_progress_km")
        if outside_count >= max(int(route["consecutive_readings"]), 2) and not departure_at:
            departure_at, departure_progress = recorded_at, total_progress
        last_progress = tracker.get("last_progress_km")
        moving_toward_betim = (
            departure_at is not None and last_progress is not None
            and progress <= float(last_progress) - 0.2
        )
        direction_count = int(tracker.get("direction_count") or 0) + 1 if moving_toward_betim else (
            int(tracker.get("direction_count") or 0) if departure_at and last_progress is None else 0
        )
        self.repository.save_return_tracker(
            parent["trip_key"], outside_count=outside_count, direction_count=direction_count,
            departure_at=departure_at, departure_progress_km=departure_progress,
            last_progress_km=progress,
        )
        if not departure_at:
            return None
        departure = datetime.fromisoformat(departure_at)
        arrival = datetime.fromisoformat(arrival_at)
        stay_hours = max((departure - arrival).total_seconds() / 3600, 0)
        settings = get_settings()
        advanced_km = max(float(departure_progress or total_progress) - progress, 0)
        compatible = lateral_km * 1000 <= settings.return_corridor_m
        if not (
            stay_hours >= settings.return_min_destination_stay_hours
            and direction_count >= settings.return_direction_readings
            and advanced_km >= settings.return_min_progress_km
            and compatible
        ):
            return None
        evidence = {
            "destination_stay_requirement_hours": settings.return_min_destination_stay_hours,
            "direction_readings": direction_count,
            "required_direction_readings": settings.return_direction_readings,
            "minimum_progress_km": settings.return_min_progress_km,
            "corridor_limit_m": settings.return_corridor_m,
            "source": source,
        }
        result = self.repository.create_return_candidate({
            "parent_trip_key": parent["trip_key"], "plate": parent["plate"],
            "driver_id": parent.get("current_driver"), "state": "AGUARDANDO_CONFIRMACAO",
            "arrival_at": arrival_at, "departure_at": departure_at,
            "destination_stay_hours": round(stay_hours, 1),
            "progress_toward_origin_km": round(advanced_km, 1),
            "corridor_distance_m": round(lateral_km * 1000, 1),
            "compatible_with_route": compatible, "evidence": evidence,
        })
        self.repository.add_event(
            parent["trip_key"], "POSSIBLE_RETURN_DETECTED", recorded_at, "system:return-detection",
            "Possível retorno identificado; aguardando confirmação humana",
            "FINALIZADA_NO_SISTEMA", "AGUARDANDO_CONFIRMACAO",
            metadata={"candidate_id": result["id"], "stay_hours": result["destination_stay_hours"],
                      "progress_km": result["progress_toward_origin_km"],
                      "compatible_with_route": compatible},
            idempotency_key=f"possible-return:{parent['trip_key']}",
        )
        return None

    def decide(
        self, candidate_id: int, decision: str, operator: str,
        justification: str | None = None,
    ) -> dict[str, Any]:
        candidate = self.repository.return_candidate_by_id(candidate_id)
        if not candidate:
            raise KeyError(candidate_id)
        if candidate.get("decision") in {"YES", "NO"}:
            return candidate
        parent = self.repository.trip(candidate["parent_trip_key"])
        if not parent:
            raise KeyError(candidate["parent_trip_key"])
        if decision == "LATER":
            updated = self.repository.decide_return_candidate(
                candidate_id, "AGUARDANDO_CONFIRMACAO", "LATER", operator, justification, None
            )
            event_type, description = "RETURN_DECISION_DEFERRED", "Confirmação do retorno adiada"
        elif decision == "NO":
            updated = self.repository.decide_return_candidate(
                candidate_id, "RETORNO_EXTERNO", "NO", operator, justification, None
            )
            event_type, description = "RETURN_MARKED_EXTERNAL", "Deslocamento classificado como retorno externo"
        elif decision == "YES":
            return_trip_key = f"return:{candidate['parent_trip_key']}:{candidate_id}"
            self._ensure_reverse_route(parent["route_id"])
            self.repository.ensure_trip(return_trip_key, parent["plate"], None, RETURN_ROUTE_ID)
            self.repository.update_trip(
                return_trip_key, state="RETORNO_SEVEN_CONFIRMADO",
                current_driver=parent.get("current_driver"), driver_source="return:human-confirmation",
                started_at=candidate["departure_at"],
            )
            updated = self.repository.decide_return_candidate(
                candidate_id, "RETORNO_SEVEN_CONFIRMADO", "YES", operator,
                justification, return_trip_key,
            )
            event_type, description = "RETURN_SEVEN_CONFIRMED", "Retorno Seven confirmado pelo operador"
            self.repository.add_event(
                return_trip_key, event_type, utc_now(), "operator", description,
                None, "RETORNO_SEVEN_CONFIRMADO",
                metadata={"parent_trip_key": candidate["parent_trip_key"], "candidate_id": candidate_id},
                justification=justification, operator=operator,
                idempotency_key=f"return-confirmed:{candidate_id}",
            )
        else:
            raise ValueError("Decisão de retorno inválida")
        self.repository.add_event(
            candidate["parent_trip_key"], event_type, utc_now(), "operator", description,
            "AGUARDANDO_CONFIRMACAO", updated["state"],
            metadata={"candidate_id": candidate_id, "return_trip_key": updated.get("return_trip_key")},
            justification=justification, operator=operator,
            idempotency_key=f"return-decision:{candidate_id}:{decision}",
        )
        return updated

    def _record_confirmed(
        self, candidate: dict[str, Any], parent: dict[str, Any], latitude: float,
        longitude: float, recorded_at: str, source: str,
    ) -> dict[str, Any] | None:
        key = candidate.get("return_trip_key")
        trip = self.repository.trip(key) if key else None
        route = self.repository.route(RETURN_ROUTE_ID)
        if not trip or not route:
            return None
        origin_distance = _distance_m(latitude, longitude, route["origin_latitude"], route["origin_longitude"])
        destination_distance = _distance_m(
            latitude, longitude, route["destination_latitude"], route["destination_longitude"]
        )
        inserted, _ = self.repository.add_position(
            key, latitude, longitude, None, recorded_at, source,
            origin_distance, destination_distance,
        )
        if not inserted:
            return trip
        fields: dict[str, Any] = {
            "last_position_at": recorded_at, "last_latitude": latitude, "last_longitude": longitude,
        }
        if destination_distance <= route["destination_radius_m"]:
            count = int(trip.get("destination_candidate_count") or 0) + 1
            fields["destination_candidate_count"] = count
            if count >= max(int(route["consecutive_readings"]), 2):
                fields.update(
                    state="RETORNO_CONCLUIDO", arrived_destination_at=recorded_at,
                    finished_at=recorded_at, finish_type="automatic",
                )
                self.repository.add_event(
                    key, "RETURN_COMPLETED", recorded_at, "system:geofence",
                    "Retorno concluído em Betim", "RETORNO_SEVEN_CONFIRMADO", "RETORNO_CONCLUIDO",
                    idempotency_key=f"return-completed:{key}",
                )
                self.repository.decide_return_candidate(
                    candidate["id"], "RETORNO_CONCLUIDO", "YES",
                    candidate.get("decided_by") or "operator", candidate.get("justification"), key,
                )
        else:
            fields["destination_candidate_count"] = 0
        updated = self.repository.update_trip(key, **fields)
        if is_final_trip_state(updated.get("state")):
            revoke_links_for_finished_trip(self.repository, key)
        from app.services.route_deviation import route_deviation_service
        route_deviation_service.process(key, parent["plate"], RETURN_ROUTE_ID, latitude, longitude, recorded_at)
        return updated

    def _ensure_reverse_route(self, forward_route_id: str) -> None:
        forward = self.repository.route(forward_route_id)
        if not forward:
            raise ValueError("Rota de ida não encontrada")
        reverse = {
            **forward, "id": RETURN_ROUTE_ID,
            "name": f"{forward['destination_name']} → {forward['origin_name']}",
            "origin_name": forward["destination_name"],
            "origin_latitude": forward["destination_latitude"],
            "origin_longitude": forward["destination_longitude"],
            "destination_name": forward["origin_name"],
            "destination_latitude": forward["origin_latitude"],
            "destination_longitude": forward["origin_longitude"],
            "match_terms": [], "active": True,
        }
        self.repository.upsert_route(reverse)
        geometry = self._geometry(forward_route_id)
        if geometry:
            points = list(reversed(geometry["geometry"]))
            mandatory = list(reversed(geometry["mandatory_points"]))
            with self.repository.connect() as connection:
                connection.execute(
                    "UPDATE route_geometry_versions SET active=0 WHERE route_id=?", (RETURN_ROUTE_ID,)
                )
                connection.execute(
                    """INSERT INTO route_geometry_versions
                       (route_id,version,source,geometry_json,mandatory_points_json,corridor_m,
                        segment_tolerances_json,active,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(route_id,version) DO UPDATE SET geometry_json=excluded.geometry_json,active=1""",
                    (RETURN_ROUTE_ID, f"{geometry['version']}-reversed", "Official geometry reversed",
                     json.dumps(points), json.dumps(mandatory), geometry["corridor_m"], "[]", 1, utc_now()),
                )

    def _geometry(self, route_id: str) -> dict[str, Any] | None:
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT * FROM route_geometry_versions WHERE route_id=? AND active=1 ORDER BY id DESC LIMIT 1",
                (route_id,),
            ).fetchone()
        if not row:
            return None
        value = dict(row)
        value["geometry"] = json.loads(value["geometry_json"])
        value["mandatory_points"] = json.loads(value["mandatory_points_json"])
        return value


def _distance_m(lat: float, lon: float, target_lat: float, target_lon: float) -> float:
    from app.services.trip_operations import distance_meters
    return distance_meters(lat, lon, target_lat, target_lon)


def route_projection(
    point: tuple[float, float], route: list[tuple[float, float]]
) -> tuple[float, float]:
    best = (0.0, float("inf"))
    cumulative = 0.0
    for a, b in zip(route, route[1:]):
        lat_scale = 111.0
        lon_scale = 111.0 * math.cos(math.radians((a[0] + b[0]) / 2))
        vx, vy = (b[1] - a[1]) * lon_scale, (b[0] - a[0]) * lat_scale
        wx, wy = (point[1] - a[1]) * lon_scale, (point[0] - a[0]) * lat_scale
        length2 = vx * vx + vy * vy
        factor = max(0, min(1, (wx * vx + wy * vy) / length2)) if length2 else 0
        lateral = math.hypot(wx - factor * vx, wy - factor * vy)
        segment = math.sqrt(length2)
        if lateral < best[1]:
            best = (cumulative + factor * segment, lateral)
        cumulative += segment
    return best
