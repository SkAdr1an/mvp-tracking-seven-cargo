from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


def test_mutating_operational_endpoints_require_panel_session(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "public_trip_token_pepper", "test-pepper")
    client = TestClient(app)
    requests = [
        ("post", "/operations/trips/missing/route", {"route_id": "missing"}),
        ("post", "/operations/return-candidates/1/decision", {"decision": "LATER"}),
        ("post", "/traffic/manual", {}),
        ("patch", "/traffic/manual/missing", {}),
        ("post", "/deviations/1/acknowledge", {}),
        ("post", "/deviations/1/close", {}),
        ("post", "/operations/trips/missing/driver-association", {}),
    ]
    for method, path, payload in requests:
        assert client.request(method, path, json=payload).status_code == 401


def test_tracking_is_fail_closed_when_key_is_missing(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "public_trip_token_pepper", "test-pepper")
    monkeypatch.setattr(settings, "tracking_api_key", "")
    client = TestClient(app)
    assert client.get("/tracking/drivers/active").status_code == 401
