from __future__ import annotations

from collections import Counter
from typing import Any, Iterable


def summarize_homologation(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Summarize synthetic/pilot exports without reading or writing operations.db."""
    values = list(events)
    positions = [item for item in values if item.get("kind") == "position"]
    accepted = [item for item in positions if item.get("accepted") is True]
    ages = [float(item["age_seconds"]) for item in accepted if item.get("age_seconds") is not None]
    tracker_checks = [item for item in values if item.get("kind") == "trafegus_check"]
    alerts = [item for item in values if item.get("kind") == "alert"]
    failures = Counter(
        f"{item.get('platform', 'desconhecido')}/{item.get('browser', 'desconhecido')}"
        for item in values
        if item.get("kind") == "browser_failure"
    )
    return {
        "positions_received": len(positions),
        "positions_accepted_percent": round(100 * len(accepted) / len(positions), 1) if positions else 0.0,
        "mobile_position_average_age_seconds": round(sum(ages) / len(ages), 1) if ages else None,
        "trafegus_availability_percent": round(
            100 * sum(item.get("available") is True for item in tracker_checks) / len(tracker_checks), 1
        ) if tracker_checks else None,
        "mobile_complementary_seconds": sum(
            int(item.get("duration_seconds") or 0)
            for item in values if item.get("kind") == "mobile_complementary"
        ),
        "alerts_presented": sum(item.get("presented") is True for item in alerts),
        "repeated_alerts_blocked": sum(item.get("blocked_reason") == "duplicate" for item in alerts),
        "alerts_discarded_behind": sum(item.get("blocked_reason") == "behind" for item in alerts),
        "alerts_discarded_stale": sum(item.get("blocked_reason") == "stale" for item in alerts),
        "source_divergences": sum(item.get("kind") == "source_divergence" for item in values),
        "failures_by_platform_browser": dict(sorted(failures.items())),
    }
