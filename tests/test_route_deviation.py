from datetime import datetime, timedelta, timezone

from app.services.route_deviation import RouteDeviationService
from app.services.trip_operations import TripOperationsService
from app.storage.operations import OperationsRepository, utc_now


def service_at(tmp_path):
    repository = OperationsRepository(tmp_path / "operations.db")
    TripOperationsService(repository)
    repository.ensure_trip("trip:1", "ABC1D23", "1", "betim-jaboatao")
    now = utc_now()
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO route_geometry_versions(route_id,version,source,geometry_json,mandatory_points_json,corridor_m,segment_tolerances_json,active,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            ("betim-jaboatao", "test-v1", "test", '[{"latitude":-20,"longitude":-44},{"latitude":-19,"longitude":-44}]', "[]", 300, "[]", 1, now),
        )
    return RouteDeviationService(repository)


def iso(minutes):
    return (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes)).isoformat()


def test_requires_two_outside_readings_and_persists_level(tmp_path):
    service = service_at(tmp_path)
    assert service.process("trip:1", "ABC1D23", "betim-jaboatao", -19.5, -43.99, iso(0)) is None
    active = service.process("trip:1", "ABC1D23", "betim-jaboatao", -19.5, -43.99, iso(1))
    assert active and active["level"] == "INITIAL"
    active = service.process("trip:1", "ABC1D23", "betim-jaboatao", -19.5, -43.99, iso(31))
    assert active and active["level"] == "MODERATE"
    restarted = RouteDeviationService(OperationsRepository(tmp_path / "operations.db"))
    assert restarted.active_for_trip("trip:1")["id"] == active["id"]


def test_return_requires_two_inside_readings_and_history_is_kept(tmp_path):
    service = service_at(tmp_path)
    service.process("trip:1", "ABC1D23", "betim-jaboatao", -19.5, -43.99, iso(0))
    service.process("trip:1", "ABC1D23", "betim-jaboatao", -19.5, -43.99, iso(1))
    assert service.process("trip:1", "ABC1D23", "betim-jaboatao", -19.5, -44, iso(2)) is not None
    assert service.process("trip:1", "ABC1D23", "betim-jaboatao", -19.5, -44, iso(3)) is None
    assert service.history("trip:1")[0]["status"] == "RETURNED"


def test_acknowledgement_is_audited_and_related_event_is_only_suggestion(tmp_path):
    service = service_at(tmp_path)
    service.process("trip:1", "ABC1D23", "betim-jaboatao", -19.5, -43.99, iso(0))
    active = service.process("trip:1", "ABC1D23", "betim-jaboatao", -19.5, -43.99, iso(1))
    acknowledged = service.acknowledge(active["id"], "operador", "TRAFFIC", "Relato confirmado por telefone")
    assert acknowledged["reason"] == "TRAFFIC"
    detail = service.deviation(active["id"])
    assert any(event["event_type"] == "ACKNOWLEDGED" for event in detail["events"])


def test_path_breaks_incompatible_jumps(tmp_path):
    service = service_at(tmp_path)
    repository = service.repository
    for minute, latitude in [(0, -20.0), (1, -19.999), (2, -15.0), (3, -14.999)]:
        repository.add_position("trip:1", latitude, -44, 50, iso(minute), "test", None, None)
    segments = service.path("trip:1")
    assert len(segments) == 2
    assert all(len(segment) == 2 for segment in segments)


def test_isolated_jump_is_reported_but_raw_history_is_preserved(tmp_path):
    service = service_at(tmp_path)
    repository = service.repository
    points = [
        (0, -20.0, -44.0),
        (60, -19.9, -44.0),
        (61, -5.0, -35.0),
        (120, -19.8, -44.0),
        (180, -19.7, -44.0),
    ]
    for minute, latitude, longitude in points:
        repository.add_position("trip:1", latitude, longitude, 50, iso(minute), "test", None, None)
    result = service.path_diagnostic("trip:1")
    assert len(repository.raw_position_history("trip:1")) == len(points)
    assert any(item["reason"] == "isolated_geographic_jump" for item in result["outliers"])
    assert all(
        point["latitude"] != -5.0
        for segment in result["segments"]
        for point in segment
    )
