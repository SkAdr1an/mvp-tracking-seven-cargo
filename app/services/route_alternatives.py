from __future__ import annotations

import json
from typing import Any

from app.services.traffic_monitoring import route_projection
from app.storage.operations import OperationsRepository, utc_now


PRIMARY_ID = "primary"
SWITCH_CONFIRMATIONS = 2
SWITCH_ADVANTAGE_KM = 0.15


class RouteAlternativeService:
    """Resolve an authorized route corridor without widening the whole route."""

    def __init__(self, repository: OperationsRepository) -> None:
        self.repository = repository

    def geometries(self, route_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        with self.repository.connect() as connection:
            primary = connection.execute(
                """SELECT version,geometry_json,corridor_m,segment_tolerances_json,source
                   FROM route_geometry_versions
                   WHERE route_id=? AND active=1 ORDER BY id DESC LIMIT 1""",
                (route_id,),
            ).fetchone()
            alternatives = connection.execute(
                """SELECT * FROM route_alternatives
                   WHERE route_id=? AND active=1 AND validation_status='validated'
                         AND geometry_json IS NOT NULL
                   ORDER BY id""",
                (route_id,),
            ).fetchall()
        if primary:
            result.append({
                "id": PRIMARY_ID,
                "route_id": route_id,
                "name": "Rota principal",
                "version": primary["version"],
                "geometry": json.loads(primary["geometry_json"]),
                "corridor_m": float(primary["corridor_m"]),
                "segment_tolerances": json.loads(primary["segment_tolerances_json"]),
                "source": primary["source"],
                "alternative": False,
            })
        for row in alternatives:
            evidence = json.loads(row["evidence_json"] or "{}")
            result.append({
                "id": row["id"],
                "route_id": route_id,
                "name": row["name"],
                "version": row["version"],
                "geometry": json.loads(row["geometry_json"]),
                "corridor_m": float(evidence.get("corridor_m") or 500),
                "segment_tolerances": evidence.get("segment_tolerances") or [],
                "source": row["source"],
                "alternative": True,
            })
        return result

    def resolve(
        self,
        trip_key: str,
        route_id: str,
        latitude: float,
        longitude: float,
        *,
        track_selection: bool = False,
    ) -> dict[str, Any] | None:
        candidates = self.geometries(route_id)
        if not candidates:
            return None
        evaluated: list[dict[str, Any]] = []
        for candidate in candidates:
            route = [
                (float(point["latitude"]), float(point["longitude"]))
                for point in candidate["geometry"]
            ]
            progress_km, distance_km = route_projection((latitude, longitude), route)
            evaluated.append({**candidate, "progress_km": progress_km, "distance_km": distance_km})
        best = min(evaluated, key=lambda item: item["distance_km"])
        if track_selection:
            self._track_selection(trip_key, route_id, best, evaluated)
        return best

    def _track_selection(
        self,
        trip_key: str,
        route_id: str,
        best: dict[str, Any],
        evaluated: list[dict[str, Any]],
    ) -> None:
        now = utc_now()
        primary = next((item for item in evaluated if item["id"] == PRIMARY_ID), None)
        with self.repository.connect() as connection:
            current = connection.execute(
                "SELECT * FROM route_alternative_selections WHERE trip_key=?", (trip_key,)
            ).fetchone()
            selected_id = current["alternative_id"] if current else None
            selected = next((item for item in evaluated if item["id"] == selected_id), primary)
            target_id = None if best["id"] == PRIMARY_ID else best["id"]
            selected_distance = selected["distance_km"] if selected else float("inf")
            target_valid = best["distance_km"] * 1000 <= best["corridor_m"]
            should_switch = (
                target_valid
                and target_id != selected_id
                and best["distance_km"] + SWITCH_ADVANTAGE_KM < selected_distance
            )
            primary_candidate = should_switch and target_id is None
            candidate_id = selected_id if primary_candidate else target_id
            same_candidate = bool(
                current
                and current["candidate_id"] == candidate_id
                and ((current["reason"] == "primary_candidate") == primary_candidate)
            )
            count = int(current["candidate_count"] or 0) + 1 if same_candidate else 1
            changed_at = current["changed_at"] if current else None
            reason = "stable_corridor"
            confidence = "HIGH" if best["distance_km"] * 1000 <= best["corridor_m"] else "LOW"
            if should_switch and count >= SWITCH_CONFIRMATIONS:
                selected_id = target_id
                changed_at = now
                candidate_id = None
                count = 0
                reason = "alternative_confirmed" if target_id else "primary_confirmed"
            elif should_switch:
                reason = "primary_candidate" if primary_candidate else "alternative_candidate"
                confidence = "MEDIUM"
            else:
                candidate_id = None
                count = 0
            connection.execute(
                """INSERT INTO route_alternative_selections(
                       trip_key,route_id,alternative_id,reason,confidence,candidate_id,
                       candidate_count,changed_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(trip_key) DO UPDATE SET
                     route_id=excluded.route_id,alternative_id=excluded.alternative_id,
                     reason=excluded.reason,confidence=excluded.confidence,
                     candidate_id=excluded.candidate_id,candidate_count=excluded.candidate_count,
                     changed_at=excluded.changed_at,updated_at=excluded.updated_at""",
                (trip_key, route_id, selected_id, reason, confidence, candidate_id, count, changed_at, now),
            )


def route_alternative_service(repository: OperationsRepository) -> RouteAlternativeService:
    return RouteAlternativeService(repository)
