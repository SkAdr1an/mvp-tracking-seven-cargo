"""Neutral operational-site registry and derived vehicle proximity state."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.config import get_settings


APPROACH_RADIUS_M = 1000.0
ENTRY_RADIUS_M = 500.0
EXIT_RADIUS_M = 650.0
CARIACICA_CANONICAL_SITE_ID = "mb-importacao-matriz-cariacica"
CARIACICA_LEGACY_SITE_ID = "mb-importacao-filial-cariacica"

SITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS operational_sites (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    operation TEXT NOT NULL,
    address TEXT,
    municipality TEXT,
    latitude REAL NOT NULL CHECK(latitude BETWEEN -90 AND 90),
    longitude REAL NOT NULL CHECK(longitude BETWEEN -180 AND 180),
    approach_radius_m REAL NOT NULL DEFAULT 1000,
    entry_radius_m REAL NOT NULL DEFAULT 500,
    exit_radius_m REAL NOT NULL DEFAULT 650,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operational_site_aliases (
    alias_code TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES operational_sites(id),
    operation TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_operational_site_alias_site ON operational_site_aliases(site_id);
CREATE TABLE IF NOT EXISTS vehicle_site_states (
    plate TEXT PRIMARY KEY,
    site_id TEXT REFERENCES operational_sites(id),
    state TEXT NOT NULL,
    distance_m REAL,
    latitude REAL,
    longitude REAL,
    position_at TEXT,
    stale INTEGER NOT NULL DEFAULT 0,
    diagnostic_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
"""


