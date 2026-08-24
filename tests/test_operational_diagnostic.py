from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.integrations.trafegus import TrafegusClient
from app.services.operational_diagnostic import OperationalDiagnosticService
from app.services.trip_operations import BETIM_JABOATAO_ROUTE
from app.storage.operations import OperationsRepository


KEY = "trafegus:diagnostic-1"
NOW = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)


def service_at(tmp_path):
    repository = OperationsRepository(tmp_path / "operations.db")
    repository.upsert_route(BETIM_JABOATAO_ROUTE)
    repository.ensure_trip(KEY, "ABC1D23", "diagnostic-1", "betim-jaboatao")
    repository.update_trip(
        KEY, state="EM_VIAGEM", started_at=(NOW - timedelta(hours=10)).isoformat(),
        last_position_at=NOW.isoformat(), last_latitude=-14, last_longitude=-40,
        last_speed_kmh=50,
    )
    return OperationalDiagnosticService(repository), repository


def trip(remaining=500, provider=600, classification="NORMAL", stale=False, speed=50, state="EM_VIAGEM", sla_hours=14):
    return {
        "plate": "ABC1D23", "stale": stale, "speed_kmh": speed,
        "sla_at": (NOW + timedelta(hours=sla_hours)).isoformat(),
        "prediction": {"status": "available", "provider_minutes": provider, "classification": classification},
        "route_progress": {
            "remaining_distance_km": remaining, "progress_percent": 50,
            "route_state": "STALE" if stale else "ON_ROUTE",
            "confidence": "LOW" if stale else "HIGH", "return_distance_km": None,
        },
        "weather_risks": [],
        "operational": {
            "trip_key": KEY, "state": state, "last_speed_kmh": speed,
            "geofences": {"origin": "outside", "destination": "outside"},
        },
    }


@pytest.mark.parametrize("remaining,progress", [(1000, 5), (500, 50), (20, 98)])
def test_eta_at_start_middle_and_end_uses_official_remaining(tmp_path, remaining, progress):
    service, _ = service_at(tmp_path)
    value = trip(remaining=remaining, provider=remaining / 60 * 60)
    value["route_progress"]["progress_percent"] = progress
    result = service.calculate(value, now=NOW)
    assert result["factors"][0]["code"] == "OFFICIAL_REMAINING"
    assert result["eta_at"] > NOW.isoformat()
    assert result["scenarios"]["optimistic"]["eta_at"] <= result["scenarios"]["likely"]["eta_at"] <= result["scenarios"]["conservative"]["eta_at"]


def test_manual_sao_bernardo_contagem_uses_31_hour_duration(tmp_path):
    service, _ = service_at(tmp_path)
    value = trip(remaining=300, provider=60)
    value["operational"]["route"] = {
        "id": "sao-bernardo-contagem-manual",
        "operational_duration_minutes": 1860,
        "is_express": False,
    }
    result = service.calculate(value, now=NOW)
    factor = next(item for item in result["factors"] if item["code"] == "CORRIDOR_OPERATIONAL_DURATION")
    assert factor["minutes"] == 1860
    assert datetime.fromisoformat(result["eta_at"]) >= NOW + timedelta(minutes=930)


def test_outbound_and_confirmed_return_use_separate_trip_keys(tmp_path):
    service, repository = service_at(tmp_path)
    outbound = service.calculate(trip(remaining=700), now=NOW)
    return_key = "return:outbound:1"
    repository.ensure_trip(return_key, "ABC1D23", None, "betim-jaboatao")
    repository.update_trip(return_key, state="RETORNO_SEVEN_CONFIRMADO")
    returning = trip(remaining=300, state="RETORNO_SEVEN_CONFIRMADO")
    returning["operational"]["trip_key"] = return_key
    returned = service.calculate(returning, now=NOW)
    assert outbound["trip_key"] != returned["trip_key"]
    assert repository.diagnostic(KEY)["eta_at"] == outbound["eta_at"]


def test_stale_position_and_tomtom_failure_preserve_last_eta(tmp_path):
    service, _ = service_at(tmp_path)
    first = service.calculate(trip(), now=NOW)
    stale = trip(provider=None, stale=True, speed=None)
    stale["prediction"] = {"status": "unavailable", "classification": "NORMAL"}
    second = service.calculate(stale, now=NOW + timedelta(minutes=20))
    assert second["eta_at"] == first["eta_at"]
    assert second["confidence"] == "LOW"
    assert "preservado" in " ".join(second["confidence_reasons"]).lower()


def test_small_eta_oscillation_is_stabilized(tmp_path):
    service, _ = service_at(tmp_path)
    first = service.calculate(trip(provider=600), now=NOW)
    second = service.calculate(trip(provider=604), now=NOW)
    assert second["eta_at"] == first["eta_at"]
    assert any("estabilização" in reason for reason in second["confidence_reasons"])


