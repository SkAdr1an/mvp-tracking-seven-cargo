from fastapi.testclient import TestClient
import pytest

from app.core.config import get_settings
from app.integrations.driver_tracking import active_drivers, manager_connections
from app.main import app


client = TestClient(app)


def setup_function() -> None:
    active_drivers.clear()
    manager_connections.clear()


@pytest.fixture(autouse=True)
def tracking_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "tracking_api_key", "test-tracking-token")


def test_driver_update_is_broadcast_to_manager() -> None:
    with client.websocket_connect("/tracking/ws/manager?token=test-tracking-token") as manager:
        assert manager.receive_json() == {"type": "initial_drivers", "drivers": {}}

        with client.websocket_connect(
            "/tracking/ws/driver/driver-1?token=test-tracking-token"
        ) as driver:
            driver.send_json(
                {
                    "latitude": -19.967,
                    "longitude": -44.199,
                    "speed_kmh": 65.4,
                }
            )
            update = manager.receive_json()
            assert update["type"] == "driver_update"
            assert update["driver_id"] == "driver-1"
            assert update["status"] == "on_route"
            assert update["location"]["latitude"] == -19.967

        offline = manager.receive_json()
        assert offline["status"] == "offline"


def test_driver_rejects_invalid_location_and_keeps_connection() -> None:
    with client.websocket_connect(
        "/tracking/ws/driver/driver-1?token=test-tracking-token"
    ) as driver:
        driver.send_json({"latitude": 100, "longitude": -44.199})
        error = driver.receive_json()
        assert error["type"] == "validation_error"


def test_tracking_http_fallbacks_use_http_status_codes() -> None:
    headers = {"Authorization": "Bearer test-tracking-token"}
    missing = client.get("/tracking/driver/missing/location", headers=headers)
    assert missing.status_code == 404

    active_drivers["driver-1"] = {
        "location": {"latitude": -19.967, "longitude": -44.199},
        "last_update": "2026-07-21T00:00:00+00:00",
        "status": "on_route",
    }
    invalid = client.post(
        "/tracking/driver/driver-1/status",
        params={"status": "unknown"},
        headers=headers,
    )
    assert invalid.status_code == 422

    response = client.get("/tracking/drivers/active", headers=headers)
    assert response.status_code == 200
    assert response.json()["total"] == 1
