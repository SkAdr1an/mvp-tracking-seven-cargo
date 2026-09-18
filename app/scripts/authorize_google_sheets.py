"""Authorize Seven Cargo to edit Google Sheets using the installed OAuth client.

The client secret and resulting refresh token remain under backend/secrets and
their contents are never printed.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECRETS_DIR = PROJECT_ROOT / "secrets"
TOKEN_PATH = SECRETS_DIR / "google_sheets_token.json"
SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def oauth_client() -> dict[str, object]:
    candidates = sorted(SECRETS_DIR.glob("client_secret*.json"))
    if len(candidates) != 1:
        raise RuntimeError("Mantenha exatamente um arquivo client_secret*.json em backend/secrets.")
    payload = json.loads(candidates[0].read_text(encoding="utf-8"))
    installed = payload.get("installed")
    if not isinstance(installed, dict):
        raise RuntimeError("A credencial encontrada não é do tipo OAuth para aplicativo instalado.")
    return installed


def main() -> None:
    client = oauth_client()
    state = secrets.token_urlsafe(32)
    result: dict[str, str] = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [""])[0] == state:
                result["code"] = query.get("code", [""])[0]
                result["error"] = query.get("error", [""])[0]
            body = "Autorização recebida. Você pode fechar esta aba e voltar ao Seven Cargo."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, *_args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Callback)
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}"
    params = {
        "client_id": str(client["client_id"]),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    authorization_url = f"{client['auth_uri']}?{urllib.parse.urlencode(params)}"
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    if not webbrowser.open(authorization_url):
        raise RuntimeError("Não foi possível abrir o navegador para autorização.")
    deadline = time.monotonic() + 300
    while thread.is_alive() and time.monotonic() < deadline:
        thread.join(timeout=0.25)
    server.server_close()
    if result.get("error"):
        raise RuntimeError("A autorização foi recusada no Google.")
    code = result.get("code")
    if not code:
        raise RuntimeError("A autorização não foi concluída em até cinco minutos.")
    response = httpx.post(
        str(client["token_uri"]),
        data={
            "client_id": str(client["client_id"]),
            "client_secret": str(client["client_secret"]),
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    response.raise_for_status()
    token = response.json()
    if not token.get("refresh_token"):
        raise RuntimeError("O Google não devolveu um token renovável.")
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(token), encoding="utf-8")
    print("Autorização do Google Sheets concluída e token armazenado com segurança.")


if __name__ == "__main__":
    main()
