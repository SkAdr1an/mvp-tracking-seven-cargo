from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.integrations.trafegus import TrafegusClient
from app.services.return_tracking import ReturnTrackingService
from app.services.route_progress import RouteProgressService
from app.services.trip_operations import BETIM_JABOATAO_ROUTE, TripOperationsService
from app.storage.operations import OperationsRepository


PLATE = "ABC1D23"
KEY = "trafegus:outbound-1"


def service_at(tmp_path, monkeypatch, *, stay=18, minimum_km=40, corridor_m=1000):
    repository = OperationsRepository(tmp_path / "operations.db")
    service = TripOperationsService(repository)
    settings = SimpleNamespace(
        return_min_destination_stay_hours=stay,
        return_min_progress_km=minimum_km,
        return_direction_readings=3,
        return_corridor_m=corridor_m,
    )
    monkeypatch.setattr("app.services.return_tracking.get_settings", lambda: settings)
    points = [
        {"latitude": BETIM_JABOATAO_ROUTE["origin_latitude"], "longitude": BETIM_JABOATAO_ROUTE["origin_longitude"]},
        {"latitude": -14.5, "longitude": -39.5},
        {"latitude": BETIM_JABOATAO_ROUTE["destination_latitude"], "longitude": BETIM_JABOATAO_ROUTE["destination_longitude"]},
    ]
    with repository.connect() as connection:
        connection.execute(
            """INSERT INTO route_geometry_versions
               (route_id,version,source,geometry_json,mandatory_points_json,corridor_m,
                segment_tolerances_json,active,created_at) VALUES(?,?,?,?,?,?,?,?,?)""",
            ("betim-jaboatao", "test-v1", "test", json.dumps(points), json.dumps(points),
             300, "[]", 1, datetime.now(timezone.utc).isoformat()),
        )
    arrival = datetime(2026, 7, 20, 10, tzinfo=timezone.utc)
    repository.ensure_trip(KEY, PLATE, "outbound-1", "betim-jaboatao")
    repository.update_trip(
        KEY, state="FINALIZADA_NO_SISTEMA", current_driver="Motorista ID 42",
        arrived_destination_at=arrival.isoformat(), destination_entered_at=arrival.isoformat(),
        finished_at=(arrival + timedelta(minutes=30)).isoformat(), finish_type="automatic",
    )
    return service, arrival, points


def coordinate(points, fraction):
    start, end = points[-2], points[-1]
    return (
        start["latitude"] + (end["latitude"] - start["latitude"]) * fraction,
        start["longitude"] + (end["longitude"] - start["longitude"]) * fraction,
    )


def observe_sequence(service, arrival, points, departure_hours=18, fractions=(.99, .97, .95, .93)):
    parent = service.repository.trip(KEY)
    route = service.repository.route("betim-jaboatao")
    destination = points[-1]
    service.return_tracking.observe(
        parent, route, destination["latitude"], destination["longitude"],
        (arrival + timedelta(hours=departure_hours) - timedelta(minutes=2)).isoformat(), "test",
    )
    for index, fraction in enumerate(fractions):
        lat, lon = coordinate(points, fraction)
        service.return_tracking.observe(
            parent, route, lat, lon,
            (arrival + timedelta(hours=departure_hours, minutes=index - 1)).isoformat(), "test",
        )
    return service.repository.return_candidate(KEY)


@pytest.mark.parametrize("hours,detected", [(17.9, False), (18, True), (20, True)])
def test_destination_stay_threshold(tmp_path, monkeypatch, hours, detected):
    service, arrival, points = service_at(tmp_path, monkeypatch, minimum_km=20)
    assert bool(observe_sequence(service, arrival, points, hours)) is detected


def test_destination_stay_is_configurable(tmp_path, monkeypatch):
    service, arrival, points = service_at(tmp_path, monkeypatch, stay=6, minimum_km=20)
    assert observe_sequence(service, arrival, points, 6)


def test_local_movement_brief_exit_and_wrong_direction_do_not_detect(tmp_path, monkeypatch):
    service, arrival, points = service_at(tmp_path, monkeypatch, minimum_km=40)
    assert observe_sequence(service, arrival, points, 20, (.999, .998, .999, .998)) is None
    service2, arrival2, points2 = service_at(tmp_path / "other", monkeypatch, minimum_km=10)
    assert observe_sequence(service2, arrival2, points2, 20, (.90, .92, .94, .96)) is None


