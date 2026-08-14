from __future__ import annotations

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

from app.storage.angellira import SCHEMA as ANGELLIRA_SCHEMA
from app.storage.operations import SCHEMA as OPERATIONS_SCHEMA
from app.storage.public_trip import PUBLIC_LINK_SCHEMA
from app.storage.traffic import TRAFFIC_SCHEMA
from app.services.operational_sites import AUTHORIZED_SITE_ALIASES, SITE_SCHEMA
from app.services.trip_operations import BETIM_JABOATAO_ROUTE, SAO_BERNARDO_CONTAGEM_ROUTE


SCHEMA_VERSION = 13
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIRECTORY = PROJECT_ROOT / "migrations"
REQUIRED_TABLES = frozenset({
    "schema_migrations",
    "route_configs",
    "operational_trips",
    "public_trip_links",
    "traffic_incidents",
    "angellira_stations",
    "portal_mobile_position_metadata",
    "portal_alert_presentations",
    "panel_sessions",
    "users",
    "roles",
    "permissions",
    "role_permissions",
    "communication_gaps",
    "journey_observation_trackers",
    "operational_exceptions",
    "operational_stops",
    "stop_evidence_events",
    "operational_observations",
    "audit_events",
})
REQUIRED_INDEXES = frozenset({
    "idx_operational_exceptions_status",
    "idx_operational_stops_trip_time",
    "idx_users_role_status",
    "idx_role_permissions_permission",
    "idx_operational_observations_trip_time",
    "idx_operational_observations_author_time",
    "idx_operational_observations_stop",
    "idx_audit_events_occurred_at",
    "idx_audit_events_actor_time",
    "idx_audit_events_trip_time",
    "idx_audit_events_action_time",
    "idx_audit_events_resource",
})


class DatabaseSchemaError(RuntimeError):
    pass


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _statements(script: str):
    pending = ""
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            statement = pending.strip()
            pending = ""
            if statement:
                yield statement
    if pending.strip():
        raise DatabaseSchemaError("Incomplete SQL statement in migration")


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _indexes(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
    }


def _current_version(connection: sqlite3.Connection) -> int | None:
    if "schema_migrations" not in _tables(connection):
        return None
    row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _integrity_result(connection: sqlite3.Connection) -> str:
    return str(connection.execute("PRAGMA integrity_check").fetchone()[0])


