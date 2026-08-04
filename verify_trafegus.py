import asyncio
import app.integrations.trafegus as trafegus_module
from app.integrations.trafegus import TrafegusClient


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = ''

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        return FakeResponse({'status': 'ok', 'incidents': []})


trafegus_module.httpx.AsyncClient = lambda *args, **kwargs: FakeAsyncClient()

client = TrafegusClient(api_key=None, username='demo_user', password='demo_password', app_id='demo_app', base_url='https://example.test')
result = asyncio.run(client.get_incidents('PE'))
print(result)
