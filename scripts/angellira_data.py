"""Importa e, sob comando explícito, geocodifica a base AngelLira."""

from __future__ import annotations

import argparse
import asyncio
import json

from app.core.config import get_settings
from app.integrations.tomtom import TomTomClient
from app.services.angellira import AngelLiraService
from app.services.route_profiles import BETIM_JABOATAO
from app.storage.angellira import AngelLiraRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("import", "status", "geocode"),
        help="Ação offline; nenhuma delas consulta o Trafegus.",
    )
    parser.add_argument("--dataset-path", help="Pasta do dataset ou pacote que contém dados/.")
    parser.add_argument("--actor", default="offline-cli", help="Identificação para auditoria.")
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Máximo de postos preparados consultados no lote de geocodificação.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = get_settings()
    service = AngelLiraService(AngelLiraRepository(settings.operations_database_path))

    if args.action == "import":
        result = service.import_package(
            args.dataset_path or settings.angellira_dataset_path,
            actor=args.actor,
        )
    elif args.action == "status":
        result = service.status()
    else:
        if args.limit < 1:
            raise SystemExit("--limit deve ser maior que zero")
        result = asyncio.run(
            service.geocode_batch(
                TomTomClient(),
                limit=args.limit,
                corridor=list(BETIM_JABOATAO.coordinates),
            )
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
