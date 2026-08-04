import base64
import asyncio
import logging
import re
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
TRANSIENT_STATUS_CODES = frozenset({502, 503, 504})

class TrafegusError(RuntimeError):
    """Erro seguro da integração, sem expor credenciais ou token."""

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        category: str,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.category = category
        self.http_status = http_status


class TrafegusClient:
    """Cliente somente leitura para a API REST oficial do Trafegus."""

    def __init__(
        self,
        api_key: str | None = None,
        username: str | None = None,
        password: str | None = None,
        app_id: str | None = None,
        document: str | None = None,
        base_url: str | None = None,
    ) -> None:
        settings = get_settings()
        # api_key foi mantido apenas para compatibilidade com código anterior.
        self.api_key = api_key or settings.trafegus_api_key
        self.username = username or settings.trafegus_username
        self.password = password or settings.trafegus_password
        self.app_id = str(app_id or settings.trafegus_app_id or "777")
        self.document = self._normalize_document(
            document or settings.trafegus_documento
        )
        self.base_url = (base_url or settings.trafegus_api_url).rstrip("/")
        self.timeout_seconds = max(float(settings.trafegus_timeout_seconds), 1.0)
        self.retry_attempts = max(int(settings.trafegus_retry_attempts), 0)

    def _validate_config(self) -> None:
        missing = [
            name for name, value in (
                ("TRAFEGUS_USERNAME", self.username),
                ("TRAFEGUS_PASSWORD", self.password),
                ("TRAFEGUS_DOCUMENTO", self.document),
            )
            if not value
        ]
        if missing:
            raise TrafegusError(
                f"Configuração obrigatória do Trafegus ausente: {', '.join(missing)}.",
                phase="configuration",
                category="configuration",
            )

    def _authentication_headers(self) -> dict[str, str]:
        credentials = base64.b64encode(
            f"{self.username}:{self.password}".encode("utf-8")
        ).decode("ascii")
        return {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "X-App-Trafegus": self.app_id,
        }

    def _read_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-App-Trafegus": self.app_id,
        }

    async def _authenticate(self, client: httpx.AsyncClient) -> str:
        self._validate_config()
        response = await self._request_with_retry(
            client,
            "POST",
            "/usuariov2",
            json={"usuario": self.username, "senha": self.password},
            headers=self._authentication_headers(),
            phase="authentication",
        )
        if response.status_code != 200:
            message = (
                "Credenciais rejeitadas pelo Trafegus."
                if response.status_code in {401, 403}
                else f"Falha de autenticação no Trafegus (HTTP {response.status_code})."
            )
            raise TrafegusError(
                message,
                phase="authentication",
                category="credentials" if response.status_code in {401, 403} else "http",
                http_status=response.status_code,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise TrafegusError(
                "Resposta incompatível na autenticação do Trafegus.",
                phase="authentication",
                category="invalid_json",
                http_status=response.status_code,
            ) from exc

        success = payload.get("success") or {}
        token = success.get("token") if isinstance(success, dict) else None
        if not token:
            raise TrafegusError(
                "Resposta incompatível: token de acesso ausente.",
                phase="authentication",
                category="contract",
                http_status=response.status_code,
            )
        return str(token)

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        phase: str,
        **kwargs: Any,
    ) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        for attempt in range(self.retry_attempts + 1):
            try:
                if method == "POST":
                    response = await client.post(url, **kwargs)
                else:
                    response = await client.get(url, **kwargs)
            except httpx.TimeoutException as exc:
                if attempt < self.retry_attempts:
                    await asyncio.sleep(0.25 * (2 ** attempt))
                    continue
                raise TrafegusError(
                    "Tempo de resposta do Trafegus excedido.",
                    phase=phase,
                    category="timeout",
                ) from exc
            except httpx.ConnectError as exc:
                if attempt < self.retry_attempts:
                    await asyncio.sleep(0.25 * (2 ** attempt))
                    continue
                raise TrafegusError(
                    "Não foi possível estabelecer conexão com o Trafegus.",
                    phase=phase,
                    category="connection",
                ) from exc
            except httpx.RequestError as exc:
                if attempt < self.retry_attempts:
                    await asyncio.sleep(0.25 * (2 ** attempt))
                    continue
                raise TrafegusError(
                    "Falha de rede durante a comunicação com o Trafegus.",
                    phase=phase,
                    category="network",
                ) from exc
            if response.status_code in TRANSIENT_STATUS_CODES and attempt < self.retry_attempts:
                await asyncio.sleep(0.25 * (2 ** attempt))
                continue
            return response
        raise AssertionError("unreachable")

    async def _get(
        self,
        client: httpx.AsyncClient,
        token: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self._request_with_retry(
            client,
            "GET",
            path,
            params=params,
            headers=self._read_headers(token),
            phase="query",
        )
        result: dict[str, Any] = {"http_status": response.status_code}
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if response.status_code == 200 and isinstance(payload, dict):
            result["ok"] = True
            result["data"] = payload
        else:
            result["ok"] = False
            if response.status_code in {401, 403}:
                result["error"] = "Sessão do Trafegus rejeitada ou expirada."
            elif response.status_code == 429:
                result["error"] = "Limite de requisições do Trafegus atingido."
            elif response.status_code in TRANSIENT_STATUS_CODES:
                result["error"] = "Serviço do fornecedor temporariamente indisponível."
            elif response.status_code == 200:
                result["error"] = "Resposta incompatível retornada pelo Trafegus."
            else:
                result["error"] = f"Consulta recusada pelo Trafegus (HTTP {response.status_code})."
        return result

    async def _get_with_reauth(
        self,
        client: httpx.AsyncClient,
        token: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        result = await self._get(client, token, path, params)
        if result.get("http_status") not in {401, 403}:
            return result, token
        renewed_token = await self._authenticate(client)
        return await self._get(client, renewed_token, path, params), renewed_token

    @staticmethod
    def _normalize_plate(plate: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9]", "", plate).upper()
        if not re.fullmatch(r"[A-Z]{3}[0-9][A-Z0-9][0-9]{2}", normalized):
            raise ValueError("Placa inválida. Use o formato ABC1234 ou ABC1D23.")
        return normalized

    @staticmethod
    def _normalize_document(document: str | None) -> str:
        if not document:
            return ""
        return re.sub(r"\D", "", str(document))

    def _require_company_document(self) -> str:
        if len(self.document) != 14:
            raise TrafegusError(
                "CNPJ da Seven Cargo não configurado. Preencha "
                "TRAFEGUS_DOCUMENTO no arquivo .env usando apenas números.",
                phase="configuration",
                category="configuration",
            )
        return self.document

    @staticmethod
    def _vehicle_from(payload: dict[str, Any]) -> dict[str, Any] | None:
        vehicle = payload.get("veiculo")
        if isinstance(vehicle, list):
            return vehicle[0] if vehicle and isinstance(vehicle[0], dict) else None
        return vehicle if isinstance(vehicle, dict) else None

    @staticmethod
    def _transporter_document(vehicle: dict[str, Any] | None) -> str | None:
        if not vehicle:
            return None
        transporters = vehicle.get("transportadores") or []
        if isinstance(transporters, list):
            for transporter in transporters:
                if isinstance(transporter, dict) and transporter.get("documento_transportador"):
                    return str(transporter["documento_transportador"])
        return None

    @staticmethod
    def _first_trip(payload: dict[str, Any]) -> dict[str, Any] | None:
        trips = payload.get("viagens") or payload.get("viagem")
        if isinstance(trips, list):
            return trips[0] if trips and isinstance(trips[0], dict) else None
        return trips if isinstance(trips, dict) else None

    @staticmethod
    def _trip_terminal(trip: dict[str, Any] | None) -> dict[str, Any] | None:
        if not trip:
            return None
        terminals = trip.get("terminais") or []
        if isinstance(terminals, list):
            return next((item for item in terminals if isinstance(item, dict)), None)
        return terminals if isinstance(terminals, dict) else None

    async def consult_plate(self, plate: str) -> dict[str, Any]:
        """Autentica uma vez e executa apenas GETs para a placa informada."""
        normalized_plate = self._normalize_plate(plate)
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
            token = await self._authenticate(client)

            vehicle_result, token = await self._get_with_reauth(
                client, token, f"veiculo/{normalized_plate}"
            )
            vehicle_payload = vehicle_result.get("data") or {}
            vehicle = self._vehicle_from(vehicle_payload)
            document = self._transporter_document(vehicle)

            position_params: dict[str, Any] = {
                # IdPosicao funciona como cursor. Zero é tratado como não informado
                # pelo Trafegus; 1 inicia a leitura sem adivinhar o ID do rastreador.
                "IdPosicao": 1,
                "Placa": normalized_plate,
                "Qtde": 1,
            }
            if document:
                position_params["Documento"] = document

            # Todas as chamadas abaixo são GET (somente leitura).
            position_result, token = await self._get_with_reauth(
                client,
                token,
                "ultimaPosicaoVeiculo",
                position_params,
            )
            events_result, token = await self._get_with_reauth(
                client,
                token,
                "eventos",
                {"UltCodigo": 1, "Placa": normalized_plate},
            )
            trip_result, token = await self._get_with_reauth(
                client,
                token,
                "viagem",
                {
                    "UltCodigo": 1,
                    "Placa": normalized_plate,
                    "UltimaViagem": "true",
                    "ignorarPdf": 1,
                },
            )

        return {
            "plate": normalized_plate,
            "vehicle": vehicle_result,
            "last_position": position_result,
            "events": events_result,
            "trip": trip_result,
        }

    async def active_trip_positions(self) -> dict[str, Any]:
        """Retorna as últimas posições de todas as viagens em andamento."""
        document = self._require_company_document()
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
            token = await self._authenticate(client)
            result, _ = await self._get_with_reauth(
                client,
                token,
                "ultima-posicao-viagem",
                {"Documento": document},
            )
            return result

    async def active_trips_with_details(self) -> dict[str, Any]:
        """Consulta posições ativas e a última viagem de cada placa com um token.

        Todas as operações no Trafegus são GET após a autenticação. O limite de
        concorrência protege o provedor quando há muitas viagens ativas.
        """
        document = self._require_company_document()
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
            token = await self._authenticate(client)
            positions, token = await self._get_with_reauth(
                client, token, "ultima-posicao-viagem", {"Documento": document}
            )
            if not positions.get("ok"):
                raise TrafegusError(
                    str(positions.get("error") or "Consulta de frota recusada pelo Trafegus."),
                    phase="fleet_query",
                    category="http" if positions.get("http_status") != 200 else "contract",
                    http_status=positions.get("http_status"),
                )
            plates = sorted(self._plates_from(positions.get("data")))
            semaphore = asyncio.Semaphore(4)

            async def get_details(plate: str) -> tuple[str, dict[str, dict[str, Any]]]:
                async with semaphore:
                    trip_result, vehicle_result = await asyncio.gather(
                        self._get_with_reauth(
                            client,
                            token,
                            "viagem",
                            {
                                "UltCodigo": 1,
                                "Placa": plate,
                                "UltimaViagem": "true",
                                "ignorarPdf": 1,
                            },
                        ),
                        self._get_with_reauth(client, token, f"veiculo/{plate}"),
                    )
                    trip, _ = trip_result
                    vehicle, _ = vehicle_result
                    return plate, {"trip": trip, "vehicle": vehicle}

            details = dict(await asyncio.gather(*(get_details(plate) for plate in plates)))
        return {
            "positions": positions,
            "trip_details": {plate: item["trip"] for plate, item in details.items()},
            "vehicle_details": {plate: item["vehicle"] for plate, item in details.items()},
            "_telemetry": {
                "request_count": 2 + 2 * len(plates),
                "http_status": positions.get("http_status"),
                "vehicle_count": len(plates),
                "read_only": True,
            },
        }

    @classmethod
    def _plates_from(cls, value: Any) -> set[str]:
        plates: set[str] = set()
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower().replace("_", "") in {"placa", "placaveiculo"}:
                    candidate = re.sub(r"[^A-Za-z0-9]", "", str(item)).upper()
                    if re.fullmatch(r"[A-Z]{3}[0-9][A-Z0-9][0-9]{2}", candidate):
                        plates.add(candidate)
                else:
                    plates.update(cls._plates_from(item))
        elif isinstance(value, list):
            for item in value:
                plates.update(cls._plates_from(item))
        return plates

    async def diagnose_position(self, plate: str) -> dict[str, Any]:
        """Consulta as viagens ativas e filtra uma placa, somente com GETs."""
        normalized_plate = self._normalize_plate(plate)
        document = self._require_company_document()
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
            token = await self._authenticate(client)
            active_positions, token = await self._get_with_reauth(
                client,
                token,
                "ultima-posicao-viagem",
                {"Documento": document},
            )
            nonconformities, token = await self._get_with_reauth(
                client,
                token,
                "naoconformidadeveiculo",
                {"ultimoCodigo": 0, "placa": normalized_plate},
            )

        return {
            "plate": normalized_plate,
            "active_trip_positions": active_positions,
            "nonconformities": nonconformities,
        }

    async def get_incidents(
        self,
        region: str,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> dict[str, Any]:
        """Compatibilidade: o Trafegus não oferece incidentes por cidade/região."""
        return {
            "status": "unsupported",
            "message": "O Trafegus deve ser consultado por placa, viagem ou evento.",
            "incidents": [],
        }

    async def get_incidents_by_coordinates(
        self, latitude: float, longitude: float, radius_km: float = 50
    ) -> dict[str, Any]:
        """Compatibilidade: não existe busca oficial por coordenadas neste serviço."""
        return {
            "status": "unsupported",
            "message": "O Trafegus não possui consulta oficial por raio geográfico.",
            "incidents": [],
        }
