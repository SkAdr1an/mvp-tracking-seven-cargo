from __future__ import annotations

import html
import base64
import json
import math
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
        self.consolidate_verified_identities()
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
            verified = connection.execute(
                """SELECT id FROM driver_profiles
                WHERE identity_status='VERIFIED' AND cpf IS NOT NULL
                  AND lower(trim(name))=lower(trim(?)) LIMIT 2""",
                (name,),
            ).fetchall()
            previous_driver_id = existing["driver_id"] if existing else None
            driver_id = verified[0]["id"] if len(verified) == 1 else previous_driver_id
            if not driver_id:
                driver_id = "drv_" + uuid.uuid4().hex
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
            if previous_driver_id and previous_driver_id != driver_id:
                connection.execute(
                    """DELETE FROM driver_profiles WHERE id=? AND identity_status='PENDING'
                    AND cpf IS NULL AND phone IS NULL
                    AND NOT EXISTS(SELECT 1 FROM driver_trip_history WHERE driver_id=?)
                    AND NOT EXISTS(SELECT 1 FROM driver_evaluations WHERE driver_id=?)
                    AND NOT EXISTS(SELECT 1 FROM driver_internal_notes WHERE driver_id=?)""",
                    (previous_driver_id, previous_driver_id, previous_driver_id, previous_driver_id),
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

    def consolidate_verified_identities(self) -> int:
        """Merge pending profiles only when an exact name maps to one CPF-verified profile."""
        merged = 0
        now = _now()
        with self.repository._lock, self.repository.connect() as connection:
            groups = connection.execute(
                """SELECT lower(trim(name)) name_key,MIN(id) verified_id,COUNT(*) matches
                FROM driver_profiles WHERE identity_status='VERIFIED' AND cpf IS NOT NULL
                GROUP BY lower(trim(name)) HAVING COUNT(*)=1"""
            ).fetchall()
            for group in groups:
                pending = connection.execute(
                    """SELECT id FROM driver_profiles WHERE lower(trim(name))=? AND identity_status='PENDING'
                    AND cpf IS NULL AND id<>?""", (group["name_key"], group["verified_id"])
                ).fetchall()
                for source in pending:
                    trip_keys = [row[0] for row in connection.execute(
                        "SELECT trip_key FROM driver_trip_history WHERE driver_id=?", (source["id"],)
                    )]
                    connection.execute("UPDATE driver_trip_history SET driver_id=?,updated_at=? WHERE driver_id=?",
                                       (group["verified_id"], now, source["id"]))
                    connection.execute("UPDATE driver_evaluations SET driver_id=?,updated_at=? WHERE driver_id=?",
                                       (group["verified_id"], now, source["id"]))
                    connection.execute("UPDATE driver_internal_notes SET driver_id=? WHERE driver_id=?",
                                       (group["verified_id"], source["id"]))
                    for trip_key in trip_keys:
                        connection.execute(
                            "INSERT INTO driver_identity_links(trip_key,previous_driver_id,new_driver_id,source,justification,responsible,created_at) VALUES(?,?,?,?,?,?,?)",
                            (trip_key, source["id"], group["verified_id"], "internal:cpf-consolidation",
                             "Nome exato associado a um único perfil com CPF verificado", "system:identity", now),
                        )
                    connection.execute("DELETE FROM driver_profiles WHERE id=?", (source["id"],))
                    merged += 1
        return merged

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
        if clean_cpf:
            self.consolidate_verified_identities()
            return self.profile(driver_id)
        return self._safe_profile(dict(row))

    def drivers(self, *, search: str = "", page: int = 1, page_size: int = 25) -> dict[str, Any]:
        text = search.strip()
        digits = re.sub(r"\D", "", text)
        term = f"%{text}%"
        cpf_term = f"%{digits}%" if digits else term
        where = """WHERE (?='' OR d.name LIKE ? OR d.cpf LIKE ? OR d.phone LIKE ? OR EXISTS(
            SELECT 1 FROM driver_trip_history h WHERE h.driver_id=d.id AND h.plate LIKE ?))"""
        params = (text, term, cpf_term, term, term)
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

    def master_drivers(self, *, search: str = "", status: str = "", client_operation: str = "",
                       vehicle_profile: str = "", route: str = "", page: int = 1,
                       page_size: int = 50) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        text, digits = search.strip(), re.sub(r"\D", "", search)
        phone_digits = lambda column: f"replace(replace(replace(replace(replace({column},' ',''),'-',''),'(',''),')',''),'+','')"
        if text:
            clauses.append(f"(lower(d.name) LIKE lower(?) OR d.cpf LIKE ? OR {phone_digits('d.phone')} LIKE ? OR {phone_digits('d.emergency_phone')} LIKE ?)")
            params.extend((f"%{text}%", f"%{digits}%" if digits else "", f"%{digits}%" if digits else "", f"%{digits}%" if digits else ""))
        if status: clauses.append("COALESCE(d.master_status,d.identity_status)=?"); params.append(status)
        if client_operation:
            clauses.append("(d.client_operation=? OR EXISTS(SELECT 1 FROM driver_trip_history hc WHERE hc.driver_id=d.id AND hc.customer=?))")
            params.extend((client_operation,client_operation))
        if vehicle_profile: clauses.append("d.vehicle_profile=?"); params.append(vehicle_profile)
        if route:
            clauses.append("(d.routes_json LIKE ? OR EXISTS(SELECT 1 FROM driver_trip_history hr WHERE hr.driver_id=d.id AND hr.route_name=?))")
            params.extend((f'%"{route}"%',route))
        where=" WHERE "+" AND ".join(clauses) if clauses else ""
        with self.repository.connect() as connection:
            total=connection.execute(f"SELECT COUNT(*) FROM driver_profiles d{where}",params).fetchone()[0]
            rows=connection.execute(
                f"""SELECT d.*,
                (SELECT group_concat(DISTINCT h.customer) FROM driver_trip_history h WHERE h.driver_id=d.id AND h.customer IS NOT NULL) history_clients,
                (SELECT group_concat(DISTINCT h.route_name) FROM driver_trip_history h WHERE h.driver_id=d.id AND h.route_name IS NOT NULL) history_routes
                FROM driver_profiles d{where} ORDER BY d.name COLLATE NOCASE LIMIT ? OFFSET ?""",
                (*params,page_size,(page-1)*page_size),
            ).fetchall()
            statuses=[row[0] for row in connection.execute("SELECT DISTINCT COALESCE(master_status,identity_status) FROM driver_profiles WHERE COALESCE(master_status,identity_status)<>'' ORDER BY 1")]
            clients=[row[0] for row in connection.execute("SELECT value FROM (SELECT client_operation value FROM driver_profiles UNION SELECT customer FROM driver_trip_history) WHERE value IS NOT NULL AND trim(value)<>'' GROUP BY value ORDER BY value")]
            profiles=[row[0] for row in connection.execute("SELECT DISTINCT vehicle_profile FROM driver_profiles WHERE vehicle_profile IS NOT NULL AND trim(vehicle_profile)<>'' ORDER BY 1")]
            routes=[row[0] for row in connection.execute("SELECT value FROM (SELECT route_name value FROM driver_trip_history UNION SELECT json_each.value FROM driver_profiles,json_each(driver_profiles.routes_json)) WHERE value IS NOT NULL AND trim(value)<>'' GROUP BY value ORDER BY value")]
        items=[]
        for source in rows:
            value=dict(source)
            stored_routes=json.loads(value.pop("routes_json") or "[]")
            history_routes=[item for item in (value.pop("history_routes") or "").split(",") if item]
            history_clients=[item for item in (value.pop("history_clients") or "").split(",") if item]
            value["routes"]=list(dict.fromkeys([*stored_routes,*history_routes]))
            value["client_operations"]=list(dict.fromkeys([item for item in [value.pop("client_operation",None),*history_clients] if item]))
            value["cpf_duplicate"]=False
            items.append(self._safe_profile(value))
        return {"items":items,"page":page,"page_size":page_size,"total":total,
                "facets":{"statuses":statuses,"client_operations":clients,"vehicle_profiles":profiles,"routes":routes}}

    def preview_master_import(self, *, file_name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        with self.repository.connect() as connection:
            existing={row["cpf"]:dict(row) for row in connection.execute("SELECT * FROM driver_profiles WHERE cpf IS NOT NULL")}
        items=[];seen_cpfs:set[str]=set()
        for row in rows:
            source_row=int(row.get("source_row") or 0);name=str(row.get("name") or "").strip();cpf=re.sub(r"\D","",str(row.get("cpf") or ""))
            if not name:
                items.append({"source_row":source_row,"name":"Não informado","classification":"INVALID","importable":False,"reason":"Motorista não informado","changes":[]});continue
            if cpf and len(cpf)!=11:
                items.append({"source_row":source_row,"name":name,"cpf_masked":self._masked_cpf(cpf),"classification":"INVALID","importable":False,"reason":"CPF deve conter 11 dígitos","changes":[]});continue
            warnings=list(row.get("warnings") or [])
            if not cpf:
                items.append({"source_row":source_row,"name":name,"classification":"PENDING","importable":False,"reason":"CPF não informado; revisão manual necessária","changes":[],"row":row});continue
            if cpf in seen_cpfs: warnings.append("CPF repetido no arquivo")
            seen_cpfs.add(cpf)
            current=existing.get(cpf);changes=[]
            mapping=(("name","Motorista"),("phone","Telefone principal"),("emergency_phone","Telefone de emergência"),("master_status","Status"),("registration_date","Data do cadastro"),("client_operation","Cliente / Operação"),("vehicle_profile","Perfil de veículo"))
            for target,label in mapping:
                source="primary_phone" if target=="phone" else "status" if target=="master_status" else target
                value=str(row.get(source) or "").strip()
                before=str(current.get(target) or "").strip() if current else ""
                if value and value!=before:changes.append({"field":label,"before":before or None,"after":value})
            routes=list(row.get("routes") or []);before_routes=json.loads(current.get("routes_json") or "[]") if current else []
            if routes and routes!=before_routes:changes.append({"field":"Rotas","before":", ".join(before_routes) or None,"after":", ".join(routes)})
            classification="PENDING" if warnings else ("UPDATE" if current else "NEW")
            items.append({"source_row":source_row,"name":name,"cpf_masked":self._masked_cpf(cpf),"classification":classification,"importable":True,"reason":"; ".join(warnings) or None,"changes":changes,"row":{**row,"cpf":cpf}})
        return self._import_summary(file_name,items)

    def import_master(self, *, file_name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        preview=self.preview_master_import(file_name=file_name,rows=rows)
        now=_now();created=updated=pending=0
        with self.repository._lock,self.repository.connect() as connection:
            for item in preview["items"]:
                if not item["importable"]:continue
                row=item["row"];cpf=row["cpf"]
                current=connection.execute("SELECT * FROM driver_profiles WHERE cpf=?",(cpf,)).fetchone()
                if current:
                    current=dict(current)
                    values={"name":str(row.get("name") or "").strip() or current["name"],"phone":str(row.get("primary_phone") or "").strip() or current.get("phone"),"emergency_phone":str(row.get("emergency_phone") or "").strip() or current.get("emergency_phone"),"master_status":str(row.get("status") or "").strip() or current.get("master_status"),"registration_date":str(row.get("registration_date") or "").strip() or current.get("registration_date"),"client_operation":str(row.get("client_operation") or "").strip() or current.get("client_operation"),"routes_json":json.dumps(row.get("routes") or json.loads(current.get("routes_json") or "[]"),ensure_ascii=False),"vehicle_profile":str(row.get("vehicle_profile") or "").strip() or current.get("vehicle_profile")}
                    connection.execute("""UPDATE driver_profiles SET name=:name,phone=:phone,emergency_phone=:emergency_phone,master_status=:master_status,registration_date=:registration_date,client_operation=:client_operation,routes_json=:routes_json,vehicle_profile=:vehicle_profile,identity_status='VERIFIED',updated_at=:updated_at WHERE id=:id""",{**values,"updated_at":now,"id":current["id"]});updated+=1
                else:
                    connection.execute("""INSERT INTO driver_profiles(id,cpf,name,phone,emergency_phone,client_operation,routes_json,vehicle_profile,master_status,registration_date,identity_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",("drv_"+uuid.uuid4().hex,cpf,str(row["name"]).strip(),str(row.get("primary_phone") or "").strip() or None,str(row.get("emergency_phone") or "").strip() or None,str(row.get("client_operation") or "").strip() or None,json.dumps(row.get("routes") or [],ensure_ascii=False),str(row.get("vehicle_profile") or "").strip() or None,str(row.get("status") or "").strip() or None,str(row.get("registration_date") or "").strip() or None,"VERIFIED",now,now));created+=1
                if item["classification"]=="PENDING":pending+=1
        ignored=sum(1 for item in preview["items"] if not item["importable"])
        self.consolidate_verified_identities()
        return {"file_name":file_name,"created":created,"updated":updated,"pending":pending,"invalid":preview["invalid_count"],"ignored":ignored}

    @staticmethod
    def _masked_cpf(cpf: str) -> str | None:return f"***.***.***-{cpf[-2:]}" if cpf else None

    @staticmethod
    def _import_summary(file_name: str,items:list[dict[str,Any]])->dict[str,Any]:
        count=lambda value:sum(1 for item in items if item["classification"]==value)
        return {"file_name":file_name,"total":len(items),"new_count":count("NEW"),"update_count":count("UPDATE"),"pending_count":count("PENDING"),"invalid_count":count("INVALID"),"items":items}

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
                SUM(COALESCE(considered_punctuality,automatic_punctuality)='ON_TIME') considered_on_time,
                SUM(COALESCE(considered_punctuality,automatic_punctuality) IN ('ON_TIME','LATE')) considered_eligible
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
        considered_eligible = int(totals["considered_eligible"] or 0)
        result["considered_punctuality_percent"] = round(100 * int(totals["considered_on_time"] or 0) / considered_eligible, 1) if considered_eligible else None
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
                WHERE {where}
                ORDER BY datetime(COALESCE(h.loaded_at,h.started_at,h.arrived_destination_at,h.finished_at,h.source_created_at,h.created_at)) DESC,
                         h.trip_key DESC
                LIMIT ? OFFSET ?""",
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

    def report_preview(self, trip_key: str) -> dict[str, Any]:
        from app.services.trip_report import TripReportService
        with self.repository.connect() as connection:
            history = connection.execute("SELECT * FROM driver_trip_history WHERE trip_key=?", (trip_key,)).fetchone()
            if not history:
                raise KeyError(trip_key)
            changes = [dict(row) for row in connection.execute(
                "SELECT id,field_name,previous_value,new_value,responsible,justification,created_at FROM driver_trip_history_changes WHERE trip_key=? ORDER BY created_at,id",
                (trip_key,),
            )]
        evidence = TripReportService(self.repository, Path(".")).evidence(trip_key)
        latest = {item["field_name"]: item["new_value"] for item in changes}
        trip = dict(history)
        trip_fields = ("origin_name", "destination_name", "loaded_at", "started_at", "scheduled_arrival_at",
                       "arrived_destination_at", "finished_at", "trailer_plate", "customer", "status")
        fields = [{"key": f"trip.{name}", "label": name.replace("_", " ").title(),
                   "original": trip.get(name), "value": latest.get(f"trip.{name}", trip.get(name)),
                   "history": [item for item in changes if item["field_name"] == f"trip.{name}"]}
                  for name in trip_fields]
        stops = []
        for index, stop in enumerate(evidence["stops"], 1):
            value = dict(stop)
            stop_fields = []
            for name in ("started_at", "ended_at", "duration_minutes", "reason_text"):
                key = f"stop.{stop['id']}.{name}"
                stop_fields.append({"key": key, "label": name.replace("_", " ").title(),
                                    "original": value.get(name), "value": latest.get(key, value.get(name)),
                                    "history": [item for item in changes if item["field_name"] == key]})
            stops.append({"id": stop["id"], "label": f"Parada {index}", "latitude": stop["latitude"],
                          "longitude": stop["longitude"], "fields": stop_fields})
        positions = evidence["positions"]
        notes = evidence.get("operational_observations", [])
        for note in notes:
            for attachment in (note.get("metadata") or {}).get("report_attachments", []):
                attachment["url"] = f"/api/driver-history/evidence/{attachment['id']}"
        return {"trip_key": trip_key, "provider_trip_id": trip.get("provider_trip_id"), "plate": trip["plate"],
                "fields": fields, "stops": stops, "changes": changes,
                "notes": notes,
                "telemetry": {"position_count": len(positions), "stop_count": len(stops),
                              "first_position_at": positions[0]["recorded_at"] if positions else None,
                              "last_position_at": positions[-1]["recorded_at"] if positions else None}}

    def correct_report_field(self, trip_key: str, *, field: str, value: str,
                             justification: str, responsible: str) -> dict[str, Any]:
        if len(justification.strip()) < 5:
            raise ValueError("Justificativa é obrigatória")
        trip_allowed = {"origin_name", "destination_name", "loaded_at", "started_at", "scheduled_arrival_at",
                        "arrived_destination_at", "finished_at", "trailer_plate", "customer", "status"}
        stop_allowed = {"started_at", "ended_at", "duration_minutes", "reason_text"}
        with self.repository._lock, self.repository.connect() as connection:
            history = connection.execute("SELECT * FROM driver_trip_history WHERE trip_key=?", (trip_key,)).fetchone()
            if not history:
                raise KeyError(trip_key)
            latest = connection.execute(
                "SELECT new_value FROM driver_trip_history_changes WHERE trip_key=? AND field_name=? ORDER BY created_at DESC,id DESC LIMIT 1",
                (trip_key, field),
            ).fetchone()
            if field.startswith("trip.") and field[5:] in trip_allowed:
                original = history[field[5:]]
            else:
                match = re.fullmatch(r"stop\.(\d+)\.([a-z_]+)", field)
                if not match or match.group(2) not in stop_allowed:
                    raise ValueError("Campo não permitido para correção")
                row = connection.execute(
                    f"SELECT {match.group(2)} FROM operational_stops WHERE id=? AND trip_key=?",
                    (int(match.group(1)), trip_key),
                ).fetchone()
                if not row:
                    raise KeyError(field)
                original = row[0]
            previous = latest["new_value"] if latest else original
            if str(previous or "") == value.strip():
                raise ValueError("O novo valor é igual ao valor atual")
            connection.execute(
                "INSERT INTO driver_trip_history_changes(trip_key,field_name,previous_value,new_value,responsible,justification,created_at) VALUES(?,?,?,?,?,?,?)",
                (trip_key, field, None if previous is None else str(previous), value.strip(),
                 responsible, justification.strip(), _now()),
            )
        return self.report_preview(trip_key)

    def report_html(self, driver_id: str, trips: list[dict[str, Any]], *, include_sensitive: bool = False,
                    filters: dict[str, str | None] | None = None) -> str:
        profile = self.profile(driver_id)
        trip_keys = [trip["trip_key"] for trip in trips]
        events: list[dict[str, Any]] = []
        evaluations: list[dict[str, Any]] = []
        report_changes: list[dict[str, Any]] = []
        operational_evidence: dict[str, dict[str, Any]] = {}
        if trip_keys:
            placeholders = ",".join("?" for _ in trip_keys)
            with self.repository.connect() as connection:
                events = [dict(row) for row in connection.execute(
                    f"SELECT trip_key,event_type,occurred_at,description,operator,justification FROM operational_events WHERE trip_key IN ({placeholders}) ORDER BY occurred_at", trip_keys).fetchall()]
                evaluations = [dict(row) for row in connection.execute(
                    f"SELECT * FROM driver_evaluations WHERE trip_key IN ({placeholders}) ORDER BY created_at", trip_keys).fetchall()]
                report_changes = [dict(row) for row in connection.execute(
                    f"SELECT * FROM driver_trip_history_changes WHERE trip_key IN ({placeholders}) ORDER BY created_at,id", trip_keys).fetchall()]
            from app.services.trip_report import TripReportService
            evidence_service = TripReportService(self.repository, Path("."))
            for trip_key in trip_keys:
                try:
                    operational_evidence[trip_key] = evidence_service.evidence(trip_key)
                except KeyError:
                    continue

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

        def format_minutes(value: Any) -> str:
            try:
                minutes = float(value)
            except (TypeError, ValueError):
                return "Não informado"
            text = f"{minutes:.0f}" if minutes.is_integer() else f"{minutes:.1f}"
            return f"{text} min"

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

        def trip_corrections(trip: dict[str, Any]) -> str:
            related = [change for change in report_changes if change["trip_key"] == trip["trip_key"]]
            if not related:
                return "<li>Nenhuma correção registrada.</li>"
            return "".join(
                f"<li><b>{shown(item['field_name'])}</b>: original/anterior {shown(item.get('previous_value'))} → "
                f"correção {shown(item.get('new_value'))} · {shown(item['responsible'])} · "
                f"{date(item['created_at'])} · {shown(item['justification'])}</li>" for item in related
            )

        def corrected(trip_key: str, field: str, original: Any) -> Any:
            related = [item for item in report_changes
                       if item["trip_key"] == trip_key and item["field_name"] == field]
            return related[-1]["new_value"] if related else original

        def observed_distance(positions: list[dict[str, Any]]) -> float:
            total = 0.0
            for previous, current in zip(positions, positions[1:]):
                lat1, lat2 = math.radians(previous["latitude"]), math.radians(current["latitude"])
                dlat = lat2 - lat1
                dlon = math.radians(current["longitude"] - previous["longitude"])
                value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
                total += 6371 * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0, 1 - value)))
            return total

        def tracking_details(trip: dict[str, Any]) -> str:
            evidence = operational_evidence.get(trip["trip_key"])
            if not evidence:
                return "<p class='unavailable'>Telemetria operacional não encontrada para esta viagem.</p>"
            positions = evidence["positions"]
            stops = evidence["stops"]
            gaps = evidence["communication_gaps"]
            summary = evidence["summary"]
            def stop_value(item: dict[str, Any], name: str) -> Any:
                return corrected(trip["trip_key"], f"stop.{item['id']}.{name}", item.get(name))
            coverage = (
                f"{date(positions[0]['recorded_at'])} a {date(positions[-1]['recorded_at'])}"
                if positions else "Não informado"
            )
            stop_rows = "".join(
                f"<tr><td>P{index}</td><td>{date(stop_value(item, 'started_at'))}</td><td>{date(stop_value(item, 'ended_at'))}</td>"
                f"<td>{format_minutes(stop_value(item, 'duration_minutes'))}</td>"
                f"<td>{float(item['latitude']):.5f}, {float(item['longitude']):.5f}</td>"
                f"<td>{shown(stop_value(item, 'reason_text') or 'Motivo não registrado')}</td></tr>"
            for index, item in enumerate(stops, 1)
            ) or "<tr><td colspan='6'>Nenhuma parada observada nas posições recebidas.</td></tr>"
            gap_rows = "".join(
                f"<tr><td>{date(item.get('started_at'))}</td><td>{date(item.get('ended_at'))}</td>"
                f"<td>{float(item.get('duration_minutes') or 0):.0f} min</td></tr>" for item in gaps
            ) or "<tr><td colspan='3'>Nenhuma lacuna de comunicação superior ao limite operacional.</td></tr>"
            note_cards = []
            evidence_dir = Path(self.repository.database_path).resolve().parent / "report-evidence"
            for note in evidence.get("operational_observations", []):
                images = []
                for attachment in (note.get("metadata") or {}).get("report_attachments", []):
                    file_name = Path(str(attachment.get("file") or "")).name
                    path = evidence_dir / file_name
                    if path.is_file() and path.resolve().parent == evidence_dir:
                        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                        images.append(f"<figure style='margin:8px 0;break-inside:avoid'><img style='max-width:100%;max-height:420px;object-fit:contain' src='data:{attachment['mime_type']};base64,{encoded}'/><figcaption>{shown(attachment.get('name'))}</figcaption></figure>")
                note_cards.append(f"<article class='report-note'><p>{shown(note.get('content'))}</p><small>{shown(note['author']['display_name'])} · {date(note.get('created_at'))}</small><div class='evidence-images'>{''.join(images)}</div></article>")
            notes_html = "".join(note_cards) or "<p>Nenhuma anotação operacional registrada.</p>"
            first_point = positions[0] if positions else None
            last_point = positions[-1] if positions else None
            endpoints = (
                f"<tr><td>Primeiro ponto</td><td>{date(first_point['recorded_at'])}</td><td>{first_point['latitude']:.5f}, {first_point['longitude']:.5f}</td></tr>"
                f"<tr><td>Último ponto</td><td>{date(last_point['recorded_at'])}</td><td>{last_point['latitude']:.5f}, {last_point['longitude']:.5f}</td></tr>"
                if first_point and last_point else "<tr><td colspan='3'>Percurso GPS indisponível.</td></tr>"
            )
            return f"""<h3>Percurso registrado</h3><div class='tracking-summary'>
            <b>{len(positions)} posições GPS</b><b>{observed_distance(positions):.1f} km observados</b>
            <b>{len(stops)} parada(s)</b><b>{summary['observed_stop_minutes']:.0f} min parado</b></div>
            <p class='coverage'>Cobertura GPS: {coverage}</p>
            <table><thead><tr><th>Marco</th><th>Data/hora</th><th>Coordenadas</th></tr></thead><tbody>{endpoints}</tbody></table>
            <h3>Paradas e pausas observadas</h3><table><thead><tr><th>#</th><th>Início</th><th>Fim</th><th>Duração</th><th>Coordenadas</th><th>Motivo</th></tr></thead><tbody>{stop_rows}</tbody></table>
            <h3>Lacunas de comunicação</h3><p class='method'>Ausência de sinal não é contabilizada como parada.</p>
            <table><thead><tr><th>Início</th><th>Fim</th><th>Duração</th></tr></thead><tbody>{gap_rows}</tbody></table>
            <h3>Anotações e evidências</h3>{notes_html}"""

        cards = []
        for trip in trips:
            number = shown(trip.get("provider_trip_id") or trip["trip_key"])
            reference_date = trip.get("loaded_at") or trip.get("started_at") or trip.get("arrived_destination_at") or trip.get("finished_at") or trip.get("source_created_at")
            operation = corrected(trip["trip_key"], "trip.customer", trip.get("customer")) or trip.get("route_name")
            cards.append(f"""<section class='trip'><h2>Viagem {number}</h2><table>
            <tr><th>Data de referência</th><td>{date(reference_date)}</td><th>Status</th><td>{shown(corrected(trip['trip_key'], 'trip.status', trip.get('status')))}</td></tr>
            <tr><th>Origem</th><td>{shown(corrected(trip['trip_key'], 'trip.origin_name', trip.get('origin_name')))}</td><th>Destino</th><td>{shown(corrected(trip['trip_key'], 'trip.destination_name', trip.get('destination_name')))}</td></tr>
            <tr><th>Cliente/operação</th><td>{shown(operation)}</td><th>Pacotes</th><td>{shown(trip.get('package_count'))}</td></tr>
            <tr><th>Placa</th><td>{shown(trip.get('plate'))}</td><th>Implemento</th><td>{shown(corrected(trip['trip_key'], 'trip.trailer_plate', trip.get('trailer_plate')))}</td></tr>
            <tr><th>Carregamento</th><td>{date(corrected(trip['trip_key'], 'trip.loaded_at', trip.get('loaded_at')))}</td><th>Início</th><td>{date(corrected(trip['trip_key'], 'trip.started_at', trip.get('started_at')))}</td></tr>
            <tr><th>Previsão de chegada</th><td>{date(corrected(trip['trip_key'], 'trip.scheduled_arrival_at', trip.get('scheduled_arrival_at') or trip.get('eta_at')))}</td><th>Chegada real</th><td>{date(corrected(trip['trip_key'], 'trip.arrived_destination_at', trip.get('arrived_destination_at')))}</td></tr>
            <tr><th>Término</th><td>{date(corrected(trip['trip_key'], 'trip.finished_at', trip.get('finished_at')))}</td><th>Responsável</th><td>{shown(trip.get('evaluation_responsible') or trip.get('responsible'))}</td></tr>
            <tr><th>Pontualidade calculada</th><td>{punctuality(trip.get('automatic_punctuality'))}</td><th>Pontualidade considerada</th><td>{punctuality(trip.get('considered_punctuality') or trip.get('automatic_punctuality'))}</td></tr>
            </table>{tracking_details(trip)}<h3>Correções do relatório</h3><ul>{trip_corrections(trip)}</ul><h3>Ocorrências</h3><ul>{trip_events(trip)}</ul><h3>Avaliações e observações</h3><ul>{trip_evaluations(trip)}</ul></section>""")
        earliest = min((trip.get("source_created_at") for trip in trips if trip.get("source_created_at")), default=None)
        latest = max((trip.get("finished_at") or trip.get("source_updated_at") for trip in trips if trip.get("finished_at") or trip.get("source_updated_at")), default=None)
        start_filter, end_filter = (filters or {}).get("início"), (filters or {}).get("fim")
        period = f"{date(start_filter or earliest)} a {date(end_filter or latest)}" if trips else "Não informado"
        count_label = "1 viagem" if len(trips) == 1 else f"{len(trips)} viagens"
        identity = " · ".join(value for value in (profile.get("cpf_masked"), profile.get("phone")) if value) or "CPF e telefone não informados"
        notes = "" if not include_sensitive else "<h2>Observações internas do motorista</h2><ul>" + "".join(f"<li>{shown(n['note'])}</li>" for n in profile["notes"]) + "</ul>"
        return f"""<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><style>@page{{size:A4;margin:11mm}}body{{font:12px Arial;color:#172033}}header{{background:#12395b;color:#fff;padding:22px}}header h1{{margin:8px 0}}.internal-id{{font-size:9px;opacity:.65}}.summary{{display:flex;gap:22px;padding:12px 0}}.trip{{margin:14px 0 20px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:7px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}}th{{background:#f4f0df}}h2{{color:#12395b}}h3{{margin:16px 0 5px}}small{{opacity:.75}}.tracking-summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}}.tracking-summary b{{padding:9px;background:#edf3f7;color:#12395b}}.coverage,.method,.unavailable{{color:#526174}}thead{{display:table-header-group}}tr,.tracking-summary{{break-inside:avoid}}</style></head><body><header><small>SEVEN CARGO · HISTÓRICO OPERACIONAL</small><h1>{shown(profile['name'])}</h1><p>{shown(identity)}</p><p class='internal-id'>Referência interna: {shown(profile['id'])}</p></header><div class='summary'><strong>Período consultado: {period}</strong><strong>Total: {count_label}</strong></div>{''.join(cards) or '<p>Nenhuma viagem no período.</p>'}{notes}<footer><p>Documento gerado sob demanda com os dados disponíveis na fonte operacional interna. Campos não armazenados são apresentados como “Não informado”.</p></footer></body></html>"""
