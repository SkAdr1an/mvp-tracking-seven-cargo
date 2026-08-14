import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, field_validator

from app.integrations.tomtom import AuthError, RateLimitError, TomTomClient, UnavailableError, UpstreamError
from app.integrations.weather import WeatherClient
from app.integrations.driver_tracking import router as tracking_router
from app.integrations.trafegus import TrafegusClient, TrafegusError
from app.core.config import get_settings
from app.core.middleware import ApplicationSecurityMiddleware
from app.core.security import Permission, Principal, require_permission
from app.services.audit import AuditAction, AuditService
from app.services.operational_route import estimate_operational_time
from app.services.route_profiles import ROUTE_PROFILES, get_route_profile
from app.services.fleet_tracking import fleet_tracking_service
from app.api.operations import router as operations_router
from app.api.traffic import router as traffic_router
from app.api.route_monitoring import router as route_monitoring_router
from app.api.angellira import router as angellira_router
from app.api.public_trip import router as public_trip_router
from app.api.auth import router as auth_router
from app.api.operational_sites import router as operational_sites_router
from app.api.users import router as users_router
from app.api.audit import router as audit_router
from app.services.route_deviation import route_deviation_service
from app.services.traffic_monitoring import traffic_monitoring_service
from app.services.routing_provider import RoutingProviderService, RoutingProvidersFailed
from app.storage.migrations import DatabaseSchemaError, validate_database_schema


logger = logging.getLogger(__name__)
_collector_task: asyncio.Task[None] | None = None
_traffic_collector_task: asyncio.Task[None] | None = None
_route_geometry_task: asyncio.Task[None] | None = None
_backup_task: asyncio.Task[None] | None = None


async def _route_geometry_bootstrap() -> None:
    try:
        await route_deviation_service.ensure_geometry()
    except Exception as exc:
        logger.warning("Geometria operacional indisponível; será mantida a última versão persistida: %s", type(exc).__name__)


async def _fleet_collector() -> None:
    settings = get_settings()
    await asyncio.sleep(max(settings.fleet_collector_initial_delay_seconds, 0))
    while True:
        try:
            await fleet_tracking_service.get_snapshot(force=True)
        except Exception as exc:
            logger.warning("Coletor de frota indisponível: %s", type(exc).__name__)
        await asyncio.sleep(max(settings.fleet_collector_interval_seconds, 10))


async def _traffic_collector() -> None:
    settings=get_settings()
    await asyncio.sleep(max(settings.traffic_collector_initial_delay_seconds,0))
    while True:
        try:
            snapshot=await fleet_tracking_service.get_snapshot()
            await traffic_monitoring_service.collect(snapshot.get("trips") or [])
            routes=traffic_monitoring_service.repository.operations.routes(active_only=True)
            if routes:
                route=routes[0]
                await traffic_monitoring_service.validate_flow(route["origin_latitude"],route["origin_longitude"])
        except Exception as exc:
            logger.warning("Coletor de trânsito indisponível: %s",type(exc).__name__)
        await asyncio.sleep(max(settings.traffic_collector_interval_seconds,120))


async def _database_backup_collector() -> None:
    settings = get_settings()
    await asyncio.sleep(max(settings.operations_backup_initial_delay_seconds, 10))
    while True:
        try:
            from app.services.database_backup import DatabaseBackupService
            service = DatabaseBackupService(
                settings.operations_database_path,
                settings.operations_database_path.parent / "backups",
            )
            await asyncio.to_thread(service.create, label="automatic")
            await asyncio.to_thread(
                service.enforce_retention,
                daily=settings.operations_backup_daily_retention,
                weekly=settings.operations_backup_weekly_retention,
                monthly=settings.operations_backup_monthly_retention,
            )
        except Exception as exc:
            logger.exception("Backup automático indisponível: %s", type(exc).__name__)
        await asyncio.sleep(max(settings.operations_backup_interval_hours, 1) * 3600)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _collector_task, _traffic_collector_task, _route_geometry_task, _backup_task
    settings = get_settings()
    validate_database_schema(settings.operations_database_path)
    settings.validate_public_trip_runtime()
    settings.validate_security_runtime()
    if settings.development:
        logger.info(
            "Runtime storage configured database=%s",
            settings.operations_database_path,
        )
    _route_geometry_task = asyncio.create_task(_route_geometry_bootstrap())
    if settings.fleet_collector_enabled:
        _collector_task = asyncio.create_task(_fleet_collector())
    if settings.traffic_collector_enabled:
        _traffic_collector_task=asyncio.create_task(_traffic_collector())
    if settings.operations_backup_enabled:
        _backup_task = asyncio.create_task(_database_backup_collector())
    yield
    if _collector_task:
        _collector_task.cancel()
        with suppress(asyncio.CancelledError):
            await _collector_task
        _collector_task = None
    if _traffic_collector_task:
        _traffic_collector_task.cancel()
        with suppress(asyncio.CancelledError): await _traffic_collector_task
        _traffic_collector_task=None
    if _route_geometry_task:
        _route_geometry_task.cancel()
        with suppress(asyncio.CancelledError): await _route_geometry_task
        _route_geometry_task = None
    if _backup_task:
        _backup_task.cancel()
        with suppress(asyncio.CancelledError):
            await _backup_task
        _backup_task = None

