from app.integrations.trafegus import TrafegusClient
from app.services.routing_provider import RoutingProviderService
from app.integrations.weather import WeatherClient


class RiskEngine:
    def __init__(self) -> None:
        self.routing = RoutingProviderService()
        self.weather = WeatherClient()
        self.trafegus = TrafegusClient()

    async def assess_risk(self, origin: str, destination: str, city: str) -> dict[str, object]:
        route = await self.routing.get_route(
            origin, destination, request_context="explicit_risk_assessment"
        )
        weather = await self.weather.get_current_weather(city)
        incidents = await self.trafegus.get_incidents(city)

        weather_items = weather.get("weather") or []
        weather_description = ""
        if weather_items and isinstance(weather_items[0], dict):
            weather_description = str(weather_items[0].get("description", "")).lower()

        risk_factors: list[str] = []
        if any(term in weather_description for term in ("rain", "storm", "thunder", "chuva", "tempestade")):
            risk_factors.append("adverse_weather")
        incident_items = incidents.get("incidents") or []
        if incident_items:
            risk_factors.append("reported_incidents")

        level = "high" if len(risk_factors) >= 2 else "attention" if risk_factors else "normal"
        return {
            "route": route,
            "weather": weather,
            "incidents": incidents,
            "risk_level": level,
            "risk_factors": risk_factors,
            "summary": "Route requires attention" if risk_factors else "No active risk factors identified",
        }
