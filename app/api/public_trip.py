from __future__ import annotations

import hashlib
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.security import Principal, require_internal_api_key
from app.services.audit import AuditAction, AuditService
from app.schemas.public_trip import (
    DriverPortalAlertsResponse,
    MobilePositionAccepted,
    MobilePositionRequest,
    PublicLinkCreateRequest,
    PublicLinkCreatedResponse,
    PublicLinkStatusResponse,
    PublicTripResponse,
)
from app.services.public_trip import MobileLocationRejected, PublicTripService, PublicTripUnavailable
from app.services.trip_operations import trip_operations_service


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["driver-trip-portal"])
public_trip_service = PublicTripService(trip_operations_service.repository)
PUBLIC_TRIP_BUILD = "public-trip-cd-layout-20260731.2"


def get_public_trip_service() -> PublicTripService:
    return public_trip_service


def _redact_public_token(request: Request) -> None:
    request.scope["path"] = "/api/public/trips/[REDACTED]"
    request.scope["raw_path"] = b"/api/public/trips/[REDACTED]"


def _valid_public_token(token: str) -> bool:
    return 43 <= len(token) <= 128 and all(
        character.isalnum() or character in "-_" for character in token
    )


@router.post(
    "/trips/{trip_id}/public-link",
    response_model=PublicLinkCreatedResponse,
    status_code=201,
)
async def create_public_link(
    trip_id: str,
    payload: PublicLinkCreateRequest,
    actor: Principal | str = Depends(require_internal_api_key),
    service: PublicTripService = Depends(get_public_trip_service),
) -> PublicLinkCreatedResponse:
    try:
        actor_name = actor.username if isinstance(actor, Principal) else actor
        link, token = service.create_link(trip_id, payload.expires_at, actor_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Trip not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(actor, Principal):
        AuditService(service.operations.database_path).record(
            actor, AuditAction.PUBLIC_LINK_CREATED, "public_link", resource_id=link["id"],
            trip_key=trip_id, after={"status": "ACTIVE", "expires_at": link.get("expires_at")}
        )
    base = get_settings().public_trip_base_url.rstrip("/")
    return PublicLinkCreatedResponse(
        id=link["id"],
        url=f"{base}/{token}",
        created_at=link["created_at"],
        expires_at=link.get("expires_at"),
        active=True,
    )


@router.get(
    "/trips/{trip_id}/public-link",
    response_model=PublicLinkStatusResponse,
)
async def public_link_status(
    trip_id: str,
    _actor: str = Depends(require_internal_api_key),
    service: PublicTripService = Depends(get_public_trip_service),
) -> PublicLinkStatusResponse:
    try:
        link = service.link_status(trip_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Trip not found") from exc
    if not link:
        raise HTTPException(status_code=404, detail="Public link not found")
    return PublicLinkStatusResponse.model_validate(service.status_payload(link))


@router.delete(
    "/trips/{trip_id}/public-link",
    status_code=204,
)
async def revoke_public_link(
    trip_id: str,
    actor: Principal | str = Depends(require_internal_api_key),
    service: PublicTripService = Depends(get_public_trip_service),
) -> Response:
    try:
        link = service.link_status(trip_id)
        if not link or not service.status_payload(link)["active"]:
            raise HTTPException(status_code=404, detail="Public link not found")
        actor_name = actor.username if isinstance(actor, Principal) else actor
        if not service.revoke_link(trip_id, actor_name):
            raise HTTPException(status_code=404, detail="Public link not found")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Trip not found") from exc
    if isinstance(actor, Principal):
        AuditService(service.operations.database_path).record(
            actor, AuditAction.PUBLIC_LINK_REVOKED, "public_link", resource_id=link["id"],
            trip_key=trip_id, before={"status": "ACTIVE"}, after={"status": "REVOKED"}
        )
    return Response(status_code=204)


@router.get("/public/trips/{token}", response_model=PublicTripResponse)
async def get_public_trip(
    token: str,
    background_tasks: BackgroundTasks,
    request: Request,
    response: Response,
    service: PublicTripService = Depends(get_public_trip_service),
) -> PublicTripResponse | JSONResponse:
    # Starlette has already routed the request. Redacting the scope here prevents
    # Uvicorn's access logger from persisting the bearer token in the URL.
    _redact_public_token(request)
    response.headers["X-Seven-Public-Trip-Build"] = PUBLIC_TRIP_BUILD
    if not _valid_public_token(token):
        return _public_error("invalid_token")
    try:
        payload, link_id = service.resolve(token)
    except PublicTripUnavailable as exc:
        return _public_error(exc.reason)
    except Exception:
        correlation_id = str(uuid.uuid4())
        token_hint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]
        logger.exception(
            "Public trip lookup failed correlation_id=%s token_hint=%s",
            correlation_id,
            token_hint,
        )
        raise HTTPException(status_code=500, detail="Public trip temporarily unavailable")
    background_tasks.add_task(_record_access_safely, service, link_id)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return payload


@router.post("/public/trips/{token}/positions", response_model=MobilePositionAccepted, status_code=202)
async def submit_mobile_position(
    token: str,
    payload: MobilePositionRequest,
    request: Request,
    service: PublicTripService = Depends(get_public_trip_service),
) -> MobilePositionAccepted | JSONResponse:
    _redact_public_token(request)
    if not _valid_public_token(token):
        return _public_error("invalid_token")
    try:
        return MobilePositionAccepted.model_validate(service.accept_mobile_position(token, payload))
    except PublicTripUnavailable as exc:
        return _public_error(exc.reason)
    except MobileLocationRejected as exc:
        statuses = {
            "feature_disabled": (404, "Compartilhamento de localização indisponível."),
            "feature_unavailable": (503, "Compartilhamento temporariamente indisponível."),
            "accuracy_too_low": (422, "A precisão informada é insuficiente."),
            "invalid_coordinates": (422, "A localização informada é inválida."),
            "invalid_client_time": (422, "Horário da posição inválido."),
            "rate_limited": (429, "Aguarde antes de enviar uma nova posição."),
        }
        status, detail = statuses.get(exc.reason, statuses["feature_unavailable"])
        headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
        if exc.retry_after:
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=status,
            content={"detail": detail, "reason": exc.reason},
            headers=headers,
        )


@router.get("/public/trips/{token}/alerts", response_model=DriverPortalAlertsResponse)
async def get_driver_portal_alerts(
    token: str,
    request: Request,
    service: PublicTripService = Depends(get_public_trip_service),
) -> DriverPortalAlertsResponse | JSONResponse:
    _redact_public_token(request)
    if not _valid_public_token(token):
        return _public_error("invalid_token")
    try:
        from app.services.portal_alerts import PortalAlertService

        return DriverPortalAlertsResponse.model_validate(PortalAlertService(service).alerts(token))
    except PublicTripUnavailable as exc:
        return _public_error(exc.reason)


def _record_access_safely(service: PublicTripService, link_id: str) -> None:
    try:
        service.repository.record_access(link_id)
    except Exception:
        logger.exception("Public trip access audit failed link_id=%s", link_id)


def _public_error(reason: str) -> JSONResponse:
    errors = {
        "invalid_token": (404, "Link de viagem inválido."),
        "expired": (410, "Este link expirou."),
        "revoked": (410, "Este link não está mais disponível."),
        "trip_finished": (
            410,
            "Esta viagem foi finalizada e o link não está mais disponível.",
        ),
    }
    status_code, detail = errors.get(reason, errors["invalid_token"])
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "reason": reason},
        headers={
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
            "X-Seven-Public-Trip-Build": PUBLIC_TRIP_BUILD,
        },
    )
