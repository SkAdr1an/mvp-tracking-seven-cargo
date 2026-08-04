from __future__ import annotations

import json
from pathlib import Path

from app.core.config import Settings
from app.services.portal_homologation import summarize_homologation


FIXTURE = Path(__file__).parent / "fixtures" / "driver_portal_homologation.json"


def test_pilot_allowlist_is_closed_by_default_and_exact() -> None:
    settings = Settings(
        driver_mobile_location_enabled=True,
        driver_portal_alerts_enabled=True,
        driver_portal_pilot_trip_keys="trip-a, trip-b",
    )
    assert settings.driver_portal_feature_allowed("trip-a", settings.driver_mobile_location_enabled)
    assert settings.driver_portal_feature_allowed("trip-b", settings.driver_portal_alerts_enabled)
    assert not settings.driver_portal_feature_allowed("trip-c", settings.driver_portal_alerts_enabled)
    settings.driver_portal_pilot_trip_keys = ""
    assert not settings.driver_portal_feature_allowed("trip-a", True)
    assert not settings.driver_portal_feature_allowed("*", True)


def test_homologation_metrics_use_only_explicit_fixture_events() -> None:
    events = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = summarize_homologation(events)
    assert result == {
        "positions_received": 3,
        "positions_accepted_percent": 66.7,
        "mobile_position_average_age_seconds": 30.0,
        "trafegus_availability_percent": 50.0,
        "mobile_complementary_seconds": 120,
        "alerts_presented": 1,
        "repeated_alerts_blocked": 1,
        "alerts_discarded_behind": 1,
        "alerts_discarded_stale": 1,
        "source_divergences": 1,
        "failures_by_platform_browser": {"iOS/Safari": 1},
    }


def test_required_scenario_matrix_is_complete() -> None:
    matrix = json.loads((FIXTURE.parent / "driver_portal_scenarios.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in matrix] == list(range(1, 33))
    assert all(item["automated"] and item["evidence"] for item in matrix)
    assert all(item["data_scope"] == "fixture_or_mock" for item in matrix)
