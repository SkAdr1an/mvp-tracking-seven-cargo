from typing import Any


class TrafegusClient:
    async def get_incidents(self, region: str) -> dict[str, Any]:
        return {
            "status": "pending",
            "message": "Trafegus integration is not implemented yet.",
            "region": region,
        }
