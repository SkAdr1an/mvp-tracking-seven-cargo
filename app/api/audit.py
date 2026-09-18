from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import get_settings
from app.core.security import Permission, Principal, require_permission
from app.services.audit import AuditAction, AuditService


router = APIRouter(tags=["audit"])


def _service() -> AuditService:
    return AuditService(get_settings().operations_database_path)


@router.get("/api/audit")
async def full_audit(
    actor_user_id: str | None = None,
    actor_query: str | None = None,
    action_type: AuditAction | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    trip_key: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=250),
    cursor: str | None = None,
    _principal: Principal = Depends(require_permission(Permission.AUDIT_READ_FULL)),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must not be after date_to")
    return _service().query(
        actor_user_id=actor_user_id, actor_query=actor_query,
        action_type=action_type.value if action_type else None,
        resource_type=resource_type, resource_id=resource_id, trip_key=trip_key,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None, limit=limit, cursor=cursor,
    )


@router.get("/operations/trips/{trip_key}/audit")
async def operational_audit(
    trip_key: str,
    limit: int = Query(default=100, ge=1, le=250),
    cursor: str | None = None,
    _principal: Principal = Depends(require_permission(Permission.AUDIT_READ_OPERATIONAL)),
):
    return _service().query(trip_key=trip_key, limit=limit, cursor=cursor, operational_only=True)
