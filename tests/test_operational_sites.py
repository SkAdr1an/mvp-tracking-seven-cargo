from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from app.integrations.trafegus import TrafegusClient
from app.services.operational_sites import (
    AUTHORIZED_SITE_ALIASES,
    OperationalSiteService,
    derived_site_state,
    geodesic_distance_m,
    latest_valid_trips,
    valid_coordinate,
)


NOW = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)


def service(tmp_path):
    return OperationalSiteService(tmp_path / "operations.db")


def trip(plate="ABC1D23", latitude=-23.719457759779772, longitude=-46.60073995582935, at=NOW):
    return {
        "plate": plate,
        "driver": "Motorista Teste",
        "trip_id": "existing-trip",
        "route": "existing-route",
        "position": {"latitude": latitude, "longitude": longitude},
        "communicated_at": at.isoformat(),
        "stale": False,
    }


def test_registers_all_aliases_as_22_physical_sites(tmp_path):
    registry = service(tmp_path)
    sites = registry.sites()
    assert len(AUTHORIZED_SITE_ALIASES) == 24
    assert len(sites) == 22
    assert sum(len(item["aliases"]) for item in sites) == 24
    assert all(item["entry_radius_m"] == 500 for item in sites)
    assert all(item["exit_radius_m"] == 650 for item in sites)
    assert all(item["approach_radius_m"] == 1000 for item in sites)


def test_upsert_is_idempotent_and_preserves_ids(tmp_path):
    registry = service(tmp_path)
    before = {item["name"]: item["id"] for item in registry.sites()}
    first = registry.upsert_authorized_sites()
    second = registry.upsert_authorized_sites()
    after = {item["name"]: item["id"] for item in registry.sites()}
    assert before == after
    assert first["created"] == second["created"] == 0
    assert first["aliases"] == second["aliases"] == 24


def test_curitiba_reference_is_one_active_site_with_address_and_alias(tmp_path):
    registry = service(tmp_path)
    matches = [item for item in registry.sites() if item["id"] == "soc-pr-curitiba"]
    assert len(matches) == 1
    site = matches[0]
    assert site["aliases"] == ["SoC_PR_CURITIBA/PR"]
    assert site["address"] == "Rodovia Régis Bittencourt, 1500"
    assert site["municipality"] == "Campina Grande do Sul/PR"
    assert site["latitude"] == -25.349037664133935
    assert site["longitude"] == -49.058775032429246


def test_sanitized_roeliton_position_is_inside_curitiba_cd(tmp_path):
    registry = service(tmp_path)
    value = trip(plate="ADU5F54", latitude=-25.3505555556, longitude=-49.0605555556)
    registry.recognize_trips([value], NOW)
    state = value["operational_site"]
    assert state["site_id"] == "soc-pr-curitiba"
    assert state["state"] == "INSIDE"
    assert state["distance_m"] == pytest.approx(246.0, abs=.1)


def test_stale_position_never_confirms_presence(tmp_path):
    registry = service(tmp_path)
    value = trip(plate="STALE01", latitude=-25.349037664133935, longitude=-49.058775032429246)
    value["stale"] = True
    registry.recognize_trips([value], NOW)
    assert value["operational_site"]["state"] == "UNAVAILABLE"
    assert value["operational_site"]["diagnostic"]["reason"] == "stale_position"


def test_wne_aliases_share_one_point_without_duplicate_radius(tmp_path):
    sites = service(tmp_path).sites()
    wne = [item for item in sites if item["id"] == "wne-cabo-santo-agostinho"]
    assert len(wne) == 1
    assert set(wne[0]["aliases"]) == {
        "WNE MATRIZ - CABO DE SANTO AGOSTINHO/PE",
        "WNE FILIAL - CABO DE SANTO AGOSTINHO/PE",
    }


def test_cariacica_aliases_share_canonical_point_and_preserve_legacy_id(tmp_path):
    registry = service(tmp_path)
    sites = registry.sites()
    cariacica = [item for item in sites if item["id"] == "mb-importacao-matriz-cariacica"]
    assert len(cariacica) == 1
    assert set(cariacica[0]["aliases"]) == {
        "MB IMPORTAÇÃO MATRIZ - CARIACICA/ES",
        "MB IMPORTAÇÃO FILIAL - CARIACICA/ES",
    }
    with registry.connect() as connection:
        legacy = connection.execute(
            "SELECT active FROM operational_sites WHERE id='mb-importacao-filial-cariacica'"
        ).fetchone()
        if legacy is not None:
            assert legacy["active"] == 0


