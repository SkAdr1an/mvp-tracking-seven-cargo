import json

from app.services.route_progress import RouteProgressService
from app.services.trip_operations import TripOperationsService
from app.storage.operations import OperationsRepository, utc_now


def service_at(tmp_path):
    repository=OperationsRepository(tmp_path/"operations.db");TripOperationsService(repository)
    route = repository.route("betim-jaboatao")
    repository.upsert_route({
        **route,
        "origin_latitude": 0.0,
        "origin_longitude": 0.0,
        "destination_latitude": 0.0,
        "destination_longitude": 3.0,
        "origin_radius_m": 1000,
        "destination_radius_m": 1000,
    })
    repository.ensure_trip("trip:progress","ABC1D23","progress","betim-jaboatao")
    geometry=[{"latitude":0.0,"longitude":value} for value in (0.0,1.0,2.0,3.0)]
    with repository.connect() as connection:
        connection.execute("INSERT INTO route_geometry_versions(route_id,version,source,geometry_json,mandatory_points_json,corridor_m,segment_tolerances_json,active,created_at) VALUES(?,?,?,?,?,?,?,?,?)",("betim-jaboatao","progress-v1","test",json.dumps(geometry),"[]",300,"[]",1,utc_now()))
    return RouteProgressService(repository)


def test_speed_zero_and_mid_route_progress(tmp_path):
    service=service_at(tmp_path)
    value=service.calculate("trip:progress","betim-jaboatao",0,1.5,0,"2026-07-22T10:00:00+00:00",False)
    assert value["speed_kmh"]==0 and value["speed_state"]=="CURRENT"
    assert 49<value["progress_percent"]<51
    assert abs(value["advanced_distance_km"]-value["remaining_distance_km"])<1


def test_start_destination_and_off_route_return_are_separate(tmp_path):
    service=service_at(tmp_path)
    start=service.calculate("trip:progress","betim-jaboatao",0,0,None,None,False)
    assert start["progress_percent"]==0 and start["speed_state"]=="UNAVAILABLE"
    outside=service.calculate("trip:progress","betim-jaboatao",0.1,1.5,50,"2026-07-22T10:01:00+00:00",False)
    assert outside["route_state"]=="OUTSIDE" and outside["return_distance_km"]>10
    assert outside["remaining_distance_km"]>0
    destination=service.calculate("trip:progress","betim-jaboatao",0,3,20,"2026-07-22T10:02:00+00:00",False)
    assert destination["progress_percent"]==100 and destination["remaining_distance_km"]==0


def test_small_gps_oscillation_does_not_reduce_and_restart_preserves(tmp_path):
    service=service_at(tmp_path)
    first=service.calculate("trip:progress","betim-jaboatao",0,2,40,"2026-07-22T10:00:00+00:00",False)
    jitter=service.calculate("trip:progress","betim-jaboatao",0,1.99,39,"2026-07-22T10:01:00+00:00",False)
    assert jitter["advanced_distance_km"]==first["advanced_distance_km"]
    restarted=RouteProgressService(OperationsRepository(tmp_path/"operations.db"))
    stale=restarted.calculate("trip:progress","betim-jaboatao",0,2.1,80,"2026-07-22T08:00:00+00:00",True)
    assert stale["confidence"]=="LOW" and stale["speed_kmh"] is None and stale["speed_state"]=="STALE"
    assert stale["advanced_distance_km"]==first["advanced_distance_km"]


def test_projection_near_route_end_cannot_report_complete_while_destination_is_far(tmp_path):
    service = service_at(tmp_path)
    # A late segment passes close to the vehicle, but the configured destination
    # remains hundreds of kilometres away.
    with service.repository.connect() as connection:
        connection.execute("DELETE FROM route_geometry_versions WHERE route_id=?", ("betim-jaboatao",))
        geometry = [
            {"latitude": 0.0, "longitude": 0.0},
            {"latitude": 0.0, "longitude": 3.0},
            {"latitude": 1.0, "longitude": 1.0},
        ]
        connection.execute(
            """INSERT INTO route_geometry_versions(
                   route_id,version,source,geometry_json,mandatory_points_json,corridor_m,
                   segment_tolerances_json,active,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            ("betim-jaboatao", "crossing-v2", "test", json.dumps(geometry), "[]", 300, "[]", 1, utc_now()),
        )
    service._cache.clear()
    value = service.calculate(
        "trip:progress", "betim-jaboatao", 1.0, 1.0, 40,
        "2026-07-22T10:00:00+00:00", False,
    )
    assert value["progress_percent"] < 100
    assert value["remaining_distance_km"] > 0

