from __future__ import annotations

import inspect

from app.core.config import get_settings
from app.services.fleet_tracking import FleetTrackingService
from app.services.route_deviation import RouteDeviationService


def test_automatic_fleet_routing_is_disabled_by_default():
    assert get_settings().fleet_routing_enabled is False
    source = inspect.getsource(FleetTrackingService._enrich_trips)
    assert source.index("fleet_routing_enabled") < source.index("_enrich_prediction")


def test_geometry_bootstrap_never_calls_external_provider_without_explicit_permission(tmp_path):
    class Repository:
        pass

    source = inspect.getsource(RouteDeviationService.ensure_geometry)
    assert "allow_external:bool=False" in source.replace(" ", "")
    assert source.index("if not allow_external") < source.index("RoutingProviderService")
