from pathlib import Path

from app.services.fleet_tracking import FleetTrackingService


def test_shared_snapshot_round_trip_is_atomic_and_marks_cache(tmp_path: Path):
    path = tmp_path / "fleet-snapshot.json"
    FleetTrackingService._write_shared_snapshot(
        path,
        {"generated_at": "2026-09-17T18:00:00+00:00", "trips": [{"plate": "ABC1D23"}]},
    )

    restored = FleetTrackingService._read_shared_snapshot(path)

    assert restored is not None
    assert restored["trips"] == [{"plate": "ABC1D23"}]
    assert restored["cache"] == {"hit": True, "shared": True}
    assert list(tmp_path.glob("*.tmp")) == []


def test_invalid_shared_snapshot_is_ignored(tmp_path: Path):
    path = tmp_path / "fleet-snapshot.json"
    path.write_text('{"trips":"invalid"}', encoding="utf-8")

    assert FleetTrackingService._read_shared_snapshot(path) is None
