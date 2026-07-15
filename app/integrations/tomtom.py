from typing import Any

import httpx

from app.core.config import get_settings


class TomTomClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or get_settings().tomtom_api_key
        self.base_url = "https://api.tomtom.com"

    async def get_route(self, origin: str, destination: str) -> dict[str, Any]:
        if not self.api_key:
            return {"status": "pending", "message": "TOMTOM_API_KEY not configured"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.base_url}/routing/1/calculateRoute",
                params={
                    "key": self.api_key,
                    "routeType": "fastest",
                    "travelMode": "car",
                    "point": f"{origin}:{destination}",
                },
            )
            response.raise_for_status()
            return response.json()
