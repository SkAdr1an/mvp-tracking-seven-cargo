"""Controlled ORS preflight; never prints credentials or raw provider payloads."""

from __future__ import annotations

import asyncio
import json

from app.integrations.openrouteservice import OpenRouteServiceClient
from app.services.operational_route_catalog import _distance_m
from app.services.routing_provider import validate_route_geometry


ORIGIN = {"latitude": -8.207223071201726, "longitude": -34.964031908513675}
DESTINATION = {"latitude": -8.676618, "longitude": -35.576843}


async def main() -> None:
    payload = await OpenRouteServiceClient().get_route(
        f"{ORIGIN['latitude']},{ORIGIN['longitude']}",
        f"{DESTINATION['latitude']},{DESTINATION['longitude']}",
        travel_mode="truck",
        include_traffic=False,
        request_context="controlled_preflight:jaboatao-palmares",
    )
    points = validate_route_geometry(payload)
    summary = (payload["routes"][0].get("summary") or {})
    distance_m = float(summary.get("lengthInMeters") or 0)
    duration_seconds = float(summary.get("travelTimeInSeconds") or 0)
    start_offset_m = _distance_m(ORIGIN, points[0])
    end_offset_m = _distance_m(DESTINATION, points[-1])
    direct_m = _distance_m(ORIGIN, DESTINATION)
    validation = payload.get("_validation") or {}
    valid = (
        validation.get("collection_type") == "FeatureCollection"
        and validation.get("geometry_type") == "LineString"
        and len(points) >= 2 and points[0] != points[-1]
        and distance_m > 0 and duration_seconds > 0
        and start_offset_m <= 10_000 and end_offset_m <= 10_000
        and distance_m >= direct_m * 0.8 and distance_m <= direct_m * 4
    )
    print(json.dumps({
        "http_status": 200,
        "feature_collection": validation.get("collection_type"),
        "geometry_type": validation.get("geometry_type"),
        "point_count": len(points),
        "distance_km": round(distance_m / 1000, 3),
        "duration_minutes": round(duration_seconds / 60, 2),
        "start_offset_m": round(start_offset_m, 1),
        "end_offset_m": round(end_offset_m, 1),
        "road_route_plausible": valid,
    }, ensure_ascii=False))
    if not valid:
        raise RuntimeError("OpenRouteService preflight returned invalid road geometry")


if __name__ == "__main__":
    asyncio.run(main())
