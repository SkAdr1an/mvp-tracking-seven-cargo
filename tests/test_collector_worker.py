from pathlib import Path


def test_api_supports_disabling_every_background_task():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert "if settings.route_geometry_bootstrap_enabled:" in source
    assert "if settings.fleet_collector_enabled:" in source
    assert "if settings.traffic_collector_enabled:" in source
    assert "if settings.operations_backup_enabled:" in source


def test_dedicated_worker_owns_collectors_and_backup():
    source = Path("app/scripts/run_collectors.py").read_text(encoding="utf-8")
    assert "_fleet_collector()" in source
    assert "_traffic_collector()" in source
    assert "_database_backup_collector()" in source
    assert "validate_database_schema" in source
