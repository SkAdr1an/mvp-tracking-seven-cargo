"""Verify that operational route provisioning reuses persisted geometries."""

from __future__ import annotations

import asyncio
import json
import sqlite3

from app.core.config import get_settings
from app.services.operational_route_catalog import operational_route_catalog
from app.storage.sqlite_runtime import connect_existing_database


def _usage_count(database_path: str) -> int:
    connection = connect_existing_database(database_path)
    try:
        row = connection.execute("SELECT COUNT(*) FROM routing_api_usage").fetchone()
        return int(row[0]) if row else 0
    finally:
        connection.close()


async def _main() -> None:
    database_path = str(get_settings().operations_database_path)
    before = _usage_count(database_path)
    results = await operational_route_catalog.ensure_routes(explicit=True)
    after = _usage_count(database_path)
    print(
        json.dumps(
            {
                "usage_before": before,
                "usage_after": after,
                "external_call_delta": after - before,
                "routes": results,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    asyncio.run(_main())
