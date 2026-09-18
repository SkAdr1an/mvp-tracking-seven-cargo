from __future__ import annotations

import argparse
import asyncio
import json

from app.core.config import get_settings
from app.services.routing_provider import RoutingProviderService, validate_route_geometry
from app.services.traffic_monitoring import haversine, route_projection
from app.storage.operations import OperationsRepository, utc_now


ROUTE_ID = "sao-bernardo-contagem-manual"
ALTERNATIVE_ID = "sbc-contagem-rodoanel-leste"
VERSION = "rodoanel-leste-truck-v1"
# Operationally observed eastbound access followed by the eastern Rodoanel arc.
WAYPOINTS = (
    (-23.7630864, -46.5325888),
    (-23.6848, -46.4337),
    (-23.5122, -46.3378),
)


async def provision(*, apply: bool) -> dict[str, object]:
    repository = OperationsRepository(get_settings().operations_database_path)
    route = repository.route(ROUTE_ID)
    if not route:
        raise RuntimeError(f"Rota operacional ausente: {ROUTE_ID}")
    origin_points = [
        (float(route["origin_latitude"]), float(route["origin_longitude"])),
        *WAYPOINTS,
    ]
    origin = ":".join(f"{latitude},{longitude}" for latitude, longitude in origin_points)
    destination = f"{route['destination_latitude']},{route['destination_longitude']}"
    payload = await RoutingProviderService().get_route(
        origin, destination, travel_mode="truck", include_traffic=False,
        request_context=f"authorized_alternative:{ALTERNATIVE_ID}",
    )
    points = validate_route_geometry(payload)
    geometry = [(float(point["latitude"]), float(point["longitude"])) for point in points]
    waypoint_distances = [route_projection(waypoint, geometry)[1] for waypoint in WAYPOINTS]
    if any(distance > 1.5 for distance in waypoint_distances):
        raise RuntimeError("A geometria retornada não respeita os pontos obrigatórios do Rodoanel")
    total_distance_km = sum(haversine(first, second) for first, second in zip(geometry, geometry[1:]))
    if not 450 <= total_distance_km <= 850:
        raise RuntimeError(f"Distância alternativa implausível: {total_distance_km:.1f} km")
    result = {
        "id": ALTERNATIVE_ID,
        "route_id": ROUTE_ID,
        "version": VERSION,
        "provider": payload.get("_provider") or "Routing provider",
        "point_count": len(points),
        "distance_km": round(total_distance_km, 1),
        "waypoint_max_error_km": round(max(waypoint_distances), 3),
        "applied": apply,
    }
    if apply:
        now = utc_now()
        evidence = json.dumps({
            "corridor_m": 500,
            "mandatory_points": [list(point) for point in WAYPOINTS],
            "provider": result["provider"],
            "validation": "truck profile and mandatory waypoint projection",
        }, ensure_ascii=False)
        with repository.connect() as connection:
            connection.execute(
                """INSERT INTO route_alternatives(
                       id,route_id,name,direction,origin_name,destination_name,
                       geometry_json,total_distance_km,source,source_url,
                       validation_status,version,evidence_json,active,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     geometry_json=excluded.geometry_json,total_distance_km=excluded.total_distance_km,
                     source=excluded.source,validation_status=excluded.validation_status,
                     version=excluded.version,evidence_json=excluded.evidence_json,
                     active=1,updated_at=excluded.updated_at""",
                (
                    ALTERNATIVE_ID, ROUTE_ID, "Rota alternativa · Rodoanel Leste",
                    f"{route['origin_name']} → {route['destination_name']}",
                    route["origin_name"], route["destination_name"],
                    json.dumps(points), total_distance_km,
                    f"{result['provider']} truck profile", "", "validated", VERSION,
                    evidence, 1, now, now,
                ),
            )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(provision(apply=args.apply)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
