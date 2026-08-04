from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.storage.angellira import AngelLiraRepository, utc_now


EXPECTED_DATASET_ID = "angellira-betim-jaboatao"
EXPECTED_SOURCE_VERSION = "2026-07-23-v1"
REQUIRED_COUNTS = {
    "clean_exact_station_records": 197,
    "ready_for_geocoding_station_records": 180,
    "pending_review_station_records": 17,
    "clean_risk_records": 28,
    "validated_risk_geometries": 0,
}
STATION_COLUMNS = {
    "post_id", "canonical_name", "city", "uf", "road", "km", "phone",
    "data_quality_status", "data_quality_reason", "exact_group_id",
    "source_occurrences", "source_record_nos", "source_pages", "name_variants",
    "source_location_conflict", "map_validation_status", "source_file",
    "manual_review_required", "possible_merge_group_id",
}
RISK_COLUMNS = {
    "risk_area_id", "canonical_name", "risk_type", "city", "uf",
    "data_quality_status", "data_quality_reason", "geometry_validation_status",
    "geometry_trustworthy", "display_on_map", "eligible_for_dwell_rule",
    "source_record_nos", "source_pages", "source_file",
}
VARIANT_COLUMNS = {
    "possible_merge_group_id", "exact_group_id", "representative_name", "city_uf",
    "road", "km", "phone", "candidate_method", "candidate_reason",
}


class Geocoder(Protocol):
    async def get_geocode(self, query: str) -> dict[str, Any]: ...


class DatasetValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DwellObservation:
    trip_key: str
    risk_area_id: str
    recorded_at: datetime
    latitude: float
    longitude: float
    trip_active: bool
    position_age_minutes: float
    inside_risk_area: bool
    geometry_validated: bool
    geometry_version: str | None
    inside_official_geofence: bool = False
    inside_validated_station: bool = False
    inside_official_route: bool = False
    traffic_slow: bool = False
    boundary_oscillation: bool = False
    passage_detected: bool = False
    second_factor: str | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = set(reader.fieldnames or [])
        if not required.issubset(columns):
            raise DatasetValidationError(
                f"Schema inválido em {path.name}; faltam: {sorted(required - columns)}"
            )
        return list(reader)