def test_speed_missing_or_zero_does_not_alone_raise_status(tmp_path):
    service, repository = service_at(tmp_path)
    missing = service.calculate(trip(speed=None), now=NOW)
    assert missing["classification"] == "NORMAL"
    repository.update_trip(KEY, last_speed_kmh=0)
    zero = trip(speed=0)
    zero["operational"]["last_speed_kmh"] = 0
    result = service.calculate(zero, now=NOW)
    assert result["classification"] == "NORMAL"


def test_prolonged_stop_traffic_weather_and_deviation_are_explained(tmp_path):
    service, repository = service_at(tmp_path)
    for minutes in (90, 60, 30, 0):
        repository.add_position(
            KEY, -14, -40, 0, (NOW - timedelta(minutes=minutes)).isoformat(),
            "test", None, None,
        )
    repository.update_trip(KEY, last_speed_kmh=0)
    value = trip(classification="CRITICA", speed=0)
    value["operational"]["last_speed_kmh"] = 0
    value["route_progress"].update(route_state="OUTSIDE", confidence="MEDIUM", return_distance_km=12)
    value["weather_risks"] = [{"severity": "ATENCAO", "description": "Chuva forte"}]
    incidents = [{"delay_seconds": 3600, "affected_vehicles": []}]
    result = service.calculate(value, incidents, now=NOW)
    types = {risk["type"] for risk in result["risks"]}
    assert {"TRAFFIC", "WEATHER", "DEVIATION", "PROLONGED_STOP"} <= types
    assert "Validar retorno à rota oficial" in result["recommendations"]
    assert "Confirmar motivo da parada com o motorista" in result["recommendations"]


@pytest.mark.parametrize(
    "classification,expected",
    [("NORMAL", "Status: Normal"), ("ATENCAO", "Status: Atenção"), ("CRITICA", "Status: Crítica")],
)
def test_status_classifications_have_objective_explanation(tmp_path, classification, expected):
    service, _ = service_at(tmp_path)
    result = service.calculate(trip(classification=classification), now=NOW)
    assert expected in result["status_explanation"]


def test_client_commitment_trend_and_scenarios(tmp_path):
    service, _ = service_at(tmp_path)
    result = service.calculate(trip(provider=900, classification="ATENCAO", sla_hours=12), now=NOW)
    assert result["client_eta_at"]
    assert result["commitment_delta_minutes"] is not None
    assert result["trend"] in {"RISCO_DE_ATRASO", "PROVAVEL_ATRASO"}
    assert set(result["scenarios"]) == {"optimistic", "likely", "conservative"}


def test_finished_and_unconfirmed_return_have_no_operational_eta(tmp_path):
    service, _ = service_at(tmp_path)
    assert service.calculate(trip(state="FINALIZADA_NO_SISTEMA"), now=NOW) is None
    waiting = trip(state="FINALIZADA_NO_SISTEMA")
    waiting["operational"]["return_candidate"] = {"state": "AGUARDANDO_CONFIRMACAO"}
    assert service.calculate(waiting, now=NOW) is None


def test_programmed_trip_with_transit_evidence_receives_eta(tmp_path):
    service, _ = service_at(tmp_path)
    value = trip(state="PROGRAMADA")
    value["operational"]["geofences"] = {"origin": "outside", "destination": "outside"}
    value["route_progress"]["progress_percent"] = 35
    result = service.calculate(value, now=NOW)
    assert result is not None
    assert result["eta_at"] > NOW.isoformat()


def test_programmed_trip_without_transit_evidence_has_no_eta(tmp_path):
    service, _ = service_at(tmp_path)
    value = trip(state="PROGRAMADA")
    value["operational"]["geofences"] = {"origin": "inside", "destination": "outside"}
    value["route_progress"]["progress_percent"] = 0
    assert service.calculate(value, now=NOW) is None


def test_persistence_survives_restart_and_no_external_call_is_added(tmp_path):
    service, repository = service_at(tmp_path)
    expected = service.calculate(trip(), now=NOW)
    restarted = OperationsRepository(repository.database_path)
    assert restarted.diagnostic(KEY)["eta_at"] == expected["eta_at"]
    source = inspect.getsource(OperationalDiagnosticService)
    assert "TrafegusClient" not in source
    assert "TomTomClient" not in source
    assert "WeatherClient" not in source
    assert "cristian" not in source.lower()
    trafegus_source = inspect.getsource(TrafegusClient)
    assert "client.put(" not in trafegus_source and "client.patch(" not in trafegus_source


def test_driver_diagnostic_is_responsive_without_horizontal_scroll():
    styles = Path("frontend/src/styles.css").read_text(encoding="utf-8")
    component = Path("frontend/src/components/DriverDiagnostic.tsx").read_text(encoding="utf-8")
    assert ".driver-diagnostic{position:relative" in styles
    assert "overflow-x:hidden" in styles
    assert "@media(max-width:900px)" in styles
    assert "Diagnóstico operacional individual" in component
