from __future__ import annotations

import asyncio
import json
import socket
import ssl
import time
from urllib.parse import urlsplit

from app.core.config import ENV_FILE, get_settings
from app.integrations.trafegus import TrafegusClient, TrafegusError


def _timed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


async def diagnose() -> tuple[dict[str, object], int]:
    settings = get_settings()
    client = TrafegusClient()
    parsed = urlsplit(client.base_url)
    host = parsed.hostname or ""
    port = parsed.port or 443
    report: dict[str, object] = {
        "configuration": {
            "env_file": str(ENV_FILE),
            "env_file_absolute": ENV_FILE.is_absolute(),
            "base_url": f"{parsed.scheme}://{host}{parsed.path}",
            "username": {"exists": bool(client.username), "length": len(client.username)},
            "password": {"exists": bool(client.password), "length": len(client.password)},
            "document": {"exists": bool(client.document), "length": len(client.document)},
            "app_id": {"exists": bool(client.app_id), "length": len(client.app_id)},
            "timeout_seconds": client.timeout_seconds,
            "retry_attempts": client.retry_attempts,
        },
        "phases": {},
    }
    phases = report["phases"]
    assert isinstance(phases, dict)

    started = time.perf_counter()
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
        phases["dns"] = {
            "status": "success",
            "address_count": len({item[4][0] for item in addresses}),
            "elapsed_ms": _timed(started),
        }
    except socket.gaierror as exc:
        phases["dns"] = {"status": "failure", "category": "dns", "message": str(exc), "elapsed_ms": _timed(started)}
        return report, 1

    started = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=client.timeout_seconds)
        writer.close()
        await writer.wait_closed()
        phases["tcp"] = {"status": "success", "elapsed_ms": _timed(started)}
    except Exception as exc:
        phases["tcp"] = {"status": "failure", "category": "connection", "message": type(exc).__name__, "elapsed_ms": _timed(started)}
        return report, 1

    started = time.perf_counter()
    try:
        context = ssl.create_default_context()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=context, server_hostname=host),
            timeout=client.timeout_seconds,
        )
        writer.close()
        await writer.wait_closed()
        phases["tls"] = {"status": "success", "elapsed_ms": _timed(started)}
    except ssl.SSLError as exc:
        phases["tls"] = {"status": "failure", "category": "tls", "message": type(exc).__name__, "elapsed_ms": _timed(started)}
        return report, 1

    started = time.perf_counter()
    try:
        result = await client.active_trips_with_details()
        telemetry = result.get("_telemetry") or {}
        phases["authentication"] = {"status": "success"}
        phases["session"] = {"status": "success", "reuse": "one token per collection cycle; one renewal on 401/403"}
        phases["fleet_query"] = {
            "status": "success",
            "http_status": telemetry.get("http_status"),
            "request_count": telemetry.get("request_count"),
            "vehicle_count": telemetry.get("vehicle_count"),
            "elapsed_ms": _timed(started),
        }
        phases["parsing"] = {"status": "success"}
        phases["internal_conversion"] = {"status": "not_run", "reason": "diagnostic stops before operational mutation"}
        phases["persistence_cache"] = {"status": "not_run", "reason": "diagnostic is read-only"}
        return report, 0
    except TrafegusError as exc:
        phases[exc.phase] = {
            "status": "failure",
            "category": exc.category,
            "http_status": exc.http_status,
            "message": str(exc),
            "elapsed_ms": _timed(started),
        }
        return report, 1


async def main() -> int:
    report, exit_code = await diagnose()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