AUTHORIZED_SITE_ALIASES: tuple[dict[str, Any], ...] = (
    {"id":"soc-sp-sao-bernardo-ceva","code":"SOC_SP_SÃO BERNARDO DO CAMPO","operation":"CEVA - SHOPEE","latitude":-23.719457759779772,"longitude":-46.60073995582935},
    {"id":"soc-sp-cravinhos","code":"SOC_SP_CRAVINHOS","operation":"CEVA - SHOPEE","latitude":-21.30835239271825,"longitude":-47.730721235493554},
    {"id":"soc-mg-betim","code":"SOC_MG_BETIM/MG","operation":"CEVA - SHOPEE","latitude":-19.981800153618142,"longitude":-44.26663594385532},
    {"id":"soc-pe-jaboatao","code":"SoC_PE_JABOATAO DOS GUARARAPES/PE","operation":"CEVA - SHOPEE","latitude":-8.207223071201726,"longitude":-34.964031908513675},
    {"id":"cd-shopee-fbs-contagem","code":"CD_SHOPPE_FBS-CONTAGEM/MG","operation":"CEVA - SHOPEE","latitude":-19.878364061335844,"longitude":-44.056416188767645},
    {"id":"cd-shopee-sp25-guarulhos","code":"CD_SHOPEE_SP25-GUARULHOS/SP","operation":"CEVA - SHOPEE","latitude":-23.455070061601113,"longitude":-46.444243490586497},
    {"id":"hub-shopee-cumbica-guarulhos","code":"HUB_SHOPEE_CUMBICA - GUARULHOS/SP","operation":"CEVA - SHOPEE","latitude":-23.446343283827314,"longitude":-46.44415246917209},
    {"id":"mb-importacao-matriz-cariacica","name":"MB IMPORTAÇÃO - CARIACICA/ES","code":"MB IMPORTAÇÃO MATRIZ - CARIACICA/ES","operation":"LM2RODAS","latitude":-20.286653541461504,"longitude":-40.40074933396733},
    {"id":"mb-importacao-matriz-cariacica","name":"MB IMPORTAÇÃO - CARIACICA/ES","code":"MB IMPORTAÇÃO FILIAL - CARIACICA/ES","operation":"LM2RODAS","latitude":-20.286653541461504,"longitude":-40.40074933396733},
    {"id":"wnorte-benevides","code":"WNORTE - BENEVIDES/PA","operation":"LM2RODAS","latitude":-1.367731321394543,"longitude":-48.27727301684851},
    {"id":"wne-cabo-santo-agostinho","name":"WNE - CABO DE SANTO AGOSTINHO/PE","code":"WNE MATRIZ - CABO DE SANTO AGOSTINHO/PE","operation":"LM2RODAS","latitude":-8.242412264372454,"longitude":-34.995843690398644},
    {"id":"wne-cabo-santo-agostinho","name":"WNE - CABO DE SANTO AGOSTINHO/PE","code":"WNE FILIAL - CABO DE SANTO AGOSTINHO/PE","operation":"LM2RODAS","latitude":-8.242412264372454,"longitude":-34.995843690398644},
    {"id":"wsul-navegantes","code":"WSUL - NAVEGANTES/SC","operation":"LM2RODAS","latitude":-26.872069275586764,"longitude":-48.670381573640114},
    {"id":"wco-aparecida-goiania","code":"WCO - APARECIDA DE GOIÂNIA/GO","operation":"LM2RODAS","latitude":-16.80768609425664,"longitude":-49.21550873945635},
    {"id":"soc-sp-sao-bernardo-modern","code":"SOC_SP_SÃO BERNARDO DO CAMPO/SP","operation":"MODERN - SHOPEE","latitude":-23.719137981626954,"longitude":-46.601166128837825},
    {"id":"lm-hub-mg-montes-claros","code":"LM HUB_MG_MONTES CLAROS","operation":"MODERN - SHOPEE","latitude":-16.68741723537206,"longitude":-43.87235518845435},
    {"id":"soc-sp-santana-parnaiba","code":"SOC_SP_SANTANA DO PARNAÍBA/SP","operation":"MODERN - SHOPEE","latitude":-23.482433881370866,"longitude":-46.99946674646114},
    {"id":"soc-sp-ibitinga","code":"SOC_SP_IBITINGA/SP","operation":"MODERN - SHOPEE","latitude":-21.78694708491442,"longitude":-48.84542991529164},
    {"id":"soc-ba-simoes-filho","code":"SOC_BA_SIMÕES FILHO/BA","operation":"MODERN - SHOPEE","latitude":-12.821411827681239,"longitude":-38.387697937944054},
    {"id":"tragetta-glp-guarulhos","code":"TRAGETTA - GLP GUARULHOS/SP","operation":"TRAGETTA","latitude":-23.425600200244666,"longitude":-46.38913749897839},
    {"id":"tragetta-serra","code":"TRAGETTA - SERRA/ES","operation":"TRAGETTA","latitude":-20.188966164933973,"longitude":-40.24013122509079},
    {"id":"xpt-pe-palmares","code":"XPT_PE_PALMARES/PE","operation":"CEVA - SHOPEE","latitude":-8.676618,"longitude":-35.576843},
    {"id":"wsp-itupeva","code":"WSP - ITUPEVA/SP","operation":"LM2RODAS","latitude":-23.17169605270281,"longitude":-47.03074053119824},
    {"id":"soc-pr-curitiba","name":"SoC_PR_CURITIBA/PR","code":"SoC_PR_CURITIBA/PR","operation":"CEVA - SHOPEE","address":"Rodovia Régis Bittencourt, 1500","municipality":"Campina Grande do Sul/PR","latitude":-25.349037664133935,"longitude":-49.058775032429246},
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def geodesic_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_008.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2-lat1), math.radians(lon2-lon1)
    value = math.sin(dphi/2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1-value))


def valid_coordinate(latitude: Any, longitude: Any) -> bool:
    return (
        isinstance(latitude, (int, float)) and not isinstance(latitude, bool)
        and isinstance(longitude, (int, float)) and not isinstance(longitude, bool)
        and math.isfinite(latitude) and math.isfinite(longitude)
        and -90 <= latitude <= 90 and -180 <= longitude <= 180
    )


def parse_position_time(value: Any, now: datetime | None = None) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    if parsed > (now or datetime.now(timezone.utc)) + timedelta(minutes=5):
        return None
    return parsed


