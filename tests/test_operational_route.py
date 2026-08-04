from app.services.operational_route import estimate_operational_time


def test_estimate_operational_time_decomposes_elapsed_time() -> None:
    estimate = estimate_operational_time(
        distance_km=550,
        average_speed_kmh=55,
        traffic_delay_minutes=30,
        planned_stops_minutes=60,
        risk_buffer_percent=10,
    )
    assert estimate.driving_minutes == 600
    assert estimate.traffic_minutes == 30
    assert estimate.planned_stops_minutes == 60
    assert estimate.risk_buffer_minutes == 63
    assert estimate.total_minutes == 753
