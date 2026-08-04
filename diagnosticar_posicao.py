#!/usr/bin/env python3
"""Diagnóstico seguro da cadeia viagem -> terminal -> posição no Trafegus."""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from app.integrations.trafegus import TrafegusClient, TrafegusError
from diagnosticar_trafegus import _describe, _sanitize


PLATE_KEYS = {"placa", "placaveiculo", "placa_veiculo", "veiculo_placa"}


def _records_for_plate(value: Any, plate: str) -> list[dict[str, Any]]:
    """Localiza registros da placa sem presumir o envelope da resposta."""
    matches: list[dict[str, Any]] = []
    if isinstance(value, dict):
        normalized = {str(key).lower(): item for key, item in value.items()}
        if any(
            str(normalized.get(key, "")).replace("-", "").upper() == plate
            for key in PLATE_KEYS
        ):
            matches.append(value)
        else:
            for item in value.values():
                matches.extend(_records_for_plate(item, plate))
    elif isinstance(value, list):
        for item in value:
            matches.extend(_records_for_plate(item, plate))
    return matches


def _report(name: str, result: dict[str, Any] | None) -> dict[str, Any]:
    if result is None:
        return {
            "consulta": name,
            "executada": False,
            "motivo": "identificador necessário não encontrado na viagem",
        }
    payload = result.get("data")
    report: dict[str, Any] = {
        "consulta": name,
        "executada": True,
        "ok_http": bool(result.get("ok")),
        "http_status": result.get("http_status"),
        "estrutura": _describe(payload),
        "dados_seguros": _sanitize(payload),
    }
    if result.get("error"):
        report["erro_http"] = result["error"]
    return report


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Consulta a posição oficial de uma viagem ativa, somente em leitura."
    )
    parser.add_argument("placa", help="Placa no formato ABC1234 ou ABC1D23")
    args = parser.parse_args()

    try:
        result = await TrafegusClient().diagnose_position(args.placa)
    except (TrafegusError, ValueError) as exc:
        print(json.dumps({"status": "erro", "mensagem": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    active_result = result["active_trip_positions"]
    active_payload = active_result.get("data")
    matches = _records_for_plate(active_payload, result["plate"])
    output = {
        "diagnostico_posicao": {
            "placa": result["plate"],
            "data_hora_utc": datetime.now(timezone.utc).isoformat(),
            "modo": "somente_leitura",
            "fonte": "BuscarPosicaoVeiculoViagem / ultima-posicao-viagem",
            "observacao_id_posicao": "Esta consulta oficial não exige IdPosicao.",
        },
        "viagem_ativa": {
            "encontrada_para_placa": bool(matches),
            "quantidade_registros_encontrados": len(matches),
            "dados_seguros": _sanitize(matches),
        },
        "consultas": [
            _report("posicoes_das_viagens_ativas", active_result),
            _report("nao_conformidades", result["nonconformities"]),
        ],
        "proximo_passo": (
            "Validar as coordenadas e o horário da placa; depois enviar a posição "
            "ao TomTom para calcular quilômetros restantes e previsão de chegada."
        ),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
