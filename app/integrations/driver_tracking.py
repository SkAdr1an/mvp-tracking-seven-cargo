"""Rastreamento de motoristas em tempo real via WebSocket."""

from __future__ import annotations

from datetime import datetime, timezone
import hmac
import re
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from app.core.config import get_settings
from app.services.trip_operations import PositionUpdate, trip_operations_service

router = APIRouter(prefix="/tracking", tags=["tracking"])

# Estado local do processo. Para múltiplas instâncias, substitua por Redis.
active_drivers: dict[str, dict[str, Any]] = {}
manager_connections: set[WebSocket] = set()


class DriverLocation(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    speed_kmh: float | None = Field(default=None, ge=0)
    heading: float | None = Field(default=None, ge=0, le=360)
    battery_level: float | None = Field(default=None, ge=0, le=100)
    signal_strength: int | None = Field(default=None, ge=-150, le=0)
    timestamp: str | None = None
    plate: str | None = None
    trip_id: str | None = None
    route_id: str | None = None
    route_description: str | None = None
    current_driver: str | None = None


def _authorized(token: str | None) -> bool:
    configured_token = get_settings().tracking_api_key
    return bool(configured_token and token and hmac.compare_digest(token, configured_token))


def _require_http_token(authorization: str | None = Header(default=None)) -> None:
    token = authorization.removeprefix("Bearer ") if authorization else None
    if not _authorized(token):
        raise HTTPException(status_code=401, detail="Invalid tracking token")


async def _accept_authorized(websocket: WebSocket, token: str | None) -> bool:
    if not _authorized(token):
        await websocket.close(code=1008, reason="Invalid tracking token")
        return False
    await websocket.accept()
    return True


@router.websocket("/ws/driver/{driver_id}")
async def websocket_driver_endpoint(
    websocket: WebSocket,
    driver_id: str,
    token: str | None = Query(default=None),
) -> None:
    if not await _accept_authorized(websocket, token):
        return

    try:
        while True:
            raw_data = await websocket.receive_json()
            try:
                location = DriverLocation.model_validate(raw_data)
            except ValidationError as exc:
                await websocket.send_json({"type": "validation_error", "errors": exc.errors()})
                continue

            now = datetime.now(timezone.utc).isoformat()
            location_data = location.model_dump(exclude_none=True)
            plate = re.sub(r"[^A-Za-z0-9]", "", location.plate or driver_id).upper()
            operational = None
            if re.fullmatch(r"[A-Z]{3}[0-9][A-Z0-9][0-9]{2}", plate):
                if location.current_driver:
                    trip_operations_service.reconcile_driver(
                        plate, location.trip_id, [], [location.current_driver], source="websocket"
                    )
                recorded_at = datetime.fromisoformat(location.timestamp.replace("Z", "+00:00")) if location.timestamp else datetime.now(timezone.utc)
                operational = trip_operations_service.process_position(PositionUpdate(
                    plate=plate,
                    trip_id=location.trip_id,
                    latitude=location.latitude,
                    longitude=location.longitude,
                    speed_kmh=location.speed_kmh,
                    recorded_at=recorded_at,
                    source="websocket",
                    route_id=location.route_id,
                    route_description=location.route_description,
                ))
            active_drivers[driver_id] = {
                "location": location_data,
                "last_update": now,
                "status": "on_route",
                "operational": operational.get("trip") if operational else None,
            }
            await broadcast_driver_update(driver_id, location_data, "on_route", now)
    except WebSocketDisconnect:
        pass
    finally:
        driver = active_drivers.get(driver_id)
        if driver is not None:
            driver["status"] = "offline"
            driver["last_update"] = datetime.now(timezone.utc).isoformat()
            await broadcast_driver_update(
                driver_id,
                driver.get("location", {}),
                "offline",
                driver["last_update"],
            )


@router.websocket("/ws/manager")
async def websocket_manager_endpoint(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    if not await _accept_authorized(websocket, token):
        return

    manager_connections.add(websocket)
    try:
        await websocket.send_json({"type": "initial_drivers", "drivers": active_drivers})
        while True:
            # Aceita mensagens como ping; as atualizações são enviadas pelo servidor.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager_connections.discard(websocket)


async def broadcast_driver_update(
    driver_id: str,
    location_data: dict[str, Any],
    status: str = "on_route",
    timestamp: str | None = None,
) -> None:
    message = {
        "type": "driver_update",
        "driver_id": driver_id,
        "location": location_data,
        "status": status,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
    }
    disconnected: list[WebSocket] = []
    for manager in tuple(manager_connections):
        try:
            await manager.send_json(message)
        except Exception:
            disconnected.append(manager)
    for manager in disconnected:
        manager_connections.discard(manager)


@router.get("/drivers/active", dependencies=[])
async def get_active_drivers(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_http_token(authorization)
    online = {key: value for key, value in active_drivers.items() if value["status"] != "offline"}
    return {"total": len(online), "drivers": active_drivers}


@router.get("/driver/{driver_id}/location")
async def get_driver_location(
    driver_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_http_token(authorization)
    driver = active_drivers.get(driver_id)
    if driver is None:
        raise HTTPException(status_code=404, detail=f"Driver {driver_id} not found")
    return {"driver_id": driver_id, **driver}


@router.post("/driver/{driver_id}/status")
async def update_driver_status(
    driver_id: str,
    status: str,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    _require_http_token(authorization)
    if status not in {"online", "on_route", "paused", "offline"}:
        raise HTTPException(status_code=422, detail="Invalid driver status")
    driver = active_drivers.get(driver_id)
    if driver is None:
        raise HTTPException(status_code=404, detail=f"Driver {driver_id} not found")
    driver["status"] = status
    driver["last_update"] = datetime.now(timezone.utc).isoformat()
    await broadcast_driver_update(driver_id, driver.get("location", {}), status, driver["last_update"])
    return {"status": "updated", "driver_id": driver_id, "new_status": status}
