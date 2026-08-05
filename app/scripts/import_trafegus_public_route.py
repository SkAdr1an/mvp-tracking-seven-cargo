"""Import an exact route geometry from a user-authorized public Trafegus map."""

from __future__ import annotations

import argparse
import asyncio
import json
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.services.operational_route_catalog import (
    GEOMETRY_VERSION,
    ROUTE_SPECS,
    operational_route_catalog,
)
from app.services.routing_provider import validate_route_geometry
from app.storage.operations import utc_now


class _PublicMapParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.polyline: list[str] = []
        self._inside_polyline = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        self._inside_polyline = tag == "textarea" and values.get("id") == "polyline"

    def handle_data(self, data: str) -> None:
        if self._inside_polyline:
            self.polyline.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "textarea":
            self._inside_polyline = False


def _download_geometry(url: str) -> list[dict[str, float]]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "web.grparceria.com.br":
        raise ValueError("Only an HTTPS public map from web.grparceria.com.br is accepted")
    request = Request(url, headers={"User-Agent": "SevenCargoRouteImporter/1.0"})
    with urlopen(request, timeout=30) as response:  # noqa: S310 - host is allow-listed above
        content = response.read().decode("utf-8")
    parser = _PublicMapParser()
    parser.feed(content)
    raw = json.loads("".join(parser.polyline))
    points = [
        {"latitude": float(point["lat"]), "longitude": float(point["lng"])}
        for point in raw
    ]
    return validate_route_geometry({"routes": [{"legs": [{"points": points}]}]})


def import_route(url: str, route_id: str) -> dict[str, object]:
    spec = next((item for item in ROUTE_SPECS if item["id"] == route_id), None)
    if spec is None:
        raise ValueError(f"Route is not authorized in the catalog: {route_id}")
    catalog = operational_route_catalog
    origin = catalog._site(spec["origin_site_id"])
    destination = catalog._site(spec["destination_site_id"])
    route = catalog._route(spec, origin, destination)
    points = _download_geometry(url)
    version = f"{GEOMETRY_VERSION}-trafegus-public-v1"
    mandatory = [
        [origin["latitude"], origin["longitude"]],
        [destination["latitude"], destination["longitude"]],
    ]
    with catalog.repository.connect() as connection:
        connection.execute(
            "UPDATE route_geometry_versions SET active=0 WHERE route_id=?", (route_id,)
        )
        connection.execute(
            """INSERT INTO route_geometry_versions
               (route_id,version,source,geometry_json,mandatory_points_json,
                corridor_m,segment_tolerances_json,active,created_at,provider)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(route_id,version) DO UPDATE SET
                 source=excluded.source,geometry_json=excluded.geometry_json,
                 mandatory_points_json=excluded.mandatory_points_json,
                 provider=excluded.provider,active=1""",
            (
                route_id, version, "trafegus-public-trip-map",
                json.dumps(points, separators=(",", ":")), json.dumps(mandatory),
                300, "[]", 1, utc_now(), "Trafegus",
            ),
        )
    catalog.repository.upsert_route(route)
    catalog._link_sites(route_id, spec["origin_site_id"], spec["destination_site_id"])
    return {"route_id": route_id, "version": version, "point_count": len(points)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("route_id")
    parser.add_argument("--provision-missing", action="store_true")
    args = parser.parse_args()
    result = import_route(args.url, args.route_id)
    if args.provision_missing:
        result["catalog"] = asyncio.run(
            operational_route_catalog.ensure_routes(explicit=True)
        )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
