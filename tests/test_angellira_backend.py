from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.angellira import get_angellira_service, router
from app.services.angellira import AngelLiraService, DatasetValidationError, DwellObservation
from app.storage.angellira import AngelLiraRepository


PACKAGE = Path("data/angellira/2026-07-23-v1")
pytestmark = pytest.mark.skipif(
    not (PACKAGE / "angellira_dataset_manifest.json").is_file(),
    reason="authorized AngelLira source package is not present in this checkout",
)


@pytest.fixture
def service(tmp_path: Path) -> AngelLiraService:
    return AngelLiraService(AngelLiraRepository(tmp_path / "operations.db"))


def test_import_validates_counts_and_is_idempotent(service: AngelLiraService) -> None:
    first = service.import_package(PACKAGE, "tester")
    second = service.import_package(PACKAGE, "tester")
    assert first["status"] == "imported"
    assert second["status"] == "unchanged"
    status = service.status()
    assert status["stations"]["total"] == 197
    assert status["stations"]["by_status"] == {"not_geocoded": 180, "pending_review": 17}
    assert sum(item["manual_review_required"] for item in service.repository.stations()) == 127
    assert all(
        item["manual_review_required"]
        for item in service.repository.stations()
        if item["map_validation_status"] == "pending_review"
    )
    assert status["risk_areas"] == {
        "total": 28, "validated_geometries": 0, "visible": 0, "dwell_eligible": 0
    }
    with service.repository.connect() as connection:
        assert connection.execute("SELECT count(*) FROM angellira_station_variants").fetchone()[0] == 111
        assert connection.execute("SELECT count(*) FROM angellira_import_events").fetchone()[0] == 2


def test_invalid_checksum_rolls_back(service: AngelLiraService, tmp_path: Path) -> None:
    copied = tmp_path / "package"
    shutil.copytree(PACKAGE, copied)
    station_path = copied / "postos_homologados_limpos.csv"
    station_path.write_text(station_path.read_text("utf-8") + "\n", encoding="utf-8")
    with pytest.raises(DatasetValidationError, match="Checksum inválido"):
        service.import_package(copied)
    assert service.status()["stations"]["total"] == 0


def test_risks_and_unvalidated_stations_are_never_map_features(service: AngelLiraService) -> None:
    service.import_package(PACKAGE)
    assert service.repository.stations(map_only=True) == []
    assert service.repository.risk_areas(map_only=True) == []


class FakeGeocoder:
    def __init__(self) -> None:
        self.calls = 0

    async def get_geocode(self, query: str) -> dict:
        self.calls += 1
        return {
            "results": [{
                "id": "poi-1", "type": "POI",
                "position": {"lat": -19.98, "lon": -44.26},
                "poi": {"name": "Posto"},
                "address": {
                    "municipality": "BETIM", "countrySubdivisionCode": "BR-MG",
                    "countryCodeISO3": "BRA", "streetName": "BR-381",
                },
            }]
        }


def test_explicit_geocode_is_cached_and_only_validated_is_visible(
    service: AngelLiraService,
) -> None:
    service.import_package(PACKAGE)
    fake = FakeGeocoder()
    corridor = [(-19.98, -44.26)]
    first = asyncio.run(service.geocode_batch(fake, limit=1, corridor=corridor))
    # O primeiro registro elegível pode não ser de Betim; portanto a evidência de UF
    # impede promoção indevida, mas a tentativa ainda fica persistida.
    assert first["attempted"] == 1
    assert fake.calls == 1
    with service.repository.connect() as connection:
        station = connection.execute(
            "SELECT post_id,geocode_query_hash FROM angellira_stations "
            "WHERE geocode_query_hash IS NOT NULL LIMIT 1"
        ).fetchone()
        # Resultados incompatíveis também saem da fila automática.
        assert station is not None
    second = asyncio.run(service.geocode_batch(fake, limit=1, corridor=corridor))
    assert second["attempted"] == 1  # próximo item, nunca repete a tentativa anterior
    assert fake.calls == 2


def test_city_centroid_is_rejected() -> None:
    station = {"city": "BETIM", "uf": "MG"}
    payload = {"results": [{
        "type": "Geography", "entityType": "Municipality",
        "position": {"lat": -19.9, "lon": -44.2},
        "address": {"municipality": "BETIM", "countrySubdivisionCode": "BR-MG",
                    "countryCodeISO3": "BRA"},
    }]}
    status, _, evidence = AngelLiraService._classify_geocode(station, payload, [(-19.9, -44.2)])
    assert status == "rejected"
    assert evidence["reason"] == "city_centroid_or_non_specific"


