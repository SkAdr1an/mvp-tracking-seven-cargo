from __future__ import annotations

import concurrent.futures
import tempfile
import time
from pathlib import Path

import httpx
from app.core.security import PANEL_SESSION_COOKIE, configured_user, create_panel_session


def main() -> None:
    principal = configured_user("skadrian")[0]
    token, _ = create_panel_session(principal)
    cookie = {PANEL_SESSION_COOKIE: token}
    endpoint = "http://127.0.0.1:8000/operations/trips/trafegus%3A967/report"
    with httpx.Client(cookies=cookie, timeout=5) as baseline:
        baseline_health: list[float] = []
        baseline_auth: list[float] = []
        for _ in range(5):
            sample = time.perf_counter(); baseline.get("http://127.0.0.1:8000/health/live"); baseline_health.append(time.perf_counter() - sample)
            sample = time.perf_counter(); baseline.get("http://127.0.0.1:8000/api/auth/session"); baseline_auth.append(time.perf_counter() - sample)

    def report() -> httpx.Response:
        return httpx.post(endpoint, cookies=cookie, headers={"Accept": "application/pdf"}, timeout=75)

    started = time.perf_counter()
    health_times: list[float] = []
    auth_times: list[float] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(report) for _ in range(2)]
        with httpx.Client(cookies=cookie, timeout=5) as probe:
            while not all(future.done() for future in futures):
                sample = time.perf_counter()
                probe.get("http://127.0.0.1:8000/health/live")
                health_times.append(time.perf_counter() - sample)
                sample = time.perf_counter()
                probe.get("http://127.0.0.1:8000/api/auth/session")
                auth_times.append(time.perf_counter() - sample)
        responses = [future.result() for future in futures]
    print({
        "duration_seconds": round(time.perf_counter() - started, 3),
        "baseline_health_max_seconds": round(max(baseline_health), 3),
        "baseline_auth_max_seconds": round(max(baseline_auth), 3),
        "statuses": [response.status_code for response in responses],
        "sizes": [len(response.content) for response in responses],
        "signatures": [response.content[:5].decode("ascii", "replace") for response in responses],
        "content_types": [response.headers.get("content-type") for response in responses],
        "attachments": [response.headers.get("content-disposition", "").startswith("attachment") for response in responses],
        "health_max_seconds": round(max(health_times), 3),
        "auth_max_seconds": round(max(auth_times), 3),
        "temporary_directories_after": len(list(Path(tempfile.gettempdir()).glob("seven-trip-report-*"))),
    })


if __name__ == "__main__":
    main()