def _foreign_key_violations(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute("PRAGMA foreign_key_check").fetchall()


def _validate_existing_database(connection: sqlite3.Connection) -> None:
    if _integrity_result(connection) != "ok":
        raise DatabaseSchemaError("SQLite integrity check failed")
    if _foreign_key_violations(connection):
        raise DatabaseSchemaError("Foreign-key violations found")


def _validate_required_schema(connection: sqlite3.Connection) -> None:
    missing = sorted(REQUIRED_TABLES - _tables(connection))
    if missing:
        raise DatabaseSchemaError(
            f"Migration did not create required tables ({', '.join(missing)})"
        )
    missing_indexes = sorted(REQUIRED_INDEXES - _indexes(connection))
    if missing_indexes:
        raise DatabaseSchemaError(
            f"Migration did not create required indexes ({', '.join(missing_indexes)})"
        )


def _migration_script(connection: sqlite3.Connection) -> str:
    scripts = [OPERATIONS_SCHEMA, SITE_SCHEMA]
    for name in (
        "002_corridor_catalog.sql",
        "003_operational_sites.sql",
        "004_route_site_links.sql",
        "005_routing_usage_guard.sql",
    ):
        scripts.append((MIGRATIONS_DIRECTORY / name).read_text(encoding="utf-8"))
    scripts.extend((PUBLIC_LINK_SCHEMA, TRAFFIC_SCHEMA, ANGELLIRA_SCHEMA))
    for name in ("007_driver_mobile_location.sql", "008_driver_portal_alerts.sql"):
        scripts.append((MIGRATIONS_DIRECTORY / name).read_text(encoding="utf-8"))
    scripts.append(
        (MIGRATIONS_DIRECTORY / "010_journey_observation.sql").read_text(encoding="utf-8")
    )
    scripts.append(
        (MIGRATIONS_DIRECTORY / "011_persistent_users_rbac.sql").read_text(encoding="utf-8")
    )
    scripts.append(
        (MIGRATIONS_DIRECTORY / "012_operational_observations.sql").read_text(encoding="utf-8")
    )
    scripts.append(
        (MIGRATIONS_DIRECTORY / "013_central_audit_log.sql").read_text(encoding="utf-8")
    )
    alterations: list[str] = []
    expected_columns = {
        "operational_diagnostics": {
            "commitment_delta_minutes": "ALTER TABLE operational_diagnostics ADD COLUMN commitment_delta_minutes REAL",
        },
        "route_configs": {
            "operational_duration_minutes": "ALTER TABLE route_configs ADD COLUMN operational_duration_minutes INTEGER",
            "is_express": "ALTER TABLE route_configs ADD COLUMN is_express INTEGER NOT NULL DEFAULT 0",
            "origin_site_id": "ALTER TABLE route_configs ADD COLUMN origin_site_id TEXT",
            "destination_site_id": "ALTER TABLE route_configs ADD COLUMN destination_site_id TEXT",
        },
        "routing_api_usage": {
            "provider": "ALTER TABLE routing_api_usage ADD COLUMN provider TEXT NOT NULL DEFAULT 'tomtom'",
        },
        "route_geometry_versions": {
            "provider": "ALTER TABLE route_geometry_versions ADD COLUMN provider TEXT",
            "distance_m": "ALTER TABLE route_geometry_versions ADD COLUMN distance_m REAL",
            "duration_seconds": "ALTER TABLE route_geometry_versions ADD COLUMN duration_seconds REAL",
        },
        "operational_trips": {
            "loaded_at": "ALTER TABLE operational_trips ADD COLUMN loaded_at TEXT",
            "trailer_plate": "ALTER TABLE operational_trips ADD COLUMN trailer_plate TEXT",
        },
        "traffic_incidents": {
            "publicly_visible": "ALTER TABLE traffic_incidents ADD COLUMN publicly_visible INTEGER NOT NULL DEFAULT 0",
            "public_title": "ALTER TABLE traffic_incidents ADD COLUMN public_title TEXT",
            "public_description": "ALTER TABLE traffic_incidents ADD COLUMN public_description TEXT",
        },
        "angellira_stations": {
            "manual_review_required": "ALTER TABLE angellira_stations ADD COLUMN manual_review_required INTEGER NOT NULL DEFAULT 0",
            "possible_merge_group_id": "ALTER TABLE angellira_stations ADD COLUMN possible_merge_group_id TEXT",
        },
        "panel_sessions": {
            "user_id": "ALTER TABLE panel_sessions ADD COLUMN user_id TEXT REFERENCES users(id)",
            "role_code_snapshot": "ALTER TABLE panel_sessions ADD COLUMN role_code_snapshot TEXT",
        },
        "operational_sites": {
            "address": "ALTER TABLE operational_sites ADD COLUMN address TEXT",
            "municipality": "ALTER TABLE operational_sites ADD COLUMN municipality TEXT",
        },
    }
    for table, definitions in expected_columns.items():
        existing = _columns(connection, table)
        alterations.extend(sql for column, sql in definitions.items() if existing and column not in existing)

    scripts.extend(statement.rstrip(";") + ";" for statement in alterations)
    def sql(value: object) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, (int, float)):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"

    for item in AUTHORIZED_SITE_ALIASES:
        site_id = item["id"]
        scripts.append(
            "INSERT OR IGNORE INTO operational_sites("
            "id,name,operation,address,municipality,latitude,longitude,created_at,updated_at) VALUES("
            + ",".join(sql(value) for value in (
                site_id, item.get("name", item["code"]), item["operation"],
                item.get("address"), item.get("municipality"), item["latitude"],
                item["longitude"], "migration-009", "migration-009",
            )) + ");"
        )
        scripts.append(
            "INSERT OR IGNORE INTO operational_site_aliases("
            "alias_code,site_id,operation,created_at,updated_at) VALUES("
            + ",".join(sql(value) for value in (
                item["code"], site_id, item["operation"], "migration-009", "migration-009",
            )) + ");"
        )
    for route in (BETIM_JABOATAO_ROUTE, SAO_BERNARDO_CONTAGEM_ROUTE):
        scripts.append(
            "INSERT OR IGNORE INTO route_configs("
            "id,name,origin_name,origin_latitude,origin_longitude,destination_name,"
            "destination_latitude,destination_longitude,origin_radius_m,destination_radius_m,"
            "origin_exit_radius_m,destination_exit_radius_m,origin_dwell_minutes,"
            "destination_dwell_minutes,destination_finish_minutes,stop_speed_max_kmh,"
            "consecutive_readings,sla_minutes,operational_duration_minutes,is_express,active,"
            "match_terms_json,created_at,updated_at) VALUES("
            + ",".join(sql(value) for value in (
                route["id"], route["name"], route["origin_name"], route["origin_latitude"],
                route["origin_longitude"], route["destination_name"], route["destination_latitude"],
                route["destination_longitude"], route["origin_radius_m"], route["destination_radius_m"],
                route["origin_exit_radius_m"], route["destination_exit_radius_m"],
                route["origin_dwell_minutes"], route["destination_dwell_minutes"],
                route["destination_finish_minutes"], route["stop_speed_max_kmh"],
                route["consecutive_readings"], route.get("sla_minutes"),
                route.get("operational_duration_minutes"), int(route.get("is_express", False)),
                int(route.get("active", True)), json.dumps(route.get("match_terms", []), ensure_ascii=False),
                "migration-009", "migration-009",
            )) + ");"
        )
    scripts.append("""
CREATE INDEX IF NOT EXISTS idx_incidents_public_route
ON traffic_incidents(route_id, publicly_visible, status, expires_at);
CREATE TABLE IF NOT EXISTS panel_sessions (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL,
    role TEXT NOT NULL,
    user_fingerprint TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    revoked_at INTEGER,
    user_id TEXT REFERENCES users(id),
    role_code_snapshot TEXT,
    CHECK(expires_at > created_at)
);
CREATE INDEX IF NOT EXISTS idx_panel_sessions_user_active
ON panel_sessions(username, revoked_at, expires_at);
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
""")
    now = "migration-011"
    role_names = {
        "ADMIN": "Administrador",
        "GR": "Gerenciamento de Risco",
        "MONITORING": "Monitoramento",
    }
    permission_descriptions = {
        "dashboard:read": "Visualizar painel operacional",
        "trips:read": "Visualizar viagens",
        "drivers:read": "Visualizar motoristas e veículos",
        "incidents:read": "Visualizar ocorrências",
        "stops:read": "Visualizar paradas",
        "trips:edit": "Editar dados operacionais da viagem",
        "trips:status-correct": "Corrigir estado operacional",
        "trips:finalize": "Finalizar viagem",
        "trips:cancel": "Cancelar viagem",
        "trips:archive": "Arquivar viagem",
        "trips:reopen": "Reabrir viagem",
        "trips:assign-route": "Associar rota",
        "trips:assign-driver": "Associar motorista",
        "reports:generate": "Gerar relatórios",
        "public-links:manage": "Administrar links públicos",
        "observations:create": "Criar observações operacionais",
        "observations:correct-own": "Corrigir observações próprias",
        "observations:void-any": "Anular qualquer observação",
        "stops:justify": "Justificar paradas",
        "incidents:create": "Criar ocorrências",
        "incidents:edit-structural": "Editar estrutura de ocorrências",
        "integrations:invoke": "Invocar integrações externas",
        "audit:read-operational": "Consultar auditoria operacional",
        "audit:read-full": "Consultar auditoria completa",
        "users:read": "Consultar usuários",
        "users:manage": "Administrar usuários",
        "roles:manage": "Administrar perfis e permissões",
        "settings:read": "Consultar configurações",
        "settings:manage": "Administrar configurações",
    }
    gr = {
        "dashboard:read", "trips:read", "drivers:read", "incidents:read", "stops:read",
        "trips:edit", "trips:status-correct", "trips:finalize", "trips:cancel",
        "trips:archive", "trips:reopen", "trips:assign-route", "trips:assign-driver",
        "reports:generate", "public-links:manage", "observations:create",
        "observations:correct-own", "stops:justify", "incidents:create",
        "incidents:edit-structural", "integrations:invoke", "audit:read-operational",
    }
    monitoring = {
        "dashboard:read", "trips:read", "drivers:read", "incidents:read", "stops:read",
        "observations:create", "observations:correct-own", "stops:justify",
        "incidents:create", "audit:read-operational",
    }
    for code, display_name in role_names.items():
        scripts.append(
            "INSERT OR IGNORE INTO roles(id,code,display_name,active,created_at,updated_at) "
            f"VALUES({sql(code)},{sql(code)},{sql(display_name)},1,{sql(now)},{sql(now)});"
        )
    for code, description in permission_descriptions.items():
        scripts.append(
            "INSERT OR IGNORE INTO permissions(id,code,description) "
            f"VALUES({sql(code)},{sql(code)},{sql(description)});"
        )
    for role_code, selected in (("ADMIN", set(permission_descriptions)), ("GR", gr), ("MONITORING", monitoring)):
        for permission_code in sorted(selected):
            scripts.append(
                "INSERT OR IGNORE INTO role_permissions(role_id,permission_id) "
                f"VALUES({sql(role_code)},{sql(permission_code)});"
            )
    return "\n".join(scripts)


