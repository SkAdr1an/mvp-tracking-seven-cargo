from fastapi.testclient import TestClient

from app import main as main_module


client = TestClient(main_module.app)


def test_integrations_status_has_no_fixed_city_or_weather(monkeypatch) -> None:
    settings = main_module.get_settings()
    monkeypatch.setattr(settings, "tomtom_api_key", "configured")
    monkeypatch.setattr(settings, "openweather_api_key", "configured")
    monkeypatch.setattr(settings, "trafegus_username", "configured")
    monkeypatch.setattr(settings, "trafegus_password", "configured")
    monkeypatch.setattr(settings, "trafegus_documento", "12345678000199")
    response = client.get("/integrations/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["tomtom"] == "configured"
    assert payload["openweather"] == "configured"
    assert payload["trafegus"] == "checking"
    assert payload["trafegus_detail"]["last_success_at"] is None
    assert payload["location"] is None
    assert payload["temperature_c"] is None
    assert "Betim" not in str(payload)
