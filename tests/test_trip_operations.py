from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

from app.integrations.trafegus import TrafegusClient
from app.services.trip_operations import (
    BETIM_JABOATAO_ROUTE,
    SAO_BERNARDO_CONTAGEM_ROUTE,
    PositionUpdate,
    TripOperationsService,
)
from app.storage.operations import OperationsRepository
from app.core.security import hash_password
from fastapi.testclient import TestClient
from app import main as main_module
from app.api import operations as operations_api


PLATE = "ABC1D23"


def service_at(tmp_path) -> TripOperationsService:
    return TripOperationsService(OperationsRepository(tmp_path / "operations.db"))


def test_manual_sao_bernardo_contagem_route_is_directional(tmp_path):
    service = service_at(tmp_path)
    expected = service.match_route(
        "CEVA_SHOPEE - SÃO BERNARDO DO CAMPO/SP X CEVA_SHOPEE - CONTAGEM/MG"
    )
    assert expected and expected["id"] == SAO_BERNARDO_CONTAGEM_ROUTE["id"]
    assert service.match_route(
        "CEVA_SHOPEE - CONTAGEM/MG X CEVA_SHOPEE - SÃO BERNARDO DO CAMPO/SP"
    ) is None


def test_route_recognition_respects_direction_and_known_aliases(tmp_path):
    service = service_at(tmp_path)
    outbound = service.recognize_route("CEVA_SHOPEE - BETIM/MG X JABOATÃO/PE ATUALIZADA")
    reverse = service.recognize_route("CEVA_SHOPEE - JABOATÃO/PE X BETIM/MG ATUALIZADA")
    manual_alias = service.recognize_route(
        "CEVA - SHOPEE SOC_SP_SÃO BERNARDO DO CAMPO X CD_SHOPPE_FBS - CONTAGEM/MG"
    )
    absent = service.recognize_route(
        "LM2RODAS - MB MATRIZ CARIACICA/ES X LM2RODAS - WNE MATRIZ CABO DE SANTO AGOSTINHO/PE"
    )
    assert outbound["route"]["id"] == "betim-jaboatao"
    assert reverse["status"] == "GEOMETRY_PENDING" and reverse["route"] is None
    assert manual_alias["route"]["id"] == "sao-bernardo-contagem-manual"
    assert absent["status"] == "UNIDENTIFIED" and absent["route"] is None


def test_route_recognition_uses_unique_ordered_terms_without_separator(tmp_path):
    service = service_at(tmp_path)
    route = {
        **BETIM_JABOATAO_ROUTE,
        "id": "cariacica-benevides",
        "name": "Cariacica/ES → Benevides/PA",
        "match_terms": ["MB IMPORTAÇÃO MATRIZ - CARIACICA", "WNORTE - BENEVIDES"],
    }
    service.repository.upsert_route(route)

    recognized = service.recognize_route(
        "LM2RODAS MB IMPORTAÇÃO MATRIZ - CARIACICA/ES - WNORTE - BENEVIDES/PA (GOV. E SALGUEIRO)"
    )
    reversed_direction = service.recognize_route(
        "WNORTE - BENEVIDES/PA - MB IMPORTAÇÃO MATRIZ - CARIACICA/ES"
    )

    assert recognized["status"] == "RECOGNIZED"
    assert recognized["route"]["id"] == "cariacica-benevides"
    assert recognized["method"] == "configured_ordered_description_terms"
    assert reversed_direction["status"] == "UNIDENTIFIED"


def position(service, when, latitude, longitude, speed=0, trip_id="trip-1", route_id="betim-jaboatao"):
    return service.process_position(PositionUpdate(
        plate=PLATE, trip_id=trip_id, latitude=latitude, longitude=longitude,
        speed_kmh=speed, recorded_at=when, source="test", route_id=route_id,
    ))


def at_origin(service, when, **kwargs):
    return position(service, when, BETIM_JABOATAO_ROUTE["origin_latitude"], BETIM_JABOATAO_ROUTE["origin_longitude"], **kwargs)


