from fastapi import APIRouter

from app.services.operational_sites import operational_site_service


router = APIRouter(prefix="/operational-sites", tags=["operational-sites"])


@router.get("")
async def list_operational_sites() -> dict[str, object]:
    return {"sites": operational_site_service.sites(), "states": operational_site_service.states()}