class AngelLiraService:
    def __init__(self, repository: AngelLiraRepository) -> None:
        self.repository = repository

    def import_package(self, package_dir: str | Path, actor: str = "offline-import") -> dict[str, Any]:
        root = Path(package_dir)
        data = root / "dados" if (root / "dados").is_dir() else root
        manifest_path = data / "angellira_dataset_manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DatasetValidationError("Manifesto ausente ou inválido") from exc
        self._validate_manifest(manifest, data)
        stations = _csv(data / "postos_homologados_limpos.csv", STATION_COLUMNS)
        risks = _csv(data / "areas_risco_limpas.csv", RISK_COLUMNS)
        variants = _csv(data / "postos_variantes_para_revisao.csv", VARIANT_COLUMNS)
        counts = manifest["counts"]
        if len(stations) != counts["clean_exact_station_records"] or len(risks) != counts["clean_risk_records"]:
            raise DatasetValidationError("Contagens reais não correspondem ao manifesto")
        ready = sum(item["data_quality_status"] == "ready_for_geocoding" for item in stations)
        pending = sum(item["data_quality_status"] == "pending_review" for item in stations)
        if ready != counts["ready_for_geocoding_station_records"] or pending != counts["pending_review_station_records"]:
            raise DatasetValidationError("Distribuição de qualidade dos postos inválida")

        dataset_id = manifest["dataset_id"]
        version = manifest["source_version"]
        manifest_hash = _sha256(manifest_path)
        existing = self.repository.dataset(dataset_id, version)
        if existing:
            if existing["manifest_sha256"] != manifest_hash:
                raise DatasetValidationError("Mesma versão já importada com manifesto diferente")
            self._audit(dataset_id, version, "IMPORT_NOOP", {"reason": "same_manifest"}, actor)
            return {"status": "unchanged", "dataset": existing}

        now = utc_now()
        with self.repository._lock, self.repository.connect() as connection:
            connection.execute(
                "INSERT INTO angellira_dataset_versions VALUES(?,?,?,?,?,?,?,?)",
                (dataset_id, version, manifest["source_name"], manifest_hash, "imported",
                 json.dumps(counts, ensure_ascii=False), now, actor),
            )
            for item in stations:
                quality = item["data_quality_status"]
                map_status = "not_geocoded" if quality == "ready_for_geocoding" else "pending_review"
                connection.execute(
                    """INSERT INTO angellira_stations(
                       post_id,dataset_id,source_version,canonical_name,city,uf,road,km,phone,
                       data_quality_status,manual_review_required,possible_merge_group_id,
                       map_validation_status,display_on_map,evidence_json,
                       provenance_json,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (item["post_id"], dataset_id, version, item["canonical_name"], item["city"],
                     item["uf"], item["road"] or None, item["km"] or None, item["phone"] or None,
                     quality, int(item["manual_review_required"].lower() == "true"),
                     item["possible_merge_group_id"] or None, map_status, 0,
                     json.dumps({
                         "data_quality_reason": item["data_quality_reason"],
                         "source_location_conflict": item["source_location_conflict"].lower() == "true",
                         "name_variants": item["name_variants"],
                         "manual_review_required": item["manual_review_required"].lower() == "true",
                         "possible_merge_group_id": item["possible_merge_group_id"] or None,
                     }, ensure_ascii=False),
                     json.dumps({
                         "source_file": item["source_file"], "source_record_nos": item["source_record_nos"],
                         "source_pages": item["source_pages"], "exact_group_id": item["exact_group_id"],
                     }, ensure_ascii=False), now, now),
                )
            for item in variants:
                connection.execute(
                    """INSERT INTO angellira_station_variants(
                       dataset_id,source_version,possible_merge_group_id,exact_group_id,
                       representative_name,city_uf,road,km,phone,evidence_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (dataset_id, version, item["possible_merge_group_id"], item["exact_group_id"],
                     item["representative_name"], item["city_uf"] or None, item["road"] or None,
                     item["km"] or None, item["phone"] or None,
                     json.dumps({"method": item["candidate_method"],
                                 "reason": item["candidate_reason"]}, ensure_ascii=False)),
                )
            for item in risks:
                # O pacote atual não possui geometria confiável. Campos do CSV não podem
                # promover visualização ou dwell por conta própria.
                connection.execute(
                    """INSERT INTO angellira_risk_areas(
                       risk_area_id,dataset_id,source_version,canonical_name,risk_type,city,uf,
                       data_quality_status,geometry_validation_status,display_on_map,
                       eligible_for_dwell,evidence_json,provenance_json,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (item["risk_area_id"], dataset_id, version, item["canonical_name"],
                     item["risk_type"], item["city"] or None, item["uf"] or None,
                     item["data_quality_status"], "not_available", 0, 0,
                     json.dumps({"reason": item["data_quality_reason"]}, ensure_ascii=False),
                     json.dumps({
                         "source_file": item["source_file"], "source_record_nos": item["source_record_nos"],
                         "source_pages": item["source_pages"],
                     }, ensure_ascii=False), now, now),
                )
            connection.execute(
                """INSERT INTO angellira_import_events
                   (dataset_id,source_version,event_type,details_json,actor,occurred_at)
                   VALUES(?,?,?,?,?,?)""",
                (dataset_id, version, "IMPORT_COMPLETED",
                 json.dumps({"stations": len(stations), "risks": len(risks),
                             "variants": len(variants)}, ensure_ascii=False), actor, now),
            )
        return {"status": "imported", "dataset": self.repository.dataset(dataset_id, version)}

    async def geocode_batch(
        self, geocoder: Geocoder, limit: int = 25, corridor: list[tuple[float, float]] | None = None
    ) -> dict[str, int]:
        """Executa somente quando chamado explicitamente; nunca é acionado pela API de leitura."""
        candidates = [
            item for item in self.repository.stations()
            if item["data_quality_status"] == "ready_for_geocoding"
            and item["map_validation_status"] == "not_geocoded"
        ][:max(0, limit)]
        summary = {"attempted": 0, "cached": 0, "validated": 0,
                   "probable": 0, "pending_review": 0, "rejected": 0}
        for station in candidates:
            query = self._query(station)
            query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
            with self.repository.connect() as connection:
                cached = connection.execute(
                    "SELECT status,error_code FROM angellira_geocode_attempts "
                    "WHERE post_id=? AND query_hash=?",
                    (station["post_id"], query_hash),
                ).fetchone()
            if cached and not cached["error_code"]:
                summary["cached"] += 1
                continue
            summary["attempted"] += 1
            try:
                payload = await geocoder.get_geocode(query)
                status, candidate, evidence = self._classify_geocode(station, payload, corridor)
                if station["manual_review_required"] and status == "validated":
                    status = "pending_review"
                    evidence["reason"] = "manual_review_required"
                position = (candidate or {}).get("position") or {}
                lat, lon = position.get("lat"), position.get("lon")
                with self.repository._lock, self.repository.connect() as connection:
                    connection.execute(
                        """INSERT INTO angellira_geocode_attempts(
                           post_id,query_hash,query_text,status,provider_result_id,latitude,longitude,
                           score,evidence_json,attempted_at) VALUES(?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(post_id,query_hash) DO UPDATE SET
                           status=excluded.status,provider_result_id=excluded.provider_result_id,
                           latitude=excluded.latitude,longitude=excluded.longitude,
                           score=excluded.score,evidence_json=excluded.evidence_json,
                           error_code=NULL,attempted_at=excluded.attempted_at""",
                        (station["post_id"], query_hash, query, status,
                         (candidate or {}).get("id"), lat, lon, evidence.get("score"),
                         json.dumps(evidence, ensure_ascii=False), utc_now()),
                    )
                    connection.execute(
                        """UPDATE angellira_stations SET map_validation_status=?,latitude=?,
                           longitude=?,geocoding_provider='TomTom',geocoding_confidence=?,
                           display_on_map=?,evidence_json=?,geocode_query_hash=?,
                           last_geocoded_at=?,updated_at=? WHERE post_id=?""",
                        (status, lat, lon, evidence.get("score"), int(status == "validated"),
                         json.dumps(evidence, ensure_ascii=False), query_hash, utc_now(), utc_now(),
                         station["post_id"]),
                    )
                summary[status] += 1
            except Exception as exc:
                # Não guarda corpo/resposta nem segredo.
                with self.repository.connect() as connection:
                    connection.execute(
                        """INSERT INTO angellira_geocode_attempts(
                           post_id,query_hash,query_text,status,evidence_json,error_code,attempted_at)
                           VALUES(?,?,?,?,?,?,?)
                           ON CONFLICT(post_id,query_hash) DO UPDATE SET
                           status=excluded.status,evidence_json=excluded.evidence_json,
                           error_code=excluded.error_code,attempted_at=excluded.attempted_at""",
                        (station["post_id"], query_hash, query, "pending_review", "{}",
                         type(exc).__name__, utc_now()),
                    )
                summary["pending_review"] += 1
        return summary

    def observe_dwell(
        self,
        observation: DwellObservation,
        warning_minutes: float = 15,
        critical_minutes: float = 30,
        min_positions: int = 3,
        max_position_age_minutes: float = 10,
        max_movement_m: float = 250,
    ) -> dict[str, Any]:
        """Motor futuro isolado; só processa áreas cuja geometria já foi validada."""
        now = observation.recorded_at.astimezone(timezone.utc).isoformat()
        area = next(
            (item for item in self.repository.risk_areas()
             if item["risk_area_id"] == observation.risk_area_id),
            None,
        )
        enabled = bool(
            area and area["geometry_validation_status"] == "validated"
            and area["eligible_for_dwell"] and observation.geometry_validated
            and observation.geometry_version
            and observation.geometry_version == area.get("geometry_version")
        )
        blocked_reason = None
        if not enabled:
            blocked_reason = "geometry_not_validated"
        elif not observation.trip_active:
            blocked_reason = "trip_not_active"
        elif observation.position_age_minutes > max_position_age_minutes:
            blocked_reason = "stale_position"
        elif observation.inside_official_geofence:
            blocked_reason = "official_geofence_priority"
        elif observation.inside_validated_station:
            blocked_reason = "validated_station_priority"
        elif observation.inside_official_route:
            blocked_reason = "official_route_priority"
        elif observation.traffic_slow:
            blocked_reason = "slow_traffic"
        elif observation.boundary_oscillation:
            blocked_reason = "boundary_oscillation"
        elif observation.passage_detected:
            blocked_reason = "passage"

        with self.repository._lock, self.repository.connect() as connection:
            tracker = connection.execute(
                "SELECT * FROM angellira_risk_dwell_trackers WHERE trip_key=? AND risk_area_id=?",
                (observation.trip_key, observation.risk_area_id),
            ).fetchone()
            active = connection.execute(
                """SELECT * FROM angellira_risk_dwell_episodes
                   WHERE trip_key=? AND risk_area_id=? AND status='ACTIVE'
                   ORDER BY id DESC LIMIT 1""",
                (observation.trip_key, observation.risk_area_id),
            ).fetchone()
            if blocked_reason or not observation.inside_risk_area:
                if active:
                    connection.execute(
                        "UPDATE angellira_risk_dwell_episodes SET status='CLOSED',ended_at=? WHERE id=?",
                        (now, active["id"]),
                    )
                connection.execute(
                    "DELETE FROM angellira_risk_dwell_trackers WHERE trip_key=? AND risk_area_id=?",
                    (observation.trip_key, observation.risk_area_id),
                )
                return {"status": "inactive" if blocked_reason else "closed",
                        "reason": blocked_reason or "area_exit", "episode_closed": bool(active)}

            count = int(tracker["inside_count"]) + 1 if tracker else 1
            entered_at = tracker["entered_at"] if tracker else now
            first_lat = float(tracker["first_latitude"]) if tracker else observation.latitude
            first_lon = float(tracker["first_longitude"]) if tracker else observation.longitude
            previous_lat = float(tracker["last_latitude"]) if tracker else observation.latitude
            previous_lon = float(tracker["last_longitude"]) if tracker else observation.longitude
            movement = (float(tracker["movement_m"]) if tracker else 0.0) + _haversine(
                (previous_lat, previous_lon), (observation.latitude, observation.longitude)
            ) * 1000
            connection.execute(
                """INSERT INTO angellira_risk_dwell_trackers(
                   trip_key,risk_area_id,geometry_version,inside_count,entered_at,last_position_at,
                   first_latitude,first_longitude,last_latitude,last_longitude,movement_m,state,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(trip_key,risk_area_id) DO UPDATE SET
                   inside_count=excluded.inside_count,last_position_at=excluded.last_position_at,
                   last_latitude=excluded.last_latitude,last_longitude=excluded.last_longitude,
                   movement_m=excluded.movement_m,updated_at=excluded.updated_at""",
                (observation.trip_key, observation.risk_area_id, observation.geometry_version,
                 count, entered_at, now, first_lat, first_lon, observation.latitude,
                 observation.longitude, movement, "OBSERVING", now),
            )
            elapsed = (
                observation.recorded_at.astimezone(timezone.utc)
                - datetime.fromisoformat(entered_at)
            ).total_seconds() / 60
            if count < min_positions:
                return {"status": "observing", "reason": "insufficient_positions",
                        "inside_count": count, "dwell_minutes": elapsed}
            if movement > max_movement_m:
                return {"status": "observing", "reason": "vehicle_moving",
                        "movement_m": round(movement, 1), "dwell_minutes": elapsed}
            if elapsed < warning_minutes:
                return {"status": "observing", "reason": "below_warning_threshold",
                        "inside_count": count, "dwell_minutes": elapsed}
            level = (
                "CRITICAL" if elapsed >= critical_minutes and observation.second_factor
                else "ATTENTION"
            )
            if active:
                if level == "CRITICAL" and active["level"] != "CRITICAL":
                    connection.execute(
                        """UPDATE angellira_risk_dwell_episodes
                           SET level='CRITICAL',second_factor=?,evidence_json=? WHERE id=?""",
                        (observation.second_factor,
                         json.dumps({"dwell_minutes": elapsed, "movement_m": movement},
                                    ensure_ascii=False), active["id"]),
                    )
                elif active["level"] == "CRITICAL":
                    level = "CRITICAL"
                return {"status": "active", "level": level, "created": False,
                        "dwell_minutes": elapsed}
            key = f"{observation.trip_key}:{observation.risk_area_id}:{entered_at}"
            connection.execute(
                """INSERT OR IGNORE INTO angellira_risk_dwell_episodes(
                   trip_key,risk_area_id,geometry_version,level,status,started_at,second_factor,
                   evidence_json,idempotency_key,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (observation.trip_key, observation.risk_area_id, observation.geometry_version,
                 level, "ACTIVE", entered_at, observation.second_factor,
                 json.dumps({"dwell_minutes": elapsed, "movement_m": movement}, ensure_ascii=False),
                 key, now),
            )
            return {"status": "active", "level": level, "created": True,
                    "dwell_minutes": elapsed}

    def status(self) -> dict[str, Any]:
        dataset = self.repository.latest_dataset()
        stations = self.repository.stations()
        risks = self.repository.risk_areas()
        by_status: dict[str, int] = {}
        for item in stations:
            by_status[item["map_validation_status"]] = by_status.get(item["map_validation_status"], 0) + 1
        return {
            "dataset": dataset,
            "stations": {"total": len(stations), "by_status": by_status,
                         "visible": sum(item["display_on_map"] for item in stations)},
            "risk_areas": {"total": len(risks),
                           "validated_geometries": sum(
                               item["geometry_validation_status"] == "validated" for item in risks
                           ), "visible": sum(item["display_on_map"] for item in risks),
                           "dwell_eligible": sum(item["eligible_for_dwell"] for item in risks)},
        }

    @staticmethod
    def _validate_manifest(manifest: dict[str, Any], data: Path) -> None:
        if manifest.get("dataset_id") != EXPECTED_DATASET_ID:
            raise DatasetValidationError("dataset_id inesperado")
        if manifest.get("source_version") != EXPECTED_SOURCE_VERSION:
            raise DatasetValidationError("source_version inesperada")
        if not manifest.get("source_name"):
            raise DatasetValidationError("Fonte ausente")
        counts = manifest.get("counts") or {}
        if any(counts.get(key) != value for key, value in REQUIRED_COUNTS.items()):
            raise DatasetValidationError("Contagens declaradas não são as esperadas")
        checksums = manifest.get("checksums") or {}
        required_files = {
            "postos_homologados_limpos.csv",
            "areas_risco_limpas.csv",
            "angellira_areas_risco_validadas.geojson",
        }
        if set(checksums) != required_files:
            raise DatasetValidationError("Lista de checksums inválida")
        for name, expected in checksums.items():
            path = data / name
            if not path.is_file() or _sha256(path).lower() != str(expected).lower():
                raise DatasetValidationError(f"Checksum inválido: {name}")
        try:
            geojson = json.loads((data / "angellira_areas_risco_validadas.geojson").read_text("utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DatasetValidationError("GeoJSON inválido") from exc
        if geojson.get("type") != "FeatureCollection" or geojson.get("features") != []:
            raise DatasetValidationError("GeoJSON atual deve permanecer vazio")

    def _audit(self, dataset_id: str, version: str, event: str,
               details: dict[str, Any], actor: str) -> None:
        with self.repository.connect() as connection:
            connection.execute(
                """INSERT INTO angellira_import_events
                   (dataset_id,source_version,event_type,details_json,actor,occurred_at)
                   VALUES(?,?,?,?,?,?)""",
                (dataset_id, version, event, json.dumps(details, ensure_ascii=False), actor, utc_now()),
            )

    @staticmethod
    def _query(station: dict[str, Any]) -> str:
        parts = [station["canonical_name"], station["city"], station["uf"]]
        if station.get("road"):
            parts.append(station["road"])
        if station.get("km"):
            parts.append(f"km {station['km']}")
        return ", ".join(part for part in parts if part) + ", Brasil"

    @staticmethod
    def _classify_geocode(
        station: dict[str, Any], payload: dict[str, Any],
        corridor: list[tuple[float, float]] | None,
    ) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
        results = payload.get("results") or []
        if not results:
            return "pending_review", None, {"reason": "no_results"}
        candidate = results[0]
        address = candidate.get("address") or {}
        entity = str(candidate.get("entityType") or candidate.get("type") or "").lower()
        poi = candidate.get("poi") or {}
        city = str(address.get("municipality") or "").upper()
        country = str(address.get("countryCodeISO3") or address.get("countryCode") or "").upper()
        subdivision = str(address.get("countrySubdivisionCode") or address.get("countrySubdivision") or "").upper()
        position = candidate.get("position") or {}
        try:
            lat, lon = float(position["lat"]), float(position["lon"])
        except (KeyError, TypeError, ValueError):
            return "pending_review", candidate, {"reason": "missing_coordinates"}
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return "rejected", candidate, {"reason": "invalid_coordinates"}
        if entity in {"municipality", "municipalitysubdivision", "geography"} or (not poi and not address.get("streetName")):
            return "rejected", candidate, {"reason": "city_centroid_or_non_specific"}
        uf_ok = station["uf"] in subdivision or subdivision.endswith("-" + station["uf"])
        city_ok = _normalize(station["city"]) == _normalize(city)
        country_ok = country in {"BRA", "BR"}
        distance_km = _corridor_distance_km((lat, lon), corridor) if corridor else None
        corridor_ok = distance_km is not None and distance_km <= 15
        score = sum((country_ok, uf_ok, city_ok, bool(poi), corridor_ok)) / 5
        evidence = {
            "country_match": country_ok, "uf_match": uf_ok, "city_match": city_ok,
            "poi_present": bool(poi), "corridor_distance_km": round(distance_km, 2)
            if distance_km is not None else None, "score": score,
        }
        if not country_ok or not uf_ok:
            return "rejected", candidate, evidence
        if city_ok and poi and corridor_ok and (len(results) == 1 or score >= 0.8):
            return "validated", candidate, evidence
        if city_ok and (poi or address.get("streetName")):
            return "probable", candidate, evidence
        return "pending_review", candidate, evidence


def _normalize(value: str) -> str:
    import unicodedata
    return "".join(
        char for char in unicodedata.normalize("NFKD", value or "")
        if not unicodedata.combining(char)
    ).strip().upper()


def _corridor_distance_km(
    point: tuple[float, float], corridor: list[tuple[float, float]] | None
) -> float | None:
    if not corridor:
        return None
    return min(_haversine(point, candidate) for candidate in corridor)


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    radius = 6371.0
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlon = lat2 - lat1, math.radians(b[1] - a[1])
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))
