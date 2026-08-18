from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from app import main as main_module
from app.services.fleet_tracking import (
    FleetTrackingService,
    _classify,
    _speed,
    _weather_risk,
)
from app.integrations.tomtom import UnavailableError
from app.services.route_deviation import route_deviation_service


def _raw_fleet() -> dict:
    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-3)))
    older = (now - timedelta(minutes=10)).strftime("%d/%m/%Y %H:%M:%S")
    newer = now.strftime("%d/%m/%Y %H:%M:%S")
    return {
        "positions": {
            "ok": True,
            "data": {
                "viagem": [
                    {
                        "id_viagem": 123,
                        "placa": "AWP7D63",
                        "posicoesViagem": {"placa": "AWP7D63", "motorista": "Motorista A", "coordenada": "-19.9,-44.1", "dataPosicao": older},
                    },
                    {
                        "id_viagem": 123,
                        "placa": "AWP7D63",
                        "posicoesViagem": {"placa": "AWP7D63", "motorista": "Motorista A", "coordenada": "-19.8,-44.0", "dataPosicao": newer, "rastreadora": "SASCAR"},
                    },
                ]
            },
        },
        "trip_details": {
            "AWP7D63": {
                "ok": True,
                "data": {
                    "viagens": [{
                        "id_viagem": 123,
                        "previsao_chegada": (now + timedelta(hours=12)).isoformat(),
                        "locais": [{"tipo_parada": "DESTINO", "descricao": "CD destino", "latitude": -8.2, "longitude": -35.0}],
                    }]
                },
            }
        },
    }


def test_normalizes_and_deduplicates_by_trip_identifier() -> None:
    trips = FleetTrackingService()._normalize_trips(_raw_fleet())
    assert len(trips) == 1
    assert trips[0]["plate"] == "AWP7D63"
    assert trips[0]["trip_id"] == "123"
    assert trips[0]["position"] == {"latitude": -19.8, "longitude": -44.0}
    assert trips[0]["tracker"] == "SASCAR"
    assert trips[0]["destination"]["description"] == "CD destino"


def test_eta_classification_compares_against_sla() -> None:
    assert _classify(15, 300) == "CRITICA"
    assert _classify(-30, 300) == "ATENCAO"
    assert _classify(-180, 300) == "NORMAL"


def test_classification_survives_routing_provider_failure() -> None:
    service = FleetTrackingService()
    future_sla = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    overdue_sla = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    attention = {"sla_at": future_sla, "prediction": {"status": "unavailable"}, "diagnostic": None}
    critical = {"sla_at": overdue_sla, "prediction": {"status": "unavailable"}, "diagnostic": None}

    service._ensure_operational_classification(attention)
    service._ensure_operational_classification(critical)

    assert attention["prediction"]["classification"] == "ATENCAO"
    assert attention["prediction"]["classification_source"] == "sla_fallback"
    assert critical["prediction"]["classification"] == "CRITICA"


def test_operational_diagnostic_classification_has_priority_over_sla_fallback() -> None:
    trip = {
        "sla_at": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
        "prediction": {"status": "unavailable"},
        "diagnostic": {
            "classification": "NORMAL",
            "eta_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            "commitment_delta_minutes": -120,
        },
    }

    FleetTrackingService._ensure_operational_classification(trip)

    assert trip["prediction"]["classification"] == "NORMAL"
    assert trip["prediction"]["classification_source"] == "operational_diagnostic"
    assert trip["prediction"]["eta_at"] == trip["diagnostic"]["eta_at"]


def test_weather_risk_uses_forecast_without_inventing_delay() -> None:
    risk = _weather_risk(
        {"weather": [{"id": 202, "description": "tempestade"}], "main": {"temp": 21}, "rain": {"3h": 12}},
        datetime.now(timezone.utc),
        {"latitude": -15.0, "longitude": -40.0},
    )
    assert risk is not None
    assert risk["type"] == "thunderstorm"
    assert risk["severity"] == "high"
    assert "delay_minutes" not in risk


def _weather_trip() -> dict:
    return {"position":{"latitude":-19.9,"longitude":-44.1},"operational":{"route_id":"persisted"},"route_progress":{"progress_percent":25,"remaining_distance_km":220},"weather_risks":[],"api_status":{"openweather":"not_checked","tomtom":"not_checked"}}


