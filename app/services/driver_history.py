from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.storage.operations import OperationsRepository


FINAL_STATES = {"FINALIZADA_NO_SISTEMA", "RETORNO_CONCLUIDO"}
NEGATIVE_VALUES = {"ruim", "nao_cumpriu", "nao_conforme", "com_ressalvas", "nao_recomendado"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _driver_id(name: str) -> str:
    normalized = re.sub(r"\s+", " ", name.strip().casefold())
    return "drv_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


class DriverHistoryService:
    """Internal, idempotent history. Reads never call Trafegus or another provider."""

    def __init__(self, repository: OperationsRepository) -> None:
        self.repository = repository

    def backfill_internal_trips(self) -> int:
        """Idempotently imports old local trips; it never reaches an external integration."""
        count = 0
        for trip in self.repository.trips():
            if self.sync_trip(trip["trip_key"], source="internal:backfill"):
                count += 1
        return count

    def sync_trip(self, trip_key: str, *, source: str = "internal") -> dict[str, Any] | None:
        trip = self.repository.trip(trip_key)
        if not trip or not (trip.get("current_driver") or "").strip():
            return None
        name = trip["current_driver"].strip()
        driver_id, now = _driver_id(name), _now()
        route = self.repository.route(trip["route_id"]) if trip.get("route_id") else None
        diagnostic = self.repository.diagnostic(trip_key)
        delay = diagnostic.get("commitment_delta_minutes") if diagnostic else None
        punctuality = "UNAVAILABLE" if delay is None else ("LATE" if delay > 0 else "ON_TIME")
        closed = int(trip.get("state") in FINAL_STATES)
        with self.repository._lock, self.repository.connect() as connection:
            connection.execute(
                """INSERT INTO driver_profiles(id,name,created_at,updated_at) VALUES(?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name,updated_at=excluded.updated_at""",
                (driver_id, name, now, now),
            )
            connection.execute(
                """INSERT INTO driver_trip_history(
                   trip_key,driver_id,provider_trip_id,plate,trailer_plate,route_id,route_name,
                   origin_name,destination_name,status,started_at,finished_at,source,source_updated_at,
                   automatic_punctuality,automatic_delay_minutes,closed,consolidated_at,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(trip_key) DO UPDATE SET
                   driver_id=excluded.driver_id,provider_trip_id=excluded.provider_trip_id,
                   plate=excluded.plate,trailer_plate=excluded.trailer_plate,route_id=excluded.route_id,
                   route_name=excluded.route_name,origin_name=excluded.origin_name,
                   destination_name=excluded.destination_name,status=excluded.status,
                   started_at=excluded.started_at,finished_at=excluded.finished_at,
                   source=excluded.source,source_updated_at=excluded.source_updated_at,
                   automatic_punctuality=excluded.automatic_punctuality,
                   automatic_delay_minutes=excluded.automatic_delay_minutes,
                   closed=excluded.closed,
                   consolidated_at=CASE WHEN excluded.closed=1 THEN COALESCE(driver_trip_history.consolidated_at,excluded.consolidated_at) ELSE NULL END,
                   updated_at=excluded.updated_at""",
                (trip_key, driver_id, trip.get("provider_trip_id"), trip["plate"], trip.get("trailer_plate"),
                 trip.get("route_id"), route.get("name") if route else None,
                 route.get("origin_name") if route else None, route.get("destination_name") if route else None,
                 trip["state"], trip.get("started_at"), trip.get("finished_at"), source,
                 trip.get("updated_at") or now, punctuality, delay, closed, now if closed else None, now, now),
            )
            row = connection.execute("SELECT * FROM driver_trip_history WHERE trip_key=?", (trip_key,)).fetchone()
        return dict(row)

    def update_profile(self, driver_id: str, *, cpf: str | None, phone: str | None, name: str | None) -> dict[str, Any]:
        with self.repository._lock, self.repository.connect() as connection:
            current = connection.execute("SELECT * FROM driver_profiles WHERE id=?", (driver_id,)).fetchone()
            if not current:
                raise KeyError(driver_id)
            clean_cpf = re.sub(r"\D", "", cpf or "") or None
            if clean_cpf and len(clean_cpf) != 11:
                raise ValueError("CPF deve conter 11 dígitos")
            connection.execute(
                "UPDATE driver_profiles SET cpf=?,phone=?,name=?,updated_at=? WHERE id=?",
                (clean_cpf, (phone or "").strip() or None, (name or current["name"]).strip(), _now(), driver_id),
            )
            row = connection.execute("SELECT * FROM driver_profiles WHERE id=?", (driver_id,)).fetchone()
        return dict(row)

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
        return {"items": [dict(row) for row in rows], "page": page, "page_size": page_size, "total": total}

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
        result = dict(driver)
        result.update(dict(totals))
        result["automatic_punctuality_percent"] = round(100 * int(totals["automatic_on_time"] or 0) / total, 1) if total else None
        result["considered_punctuality_percent"] = round(100 * int(totals["considered_on_time"] or 0) / total, 1) if total else None
        result["routes"] = [dict(row) for row in routes]
        result["customers"] = [dict(row) for row in customers]
        result["evaluations"] = [dict(row) for row in evaluations]
        result["notes"] = [dict(row) for row in notes]
        return result

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
        # There is no responsible person before an evaluation; this filter intentionally returns none.
        if responsible: clauses.append("0=1")
        if overdue is not None: clauses.append("((julianday('now')-julianday(h.finished_at))*24>=?)" if overdue else "((julianday('now')-julianday(h.finished_at))*24<?)"); params.append(overdue_hours)
        where = " AND ".join(clauses)
        with self.repository.connect() as connection:
            total = connection.execute(f"SELECT COUNT(*) FROM driver_trip_history h LEFT JOIN driver_evaluations e ON e.trip_key=h.trip_key WHERE {where}", params).fetchone()[0]
            rows = connection.execute(
                f"""SELECT h.*,d.name driver_name,NULL responsible,
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
        rows = "".join(f"<tr><td>{html.escape(str(t.get('provider_trip_id') or t['trip_key']))}</td><td>{html.escape(str(t.get('finished_at') or t.get('started_at') or '—'))}</td><td>{html.escape(str(t.get('route_name') or 'Rota não informada'))}</td><td>{html.escape(t['plate'])}</td><td>{html.escape(str(t.get('automatic_punctuality')))}</td><td>{html.escape(str(t.get('considered_punctuality') or t.get('automatic_punctuality')))}</td></tr>" for t in trips)
        evaluations = "".join(f"<li>{html.escape(e['recommendation'])} · comunicação {html.escape(e['communication'])} · procedimentos {html.escape(e['procedures'])} · {html.escape(e['created_at'])}</li>" for e in profile["evaluations"]) or "<li>Nenhuma avaliação.</li>"
        trip_keys = [trip["trip_key"] for trip in trips]
        events: list[dict[str, Any]] = []
        if trip_keys:
            placeholders = ",".join("?" for _ in trip_keys)
            with self.repository.connect() as connection:
                events = [dict(row) for row in connection.execute(
                    f"SELECT event_type,occurred_at,description FROM operational_events WHERE trip_key IN ({placeholders}) ORDER BY occurred_at DESC LIMIT 250", trip_keys).fetchall()]
        occurrences = "".join(f"<li>{html.escape(e['occurred_at'])} · {html.escape(e['description'])}</li>" for e in events) or "<li>Nenhuma ocorrência persistida.</li>"
        applied = ", ".join(f"{key}: {value}" for key, value in (filters or {}).items() if value) or "sem filtros adicionais"
        notes = "" if not include_sensitive else "<h2>Observações internas</h2><ul>" + "".join(f"<li>{html.escape(n['note'])}</li>" for n in profile["notes"]) + "</ul>"
        return f"""<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><style>@page{{size:A4;margin:12mm}}body{{font:14px Arial;color:#172033}}header{{background:#12395b;color:#fff;padding:26px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid #ddd;text-align:left}}th{{background:#e8b923}}small{{color:#667}}</style></head><body><header><small>SEVEN CARGO · HISTÓRICO OPERACIONAL</small><h1>{html.escape(profile['name'])}</h1><p>ID interno {html.escape(profile['id'])}</p></header><p>Emitido em {_now()} · {len(trips)} viagem(ns) · filtros: {html.escape(applied)}</p><h2>Resumo das viagens e rotas realizadas</h2><table><thead><tr><th>Viagem</th><th>Data</th><th>Rota</th><th>Placa</th><th>Pontualidade calculada</th><th>Considerada</th></tr></thead><tbody>{rows or '<tr><td colspan=6>Nenhuma viagem no período.</td></tr>'}</tbody></table><h2>Ocorrências</h2><ul>{occurrences}</ul><h2>Avaliações operacionais</h2><ul>{evaluations}</ul>{notes}<footer><p>Documento gerado sob demanda com dados consolidados no banco interno.</p></footer></body></html>"""