def at_destination(service, when, **kwargs):
    return position(service, when, BETIM_JABOATAO_ROUTE["destination_latitude"], BETIM_JABOATAO_ROUTE["destination_longitude"], **kwargs)


def outside(service, when, **kwargs):
    return position(service, when, -15.0, -40.0, **kwargs)


def advance_to_trip(service, start):
    at_origin(service, start)
    at_origin(service, start + timedelta(minutes=1))
    at_origin(service, start + timedelta(minutes=11))
    outside(service, start + timedelta(minutes=12), speed=30)
    return outside(service, start + timedelta(minutes=13), speed=35)


def test_origin_entry_dwell_and_departure_start_trip(tmp_path):
    service = service_at(tmp_path)
    start = datetime(2026, 7, 22, 10, tzinfo=timezone.utc)
    assert at_origin(service, start)["trip"]["state"] == "PROGRAMADA"
    assert at_origin(service, start + timedelta(minutes=1))["trip"]["state"] == "NA_ORIGEM"
    confirmed = at_origin(service, start + timedelta(minutes=11))["trip"]
    assert confirmed["state"] == "EM_CARREGAMENTO"
    assert confirmed["arrived_origin_at"] == start.isoformat()
    assert outside(service, start + timedelta(minutes=12), speed=30)["trip"]["state"] == "EM_CARREGAMENTO"
    started = outside(service, start + timedelta(minutes=13), speed=30)["trip"]
    assert started["state"] == "EM_VIAGEM"
    assert started["started_at"] == (start + timedelta(minutes=12)).isoformat()


def test_destination_dwell_and_automatic_finish_after_thirty_minutes(tmp_path):
    service = service_at(tmp_path)
    start = datetime(2026, 7, 22, 10, tzinfo=timezone.utc)
    advance_to_trip(service, start)
    at_destination(service, start + timedelta(minutes=20), speed=2)
    entered = at_destination(service, start + timedelta(minutes=21), speed=1)["trip"]
    assert entered["state"] == "NO_DESTINO"
    confirmed = at_destination(service, start + timedelta(minutes=31), speed=0)["trip"]
    assert confirmed["arrived_destination_at"] == (start + timedelta(minutes=20)).isoformat()
    finished = at_destination(service, start + timedelta(minutes=50), speed=0)["trip"]
    assert finished["state"] == "FINALIZADA_NO_SISTEMA"
    assert finished["finish_type"] == "automatic"
    events = service.repository.events("trafegus:trip-1")
    assert sum(event["event_type"] == "TRIP_AUTO_FINISHED" for event in events) == 1


def test_missing_speed_is_currently_treated_as_stopped_at_destination(tmp_path):
    service = service_at(tmp_path)
    start = datetime(2026, 7, 22, 10, tzinfo=timezone.utc)
    advance_to_trip(service, start)
    at_destination(service, start + timedelta(minutes=20), speed=None)
    entered = at_destination(service, start + timedelta(minutes=21), speed=None)["trip"]
    assert entered["state"] == "NO_DESTINO"
    confirmed = at_destination(service, start + timedelta(minutes=31), speed=None)["trip"]
    assert confirmed["arrived_destination_at"] == (start + timedelta(minutes=20)).isoformat()
    finished = at_destination(service, start + timedelta(minutes=50), speed=None)["trip"]
    assert finished["state"] == "FINALIZADA_NO_SISTEMA"
    assert finished["finish_type"] == "automatic"


def test_quick_destination_passage_does_not_finish(tmp_path):
    service = service_at(tmp_path)
    start = datetime(2026, 7, 22, 10, tzinfo=timezone.utc)
    service.repository.ensure_trip("trafegus:trip-1", PLATE, "trip-1", "betim-jaboatao")
    service.repository.update_trip("trafegus:trip-1", state="EM_VIAGEM")
    at_destination(service, start, speed=35)
    assert at_destination(service, start + timedelta(minutes=1), speed=30)["trip"]["state"] == "NO_DESTINO"
    outside(service, start + timedelta(minutes=2), speed=50)
    result = outside(service, start + timedelta(minutes=3), speed=50)
    assert result["trip"]["state"] == "EM_VIAGEM"
    assert result["trip"]["finished_at"] is None