def derived_site_state(distance_m: float, previous: str | None = None) -> str:
    if distance_m <= ENTRY_RADIUS_M:
        return "INSIDE"
    if distance_m <= EXIT_RADIUS_M:
        return "INSIDE" if previous == "INSIDE" else "APPROACHING"
    if distance_m <= APPROACH_RADIUS_M:
        return "APPROACHING"
    return "OUTSIDE"


def latest_valid_trips(trips: list[dict[str, Any]], now: datetime | None = None) -> dict[str, dict[str, Any]]:
    current = now or datetime.now(timezone.utc)
    selected: dict[str, tuple[datetime, dict[str, Any]]] = {}
    fallback: dict[str, dict[str, Any]] = {}
    for trip in trips:
        plate = str(trip.get("plate") or "").strip()
        if not plate:
            continue
        fallback.setdefault(plate, trip)
        coordinate = trip.get("position") or {}
        timestamp = parse_position_time(trip.get("communicated_at"), current)
        if timestamp is None or not valid_coordinate(coordinate.get("latitude"), coordinate.get("longitude")):
            continue
        if plate not in selected or timestamp > selected[plate][0]:
            selected[plate] = (timestamp, trip)
    return {plate: selected.get(plate, (current, value))[1] for plate, value in fallback.items()}


