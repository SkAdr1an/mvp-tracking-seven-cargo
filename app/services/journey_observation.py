from __future__ import annotations

import json
import math
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

from app.storage.operations import OperationsRepository, utc_now
from app.storage.sqlite_runtime import connect_existing_database


REQUIRED_TABLES = frozenset({
    "communication_gaps",
    "journey_observation_trackers",
    "operational_exceptions",
    "operational_stops",
    "stop_evidence_events",
})
REQUIRED_INDEXES = frozenset({
    "idx_operational_exceptions_status",
    "idx_operational_stops_trip_time",
})


class JourneyObservationService:
    def __init__(self, repository: OperationsRepository) -> None:
        self.repository = repository
        try:
            with closing(connect_existing_database(repository.database_path)) as connection:
                objects = {
                    (str(row[0]), str(row[1]))
                    for row in connection.execute(
                        "SELECT type, name FROM sqlite_master "
                        "WHERE type IN ('table', 'index')"
                    )
                }
            tables = {name for kind, name in objects if kind == "table"}
            indexes = {name for kind, name in objects if kind == "index"}
            if REQUIRED_TABLES - tables or REQUIRED_INDEXES - indexes:
                raise RuntimeError("Journey observation schema is unavailable")
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError("Journey observation storage is unavailable") from exc

    def observe(self, trip_key: str) -> None:
        with self.repository.connect() as connection:
            points = connection.execute(
                "SELECT latitude,longitude,recorded_at FROM operational_positions "
                "WHERE trip_key=? AND accepted=1 ORDER BY recorded_at DESC LIMIT 2",
                (trip_key,),
            ).fetchall()
            if not points:
                return
            current = points[0]
            tracker = connection.execute(
                "SELECT * FROM journey_observation_trackers WHERE trip_key=?", (trip_key,)
            ).fetchone()
            if tracker is None:
                self._reset_tracker(connection, trip_key, current)
                return
            previous_at = datetime.fromisoformat(tracker["last_position_at"])
            current_at = datetime.fromisoformat(current["recorded_at"])
            gap_minutes = (current_at - previous_at).total_seconds() / 60
            distance_km = _haversine(
                (tracker["candidate_latitude"], tracker["candidate_longitude"]),
                (current["latitude"], current["longitude"]),
            )
            if gap_minutes > 20:
                previous = points[1] if len(points) > 1 else current
                displacement = _haversine(
                    (previous["latitude"], previous["longitude"]),
                    (current["latitude"], current["longitude"]),
                )
                connection.execute(
                    """INSERT OR IGNORE INTO communication_gaps(
                       trip_key,started_at,ended_at,duration_minutes,
                       start_latitude,start_longitude,end_latitude,end_longitude,
                       displacement_km,interpretation,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        trip_key, tracker["last_position_at"], current["recorded_at"],
                        gap_minutes, previous["latitude"], previous["longitude"],
                        current["latitude"], current["longitude"], displacement,
                        "MOVEMENT_UNOBSERVED" if displacement >= 0.25 else "POSSIBLE_DWELL_UNCONFIRMED",
                        utc_now(),
                    ),
                )
                self._finish_stop(connection, tracker, tracker["last_position_at"])
                self._reset_tracker(connection, trip_key, current)
                return
            if distance_km <= 0.25:
                samples = int(tracker["sample_count"]) + 1
                duration = (current_at - datetime.fromisoformat(tracker["candidate_started_at"])).total_seconds() / 60
                stop_id = tracker["stop_id"]
                if duration >= 1:
                    classification = _classification(duration)
                    if stop_id is None:
                        cursor = connection.execute(
                            """INSERT INTO operational_stops(
                               trip_key,started_at,ended_at,duration_minutes,latitude,longitude,
                               sample_count,classification,status,evidence_source,confidence,
                               created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                trip_key, tracker["candidate_started_at"], current["recorded_at"],
                                duration, tracker["candidate_latitude"], tracker["candidate_longitude"],
                                samples, classification, "OPEN", "GPS_DWELL", "MODERATE",
                                utc_now(), utc_now(),
                            ),
                        )
                        stop_id = cursor.lastrowid
                    else:
                        connection.execute(
                            "UPDATE operational_stops SET ended_at=?,duration_minutes=?,sample_count=?,"
                            "classification=?,updated_at=? WHERE id=?",
                            (current["recorded_at"], duration, samples, classification, utc_now(), stop_id),
                        )
                connection.execute(
                    "UPDATE journey_observation_trackers SET last_position_at=?,sample_count=?,"
                    "stop_id=?,updated_at=? WHERE trip_key=?",
                    (current["recorded_at"], samples, stop_id, utc_now(), trip_key),
                )
                return
            self._finish_stop(connection, tracker, tracker["last_position_at"])
            self._reset_tracker(connection, trip_key, current)

    def reconcile(self, stale_minutes: int = 60) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        active: dict[tuple[str, str], tuple[str, str, dict[str, Any]]] = {}
        for trip in self.repository.trips():
            key = trip["trip_key"]
            if not trip.get("route_id"):
                active[(key, "ROUTE_NOT_ASSIGNED")] = (
                    "HIGH", "Viagem sem rota operacional associada", {},
                )
            last = trip.get("last_position_at")
            if last and trip.get("state") not in {"FINALIZADA_NO_SISTEMA", "RETORNO_CONCLUIDO"}:
                age = (now - datetime.fromisoformat(last).astimezone(timezone.utc)).total_seconds() / 60
                if age > stale_minutes:
                    active[(key, "STALE_POSITION")] = (
                        "HIGH", "Viagem ativa sem posição recente", {"age_minutes": round(age, 1)},
                    )
            if trip.get("state") == "PROGRAMADA":
                history = self.repository.position_history(key, 2000)
                if len(history) >= 3:
                    distance = _haversine(
                        (history[0]["latitude"], history[0]["longitude"]),
                        (history[-1]["latitude"], history[-1]["longitude"]),
                    )
                    if distance >= 10:
                        active[(key, "STATE_POSITION_MISMATCH")] = (
                            "CRITICAL", "Viagem programada com deslocamento significativo",
                            {"displacement_km": round(distance, 1)},
                        )
        with self.repository.connect() as connection:
            for (trip_key, code), (severity, summary, evidence) in active.items():
                row = connection.execute(
                    "SELECT id FROM operational_exceptions WHERE trip_key=? AND code=? "
                    "AND status='OPEN' ORDER BY id DESC LIMIT 1", (trip_key, code),
                ).fetchone()
                if row:
                    connection.execute(
                        "UPDATE operational_exceptions SET severity=?,summary=?,evidence_json=?,last_seen_at=? WHERE id=?",
                        (severity, summary, json.dumps(evidence), utc_now(), row["id"]),
                    )
                else:
                    connection.execute(
                        """INSERT INTO operational_exceptions(
                           trip_key,code,severity,status,summary,evidence_json,
                           first_detected_at,last_seen_at) VALUES(?,?,?,'OPEN',?,?,?,?)""",
                        (trip_key, code, severity, summary, json.dumps(evidence), utc_now(), utc_now()),
                    )
            rows = connection.execute("SELECT id,trip_key,code FROM operational_exceptions WHERE status='OPEN'").fetchall()
            for row in rows:
                if (row["trip_key"], row["code"]) not in active:
                    connection.execute(
                        "UPDATE operational_exceptions SET status='AUTO_RESOLVED',resolved_at=?,"
                        "resolution='Condição não está mais presente' WHERE id=?", (utc_now(), row["id"]),
                    )
        return self.exceptions()

    def stops(self, trip_key: str) -> list[dict[str, Any]]:
        with self.repository.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM operational_stops WHERE trip_key=? ORDER BY started_at", (trip_key,)
            )]

    def gaps(self, trip_key: str) -> list[dict[str, Any]]:
        with self.repository.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM communication_gaps WHERE trip_key=? ORDER BY started_at", (trip_key,)
            )]

    def exceptions(self, status: str = "OPEN") -> list[dict[str, Any]]:
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM operational_exceptions WHERE status=? ORDER BY severity,last_seen_at",
                (status,),
            ).fetchall()
        values = []
        for row in rows:
            value = dict(row); value["evidence"] = json.loads(value.pop("evidence_json") or "{}")
            values.append(value)
        return values

    def justify_stop(self, stop_id: int, reason: str, justification: str, operator: str) -> dict[str, Any]:
        with self.repository.connect() as connection:
            row = connection.execute("SELECT * FROM operational_stops WHERE id=?", (stop_id,)).fetchone()
            if not row: raise KeyError(stop_id)
            now = utc_now()
            connection.execute(
                "UPDATE operational_stops SET reason_code=?,reason_text=?,confirmed_by=?,"
                "confirmed_at=?,updated_at=? WHERE id=?",
                (reason, justification, operator, now, now, stop_id),
            )
            connection.execute(
                "INSERT INTO stop_evidence_events(stop_id,action,operator,justification,occurred_at) "
                "VALUES(?,?,?,?,?)", (stop_id, "REASON_CONFIRMED", operator, justification, now),
            )
        return self.stop(stop_id)

    def stop(self, stop_id: int) -> dict[str, Any]:
        with self.repository.connect() as connection:
            row = connection.execute("SELECT * FROM operational_stops WHERE id=?", (stop_id,)).fetchone()
        if not row: raise KeyError(stop_id)
        return dict(row)

    @staticmethod
    def _reset_tracker(connection, trip_key, point) -> None:
        connection.execute(
            """INSERT INTO journey_observation_trackers(
               trip_key,candidate_started_at,candidate_latitude,candidate_longitude,
               last_position_at,sample_count,stop_id,updated_at) VALUES(?,?,?,?,?,1,NULL,?)
               ON CONFLICT(trip_key) DO UPDATE SET candidate_started_at=excluded.candidate_started_at,
               candidate_latitude=excluded.candidate_latitude,candidate_longitude=excluded.candidate_longitude,
               last_position_at=excluded.last_position_at,sample_count=1,stop_id=NULL,updated_at=excluded.updated_at""",
            (trip_key, point["recorded_at"], point["latitude"], point["longitude"], point["recorded_at"], utc_now()),
        )

    @staticmethod
    def _finish_stop(connection, tracker, ended_at: str) -> None:
        if tracker["stop_id"] is not None:
            connection.execute(
                "UPDATE operational_stops SET ended_at=?,status='CLOSED',updated_at=? WHERE id=?",
                (ended_at, utc_now(), tracker["stop_id"]),
            )


_instances: dict[str, JourneyObservationService] = {}


def get_journey_observation_service(repository: OperationsRepository) -> JourneyObservationService:
    key = repository.database_path
    if key not in _instances:
        _instances[key] = JourneyObservationService(repository)
    return _instances[key]


def _classification(minutes: float) -> str:
    return "BRIEF" if minutes < 10 else "ATTENTION" if minutes <= 30 else "URGENT"


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    radius = 6371.0088
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlon = lat2 - lat1, math.radians(b[1] - a[1])
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return radius * 2 * math.asin(math.sqrt(value))
