#!/usr/bin/env python3
"""Consulta segura e somente leitura de uma placa no Trafegus."""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from app.integrations.trafegus import TrafegusClient, TrafegusError


def _first_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return next((item for item in value if isinstance(item, dict)), None)
    return None


def _endpoint(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(result.get("ok")),
        "http_status": result.get("http_status"),
    }


def safe_summary(result: dict[str, Any]) -> dict[str, Any]:
    vehicle_result = result["vehicle"]
    vehicle_payload = vehicle_result.get("data") or {}
    vehicle = _first_dict(vehicle_payload.get("veiculo"))

    position_result = result["last_position"]
    position_payload = position_result.get("data") or {}
    position = _first_dict(
        position_payload.get("Posicao") or position_payload.get("posicao")
    )

    events_result = result["events"]
    events_payload = events_result.get("data") or {}
    events = events_payload.get("eventos") or events_payload.get("Eventos") or []
    if isinstance(events, dict):
        events = [events]
    if not isinstance(events, list):
        events = []
    latest_event = _first_dict(events)

    trip_result = result["trip"]
    trip_payload = trip_result.get("data") or {}
    trip = _first_dict(trip_payload.get("viagens") or trip_payload.get("viagem"))

    return {
        "consulta": {
            "placa": result["plate"],
            "data_hora_utc": datetime.now(timezone.utc).isoformat(),
            "modo": "somente_leitura",
        },
        "veiculo": {
            **_endpoint(vehicle_result),
            "encontrado": vehicle is not None,
            "placa": vehicle.get("placa") if vehicle else None,
            "frota": vehicle.get("frota") if vehicle else None,
            "marca": vehicle.get("marca") if vehicle else None,
            "modelo": vehicle.get("modelo") if vehicle else None,
            "ano_modelo": vehicle.get("ano_modelo") if vehicle else None,
        },
        "ultima_posicao": {
            **_endpoint(position_result),
            "encontrada": position is not None,
            "data_bordo": position.get("DataBordo") if position else None,
            "data_cadastro": position.get("DataCadastro") if position else None,
            "cidade": position.get("Cidade") if position else None,
            "uf": position.get("UF") if position else None,
            "latitude": position.get("Latitude") if position else None,
            "longitude": position.get("Longitude") if position else None,
            "velocidade": position.get("Velocidade") if position else None,
            "ignicao": position.get("Ignicao") if position else None,
        },
        "eventos": {
            **_endpoint(events_result),
            "quantidade": len(events),
            "ultimo": {
                "tipo": latest_event.get("descricao_tipo_evento"),
                "descricao": latest_event.get("descricao"),
                "data_bordo": latest_event.get("data_bordo"),
                "posicao": latest_event.get("posicao"),
            }
            if latest_event
            else None,
        },
        "viagem": {
            **_endpoint(trip_result),
            "encontrada": trip is not None,
            "codigo": (
                trip.get("codigoSM") or trip.get("viagemId") or trip.get("codigo")
                if trip
                else None
            ),
            "status": trip.get("status_viagem") if trip else None,
            "rota": trip.get("rota_descricao") if trip else None,
        },
    }


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Consulta uma placa no Trafegus em modo somente leitura."
    )
    parser.add_argument("placa", help="Placa no formato ABC1234 ou ABC1D23")
    args = parser.parse_args()

    try:
        result = await TrafegusClient().consult_plate(args.placa)
    except (TrafegusError, ValueError) as exc:
        print(json.dumps({"status": "erro", "mensagem": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(safe_summary(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
