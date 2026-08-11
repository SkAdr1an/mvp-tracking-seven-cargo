from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS angellira_dataset_versions (
    dataset_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    source_name TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    counts_json TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    imported_by TEXT NOT NULL,
    PRIMARY KEY(dataset_id, source_version)
);
CREATE TABLE IF NOT EXISTS angellira_import_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    event_type TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    actor TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS angellira_stations (
    post_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    city TEXT NOT NULL,
    uf TEXT NOT NULL,
    road TEXT,
    km TEXT,
    phone TEXT,
    data_quality_status TEXT NOT NULL,
    manual_review_required INTEGER NOT NULL DEFAULT 0,
    possible_merge_group_id TEXT,
    map_validation_status TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    geocoding_provider TEXT,
    geocoding_confidence REAL,
    display_on_map INTEGER NOT NULL DEFAULT 0,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    geocode_query_hash TEXT,
    last_geocoded_at TEXT,
    reviewed_at TEXT,
    reviewed_by TEXT,
    review_notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (display_on_map = 0 OR (
        map_validation_status = 'validated' AND
        latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180
    ))
);
CREATE INDEX IF NOT EXISTS idx_angellira_stations_map
ON angellira_stations(display_on_map, map_validation_status);
CREATE TABLE IF NOT EXISTS angellira_station_variants (
    dataset_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    possible_merge_group_id TEXT NOT NULL,
    exact_group_id TEXT NOT NULL,
    representative_name TEXT NOT NULL,
    city_uf TEXT,
    road TEXT,
    km TEXT,
    phone TEXT,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    review_decision TEXT,
    review_notes TEXT,
    reviewed_at TEXT,
    reviewed_by TEXT,
    PRIMARY KEY(dataset_id, source_version, possible_merge_group_id, exact_group_id)
);
CREATE TABLE IF NOT EXISTS angellira_risk_areas (
    risk_area_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    risk_type TEXT NOT NULL,
    city TEXT,
    uf TEXT,
    data_quality_status TEXT NOT NULL,
    geometry_type TEXT,
    geometry_json TEXT,
    geometry_validation_status TEXT NOT NULL,
    geometry_version TEXT,
    display_on_map INTEGER NOT NULL DEFAULT 0,
    eligible_for_dwell INTEGER NOT NULL DEFAULT 0,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    reviewed_at TEXT,
    reviewed_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (geometry_type IS NULL OR geometry_type IN ('Polygon', 'MultiPolygon')),
    CHECK (display_on_map = 0 OR geometry_validation_status = 'validated'),
    CHECK (eligible_for_dwell = 0 OR geometry_validation_status = 'validated')
);
CREATE TABLE IF NOT EXISTS angellira_geocode_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    query_text TEXT NOT NULL,
    status TEXT NOT NULL,
    provider_result_id TEXT,
    latitude REAL,
    longitude REAL,
    score REAL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    attempted_at TEXT NOT NULL,
    UNIQUE(post_id, query_hash)
);
CREATE TABLE IF NOT EXISTS angellira_risk_dwell_trackers (
    trip_key TEXT NOT NULL,
    risk_area_id TEXT NOT NULL,
    geometry_version TEXT NOT NULL,
    inside_count INTEGER NOT NULL DEFAULT 0,
    entered_at TEXT,
    last_position_at TEXT,
    first_latitude REAL,
    first_longitude REAL,
    last_latitude REAL,
    last_longitude REAL,
    movement_m REAL NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'OBSERVING',
    updated_at TEXT NOT NULL,
    PRIMARY KEY(trip_key, risk_area_id)
);
CREATE TABLE IF NOT EXISTS angellira_risk_dwell_episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_key TEXT NOT NULL,
    risk_area_id TEXT NOT NULL,
    geometry_version TEXT NOT NULL,
    level TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    second_factor TEXT,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
"""


class AngelLiraRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._lock = threading.RLock()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        path = Path(self.database_path)
        if self.database_path != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=10, check_same_thread=False)
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

    def dataset(self, dataset_id: str, source_version: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM angellira_dataset_versions WHERE dataset_id=? AND source_version=?",
                (dataset_id, source_version),
            ).fetchone()
        return self._json_row(row, ("counts_json",)) if row else None

    def latest_dataset(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM angellira_dataset_versions WHERE status='imported' "
                "ORDER BY imported_at DESC LIMIT 1"
            ).fetchone()
        return self._json_row(row, ("counts_json",)) if row else None

    def stations(self, map_only: bool = False) -> list[dict[str, Any]]:
        where = " WHERE display_on_map=1 AND map_validation_status='validated'" if map_only else ""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM angellira_stations" + where + " ORDER BY canonical_name, post_id"
            ).fetchall()
        return [self._station(row) for row in rows]

    def station(self, post_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM angellira_stations WHERE post_id=?", (post_id,)
            ).fetchone()
        return self._station(row) if row else None

    def risk_areas(self, map_only: bool = False) -> list[dict[str, Any]]:
        where = (
            " WHERE display_on_map=1 AND geometry_validation_status='validated'"
            if map_only else ""
        )
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM angellira_risk_areas" + where + " ORDER BY canonical_name, risk_area_id"
            ).fetchall()
        return [self._risk(row) for row in rows]

    def review_queue(self) -> dict[str, list[dict[str, Any]]]:
        with self.connect() as connection:
            stations = connection.execute(
                "SELECT * FROM angellira_stations "
                "WHERE map_validation_status IN ('not_geocoded','probable','pending_review') "
                "ORDER BY canonical_name"
            ).fetchall()
            variants = connection.execute(
                "SELECT * FROM angellira_station_variants WHERE review_decision IS NULL "
                "ORDER BY possible_merge_group_id, exact_group_id"
            ).fetchall()
            risks = connection.execute(
                "SELECT * FROM angellira_risk_areas WHERE geometry_validation_status!='validated' "
                "ORDER BY canonical_name"
            ).fetchall()
        return {
            "stations": [self._station(row) for row in stations],
            "variants": [self._json_row(row, ("evidence_json",)) for row in variants],
            "risk_areas": [self._risk(row) for row in risks],
        }

    @staticmethod
    def _json_row(row: sqlite3.Row, fields: tuple[str, ...]) -> dict[str, Any]:
        value = dict(row)
        for field in fields:
            value[field.removesuffix("_json")] = json.loads(value.pop(field) or "{}")
        return value

    def _station(self, row: sqlite3.Row) -> dict[str, Any]:
        value = self._json_row(row, ("evidence_json", "provenance_json"))
        value["display_on_map"] = bool(value["display_on_map"])
        value["manual_review_required"] = bool(value["manual_review_required"])
        return value

    def _risk(self, row: sqlite3.Row) -> dict[str, Any]:
        value = self._json_row(row, ("evidence_json", "provenance_json"))
        value["geometry"] = json.loads(value.pop("geometry_json")) if value.get("geometry_json") else None
        value.pop("geometry_json", None)
        value["display_on_map"] = bool(value["display_on_map"])
        value["eligible_for_dwell"] = bool(value["eligible_for_dwell"])
        return value
