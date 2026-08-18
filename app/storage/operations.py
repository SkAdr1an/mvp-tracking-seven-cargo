from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.storage.sqlite_runtime import connect_existing_database


SCHEMA = """
CREATE TABLE IF NOT EXISTS route_configs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    origin_site_id TEXT,
    destination_site_id TEXT,
    origin_name TEXT NOT NULL,
    origin_latitude REAL NOT NULL,
    origin_longitude REAL NOT NULL,
    destination_name TEXT NOT NULL,
    destination_latitude REAL NOT NULL,
    destination_longitude REAL NOT NULL,
    origin_radius_m REAL NOT NULL DEFAULT 500,
    destination_radius_m REAL NOT NULL DEFAULT 500,
    origin_exit_radius_m REAL NOT NULL DEFAULT 650,
    destination_exit_radius_m REAL NOT NULL DEFAULT 650,
    origin_dwell_minutes REAL NOT NULL DEFAULT 10,
    destination_dwell_minutes REAL NOT NULL DEFAULT 10,
    destination_finish_minutes REAL NOT NULL DEFAULT 30,
    stop_speed_max_kmh REAL NOT NULL DEFAULT 5,
    consecutive_readings INTEGER NOT NULL DEFAULT 2,
    sla_minutes INTEGER,
    operational_duration_minutes INTEGER,
    is_express INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    match_terms_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operational_trips (
    trip_key TEXT PRIMARY KEY,
    provider_trip_id TEXT,
    plate TEXT NOT NULL,
    route_id TEXT REFERENCES route_configs(id),
    state TEXT NOT NULL DEFAULT 'PROGRAMADA',
    current_driver TEXT,
    previous_driver TEXT,
    driver_source TEXT,
    driver_divergence INTEGER NOT NULL DEFAULT 0,
    driver_updated_at TEXT,
    last_position_at TEXT,
    last_latitude REAL,
    last_longitude REAL,
    last_speed_kmh REAL,
    origin_candidate_at TEXT,
    origin_candidate_count INTEGER NOT NULL DEFAULT 0,
    origin_exit_candidate_at TEXT,
    origin_exit_count INTEGER NOT NULL DEFAULT 0,
    destination_candidate_at TEXT,
    destination_candidate_count INTEGER NOT NULL DEFAULT 0,
    destination_exit_count INTEGER NOT NULL DEFAULT 0,
    origin_entered_at TEXT,
    arrived_origin_at TEXT,
    started_at TEXT,
    loaded_at TEXT,
    trailer_plate TEXT,
    destination_entered_at TEXT,
    arrived_destination_at TEXT,
    finished_at TEXT,
    finish_type TEXT,
    cancelled_at TEXT,
    cancelled_by_user_id TEXT REFERENCES users(id),
    cancelled_reason TEXT,
    archived_at TEXT,
    archived_by_user_id TEXT REFERENCES users(id),
    archive_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS route_site_links (
    route_id TEXT PRIMARY KEY REFERENCES route_configs(id),
    origin_site_id TEXT NOT NULL REFERENCES operational_sites(id),
    destination_site_id TEXT NOT NULL REFERENCES operational_sites(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS routing_provision_attempts (
    route_id TEXT PRIMARY KEY,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    http_status INTEGER,
    error_code TEXT,
    message TEXT,
    last_attempt_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS routing_api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_fingerprint TEXT NOT NULL,
    context TEXT NOT NULL,
    travel_mode TEXT NOT NULL,
    traffic_enabled INTEGER NOT NULL,
    http_status INTEGER,
    result TEXT NOT NULL,
    latency_ms REAL,
    occurred_at TEXT NOT NULL
    ,provider TEXT NOT NULL DEFAULT 'tomtom'
);
CREATE INDEX IF NOT EXISTS idx_routing_usage_time
ON routing_api_usage(occurred_at);

CREATE TABLE IF NOT EXISTS operational_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_key TEXT NOT NULL REFERENCES operational_trips(trip_key),
    fingerprint TEXT NOT NULL UNIQUE,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    speed_kmh REAL,
    recorded_at TEXT NOT NULL,
    source TEXT NOT NULL,
    origin_distance_m REAL,
    destination_distance_m REAL,
    accepted INTEGER NOT NULL DEFAULT 1,
    rejection_reason TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_positions_trip_time ON operational_positions(trip_key, recorded_at);

CREATE TABLE IF NOT EXISTS operational_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_key TEXT NOT NULL REFERENCES operational_trips(trip_key),
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    source TEXT NOT NULL,
    description TEXT NOT NULL,
    previous_state TEXT,
    new_state TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    justification TEXT,
    operator TEXT,
    idempotency_key TEXT UNIQUE,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_trip_time ON operational_events(trip_key, occurred_at);
CREATE TABLE IF NOT EXISTS route_geometry_versions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, route_id TEXT NOT NULL, version TEXT NOT NULL,
 source TEXT NOT NULL, geometry_json TEXT NOT NULL, mandatory_points_json TEXT NOT NULL,
 corridor_m REAL NOT NULL DEFAULT 300, segment_tolerances_json TEXT NOT NULL DEFAULT '[]',
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
 provider TEXT, distance_m REAL, duration_seconds REAL,
 UNIQUE(route_id,version));
CREATE TABLE IF NOT EXISTS route_deviation_trackers (
 trip_key TEXT PRIMARY KEY, outside_count INTEGER NOT NULL DEFAULT 0, inside_count INTEGER NOT NULL DEFAULT 0,
 first_outside_at TEXT, first_outside_latitude REAL, first_outside_longitude REAL,
 updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS route_deviations (
 id INTEGER PRIMARY KEY AUTOINCREMENT, trip_key TEXT NOT NULL, plate TEXT NOT NULL,
 route_id TEXT NOT NULL, geometry_version TEXT NOT NULL, status TEXT NOT NULL,
 level TEXT NOT NULL, started_at TEXT NOT NULL, exit_latitude REAL NOT NULL, exit_longitude REAL NOT NULL,
 last_outside_at TEXT NOT NULL, current_distance_m REAL NOT NULL, max_distance_m REAL NOT NULL,
 returned_at TEXT, acknowledged_at TEXT, acknowledged_by TEXT, reason TEXT, justification TEXT,
 manually_closed_at TEXT, related_incidents_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_deviations_trip_status ON route_deviations(trip_key,status);
CREATE TABLE IF NOT EXISTS route_deviation_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, deviation_id INTEGER NOT NULL, event_type TEXT NOT NULL,
 occurred_at TEXT NOT NULL, level TEXT, distance_m REAL, user_name TEXT, justification TEXT,
 metadata_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS route_progress_snapshots (
 trip_key TEXT PRIMARY KEY, route_id TEXT NOT NULL, geometry_version TEXT NOT NULL,
 total_distance_km REAL NOT NULL, advanced_distance_km REAL NOT NULL,
 remaining_distance_km REAL NOT NULL, progress_percent REAL NOT NULL,
 return_distance_km REAL, route_state TEXT NOT NULL, confidence TEXT NOT NULL,
 position_at TEXT, speed_kmh REAL, speed_state TEXT NOT NULL,
 last_reliable_json TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS return_detection_trackers (
 parent_trip_key TEXT PRIMARY KEY REFERENCES operational_trips(trip_key),
 outside_count INTEGER NOT NULL DEFAULT 0, direction_count INTEGER NOT NULL DEFAULT 0,
 departure_at TEXT, departure_progress_km REAL, last_progress_km REAL,
 updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS return_candidates (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 parent_trip_key TEXT NOT NULL UNIQUE REFERENCES operational_trips(trip_key),
 plate TEXT NOT NULL, driver_id TEXT, state TEXT NOT NULL,
 arrival_at TEXT NOT NULL, departure_at TEXT NOT NULL,
 destination_stay_hours REAL NOT NULL, progress_toward_origin_km REAL NOT NULL,
 corridor_distance_m REAL NOT NULL, compatible_with_route INTEGER NOT NULL,
 evidence_json TEXT NOT NULL DEFAULT '{}', decision TEXT, decision_at TEXT,
 decided_by TEXT, justification TEXT, return_trip_key TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_return_candidates_state ON return_candidates(state);
CREATE TABLE IF NOT EXISTS operational_diagnostics (
 trip_key TEXT PRIMARY KEY REFERENCES operational_trips(trip_key),
 eta_at TEXT, window_start_at TEXT, window_end_at TEXT, client_eta_at TEXT,
 commitment_delta_minutes REAL,
 trend TEXT NOT NULL, confidence TEXT NOT NULL, classification TEXT,
 remaining_minutes REAL, stopped_minutes REAL, method_version TEXT NOT NULL,
 factors_json TEXT NOT NULL DEFAULT '[]', confidence_reasons_json TEXT NOT NULL DEFAULT '[]',
 risks_json TEXT NOT NULL DEFAULT '[]', recommendations_json TEXT NOT NULL DEFAULT '[]',
 scenarios_json TEXT NOT NULL DEFAULT '{}', status_explanation TEXT NOT NULL,
    last_reliable_json TEXT, calculated_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trip_plans (
 trip_key TEXT PRIMARY KEY REFERENCES operational_trips(trip_key),
 scheduled_start_at TEXT, scheduled_arrival_at TEXT, customer_commitment_at TEXT,
 planned_loading_minutes REAL NOT NULL DEFAULT 0,
 planned_stops_minutes REAL NOT NULL DEFAULT 0,
 operational_buffer_minutes REAL NOT NULL DEFAULT 0,
 source TEXT NOT NULL, notes TEXT, updated_by TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS eta_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 trip_key TEXT NOT NULL REFERENCES operational_trips(trip_key),
 eta_at TEXT, client_eta_at TEXT, commitment_delta_minutes REAL,
 classification TEXT, trend TEXT, confidence TEXT,
 remaining_minutes REAL, source TEXT NOT NULL, method_version TEXT,
 evidence_json TEXT NOT NULL DEFAULT '{}', recorded_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_eta_history_trip_time
ON eta_history(trip_key, recorded_at);
CREATE TABLE IF NOT EXISTS driver_profiles (
 id TEXT PRIMARY KEY, cpf TEXT UNIQUE, name TEXT NOT NULL, phone TEXT,
 identity_status TEXT NOT NULL DEFAULT 'PENDING',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_driver_profiles_name ON driver_profiles(name);
CREATE TABLE IF NOT EXISTS driver_trip_history (
 trip_key TEXT PRIMARY KEY REFERENCES operational_trips(trip_key),
 driver_id TEXT NOT NULL REFERENCES driver_profiles(id), provider_trip_id TEXT,
 plate TEXT NOT NULL, trailer_plate TEXT, route_id TEXT, route_name TEXT,
 origin_name TEXT, destination_name TEXT, customer TEXT, evaluation_responsible TEXT,
 status TEXT NOT NULL, source_created_at TEXT, loaded_at TEXT, started_at TEXT,
 scheduled_arrival_at TEXT, eta_at TEXT, arrived_destination_at TEXT, finished_at TEXT,
 package_count INTEGER, responsible TEXT, driver_source TEXT,
 source TEXT NOT NULL, source_updated_at TEXT NOT NULL,
 automatic_punctuality TEXT NOT NULL DEFAULT 'UNAVAILABLE',
 automatic_delay_minutes REAL, considered_punctuality TEXT,
 closed INTEGER NOT NULL DEFAULT 0, consolidated_at TEXT,
 consolidation_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_driver_trip_history_driver_date ON driver_trip_history(driver_id, finished_at DESC);
CREATE INDEX IF NOT EXISTS idx_driver_trip_history_status ON driver_trip_history(status, finished_at);
CREATE INDEX IF NOT EXISTS idx_driver_trip_history_route ON driver_trip_history(route_id);
CREATE TABLE IF NOT EXISTS driver_evaluations (
 id INTEGER PRIMARY KEY AUTOINCREMENT, trip_key TEXT NOT NULL UNIQUE REFERENCES driver_trip_history(trip_key),
 driver_id TEXT NOT NULL REFERENCES driver_profiles(id), communication TEXT NOT NULL,
 procedures TEXT NOT NULL, tracking_collaboration TEXT NOT NULL, time_mark TEXT NOT NULL,
 professional_behavior TEXT NOT NULL, recommendation TEXT NOT NULL,
 internal_note TEXT, justification TEXT, responsible TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_driver_evaluations_driver ON driver_evaluations(driver_id, created_at DESC);
CREATE TABLE IF NOT EXISTS driver_evaluation_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT, evaluation_id INTEGER NOT NULL REFERENCES driver_evaluations(id),
 changed_by TEXT NOT NULL, changed_at TEXT NOT NULL, previous_json TEXT, current_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS punctuality_adjustments (
 id INTEGER PRIMARY KEY AUTOINCREMENT, trip_key TEXT NOT NULL REFERENCES driver_trip_history(trip_key),
 original_value TEXT NOT NULL, considered_value TEXT NOT NULL, category TEXT NOT NULL,
 reason TEXT NOT NULL, justification TEXT NOT NULL, evidence TEXT, responsible TEXT NOT NULL,
 created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_punctuality_adjustments_trip ON punctuality_adjustments(trip_key, created_at DESC);
CREATE TABLE IF NOT EXISTS driver_internal_notes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, driver_id TEXT NOT NULL REFERENCES driver_profiles(id),
 note TEXT NOT NULL, responsible TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_driver_notes_driver ON driver_internal_notes(driver_id, created_at DESC);
CREATE TABLE IF NOT EXISTS driver_identity_links (
 id INTEGER PRIMARY KEY AUTOINCREMENT, trip_key TEXT NOT NULL REFERENCES driver_trip_history(trip_key),
 previous_driver_id TEXT, new_driver_id TEXT NOT NULL REFERENCES driver_profiles(id),
 source TEXT NOT NULL, justification TEXT NOT NULL, responsible TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_driver_identity_links_trip ON driver_identity_links(trip_key, created_at DESC);
CREATE TABLE IF NOT EXISTS driver_trip_history_changes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, trip_key TEXT NOT NULL REFERENCES driver_trip_history(trip_key),
 field_name TEXT NOT NULL, previous_value TEXT, new_value TEXT, responsible TEXT NOT NULL,
 justification TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_driver_trip_changes_trip ON driver_trip_history_changes(trip_key, created_at DESC);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OperationsRepository:
    def __init__(self, database_path: str | Path) -> None:
        path = Path(database_path)
        if str(database_path) != ":memory:" and not path.is_absolute():
            raise ValueError("SQLite database path must be absolute")
        operational_path = (Path(__file__).resolve().parents[2] / "data" / "operations.db").resolve()
        if "pytest" in sys.modules and str(database_path) != ":memory:" and path.resolve() == operational_path:
            raise RuntimeError("Tests cannot use the operational database")
        self.database_path = ":memory:" if str(database_path) == ":memory:" else str(path.resolve())
        self._lock = threading.RLock()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = connect_existing_database(
            self.database_path, timeout=10, check_same_thread=False
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def upsert_route(self, route: dict[str, Any]) -> None:
        now = utc_now()
        values = {
            **route,
            "active": int(route.get("active", True)),
            "match_terms_json": json.dumps(route.get("match_terms", []), ensure_ascii=False),
            "created_at": route.get("created_at", now),
            "updated_at": now,
        }
        values.setdefault("operational_duration_minutes", None)
        values.setdefault("origin_site_id", None)
        values.setdefault("destination_site_id", None)
        values["is_express"] = int(route.get("is_express", False))
        columns = (
            "id", "name", "origin_site_id", "destination_site_id",
            "origin_name", "origin_latitude", "origin_longitude",
            "destination_name", "destination_latitude", "destination_longitude",
            "origin_radius_m", "destination_radius_m", "origin_exit_radius_m",
            "destination_exit_radius_m", "origin_dwell_minutes", "destination_dwell_minutes",
            "destination_finish_minutes", "stop_speed_max_kmh", "consecutive_readings",
            "sla_minutes", "operational_duration_minutes", "is_express",
            "active", "match_terms_json", "created_at", "updated_at",
        )
        placeholders = ", ".join(f":{column}" for column in columns)
        updates = ", ".join(f"{column}=excluded.{column}" for column in columns if column not in {"id", "created_at"})
        with self._lock, self.connect() as connection:
            connection.execute(
                f"INSERT INTO route_configs ({', '.join(columns)}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                values,
            )

    def routes(self, active_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM route_configs" + (" WHERE active = 1" if active_only else "") + " ORDER BY name"
        with self.connect() as connection:
            rows = connection.execute(query).fetchall()
        return [self._route(row) for row in rows]

    def route(self, route_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM route_configs WHERE id = ?", (route_id,)).fetchone()
        return self._route(row) if row else None

    def ensure_trip(self, trip_key: str, plate: str, provider_trip_id: str | None, route_id: str | None) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO operational_trips
                   (trip_key, provider_trip_id, plate, route_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(trip_key) DO UPDATE SET
                     provider_trip_id=CASE
                       WHEN state='CANCELADA' OR archived_at IS NOT NULL THEN provider_trip_id
                       ELSE COALESCE(excluded.provider_trip_id, provider_trip_id) END,
                     route_id=CASE
                       WHEN state='CANCELADA' OR archived_at IS NOT NULL THEN route_id
                       WHEN route_id IS NULL OR route_id=excluded.route_id
                       THEN COALESCE(excluded.route_id,route_id)
                       ELSE route_id END,
                     updated_at=CASE
                       WHEN state='CANCELADA' OR archived_at IS NOT NULL THEN updated_at
                       ELSE excluded.updated_at END""",
                (trip_key, provider_trip_id, plate, route_id, now, now),
            )
            row = connection.execute("SELECT * FROM operational_trips WHERE trip_key = ?", (trip_key,)).fetchone()
        return dict(row)

    def trip(self, trip_key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM operational_trips WHERE trip_key = ?", (trip_key,)).fetchone()
        return self._trip(row) if row else None

    def trips(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else " WHERE archived_at IS NULL"
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM operational_trips" + where + " ORDER BY updated_at DESC"
            ).fetchall()
        return [self._trip(row) for row in rows]

    def trip_for_provider(self, provider_trip_id: str | None, plate: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            if provider_trip_id:
                row = connection.execute(
                    "SELECT * FROM operational_trips WHERE provider_trip_id = ? ORDER BY updated_at DESC LIMIT 1",
                    (provider_trip_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM operational_trips WHERE plate = ? ORDER BY updated_at DESC LIMIT 1", (plate,)
                ).fetchone()
        return self._trip(row) if row else None

    def update_trip(self, trip_key: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "route_id", "state", "current_driver", "previous_driver", "driver_source",
            "driver_divergence", "driver_updated_at", "last_position_at", "last_latitude",
            "last_longitude", "last_speed_kmh", "origin_candidate_at", "origin_candidate_count",
            "origin_exit_candidate_at", "origin_exit_count", "destination_candidate_at",
            "destination_candidate_count", "destination_exit_count", "origin_entered_at",
            "arrived_origin_at", "started_at", "destination_entered_at",
            "loaded_at", "trailer_plate", "arrived_destination_at", "finished_at", "finish_type",
            "cancelled_at", "cancelled_by_user_id", "cancelled_reason",
            "archived_at", "archived_by_user_id", "archive_reason",
        }
        clean = {key: value for key, value in fields.items() if key in allowed}
        clean["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in clean)
        with self._lock, self.connect() as connection:
            connection.execute(
                f"UPDATE operational_trips SET {assignments} WHERE trip_key = ?",
                (*clean.values(), trip_key),
            )
            row = connection.execute("SELECT * FROM operational_trips WHERE trip_key = ?", (trip_key,)).fetchone()
        if row is None:
            raise KeyError(trip_key)
        return self._trip(row)

    def add_position(
        self, trip_key: str, latitude: float, longitude: float, speed_kmh: float | None,
        recorded_at: str, source: str, origin_distance_m: float | None,
        destination_distance_m: float | None, accepted: bool = True,
        rejection_reason: str | None = None,
    ) -> tuple[bool, str]:
        raw = f"{trip_key}|{recorded_at}|{latitude:.6f}|{longitude:.6f}|{speed_kmh}|{source}"
        fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        with self._lock, self.connect() as connection:
            try:
                connection.execute(
                    """INSERT INTO operational_positions
                       (trip_key, fingerprint, latitude, longitude, speed_kmh, recorded_at, source,
                        origin_distance_m, destination_distance_m, accepted, rejection_reason, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (trip_key, fingerprint, latitude, longitude, speed_kmh, recorded_at, source,
                     origin_distance_m, destination_distance_m, int(accepted), rejection_reason, utc_now()),
                )
            except sqlite3.IntegrityError:
                return False, fingerprint
        return True, fingerprint

    def add_event(
        self, trip_key: str, event_type: str, occurred_at: str, source: str,
        description: str, previous_state: str | None = None, new_state: str | None = None,
        metadata: dict[str, Any] | None = None, justification: str | None = None,
        operator: str | None = None, idempotency_key: str | None = None,
    ) -> bool:
        with self._lock, self.connect() as connection:
            try:
                connection.execute(
                    """INSERT INTO operational_events
                       (trip_key, event_type, occurred_at, source, description, previous_state,
                        new_state, metadata_json, justification, operator, idempotency_key, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (trip_key, event_type, occurred_at, source, description, previous_state, new_state,
                     json.dumps(metadata or {}, ensure_ascii=False), justification, operator,
                     idempotency_key, utc_now()),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def events(self, trip_key: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM operational_events WHERE trip_key = ? ORDER BY occurred_at DESC, id DESC LIMIT ?",
                (trip_key, limit),
            ).fetchall()
        return [self._event(row) for row in rows]

    def position_history(self, trip_key: str, limit: int = 1500) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows=connection.execute("SELECT latitude,longitude,speed_kmh,recorded_at,source FROM operational_positions WHERE trip_key=? AND accepted=1 ORDER BY recorded_at DESC LIMIT ?",(trip_key,limit)).fetchall()
        return [dict(row) for row in reversed(rows)]

    def raw_position_history(self, trip_key: str, limit: int = 2000) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id,latitude,longitude,speed_kmh,recorded_at,source,accepted,rejection_reason
                   FROM operational_positions WHERE trip_key=?
                   ORDER BY recorded_at DESC,id DESC LIMIT ?""",
                (trip_key, limit),
            ).fetchall()
        return [dict(row) | {"accepted": bool(row["accepted"])} for row in reversed(rows)]

    def route_progress(self, trip_key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row=connection.execute("SELECT * FROM route_progress_snapshots WHERE trip_key=?",(trip_key,)).fetchone()
        if not row:return None
        value=dict(row);value["last_reliable"]=json.loads(value.pop("last_reliable_json") or "null");return value

    def save_route_progress(self, value: dict[str, Any]) -> dict[str, Any]:
        columns=("trip_key","route_id","geometry_version","total_distance_km","advanced_distance_km","remaining_distance_km","progress_percent","return_distance_km","route_state","confidence","position_at","speed_kmh","speed_state","last_reliable_json","updated_at")
        data={**value,"last_reliable_json":json.dumps(value.get("last_reliable"),ensure_ascii=False),"updated_at":utc_now()}
        placeholders=",".join("?" for _ in columns);updates=",".join(f"{column}=excluded.{column}" for column in columns if column!="trip_key")
        with self._lock,self.connect() as connection:connection.execute(f"INSERT INTO route_progress_snapshots({','.join(columns)}) VALUES({placeholders}) ON CONFLICT(trip_key) DO UPDATE SET {updates}",tuple(data.get(column) for column in columns))
        return self.route_progress(value["trip_key"]) or value

    def return_candidate(self, parent_trip_key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM return_candidates WHERE parent_trip_key=?", (parent_trip_key,)
            ).fetchone()
        return self._return_candidate(row) if row else None

    def return_candidate_by_id(self, candidate_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM return_candidates WHERE id=?", (candidate_id,)).fetchone()
        return self._return_candidate(row) if row else None

    def save_return_tracker(self, parent_trip_key: str, **values: Any) -> None:
        allowed = ("outside_count", "direction_count", "departure_at", "departure_progress_km", "last_progress_km")
        data = {key: values.get(key) for key in allowed}
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO return_detection_trackers
                   (parent_trip_key,outside_count,direction_count,departure_at,departure_progress_km,last_progress_km,updated_at)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(parent_trip_key) DO UPDATE SET
                   outside_count=excluded.outside_count,direction_count=excluded.direction_count,
                   departure_at=excluded.departure_at,departure_progress_km=excluded.departure_progress_km,
                   last_progress_km=excluded.last_progress_km,updated_at=excluded.updated_at""",
                (parent_trip_key, *(data[key] for key in allowed), utc_now()),
            )

    def return_tracker(self, parent_trip_key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM return_detection_trackers WHERE parent_trip_key=?", (parent_trip_key,)
            ).fetchone()
        return dict(row) if row else None

    def create_return_candidate(self, value: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO return_candidates
                   (parent_trip_key,plate,driver_id,state,arrival_at,departure_at,
                    destination_stay_hours,progress_toward_origin_km,corridor_distance_m,
                    compatible_with_route,evidence_json,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (value["parent_trip_key"], value["plate"], value.get("driver_id"), value["state"],
                 value["arrival_at"], value["departure_at"], value["destination_stay_hours"],
                 value["progress_toward_origin_km"], value["corridor_distance_m"],
                 int(value["compatible_with_route"]), json.dumps(value["evidence"], ensure_ascii=False),
                 now, now),
            )
            row = connection.execute(
                "SELECT * FROM return_candidates WHERE parent_trip_key=?", (value["parent_trip_key"],)
            ).fetchone()
        return self._return_candidate(row)

    def decide_return_candidate(
        self, candidate_id: int, state: str, decision: str, operator: str,
        justification: str | None, return_trip_key: str | None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self.connect() as connection:
            connection.execute(
                """UPDATE return_candidates SET state=?,decision=?,decision_at=?,decided_by=?,
                   justification=?,return_trip_key=?,updated_at=? WHERE id=?""",
                (state, decision, now, operator, justification, return_trip_key, now, candidate_id),
            )
            row = connection.execute("SELECT * FROM return_candidates WHERE id=?", (candidate_id,)).fetchone()
        if not row:
            raise KeyError(candidate_id)
        return self._return_candidate(row)

    def diagnostic(self, trip_key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM operational_diagnostics WHERE trip_key=?", (trip_key,)
            ).fetchone()
        if not row:
            return None
        value = dict(row)
        for field in (
            "factors", "confidence_reasons", "risks", "recommendations",
            "scenarios", "last_reliable",
        ):
            value[field] = json.loads(value.pop(f"{field}_json") or ("{}" if field == "scenarios" else "null" if field == "last_reliable" else "[]"))
        return value

    def save_diagnostic(self, value: dict[str, Any]) -> dict[str, Any]:
        columns = (
            "trip_key", "eta_at", "window_start_at", "window_end_at", "client_eta_at",
            "commitment_delta_minutes",
            "trend", "confidence", "classification", "remaining_minutes", "stopped_minutes",
            "method_version", "factors_json", "confidence_reasons_json", "risks_json",
            "recommendations_json", "scenarios_json", "status_explanation",
            "last_reliable_json", "calculated_at", "updated_at",
        )
        data = {
            **value,
            "factors_json": json.dumps(value.get("factors") or [], ensure_ascii=False),
            "confidence_reasons_json": json.dumps(value.get("confidence_reasons") or [], ensure_ascii=False),
            "risks_json": json.dumps(value.get("risks") or [], ensure_ascii=False),
            "recommendations_json": json.dumps(value.get("recommendations") or [], ensure_ascii=False),
            "scenarios_json": json.dumps(value.get("scenarios") or {}, ensure_ascii=False),
            "last_reliable_json": json.dumps(value.get("last_reliable"), ensure_ascii=False),
            "updated_at": utc_now(),
        }
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(f"{column}=excluded.{column}" for column in columns if column != "trip_key")
        with self._lock, self.connect() as connection:
            connection.execute(
                f"INSERT INTO operational_diagnostics({','.join(columns)}) VALUES({placeholders}) "
                f"ON CONFLICT(trip_key) DO UPDATE SET {updates}",
                tuple(data.get(column) for column in columns),
            )
            latest = connection.execute(
                "SELECT eta_at,client_eta_at,commitment_delta_minutes,classification,trend,confidence "
                "FROM eta_history WHERE trip_key=? ORDER BY id DESC LIMIT 1",
                (value["trip_key"],),
            ).fetchone()
            signature = (
                data.get("eta_at"), data.get("client_eta_at"),
                data.get("commitment_delta_minutes"), data.get("classification"),
                data.get("trend"), data.get("confidence"),
            )
            if latest is None or tuple(latest) != signature:
                connection.execute(
                    """INSERT INTO eta_history(
                       trip_key,eta_at,client_eta_at,commitment_delta_minutes,
                       classification,trend,confidence,remaining_minutes,source,
                       method_version,evidence_json,recorded_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        value["trip_key"], data.get("eta_at"), data.get("client_eta_at"),
                        data.get("commitment_delta_minutes"), data.get("classification"),
                        data.get("trend"), data.get("confidence"), data.get("remaining_minutes"),
                        "SEVEN_DIAGNOSTIC", data.get("method_version"),
                        json.dumps({"factors": value.get("factors") or []}, ensure_ascii=False),
                        data.get("calculated_at") or utc_now(),
                    ),
                )
        return self.diagnostic(value["trip_key"]) or value

    def save_plan(self, trip_key: str, value: dict[str, Any], operator: str) -> dict[str, Any]:
        if not self.trip(trip_key):
            raise KeyError(trip_key)
        now = utc_now()
        columns = (
            "trip_key", "scheduled_start_at", "scheduled_arrival_at",
            "customer_commitment_at", "planned_loading_minutes",
            "planned_stops_minutes", "operational_buffer_minutes", "source",
            "notes", "updated_by", "created_at", "updated_at",
        )
        data = {
            **value, "trip_key": trip_key, "updated_by": operator,
            "created_at": now, "updated_at": now,
        }
        with self._lock, self.connect() as connection:
            connection.execute(
                f"INSERT INTO trip_plans({','.join(columns)}) VALUES({','.join('?' for _ in columns)}) "
                "ON CONFLICT(trip_key) DO UPDATE SET "
                + ",".join(
                    f"{column}=excluded.{column}"
                    for column in columns if column not in {"trip_key", "created_at"}
                ),
                tuple(data.get(column) for column in columns),
            )
        return self.plan(trip_key) or data

    def plan(self, trip_key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM trip_plans WHERE trip_key=?", (trip_key,)
            ).fetchone()
        return dict(row) if row else None

    def eta_history(self, trip_key: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM eta_history WHERE trip_key=? ORDER BY recorded_at DESC LIMIT ?",
                (trip_key, limit),
            ).fetchall()
        values = []
        for row in rows:
            value = dict(row)
            value["evidence"] = json.loads(value.pop("evidence_json") or "{}")
            values.append(value)
        return values

    @staticmethod
    def _route(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["active"] = bool(value["active"])
        value["is_express"] = bool(value.get("is_express", 0))
        value["match_terms"] = json.loads(value.pop("match_terms_json") or "[]")
        return value

    @staticmethod
    def _trip(row: sqlite3.Row) -> dict[str, Any]:
        return OperationsRepository._trip_from_mapping(dict(row))

    @staticmethod
    def _trip_from_mapping(value: dict[str, Any]) -> dict[str, Any]:
        value["driver_divergence"] = bool(value["driver_divergence"])
        return value

    @staticmethod
    def _event(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["metadata"] = json.loads(value.pop("metadata_json") or "{}")
        return value

    @staticmethod
    def _return_candidate(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["compatible_with_route"] = bool(value["compatible_with_route"])
        value["evidence"] = json.loads(value.pop("evidence_json") or "{}")
        return value
