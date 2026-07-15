from typing import Any

import httpx

from app.core.config import get_settings


class WeatherClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or get_settings().openweather_api_key
        self.base_url = "https://api.openweathermap.org/data/2.5/weather"

    async def get_current_weather(self, city: str) -> dict[str, Any]:
        if not self.api_key:
            return {"status": "pending", "message": "OPENWEATHER_API_KEY not configured"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                self.base_url,
                params={"q": city, "appid": self.api_key, "units": "metric"},
            )
            response.raise_for_status()
            return response.json()