def test_nearby_sao_bernardo_and_guarulhos_sites_remain_distinct(tmp_path):
    sites = service(tmp_path).sites()
    sao = [item for item in sites if "sao-bernardo" in item["id"]]
    guarulhos = [item for item in sites if "guarulhos" in item["id"] or "cumbica" in item["id"]]
    assert {item["id"] for item in sao} == {"soc-sp-sao-bernardo-ceva", "soc-sp-sao-bernardo-modern"}
    assert len(guarulhos) == 3
    assert geodesic_distance_m(sao[0]["latitude"], sao[0]["longitude"], sao[1]["latitude"], sao[1]["longitude"]) > 1


@pytest.mark.parametrize(
    "distance,previous,expected",
    [
        (0, None, "INSIDE"), (500, None, "INSIDE"),
        (500.1, "INSIDE", "INSIDE"), (650, "INSIDE", "INSIDE"),
        (500.1, "OUTSIDE", "APPROACHING"), (650, None, "APPROACHING"),
        (650.1, "INSIDE", "APPROACHING"), (1000, None, "APPROACHING"),
        (1000.1, None, "OUTSIDE"),
    ],
)
def test_entry_hysteresis_approach_and_exit_boundaries(distance, previous, expected):
    assert derived_site_state(distance, previous) == expected


def test_geodesic_distance_is_in_meters():
    assert geodesic_distance_m(0, 0, 0, 0) == 0
    assert geodesic_distance_m(0, 0, 0, 0.001) == pytest.approx(111.2, abs=0.5)


@pytest.mark.parametrize(
    "latitude,longitude",
    [(None, -44), (float("nan"), -44), (float("inf"), -44), (91, -44), (-23, 181)],
)
def test_invalid_coordinates_are_rejected(latitude, longitude):
    assert valid_coordinate(latitude, longitude) is False


def test_latest_valid_position_uses_timestamp_not_input_order():
    old = trip(at=NOW - timedelta(hours=2), latitude=-20, longitude=-40)
    newest = trip(at=NOW, latitude=-21, longitude=-41)
    assert latest_valid_trips([newest, old], NOW)["ABC1D23"] is newest
    assert latest_valid_trips([old, newest], NOW)["ABC1D23"] is newest


def test_future_invalid_position_does_not_replace_last_valid():
    valid = trip(at=NOW)
    future = trip(at=NOW + timedelta(hours=1), latitude=-10, longitude=-30)
    assert latest_valid_trips([valid, future], NOW)["ABC1D23"] is valid


def test_vehicle_without_valid_position_is_recoverable(tmp_path):
    registry = service(tmp_path)
    values = [{"plate": "NOLOC1", "position": None, "communicated_at": None}]
    registry.recognize_trips(values, NOW)
    assert values[0]["operational_site"]["state"] == "UNAVAILABLE"


def test_recognition_is_immediate_and_does_not_change_trip_or_route(tmp_path):
    registry = service(tmp_path)
    value = trip()
    original = {key: value[key] for key in ("trip_id", "route", "position")}
    registry.recognize_trips([value], NOW)
    assert value["operational_site"]["state"] == "INSIDE"
    assert value["operational_site"]["distance_m"] == 0
    assert {key: value[key] for key in original} == original
    assert registry.states()[0]["state"] == "INSIDE"


def test_repeated_recognition_does_not_create_events_or_routes(tmp_path):
    registry = service(tmp_path)
    values = [trip()]
    registry.recognize_trips(values, NOW)
    registry.recognize_trips(values, NOW)
    with registry.connect() as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "route_configs" not in tables
        assert "operational_events" not in tables
        assert connection.execute("SELECT count(*) FROM vehicle_site_states").fetchone()[0] == 1


def test_trafegus_remains_read_only_and_no_route_geometry_is_created():
    source = inspect.getsource(TrafegusClient)
    assert "client.put(" not in source
    assert "client.patch(" not in source
    assert "client.delete(" not in source
    sites_source = inspect.getsource(OperationalSiteService)
    assert "route_configs" not in sites_source
    assert "route_geometry" not in sites_source