def test_read_only_api_defaults_to_safe_map_views(service: AngelLiraService) -> None:
    service.import_package(PACKAGE)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_angellira_service] = lambda: service
    client = TestClient(app)
    assert client.get("/angellira/stations?status=validated").json()["stations"] == []
    risks = client.get("/angellira/risk-areas").json()
    assert risks["risk_areas"] == []
    assert "não representa ocorrência confirmada" in risks["message"]
    assert client.get("/angellira/status").json()["stations"]["total"] == 197
    assert len(client.get("/angellira/admin").json()["review_queue"]["risk_areas"]) == 28


def _enable_area(service: AngelLiraService) -> str:
    service.import_package(PACKAGE)
    area_id = service.repository.risk_areas()[0]["risk_area_id"]
    with service.repository.connect() as connection:
        connection.execute(
            """UPDATE angellira_risk_areas SET geometry_type='Polygon',
               geometry_json=?,geometry_validation_status='validated',
               geometry_version='manual-v1',eligible_for_dwell=1 WHERE risk_area_id=?""",
            ('{"type":"Polygon","coordinates":[[[-45,-20],[-44,-20],[-44,-19],[-45,-19],[-45,-20]]]}',
             area_id),
        )
    return area_id


def test_dwell_stays_inactive_without_validated_geometry(service: AngelLiraService) -> None:
    service.import_package(PACKAGE)
    area_id = service.repository.risk_areas()[0]["risk_area_id"]
    result = service.observe_dwell(DwellObservation(
        "trip-1", area_id, datetime.now(timezone.utc), -19.5, -44.5,
        True, 0, True, False, None,
    ))
    assert result == {
        "status": "inactive", "reason": "geometry_not_validated", "episode_closed": False
    }


def test_dwell_attention_idempotent_critical_requires_factor_and_exit_closes(
    service: AngelLiraService,
) -> None:
    area_id = _enable_area(service)
    start = datetime.now(timezone.utc)

    def observe(minutes: int, **changes):
        values = {
            "trip_key": "trip-1", "risk_area_id": area_id,
            "recorded_at": start + timedelta(minutes=minutes),
            "latitude": -19.5, "longitude": -44.5, "trip_active": True,
            "position_age_minutes": 0, "inside_risk_area": True,
            "geometry_validated": True, "geometry_version": "manual-v1",
        }
        values.update(changes)
        return service.observe_dwell(DwellObservation(**values))

    assert observe(0)["reason"] == "insufficient_positions"
    assert observe(8)["reason"] == "insufficient_positions"
    attention = observe(15)
    assert attention["level"] == "ATTENTION" and attention["created"]
    assert observe(30)["level"] == "ATTENTION"
    critical = observe(31, second_factor="confirmed_deviation")
    assert critical["level"] == "CRITICAL" and not critical["created"]
    assert observe(32, inside_risk_area=False)["episode_closed"]
    with service.repository.connect() as connection:
        episodes = connection.execute(
            "SELECT level,status FROM angellira_risk_dwell_episodes"
        ).fetchall()
    assert [tuple(row) for row in episodes] == [("CRITICAL", "CLOSED")]


@pytest.mark.parametrize(
    "blocked_field,reason",
    [
        ("inside_official_geofence", "official_geofence_priority"),
        ("inside_validated_station", "validated_station_priority"),
        ("inside_official_route", "official_route_priority"),
        ("traffic_slow", "slow_traffic"),
        ("boundary_oscillation", "boundary_oscillation"),
        ("passage_detected", "passage"),
    ],
)
def test_dwell_conflict_and_false_positive_blocks(
    service: AngelLiraService, blocked_field: str, reason: str,
) -> None:
    area_id = _enable_area(service)
    values = {
        "trip_key": "trip-1", "risk_area_id": area_id,
        "recorded_at": datetime.now(timezone.utc), "latitude": -19.5, "longitude": -44.5,
        "trip_active": True, "position_age_minutes": 0, "inside_risk_area": True,
        "geometry_validated": True, "geometry_version": "manual-v1", blocked_field: True,
    }
    assert service.observe_dwell(DwellObservation(**values))["reason"] == reason
