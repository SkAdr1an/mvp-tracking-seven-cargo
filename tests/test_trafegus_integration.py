import asyncio

from app.integrations.trafegus import TrafegusClient


class FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, object]:
        return self._payload


class FakeAsyncClient:
    instances: list["FakeAsyncClient"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[tuple[str, str, dict[str, object] | None, dict[str, str]]] = []
        self.__class__.instances.append(self)

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def post(self, url, json=None, headers=None):
        self.calls.append(("POST", url, json, headers))
        return FakeResponse({"success": {"codigo": 0, "token": "safe-test-token"}, "error": []})

    async def get(self, url, params=None, headers=None):
        self.calls.append(("GET", url, params, headers))
        if "/veiculo/" in url:
            return FakeResponse(
                {
                    "veiculo": {
                        "placa": "PYL0D91",
                        "transportadores": [
                            {"documento_transportador": "00000000000000"}
                        ],
                    }
                }
            )
        if "ultimaPosicaoVeiculo" in url:
            return FakeResponse({"Posicao": []})
        if "eventos" in url:
            return FakeResponse({"eventos": []})
        return FakeResponse({"viagens": []})


def test_consult_plate_authenticates_once_and_only_reads(monkeypatch) -> None:
    FakeAsyncClient.instances.clear()
    monkeypatch.setattr(
        "app.integrations.trafegus.httpx.AsyncClient", FakeAsyncClient
    )
    client = TrafegusClient(
        username="demo_user",
        password="demo_password",
        app_id="777",
        document="00000000000000",
        base_url="https://example.test/ws_rest/public/api",
    )

    result = asyncio.run(client.consult_plate("pyl-0d91"))

    fake = FakeAsyncClient.instances[0]
    assert result["plate"] == "PYL0D91"
    assert [call[0] for call in fake.calls] == ["POST", "GET", "GET", "GET", "GET"]
    assert fake.calls[0][1].endswith("/usuariov2")
    assert fake.calls[0][3]["X-App-Trafegus"] == "777"
    assert all(call[3]["Authorization"] == "Bearer safe-test-token" for call in fake.calls[1:])
    assert fake.calls[2][2]["Documento"] == "00000000000000"
    assert fake.calls[2][2]["IdPosicao"] == 1
    assert fake.calls[3][2] == {"UltCodigo": 1, "Placa": "PYL0D91"}


def test_incidents_by_city_is_explicitly_unsupported() -> None:
    result = asyncio.run(TrafegusClient().get_incidents("Betim"))
    assert result["status"] == "unsupported"
    assert result["incidents"] == []


def test_diagnose_position_uses_official_active_trip_endpoint(monkeypatch) -> None:
    FakeAsyncClient.instances.clear()
    monkeypatch.setattr(
        "app.integrations.trafegus.httpx.AsyncClient", FakeAsyncClient
    )
    client = TrafegusClient(
        username="demo_user",
        password="demo_password",
        app_id="777",
        document="12.345.678/0001-99",
        base_url="https://example.test/ws_rest/public/api",
    )

    result = asyncio.run(client.diagnose_position("AWP7D63"))

    fake = FakeAsyncClient.instances[0]
    assert result["plate"] == "AWP7D63"
    assert [call[0] for call in fake.calls] == ["POST", "GET", "GET"]
    assert fake.calls[1][1].endswith("/ultima-posicao-viagem")
    assert fake.calls[1][2] == {"Documento": "12345678000199"}
    assert fake.calls[2][1].endswith("/naoconformidadeveiculo")
    assert fake.calls[2][2] == {"ultimoCodigo": 0, "placa": "AWP7D63"}


def test_active_trip_positions_uses_document_and_read_only_get(monkeypatch) -> None:
    FakeAsyncClient.instances.clear()
    monkeypatch.setattr("app.integrations.trafegus.httpx.AsyncClient", FakeAsyncClient)
    client = TrafegusClient(
        username="demo_user", password="demo_password", document="12.345.678/0001-99",
        base_url="https://example.test/ws_rest/public/api",
    )
    result = asyncio.run(client.active_trip_positions())
    fake = FakeAsyncClient.instances[0]
    assert result["ok"] is True
    assert [call[0] for call in fake.calls] == ["POST", "GET"]
    assert fake.calls[1][1].endswith("/ultima-posicao-viagem")
    assert fake.calls[1][2] == {"Documento": "12345678000199"}