@pytest.mark.asyncio
async def test_persisted_geometry_enriches_weather_with_routing_disabled(monkeypatch) -> None:
    service=FleetTrackingService(); calls=[]
    monkeypatch.setattr(route_deviation_service,"geometry",lambda _: {"geometry":[{"latitude":-20+i,"longitude":-44+i} for i in range(6)]})
    async def forecast(lat,lon,passage): calls.append((lat,lon)); return {"weather":[{"id":202,"description":"tempestade"}],"rain":{"3h":12}}
    monkeypatch.setattr(service,"_forecast",forecast)
    trip=_weather_trip(); await service._weather_from_persisted_route(trip)
    assert len(calls)==3 and len(trip["weather_risks"])==3
    assert trip["api_status"]["openweather"]=="connected"
    assert trip["api_status"]["tomtom"]=="not_checked"


@pytest.mark.asyncio
async def test_missing_geometry_does_not_call_weather_and_explains_reason(monkeypatch) -> None:
    service=FleetTrackingService(); monkeypatch.setattr(route_deviation_service,"geometry",lambda _: None)
    async def unexpected(*_): raise AssertionError("weather must not be called")
    monkeypatch.setattr(service,"_forecast",unexpected); trip=_weather_trip(); await service._weather_from_persisted_route(trip)
    assert trip["api_status"]["openweather"]=="not_checked"
    assert trip["api_status"]["openweather_reason"]=="route_geometry_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("forecast,expected",[({"weather":[{"id":800,"description":"céu limpo"}]},0),({"weather":[{"id":501,"description":"chuva"}]},3)])
async def test_openweather_result_only_creates_real_risks(monkeypatch,forecast,expected) -> None:
    service=FleetTrackingService(); monkeypatch.setattr(route_deviation_service,"geometry",lambda _: {"geometry":[{"latitude":-20+i,"longitude":-44+i} for i in range(5)]})
    async def result(*_): return forecast
    monkeypatch.setattr(service,"_forecast",result); trip=_weather_trip(); await service._weather_from_persisted_route(trip)
    assert len(trip["weather_risks"])==expected and trip["api_status"]["openweather"]=="connected"


@pytest.mark.asyncio
async def test_openweather_failure_keeps_operational_trip(monkeypatch) -> None:
    service=FleetTrackingService(); monkeypatch.setattr(route_deviation_service,"geometry",lambda _: {"geometry":[{"latitude":-20+i,"longitude":-44+i} for i in range(5)]})
    async def failure(*_): raise UnavailableError("temporary")
    monkeypatch.setattr(service,"_forecast",failure); trip=_weather_trip(); await service._weather_from_persisted_route(trip)
    assert trip["weather_risks"]==[] and trip["api_status"]["openweather"]=="unavailable"


@pytest.mark.asyncio
async def test_forecast_cache_avoids_repeated_openweather_calls(monkeypatch) -> None:
    service=FleetTrackingService(); calls=0
    async def forecast(*_):
        nonlocal calls; calls+=1; return {"list":[{"dt":datetime.now(timezone.utc).timestamp(),"weather":[{"id":800}]}]}
    monkeypatch.setattr("app.services.fleet_tracking.WeatherClient.get_forecast_by_coords",forecast)
    passage=datetime.now(timezone.utc)
    await service._forecast(-19.98,-44.26,passage); await service._forecast(-19.98,-44.26,passage)
    assert calls==1 and len(service._weather_cache)==1


def test_speed_accepts_provider_case_and_preserves_stopped_vehicle() -> None:
    assert _speed({"Velocidade": 0}) == 0
    assert _speed({"velocidade_atual": "72"}) == 72
    assert _speed({}) is None


def test_active_fleet_endpoint_does_not_stay_zero_when_trafegus_has_trips(monkeypatch) -> None:
    async def fake_snapshot(force: bool = False) -> dict:
        return {"source": "trafegus", "source_status": "connected", "generated_at": datetime.now(timezone.utc).isoformat(), "counts": {"total": 1}, "trips": [{"plate": "AWP7D63"}]}
    monkeypatch.setattr(main_module.fleet_tracking_service, "get_snapshot", fake_snapshot)
    response = TestClient(main_module.app).get("/fleet/active")
    assert response.status_code == 200
    assert response.json()["counts"]["total"] == 1
    assert response.json()["trips"][0]["plate"] == "AWP7D63"
