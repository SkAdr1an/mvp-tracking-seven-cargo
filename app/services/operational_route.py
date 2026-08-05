from dataclasses import dataclass


@dataclass(frozen=True)
class OperationalEstimate:
    driving_minutes: float
    traffic_minutes: float
    planned_stops_minutes: float
    risk_buffer_minutes: float
    total_minutes: float


def estimate_operational_time(
    *,
    distance_km: float,
    average_speed_kmh: float,
    traffic_delay_minutes: float,
    planned_stops_minutes: float,
    risk_buffer_percent: float,
) -> OperationalEstimate:
    """Estimate elapsed trip time using explicit operational assumptions.

    The routing provider determines distance and traffic. The configured average
    speed is the fleet planning speed; it is deliberately not presented as a
    live speed prediction.
    """
    driving = distance_km / average_speed_kmh * 60.0
    traffic = max(traffic_delay_minutes, 0.0)
    stops = max(planned_stops_minutes, 0.0)
    buffer = (driving + traffic) * max(risk_buffer_percent, 0.0) / 100.0
    total = driving + traffic + stops + buffer
    return OperationalEstimate(
        driving_minutes=round(driving, 3),
        traffic_minutes=round(traffic, 3),
        planned_stops_minutes=round(stops, 3),
        risk_buffer_minutes=round(buffer, 3),
        total_minutes=round(total, 3),
    )
