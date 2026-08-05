"""Verify the latest Edge public-trip URL without printing its token."""

from __future__ import annotations

import json
import sqlite3
import sys
from urllib.parse import urlparse

import httpx


def main(history_copy: str) -> None:
    connection = sqlite3.connect(f"file:{history_copy}?mode=ro", uri=True)
    row = connection.execute(
        """SELECT url FROM urls
           WHERE url LIKE '%/viagem/%'
           ORDER BY last_visit_time DESC LIMIT 1"""
    ).fetchone()
    if not row:
        print(json.dumps({"found_recent_public_link": False}))
        return
    url = str(row[0])
    token = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    if len(token) < 43:
        print(json.dumps({"found_recent_public_link": False}))
        return
    results = {}
    for label, base in (
        ("direct_backend", "http://127.0.0.1:8000"),
        ("frontend_configured_backend", "http://192.168.18.217:8000"),
    ):
        response = httpx.get(
            f"{base}/api/public/trips/{token}",
            headers={"Accept": "application/json"},
            timeout=20,
        )
        payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        route = payload.get("route") or {}
        important = route.get("important_points") or []
        serialized = json.dumps(payload, ensure_ascii=False)
        results[label] = {
            "status": response.status_code,
            "build": response.headers.get("X-Seven-Public-Trip-Build"),
            "geometry_coordinate_count": len(route.get("geometry") or []),
            "important_point_count": len(important),
            "latest_position_count": int(payload.get("latest_position") is not None),
            "contains_ponto_1": "Ponto 1" in serialized,
            "contains_ponto_2": "Ponto 2" in serialized,
            "origin": {
                "name": (route.get("origin") or {}).get("name"),
                "city": (route.get("origin") or {}).get("city"),
                "state": (route.get("origin") or {}).get("state"),
            },
            "destination": {
                "name": (route.get("destination") or {}).get("name"),
                "city": (route.get("destination") or {}).get("city"),
                "state": (route.get("destination") or {}).get("state"),
            },
        }
    print(json.dumps({"found_recent_public_link": True, "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
