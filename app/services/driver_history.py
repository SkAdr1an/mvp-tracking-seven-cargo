from __future__ import annotations

import html
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.storage.operations import OperationsRepository
from app.storage.feature_migrations import migration_009_pending


FINAL_STATES = {"FINALIZADA_NO_SISTEMA", "RETORNO_CONCLUIDO"}
NEGATIVE_VALUES = {"ruim", "nao_cumpriu", "nao_conforme", "com_ressalvas", "nao_recomendado"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DriverHistoryService:
    """Internal, idempotent history. Reads never call Trafegus or another provider."""

    def __init__(self, repository: OperationsRepository) -> None:
        self.repository = repository

    def available(self) -> bool:
        return not migration_009_pending(self.repository.database_path)

    def backfill_internal_trips(self) -> int:
        """Idempotently imports old local trips; it never reaches an external integration."""
        count = 0
        for trip in self.repository.trips():
            if self.sync_trip(trip["trip_key"], source="internal:backfill"):
                count += 1
        self._reconcile_evidenced_identities()
        return count

    def sync_trip(self, trip_key: str, *, source: str = "internal") -> dict[str, Any] | None:
        if not self.available():
            return None
        trip = self.repository.trip(trip_key)
        if not trip or not (trip.get("current_driver") or "").strip():
            return None
        name, now = trip["current_driver"].strip(), _now()
        route = self.repository.route(trip["route_id"]) if trip.get("route_id") else None
        diagnostic = self.repository.diagnostic(trip_key)
        with self.repository.connect() as connection:
            plan = connection.execute("SELECT * FROM trip_plans WHERE trip_key=?", (trip_key,)).fetchone()
        plan = dict(plan) if plan else {}
        scheduled_arrival = (plan.get("customer_commitment_at") or plan.get("scheduled_arrival_at")
                             or (diagnostic or {}).get("client_eta_at"))
        delay = self._punctuality_delay(trip.get("arrived_destination_at") or trip.get("finished_at"),
                                        scheduled_arrival,
                                        (diagnostic or {}).get("commitment_delta_minutes"))
        punctuality = "UNAVAILABLE" if delay is None else ("LATE" if delay > 0 else "ON_TIME")
        closed = int(trip.get("state") in FINAL_STATES)
        with self.repository._lock, self.repository.connect() as connection:
            existing = connection.execute("SELECT driver_id FROM driver_trip_history WHERE trip_key=?", (trip_key,)).fetchone()
            driver_id = existing["driver_id"] if existing else "drv_" + uuid.uuid4().hex
            if not existing:
                connection.execute(
                    "INSERT INTO driver_profiles(id,name,identity_status,created_at,updated_at) VALUES(?,?,?,?,?)",
                    (driver_id, name, "PENDING", now, now),
                )
            connection.execute(
                """INSERT INTO driver_trip_history(
                   trip_key,driver_id,provider_trip_id,plate,trailer_plate,route_id,route_name,
                   origin_name,destination_name,status,source_created_at,loaded_at,started_at,
                   scheduled_arrival_at,eta_at,arrived_destination_at,finished_at,package_count,
                   responsible,driver_source,source,source_updated_at,automatic_punctuality,
                   automatic_delay_minutes,closed,consolidated_at,consolidation_version,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(trip_key) DO UPDATE SET
                   driver_id=excluded.driver_id,provider_trip_id=excluded.provider_trip_id,
                   plate=excluded.plate,trailer_plate=excluded.trailer_plate,route_id=excluded.route_id,
                   route_name=excluded.route_name,origin_name=excluded.origin_name,
                   destination_name=excluded.destination_name,status=excluded.status,
                   source_created_at=excluded.source_created_at,loaded_at=excluded.loaded_at,
                   started_at=excluded.started_at,scheduled_arrival_at=excluded.scheduled_arrival_at,
                   eta_at=excluded.eta_at,arrived_destination_at=excluded.arrived_destination_at,
                   finished_at=excluded.finished_at,package_count=COALESCE(excluded.package_count,driver_trip_history.package_count),
                   responsible=COALESCE(excluded.responsible,driver_trip_history.responsible),
                   driver_source=excluded.driver_source,
                   source=excluded.source,source_updated_at=excluded.source_updated_at,
                   automatic_punctuality=excluded.automatic_punctuality,
                   automatic_delay_minutes=excluded.automatic_delay_minutes,
                   closed=excluded.closed,
                   consolidation_version=excluded.consolidation_version,
                   consolidated_at=CASE WHEN excluded.closed=1 THEN COALESCE(driver_trip_history.consolidated_at,excluded.consolidated_at) ELSE NULL END,
                   updated_at=excluded.updated_at""",
                (trip_key, driver_id, trip.get("provider_trip_id"), trip["plate"], trip.get("trailer_plate"),
                 trip.get("route_id"), route.get("name") if route else None,
                 route.get("origin_name") if route else None, route.get("destination_name") if route else None,
                 trip["state"], trip.get("created_at"), trip.get("loaded_at"), trip.get("started_at"),
                 scheduled_arrival, (diagnostic or {}).get("eta_at"), trip.get("arrived_destination_at"),
                 trip.get("finished_at"), None, plan.get("updated_by"), trip.get("driver_source"), source,
                 trip.get("updated_at") or now, punctuality, delay, closed, now if closed else None, 2, now, now),
            )
            row = connection.execute("SELECT * FROM driver_trip_history WHERE trip_key=?", (trip_key,)).fetchone()
        return dict(row)

    @staticmethod
    def _punctuality_delay(actual: str | None, scheduled: str | None, fallback: float | None) -> float | None:
        if actual and scheduled:
            try:
                return round((datetime.fromisoformat(actual) - datetime.fromisoformat(scheduled)).total_seconds() / 60, 1)
            except ValueError:
                pass
        return fallback

    def _reconcile_evidenced_identities(self) -> None:
        """Merge pending duplicates only with name + plate + provider association evidence."""
        now = _now()
        with self.repository._lock, self.repository.connect() as connection:
            groups = connection.execute(
                """SELECT lower(trim(d.name)) name_key,h.plate,h.driver_source,MIN(d.id) canonical_id,COUNT(DISTINCT d.id) profiles
                FROM driver_profiles d JOIN driver_trip_history h ON h.driver_id=d.id
                WHERE d.identity_status='PENDING' AND d.cpf IS NULL AND d.phone IS NULL
                  AND h.driver_source IS NOT NULL AND trim(h.driver_source)<>''
                GROUP BY lower(trim(d.name)),h.plate,h.driver_source HAVING COUNT(DISTINCT d.id)>1"""
            ).fetchall()
            for group in groups:
                rows = connection.execute(
                    """SELECT h.trip_key,h.driver_id FROM driver_trip_history h JOIN driver_profiles d ON d.id=h.driver_id
                    WHERE lower(trim(d.name))=? AND h.plate=? AND h.driver_source=? AND h.driver_id<>?""",
                    (group["name_key"], group["plate"], group["driver_source"], group["canonical_id"]),
                ).fetchall()
                for row in rows:
                    connection.execute("UPDATE driver_trip_history SET driver_id=?,updated_at=? WHERE trip_key=?",
                                       (group["canonical_id"], now, row["trip_key"]))
                    connection.execute("UPDATE driver_evaluations SET driver_id=?,updated_at=? WHERE trip_key=?",
                                       (group["canonical_id"], now, row["trip_key"]))
                    if not connection.execute(
                        "SELECT 1 FROM driver_identity_links WHERE trip_key=? AND previous_driver_id=? AND new_driver_id=? AND source='internal:backfill:v2'",
                        (row["trip_key"], row["driver_id"], group["canonical_id"]),
                    ).fetchone():
                        connection.execute(
                            "INSERT INTO driver_identity_links(trip_key,previous_driver_id,new_driver_id,source,justification,responsible,created_at) VALUES(?,?,?,?,?,?,?)",
                            (row["trip_key"], row["driver_id"], group["canonical_id"], "internal:backfill:v2",
                             "Mesma associação de origem, nome exato e placa", "system:consolidation", now),
                        )
                    connection.execute(
                        """DELETE FROM driver_profiles WHERE id=? AND identity_status='PENDING' AND cpf IS NULL AND phone IS NULL
                        AND NOT EXISTS(SELECT 1 FROM driver_trip_history h WHERE h.driver_id=driver_profiles.id)
                        AND NOT EXISTS(SELECT 1 FROM driver_evaluations e WHERE e.driver_id=driver_profiles.id)
                        AND NOT EXISTS(SELECT 1 FROM driver_internal_notes n WHERE n.driver_id=driver_profiles.id)""",
                        (row["driver_id"],),
                    )

    def update_profile(self, driver_id: str, *, cpf: str | None, phone: str | None, name: str | None) -> dict[str, Any]:
        with self.repository._lock, self.repository.connect() as connection:
            current = connection.execute("SELECT * FROM driver_profiles WHERE id=?", (driver_id,)).fetchone()
            if not current:
                raise KeyError(driver_id)
            clean_cpf = re.sub(r"\D", "", cpf or "") or None
            if clean_cpf and len(clean_cpf) != 11:
                raise ValueError("CPF deve conter 11 dígitos")
            connection.execute(
                "UPDATE driver_profiles SET cpf=?,phone=?,name=?,identity_status=?,updated_at=? WHERE id=?",
                (clean_cpf, (phone or "").strip() or None, (name or current["name"]).strip(), "VERIFIED" if clean_cpf else "PENDING", _now(), driver_id),
            )
            row = connection.execute("SELECT * FROM driver_profiles WHERE id=?", (driver_id,)).fetchone()
        return self._safe_profile(dict(row))

    def drivers(self, *, search: str = "", page: int = 1, page_size: int = 25) -> dict[str, Any]:
        term = f"%{search.strip()}%"
        where = """WHERE (?='' OR d.name LIKE ? OR d.cpf LIKE ? OR d.phone LIKE ? OR EXISTS(
            SELECT 1 FROM driver_trip_history h WHERE h.driver_id=d.id AND h.plate LIKE ?))"""
        params = (search.strip(), term, term, term, term)
        with self.repository.connect() as connection:
            total = connection.execute(f"SELECT COUNT(*) FROM driver_profiles d {where}", params).fetchone()[0]
            rows = connection.execute(
                f"""SELECT d.*,COUNT(h.trip_key) total_trips,
                SUM(CASE WHEN h.closed=1 THEN 1 ELSE 0 END) finished_trips,
                SUM(CASE WHEN h.closed=0 THEN 1 ELSE 0 END) active_trips,
                SUM(CASE WHEN h.closed=1 AND e.id IS NULL THEN 1 ELSE 0 END) pending_evaluations,
                MAX(COALESCE(h.finished_at,h.started_at,h.created_at)) last_trip_at
                FROM driver_profiles d LEFT JOIN driver_trip_history h ON h.driver_id=d.id
                LEFT JOIN driver_evaluations e ON e.trip_key=h.trip_key {where}
                GROUP BY d.id ORDER BY last_trip_at DESC,d.name LIMIT ? OFFSET ?""",
                (*params, page_size, (page - 1) * page_size),
            ).fetchall()
        return {"items": [self._safe_profile(dict(row)) for row in rows], "page": page, "page_size": page_size, "total": total}

    def profile(self, driver_id_or_cpf: str) -> dict[str, Any]:
        value = re.sub(r"\D", "", driver_id_or_cpf) if not driver_id_or_cpf.startswith("drv_") else driver_id_or_cpf
        with self.repository.connect() as connection:
            driver = connection.execute("SELECT * FROM driver_profiles WHERE id=? OR cpf=?", (driver_id_or_cpf, value)).fetchone()
            if not driver:
                raise KeyError(driver_id_or_cpf)
            driver_id = driver["id"]
            totals = connection.execute(
                """SELECT COUNT(*) total_trips,SUM(closed=1) finished_trips,SUM(closed=0) active_trips,
                SUM(status='CANCELADA') cancelled_trips,
                SUM(closed=1 AND e.id IS NULL) pending_evaluations,
                SUM(automatic_punctuality='ON_TIME') automatic_on_time,
                SUM(COALESCE(considered_punctuality,automatic_punctuality)='ON_TIME') considered_on_time
                FROM driver_trip_history h LEFT JOIN driver_evaluations e ON e.trip_key=h.trip_key WHERE h.driver_id=?""",
                (driver_id,),
            ).fetchone()
            routes = connection.execute("SELECT route_name,COUNT(*) trips FROM driver_trip_history WHERE driver_id=? AND route_name IS NOT NULL GROUP BY route_name ORDER BY trips DESC", (driver_id,)).fetchall()
            customers = connection.execute("SELECT customer,COUNT(*) trips FROM driver_trip_history WHERE driver_id=? AND customer IS NOT NULL GROUP BY customer ORDER BY trips DESC", (driver_id,)).fetchall()
            evaluations = connection.execute("SELECT * FROM driver_evaluations WHERE driver_id=? ORDER BY created_at DESC", (driver_id,)).fetchall()
            notes = connection.execute("SELECT * FROM driver_internal_notes WHERE driver_id=? ORDER BY created_at DESC", (driver_id,)).fetchall()
        total = int(totals["total_trips"] or 0)
        result = self._safe_profile(dict(driver))
        result.update(dict(totals))
        result["automatic_punctuality_percent"] = round(100 * int(totals["automatic_on_time"] or 0) / total, 1) if total else None
        result["considered_punctuality_percent"] = round(100 * int(totals["considered_on_time"] or 0) / total, 1) if total else None
        result["routes"] = [dict(row) for row in routes]
        result["customers"] = [dict(row) for row in customers]
        result["evaluations"] = [dict(row) for row in evaluations]
        result["notes"] = [dict(row) for row in notes]
        return result

    @staticmethod
    def _safe_profile(value: dict[str, Any]) -> dict[str, Any]:
        cpf = value.pop("cpf", None)
        value["cpf_masked"] = f"***.***.***-{cpf[-2:]}" if cpf else None
        return value

    def link_identity(self, trip_key: str, *, target_driver_id: str | None, cpf: str | None,
                      name: str, source: str, justification: str, responsible: str) -> dict[str, Any]:
        clean_cpf = re.sub(r"\D", "", cpf or "") or None
        if clean_cpf and len(clean_cpf) != 11: raise ValueError("CPF deve conter 11 dígitos")
        if len(justification.strip()) < 5: raise ValueError("Justificativa é obrigatória")
        now = _now()
        with self.repository._lock, self.repository.connect() as connection:
            trip = connection.execute("SELECT * FROM driver_trip_history WHERE trip_key=?", (trip_key,)).fetchone()
            if not trip: raise KeyError(trip_key)
            previous = trip["driver_id"]
            target = None
            if target_driver_id:
                target = connection.execute("SELECT * FROM driver_profiles WHERE id=?", (target_driver_id,)).fetchone()
            elif clean_cpf:
                target = connection.execute("SELECT * FROM driver_profiles WHERE cpf=?", (clean_cpf,)).fetchone()
            if target:
                new_id = target["id"]
                if clean_cpf and target["cpf"] != clean_cpf: raise ValueError("CPF já vinculado a outra identidade")
                connection.execute("UPDATE driver_profiles SET name=?,phone=phone,identity_status='VERIFIED',updated_at=? WHERE id=?", (name.strip(), now, new_id))
            else:
                new_id = "drv_" + uuid.uuid4().hex
                connection.execute("INSERT INTO driver_profiles(id,cpf,name,identity_status,created_at,updated_at) VALUES(?,?,?,?,?,?)", (new_id, clean_cpf, name.strip(), "VERIFIED" if clean_cpf else "PENDING", now, now))
            connection.execute("UPDATE driver_trip_history SET driver_id=?,updated_at=? WHERE trip_key=?", (new_id, now, trip_key))
            connection.execute("INSERT INTO driver_identity_links(trip_key,previous_driver_id,new_driver_id,source,justification,responsible,created_at) VALUES(?,?,?,?,?,?,?)", (trip_key, previous, new_id, source, justification.strip(), responsible, now))
        return self.profile(new_id)

    def correct_trip_metadata(self, trip_key: str, *, customer: str | None,
                              evaluation_responsible: str | None, justification: str, responsible: str) -> dict[str, Any]:
        if len(justification.strip()) < 5: raise ValueError("Justificativa é obrigatória")
        now = _now()
        updates = {"customer": (customer or "").strip() or None,
                   "evaluation_responsible": (evaluation_responsible or "").strip() or None}
        with self.repository._lock, self.repository.connect() as connection:
            trip = connection.execute("SELECT * FROM driver_trip_history WHERE trip_key=?", (trip_key,)).fetchone()
            if not trip: raise KeyError(trip_key)
            for field, value in updates.items():
                if trip[field] != value:
                    connection.execute("INSERT INTO driver_trip_history_changes(trip_key,field_name,previous_value,new_value,responsible,justification,created_at) VALUES(?,?,?,?,?,?,?)", (trip_key, field, trip[field], value, responsible, justification.strip(), now))
            connection.execute("UPDATE driver_trip_history SET customer=?,evaluation_responsible=?,updated_at=? WHERE trip_key=?", (updates["customer"], updates["evaluation_responsible"], now, trip_key))
            row = connection.execute("SELECT * FROM driver_trip_history WHERE trip_key=?", (trip_key,)).fetchone()
        return dict(row)

    def trips(self, driver_id: str, *, start: str | None = None, end: str | None = None,
              route: str | None = None, customer: str | None = None, status: str | None = None,
              page: int = 1, page_size: int = 25) -> dict[str, Any]:
        clauses, params = ["h.driver_id=?"], [driver_id]
        for condition, value in (("COALESCE(h.finished_at,h.started_at)>=?", start), ("COALESCE(h.finished_at,h.started_at)<=?", end),
                                 ("(h.route_id=? OR h.route_name=?)", route), ("h.customer=?", customer), ("h.status=?", status)):
            if value:
                clauses.append(condition); params.extend([value, value] if condition.count("?")==2 else [value])
        where = " AND ".join(clauses)
        with self.repository.connect() as connection:
            total = connection.execute(f"SELECT COUNT(*) FROM driver_trip_history h WHERE {where}", params).fetchone()[0]
            rows = connection.execute(
                f"""SELECT h.*,CASE WHEN e.id IS NULL AND h.closed=1 THEN 'PENDING' WHEN e.id IS NOT NULL THEN 'COMPLETED' ELSE 'NOT_APPLICABLE' END evaluation_status
                FROM driver_trip_history h LEFT JOIN driver_evaluations e ON e.trip_key=h.trip_key
                WHERE {where} ORDER BY COALESCE(h.finished_at,h.started_at,h.created_at) DESC LIMIT ? OFFSET ?""",
                (*params, page_size, (page - 1) * page_size),
            ).fetchall()
        return {"items": [dict(row) for row in rows], "page": page, "page_size": page_size, "total": total}

    def pending(self, *, overdue_hours: int = 24, page: int = 1, page_size: int = 25,
                responsible: str | None = None, start: str | None = None, end: str | None = None,
                customer: str | None = None, route: str | None = None, overdue: bool | None = None) -> dict[str, Any]:
        clauses, params = ["h.closed=1", "e.id IS NULL"], []
        for condition, value in (("h.finished_at>=?", start), ("h.finished_at<=?", end), ("h.customer=?", customer), ("h.route_id=?", route)):
            if value: clauses.append(condition); params.append(value)
        if responsible: clauses.append("h.evaluation_responsible=?"); params.append(responsible)
        if overdue is not None: clauses.append("((julianday('now')-julianday(h.finished_at))*24>=?)" if overdue else "((julianday('now')-julianday(h.finished_at))*24<?)"); params.append(overdue_hours)
        where = " AND ".join(clauses)
        with self.repository.connect() as connection:
            total = connection.execute(f"SELECT COUNT(*) FROM driver_trip_history h LEFT JOIN driver_evaluations e ON e.trip_key=h.trip_key WHERE {where}", params).fetchone()[0]
            rows = connection.execute(
                f"""SELECT h.*,d.name driver_name,COALESCE(h.evaluation_responsible,'Não informado') responsible,
                CAST(MAX(0,(julianday('now')-julianday(h.finished_at))*24) AS INTEGER) pending_hours,
                CASE WHEN (julianday('now')-julianday(h.finished_at))*24>=? THEN 'OVERDUE' ELSE 'PENDING' END situation
                FROM driver_trip_history h JOIN driver_profiles d ON d.id=h.driver_id
                LEFT JOIN driver_evaluations e ON e.trip_key=h.trip_key WHERE {where}
                ORDER BY h.finished_at LIMIT ? OFFSET ?""", (overdue_hours, *params, page_size, (page-1)*page_size)).fetchall()
        return {"items": [dict(row) for row in rows], "page": page, "page_size": page_size, "total": total, "overdue_hours": overdue_hours}

    def evaluate(self, trip_key: str, values: dict[str, Any], responsible: str) -> dict[str, Any]:
        now = _now()
        if any(str(values.get(key, "")).casefold() in NEGATIVE_VALUES for key in
               ("communication", "procedures", "tracking_collaboration", "time_mark", "professional_behavior", "recommendation")) and len((values.get("justification") or "").strip()) < 5:
            raise ValueError("Justificativa é obrigatória para avaliação negativa ou com ressalvas")
        with self.repository._lock, self.repository.connect() as connection:
            history = connection.execute("SELECT * FROM driver_trip_history WHERE trip_key=?", (trip_key,)).fetchone()
            if not history or not history["closed"]: raise ValueError("A viagem precisa estar finalizada e consolidada")
            previous = connection.execute("SELECT * FROM driver_evaluations WHERE trip_key=?", (trip_key,)).fetchone()
            if previous: raise ValueError("Esta viagem já possui avaliação")
            columns = ("communication", "procedures", "tracking_collaboration", "time_mark", "professional_behavior", "recommendation")
            if any(not values.get(column) for column in columns): raise ValueError("Preencha todos os campos da avaliação")
            cursor = connection.execute(
                """INSERT INTO driver_evaluations(trip_key,driver_id,communication,procedures,tracking_collaboration,time_mark,professional_behavior,recommendation,internal_note,justification,responsible,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (trip_key, history["driver_id"], *(values[column] for column in columns), values.get("internal_note"), values.get("justification"), responsible, now, now))
            evaluation_id = cursor.lastrowid
            row = connection.execute("SELECT * FROM driver_evaluations WHERE id=?", (evaluation_id,)).fetchone()
            connection.execute("INSERT INTO driver_evaluation_history(evaluation_id,changed_by,changed_at,current_json) VALUES(?,?,?,?)", (evaluation_id, responsible, now, str(dict(row))))
        return dict(row)

    def adjust_punctuality(self, trip_key: str, considered: str, category: str, reason: str,
                           justification: str, evidence: str | None, responsible: str) -> dict[str, Any]:
        if len(justification.strip()) < 5: raise ValueError("Justificativa é obrigatória")
        now = _now()
        with self.repository._lock, self.repository.connect() as connection:
            trip = connection.execute("SELECT * FROM driver_trip_history WHERE trip_key=?", (trip_key,)).fetchone()
            if not trip: raise KeyError(trip_key)
            cursor = connection.execute("""INSERT INTO punctuality_adjustments(trip_key,original_value,considered_value,category,reason,justification,evidence,responsible,created_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                (trip_key, trip["automatic_punctuality"], considered, category, reason.strip(), justification.strip(), evidence, responsible, now))
            connection.execute("UPDATE driver_trip_history SET considered_punctuality=?,updated_at=? WHERE trip_key=?", (considered, now, trip_key))
            row = connection.execute("SELECT * FROM punctuality_adjustments WHERE id=?", (cursor.lastrowid,)).fetchone()
        return dict(row)

    def add_note(self, driver_id: str, note: str, responsible: str) -> dict[str, Any]:
        if len(note.strip()) < 3: raise ValueError("Observação muito curta")
        with self.repository._lock, self.repository.connect() as connection:
            if not connection.execute("SELECT 1 FROM driver_profiles WHERE id=?", (driver_id,)).fetchone(): raise KeyError(driver_id)
            cursor = connection.execute("INSERT INTO driver_internal_notes(driver_id,note,responsible,created_at) VALUES(?,?,?,?)", (driver_id, note.strip(), responsible, _now()))
            row = connection.execute("SELECT * FROM driver_internal_notes WHERE id=?", (cursor.lastrowid,)).fetchone()
        return dict(row)

    def report_html(self, driver_id: str, trips: list[dict[str, Any]], *, include_sensitive: bool = False,
                    filters: dict[str, str | None] | None = None) -> str:
        profile = self.profile(driver_id)
        trip_keys = [trip["trip_key"] for trip in trips]
        events: list[dict[str, Any]] = []
        evaluations: list[dict[str, Any]] = []
        if trip_keys:
            placeholders = ",".join("?" for _ in trip_keys)
            with self.repository.connect() as connection:
                events = [dict(row) for row in connection.execute(
                    f"SELECT trip_key,event_type,occurred_at,description,operator,justification FROM operational_events WHERE trip_key IN ({placeholders}) ORDER BY occurred_at", trip_keys).fetchall()]
                evaluations = [dict(row) for row in connection.execute(
                    f"SELECT * FROM driver_evaluations WHERE trip_key IN ({placeholders}) ORDER BY created_at", trip_keys).fetchall()]

        def shown(value: Any) -> str:
            return html.escape(str(value)) if value not in (None, "", "—", "UNAVAILABLE") else "Não informado"

        def date(value: str | None) -> str:
            if not value:
                return "Não informado"
            try:
                return datetime.fromisoformat(value).astimezone().strftime("%d/%m/%Y %H:%M")
            except ValueError:
                return shown(value)

        def punctuality(value: str | None) -> str:
            return {"UNAVAILABLE": "Não disponível", "ON_TIME": "No prazo", "LATE": "Atrasada"}.get(value or "", shown(value))

        def trip_events(trip: dict[str, Any]) -> str:
            related = [event for event in events if event["trip_key"] == trip["trip_key"]]
            return "".join(f"<li>{date(event['occurred_at'])} · {shown(event['description'])}</li>" for event in related) or "<li>Não informado</li>"

        def trip_evaluations(trip: dict[str, Any]) -> str:
            related = [evaluation for evaluation in evaluations if evaluation["trip_key"] == trip["trip_key"]]
            return "".join(
                f"<li>{shown(item['recommendation'])} · responsável: {shown(item['responsible'])} · {date(item['created_at'])}"
                + (f" · observação: {shown(item['internal_note'])}" if include_sensitive and item.get("internal_note") else "") + "</li>"
                for item in related
            ) or "<li>Nenhuma avaliação registrada.</li>"

        cards = []
        for trip in trips:
            number = shown(trip.get("provider_trip_id") or trip["trip_key"])
            reference_date = trip.get("loaded_at") or trip.get("started_at") or trip.get("arrived_destination_at") or trip.get("finished_at") or trip.get("source_created_at")
            operation = trip.get("customer") or trip.get("route_name")
            cards.append(f"""<section class='trip'><h2>Viagem {number}</h2><table>
            <tr><th>Data de referência</th><td>{date(reference_date)}</td><th>Status</th><td>{shown(trip.get('status'))}</td></tr>
            <tr><th>Origem</th><td>{shown(trip.get('origin_name'))}</td><th>Destino</th><td>{shown(trip.get('destination_name'))}</td></tr>
            <tr><th>Cliente/operação</th><td>{shown(operation)}</td><th>Pacotes</th><td>{shown(trip.get('package_count'))}</td></tr>
            <tr><th>Placa</th><td>{shown(trip.get('plate'))}</td><th>Implemento</th><td>{shown(trip.get('trailer_plate'))}</td></tr>
            <tr><th>Carregamento</th><td>{date(trip.get('loaded_at'))}</td><th>Início</th><td>{date(trip.get('started_at'))}</td></tr>
            <tr><th>Previsão de chegada</th><td>{date(trip.get('scheduled_arrival_at') or trip.get('eta_at'))}</td><th>Chegada real</th><td>{date(trip.get('arrived_destination_at'))}</td></tr>
            <tr><th>Término</th><td>{date(trip.get('finished_at'))}</td><th>Responsável</th><td>{shown(trip.get('evaluation_responsible') or trip.get('responsible'))}</td></tr>
            <tr><th>Pontualidade calculada</th><td>{punctuality(trip.get('automatic_punctuality'))}</td><th>Pontualidade considerada</th><td>{punctuality(trip.get('considered_punctuality') or trip.get('automatic_punctuality'))}</td></tr>
            </table><h3>Ocorrências</h3><ul>{trip_events(trip)}</ul><h3>Avaliações e observações</h3><ul>{trip_evaluations(trip)}</ul></section>""")
        earliest = min((trip.get("source_created_at") for trip in trips if trip.get("source_created_at")), default=None)
        latest = max((trip.get("finished_at") or trip.get("source_updated_at") for trip in trips if trip.get("finished_at") or trip.get("source_updated_at")), default=None)
        start_filter, end_filter = (filters or {}).get("início"), (filters or {}).get("fim")
        period = f"{date(start_filter or earliest)} a {date(end_filter or latest)}" if trips else "Não informado"
        count_label = "1 viagem" if len(trips) == 1 else f"{len(trips)} viagens"
        identity = " · ".join(value for value in (profile.get("cpf_masked"), profile.get("phone")) if value) or "CPF e telefone não informados"
        notes = "" if not include_sensitive else "<h2>Observações internas do motorista</h2><ul>" + "".join(f"<li>{shown(n['note'])}</li>" for n in profile["notes"]) + "</ul>"
        return f"""<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><style>@page{{size:A4;margin:11mm}}body{{font:12px Arial;color:#172033}}header{{background:#12395b;color:#fff;padding:22px}}header h1{{margin:8px 0}}.internal-id{{font-size:9px;opacity:.65}}.summary{{display:flex;gap:22px;padding:12px 0}}.trip{{break-inside:avoid;margin:14px 0 20px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:7px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}}th{{width:20%;background:#f4f0df}}h2{{color:#12395b}}h3{{margin-bottom:4px}}small{{opacity:.75}}</style></head><body><header><small>SEVEN CARGO · HISTÓRICO OPERACIONAL</small><h1>{shown(profile['name'])}</h1><p>{shown(identity)}</p><p class='internal-id'>Referência interna: {shown(profile['id'])}</p></header><div class='summary'><strong>Período consultado: {period}</strong><strong>Total: {count_label}</strong></div>{''.join(cards) or '<p>Nenhuma viagem no período.</p>'}{notes}<footer><p>Documento gerado sob demanda com os dados disponíveis na fonte operacional interna. Campos não armazenados são apresentados como “Não informado”.</p></footer></body></html>"""
