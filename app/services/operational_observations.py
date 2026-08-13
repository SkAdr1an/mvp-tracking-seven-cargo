from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.core.security import Principal
from app.storage.sqlite_runtime import connect_existing_database


class ObservationType(StrEnum):
    GENERAL = "GENERAL"
    STOP = "STOP"
    DRIVER_CONTACT = "DRIVER_CONTACT"
    GR_INTERVENTION = "GR_INTERVENTION"
    INCIDENT = "INCIDENT"
    OPERATIONAL_NOTE = "OPERATIONAL_NOTE"


OBSERVATION_TYPE_LABELS = {
    ObservationType.GENERAL: "Observação geral",
    ObservationType.STOP: "Parada operacional",
    ObservationType.DRIVER_CONTACT: "Contato com motorista",
    ObservationType.GR_INTERVENTION: "Intervenção GR",
    ObservationType.INCIDENT: "Ocorrência observada",
    ObservationType.OPERATIONAL_NOTE: "Nota operacional",
}

ROLE_LABELS = {
    "ADMIN": "Administrador",
    "GR": "GR",
    "MONITORING": "Monitoramento",
}


class PersistentIdentityRequired(ValueError):
    pass


class ObservationConflict(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 4000:
        raise ValueError("Observation content must contain 1-4000 characters")
    return normalized


def _reason(value: str) -> str:
    normalized = value.strip()
    if not 5 <= len(normalized) <= 1000:
        raise ValueError("Reason must contain 5-1000 characters")
    return normalized


class OperationalObservationService:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(Path(database_path).resolve())

    def _connect(self) -> sqlite3.Connection:
        connection = connect_existing_database(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _persistent_actor(principal: Principal) -> str:
        if principal.user_id is None:
            raise PersistentIdentityRequired(
                "A persistent user identity is required for attributed observations"
            )
        return principal.user_id

    @staticmethod
    def _payload(row: sqlite3.Row) -> dict[str, Any]:
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else None
        return {
            "id": str(row["id"]),
            "trip_key": str(row["trip_key"]),
            "type": str(row["observation_type"]),
            "type_label": OBSERVATION_TYPE_LABELS[ObservationType(row["observation_type"])],
            "content": str(row["content"]),
            "occurred_at": str(row["occurred_at"]),
            "created_at": str(row["created_at"]),
            "status": str(row["status"]),
            "include_in_report": bool(row["include_in_report"]),
            "stop_id": row["stop_id"],
            "author": {
                "user_id": str(row["created_by_user_id"]),
                "username": str(row["author_username_snapshot"]),
                "display_name": str(row["author_display_name_snapshot"]),
                "role": str(row["author_role_snapshot"]),
                "role_label": ROLE_LABELS.get(
                    str(row["author_role_snapshot"]), str(row["author_role_snapshot"])
                ),
            },
            "correction": {
                "corrected_by_user_id": row["corrected_by_user_id"],
                "corrected_at": row["corrected_at"],
                "reason": row["correction_reason"],
                "supersedes_observation_id": row["supersedes_observation_id"],
            } if row["corrected_at"] or row["supersedes_observation_id"] else None,
            "void": {
                "voided_by_user_id": row["voided_by_user_id"],
                "voided_at": row["voided_at"],
                "reason": row["void_reason"],
            } if row["voided_at"] else None,
            "created_from": row["created_from"],
            "metadata": metadata,
        }

    @staticmethod
    def _trip_exists(connection: sqlite3.Connection, trip_key: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM operational_trips WHERE trip_key=?", (trip_key,)
        ).fetchone() is not None

    @staticmethod
    def _validate_stop(
        connection: sqlite3.Connection, trip_key: str, observation_type: ObservationType,
        stop_id: int | None,
    ) -> None:
        if observation_type is ObservationType.STOP and stop_id is None:
            raise ValueError("STOP observations require stop_id")
        if observation_type is not ObservationType.STOP and stop_id is not None:
            raise ValueError("stop_id is only valid for STOP observations")
        if stop_id is not None:
            row = connection.execute(
                "SELECT trip_key FROM operational_stops WHERE id=?", (stop_id,)
            ).fetchone()
            if row is None:
                raise KeyError("stop")
            if str(row[0]) != trip_key:
                raise ObservationConflict("Stop does not belong to the observation trip")

    @staticmethod
    def _insert(
        connection: sqlite3.Connection, *, identifier: str, trip_key: str,
        observation_type: ObservationType, content: str, occurred_at: str,
        principal: Principal, stop_id: int | None, include_in_report: bool,
        created_at: str, created_from: str, metadata: dict[str, Any] | None = None,
        supersedes_observation_id: str | None = None,
    ) -> None:
        assert principal.user_id is not None
        connection.execute(
            """INSERT INTO operational_observations(
               id,trip_key,observation_type,content,occurred_at,created_at,
               created_by_user_id,author_username_snapshot,author_display_name_snapshot,
               author_role_snapshot,stop_id,include_in_report,status,created_from,
               metadata_json,supersedes_observation_id
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'ACTIVE',?,?,?)""",
            (
                identifier, trip_key, observation_type.value, content, occurred_at, created_at,
                principal.user_id, principal.username, principal.display_name or principal.username,
                principal.role.value, stop_id, int(include_in_report), created_from,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True) if metadata else None,
                supersedes_observation_id,
            ),
        )

    def create(
        self, *, trip_key: str, observation_type: ObservationType, content: str,
        occurred_at: datetime, principal: Principal, stop_id: int | None = None,
        include_in_report: bool = True,
    ) -> dict[str, Any]:
        self._persistent_actor(principal)
        if occurred_at.tzinfo is None:
            raise ValueError("occurred_at must include timezone")
        identifier, created_at = str(uuid.uuid4()), utc_now()
        with self._connect() as connection:
            if not self._trip_exists(connection, trip_key):
                raise KeyError("trip")
            self._validate_stop(connection, trip_key, observation_type, stop_id)
            self._insert(
                connection, identifier=identifier, trip_key=trip_key,
                observation_type=observation_type, content=_content(content),
                occurred_at=occurred_at.astimezone(timezone.utc).isoformat(), principal=principal,
                stop_id=stop_id, include_in_report=include_in_report, created_at=created_at,
                created_from="PANEL",
            )
            row = connection.execute(
                "SELECT * FROM operational_observations WHERE id=?", (identifier,)
            ).fetchone()
            assert row is not None
            return self._payload(row)

    def list_for_trip(
        self, trip_key: str, *, active_report_only: bool = False,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if not self._trip_exists(connection, trip_key):
                raise KeyError("trip")
            condition = " AND status='ACTIVE' AND include_in_report=1" if active_report_only else ""
            rows = connection.execute(
                "SELECT * FROM operational_observations WHERE trip_key=?" + condition
                + " ORDER BY occurred_at,created_at,id",
                (trip_key,),
            ).fetchall()
            return [self._payload(row) for row in rows]

    def correct(
        self, observation_id: str, *, content: str, reason: str, principal: Principal,
    ) -> dict[str, Any]:
        actor_id = self._persistent_actor(principal)
        now, identifier = utc_now(), str(uuid.uuid4())
        with self._connect() as connection:
            original = connection.execute(
                "SELECT * FROM operational_observations WHERE id=?", (observation_id,)
            ).fetchone()
            if original is None:
                raise KeyError("observation")
            if str(original["status"]) != "ACTIVE":
                raise ObservationConflict("Only active observations can be corrected")
            if str(original["created_by_user_id"]) != actor_id:
                raise PermissionError("Only the original author can correct this observation")
            cursor = connection.execute(
                """UPDATE operational_observations SET status='CORRECTED',
                   corrected_by_user_id=?,corrected_at=?,correction_reason=?
                   WHERE id=? AND status='ACTIVE' AND created_by_user_id=?""",
                (actor_id, now, _reason(reason), observation_id, actor_id),
            )
            if cursor.rowcount != 1:
                raise ObservationConflict("Observation changed concurrently")
            self._insert(
                connection, identifier=identifier, trip_key=str(original["trip_key"]),
                observation_type=ObservationType(original["observation_type"]),
                content=_content(content), occurred_at=str(original["occurred_at"]),
                principal=principal, stop_id=original["stop_id"],
                include_in_report=bool(original["include_in_report"]), created_at=now,
                created_from="CORRECTION", metadata={"corrected_from": observation_id},
                supersedes_observation_id=observation_id,
            )
            current = connection.execute(
                "SELECT * FROM operational_observations WHERE id=?", (identifier,)
            ).fetchone()
            previous = connection.execute(
                "SELECT * FROM operational_observations WHERE id=?", (observation_id,)
            ).fetchone()
            assert current is not None and previous is not None
            return {"original": self._payload(previous), "observation": self._payload(current)}

    def void(self, observation_id: str, *, reason: str, principal: Principal) -> dict[str, Any]:
        actor_id = self._persistent_actor(principal)
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE operational_observations SET status='VOIDED',
                   voided_by_user_id=?,voided_at=?,void_reason=? WHERE id=? AND status='ACTIVE'""",
                (actor_id, now, _reason(reason), observation_id),
            )
            if cursor.rowcount != 1:
                row = connection.execute(
                    "SELECT status FROM operational_observations WHERE id=?", (observation_id,)
                ).fetchone()
                if row is None:
                    raise KeyError("observation")
                raise ObservationConflict("Only active observations can be voided")
            row = connection.execute(
                "SELECT * FROM operational_observations WHERE id=?", (observation_id,)
            ).fetchone()
            assert row is not None
            return self._payload(row)
