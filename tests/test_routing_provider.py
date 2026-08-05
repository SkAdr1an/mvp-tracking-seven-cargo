from __future__ import annotations

import pytest

from app.integrations.openrouteservice import _coordinates, _normalize
from app.integrations.tomtom import AuthError, UpstreamError, UnavailableError
from app.services.routing_provider import (
    RoutingProviderService, RoutingProvidersFailed,
)


def geometry(provider=None):
    value = {"routes": [{"legs": [{"points": [
        {"latitude": -20.0, "longitude": -44.0},
        {"latitude": -19.0, "longitude": -43.0},
    ]}], "summary": {}}]}
    if provider:
        value["_provider"] = provider
    return value


class Client:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0

    async def get_route(self, *_args, **_kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


@pytest.mark.asyncio
async def test_tomtom_success_never_calls_fallback():
    primary, fallback = Client(geometry()), Client(geometry())
    result = await RoutingProviderService(primary, fallback).get_route("-20,-44", "-19,-43")
    assert result["_provider"] == "TomTom"
    assert primary.calls == 1
    assert fallback.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    AuthError("forbidden", 403, "InsufficientFunds"),
    AuthError("unauthorized", 401, "Unauthorized"),
    UnavailableError("timeout"),
    UpstreamError("TomTom", 503, "unavailable"),
])
async def test_eligible_primary_failure_calls_fallback_once(error):
    primary, fallback = Client(error=error), Client(geometry("OpenRouteService"))
    result = await RoutingProviderService(primary, fallback).get_route("-20,-44", "-19,-43")
    assert result["_provider"] == "OpenRouteService"
    assert primary.calls == fallback.calls == 1


@pytest.mark.asyncio
async def test_invalid_primary_geometry_uses_fallback():
    primary, fallback = Client({"routes": []}), Client(geometry())
    result = await RoutingProviderService(primary, fallback).get_route("-20,-44", "-19,-43")
    assert result["_provider"] == "OpenRouteService"
    assert primary.calls == fallback.calls == 1


@pytest.mark.asyncio
async def test_invalid_request_does_not_call_fallback():
    primary = Client(error=UpstreamError("TomTom", 400, "invalid request"))
    fallback = Client(geometry())
    with pytest.raises(UpstreamError):
        await RoutingProviderService(primary, fallback).get_route("bad", "data")
    assert primary.calls == 1
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_both_fail_once_and_errors_are_sanitized():
    primary = Client(error=AuthError("forbidden", 403, "InsufficientFunds"))
    fallback = Client(error=UnavailableError("ORS timeout"))
    with pytest.raises(RoutingProvidersFailed) as raised:
        await RoutingProviderService(primary, fallback).get_route("-20,-44", "-19,-43")
    assert primary.calls == fallback.calls == 1
    assert raised.value.primary_error["http_status"] == 403
    assert raised.value.fallback_error["type"] == "UnavailableError"


@pytest.mark.asyncio
async def test_concurrent_identical_requests_share_one_provider_call():
    import asyncio

    class Slow(Client):
        async def get_route(self, *_args, **_kwargs):
            self.calls += 1
            await asyncio.sleep(0.01)
            return self.result

    primary, fallback = Slow(geometry()), Client(geometry())
    service = RoutingProviderService(primary, fallback)
    first, second = await asyncio.gather(
        service.get_route("-20,-44", "-19,-43", travel_mode="truck"),
        service.get_route("-20,-44", "-19,-43", travel_mode="truck"),
    )
    assert first == second
    assert primary.calls == 1
    assert fallback.calls == 0


def test_openrouteservice_uses_hgv_coordinate_order_and_normalizes_geometry():
    assert _coordinates("-20,-44:-19.5,-43.5", "-19,-43") == [
        [-44.0, -20.0], [-43.5, -19.5], [-43.0, -19.0]
    ]
    result = _normalize({"features": [{
        "geometry": {"coordinates": [[-44, -20], [-43, -19]]},
        "properties": {"summary": {"distance": 1000, "duration": 120}},
    }]})
    assert result["routes"][0]["legs"][0]["points"][0] == {
        "latitude": -20.0, "longitude": -44.0,
    }
    assert result["routes"][0]["summary"]["travelTimeInSeconds"] == 120
