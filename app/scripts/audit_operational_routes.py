"""Read-only, credential-free audit of the operational route catalog."""

from __future__ import annotations

import hashlib
import json
import sqlite3

from app.core.config import get_settings
from app.services.operational_route_catalog import ROUTE_SPECS


def main() -> None:
    connection = sqlite3.connect(
        f"file:{get_settings().operations_database_path.as_posix()}?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    route_ids = [spec["id"] for spec in ROUTE_SPECS]
    placeholders = ",".join("?" for _ in route_ids)
    rows = connection.execute(
        f"""SELECT r.id,r.origin_site_id,r.destination_site_id,r.sla_minutes,
                   r.operational_duration_minutes,g.version,g.source,g.provider,
                   g.distance_m,g.duration_seconds,g.active,g.geometry_json,
                   l.origin_site_id linked_origin_site_id,
                   l.destination_site_id linked_destination_site_id
            FROM route_configs r
            JOIN route_geometry_versions g ON g.route_id=r.id AND g.active=1
            JOIN route_site_links l ON l.route_id=r.id
            WHERE r.id IN ({placeholders}) ORDER BY r.id""",
        route_ids,
    ).fetchall()
    routes = []
    for row in rows:
        value = dict(row)
        geometry = json.loads(value.pop("geometry_json"))
        value["point_count"] = len(geometry)
        value["distance_km"] = round(float(value.pop("distance_m")) / 1000, 3)
        value["duration_minutes"] = round(float(value.pop("duration_seconds")) / 60, 2)
        routes.append(value)
    preserved = connection.execute(
        """SELECT route_id,version,source,created_at,geometry_json
           FROM route_geometry_versions
           WHERE route_id=? AND active=1""",
        ("betim-jaboatao",),
    ).fetchone()
    usage = [dict(row) for row in connection.execute(
        """SELECT provider,result,http_status,count(*) request_count
           FROM routing_api_usage
           WHERE context LIKE 'controlled_preflight:%'
              OR context LIKE 'catalog_provision:%'
           GROUP BY provider,result,http_status ORDER BY provider,result"""
    )]
    print(json.dumps({
        "routes": routes,
        "preserved_tomtom": {
            "route_id": preserved["route_id"], "version": preserved["version"],
            "source": preserved["source"], "created_at": preserved["created_at"],
            "point_count": len(json.loads(preserved["geometry_json"])),
            "geometry_sha256": hashlib.sha256(preserved["geometry_json"].encode()).hexdigest(),
        },
        "usage": usage,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
