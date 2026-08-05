from __future__ import annotations

import asyncio

import httpx
import pytest

from app.integrations.trafegus import TrafegusClient, TrafegusError
from app.services import fleet_tracking as fleet_module
from app.services.fleet_tracking import FleetTrackingService


def client(**overrides) -> TrafegusClient:
    return TrafegusClient(
        username=overrides.pop("username", "user"),
        password=overrides.pop("password", "password"),
        document=overrides.pop("document", "12345678000199"),
        base_url="https://example.test/api",
        **overrides,
    )


def test_missing_configuration_names_the_absent_variable() -> None:
    configured = client(document="")
    configured.document = ""
    with pytest.raises(TrafegusError) as raised:
        configured._validate_config()
    assert raised.value.phase == "configuration"
    assert "TRAFEGUS_DOCUMENTO" in str(raised.value)


@pytest.mark.asyncio
async def test_rejected_credentials_are_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": "invalid"}, request=request)

    configured = client()
    configured.retry_attempts = 2
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
        with pytest.raises(TrafegusError) as raised:
            await configured._authenticate(session)
    assert calls == 1
    assert raised.value.category == "credentials"
    assert raised.value.http_status == 401


@pytest.mark.asyncio
async def test_timeout_retries_with_limit_and_reports_cause(monkeypatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timed out", request=request)

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("app.integrations.trafegus.asyncio.sleep", no_sleep)
    configured = client()
    configured.retry_attempts = 2
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
        with pytest.raises(TrafegusError) as raised:
            await configured._request_with_retry(session, "GET", "/fleet", phase="fleet_query")
    assert calls == 3
    assert raised.value.category == "timeout"


@pytest.mark.asyncio
async def test_transient_503_is_retried_then_succeeds(monkeypatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503 if calls == 1 else 200, json={}, request=request)

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("app.integrations.trafegus.asyncio.sleep", no_sleep)
    configured = client()
    configured.retry_attempts = 2
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
        response = await configured._request_with_retry(session, "GET", "/fleet", phase="fleet_query")
    assert response.status_code == 200
    assert calls == 2


@pytest.mark.asyncio
async def test_expired_session_is_renewed_once() -> None:
    login_calls = 0
    get_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal login_calls, get_calls
        if request.method == "POST":
            login_calls += 1
            return httpx.Response(200, json={"success": {"token": f"token-{login_calls}"}}, request=request)
        get_calls += 1
        return httpx.Response(401 if get_calls == 1 else 200, json={"viagem": []}, request=request)

    configured = client()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
        result, token = await configured._get_with_reauth(session, "expired", "/fleet")
    assert result["ok"] is True
    assert token == "token-1"
    assert login_calls == 1
    assert get_calls == 2


@pytest.mark.asyncio
async def test_invalid_authentication_json_is_incompatible_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>unexpected</html>", request=request)

    configured = client()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
        with pytest.raises(TrafegusError) as raised:
            await configured._authenticate(session)
    assert raised.value.category == "invalid_json"


@pytest.mark.asyncio
async def test_previous_snapshot_remains_available_in_degraded_mode(monkeypatch) -> None:
    service = FleetTrackingService()
    service._snapshot = {"source": "trafegus", "trips": [{"plate": "ABC1D23"}]}
    service._snapshot_at = 1.0

    class FailingClient:
        async def active_trips_with_details(self):
            raise TrafegusError(
                "Tempo de resposta do Trafegus excedido.",
                phase="authentication",
                category="timeout",
            )

        username = "configured"
        password = "configured"
        document = "12345678000199"

    monkeypatch.setattr(fleet_module, "TrafegusClient", FailingClient)
    result = await service.get_snapshot(force=True)
    assert result["source_status"] == "stale"
    assert result["trips"][0]["plate"] == "ABC1D23"
    health = service.trafegus_health()
    assert health["status"] == "degraded"
    assert health["message"] == "Tempo de resposta do Trafegus excedido."