_settings = get_settings()
app = FastAPI(
    title="7Seven Cargo MVP Tracking",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs" if _settings.expose_api_docs else None,
    redoc_url="/redoc" if _settings.expose_api_docs else None,
    openapi_url="/openapi.json" if _settings.expose_api_docs else None,
    debug=False,
)

app.add_middleware(ApplicationSecurityMiddleware)
_allowed_hosts = [value.strip() for value in _settings.allowed_hosts.split(",") if value.strip()]
if _settings.development:
    _allowed_hosts.append("testserver")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)
if _settings.force_https:
    app.add_middleware(HTTPSRedirectMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _settings.frontend_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir routers
app.include_router(tracking_router)
app.include_router(operations_router)
app.include_router(traffic_router)
app.include_router(route_monitoring_router)
app.include_router(angellira_router)
app.include_router(public_trip_router)
app.include_router(auth_router)
app.include_router(operational_sites_router)
app.include_router(users_router)
app.include_router(audit_router)


class RoutePreviewRequest(BaseModel):
    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    departure_at: str = Field(min_length=1)
    waypoints: list[str] = Field(default_factory=list, max_length=30)
    operational_speed_min_kmh: float = Field(default=50, ge=30, le=90)
    operational_speed_max_kmh: float = Field(default=60, ge=30, le=90)
    average_speed_kmh: float | None = Field(default=None, ge=30, le=90)
    planned_stops_minutes: float = Field(default=0, ge=0, le=1440)
    risk_buffer_percent: float = Field(default=10, ge=0, le=100)
    route_profile: str | None = None

    @field_validator("origin", "destination")
    @classmethod
    def validate_location(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("location must not be blank")
        return value

    @field_validator("waypoints")
    @classmethod
    def validate_waypoints(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("waypoints must not contain blank locations")
        return cleaned

    @field_validator("operational_speed_max_kmh")
    @classmethod
    def validate_speed_range(cls, value: float, info) -> float:
        minimum = info.data.get("operational_speed_min_kmh", 50)
        if value < minimum:
            raise ValueError("operational_speed_max_kmh must be greater than or equal to the minimum")
        return value

    @field_validator("departure_at")
    @classmethod
    def validate_departure_at(cls, value: str) -> str:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("departure_at must be a valid ISO 8601 datetime") from exc
        return value


class RoutePreviewResponse(BaseModel):
    origin: dict[str, object]
    destination: dict[str, object]
    departure_at: str
    distance_km: float
    duration_without_traffic_minutes: float
    duration_with_traffic_minutes: float
    traffic_delay_minutes: float
    live_traffic_delay_minutes: float
    traffic_length_km: float
    estimated_arrival_at: str
    status: str
    waypoints: list[dict[str, object]]
    average_speed_kmh: float
    provider_duration_minutes: float
    driving_minutes: float
    planned_stops_minutes: float
    risk_buffer_minutes: float
    operational_duration_minutes: float
    route_constraints_applied: bool
    estimate_basis: list[str]
    operational_estimate: dict[str, object]
    timeline: list[dict[str, object]]
    risk_factors: list[dict[str, object]]
    assumptions: list[str]
    route_profile: dict[str, object] | None
    operational_speed_min_kmh: float
    operational_speed_max_kmh: float
    operational_arrival_at: str
    data_freshness: str


class PlateConsultRequest(BaseModel):
    plate: str = Field(min_length=7, max_length=8)


@app.get("/health")
async def health_check() -> dict[str, str]:
    try:
        validate_database_schema(get_settings().operations_database_path)
    except (DatabaseSchemaError, OSError, sqlite3.Error) as exc:
        raise HTTPException(status_code=503, detail="Operational database unavailable") from exc
    return {"status": "ok"}


@app.get("/fleet/active", dependencies=[Depends(require_permission(Permission.INTEGRATIONS_INVOKE))])
async def active_fleet(force: bool = Query(default=False)) -> dict[str, object]:
    """Frota ativa do Trafegus com previsão degradável por viagem."""
    try:
        return await fleet_tracking_service.get_snapshot(force=force)
    except TrafegusError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/trafegus/vehicles/consult")
async def consult_vehicle(
    payload: PlateConsultRequest,
    principal: Principal = Depends(require_permission(Permission.INTEGRATIONS_INVOKE)),
) -> dict[str, object]:
    try:
        result = await TrafegusClient().consult_plate(payload.plate)
        AuditService(get_settings().operations_database_path).record_optional(
            principal, AuditAction.INTEGRATION_INVOKED, "integration",
            metadata={"integration": "TRAFEGUS", "operation": "vehicle_consult",
                      "vehicle": payload.plate, "success": True},
        )
        return _sanitize_provider_data(result)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TrafegusError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _sanitize_provider_data(value: object, key: str = "") -> object:
    """Remove segredos e mascara documentos antes de enviar dados ao navegador."""
    normalized_key = key.lower()
    if any(term in normalized_key for term in ("senha", "password", "token")):
        return None
    if any(term in normalized_key for term in ("documento", "cpf", "cnpj", "renavam", "chassi")):
        text = str(value) if value is not None else ""
        return f"••••{text[-4:]}" if text else None
    if isinstance(value, dict):
        return {item_key: _sanitize_provider_data(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_sanitize_provider_data(item, key) for item in value]
    return value


@app.post("/routes/preview", response_model=RoutePreviewResponse)
async def preview_route(
    payload: RoutePreviewRequest,
    principal: Principal = Depends(require_permission(Permission.INTEGRATIONS_INVOKE)),
) -> RoutePreviewResponse:
    profile = get_route_profile(payload.route_profile)
    if payload.route_profile and profile is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown route profile. Available: {', '.join(ROUTE_PROFILES)}",
        )
    try:
        if profile:
            profile_results = [
                {"address": {"freeformAddress": profile.origin if index == 0 else profile.destination if index == len(profile.coordinates) - 1 else f"Controle de corredor {index}"}, "position": {"lat": lat, "lon": lon}}
                for index, (lat, lon) in enumerate(profile.coordinates)
            ]
            origin_geocode = {"results": [profile_results[0]]}
            waypoint_geocodes = [{"results": [item]} for item in profile_results[1:-1]]
            destination_geocode = {"results": [profile_results[-1]]}
        else:
            locations = [payload.origin, *payload.waypoints, payload.destination]
            geocodes = [await TomTomClient().get_geocode(location) for location in locations]
            origin_geocode = geocodes[0]
            waypoint_geocodes = geocodes[1:-1]
            destination_geocode = geocodes[-1]
    except UpstreamError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "provider": exc.provider,
                "upstream_status": exc.status_code,
                "upstream_message": exc.message[:300],
            },
        ) from exc
    except AuthError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "provider": "TomTom",
                "upstream_status": 401,
                "upstream_message": str(exc)[:300],
            },
        ) from exc
    except RateLimitError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "provider": "TomTom",
                "upstream_status": 429,
                "upstream_message": str(exc)[:300],
            },
        ) from exc
    except UnavailableError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "provider": "TomTom",
                "upstream_status": 503,
                "upstream_message": str(exc)[:300],
            },
        ) from exc

    origin_result = (origin_geocode.get("results") or [{}])[0]
    destination_result = (destination_geocode.get("results") or [{}])[0]

    origin_address = (origin_result.get("address") or {}).get("freeformAddress") or payload.origin
    destination_address = (destination_result.get("address") or {}).get("freeformAddress") or payload.destination

    origin_position = origin_result.get("position") or {}
    destination_position = destination_result.get("position") or {}
    waypoint_results = [(item.get("results") or [{}])[0] for item in waypoint_geocodes]
    waypoint_positions = [item.get("position") or {} for item in waypoint_results]
    coordinate_positions = [origin_position, *waypoint_positions]
    origin_coordinates = ":".join(
        f"{position.get('lat')},{position.get('lon')}" for position in coordinate_positions
    )
    destination_coordinates = f"{destination_position.get('lat')},{destination_position.get('lon')}"

    try:
        route_payload = await RoutingProviderService().get_route(
            origin_coordinates,
            destination_coordinates,
            travel_mode="truck",
            include_traffic=True,
            departure_at=payload.departure_at,
            request_context="explicit_route_preview",
        )
    except UpstreamError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "provider": exc.provider,
                "upstream_status": exc.status_code,
                "upstream_message": exc.message[:300],
            },
        ) from exc
    except RoutingProvidersFailed as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "provider": "routing_fallback",
                "primary": exc.primary_error,
                "fallback": exc.fallback_error,
            },
        ) from exc
    except AuthError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "provider": "TomTom",
                "upstream_status": 401,
                "upstream_message": str(exc)[:300],
            },
        ) from exc
    except RateLimitError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "provider": "TomTom",
                "upstream_status": 429,
                "upstream_message": str(exc)[:300],
            },
        ) from exc
    except UnavailableError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "provider": "TomTom",
                "upstream_status": 503,
                "upstream_message": str(exc)[:300],
            },
        ) from exc

    route = (route_payload.get("routes") or [{}])[0]
    summary = route.get("summary") or {}
    length_in_meters = float(summary.get("lengthInMeters") or 0)
    travel_time_seconds = float(summary.get("travelTimeInSeconds") or 0)
    traffic_delay_seconds = float(summary.get("trafficDelayInSeconds") or 0)
    no_traffic_time_seconds = float(
        summary.get("noTrafficTravelTimeInSeconds")
        or max(travel_time_seconds - traffic_delay_seconds, 0)
    )
    traffic_length_meters = float(summary.get("trafficLengthInMeters") or 0)

    distance_km = round(length_in_meters / 1000.0, 3)
    duration_without_traffic_minutes = round(no_traffic_time_seconds / 60.0, 3)
    duration_with_traffic_minutes = round(travel_time_seconds / 60.0, 3)
    estimated_delay_seconds = max(travel_time_seconds - no_traffic_time_seconds, traffic_delay_seconds, 0)
    traffic_delay_minutes = round(estimated_delay_seconds / 60.0, 3)
    live_traffic_delay_minutes = round(traffic_delay_seconds / 60.0, 3)
    traffic_length_km = round(traffic_length_meters / 1000.0, 3)
    planning_speed = payload.average_speed_kmh or (
        payload.operational_speed_min_kmh + payload.operational_speed_max_kmh
    ) / 2
    operational = estimate_operational_time(
        distance_km=distance_km,
        average_speed_kmh=planning_speed,
        traffic_delay_minutes=traffic_delay_minutes,
        planned_stops_minutes=payload.planned_stops_minutes,
        risk_buffer_percent=payload.risk_buffer_percent,
    )

    departure_dt = datetime.fromisoformat(payload.departure_at)
    if departure_dt.tzinfo is None:
        departure_dt = departure_dt.replace(tzinfo=timezone.utc)

    if departure_dt.utcoffset() is not None:
        departure_dt = departure_dt.astimezone(timezone(timedelta(hours=-3)))
    else:
        departure_dt = departure_dt.replace(tzinfo=timezone(timedelta(hours=-3)))

    estimated_arrival_dt = departure_dt + timedelta(minutes=operational.total_minutes)
    estimated_arrival_at = estimated_arrival_dt.isoformat()

    if traffic_delay_minutes < 20:
        status = "normal"
    elif traffic_delay_minutes < 60:
        status = "attention"
    else:
        status = "critical"

    response = RoutePreviewResponse(
        origin={"address": origin_address, "position": origin_position},
        destination={"address": destination_address, "position": destination_position},
        departure_at=payload.departure_at,
        distance_km=distance_km,
        duration_without_traffic_minutes=duration_without_traffic_minutes,
        duration_with_traffic_minutes=duration_with_traffic_minutes,
        traffic_delay_minutes=traffic_delay_minutes,
        live_traffic_delay_minutes=live_traffic_delay_minutes,
        traffic_length_km=traffic_length_km,
        estimated_arrival_at=estimated_arrival_at,
        status=status,
        waypoints=[
            {
                "address": (result.get("address") or {}).get("freeformAddress") or requested,
                "position": result.get("position") or {},
                "required": True,
            }
            for requested, result in zip(
                ([f"Controle de corredor {index}" for index in range(1, len(profile.coordinates) - 1)] if profile else payload.waypoints),
                waypoint_results,
            )
        ],
        average_speed_kmh=planning_speed,
        provider_duration_minutes=duration_with_traffic_minutes,
        driving_minutes=operational.driving_minutes,
        planned_stops_minutes=operational.planned_stops_minutes,
        risk_buffer_minutes=operational.risk_buffer_minutes,
        operational_duration_minutes=operational.total_minutes,
        operational_speed_min_kmh=payload.operational_speed_min_kmh,
        operational_speed_max_kmh=payload.operational_speed_max_kmh,
        operational_arrival_at=estimated_arrival_at,
        data_freshness=datetime.now(timezone.utc).isoformat(),
        route_constraints_applied=bool(payload.waypoints or profile),
        estimate_basis=[
            "distance_and_route_from_tomtom_truck_profile",
            "fleet_average_speed_assumption",
            "tomtom_traffic_delay",
            "planned_stops",
            "operational_risk_buffer",
        ],
        operational_estimate={
            "speed_min_kmh": payload.operational_speed_min_kmh,
            "speed_max_kmh": payload.operational_speed_max_kmh,
            "planning_speed_kmh": planning_speed,
            "driving_minutes": operational.driving_minutes,
            "traffic_minutes": operational.traffic_minutes,
            "planned_stops_minutes": operational.planned_stops_minutes,
            "risk_buffer_minutes": operational.risk_buffer_minutes,
            "total_minutes": operational.total_minutes,
            "estimated_arrival_at": estimated_arrival_at,
        },
        timeline=[
            {"type": "driving", "title": "Condução na velocidade operacional", "minutes": operational.driving_minutes, "description": f"Planejamento a {planning_speed:g} km/h"},
            {"type": "traffic", "title": "Impacto de trânsito", "minutes": operational.traffic_minutes, "description": "Dados históricos e ao vivo da TomTom"},
            {"type": "planned_stops", "title": "Paradas planejadas", "minutes": operational.planned_stops_minutes},
            {"type": "risk_buffer", "title": "Margem operacional", "minutes": operational.risk_buffer_minutes, "description": f"Buffer de {payload.risk_buffer_percent:g}%"},
        ],
        risk_factors=[
            {
                "type": "traffic",
                "title": "Trânsito reportado",
                "description": "Acréscimo calculado sobre o fluxo livre",
                "severity": "medium" if operational.traffic_minutes else "low",
                "status": "active" if operational.traffic_minutes > 0 else "not_reported",
                "minutes": operational.traffic_minutes,
                "source": "TomTom",
            },
            {
                "type": "operational_uncertainty",
                "title": "Incerteza operacional",
                "description": "Margem para variações não confirmadas por fontes em tempo real",
                "severity": "medium",
                "status": "modeled",
                "minutes": operational.risk_buffer_minutes,
                "source": "planning_assumption",
            },
        ],
        assumptions=[
            f"Fleet operating-speed range: {payload.operational_speed_min_kmh:g}-{payload.operational_speed_max_kmh:g} km/h",
            "Mandatory waypoints are sent to the routing provider in the supplied order",
            "Accidents, checkpoints and road restrictions are not asserted without provider data",
        ],
        route_profile=(
            {
                "key": profile.key,
                "name": profile.name,
                "source": profile.source,
                "control_points": len(profile.coordinates),
                "is_exact_geometry": False,
                "note": "Corredor reconstruído por pontos de controle; a geometria entre pontos é recalculada pela TomTom.",
            }
            if profile else None
        ),
    )
    AuditService(get_settings().operations_database_path).record_optional(
        principal, AuditAction.INTEGRATION_INVOKED, "integration",
        metadata={"integration": "ROUTING", "operation": "route_preview",
                  "origin": payload.origin, "destination": payload.destination,
                  "success": True},
    )
    return response


@app.get("/integrations/status", dependencies=[Depends(require_permission(Permission.DASHBOARD_READ))])
async def integrations_status() -> dict[str, object]:
    settings = get_settings()
    traffic_health = traffic_monitoring_service.repository.health()
    trafegus_health = fleet_tracking_service.trafegus_health()
    return {
        "tomtom": "configured" if settings.tomtom_api_key else "not_configured",
        "tomtom_routing": "operational" if settings.tomtom_api_key else "unavailable",
        "tomtom_traffic_incidents": (traffic_health.get("tomtom_traffic_incidents") or {}).get("status", "degraded").lower(),
        "tomtom_traffic_flow": (traffic_health.get("tomtom_traffic_flow") or {}).get("status", "degraded").lower(),
        "openweather": "configured" if settings.openweather_api_key else "not_configured",
        "trafegus": trafegus_health["status"],
        "trafegus_detail": trafegus_health,
        "location": None,
        "temperature_c": None,
        "weather": None,
        "note": "O clima é consultado ao longo das rotas ativas, não em uma cidade fixa.",
    }
