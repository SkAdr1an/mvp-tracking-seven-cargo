#!/usr/bin/env python3
"""Diagnóstico seguro da resposta do Trafegus para uma placa.

O script usa o cliente já configurado no projeto, executa somente consultas GET
e exibe a estrutura recebida sem revelar credenciais, token ou documentos.
"""

import argparse
import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any

from app.integrations.trafegus import TrafegusClient, TrafegusError


SENSITIVE_KEYS = re.compile(
    r"(^|_)(senha|password|token|authorization|cpf|cnpj|documento|rg|cnh|email|"
    r"telefone|celular|pix|banco|agencia|conta|renavam|chassi|antt|rntc|crlv)($|_)",
    re.IGNORECASE,
)
MAX_DEPTH = 10
MAX_LIST_ITEMS = 30
MAX_TEXT_LENGTH = 500


def _sanitize(value: Any, *, key: str = "", depth: int = 0) -> Any:
    """Remove segredos/documentos e limita respostas excessivamente grandes."""
    if SENSITIVE_KEYS.search(key):
        return "[OCULTO]"
    if depth >= MAX_DEPTH:
        return "[NÍVEL MÁXIMO ATINGIDO]"
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize(item_value, key=str(item_key), depth=depth + 1)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        visible = [
            _sanitize(item, key=key, depth=depth + 1)
            for item in value[:MAX_LIST_ITEMS]
        ]
        if len(value) > MAX_LIST_ITEMS:
            visible.append(f"[+{len(value) - MAX_LIST_ITEMS} itens omitidos]")
        return visible
    if isinstance(value, str) and len(value) > MAX_TEXT_LENGTH:
        return value[:MAX_TEXT_LENGTH] + "...[TEXTO TRUNCADO]"
    return value


def _describe(value: Any, depth: int = 0) -> Any:
    """Mostra nomes e tipos dos campos, sem repetir seus valores."""
    if depth >= 6:
        return "..."
    if isinstance(value, dict):
        return {str(key): _describe(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return {
            "tipo": "lista",
            "quantidade": len(value),
            "estrutura_primeiro_item": _describe(value[0], depth + 1) if value else None,
        }
    if value is None:
        return "nulo"
    return type(value).__name__


def _endpoint_report(name: str, result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("data")
    return {
        "consulta": name,
        "ok": bool(result.get("ok")),
        "http_status": result.get("http_status"),
        "estrutura": _describe(payload),
        "dados_seguros": _sanitize(payload),
        **({"erro": result.get("error")} if not result.get("ok") else {}),
    }


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exibe a resposta detalhada e protegida do Trafegus para uma placa."
    )
    parser.add_argument("placa", help="Placa no formato ABC1234 ou ABC1D23")
    args = parser.parse_args()

    try:
        result = await TrafegusClient().consult_plate(args.placa)
    except (TrafegusError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "erro", "mensagem": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    report = {
        "diagnostico": {
            "placa": result["plate"],
            "data_hora_utc": datetime.now(timezone.utc).isoformat(),
            "modo": "somente_leitura",
            "seguranca": "credenciais, tokens e documentos ocultados",
        },
        "endpoints": [
            _endpoint_report("veiculo", result["vehicle"]),
            _endpoint_report("ultima_posicao_veiculo", result["last_position"]),
            _endpoint_report("eventos", result["events"]),
            _endpoint_report("ultima_viagem", result["trip"]),
        ],
        "proxima_analise": [
            "identificar campos de motorista, terminal e tecnologia",
            "confirmar o formato real retornado para posição e eventos",
            "usar os identificadores encontrados nas consultas específicas liberadas",
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
