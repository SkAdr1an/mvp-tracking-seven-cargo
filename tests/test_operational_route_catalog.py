from __future__ import annotations

import json
import math

import pytest

from app.services.operational_route_catalog import (
    GEOMETRY_SOURCE,
    ROUTE_SPECS,
    OperationalRouteCatalog,
)
from app.integrations.tomtom import AuthError
from app.services.operational_sites import OperationalSiteService
from app.services.trip_operations import OperationsRepository


class FakeTomTom:
    def __init__(self):
        self.calls = []

    async def get_route(self, origin, destination, **options):
        self.calls.append((origin, destination, options))
        a_lat, a_lon = (float(value) for value in origin.split(","))
        b_lat, b_lon = (float(value) for value in destination.split(","))
        direct = 6_371_008.8 * 2 * math.asin(math.sqrt(
            math.sin(math.radians(b_lat-a_lat)/2)**2
            + math.cos(math.radians(a_lat))*math.cos(math.radians(b_lat))
            * math.sin(math.radians(b_lon-a_lon)/2)**2
        ))
        return {
            "routes": [{
                "legs": [{"points": [
                    {"latitude": a_lat, "longitude": a_lon},
                    {"latitude": (a_lat + b_lat) / 2, "longitude": (a_lon + b_lon) / 2},
                    {"latitude": b_lat, "longitude": b_lon},
                ]}], "summary": {
                    "lengthInMeters": direct * 1.2,
                    "travelTimeInSeconds": direct * 1.2 / 20,
                }
            }]
        }


@pytest.mark.asyncio
async def test_provisions_directional_routes_with_explicit_sites_and_is_idempotent(tmp_path):
    database = tmp_path / "operations.db"
    sites = OperationalSiteService(database)
    repository = OperationsRepository(database)
    catalog = OperationalRouteCatalog(repository, sites)
    client = FakeTomTom()

    first = await catalog.ensure_routes(client)
    second = await catalog.ensure_routes(client)

    assert len(client.calls) == len(ROUTE_SPECS)
    assert all(call[2]["travel_mode"] == "truck" for call in client.calls)
    assert all(call[2]["include_traffic"] is False for call in client.calls)
    assert all(call[2]["request_context"].startswith("catalog_provision:") for call in client.calls)
    assert all(item["geometry_created"] for item in first)
    assert not any(item["geometry_created"] for item in second)
    routes = {route["id"]: route for route in repository.routes()}
    assert len([route_id for route_id in routes if route_id in {item["id"] for item in ROUTE_SPECS}]) == len(ROUTE_SPECS)
    assert routes["contagem-guarulhos-cumbica"]["destination_site_id"] == "hub-shopee-cumbica-guarulhos"
    assert routes["contagem-guarulhos-cumbica"]["sla_minutes"] == 840
    assert routes["jaboatao-palmares"]["sla_minutes"] == 210
    assert routes["palmares-jaboatao"]["sla_minutes"] == 210
    assert routes["jaboatao-betim"]["sla_minutes"] is None
    assert routes["cariacica-cabo-santo-agostinho"]["sla_minutes"] is None

    route_ids = tuple(item["id"] for item in ROUTE_SPECS)
    placeholders = ",".join("?" for _ in route_ids)
    with repository.connect() as connection:
        rows = connection.execute(
            """SELECT route_id,source,geometry_json,mandatory_points_json,
                      provider,distance_m,duration_seconds
               FROM route_geometry_versions WHERE route_id IN (""" + placeholders + ")",
            route_ids,
        ).fetchall()
        links = connection.execute(
            """SELECT route_id,origin_site_id,destination_site_id
               FROM route_site_links WHERE route_id IN (""" + placeholders + ")",
            route_ids,
        ).fetchall()
    assert len(rows) == len(ROUTE_SPECS)
    assert all(row["source"] == "tomtom-truck" for row in rows)
    assert all(row["provider"] == "TomTom" for row in rows)
    assert all(row["distance_m"] > 0 and row["duration_seconds"] > 0 for row in rows)
    assert all(len(json.loads(row["geometry_json"])) == 3 for row in rows)
    assert all(len(json.loads(row["mandatory_points_json"])) == 2 for row in rows)
    assert len(links) == len(ROUTE_SPECS)


