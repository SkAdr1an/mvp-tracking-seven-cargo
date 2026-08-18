from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.storage.operations import OperationsRepository


TRAFFIC_SCHEMA = """
CREATE TABLE IF NOT EXISTS traffic_snapshots (
 id INTEGER PRIMARY KEY AUTOINCREMENT, route_id TEXT NOT NULL, collected_at TEXT NOT NULL,
 status TEXT NOT NULL, request_count INTEGER NOT NULL, incident_count INTEGER NOT NULL,
 latency_ms REAL, error_code TEXT, metadata_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS traffic_incidents (
 id TEXT PRIMARY KEY, route_id TEXT NOT NULL, category TEXT NOT NULL, severity TEXT NOT NULL,
 original_type TEXT, source TEXT NOT NULL, description TEXT NOT NULL, road_name TEXT,
 direction TEXT, latitude REAL NOT NULL, longitude REAL NOT NULL, geometry_json TEXT NOT NULL,
 length_m REAL, delay_seconds REAL, delay_already_in_eta INTEGER NOT NULL DEFAULT 1,
 started_at TEXT, updated_at TEXT NOT NULL, expires_at TEXT NOT NULL, status TEXT NOT NULL,
 manual INTEGER NOT NULL DEFAULT 0, information_source TEXT, responsible_user TEXT,
 affected_vehicles_json TEXT NOT NULL DEFAULT '[]', provider_payload_json TEXT NOT NULL DEFAULT '{}',
 publicly_visible INTEGER NOT NULL DEFAULT 0, public_title TEXT, public_description TEXT,
 created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_incidents_route_status ON traffic_incidents(route_id,status,expires_at);
CREATE TABLE IF NOT EXISTS traffic_incident_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL, action TEXT NOT NULL,
 occurred_at TEXT NOT NULL, user_name TEXT, justification TEXT, changes_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS provider_health (
 provider TEXT PRIMARY KEY, status TEXT NOT NULL, http_status INTEGER, latency_ms REAL,
 result_count INTEGER NOT NULL DEFAULT 0, message TEXT, checked_at TEXT NOT NULL);
"""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrafficRepository:
    def __init__(self, operations: OperationsRepository) -> None:
        self.operations = operations

    def save_snapshot(self, route_id: str, status: str, requests: int, count: int,
                      latency_ms: float | None = None, error_code: str | None = None,
                      metadata: dict[str, Any] | None = None) -> None:
        with self.operations.connect() as connection:
            connection.execute(
                "INSERT INTO traffic_snapshots(route_id,collected_at,status,request_count,incident_count,latency_ms,error_code,metadata_json) VALUES(?,?,?,?,?,?,?,?)",
                (route_id, now_utc(), status, requests, count, latency_ms, error_code, json.dumps(metadata or {})),
            )

    def upsert_incident(self, incident: dict[str, Any]) -> None:
        fields = ("id","route_id","category","severity","original_type","source","description","road_name",
                  "direction","latitude","longitude","geometry_json","length_m","delay_seconds","delay_already_in_eta",
                  "started_at","updated_at","expires_at","status","manual","information_source","responsible_user",
                  "affected_vehicles_json","provider_payload_json","created_at")
        values = {**incident, "geometry_json": json.dumps(incident.get("geometry", {})),
                  "affected_vehicles_json": json.dumps(incident.get("affected_vehicles", []), ensure_ascii=False),
                  "provider_payload_json": json.dumps(incident.get("provider_payload", {})),
                  "delay_already_in_eta": int(incident.get("delay_already_in_eta", True)),
                  "manual": int(incident.get("manual", False)), "created_at": incident.get("created_at", now_utc())}
        placeholders = ",".join(f":{field}" for field in fields)
        updates = ",".join(f"{field}=excluded.{field}" for field in fields if field not in {"id","created_at","manual"})
        with self.operations.connect() as connection:
            connection.execute(f"INSERT INTO traffic_incidents({','.join(fields)}) VALUES({placeholders}) ON CONFLICT(id) DO UPDATE SET {updates}", values)

    def incidents(self, route_id: str | None = None, bbox: tuple[float,float,float,float] | None = None,
                  include_inactive: bool = False) -> list[dict[str, Any]]:
        clauses, params = [], []
        if route_id: clauses.append("route_id=?"); params.append(route_id)
        if not include_inactive: clauses.extend(["status IN ('ACTIVE','CONFIRMED')", "expires_at>?"]); params.append(now_utc())
        if bbox:
            clauses.extend(["longitude>=?","latitude>=?","longitude<=?","latitude<=?"]); params.extend(bbox)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.operations.connect() as connection:
            rows = connection.execute("SELECT * FROM traffic_incidents" + where + " ORDER BY severity DESC,updated_at DESC", params).fetchall()
        return [self._incident(row) for row in rows]

    def incident(self, incident_id: str) -> dict[str, Any] | None:
        with self.operations.connect() as connection:
            row = connection.execute("SELECT * FROM traffic_incidents WHERE id=?", (incident_id,)).fetchone()
            history = connection.execute("SELECT * FROM traffic_incident_history WHERE incident_id=? ORDER BY occurred_at DESC", (incident_id,)).fetchall()
        if not row: return None
        value = self._incident(row); value["history"] = [dict(item) | {"changes": json.loads(item["changes_json"])} for item in history]
        for item in value["history"]: item.pop("changes_json", None)
        return value

    def update_manual(self, incident_id: str, changes: dict[str, Any], action: str, user: str, justification: str) -> dict[str, Any]:
        allowed = {"category","severity","description","road_name","direction","latitude","longitude","started_at","expires_at","status","information_source"}
        clean = {key:value for key,value in changes.items() if key in allowed}
        if not clean: raise ValueError("Nenhuma alteração válida")
        clean["updated_at"] = now_utc()
        with self.operations.connect() as connection:
            current = connection.execute("SELECT manual FROM traffic_incidents WHERE id=?", (incident_id,)).fetchone()
            if not current: raise KeyError(incident_id)
            if not current["manual"]: raise ValueError("Somente ocorrências manuais podem ser alteradas")
            connection.execute("UPDATE traffic_incidents SET " + ",".join(f"{key}=?" for key in clean) + " WHERE id=?", (*clean.values(), incident_id))
            connection.execute("INSERT INTO traffic_incident_history(incident_id,action,occurred_at,user_name,justification,changes_json) VALUES(?,?,?,?,?,?)",
                               (incident_id, action, now_utc(), user, justification, json.dumps(clean, ensure_ascii=False)))
        return self.incident(incident_id) or {}

    def expire(self) -> int:
        with self.operations.connect() as connection:
            cursor = connection.execute("UPDATE traffic_incidents SET status='EXPIRED' WHERE status IN ('ACTIVE','CONFIRMED') AND expires_at<=?", (now_utc(),))
            return cursor.rowcount

    def expire_irrelevant(self, route_id: str, source: str | None = None,
                          relevant_ids: set[str] | None = None) -> int:
        """Expire automated incidents no longer relevant after a successful route evaluation."""
        clauses=["route_id=?","manual=0","status IN ('ACTIVE','CONFIRMED')"]
        params: list[Any]=[route_id]
        if source:
            clauses.append("source=?"); params.append(source)
        identifiers=sorted(relevant_ids or set())
        if identifiers:
            clauses.append(f"id NOT IN ({','.join('?' for _ in identifiers)})"); params.extend(identifiers)
        with self.operations.connect() as connection:
            cursor=connection.execute(
                "UPDATE traffic_incidents SET status='EXPIRED',updated_at=? WHERE "+" AND ".join(clauses),
                [now_utc(),*params],
            )
            return cursor.rowcount

    def health(self) -> dict[str, dict[str, Any]]:
        with self.operations.connect() as connection:
            rows = connection.execute("SELECT * FROM provider_health").fetchall()
        return {row["provider"]: dict(row) for row in rows}

    def save_health(self, provider: str, status: str, http_status: int | None, latency_ms: float | None,
                    count: int, message: str) -> None:
        with self.operations.connect() as connection:
            connection.execute("INSERT INTO provider_health(provider,status,http_status,latency_ms,result_count,message,checked_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(provider) DO UPDATE SET status=excluded.status,http_status=excluded.http_status,latency_ms=excluded.latency_ms,result_count=excluded.result_count,message=excluded.message,checked_at=excluded.checked_at",
                               (provider,status,http_status,latency_ms,count,message,now_utc()))

    def latest_snapshot(self, route_id: str | None = None) -> dict[str, Any] | None:
        query = "SELECT * FROM traffic_snapshots" + (" WHERE route_id=?" if route_id else "") + " ORDER BY collected_at DESC LIMIT 1"
        with self.operations.connect() as connection:
            row = connection.execute(query, (route_id,) if route_id else ()).fetchone()
        if not row: return None
        value=dict(row); value["metadata"]=json.loads(value.pop("metadata_json")); return value

    @staticmethod
    def _incident(row: sqlite3.Row) -> dict[str, Any]:
        value=dict(row); value["geometry"]=json.loads(value.pop("geometry_json")); value["affected_vehicles"]=json.loads(value.pop("affected_vehicles_json")); value["provider_payload"]=json.loads(value.pop("provider_payload_json")); value["manual"]=bool(value["manual"]); value["delay_already_in_eta"]=bool(value["delay_already_in_eta"]); return value