class OperationalSiteService:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(Path(database_path).resolve())
        self._lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        with self._lock, self.connect() as connection:
            connection.executescript(SITE_SCHEMA)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(operational_sites)")}
            if "address" not in columns:
                connection.execute("ALTER TABLE operational_sites ADD COLUMN address TEXT")
            if "municipality" not in columns:
                connection.execute("ALTER TABLE operational_sites ADD COLUMN municipality TEXT")
            connection.commit()

    def upsert_authorized_sites(self) -> dict[str, int]:
        now = utc_now()
        created = updated = aliases = 0
        with self._lock, self.connect() as connection:
            for item in AUTHORIZED_SITE_ALIASES:
                site_id = item["id"]
                row = connection.execute("SELECT id FROM operational_sites WHERE id=?", (site_id,)).fetchone()
                values = (
                    site_id, item.get("name", item["code"]), item["operation"], item.get("address"), item.get("municipality"), item["latitude"], item["longitude"],
                    APPROACH_RADIUS_M, ENTRY_RADIUS_M, EXIT_RADIUS_M, now, now,
                )
                connection.execute(
                    """INSERT INTO operational_sites
                       (id,name,operation,address,municipality,latitude,longitude,approach_radius_m,entry_radius_m,exit_radius_m,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET name=excluded.name,operation=excluded.operation,
                         address=excluded.address,municipality=excluded.municipality,
                         latitude=excluded.latitude,longitude=excluded.longitude,
                         approach_radius_m=excluded.approach_radius_m,entry_radius_m=excluded.entry_radius_m,
                         exit_radius_m=excluded.exit_radius_m,updated_at=excluded.updated_at""",
                    values,
                )
                created += int(row is None)
                updated += int(row is not None)
                connection.execute(
                    """INSERT INTO operational_site_aliases(alias_code,site_id,operation,created_at,updated_at)
                       VALUES(?,?,?,?,?) ON CONFLICT(alias_code) DO UPDATE SET
                       site_id=excluded.site_id,operation=excluded.operation,updated_at=excluded.updated_at""",
                    (item["code"], site_id, item["operation"], now, now),
                )
                aliases += 1
            # O ID legado permanece fisicamente no banco quando já existia,
            # preservando referências históricas, mas deixa de representar um
            # segundo ponto no mapa ou nas contagens.
            connection.execute(
                "UPDATE operational_sites SET active=0,updated_at=? WHERE id=?",
                (now, CARIACICA_LEGACY_SITE_ID),
            )
            connection.execute(
                """UPDATE operational_site_aliases SET site_id=?,updated_at=?
                   WHERE site_id=?""",
                (CARIACICA_CANONICAL_SITE_ID, now, CARIACICA_LEGACY_SITE_ID),
            )
            connection.commit()
        return {"created": created, "updated": updated, "aliases": aliases}

    def sites(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT s.*,group_concat(a.alias_code,'|') aliases
                   FROM operational_sites s LEFT JOIN operational_site_aliases a ON a.site_id=s.id
                   WHERE s.active=1 GROUP BY s.id ORDER BY s.name"""
            ).fetchall()
        return [
            {
                **dict(row),
                "active": bool(row["active"]),
                "aliases": str(row["aliases"] or "").split("|") if row["aliases"] else [],
            }
            for row in rows
        ]

    def recognize_trips(self, trips: list[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
        current = now or datetime.now(timezone.utc)
        sites = self.sites()
        with self._lock, self.connect() as connection:
            previous = {
                row["plate"]: dict(row)
                for row in connection.execute("SELECT * FROM vehicle_site_states").fetchall()
            }
            selected_trips = latest_valid_trips(trips, current)
            for plate, trip in selected_trips.items():
                coordinate = trip.get("position") or {}
                position_at = parse_position_time(trip.get("communicated_at"), current)
                latitude, longitude = coordinate.get("latitude"), coordinate.get("longitude")
                if not plate:
                    continue
                if not valid_coordinate(latitude, longitude) or position_at is None or bool(trip.get("stale")):
                    state = {
                        "site_id": None, "site_name": None, "operation": None,
                        "state": "UNAVAILABLE", "distance_m": None,
                        "position_at": trip.get("communicated_at"),
                        "diagnostic": {"reason": "stale_position" if trip.get("stale") else "invalid_or_missing_position"},
                    }
                else:
                    distances = sorted(
                        (geodesic_distance_m(latitude, longitude, site["latitude"], site["longitude"]), site)
                        for site in sites
                    )
                    distance, site = distances[0]
                    old = previous.get(plate) or {}
                    old_state = old.get("state") if old.get("site_id") == site["id"] else None
                    state_name = derived_site_state(distance, old_state)
                    state = {
                        "site_id": site["id"], "site_name": site["name"], "operation": site["operation"],
                        "state": state_name, "distance_m": round(distance, 1),
                        "position_at": position_at.isoformat(),
                        "diagnostic": {
                            "nearest_site": site["id"],
                            "overlap_candidates": [
                                candidate["id"] for candidate_distance, candidate in distances
                                if candidate_distance <= APPROACH_RADIUS_M
                            ],
                            "hysteresis_preserved": 500 < distance <= 650 and old_state == "INSIDE",
                            "confirmed_exit": old_state == "INSIDE" and distance > 650,
                        },
                    }
                for matching_trip in trips:
                    if str(matching_trip.get("plate") or "").strip() == plate:
                        matching_trip["operational_site"] = state
                connection.execute(
                    """INSERT INTO vehicle_site_states
                       (plate,site_id,state,distance_m,latitude,longitude,position_at,stale,diagnostic_json,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(plate) DO UPDATE SET site_id=excluded.site_id,state=excluded.state,
                       distance_m=excluded.distance_m,latitude=excluded.latitude,longitude=excluded.longitude,
                       position_at=excluded.position_at,stale=excluded.stale,
                       diagnostic_json=excluded.diagnostic_json,updated_at=excluded.updated_at""",
                    (
                        plate, state["site_id"], state["state"], state["distance_m"],
                        latitude if valid_coordinate(latitude, longitude) else None,
                        longitude if valid_coordinate(latitude, longitude) else None,
                        state["position_at"], int(bool(trip.get("stale"))),
                        json.dumps(state["diagnostic"], ensure_ascii=False), utc_now(),
                    ),
                )
            connection.commit()
        return trips

    def states(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT v.*,s.name site_name,s.operation FROM vehicle_site_states v
                   LEFT JOIN operational_sites s ON s.id=v.site_id ORDER BY v.plate"""
            ).fetchall()
        result = []
        for row in rows:
            value = dict(row)
            value["stale"] = bool(value["stale"])
            value["diagnostic"] = json.loads(value.pop("diagnostic_json") or "{}")
            result.append(value)
        return result


operational_site_service = OperationalSiteService(get_settings().operations_database_path)
