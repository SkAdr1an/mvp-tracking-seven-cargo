from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.storage.operations import OperationsRepository


METHOD_VERSION = "dynamic-eta-v1"
ACTIVE_STATES = {
    "EM_VIAGEM", "NO_DESTINO", "RETORNO_SEVEN_CONFIRMADO",
}


class OperationalDiagnosticService:
    """Explica e estabiliza o ETA usando dados já coletados e persistidos."""

    def __init__(self, repository: OperationsRepository) -> None:
        self.repository = repository

    def calculate(
        self, trip: dict[str, Any], incidents: list[dict[str, Any]] | None = None,
        deviation: dict[str, Any] | None = None, now: datetime | None = None,
    ) -> dict[str, Any] | None:
        operation = trip.get("operational") or {}
        trip_key = operation.get("trip_key")
        if not trip_key:
            return None
        candidate = operation.get("return_candidate") or {}
        if (
            operation.get("state") not in ACTIVE_STATES
            or candidate.get("state") in {"AGUARDANDO_CONFIRMACAO", "RETORNO_EXTERNO"}
        ):
            return None
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        progress = trip.get("route_progress") or {}
        prediction = trip.get("prediction") or {}
        remaining_km = _number(progress.get("remaining_distance_km"))
        progress_percent = _number(progress.get("progress_percent"))
        provider_minutes = _number(prediction.get("provider_minutes"))
        if remaining_km is None and provider_minutes is None:
            return self._preserve_previous(trip_key, "Distância e tempo de percurso indisponíveis", now)

        factors: list[dict[str, Any]] = []
        confidence_reasons: list[str] = []
        risks: list[dict[str, Any]] = []
        relevant_incidents = incidents or []
        traffic_delay = max((_number(item.get("delay_seconds")) or 0) / 60 for item in relevant_incidents) if relevant_incidents else 0
        weather = trip.get("weather_risks") or []
        stopped_minutes = self._stopped_minutes(trip_key, operation)
        stale = bool(trip.get("stale"))
        outside = progress.get("route_state") == "OUTSIDE"
        return_km = _number(progress.get("return_distance_km")) or 0

        distance_minutes = (remaining_km / 55 * 60) if remaining_km is not None else None
        route_config = operation.get("route") or {}
        configured_duration = _number(route_config.get("operational_duration_minutes"))
        configured_remaining = (
            configured_duration * max(100 - progress_percent, 0) / 100
            if configured_duration is not None and progress_percent is not None
            and route_config.get("id") == "sao-bernardo-contagem-manual"
            else None
        )
        optimistic_minutes = max(
            value for value in (provider_minutes, (remaining_km / 65 * 60 if remaining_km is not None else None))
            if value is not None
        )
        base_minutes = max(
            value for value in (provider_minutes, distance_minutes, configured_remaining)
            if value is not None
        )
        # Margem proporcional e rastreável para descanso, abastecimento e imprevistos.
        operational_margin = max(20.0, min(90.0, (remaining_km or 0) / 500 * 45))
        likely_minutes = base_minutes + operational_margin
        conservative_extra = operational_margin

        factors.append({"code": "OFFICIAL_REMAINING", "label": "Quilometragem restante pela rota oficial", "value": round(remaining_km, 1) if remaining_km is not None else None})
        factors.append({"code": "ROUTE_PROGRESS", "label": "Progresso sobre a geometria oficial", "value": _number(progress.get("progress_percent"))})
        factors.append({"code": "SIGNAL_AGE", "label": "Qualidade temporal da última posição", "value": _number(trip.get("stale_minutes"))})
        factors.append({"code": "OFFICIAL_SPEED", "label": "Velocidade oficial como fator auxiliar", "value": _number(trip.get("speed_kmh"))})
        if configured_remaining is not None:
            factors.append({
                "code": "CORRIDOR_OPERATIONAL_DURATION",
                "label": "Prazo operacional configurado do corredor",
                "minutes": round(configured_duration, 1),
            })
        if provider_minutes is not None:
            factors.append({"code": "TOMTOM_TRAVEL_TIME", "label": "Tempo restante de percurso com trânsito", "minutes": round(provider_minutes, 1)})
        factors.append({"code": "OPERATIONAL_MARGIN", "label": "Margem para paradas e imprevistos", "minutes": round(operational_margin, 1)})

        if traffic_delay > 0:
            risks.append({"type": "TRAFFIC", "severity": "HIGH" if traffic_delay >= 60 else "MEDIUM", "description": "Ocorrência de trânsito relevante à frente", "delay_minutes": round(traffic_delay, 1)})
            conservative_extra += traffic_delay
        if weather:
            relevant_weather = [item for item in weather if item.get("severity") in {"ATENCAO", "CRITICO", "HIGH", "MEDIUM"}]
            if relevant_weather:
                weather_allowance = 20.0 * len(relevant_weather)
                risks.append({"type": "WEATHER", "severity": "MEDIUM", "description": "Condição climática relevante no corredor", "delay_minutes": weather_allowance})
                conservative_extra += weather_allowance
        if outside:
            return_minutes = return_km / 35 * 60
            risks.append({"type": "DEVIATION", "severity": "HIGH" if return_km >= 10 else "MEDIUM", "description": "Veículo fora da rota oficial", "return_distance_km": round(return_km, 1), "delay_minutes": round(return_minutes, 1)})
            likely_minutes += return_minutes
            conservative_extra += return_minutes
        if stopped_minutes >= 60 and not self._inside_expected_operation(operation):
            stop_allowance = min(stopped_minutes * .5, 120)
            risks.append({"type": "PROLONGED_STOP", "severity": "HIGH" if stopped_minutes >= 120 else "MEDIUM", "description": "Parada prolongada fora de local operacional esperado", "stopped_minutes": round(stopped_minutes, 1), "delay_minutes": round(stop_allowance, 1)})
            likely_minutes += stop_allowance
            conservative_extra += stop_allowance

        confidence = "HIGH"
        if stale or progress.get("confidence") in {"LOW", "UNAVAILABLE"}:
            confidence = "LOW"
            confidence_reasons.append("Última posição desatualizada ou estimativa preservada")
        elif progress.get("confidence") == "MEDIUM" or outside or prediction.get("status") != "available":
            confidence = "MEDIUM"
        if trip.get("speed_kmh") is None:
            confidence_reasons.append("Velocidade oficial indisponível; não foi inventada")
            if confidence == "HIGH":
                confidence = "MEDIUM"
        else:
            confidence_reasons.append("Velocidade oficial disponível como fator auxiliar")
        if provider_minutes is None:
            confidence_reasons.append("Tempo TomTom indisponível; usada distância oficial")
            confidence = "LOW" if stale else "MEDIUM"
        if not confidence_reasons:
            confidence_reasons.append("Posição recente, rota coerente e tempo de percurso disponível")
        confidence_reasons.append("Histórico da rota não aplicado sem amostra operacional suficiente")

        eta = now + timedelta(minutes=likely_minutes)
        optimistic_eta = now + timedelta(minutes=optimistic_minutes)
        conservative_eta = now + timedelta(minutes=likely_minutes + conservative_extra)
        client_eta = _datetime(trip.get("sla_at") or prediction.get("sla_at"))
        delta = (eta - client_eta).total_seconds() / 60 if client_eta else None
        classification = prediction.get("classification") or _classification(delta, likely_minutes)
        trend = _trend(delta)
        status_explanation = self._explanation(classification, delta, outside, stopped_minutes, traffic_delay)
        recommendations = self._recommendations(classification, outside, stopped_minutes, delta)
        calculated = {
            "trip_key": trip_key,
            "eta_at": eta.isoformat(),
            "window_start_at": optimistic_eta.isoformat(),
            "window_end_at": conservative_eta.isoformat(),
            "client_eta_at": client_eta.isoformat() if client_eta else None,
            "commitment_delta_minutes": round(delta, 1) if delta is not None else None,
            "trend": trend,
            "confidence": confidence,
            "classification": classification,
            "remaining_minutes": round(likely_minutes, 1),
            "stopped_minutes": round(stopped_minutes, 1),
            "method_version": METHOD_VERSION,
            "factors": factors,
            "confidence_reasons": confidence_reasons,
            "risks": risks,
            "recommendations": recommendations,
            "scenarios": {
                "optimistic": {"eta_at": optimistic_eta.isoformat(), "explanation": "Sem novas paradas e sem agravamento das condições atuais."},
                "likely": {"eta_at": eta.isoformat(), "explanation": "Condições atuais, tempo de percurso e margem operacional."},
                "conservative": {"eta_at": conservative_eta.isoformat(), "explanation": "Riscos existentes, margem adicional e eventual retorno à rota."},
            },
            "status_explanation": status_explanation,
            "calculated_at": now.isoformat(),
        }
        return self._stabilize_and_save(calculated, stale)

    def _stabilize_and_save(self, value: dict[str, Any], stale: bool) -> dict[str, Any]:
        previous = self.repository.diagnostic(value["trip_key"])
        reliable = not stale and value["confidence"] in {"HIGH", "MEDIUM"}
        previous_reliable = (previous or {}).get("last_reliable")
        if previous and (stale or value["confidence"] == "LOW"):
            reliable_value = previous_reliable or previous
            for field in ("eta_at", "window_start_at", "window_end_at", "remaining_minutes", "scenarios"):
                value[field] = reliable_value.get(field, value[field])
            value["confidence_reasons"].append("Último ETA confiável preservado")
        elif previous and previous.get("eta_at"):
            delta = abs((_datetime(value["eta_at"]) - _datetime(previous["eta_at"])).total_seconds() / 60)
            same_risks = [item.get("type") for item in value["risks"]] == [item.get("type") for item in previous.get("risks") or []]
            if delta < 10 and same_risks and value["classification"] == previous.get("classification"):
                value["eta_at"] = previous["eta_at"]
                value["confidence_reasons"].append("Variação pequena absorvida pela estabilização")
        value["last_reliable"] = {key: val for key, val in value.items() if key != "last_reliable"} if reliable else previous_reliable
        return self.repository.save_diagnostic(value)

    def _preserve_previous(self, trip_key: str, reason: str, now: datetime) -> dict[str, Any] | None:
        previous = self.repository.diagnostic(trip_key)
        if not previous:
            return None
        previous["confidence"] = "LOW"
        previous["confidence_reasons"] = [reason, "Último diagnóstico válido preservado"]
        previous["calculated_at"] = now.isoformat()
        return self.repository.save_diagnostic(previous)

    def _stopped_minutes(self, trip_key: str, operation: dict[str, Any]) -> float:
        if operation.get("last_speed_kmh") is None or float(operation["last_speed_kmh"]) > 3:
            return 0
        history = self.repository.position_history(trip_key, 120)
        if not history:
            return 0
        latest = _datetime(history[-1]["recorded_at"])
        earliest = latest
        for point in reversed(history):
            speed = point.get("speed_kmh")
            if speed is None or float(speed) > 3:
                break
            earliest = _datetime(point["recorded_at"])
        return max((latest - earliest).total_seconds() / 60, 0)

    @staticmethod
    def _inside_expected_operation(operation: dict[str, Any]) -> bool:
        fences = operation.get("geofences") or {}
        return fences.get("origin") == "inside" or fences.get("destination") == "inside"

    @staticmethod
    def _explanation(classification: str, delta: float | None, outside: bool, stopped: float, traffic: float) -> str:
        label = {"NORMAL": "Normal", "ATENCAO": "Atenção", "CRITICA": "Crítica"}.get(classification, classification)
        reasons = []
        if delta is not None:
            reasons.append(f"previsão {'ultrapassa' if delta > 0 else 'antecede'} o compromisso em {abs(delta):.0f} minutos")
        if outside:
            reasons.append("desvio confirmado da rota oficial")
        if stopped >= 60:
            reasons.append(f"parada de {stopped:.0f} minutos")
        if traffic > 0:
            reasons.append("trânsito relevante à frente")
        return f"Status: {label}. " + ("; ".join(reasons) + "." if reasons else "Condições operacionais sem risco relevante identificado.")

    @staticmethod
    def _recommendations(classification: str, outside: bool, stopped: float, delta: float | None) -> list[str]:
        result = []
        if outside:
            result.append("Validar retorno à rota oficial")
        if stopped >= 60:
            result.append("Confirmar motivo da parada com o motorista")
        if classification == "CRITICA" or (delta or 0) >= 60:
            result.append("Avisar o cliente sobre provável atraso")
        elif classification == "ATENCAO":
            result.append("Acompanhar novamente em 30 minutos")
        if not result:
            result.append("Sem ação necessária no momento")
        return result


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _classification(delta: float | None, remaining: float) -> str:
    if delta is None:
        return "ATENCAO" if remaining > 24 * 60 else "NORMAL"
    return "CRITICA" if delta >= 120 else "ATENCAO" if delta >= 30 else "NORMAL"


def _trend(delta: float | None) -> str:
    if delta is None:
        return "SEM_COMPROMISSO"
    if delta <= -60:
        return "ADIANTADO"
    if delta <= 15:
        return "DENTRO_DO_PRAZO"
    if delta < 60:
        return "RISCO_DE_ATRASO"
    return "PROVAVEL_ATRASO"
