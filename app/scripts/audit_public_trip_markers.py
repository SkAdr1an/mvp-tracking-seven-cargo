"""Read-only audit of marker-producing data for the latest public trip link."""

from __future__ import annotations

import json
import sqlite3

from app.core.config import get_settings
from app.services.public_trip import PublicTripService
from app.storage.operations import OperationsRepository


def main() -> None:
    path = get_settings().operations_database_path
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    links = connection.execute(
        """SELECT l.id,l.trip_key,l.created_at,t.route_id,t.current_driver,t.plate,
                  t.last_latitude,t.last_longitude
           FROM public_trip_links l
           JOIN operational_trips t ON t.trip_key=l.trip_key
           WHERE t.route_id=? ORDER BY l.created_at DESC LIMIT 3""",
        ("betim-jaboatao",),
    ).fetchall()
    geometry = connection.execute(
        """SELECT version,source,geometry_json,mandatory_points_json
           FROM route_geometry_versions
           WHERE route_id=? AND active=1 ORDER BY id DESC LIMIT 1""",
        ("betim-jaboatao",),
    ).fetchone()
    route_points = json.loads(geometry["geometry_json"] or "[]") if geometry else []
    mandatory = json.loads(geometry["mandatory_points_json"] or "[]") if geometry else []
    payload = None
    if links:
        operations = OperationsRepository(path)
        trip = operations.trip(links[0]["trip_key"])
        if trip:
            payload = PublicTripService(operations)._public_payload(trip)
    print(json.dumps({
        "recent_links": [{
            "link_id": row["id"], "trip_key": row["trip_key"],
            "created_at": row["created_at"], "route_id": row["route_id"],
            "has_driver": bool(row["current_driver"]), "plate": row["plate"],
            "has_position": row["last_latitude"] is not None and row["last_longitude"] is not None,
        } for row in links],
        "geometry_version": geometry["version"] if geometry else None,
        "geometry_source": geometry["source"] if geometry else None,
        "geometry_coordinate_count": len(route_points),
        "mandatory_point_count": len(mandatory),
        "mandatory_point_shapes": [type(item).__name__ for item in mandatory],
        "mandatory_point_names": [
            (item.get("name") or item.get("description")) if isinstance(item, dict) else None
            for item in mandatory
        ],
        "public_payload": {
            "geometry_coordinate_count": len(payload["route"]["geometry"]),
            "important_point_count": len(payload["route"]["important_points"]),
            "latest_position_count": int(payload["latest_position"] is not None),
            "origin_marker_count": int(payload["route"]["origin"]["coordinate"] is not None),
            "destination_marker_count": int(payload["route"]["destination"]["coordinate"] is not None),
            "total_marker_count": (
                len(payload["route"]["important_points"])
                + int(payload["latest_position"] is not None)
                + int(payload["route"]["origin"]["coordinate"] is not None)
                + int(payload["route"]["destination"]["coordinate"] is not None)
            ),
        } if payload else None,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