def test_hysteresis_requires_consecutive_true_entries(tmp_path):
    service = service_at(tmp_path)
    start = datetime(2026, 7, 22, 10, tzinfo=timezone.utc)
    # Aproximadamente 550 m: fora do raio de entrada, dentro da margem de saída.
    edge_lat = BETIM_JABOATAO_ROUTE["origin_latitude"] + 0.00495
    position(service, start, edge_lat, BETIM_JABOATAO_ROUTE["origin_longitude"])
    at_origin(service, start + timedelta(minutes=1))
    position(service, start + timedelta(minutes=2), edge_lat, BETIM_JABOATAO_ROUTE["origin_longitude"])
    assert at_origin(service, start + timedelta(minutes=3))["trip"]["state"] == "PROGRAMADA"
    assert at_origin(service, start + timedelta(minutes=4))["trip"]["state"] == "NA_ORIGEM"


def test_duplicate_old_and_out_of_order_positions_are_ignored(tmp_path):
    service = service_at(tmp_path)
    start = datetime(2026, 7, 22, 10, tzinfo=timezone.utc)
    first = at_origin(service, start)
    duplicate = at_origin(service, start)
    old = at_origin(service, start - timedelta(minutes=1))
    assert first["accepted"] is True
    assert duplicate["accepted"] is False and duplicate["duplicate"] is True
    assert old["accepted"] is False
    assert service.repository.trip("trafegus:trip-1")["last_position_at"] == start.isoformat()


def test_restart_recovers_persisted_state(tmp_path):
    path = tmp_path / "operations.db"
    first = TripOperationsService(OperationsRepository(path))
    start = datetime(2026, 7, 22, 10, tzinfo=timezone.utc)
    advance_to_trip(first, start)
    restarted = TripOperationsService(OperationsRepository(path))
    trip = restarted.repository.trip("trafegus:trip-1")
    assert trip and trip["state"] == "EM_VIAGEM"
    assert trip["started_at"] == (start + timedelta(minutes=12)).isoformat()


def test_manual_correction_finalize_and_reopen_require_history(tmp_path):
    service = service_at(tmp_path)
    service.repository.ensure_trip("trafegus:trip-1", PLATE, "trip-1", "betim-jaboatao")
    corrected = service.manual_action(
        "trafegus:trip-1", "correct_times", "Correção validada pelo operador", "operador-1",
        {"started_at": "2026-07-22T10:00:00-03:00"},
    )
    assert corrected["started_at"] == "2026-07-22T13:00:00+00:00"
    assert service.manual_action("trafegus:trip-1", "finalize", "Descarga confirmada", "operador-1")["state"] == "FINALIZADA_NO_SISTEMA"
    assert service.manual_action("trafegus:trip-1", "reopen", "Finalização incorreta", "operador-1")["state"] == "REABERTA_MANUALMENTE"
    events = service.repository.events("trafegus:trip-1")
    assert all(event["justification"] for event in events if event["source"] == "operator")


def test_driver_change_and_ambiguous_divergence_preserve_last_reliable(tmp_path):
    service = service_at(tmp_path)
    first = service.reconcile_driver(PLATE, "trip-1", ["Condutor da viagem"], ["Condutor atual"])
    assert first["current_driver"] == "Condutor atual"
    assert first["previous_driver"] == "Condutor da viagem"
    assert first["driver_changed"] is True
    changed = service.reconcile_driver(PLATE, "trip-1", ["Condutor da viagem"], ["Novo condutor"])
    assert changed["previous_driver"] == "Condutor atual"
    assert changed["current_driver"] == "Novo condutor"
    assert changed["driver_changed"] is True
    ambiguous = service.reconcile_driver(PLATE, "trip-1", ["Condutor da viagem"], ["Pessoa A", "Pessoa B"])
    assert ambiguous["current_driver"] == "Novo condutor"
    assert ambiguous["driver_divergence"] is True
    assert any(event["event_type"] == "DRIVER_CHANGED" for event in service.repository.events("trafegus:trip-1"))


