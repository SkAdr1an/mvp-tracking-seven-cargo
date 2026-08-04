from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.portal_homologation import summarize_homologation


def main() -> None:
    parser = argparse.ArgumentParser(description="Resume eventos exportados da homologação do Portal do Motorista")
    parser.add_argument("events", type=Path, help="JSON de eventos separado do banco operacional")
    args = parser.parse_args()
    events = json.loads(args.events.read_text(encoding="utf-8"))
    if not isinstance(events, list):
        raise SystemExit("O arquivo deve conter uma lista JSON.")
    print(json.dumps(summarize_homologation(events), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
