from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PublicLinkCreateRequest(BaseModel):
    expires_at: datetime | None = None


class PublicLinkCreatedResponse(BaseModel):
    id: str
    url: str
    created_at: datetime
    expires_at: datetime | None
    active: bool


class PublicLinkStatusResponse(BaseModel):
    id: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    active: bool
    last_access_at: datetime | None
    access_count: int = Field(ge=0)
    created_by: str | None


class PublicCoordinate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class PublicPlace(BaseModel):
    name: str
    city: str | None = None
    state: str | None = None
    coordinate: PublicCoordinate | None = None


class PublicPosition(PublicCoordinate):
    recorded_at: datetime
    speed_kmh: float | None = Field(default=None, ge=0)
    source: str = "Rastreador do veículo"


class PublicSourcePosition(PublicPosition):
    accuracy_m: float | None = Field(default=None, ge=0)
    age_seconds: int = Field(ge=0)
    status: str


class PublicLocationSources(BaseModel):
    trafegus: PublicSourcePosition | None = None
    mobile: PublicSourcePosition | None = None
    difference_km: float | None = Field(default=None, ge=0)
    situation: str


class MobilePositionRequest(PublicCoordinate):
    accuracy_m: float = Field(ge=0, le=10000)
    recorded_at: datetime | None = None


class MobilePositionAccepted(BaseModel):
    accepted: bool = True
    received_at: datetime
    source: str = "LINK_MOTORISTA"


class DriverPortalAlert(BaseModel):
    id: str
    type: str
    severity: str
    distance_km: float | None = Field(default=None, ge=0)
    reference: str | None = None
    updated_at: datetime
    source: str
    guidance: str
    description: str
    delay_minutes: float | None = Field(default=None, ge=0)
    distance_band: str
    presentation: str
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class DriverPortalAlertsResponse(BaseModel):
    enabled: bool
    alerts: list[DriverPortalAlert] = Field(default_factory=list)
    map_alerts: list[DriverPortalAlert] = Field(default_factory=list)
    integrations: dict[str, str] = Field(default_factory=dict)
    generated_at: datetime


class PublicVehicle(BaseModel):
    plate: str | None = None
    trailer_plate: str | None = None


class PublicImportantPoint(BaseModel):
    name: str
    coordinate: PublicCoordinate


class PublicNotice(BaseModel):
    title: str
    description: str
    severity: str
    updated_at: datetime


class PublicContact(BaseModel):
    name: str
    phone: str | None = None


class PublicRoute(BaseModel):
    name: str | None = None
    origin: PublicPlace
    destination: PublicPlace
    geometry: list[PublicCoordinate] = Field(default_factory=list)
    important_points: list[PublicImportantPoint] = Field(default_factory=list)


class PublicTripResponse(BaseModel):
    driver_name: str
    trip_reference: str | None = None
    route: PublicRoute
    public_status: str
    loaded_at: datetime | None = None
    estimated_arrival_at: datetime | None = None
    estimated_arrival_updated_at: datetime | None = None
    last_updated_at: datetime
    stale: bool
    finished: bool = False
    vehicle: PublicVehicle
    latest_position: PublicPosition | None = None
    location_sources: PublicLocationSources
    mobile_location_enabled: bool = False
    portal_alerts_enabled: bool = False
    operational_instructions: list[str] = Field(default_factory=list)
    central_contact: PublicContact
    notices: list[PublicNotice] = Field(default_factory=list)
