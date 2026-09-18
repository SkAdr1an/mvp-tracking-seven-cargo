from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from app.core.config import get_settings
from app.main import (
    _database_backup_collector,
    _fleet_collector,
    _route_geometry_bootstrap,
    _traffic_collector,
)
from app.storage.migrations import validate_database_schema


logger = logging.getLogger(__name__)


async def run() -> None:
    settings = get_settings()
    validate_database_schema(settings.operations_database_path)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGTERM", "SIGINT"):
        if hasattr(signal, name):
            with suppress(NotImplementedError):
                loop.add_signal_handler(getattr(signal, name), stop.set)

    tasks: list[asyncio.Task[None]] = []
    if settings.route_geometry_bootstrap_enabled:
        tasks.append(asyncio.create_task(_route_geometry_bootstrap(), name="route-geometry-bootstrap"))
    if settings.fleet_collector_enabled:
        tasks.append(asyncio.create_task(_fleet_collector(), name="fleet-collector"))
    if settings.traffic_collector_enabled:
        tasks.append(asyncio.create_task(_traffic_collector(), name="traffic-collector"))
    if settings.operations_backup_enabled:
        tasks.append(asyncio.create_task(_database_backup_collector(), name="database-backup"))
    if not tasks:
        raise RuntimeError("No background collector is enabled")

    logger.info("Background worker started tasks=%s", ",".join(task.get_name() for task in tasks))
    await stop.wait()
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # HTTP client INFO messages include full query strings and can expose
    # provider credentials. Integration failures are logged by our services
    # with sanitized categories instead.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    asyncio.run(run())


if __name__ == "__main__":
    main()
