from __future__ import annotations

import json
import re
from urllib.parse import quote
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings


class GoogleSheetsError(RuntimeError):
    pass


def _normalized(value: object) -> str:
    text = str(value or "").strip().upper()
    return "".join(char for char in text if char.isalnum())


class GoogleSheetsWriteback:
    API = "https://sheets.googleapis.com/v4/spreadsheets"
    HEADER_ALIASES = {
        "driver": {"MOTORISTA", "DRIVER", "CONDUTOR"},
        "truck": {"CAVALO", "PLACACAVALO", "PLACAVEICULO"},
        "trailer": {"CARRETA", "PLACACARRETA", "IMPLEMENTO"},
        "phone": {"TELEFONE", "CELULAR", "FONE"},
        "cpf": {"CPF", "CPFMOTORISTA"},
        "email": {"EMAIL", "EMAILMOTORISTA"},
    }
    LT_ALIASES = {"LHTRIP", "LT", "IDENTIFICADORLT"}

    def __init__(self) -> None:
        settings = get_settings()
        self.spreadsheet_id = settings.weekly_writeback_spreadsheet_id.strip()
        self.default_sheet = settings.weekly_writeback_sheet_name.strip()
        self.token_path = settings.google_sheets_token_path
        self.client_directory = settings.google_oauth_client_path

    def _oauth_client(self) -> dict[str, Any]:
        candidates = sorted(self.client_directory.glob("client_secret*.json")) if self.client_directory.is_dir() else [self.client_directory]
        if len(candidates) != 1:
            raise GoogleSheetsError("Credencial OAuth do Google não configurada de forma única.")
        payload = json.loads(candidates[0].read_text(encoding="utf-8"))
        client = payload.get("installed")
        if not isinstance(client, dict):
            raise GoogleSheetsError("Credencial OAuth do Google incompatível.")
        return client

    def _access_token(self) -> str:
        if not self.token_path.exists():
            raise GoogleSheetsError("Autorização do Google Sheets ainda não foi concluída.")
        saved = json.loads(self.token_path.read_text(encoding="utf-8"))
        refresh_token = saved.get("refresh_token")
        if not refresh_token:
            raise GoogleSheetsError("Token renovável do Google Sheets ausente.")
        client = self._oauth_client()
        response = httpx.post(str(client["token_uri"]), data={
            "client_id": client["client_id"], "client_secret": client["client_secret"],
            "refresh_token": refresh_token, "grant_type": "refresh_token",
        }, timeout=20)
        if response.status_code != 200:
            raise GoogleSheetsError("Não foi possível renovar a autorização do Google Sheets.")
        token = response.json().get("access_token")
        if not token:
            raise GoogleSheetsError("Resposta de autorização do Google Sheets incompatível.")
        return str(token)

    def read_row_colors(self, *, sheet_name: str) -> dict[int, str]:
        """Return meaningful row background colors keyed by one-based row number."""
        if not self.spreadsheet_id:
            raise GoogleSheetsError("Planilha da programação não configurada.")
        token = self._access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        metadata = httpx.get(
            f"{self.API}/{self.spreadsheet_id}", headers=headers,
            params={"fields": "sheets.properties(title)"}, timeout=30,
        )
        if metadata.status_code != 200:
            raise GoogleSheetsError("Não foi possível identificar a aba semanal no Google Sheets.")
        wanted = _normalized(sheet_name)
        titles = [str(item.get("properties", {}).get("title", "")) for item in metadata.json().get("sheets", [])]
        actual = next((title for title in titles if _normalized(title) == wanted), None)
        if not actual:
            raise GoogleSheetsError("A aba semanal não foi encontrada no Google Sheets.")
        quoted = actual.replace("'", "''")
        response = httpx.get(
            f"{self.API}/{self.spreadsheet_id}", headers=headers,
            params={
                "ranges": f"'{quoted}'!A1:N1006", "includeGridData": "true",
                "fields": "sheets(data(startRow,rowData(values(effectiveFormat(backgroundColor,backgroundColorStyle)))))",
            }, timeout=30,
        )
        if response.status_code != 200:
            raise GoogleSheetsError("Não foi possível ler as cores da programação.")
        colors: dict[int, str] = {}
        sheets = response.json().get("sheets", [])
        for grid in (sheets[0].get("data", []) if sheets else []):
            start = int(grid.get("startRow", 0))
            for offset, row in enumerate(grid.get("rowData", [])):
                detected: set[str] = set()
                for cell in row.get("values", []):
                    effective = cell.get("effectiveFormat", {})
                    color = effective.get("backgroundColorStyle", {}).get("rgbColor") or effective.get("backgroundColor") or {}
                    red, green, blue = (float(color.get(key, 0)) for key in ("red", "green", "blue"))
                    if red >= .75 and green <= .35 and blue <= .35:
                        detected.add("RED")
                    elif green >= .65 and red <= .35 and blue <= .35:
                        detected.add("GREEN")
                if "RED" in detected:
                    colors[start + offset + 1] = "RED"
                elif "GREEN" in detected:
                    colors[start + offset + 1] = "GREEN"
        return colors

    def read_latest_weekly_source(self) -> tuple[str, list[list[object]], dict[int, str]]:
        """Read the newest LHW tab, including displayed values and operational row colors."""
        if not self.spreadsheet_id:
            raise GoogleSheetsError("Planilha da programação não configurada.")
        token = self._access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        metadata = httpx.get(
            f"{self.API}/{self.spreadsheet_id}", headers=headers,
            params={"fields": "sheets.properties(title)"}, timeout=30,
        )
        if metadata.status_code != 200:
            raise GoogleSheetsError("Não foi possível identificar a aba semanal no Google Sheets.")
        candidates: list[tuple[int, str]] = []
        for item in metadata.json().get("sheets", []):
            title = str(item.get("properties", {}).get("title", ""))
            match = re.fullmatch(r"\s*LHW[\s_-]*(\d{1,3})\s*", title, re.IGNORECASE)
            if match:
                candidates.append((int(match.group(1)), title))
        if not candidates:
            raise GoogleSheetsError("Nenhuma aba semanal LHW foi encontrada no Google Sheets.")
        number, actual = max(candidates, key=lambda item: item[0])
        canonical = f"LHW{number}"
        quoted_title = actual.replace("'", "''")
        range_name = f"'{quoted_title}'!A1:BP1006"
        values_response = httpx.get(
            f"{self.API}/{self.spreadsheet_id}/values/{quote(range_name, safe='')}",
            headers=headers, params={"majorDimension": "ROWS", "valueRenderOption": "FORMATTED_VALUE"}, timeout=30,
        )
        if values_response.status_code != 200:
            raise GoogleSheetsError("Não foi possível ler os dados da programação.")
        grid_response = httpx.get(
            f"{self.API}/{self.spreadsheet_id}", headers=headers,
            params={
                "ranges": f"'{quoted_title}'!A1:N1006", "includeGridData": "true",
                "fields": "sheets(data(startRow,rowData(values(effectiveFormat(backgroundColor,backgroundColorStyle)))))",
            }, timeout=30,
        )
        if grid_response.status_code != 200:
            raise GoogleSheetsError("Não foi possível ler as cores da programação.")
        colors: dict[int, str] = {}
        sheets = grid_response.json().get("sheets", [])
        for grid in (sheets[0].get("data", []) if sheets else []):
            start = int(grid.get("startRow", 0))
            for offset, row in enumerate(grid.get("rowData", [])):
                detected: set[str] = set()
                for cell in row.get("values", []):
                    effective = cell.get("effectiveFormat", {})
                    color = effective.get("backgroundColorStyle", {}).get("rgbColor") or effective.get("backgroundColor") or {}
                    red, green, blue = (float(color.get(key, 0)) for key in ("red", "green", "blue"))
                    if red >= .75 and green <= .35 and blue <= .35:
                        detected.add("RED")
                    elif green >= .65 and red <= .35 and blue <= .35:
                        detected.add("GREEN")
                if "RED" in detected:
                    colors[start + offset + 1] = "RED"
                elif "GREEN" in detected:
                    colors[start + offset + 1] = "GREEN"
        return canonical, values_response.json().get("values", []), colors

    @staticmethod
    def _column_name(index: int) -> str:
        result = ""
        value = index + 1
        while value:
            value, remainder = divmod(value - 1, 26)
            result = chr(65 + remainder) + result
        return result

    def update_lt(self, *, lt: str, sheet_name: str | None = None, values: dict[str, str | None]) -> dict[str, Any]:
        sheet = (sheet_name or self.default_sheet).strip()
        if not self.spreadsheet_id or not re.fullmatch(r"LHW\d{1,3}", sheet, re.IGNORECASE):
            raise GoogleSheetsError("Destino de escrita da programação inválido.")
        token = self._access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        quoted = sheet.replace("'", "''")
        range_name = f"'{quoted}'!A1:BP1006"
        response = httpx.get(f"{self.API}/{self.spreadsheet_id}/values/{httpx.URL(range_name).raw_path.decode()}", headers=headers, params={"majorDimension": "ROWS"}, timeout=30)
        if response.status_code != 200:
            raise GoogleSheetsError("Não foi possível ler a planilha de destino.")
        rows = response.json().get("values") or []
        if not rows:
            raise GoogleSheetsError("A planilha de destino está vazia.")
        header = [_normalized(value) for value in rows[0]]
        lt_column = next((index for index, name in enumerate(header) if name in self.LT_ALIASES), None)
        if lt_column is None:
            raise GoogleSheetsError("Cabeçalho da LT não encontrado na planilha de destino.")
        wanted = _normalized(lt)
        matches = [index for index, row in enumerate(rows[1:], start=2) if lt_column < len(row) and _normalized(row[lt_column]) == wanted]
        if len(matches) != 1:
            raise GoogleSheetsError("A LT deve existir exatamente uma vez na planilha de destino.")
        updates: list[dict[str, object]] = []
        for field, value in values.items():
            if value is None or field not in self.HEADER_ALIASES:
                continue
            column = next((index for index, name in enumerate(header) if name in self.HEADER_ALIASES[field]), None)
            if column is not None:
                updates.append({"range": f"'{quoted}'!{self._column_name(column)}{matches[0]}", "values": [[value]]})
        if not updates:
            raise GoogleSheetsError("Nenhum campo compatível foi informado para escrita.")
        written = httpx.post(f"{self.API}/{self.spreadsheet_id}/values:batchUpdate", headers={**headers, "Content-Type": "application/json"}, json={"valueInputOption": "RAW", "data": updates}, timeout=30)
        if written.status_code != 200:
            raise GoogleSheetsError("O Google Sheets recusou a atualização da planilha de destino.")
        return {"spreadsheet_id": self.spreadsheet_id, "sheet_name": sheet, "lt": lt, "updated_fields": sorted(item for item, value in values.items() if value is not None and item in self.HEADER_ALIASES)}
