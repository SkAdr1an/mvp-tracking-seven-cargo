from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.core.security import Principal
from app.services.audit import AuditAction, AuditService
from app.storage.operations import OperationsRepository


ARCHIVABLE_STATES = frozenset({"FINALIZADA_NO_SISTEMA", "RETORNO_CONCLUIDO", "CANCELADA"})


class TripLifecycleConflict(ValueError):
    pass


class TripLifecycleService:
    def __init__(self, repository: OperationsRepository) -> None:
        self.repository = repository
        self.audit = AuditService(repository.database_path)

    @staticmethod
    def _reason(value: str) -> str:
        reason = value.strip()
        if len(reason) < 5:
            raise ValueError("A justificativa deve ter pelo menos 5 caracteres")
        return reason

    def cancel(self, trip_key: str, reason: str, principal: Principal) -> dict[str, Any]:
        reason = self._reason(reason)
        now = datetime.now(timezone.utc).isoformat()
        with self.repository._lock, self.repository.connect() as connection:
            row = connection.execute(
                "SELECT * FROM operational_trips WHERE trip_key=?", (trip_key,)
            ).fetchone()
            if row is None:
                raise KeyError(trip_key)
            before = dict(row)
            if before.get("archived_at"):
                raise TripLifecycleConflict("Viagem arquivada não pode ser cancelada")
            if before["state"] == "CANCELADA":
                raise TripLifecycleConflict("Viagem já está cancelada")
            if before["state"] in {"FINALIZADA_NO_SISTEMA", "RETORNO_CONCLUIDO"}:
                raise TripLifecycleConflict("Viagem finalizada não pode ser cancelada")
            connection.execute(
                """UPDATE operational_trips
                   SET state='CANCELADA',cancelled_at=?,cancelled_by_user_id=?,
                       cancelled_reason=?,updated_at=? WHERE trip_key=?""",
                (now, principal.user_id, reason, now, trip_key),
            )
            connection.execute(
                """INSERT INTO operational_events(
                   trip_key,event_type,occurred_at,source,description,previous_state,
                   new_state,metadata_json,justification,operator,idempotency_key,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (trip_key, "TRIP_CANCELLED", now, "operator", "Viagem cancelada",
                 before["state"], "CANCELADA", json.dumps({"trafegus_mutated": False}),
                 reason, principal.username, f"trip-cancelled:{trip_key}", now),
            )
            links = connection.execute(
                "SELECT id FROM public_trip_links WHERE trip_key=? AND active=1", (trip_key,)
            ).fetchall()
            connection.execute(
                "UPDATE public_trip_links SET active=0,revoked_at=? WHERE trip_key=? AND active=1",
                (now, trip_key),
            )
            for link in links:
                connection.execute(
                    """INSERT INTO public_trip_link_events(
                       public_link_id,event_type,occurred_at,actor,metadata_json)
                       VALUES(?,?,?,?,?)""",
                    (link["id"], "TRIP_CANCELLED", now, principal.username, "{}"),
                )
            after = dict(connection.execute(
                "SELECT * FROM operational_trips WHERE trip_key=?", (trip_key,)
            ).fetchone())
            self.audit.record(
                principal, AuditAction.TRIP_CANCELLED, "trip", resource_id=trip_key,
                trip_key=trip_key, before=before, after=after, justification=reason,
                metadata={"revoked_public_links": len(links)}, connection=connection,
            )
        return self.repository._trip_from_mapping(after)

    def archive(self, trip_key: str, reason: str, principal: Principal) -> dict[str, Any]:
        return self._set_archive(trip_key, self._reason(reason), principal, archived=True)

    def unarchive(self, trip_key: str, reason: str, principal: Principal) -> dict[str, Any]:
        return self._set_archive(trip_key, self._reason(reason), principal, archived=False)

    def _set_archive(self, trip_key: str, reason: str, principal: Principal, *, archived: bool) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self.repository._lock, self.repository.connect() as connection:
            row = connection.execute(
                "SELECT * FROM operational_trips WHERE trip_key=?", (trip_key,)
            ).fetchone()
            if row is None:
                raise KeyError(trip_key)
            before = dict(row)
            if archived:
                if before.get("archived_at"):
                    raise TripLifecycleConflict("Viagem já está arquivada")
                if before["state"] not in ARCHIVABLE_STATES:
                    raise TripLifecycleConflict("Somente viagens encerradas podem ser arquivadas")
                fields = (now, principal.user_id, reason, now, trip_key)
                connection.execute(
                    """UPDATE operational_trips SET archived_at=?,archived_by_user_id=?,
                       archive_reason=?,updated_at=? WHERE trip_key=?""", fields,
                )
                action, event, description = AuditAction.TRIP_ARCHIVED, "TRIP_ARCHIVED", "Viagem arquivada"
            else:
                if not before.get("archived_at"):
                    raise TripLifecycleConflict("Viagem não está arquivada")
                connection.execute(
                    """UPDATE operational_trips SET archived_at=NULL,archived_by_user_id=NULL,
                       archive_reason=NULL,updated_at=? WHERE trip_key=?""", (now, trip_key),
                )
                action, event, description = AuditAction.TRIP_UNARCHIVED, "TRIP_UNARCHIVED", "Viagem desarquivada"
            connection.execute(
                """INSERT INTO operational_events(
                   trip_key,event_type,occurred_at,source,description,previous_state,new_state,
                   metadata_json,justification,operator,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (trip_key, event, now, "operator", description, before["state"], before["state"],
                 "{}", reason, principal.username, now),
            )
            after = dict(connection.execute(
                "SELECT * FROM operational_trips WHERE trip_key=?", (trip_key,)
            ).fetchone())
            self.audit.record(
                principal, action, "trip", resource_id=trip_key, trip_key=trip_key,
                before=before, after=after, justification=reason, connection=connection,
            )
        return self.repository._trip_from_mapping(after)
