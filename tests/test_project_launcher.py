from pathlib import Path


def test_launcher_preflights_trafegus_without_calling_protected_fleet_endpoint() -> None:
    source = (Path(__file__).parents[1] / "project.ps1").read_text(encoding="utf-8")

    assert "-m app.scripts.diagnose_trafegus" in source
    assert "Test-TrafegusApi $python" in source
    assert 'Invoke-WebRequest -Uri "http://127.0.0.1:8000/fleet/active"' not in source

