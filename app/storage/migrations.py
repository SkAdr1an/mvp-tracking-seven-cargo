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


SCHEMA_VERSION = 9
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
})


class DatabaseSchemaError(RuntimeError):
    pass


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


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
        "operational_sites": {
            "address": "ALTER TABLE operational_sites ADD COLUMN address TEXT",
            "municipality": "ALTER TABLE operational_sites ADD COLUMN municipality TEXT",
        },
    }
    for table, definitions in expected_columns.items():
        existing = _columns(connection, table)
        alterations.extend(sql for column, sql in definitions.items() if existing and column not in existing)

    scripts.extend(alterations)
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
    CHECK(expires_at > created_at)
);
CREATE INDEX IF NOT EXISTS idx_panel_sessions_user_active
ON panel_sessions(username, revoked_at, expires_at);
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
""")
    return "\n".join(scripts)


def migrate_database(database_path: str | Path, *, failure_probe: bool = False) -> None:
    path = Path(database_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        current = connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] if "schema_migrations" in {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        } else None
        if current == SCHEMA_VERSION:
            tables = {
                str(row[0]) for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            missing = REQUIRED_TABLES - tables
            if missing:
                raise DatabaseSchemaError("Current migration marker has an incomplete schema")
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise DatabaseSchemaError("SQLite integrity check failed")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise DatabaseSchemaError("Foreign-key violations found")
            return
        if current is not None and int(current) > SCHEMA_VERSION:
            raise DatabaseSchemaError(
                f"Database schema version {current} is newer than supported version {SCHEMA_VERSION}"
            )
        script = _migration_script(connection)
        failure_statement = "SELECT * FROM __synthetic_migration_failure__;" if failure_probe else ""
        applied_at = datetime.now(timezone.utc).isoformat().replace("'", "''")
        connection.executescript(
            "BEGIN IMMEDIATE;\n"
            + script
            + "\n"
            + failure_statement
            + f"\nINSERT OR REPLACE INTO schema_migrations(version, applied_at) VALUES({SCHEMA_VERSION}, '{applied_at}');\n"
            + "COMMIT;"
        )
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise DatabaseSchemaError("SQLite integrity check failed after migration")
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise DatabaseSchemaError("Foreign-key violations found after migration")
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
        row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        version = int(row[0]) if row and row[0] is not None else 0
        if version != SCHEMA_VERSION:
            raise DatabaseSchemaError(
                f"Database schema version {version} does not match required version {SCHEMA_VERSION}"
            )
    finally:
        connection.close()