def test_multiple_route_configuration_is_not_hardcoded(tmp_path):
    service = service_at(tmp_path)
    second = {**BETIM_JABOATAO_ROUTE, "id": "route-two", "name": "Rota Dois",
              "origin_latitude": -23.0, "origin_longitude": -46.0,
              "destination_latitude": -22.0, "destination_longitude": -45.0,
              "match_terms": ["ORIGEM DOIS", "DESTINO DOIS"]}
    service.repository.upsert_route(second)
    assert service.match_route("Origem dois para Destino dois")["id"] == "route-two"
    result = position(service, datetime(2026, 7, 22, tzinfo=timezone.utc), -23.0, -46.0,
                      trip_id="trip-2", route_id="route-two")
    assert result["trip"]["route_id"] == "route-two"


def test_trafegus_client_has_no_trip_mutation_or_finish_command():
    source = inspect.getsource(TrafegusClient)
    assert "client.put(" not in source
    assert "client.patch(" not in source
    assert "client.delete(" not in source
    assert "finalizar" not in source.lower()


def test_operational_actions_require_panel_session_and_preserve_audit(tmp_path, monkeypatch):
    service = service_at(tmp_path)
    key = "trafegus:api-trip"
    service.repository.ensure_trip(key, PLATE, "api-trip", "betim-jaboatao")
    monkeypatch.setattr(operations_api, "trip_operations_service", service)
    settings = main_module.get_settings()
    monkeypatch.setattr(settings, "panel_admin_username", "operador")
    monkeypatch.setattr(settings, "panel_admin_password_hash", hash_password("senha-forte-123"))
    monkeypatch.setattr(settings, "panel_session_secret", "segredo-de-sessao-com-mais-de-32-bytes")
    client = TestClient(main_module.app)
    detail = client.get(f"/operations/trips/{key}")
    assert detail.status_code == 200
    payload = {
        "action": "finalize", "justification": "Confirmado pelo operador", "operator": "teste",
    }
    assert client.post(f"/operations/trips/{key}/actions", json=payload).status_code == 401
    assert client.post(
        f"/operations/trips/{key}/actions",
        headers={"Authorization": "Bearer senha-forte"},
        json=payload,
    ).status_code == 401
    assert client.post(
        f"/operations/trips/{key}/actions",
        headers={"Cookie": "seven_panel_session=invalida"},
        json=payload,
    ).status_code == 401
    login = client.post(
        "/api/auth/session", json={"username": "operador", "password": "senha-forte-123"},
    )
    assert login.status_code == 200
    assert "path=/" in login.headers["set-cookie"].lower()
    response = client.post(
        f"/operations/trips/{key}/actions",
        json=payload,
    )
    assert response.status_code == 200
    assert response.json()["state"] == "FINALIZADA_NO_SISTEMA"
    assert response.json()["events"][0]["justification"] == "Confirmado pelo operador"

    actions = [
        {"action": "reopen", "justification": "Reabertura validada"},
        {"action": "undo_detection", "justification": "DetecÃ§Ã£o desfeita"},
        {
            "action": "correct_times",
            "justification": "HorÃ¡rio corrigido",
            "corrections": {"started_at": "2026-07-22T10:00:00-03:00"},
        },
    ]
    for action_payload in actions:
        unauthenticated = TestClient(main_module.app).post(
            f"/operations/trips/{key}/actions", json=action_payload,
        )
        assert unauthenticated.status_code == 401
        authorized = client.post(f"/operations/trips/{key}/actions", json=action_payload)
        assert authorized.status_code == 200

    events = service.repository.events(key)
    manual_events = [event for event in events if event["source"] == "operator"]
    assert {event["event_type"] for event in manual_events} == {
        "MANUAL_FINALIZE", "MANUAL_REOPEN", "MANUAL_UNDO_DETECTION", "MANUAL_CORRECT_TIMES",
    }
    assert all(event["justification"] for event in manual_events)