def test_three_consecutive_positions_and_corridor_are_required(tmp_path, monkeypatch):
    service, arrival, points = service_at(tmp_path, monkeypatch, minimum_km=20)
    assert observe_sequence(service, arrival, points, 20, (.98, .96)) is None
    service2, arrival2, points2 = service_at(tmp_path / "outside", monkeypatch, minimum_km=20, corridor_m=100)
    parent = service2.repository.trip(KEY)
    route = service2.repository.route("betim-jaboatao")
    for index, fraction in enumerate((.98, .96, .94)):
        lat, lon = coordinate(points2, fraction)
        service2.return_tracking.observe(
            parent, route, lat + .2, lon,
            (arrival2 + timedelta(hours=20, minutes=index)).isoformat(), "test",
        )
    assert service2.repository.return_candidate(KEY) is None


def test_unfinished_outbound_never_detects(tmp_path, monkeypatch):
    service, arrival, points = service_at(tmp_path, monkeypatch, minimum_km=20)
    service.repository.update_trip(KEY, state="EM_VIAGEM", finished_at=None)
    assert observe_sequence(service, arrival, points, 20) is None


def test_human_decisions_are_audited_and_idempotent(tmp_path, monkeypatch):
    service, arrival, points = service_at(tmp_path, monkeypatch, minimum_km=20)
    candidate = observe_sequence(service, arrival, points, 20)
    later = service.return_tracking.decide(candidate["id"], "LATER", "operador-1", "Conferir documento")
    assert later["state"] == "AGUARDANDO_CONFIRMACAO"
    confirmed = service.return_tracking.decide(candidate["id"], "YES", "operador-1", "Retorno confirmado")
    assert confirmed["state"] == "RETORNO_SEVEN_CONFIRMADO"
    return_trip = service.repository.trip(confirmed["return_trip_key"])
    assert return_trip["state"] == "RETORNO_SEVEN_CONFIRMADO"
    assert return_trip["trip_key"] != KEY
    assert service.repository.trip(KEY)["state"] == "FINALIZADA_NO_SISTEMA"
    again = service.return_tracking.decide(candidate["id"], "YES", "operador-1", "Repetição")
    assert again["return_trip_key"] == confirmed["return_trip_key"]
    events = service.repository.events(KEY)
    assert sum(event["event_type"] == "POSSIBLE_RETURN_DETECTED" for event in events) == 1


def test_external_return_stops_operational_tracking(tmp_path, monkeypatch):
    service, arrival, points = service_at(tmp_path, monkeypatch, minimum_km=20)
    candidate = observe_sequence(service, arrival, points, 20)
    external = service.return_tracking.decide(candidate["id"], "NO", "operador-1", "Frete particular")
    assert external["state"] == "RETORNO_EXTERNO"
    assert external["return_trip_key"] is None


def test_confirmed_return_uses_reversed_official_geometry_and_progress(tmp_path, monkeypatch):
    service, arrival, points = service_at(tmp_path, monkeypatch, minimum_km=20)
    candidate = observe_sequence(service, arrival, points, 20)
    confirmed = service.return_tracking.decide(candidate["id"], "YES", "operador-1", "Carga Seven")
    route = service.repository.route("jaboatao-betim-return")
    assert route["origin_name"] == BETIM_JABOATAO_ROUTE["destination_name"]
    assert route["destination_name"] == BETIM_JABOATAO_ROUTE["origin_name"]
    with service.repository.connect() as connection:
        row = connection.execute(
            "SELECT geometry_json FROM route_geometry_versions WHERE route_id=? AND active=1",
            ("jaboatao-betim-return",),
        ).fetchone()
    reverse_points = json.loads(row["geometry_json"])
    assert reverse_points[0] == points[-1]
    assert reverse_points[-1] == points[0]
    assert confirmed["return_trip_key"] != KEY
    middle = points[-2]
    progress = RouteProgressService(service.repository).calculate(
        confirmed["return_trip_key"], "jaboatao-betim-return",
        middle["latitude"], middle["longitude"], 50,
        (arrival + timedelta(hours=24)).isoformat(), False,
    )
    assert 35 <= progress["progress_percent"] <= 65
    assert progress["remaining_distance_km"] < progress["total_distance_km"]


def test_detection_adds_no_trafegus_calls_and_no_cristian_rule():
    source = inspect.getsource(ReturnTrackingService)
    assert "TrafegusClient" not in source
    assert "cristian" not in source.lower()
    client_source = inspect.getsource(TrafegusClient)
    assert "client.post(" in client_source  # autenticação existente, não chamada adicional por motorista
