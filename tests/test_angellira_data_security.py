from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.angellira import AngelLiraService, DatasetValidationError
from app.storage.angellira import AngelLiraRepository


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = PROJECT_ROOT / "data" / "angellira" / "2026-07-23-v1"
MANIFEST_PATH = DATASET_DIR / "angellira_dataset_manifest.json"
pytestmark = pytest.mark.skipif(
    not MANIFEST_PATH.is_file(),
    reason="authorized AngelLira source package is not present in this checkout",
)

EXPECTED_STATION_COLUMNS = {
    "post_id",
    "canonical_name",
    "city",
    "uf",
    "city_uf",
    "data_quality_status",
    "source_location_conflict",
    "map_validation_status",
    "latitude",
    "longitude",
    "manual_review_required",
}
EXPECTED_RISK_COLUMNS = {
    "risk_area_id",
    "canonical_name",
    "risk_type",
    "city",
    "uf",
    "geometry_validation_status",
    "geometry_trustworthy",
    "latitude",
    "longitude",
    "radius_m",
    "polygon_geojson",
    "display_on_map",
    "eligible_for_dwell_rule",
}


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _validate_package(root: Path) -> None:
    manifest = json.loads((root / "angellira_dataset_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != "angellira-betim-jaboatao":
        raise ValueError("invalid dataset id")
    if manifest.get("source_version") != "2026-07-23-v1":
        raise ValueError("invalid dataset version")

    station_columns, stations = _read_csv(root / "postos_homologados_limpos.csv")
    risk_columns, risks = _read_csv(root / "areas_risco_limpas.csv")
    if not EXPECTED_STATION_COLUMNS.issubset(station_columns):
        raise ValueError("invalid station schema")
    if not EXPECTED_RISK_COLUMNS.issubset(risk_columns):
        raise ValueError("invalid risk schema")

    counts = manifest.get("counts") or {}
    if len(stations) != counts.get("clean_exact_station_records"):
        raise ValueError("invalid station count")
    if len(risks) != counts.get("clean_risk_records"):
        raise ValueError("invalid risk count")

    checksums = manifest.get("checksums") or {}
    for filename in (
        "postos_homologados_limpos.csv",
        "areas_risco_limpas.csv",
        "angellira_areas_risco_validadas.geojson",
    ):
        if checksums.get(filename) != _sha256(root / filename):
            raise ValueError(f"invalid checksum: {filename}")


def _copy_dataset(tmp_path: Path) -> Path:
    target = tmp_path / "package" / "dados"
    target.mkdir(parents=True)
    for source in DATASET_DIR.iterdir():
        if source.is_file():
            (target / source.name).write_bytes(source.read_bytes())
    return target


def test_manifest_schema_counts_and_checksums_are_valid() -> None:
    _validate_package(DATASET_DIR)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["counts"]["clean_exact_station_records"] == 197
    assert manifest["counts"]["clean_risk_records"] == 28
    assert manifest["counts"]["validated_station_records"] == 0
    assert manifest["counts"]["validated_risk_geometries"] == 0


@pytest.mark.parametrize("mutation", ["version", "count", "checksum", "station_schema", "risk_schema"])
def test_corrupted_package_is_rejected(tmp_path: Path, mutation: str) -> None:
    root = _copy_dataset(tmp_path)
    manifest_path = root / "angellira_dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if mutation == "version":
        manifest["source_version"] = "untrusted-version"
    elif mutation == "count":
        manifest["counts"]["clean_exact_station_records"] = 198
    elif mutation == "checksum":
        manifest["checksums"]["postos_homologados_limpos.csv"] = "sha256:" + ("0" * 64)
    elif mutation == "station_schema":
        path = root / "postos_homologados_limpos.csv"
        path.write_text(path.read_text(encoding="utf-8").replace("post_id", "unsafe_id", 1), encoding="utf-8")
        manifest["checksums"][path.name] = _sha256(path)
    else:
        path = root / "areas_risco_limpas.csv"
        path.write_text(
            path.read_text(encoding="utf-8").replace("geometry_validation_status", "unsafe_status", 1),
            encoding="utf-8",
        )
        manifest["checksums"][path.name] = _sha256(path)

    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    service = AngelLiraService(AngelLiraRepository(tmp_path / "operations.db"))
    with pytest.raises(DatasetValidationError):
        service.import_package(root.parent)


def test_runtime_import_is_idempotent_and_keeps_every_record_separate(tmp_path: Path) -> None:
    package_data = _copy_dataset(tmp_path)
    repository = AngelLiraRepository(tmp_path / "operations.db")
    service = AngelLiraService(repository)

    first = service.import_package(package_data.parent, actor="security-test")
    second = service.import_package(package_data.parent, actor="security-test")

    assert first["status"] == "imported"
    assert second["status"] == "unchanged"
    assert len(repository.stations()) == 197
    assert len(repository.risk_areas()) == 28
    assert repository.stations(map_only=True) == []
    assert repository.risk_areas(map_only=True) == []
    queue = repository.review_queue()
    assert len(queue["variants"]) == 111
    assert len({item["possible_merge_group_id"] for item in queue["variants"]}) == 51
    assert len(queue["risk_areas"]) == 28


def test_database_constraints_block_unvalidated_map_content(tmp_path: Path) -> None:
    package_data = _copy_dataset(tmp_path)
    repository = AngelLiraRepository(tmp_path / "operations.db")
    AngelLiraService(repository).import_package(package_data.parent)
    station = repository.stations()[0]
    risk = repository.risk_areas()[0]

    with pytest.raises(Exception):
        with repository.connect() as connection:
            connection.execute(
                "UPDATE angellira_stations SET display_on_map=1 WHERE post_id=?",
                (station["post_id"],),
            )
    with pytest.raises(Exception):
        with repository.connect() as connection:
            connection.execute(
                "UPDATE angellira_risk_areas SET display_on_map=1, eligible_for_dwell=1 "
                "WHERE risk_area_id=?",
                (risk["risk_area_id"],),
            )


def test_variants_remain_separate_and_await_human_review() -> None:
    _, stations = _read_csv(DATASET_DIR / "postos_homologados_limpos.csv")
    _, variants = _read_csv(DATASET_DIR / "postos_variantes_para_revisao.csv")

    assert len(stations) == 197
    assert len(variants) == 111
    assert len({row["possible_merge_group_id"] for row in variants}) == 51
    assert all(not row["review_decision"].strip() for row in variants)
    assert all(not row["review_notes"].strip() for row in variants)
    assert len({row["post_id"] for row in stations}) == 197


def test_location_conflicts_are_pending_and_never_markers() -> None:
    _, stations = _read_csv(DATASET_DIR / "postos_homologados_limpos.csv")
    conflicts = [row for row in stations if row["source_location_conflict"].lower() == "true"]

    assert len(conflicts) == 3
    assert all(row["data_quality_status"] == "pending_review" for row in conflicts)
    assert all(row["manual_review_required"].lower() == "true" for row in conflicts)
    assert all(row["map_validation_status"] != "validated" for row in conflicts)


def test_only_validated_stations_can_become_map_markers() -> None:
    _, stations = _read_csv(DATASET_DIR / "postos_homologados_limpos.csv")
    markers = [
        row
        for row in stations
        if row["map_validation_status"] == "validated"
        and row["latitude"].strip()
        and row["longitude"].strip()
    ]

    assert markers == []
    assert all(row["map_validation_status"] == "not_geocoded" for row in stations)
    assert all(not row["latitude"].strip() and not row["longitude"].strip() for row in stations)


def test_current_risk_records_have_no_invented_geometry_or_alert_eligibility() -> None:
    _, risks = _read_csv(DATASET_DIR / "areas_risco_limpas.csv")
    geojson = json.loads(
        (DATASET_DIR / "angellira_areas_risco_validadas.geojson").read_text(encoding="utf-8")
    )

    assert len(risks) == 28
    assert geojson["type"] == "FeatureCollection"
    assert geojson["features"] == []
    assert all(row["geometry_validation_status"] == "not_available" for row in risks)
    assert all(row["geometry_trustworthy"].lower() == "false" for row in risks)
    assert all(row["display_on_map"].lower() == "false" for row in risks)
    assert all(row["eligible_for_dwell_rule"].lower() == "false" for row in risks)
    geometry_fields = ("latitude", "longitude", "radius_m", "polygon_geojson")
    assert all(not row[field].strip() for row in risks for field in geometry_fields)


def test_dwell_security_defaults_match_the_approved_policy() -> None:
    settings = Settings(_env_file=None)

    assert settings.angellira_dataset_path == "data/angellira/2026-07-23-v1"
    assert settings.risk_area_dwell_warning_minutes == 15
    assert settings.risk_area_dwell_critical_minutes == 30
    assert settings.risk_area_min_consecutive_positions == 3
    assert settings.risk_area_max_position_age_minutes == 10
    assert settings.risk_area_max_stop_movement_meters == 250
    assert settings.homologated_station_geofence_meters == 300


def test_production_code_has_no_station_specific_identity_or_coordinate_hardcode() -> None:
    _, stations = _read_csv(DATASET_DIR / "postos_homologados_limpos.csv")
    production_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (PROJECT_ROOT / "app").rglob("*.py")
    ).upper()

    # Long, distinctive identities must come from the versioned dataset, never source.
    distinctive_names = {
        re.sub(r"\s+", " ", row["canonical_name"].strip()).upper()
        for row in stations
        if len(row["canonical_name"].strip()) >= 18
    }
    assert not any(name in production_text for name in distinctive_names)
    assert "ANGELLIRA" not in production_text or "2026-07-23-V1" in production_text
