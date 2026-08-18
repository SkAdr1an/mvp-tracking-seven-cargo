from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.integrations.azure_maps import (
    AzureMapsAuthError, AzureMapsClient, AzureMapsRateLimitError,
    AzureMapsUnavailableError, normalize_azure_incident,
)


def feature(kind: str, *, identifier: str = "1", delay: int = 120, closed: bool = False):
    return {"type":"Feature","id":identifier,"geometry":{"type":"Point","coordinates":[-44.1,-19.9]},
            "properties":{"incidentType":kind,"severity":2,"delay":delay,"isRoadClosed":closed,
                          "title":"BR-381","description":kind,"startTime":"2026-08-17T10:00:00Z",
                          "endTime":(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()}}


@pytest.mark.parametrize(("kind","category"),[("Accident","ACIDENTE"),("Construction","OBRA"),
    ("RoadClosure","VIA_FECHADA"),("Congestion","CONGESTIONAMENTO"),
    ("DisabledVehicle","VEICULO_PARADO"),("RoadHazard","RISCO_VIA"),("Weather","RISCO_CLIMATICO"),
    ("PlannedEvent","OUTRO")])
def test_azure_parser_maps_only_known_categories(kind,category):
    value=normalize_azure_incident(feature(kind,closed=kind=="RoadClosure"),"route",30)
    assert value and value["category"]==category and value["id"].startswith("azure:")
    assert value["delay_seconds"]==120 and value["delay_already_in_eta"] is False


class ResponseClient:
    def __init__(self,response):self.response=response
    async def __aenter__(self):return self
    async def __aexit__(self,*_):return None
    async def get(self,*args,**kwargs):
        assert kwargs["headers"]["subscription-key"]=="secret-test-key"
        assert "secret-test-key" not in str(args) and "secret-test-key" not in str(kwargs["params"])
        return self.response


@pytest.mark.asyncio
async def test_azure_200_contract(monkeypatch):
    request=httpx.Request("GET","https://atlas.microsoft.com/traffic/incident")
    response=httpx.Response(200,request=request,json={"type":"FeatureCollection","features":[feature("Construction")]})
    monkeypatch.setattr("app.integrations.azure_maps.httpx.AsyncClient",lambda **_:ResponseClient(response))
    payload=await AzureMapsClient(subscription_key="secret-test-key").get_traffic_incidents((-44.2,-20,-44,-19.8))
    assert len(payload["features"])==1


@pytest.mark.asyncio
@pytest.mark.parametrize(("status","error"),[(401,AzureMapsAuthError),(403,AzureMapsAuthError),
                                              (429,AzureMapsRateLimitError),(500,AzureMapsUnavailableError)])
async def test_azure_errors_are_typed_and_sanitized(monkeypatch,status,error):
    request=httpx.Request("GET","https://atlas.microsoft.com/traffic/incident")
    response=httpx.Response(status,request=request,json={"error":{"message":"provider rejected request"}})
    monkeypatch.setattr("app.integrations.azure_maps.httpx.AsyncClient",lambda **_:ResponseClient(response))
    with pytest.raises(error) as raised:
        await AzureMapsClient(subscription_key="secret-test-key").get_traffic_incidents((-44.2,-20,-44,-19.8))
    assert "secret-test-key" not in str(raised.value)


def test_expired_azure_incident_is_not_reactivated():
    raw=feature("Accident")
    raw["properties"]["endTime"]="2020-01-01T00:00:00Z"
    assert normalize_azure_incident(raw,"route",30) is None
