from typing import Any

import httpx

from app.core.config import get_settings
from app.integrations.tomtom import AuthError, RateLimitError, UnavailableError


class WeatherClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or get_settings().openweather_api_key
        self.base_url = "https://api.openweathermap.org/data/2.5/weather"
        self.forecast_url = "https://api.openweathermap.org/data/2.5/forecast"

    async def get_current_weather(self, city: str) -> dict[str, Any]:
        if not self.api_key:
            raise AuthError("OPENWEATHER_API_KEY not configured")

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(
                    self.base_url,
                    params={"q": city, "appid": self.api_key, "units": "metric"},
                )
            except httpx.TimeoutException as exc:
                raise UnavailableError("OpenWeather timeout") from exc
            except httpx.RequestError as exc:
                raise UnavailableError("OpenWeather unavailable") from exc

            if response.status_code in {401, 403}:
                raise AuthError("OpenWeather authentication failed")
            if response.status_code == 429:
                raise RateLimitError("OpenWeather rate limit exceeded")
            if response.status_code >= 500:
                raise UnavailableError("OpenWeather service unavailable")

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise UnavailableError("OpenWeather request failed") from exc

            return response.json()

    async def get_current_weather_by_coords(self, latitude: float, longitude: float) -> dict[str, Any]:
        if not self.api_key:
            raise AuthError("OPENWEATHER_API_KEY not configured")

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(
                    self.base_url,
                    params={"lat": latitude, "lon": longitude, "appid": self.api_key, "units": "metric"},
                )
            except httpx.TimeoutException as exc:
                raise UnavailableError("OpenWeather timeout") from exc
            except httpx.RequestError as exc:
                raise UnavailableError("OpenWeather unavailable") from exc

            if response.status_code in {401, 403}:
                raise AuthError("OpenWeather authentication failed")
            if response.status_code == 429:
                raise RateLimitError("OpenWeather rate limit exceeded")
            if response.status_code >= 500:
                raise UnavailableError("OpenWeather service unavailable")

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise UnavailableError("OpenWeather request failed") from exc

            return response.json()

    async def get_forecast_by_coords(self, latitude: float, longitude: float) -> dict[str, Any]:
        """Retorna previsão em blocos de três horas para uma coordenada."""
        if not self.api_key:
            raise AuthError("OPENWEATHER_API_KEY not configured")
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(
                    self.forecast_url,
                    params={
                        "lat": latitude,
                        "lon": longitude,
                        "appid": self.api_key,
                        "units": "metric",
                        "lang": "pt_br",
                    },
                )
            except httpx.TimeoutException as exc:
                raise UnavailableError("OpenWeather forecast timeout") from exc
            except httpx.RequestError as exc:
                raise UnavailableError("OpenWeather forecast unavailable") from exc
            if response.status_code in {401, 403}:
                raise AuthError("OpenWeather authentication failed")
            if response.status_code == 429:
                raise RateLimitError("OpenWeather rate limit exceeded")
            if response.status_code >= 500:
                raise UnavailableError("OpenWeather forecast unavailable")
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise UnavailableError("OpenWeather forecast request failed") from exc
            return response.json()
