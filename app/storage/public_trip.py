from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.storage.operations import OperationsRepository


PUBLIC_LINK_SCHEMA = """
CREATE TABLE IF NOT EXISTS public_trip_links (
 id TEXT PRIMARY KEY, trip_key TEXT NOT NULL REFERENCES operational_trips(trip_key),
 token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, expires_at TEXT, revoked_at TEXT,
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), last_access_at TEXT,
 access_count INTEGER NOT NULL DEFAULT 0 CHECK(access_count>=0), created_by TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS idx_public_trip_links_one_active
 ON public_trip_links(trip_key) WHERE active=1;
CREATE INDEX IF NOT EXISTS idx_public_trip_links_hash ON public_trip_links(token_hash);
CREATE TABLE IF NOT EXISTS public_trip_link_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 public_link_id TEXT NOT NULL REFERENCES public_trip_links(id),
 event_type TEXT NOT NULL, occurred_at TEXT NOT NULL, actor TEXT,
 metadata_json TEXT NOT NULL DEFAULT '{}');
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PublicTripRepository:
    def __init__(self, operations: OperationsRepository) -> None:
        self.operations = operations
        self.initialize()

    def initialize(self) -> None:
        with self.operations.connect() as connection:
            connection.executescript(PUBLIC_LINK_SCHEMA)
            trip_columns = {row["name"] for row in connection.execute("PRAGMA table_info(operational_trips)")}
            if "loaded_at" not in trip_columns:
                connection.execute("ALTER TABLE operational_trips ADD COLUMN loaded_at TEXT")
            if "trailer_plate" not in trip_columns:
                connection.execute("ALTER TABLE operational_trips ADD COLUMN trailer_plate TEXT")
            traffic_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='traffic_incidents'"
            ).fetchone()
            traffic_columns = (
                {row["name"] for row in connection.execute("PRAGMA table_info(traffic_incidents)")}
                if traffic_table else set()
            )
        self._public_incidents_available = {
            "publicly_visible", "public_title", "public_description"
        }.issubset(traffic_columns)

    def mobile_schema_available(self) -> bool:
        with self.operations.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='portal_mobile_position_metadata'"
            ).fetchone() is not None

    def latest_position_by_source(self, trip_key: str, *, mobile: bool) -> dict[str, Any] | None:
        operator = "=" if mobile else "<>"
        with self.operations.connect() as connection:
            row = connection.execute(
                f"""SELECT p.latitude,p.longitude,p.speed_kmh,p.recorded_at,p.source,
                            m.accuracy_m,m.received_at
                     FROM operational_positions p
                     LEFT JOIN portal_mobile_position_metadata m ON m.position_id=p.id
                     WHERE p.trip_key=? AND p.accepted=1 AND UPPER(p.source){operator}'LINK_MOTORISTA'
                     ORDER BY p.recorded_at DESC,p.id DESC LIMIT 1""",
                (trip_key,),
            ).fetchone()
        return dict(row) if row else None

    def save_mobile_position(
        self,
        *,
        trip_key: str,
        link_id: str,
        fingerprint: str,
        latitude: float,
        longitude: float,
        accuracy_m: float,
        client_recorded_at: str | None,
        received_at: str,
        min_interval_seconds: int,
        max_per_minute: int,
    ) -> int:
        with self.operations._lock, self.operations.connect() as connection:
            last = connection.execute(
                "SELECT received_at FROM portal_mobile_position_metadata "
                "WHERE public_link_id=? ORDER BY received_at DESC LIMIT 1",
                (link_id,),
            ).fetchone()
            window_start = (
                datetime.fromisoformat(received_at) - timedelta(seconds=60)
            ).isoformat()
            recent = connection.execute(
                "SELECT COUNT(*) FROM portal_mobile_position_metadata "
                "WHERE public_link_id=? AND received_at>=?",
                (link_id, window_start),
            ).fetchone()[0]
            if last:
                elapsed = (
                    datetime.fromisoformat(received_at) - datetime.fromisoformat(last["received_at"])
                ).total_seconds()
                if elapsed < min_interval_seconds:
                    raise ValueError(f"rate_interval:{max(1, int(min_interval_seconds - elapsed))}")
            if recent >= max_per_minute:
                raise ValueError("rate_window:60")
            cursor = connection.execute(
                """INSERT INTO operational_positions(
                   trip_key,fingerprint,latitude,longitude,speed_kmh,recorded_at,source,
                   origin_distance_m,destination_distance_m,accepted,rejection_reason,created_at)
                   VALUES(?,?,?,?,NULL,?,'LINK_MOTORISTA',NULL,NULL,1,NULL,?)""",
                (trip_key, fingerprint, latitude, longitude, received_at, received_at),
            )
            connection.execute(
                """INSERT INTO portal_mobile_position_metadata(
                   position_id,public_link_id,accuracy_m,client_recorded_at,received_at)
                   VALUES(?,?,?,?,?)""",
                (cursor.lastrowid, link_id, accuracy_m, client_recorded_at, received_at),
            )
            return int(cursor.lastrowid)

    def active_for_trip(self, trip_key: str) -> dict[str, Any] | None:
        with self.operations.connect() as connection:
            row = connection.execute(
                "SELECT * FROM public_trip_links WHERE trip_key=? AND active=1 ORDER BY created_at DESC LIMIT 1",
                (trip_key,),
            ).fetchone()
        return dict(row) if row else None

    def latest_for_trip(self, trip_key: str) -> dict[str, Any] | None:
        with self.operations.connect() as connection:
            row = connection.execute(
                "SELECT * FROM public_trip_links WHERE trip_key=? ORDER BY created_at DESC LIMIT 1",
                (trip_key,),
            ).fetchone()
        return dict(row) if row else None

    def by_hash(self, token_hash: str) -> dict[str, Any] | None:
        with self.operations.connect() as connection:
            row = connection.execute(
                "SELECT * FROM public_trip_links WHERE token_hash=? LIMIT 1", (token_hash,)
            ).fetchone()
        return dict(row) if row else None

    def create(self, value: dict[str, Any]) -> dict[str, Any]:
        now = value["created_at"]
        with self.operations._lock, self.operations.connect() as connection:
            current = connection.execute(
                "SELECT id FROM public_trip_links WHERE trip_key=? AND active=1", (value["trip_key"],)
            ).fetchone()
            if current:
                connection.execute(
                    "UPDATE public_trip_links SET active=0,revoked_at=? WHERE id=?", (now, current["id"])
                )
                self._event(connection, current["id"], "ROTATED", value.get("created_by"))
            connection.execute(
                """INSERT INTO public_trip_links
                   (id,trip_key,token_hash,created_at,expires_at,active,created_by)
                   VALUES(?,?,?,?,?,1,?)""",
                (value["id"], value["trip_key"], value["token_hash"], now,
                 value.get("expires_at"), value.get("created_by")),
            )
            self._event(connection, value["id"], "CREATED", value.get("created_by"))
        return self.active_for_trip(value["trip_key"]) or value

    def revoke(self, trip_key: str, actor: str | None) -> dict[str, Any] | None:
        now = utc_now()
        with self.operations._lock, self.operations.connect() as connection:
            row = connection.execute(
                "SELECT * FROM public_trip_links WHERE trip_key=? AND active=1", (trip_key,)
            ).fetchone()
            if not row:
                return None
            connection.execute(
                "UPDATE public_trip_links SET active=0,revoked_at=? WHERE id=?", (now, row["id"])
            )
            self._event(connection, row["id"], "REVOKED", actor)
        return dict(row) | {"active": 0, "revoked_at": now}

    def revoke_finished_trip(self, trip_key: str) -> int:
        """Invalidate every active link when its operational trip is finished."""
        now = utc_now()
        with self.operations._lock, self.operations.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM public_trip_links WHERE trip_key=? AND active=1",
                (trip_key,),
            ).fetchall()
            if not rows:
                return 0
            connection.execute(
                """UPDATE public_trip_links
                   SET active=0,revoked_at=COALESCE(revoked_at,?)
                   WHERE trip_key=? AND active=1""",
                (now, trip_key),
            )
            for row in rows:
                self._event(connection, row["id"], "TRIP_FINISHED", "system:trip-status")
        return len(rows)

    def expire(self, link_id: str) -> None:
        now = utc_now()
        with self.operations._lock, self.operations.connect() as connection:
            changed = connection.execute(
                "UPDATE public_trip_links SET active=0 WHERE id=? AND active=1", (link_id,)
            ).rowcount
            if changed:
                self._event(connection, link_id, "EXPIRED", None)

    def record_access(self, link_id: str) -> None:
        now = utc_now()
        with self.operations._lock, self.operations.connect() as connection:
            connection.execute(
                """UPDATE public_trip_links
                   SET last_access_at=?,access_count=access_count+1 WHERE id=?""",
                (now, link_id),
            )

    def public_incidents(self, trip_key: str, route_id: str | None) -> list[dict[str, Any]]:
        if not trip_key or not route_id or not self._public_incidents_available:
            return []
        with self.operations.connect() as connection:
            rows = connection.execute(
                """SELECT id,category,public_title,public_description,description,severity,
                          source,road_name,direction,latitude,longitude,delay_seconds,
                          updated_at,expires_at,status,affected_vehicles_json
                   FROM traffic_incidents
                   WHERE route_id=? AND publicly_visible=1
                     AND status IN ('ACTIVE','CONFIRMED') AND expires_at>?
                   ORDER BY updated_at DESC LIMIT 100""",
                (route_id, utc_now()),
            ).fetchall()
        result = []
        for row in rows:
            try:
                affected = json.loads(row["affected_vehicles_json"] or "[]")
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(affected, list) or not any(
                isinstance(item, dict) and item.get("trip_key") == trip_key
                for item in affected
            ):
                continue
            result.append(dict(row) | {"affected_vehicles_json": None})
        return result

    def alert_schema_available(self) -> bool:
        with self.operations.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='portal_alert_presentations'"
            ).fetchone() is not None

    def register_alerts(
        self, link_id: str, alerts: list[dict[str, Any]], seen_at: str
    ) -> list[dict[str, Any]]:
        if not self.alert_schema_available():
            return [item | {"presentation": "ACTIVE"} for item in alerts]
        active_keys = {item["id"] for item in alerts}
        result = []
        with self.operations._lock, self.operations.connect() as connection:
            existing = {
                row["alert_key"]: row for row in connection.execute(
                    "SELECT * FROM portal_alert_presentations WHERE public_link_id=?",
                    (link_id,),
                ).fetchall()
            }
            for alert in alerts:
                previous = existing.get(alert["id"])
                if previous is None:
                    presentation = "NEW"
                elif previous["severity"] != alert["severity"]:
                    presentation = "UPDATED"
                elif previous["distance_band"] != alert["distance_band"]:
                    presentation = "REINFORCED"
                else:
                    presentation = "ACTIVE"
                if previous is None:
                    connection.execute(
                        """INSERT INTO portal_alert_presentations(
                           public_link_id,alert_key,distance_band,severity,first_presented_at,
                           last_presented_at,last_seen_at,presentation_count,active)
                           VALUES(?,?,?,?,?,?,?,1,1)""",
                        (link_id, alert["id"], alert["distance_band"], alert["severity"],
                         seen_at, seen_at, seen_at),
                    )
                elif presentation == "ACTIVE":
                    connection.execute(
                        "UPDATE portal_alert_presentations SET last_seen_at=?,active=1 "
                        "WHERE public_link_id=? AND alert_key=?",
                        (seen_at, link_id, alert["id"]),
                    )
                else:
                    connection.execute(
                        """UPDATE portal_alert_presentations SET distance_band=?,severity=?,
                           last_presented_at=?,last_seen_at=?,presentation_count=presentation_count+1,
                           active=1 WHERE public_link_id=? AND alert_key=?""",
                        (alert["distance_band"], alert["severity"], seen_at, seen_at,
                         link_id, alert["id"]),
                    )
                result.append(alert | {"presentation": presentation})
            for key, previous in existing.items():
                if previous["active"] and key not in active_keys:
                    connection.execute(
                        "UPDATE portal_alert_presentations SET active=0,last_seen_at=? "
                        "WHERE public_link_id=? AND alert_key=?",
                        (seen_at, link_id, key),
                    )
        return result

    @staticmethod
    def _event(connection, link_id: str, event_type: str, actor: str | None) -> None:
        connection.execute(
            """INSERT INTO public_trip_link_events
               (public_link_id,event_type,occurred_at,actor,metadata_json) VALUES(?,?,?,?,?)""",
            (link_id, event_type, utc_now(), actor, "{}"),
        )