@pytest.mark.asyncio
async def test_failure_does_not_leave_incomplete_route(tmp_path):
    database = tmp_path / "operations.db"
    sites = OperationalSiteService(database)
    repository = OperationsRepository(database)
    with repository.connect() as connection:
        connection.execute("DELETE FROM route_configs WHERE id=?", (ROUTE_SPECS[0]["id"],))
    catalog = OperationalRouteCatalog(repository, sites)

    class Failure:
        async def get_route(self, *_args, **_kwargs):
            raise RuntimeError("routing unavailable")

    with pytest.raises(RuntimeError, match="routing unavailable"):
        await catalog.ensure_routes(Failure())
    assert repository.route(ROUTE_SPECS[0]["id"]) is None


@pytest.mark.asyncio
async def test_403_falls_back_and_blocks_further_tomtom_attempts(tmp_path):
    database = tmp_path / "operations.db"
    sites = OperationalSiteService(database)
    repository = OperationsRepository(database)
    catalog = OperationalRouteCatalog(repository, sites)

    class Forbidden:
        def __init__(self):
            self.calls = 0

        async def get_route(self, *_args, **_kwargs):
            self.calls += 1
            raise AuthError("insufficient funds", 403, "InsufficientFunds")

    client = Forbidden()
    fallback = FakeTomTom()
    result = await catalog.ensure_routes(client, fallback)
    assert client.calls == 1
    assert len(fallback.calls) == len(ROUTE_SPECS)
    assert all(item["geometry_created"] for item in result)
    with repository.connect() as connection:
        sources = [row[0] for row in connection.execute(
            "SELECT source FROM route_geometry_versions ORDER BY route_id"
        )]
    assert all(source == "openrouteservice-driving-hgv" for source in sources)


@pytest.mark.asyncio
async def test_existing_geometries_are_reused_without_queries(tmp_path):
    database = tmp_path / "operations.db"
    sites = OperationalSiteService(database)
    repository = OperationsRepository(database)
    catalog = OperationalRouteCatalog(repository, sites)
    first = FakeTomTom()
    await catalog.ensure_routes(first)
    second = FakeTomTom()
    await catalog.ensure_routes(second)
    assert len(first.calls) == len(ROUTE_SPECS)
    assert second.calls == []


@pytest.mark.asyncio
async def test_valid_geometry_from_older_version_is_reused(tmp_path):
    database = tmp_path / "operations.db"
    sites = OperationalSiteService(database)
    repository = OperationsRepository(database)
    catalog = OperationalRouteCatalog(repository, sites)
    spec = ROUTE_SPECS[0]
    route = catalog._route(spec, catalog._site(spec["origin_site_id"]), catalog._site(spec["destination_site_id"]))
    repository.upsert_route(route)
    with repository.connect() as connection:
        connection.execute(
            """INSERT INTO route_geometry_versions
               (route_id,version,source,geometry_json,mandatory_points_json,
                corridor_m,segment_tolerances_json,active,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (spec["id"], "legacy-valid-v1", "Legacy provider", json.dumps([
                {"latitude": -20, "longitude": -44},
                {"latitude": -19, "longitude": -43},
            ]), "[]", 300, "[]", 1, "2026-07-31T00:00:00+00:00"),
        )
        before = dict(connection.execute(
            "SELECT * FROM route_geometry_versions WHERE route_id=?", (spec["id"],)
        ).fetchone())
    primary = FakeTomTom()
    await catalog.ensure_routes(primary)
    assert len(primary.calls) == len(ROUTE_SPECS) - 1
    with repository.connect() as connection:
        after = dict(connection.execute(
            "SELECT * FROM route_geometry_versions WHERE route_id=?", (spec["id"],)
        ).fetchone())
    assert after == before


@pytest.mark.asyncio
async def test_concurrent_provisioning_is_deduplicated(tmp_path):
    import asyncio

    database = tmp_path / "operations.db"
    sites = OperationalSiteService(database)
    repository = OperationsRepository(database)
    catalog = OperationalRouteCatalog(repository, sites)
    client = FakeTomTom()
    await asyncio.gather(catalog.ensure_routes(client), catalog.ensure_routes(client))
    assert len(client.calls) == len(ROUTE_SPECS)
