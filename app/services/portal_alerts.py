from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.services.fleet_tracking import fleet_tracking_service
from app.services.public_trip import PublicTripService
from app.services.traffic_monitoring import haversine, route_projection


class PortalAlertService:
    def __init__(self, public_trips: PublicTripService) -> None:
        self.public_trips = public_trips
        self.repository = public_trips.repository
        self.operations = public_trips.operations

    def alerts(self, token: str) -> dict[str, Any]:
        link, trip = self.public_trips._resolve_active_link(token)
        settings = get_settings()
        now = datetime.now(timezone.utc)
        if not settings.driver_portal_feature_allowed(
            trip["trip_key"], settings.driver_portal_alerts_enabled
        ):
            return {"enabled": False, "alerts": [], "map_alerts": [], "integrations": {"portal_alerts": "DISABLED"}, "generated_at": now}
        if not self.repository.alert_schema_available():
            return {"enabled": False, "alerts": [], "map_alerts": [], "integrations": {"portal_alerts": "UNAVAILABLE"}, "generated_at": now}
        geometry = self._geometry(trip.get("route_id"))
        sources = self.public_trips._location_sources(trip["trip_key"])
        position = self._position(sources)
        cached = fleet_tracking_service.cached_trip(trip["trip_key"])
        integrations = self._integrations(cached)
        candidates: list[dict[str, Any]] = []
        if geometry and position:
            candidates.extend(self._traffic(trip, position, geometry, now))
            candidates.extend(self._weather(cached, position, geometry, now))
            candidates.extend(self._places(trip, position, geometry, now))
        deviation = self._deviation(trip, now)
        if deviation:
            candidates.append(deviation)
        candidates.sort(key=lambda item: (item["distance_km"] is None, item["distance_km"] or 0, item["id"]))
        cards = [item for item in candidates if self._card_relevant(item)]
        registered = self.repository.register_alerts(link["id"], cards, now.isoformat())
        presentations = {item["id"]: item["presentation"] for item in registered}
        map_alerts = [item | {"presentation": presentations.get(item["id"], "ACTIVE")} for item in candidates]
        return {"enabled": True, "alerts": registered, "map_alerts": map_alerts, "integrations": integrations, "generated_at": now}

    @staticmethod
    def _card_relevant(alert: dict[str, Any]) -> bool:
        settings = get_settings()
        distance = alert.get("distance_km")
        alert_type = str(alert.get("type") or "").upper()
        if distance is None or distance < 0 or alert_type == "CLIMA_NORMAL":
            return False
        if distance <= settings.driver_alert_card_near_km:
            return alert_type in {
                "TRANSITO_LENTO", "CHUVA_LEVE", "CHUVA_FORTE",
                "ACIDENTE_BLOQUEIO", "DESVIO_CONFIRMADO",
            }
        return (
            distance <= settings.driver_alert_card_critical_km
            and str(alert.get("severity") or "").upper() == "CRITICO"
            and alert_type in {"CHUVA_FORTE", "ACIDENTE_BLOQUEIO", "DESVIO_CONFIRMADO"}
        )

    @staticmethod
    def _position(sources: dict[str, Any]) -> dict[str, Any] | None:
        tracker, mobile = sources.get("trafegus"), sources.get("mobile")
        if tracker and tracker.get("status") == "CURRENT":
            return tracker
        if mobile and mobile.get("status") == "CURRENT":
            return mobile
        return None

    def _geometry(self, route_id: str | None) -> list[tuple[float, float]]:
        if not route_id:
            return []
        with self.operations.connect() as connection:
            row = connection.execute(
                "SELECT geometry_json FROM route_geometry_versions WHERE route_id=? "
                "AND active=1 ORDER BY id DESC LIMIT 1", (route_id,),
            ).fetchone()
        if not row:
            return []
        try:
            values = json.loads(row["geometry_json"] or "[]")
            return [(float(item["latitude"]), float(item["longitude"])) for item in values]
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            return []

    def _traffic(self, trip: dict[str, Any], position: dict[str, Any], geometry: list[tuple[float, float]], now: datetime) -> list[dict[str, Any]]:
        settings = get_settings()
        vehicle_progress, vehicle_lateral = route_projection((position["latitude"], position["longitude"]), geometry)
        if vehicle_lateral > settings.driver_alert_route_corridor_km:
            return []
        values = []
        for incident in self.repository.public_incidents(trip["trip_key"], trip.get("route_id")):
            updated = self._time(incident.get("updated_at"))
            if not updated or (now - updated).total_seconds() > settings.driver_alert_max_age_minutes * 60:
                continue
            event_progress, lateral = route_projection((incident["latitude"], incident["longitude"]), geometry)
            distance = event_progress - vehicle_progress
            if distance < -0.2 or lateral > settings.driver_alert_route_corridor_km:
                continue
            alert_type, _, reinforce, guidance = self._category(incident)
            values.append({
                "id": f"incident:{incident['id']}", "type": alert_type,
                "severity": incident["severity"], "distance_km": round(max(distance, 0), 1),
                "reference": incident.get("road_name") or incident.get("direction"),
                "updated_at": updated, "source": incident.get("source") or "Fonte não informada",
                "guidance": guidance,
                "description": incident.get("public_description") or incident.get("description") or "Informação indisponível",
                "delay_minutes": round(float(incident["delay_seconds"]) / 60, 1) if incident.get("delay_seconds") is not None else None,
                "distance_band": "REINFORCEMENT" if distance <= reinforce else "FIRST",
                "latitude": incident["latitude"], "longitude": incident["longitude"],
            })
        return values

    def _weather(self, cached: dict[str, Any] | None, position: dict[str, Any], geometry: list[tuple[float, float]], now: datetime) -> list[dict[str, Any]]:
        if not cached:
            return []
        updated = self._time(cached.get("portal_snapshot_generated_at"))
        if not updated or (now - updated).total_seconds() > get_settings().driver_alert_max_age_minutes * 60:
            return []
        vehicle_progress, _ = route_projection((position["latitude"], position["longitude"]), geometry)
        result = []
        for index, risk in enumerate(cached.get("weather_risks") or []):
            point = risk.get("position") or {}
            if point.get("latitude") is None or point.get("longitude") is None:
                continue
            progress, lateral = route_projection((point["latitude"], point["longitude"]), geometry)
            distance = progress - vehicle_progress
            if distance < -0.2 or lateral > get_settings().driver_alert_route_corridor_km:
                continue
            heavy = risk.get("severity") == "high" or risk.get("type") in {"heavy_rain", "thunderstorm"}
            first = get_settings().driver_alert_heavy_rain_first_km if heavy else get_settings().driver_alert_light_rain_first_km
            reinforce = get_settings().driver_alert_heavy_rain_reinforce_km if heavy else get_settings().driver_alert_light_rain_reinforce_km
            result.append({
                "id": f"weather:{risk.get('type')}:{index}:{point['latitude']:.3f}:{point['longitude']:.3f}",
                "type": "CHUVA_FORTE" if heavy else "CHUVA_LEVE", "severity": "CRITICO" if heavy else "ATENCAO",
                "distance_km": round(max(distance, 0), 1), "reference": None,
                "updated_at": updated, "source": risk.get("source") or "OpenWeather",
                "guidance": "Reduza a velocidade e aumente a distância de segurança.",
                "description": risk.get("description") or "Condição climática à frente",
                "delay_minutes": None, "distance_band": "REINFORCEMENT" if distance <= reinforce else "FIRST",
                "latitude": point["latitude"], "longitude": point["longitude"],
            })
        return result

    def _places(self, trip: dict[str, Any], position: dict[str, Any], geometry: list[tuple[float, float]], now: datetime) -> list[dict[str, Any]]:
        vehicle_progress, _ = route_projection((position["latitude"], position["longitude"]), geometry)
        total_progress = route_projection(geometry[-1], geometry)[0]
        distance = max(total_progress - vehicle_progress, 0)
        settings = get_settings()
        alerts = []
        if trip.get("state") in {"PROGRAMADA", "NA_ORIGEM", "EM_CARREGAMENTO"}:
            origin_distance = haversine((position["latitude"], position["longitude"]), geometry[0])
            if origin_distance <= settings.driver_alert_place_first_km:
                alerts.append({
                    "id": f"place:origin:{trip['trip_key']}", "type": "ORIGEM",
                    "severity": "INFORMATIVO", "distance_km": round(origin_distance, 1), "reference": "Origem da viagem",
                    "updated_at": now, "source": "Rota operacional Seven Cargo",
                    "guidance": "Siga as orientações de acesso e aguarde em local seguro.",
                    "description": "Aproximação da origem operacional.", "delay_minutes": None,
                    "distance_band": "REINFORCEMENT" if origin_distance <= settings.driver_alert_place_reinforce_km else "FIRST",
                    "latitude": geometry[0][0], "longitude": geometry[0][1],
                })
        if distance > settings.driver_alert_place_first_km or trip.get("state") in {"FINALIZADA_NO_SISTEMA", "RETORNO_CONCLUIDO"}:
            return alerts
        alerts.append({
            "id": f"place:destination:{trip['trip_key']}", "type": "DESTINO",
            "severity": "INFORMATIVO", "distance_km": round(distance, 1), "reference": "Destino da viagem",
            "updated_at": now, "source": "Rota operacional Seven Cargo",
            "guidance": "Prepare-se para a chegada e siga as orientações do destino.",
            "description": "Aproximação do destino operacional.", "delay_minutes": None,
            "distance_band": "REINFORCEMENT" if distance <= settings.driver_alert_place_reinforce_km else "FIRST",
            "latitude": geometry[-1][0], "longitude": geometry[-1][1],
        })
        return alerts

    def _deviation(self, trip: dict[str, Any], now: datetime) -> dict[str, Any] | None:
        with self.operations.connect() as connection:
            row = connection.execute(
                "SELECT * FROM route_deviations WHERE trip_key=? AND status='ACTIVE' ORDER BY id DESC LIMIT 1",
                (trip["trip_key"],),
            ).fetchone()
        if not row:
            return None
        return {
            "id": f"deviation:{row['id']}", "type": "DESVIO_CONFIRMADO", "severity": "CRITICO",
            "distance_km": 0, "reference": None, "updated_at": self._time(row["last_outside_at"]) or now,
            "source": "Monitoramento de rota Seven Cargo", "guidance": "Retorne à rota somente quando for seguro.",
            "description": "Veículo fora do corredor operacional confirmado.", "delay_minutes": None,
            "distance_band": "REINFORCEMENT", "latitude": row["exit_latitude"], "longitude": row["exit_longitude"],
        }

    @staticmethod
    def _category(incident: dict[str, Any]) -> tuple[str, float, float, str]:
        settings = get_settings(); category = str(incident.get("category") or "OUTRO").upper()
        if category in {"CONGESTIONAMENTO", "TRANSITO_LENTO", "TRECHO_LENTO"}:
            return "TRANSITO_LENTO", settings.driver_alert_slow_traffic_first_km, settings.driver_alert_slow_traffic_reinforce_km, "Reduza a velocidade e mantenha distância segura."
        if category == "CLIMA_NORMAL":
            return "CLIMA_NORMAL", settings.driver_alert_heavy_rain_first_km, settings.driver_alert_heavy_rain_reinforce_km, "Condição estável no trecho; mantenha a condução segura."
        if category == "RISCO_CLIMATICO":
            description = str(incident.get("description") or "").lower(); heavy = any(word in description for word in ("forte", "temporal", "tempestade"))
            return ("CHUVA_FORTE" if heavy else "CHUVA_LEVE", settings.driver_alert_heavy_rain_first_km if heavy else settings.driver_alert_light_rain_first_km, settings.driver_alert_heavy_rain_reinforce_km if heavy else settings.driver_alert_light_rain_reinforce_km, "Reduza a velocidade e considere pista molhada.")
        return "ACIDENTE_BLOQUEIO", settings.driver_alert_blockage_first_km, settings.driver_alert_blockage_reinforce_km, "Atenção à sinalização e não utilize o celular em movimento."

    @staticmethod
    def _time(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    def _integrations(self, cached: dict[str, Any] | None) -> dict[str, str]:
        with self.operations.connect() as connection:
            row = connection.execute("SELECT status FROM provider_health WHERE provider='tomtom_traffic_incidents'").fetchone()
        return {
            "traffic": row["status"] if row else "NOT_AVAILABLE",
            "weather": str((cached or {}).get("api_status", {}).get("openweather") or "NOT_AVAILABLE").upper(),
        }
