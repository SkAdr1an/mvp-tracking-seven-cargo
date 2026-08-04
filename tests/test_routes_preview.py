from fastapi.testclient import TestClient

from app import main as main_module
from app.integrations.tomtom import AuthError

client = TestClient(main_module.app)


def test_routes_preview_returns_calculated_metrics(monkeypatch) -> None:
    async def fake_geocode(self, query: str) -> dict[str, object]:
        return {
            "results": [
                {
                    "address": {"freeformAddress": query},
                    "position": {"lat": -19.97, "lon": -44.2},
                }
            ]
        }

    async def fake_route(self, origin: str, destination: str, travel_mode: str = "car", include_traffic: bool = False, departure_at: str | None = None, request_context: str = "unspecified") -> dict[str, object]:
        return {
            "routes": [
                    {
                        "legs": [{"points": [
                            {"latitude": -19.97, "longitude": -44.2},
                            {"latitude": -8.2, "longitude": -35.0},
                        ]}],
                        "summary": {
                        "lengthInMeters": 1500000,
                        "travelTimeInSeconds": 7200,
                        "trafficDelayInSeconds": 1800,
                        "noTrafficTravelTimeInSeconds": 5400,
                        "trafficLengthInMeters": 25000,
                    }
                }
            ]
        }

    monkeypatch.setattr(main_module.TomTomClient, "get_geocode", fake_geocode)
    monkeypatch.setattr(main_module.TomTomClient, "get_route", fake_route)

    response = client.post(
        "/routes/preview",
        json={
            "origin": "Betim, MG, Brasil",
            "destination": "Jaboatão dos Guararapes, PE, Brasil",
            "departure_at": "2026-07-15T03:00:00-03:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["origin"]["address"] == "Betim, MG, Brasil"
    assert payload["destination"]["address"] == "Jaboatão dos Guararapes, PE, Brasil"
    assert payload["distance_km"] == 1500.0
    assert payload["duration_without_traffic_minutes"] == 90.0
    assert payload["duration_with_traffic_minutes"] == 120.0
    assert payload["traffic_delay_minutes"] == 30.0
    assert payload["live_traffic_delay_minutes"] == 30.0
    assert payload["traffic_length_km"] == 25.0
    # 1,500 km at the fleet default (55 km/h), traffic and a 10% buffer.
    assert payload["driving_minutes"] == 1636.364
    assert payload["operational_duration_minutes"] == 1833.0
    assert payload["estimated_arrival_at"] == "2026-07-16T09:33:00-03:00"
    assert payload["average_speed_kmh"] == 55
    assert payload["route_constraints_applied"] is False
    assert payload["status"] == "attention"


def test_routes_preview_returns_tomtom_error(monkeypatch) -> None:
    async def fake_geocode(self, query: str) -> dict[str, object]:
        raise AuthError("tomtom auth failed")

    monkeypatch.setattr(main_module.TomTomClient, "get_geocode", fake_geocode)

    response = client.post(
        "/routes/preview",
        json={
            "origin": "Betim, MG, Brasil",
            "destination": "Jaboatão dos Guararapes, PE, Brasil",
            "departure_at": "2026-07-15T03:00:00-03:00",
        },
    )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["provider"] == "TomTom"
    assert detail["upstream_status"] is not None
    assert detail["upstream_message"]


def test_routes_preview_applies_required_waypoints_and_operational_inputs(monkeypatch) -> None:
    queried: list[str] = []
    route_origins: list[str] = []

    async def fake_geocode(self, query: str) -> dict[str, object]:
        queried.append(query)
        index = len(queried)
        return {"results": [{"address": {"freeformAddress": query}, "position": {"lat": -20 + index, "lon": -45 + index}}]}

    async def fake_route(self, origin: str, destination: str, travel_mode: str = "car", include_traffic: bool = False, departure_at: str | None = None, request_context: str = "unspecified") -> dict[str, object]:
        route_origins.append(origin)
        return {"routes": [{"legs": [{"points": [
            {"latitude": -19, "longitude": -44},
            {"latitude": -17, "longitude": -42},
        ]}], "summary": {"lengthInMeters": 500000, "travelTimeInSeconds": 36000, "trafficDelayInSeconds": 3600, "noTrafficTravelTimeInSeconds": 32400}}]}

    monkeypatch.setattr(main_module.TomTomClient, "get_geocode", fake_geocode)
    monkeypatch.setattr(main_module.TomTomClient, "get_route", fake_route)
    response = client.post("/routes/preview", json={
        "origin": "Origem", "waypoints": ["Posto fiscal A", "Ponto B"], "destination": "Destino",
        "departure_at": "2026-07-15T03:00:00-03:00", "average_speed_kmh": 50,
        "planned_stops_minutes": 45, "risk_buffer_percent": 20,
    })

    assert response.status_code == 200
    payload = response.json()
    assert queried == ["Origem", "Posto fiscal A", "Ponto B", "Destino"]
    assert route_origins == ["-19,-44:-18,-43:-17,-42"]
    assert [point["address"] for point in payload["waypoints"]] == ["Posto fiscal A", "Ponto B"]
    assert payload["route_constraints_applied"] is True
    assert payload["driving_minutes"] == 600
    assert payload["traffic_delay_minutes"] == 60
    assert payload["planned_stops_minutes"] == 45
    assert payload["risk_buffer_minutes"] == 132
    assert payload["operational_duration_minutes"] == 837