def migrate_database(
    database_path: str | Path,
    *,
    failure_probe: bool = False,
    foreign_key_failure_probe: bool = False,
) -> None:
    path = Path(database_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        _validate_existing_database(connection)
        connection.execute("BEGIN IMMEDIATE")
        current = _current_version(connection)
        if current == SCHEMA_VERSION:
            _validate_required_schema(connection)
            _validate_existing_database(connection)
            connection.rollback()
            return
        if current is not None and int(current) > SCHEMA_VERSION:
            raise DatabaseSchemaError(
                f"Database schema version {current} is newer than supported version {SCHEMA_VERSION}"
            )
        for statement in _statements(_migration_script(connection)):
            connection.execute(statement)
        if failure_probe:
            connection.execute("SELECT * FROM __synthetic_migration_failure__")
        if foreign_key_failure_probe:
            connection.execute("PRAGMA defer_foreign_keys=ON")
            connection.execute(
                """INSERT INTO public_trip_links(
                       id, trip_key, token_hash, created_at
                   ) VALUES('synthetic-orphan','missing-trip','synthetic-hash','synthetic')"""
            )
        _validate_required_schema(connection)
        _validate_existing_database(connection)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES(?, ?)",
            (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
        )
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def validate_database_schema(database_path: str | Path) -> None:
    path = Path(database_path).resolve()
    if not path.is_file():
        raise DatabaseSchemaError(
            f"Database is not migrated: expected schema version {SCHEMA_VERSION}"
        )
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        tables = {
            str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = sorted(REQUIRED_TABLES - tables)
        if missing:
            raise DatabaseSchemaError(
                f"Database is not migrated: missing required tables ({', '.join(missing)})"
            )
        indexes = {
            str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        missing_indexes = sorted(REQUIRED_INDEXES - indexes)
        if missing_indexes:
            raise DatabaseSchemaError(
                "Database is not migrated: missing required indexes "
                f"({', '.join(missing_indexes)})"
            )
        row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        version = int(row[0]) if row and row[0] is not None else 0
        if version != SCHEMA_VERSION:
            raise DatabaseSchemaError(
                f"Database schema version {version} does not match required version {SCHEMA_VERSION}"
            )
    finally:
        connection.close()
