from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PublicTripLink:
    id: str
    trip_key: str
    token_hash: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    active: bool
    last_access_at: datetime | None
    access_count: int
    created_by: str | None
