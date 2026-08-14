"""Central, append-only audit trail for human actions.

Action types are deliberately centralized here. Sector-specific event tables remain
the source of their detailed domain history; this table is the searchable envelope.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.core.security import Principal
from app.storage.sqlite_runtime import connect_existing_database


logger = logging.getLogger(__name__)


class AuditAction(StrEnum):
    AUTH_LOGIN_SUCCESS = "AUTH_LOGIN_SUCCESS"
    AUTH_LOGIN_FAILURE = "AUTH_LOGIN_FAILURE"
    AUTH_LOGOUT = "AUTH_LOGOUT"
    USER_CREATED = "USER_CREATED"
    USER_UPDATED = "USER_UPDATED"
    USER_ACTIVATED = "USER_ACTIVATED"
    USER_DEACTIVATED = "USER_DEACTIVATED"
    USER_ROLE_CHANGED = "USER_ROLE_CHANGED"
    USER_PASSWORD_RESET = "USER_PASSWORD_RESET"
    TRIP_PLAN_UPDATED = "TRIP_PLAN_UPDATED"
    TRIP_FINALIZED = "TRIP_FINALIZED"
    TRIP_REOPENED = "TRIP_REOPENED"
    TRIP_STATUS_CORRECTED = "TRIP_STATUS_CORRECTED"
    TRIP_ROUTE_ASSIGNED = "TRIP_ROUTE_ASSIGNED"
    TRIP_DRIVER_ASSIGNED = "TRIP_DRIVER_ASSIGNED"
    TRIP_RETURN_DECISION = "TRIP_RETURN_DECISION"
    TRIP_CANCELLED = "TRIP_CANCELLED"
    TRIP_ARCHIVED = "TRIP_ARCHIVED"
    TRIP_UNARCHIVED = "TRIP_UNARCHIVED"
    STOP_JUSTIFIED = "STOP_JUSTIFIED"
    OBSERVATION_CREATED = "OBSERVATION_CREATED"
    OBSERVATION_CORRECTED = "OBSERVATION_CORRECTED"
    OBSERVATION_VOIDED = "OBSERVATION_VOIDED"
    INCIDENT_CREATED = "INCIDENT_CREATED"
    INCIDENT_UPDATED = "INCIDENT_UPDATED"
    INCIDENT_CONFIRMED = "INCIDENT_CONFIRMED"
    INCIDENT_CLOSED = "INCIDENT_CLOSED"
    INCIDENT_DISCARDED = "INCIDENT_DISCARDED"
    PUBLIC_LINK_CREATED = "PUBLIC_LINK_CREATED"
    PUBLIC_LINK_REVOKED = "PUBLIC_LINK_REVOKED"
    REPORT_GENERATED = "REPORT_GENERATED"
    INTEGRATION_INVOKED = "INTEGRATION_INVOKED"


SENSITIVE_PARTS = ("password", "passwd", "secret", "token", "cookie", "api_key", "apikey", "authorization", "pepper", "hash")


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _safe(item) for key, item in value.items()
            if not any(part in str(key).lower() for part in SENSITIVE_PARTS)
        }
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(_safe(value), ensure_ascii=False, sort_keys=True)


class AuditService:
    def __init__(self, database_path: str | Path):
        self.database_path = str(Path(database_path).resolve())

    def _connect(self) -> sqlite3.Connection:
        connection = connect_existing_database(self.database_path)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def record(self, principal: Principal, action_type: AuditAction, resource_type: str, *,
               resource_id: str | int | None = None, trip_key: str | None = None,
               before: Any = None, after: Any = None, content: str | None = None,
               justification: str | None = None, metadata: Any = None,
               request_id: str | None = None, connection: sqlite3.Connection | None = None) -> str:
        if not principal.username or not principal.role.value:
            raise ValueError("Human audit snapshots are required")
        identifier = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        values = (
            identifier, now, principal.user_id, principal.username,
            principal.display_name or principal.username, principal.role.value,
            action_type.value, resource_type, None if resource_id is None else str(resource_id),
            trip_key, _json(before), _json(after), content, justification,
            request_id or str(uuid.uuid4()), _json(metadata), now,
        )
        sql = """INSERT INTO audit_events(id,occurred_at,actor_user_id,
                 actor_username_snapshot,actor_display_name_snapshot,actor_role_snapshot,
                 action_type,resource_type,resource_id,trip_key,before_json,after_json,
                 content,justification,request_id,metadata_json,created_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
        if connection is not None:
            connection.execute(sql, values)
        else:
            with self._connect() as owned:
                owned.execute(sql, values)
        return identifier

    def record_login_failure(self, attempted_username: str) -> str:
        """Record minimal failed-login context without inventing a persistent actor."""
        identifier, now = str(uuid.uuid4()), datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO audit_events(id,occurred_at,actor_user_id,
                   actor_username_snapshot,actor_display_name_snapshot,actor_role_snapshot,
                   action_type,resource_type,request_id,metadata_json,created_at)
                   VALUES(?,?,NULL,?,?,?,?,'authentication',?,?,?)""",
                (identifier, now, attempted_username.strip()[:100] or "unknown",
                 "Unknown", "UNKNOWN", AuditAction.AUTH_LOGIN_FAILURE.value,
                 str(uuid.uuid4()), _json({"success": False}), now),
            )
        return identifier

    def record_optional(self, principal: Principal, action_type: AuditAction,
                        resource_type: str, **values: Any) -> str | None:
        """Best-effort envelope for non-critical reads/invocations.

        Operational success must not be converted into an error when a legacy
        test/runtime has not made optional audit storage available yet.
        """
        try:
            return self.record(principal, action_type, resource_type, **values)
        except (OSError, sqlite3.Error):
            logger.exception("Optional audit event could not be persisted action=%s", action_type)
            return None

    def query(self, *, actor_user_id: str | None = None, action_type: str | None = None,
              resource_type: str | None = None, resource_id: str | None = None,
              trip_key: str | None = None, date_from: str | None = None,
              date_to: str | None = None, limit: int = 100, cursor: str | None = None,
              operational_only: bool = False) -> dict[str, Any]:
        clauses, params = [], []
        for column, value in (("actor_user_id", actor_user_id), ("action_type", action_type),
                              ("resource_type", resource_type), ("resource_id", resource_id),
                              ("trip_key", trip_key)):
            if value is not None:
                clauses.append(f"{column}=?"); params.append(value)
        if date_from: clauses.append("occurred_at>=?"); params.append(date_from)
        if date_to: clauses.append("occurred_at<=?"); params.append(date_to)
        if cursor: clauses.append("id<?"); params.append(cursor)
        if operational_only:
            clauses.append("trip_key IS NOT NULL")
            clauses.append("resource_type NOT IN ('user','authentication','settings')")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM audit_events" + where + " ORDER BY occurred_at DESC,id DESC LIMIT ?",
                (*params, min(max(limit, 1), 250) + 1),
            ).fetchall()
        has_more = len(rows) > min(max(limit, 1), 250)
        rows = rows[:min(max(limit, 1), 250)]
        events = []
        for row in rows:
            item = dict(row)
            for field in ("before_json", "after_json", "metadata_json"):
                item[field.removesuffix("_json")] = json.loads(item.pop(field)) if item[field] else None
            events.append(item)
        return {"events": events, "next_cursor": events[-1]["id"] if has_more and events else None}
