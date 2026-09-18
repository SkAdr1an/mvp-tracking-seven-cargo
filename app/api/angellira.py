from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, Query
from app.core.security import Permission, require_permission

from app.core.config import get_settings
from app.services.angellira import AngelLiraService
from app.storage.angellira import AngelLiraRepository


router = APIRouter(prefix="/angellira", tags=["reference-data"])


@lru_cache
def get_angellira_service() -> AngelLiraService:
    return AngelLiraService(AngelLiraRepository(get_settings().operations_database_path))


@router.get("/status", dependencies=[Depends(require_permission(Permission.TRIPS_READ))])
async def status(service: AngelLiraService = Depends(get_angellira_service)) -> dict[str, Any]:
    return service.status()


@router.get("/stations", dependencies=[Depends(require_permission(Permission.TRIPS_READ))])
async def stations(
    status: str = Query(default="validated", pattern="^(validated|all)$"),
    service: AngelLiraService = Depends(get_angellira_service),
) -> dict[str, Any]:
    values = service.repository.stations(map_only=status == "validated")
    return {
        "source": "AngelLira",
        "dataset": service.repository.latest_dataset(),
        "stations": values,
    }


@router.get("/risk-areas", dependencies=[Depends(require_permission(Permission.TRIPS_READ))])
async def risk_areas(
    status: str = Query(default="validated", pattern="^(validated|all)$"),
    service: AngelLiraService = Depends(get_angellira_service),
) -> dict[str, Any]:
    values = service.repository.risk_areas(map_only=status == "validated")
    return {
        "source": "AngelLira",
        "dataset": service.repository.latest_dataset(),
        "message": "Área estimada pela AngelLira - não representa ocorrência confirmada.",
        "risk_areas": values,
    }


@router.get("/admin", dependencies=[Depends(require_permission(Permission.SETTINGS_READ))])
async def admin(
    service: AngelLiraService = Depends(get_angellira_service),
) -> dict[str, Any]:
    return {
        "status": service.status(),
        "review_queue": service.repository.review_queue(),
    }
