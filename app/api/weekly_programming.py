import asyncio
import csv
from datetime import datetime, timezone
import io
import re
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.security import Permission, require_permission
from app.storage.weekly_programming import WeeklyProgrammingRepository
from app.integrations.google_sheets import GoogleSheetsError, GoogleSheetsWriteback


router = APIRouter(
    prefix="/api/weekly-programming",
    tags=["weekly-programming"],
    dependencies=[Depends(require_permission(Permission.TRIPS_READ))],
)

SPREADSHEET_ID = "1bMedHYmCiZZA6w1pXpQZbg8Rcmts5cQXfSEN9aN_v6s"
MAX_SOURCE_BYTES = 2_000_000
CACHE_SECONDS = 45
_cache: tuple[float, str, str, str, dict[int, str]] | None = None
_lock = asyncio.Lock()
_WEEKLY_SHEET_PATTERN = re.compile(
    r'\[\d+,0,\\"(?P<gid>\d+)\\".{0,120}?\[\[0,0,\\"(?P<name>\s*LHW[\s_-]*\d{1,3})\\"',
    re.IGNORECASE,
)


def _latest_weekly_sheet(metadata: str) -> tuple[str, str]:
    sheets: list[tuple[int, str, str]] = []
    for match in _WEEKLY_SHEET_PATTERN.finditer(metadata):
        number_match = re.search(r"(\d{1,3})$", match.group("name").strip())
        if number_match:
            number = int(number_match.group(1))
            sheets.append((number, f"LHW{number}", match.group("gid")))
    if not sheets:
        raise ValueError("Nenhuma aba semanal LHW foi localizada.")
    _, name, gid = max(sheets, key=lambda item: item[0])
    return name, gid


class WeeklyProgrammingState(BaseModel):
    week: str = Field(min_length=1, max_length=80)
    file_name: str = Field(min_length=1, max_length=255)
    sheet_name: str = Field(min_length=1, max_length=80)
    rows: list[dict[str, object]] = Field(max_length=5000)
    imported_at: str | None = None
    online_fetched_at: str | None = None


class WeeklyProgrammingWriteback(BaseModel):
    lt: str = Field(min_length=1, max_length=80)
    sheet_name: str = Field(pattern=r"(?i)^LHW\d{1,3}$")
    driver: str | None = Field(default=None, max_length=180)
    truck: str | None = Field(default=None, max_length=20)
    trailer: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=40)
    cpf: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=254)
    driver_id: str | None = Field(default=None, max_length=100)
    event: Literal["FIELDS", "DRIVER_SELECTED", "ROUTE_RELEASED"] = "FIELDS"


def _repository() -> WeeklyProgrammingRepository:
    return WeeklyProgrammingRepository(get_settings().operations_database_path)


@router.get("/state")
async def weekly_programming_state() -> dict[str, object]:
    state = await asyncio.to_thread(_repository().load)
    return {"state": state}


@router.put("/state", dependencies=[Depends(require_permission(Permission.TRIPS_EDIT))])
async def save_weekly_programming_state(payload: WeeklyProgrammingState) -> dict[str, object]:
    state = await asyncio.to_thread(
        _repository().save,
        week=payload.week, file_name=payload.file_name, sheet_name=payload.sheet_name,
        rows=payload.rows, imported_at=payload.imported_at,
        online_fetched_at=payload.online_fetched_at,
    )
    return {"state": state}


@router.post("/writeback", dependencies=[Depends(require_permission(Permission.TRIPS_EDIT))])
async def writeback_weekly_programming(payload: WeeklyProgrammingWriteback) -> dict[str, object]:
    if not get_settings().weekly_writeback_enabled:
        raise HTTPException(status_code=503, detail="A escrita no Google Sheets está desativada.")
    try:
        values = {
            "driver": payload.driver, "truck": payload.truck,
            "trailer": payload.trailer, "phone": payload.phone,
            "cpf": payload.cpf, "email": payload.email,
        }
        if payload.event in {"DRIVER_SELECTED", "ROUTE_RELEASED"}:
            if not payload.driver_id:
                if payload.event == "DRIVER_SELECTED" and payload.driver == "":
                    values = {"driver": ""}
                else:
                    raise HTTPException(status_code=422, detail="Selecione um motorista da Base de Motoristas.")
            else:
                def load_driver() -> sqlite3.Row | None:
                    connection = sqlite3.connect(get_settings().operations_database_path)
                    connection.row_factory = sqlite3.Row
                    try:
                        return connection.execute(
                            "SELECT name, phone, cpf FROM driver_profiles WHERE id = ?",
                            (payload.driver_id,),
                        ).fetchone()
                    finally:
                        connection.close()

                driver = await asyncio.to_thread(load_driver)
                if driver is None:
                    raise HTTPException(status_code=422, detail="Motorista não encontrado na Base de Motoristas.")
                if payload.event == "DRIVER_SELECTED":
                    values = {"driver": str(driver["name"] or "").strip()}
                else:
                    missing = []
                    if not str(driver["phone"] or "").strip(): missing.append("telefone")
                    if not str(driver["cpf"] or "").strip(): missing.append("CPF")
                    if not str(payload.truck or "").strip(): missing.append("cavalo")
                    if not str(payload.trailer or "").strip(): missing.append("carreta")
                    if missing:
                        raise HTTPException(status_code=422, detail=f"Preencha: {', '.join(missing)}.")
                    plate_pattern = re.compile(r"^[A-Z]{3}(?:\d{4}|\d[A-Z]\d{2})$")
                    invalid = []
                    truck = re.sub(r"[^A-Z0-9]", "", str(payload.truck).upper())
                    trailer = re.sub(r"[^A-Z0-9]", "", str(payload.trailer).upper())
                    if not plate_pattern.fullmatch(truck): invalid.append("cavalo")
                    if not plate_pattern.fullmatch(trailer): invalid.append("carreta")
                    if invalid:
                        raise HTTPException(status_code=422, detail=f"Placa inválida: {' e '.join(invalid)}.")
                    values = {
                        "driver": str(driver["name"] or "").strip(),
                        "truck": truck,
                        "trailer": trailer,
                        "phone": str(driver["phone"] or "").strip(),
                        "cpf": str(driver["cpf"] or "").strip(),
                    }
        result = await asyncio.to_thread(
            GoogleSheetsWriteback().update_lt,
            lt=payload.lt,
            sheet_name=payload.sheet_name,
            values=values,
        )
    except GoogleSheetsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"writeback": result}


@router.get("/source")
async def weekly_programming_source(force: bool = Query(default=False)) -> dict[str, object]:
    global _cache
    loop = asyncio.get_running_loop()
    now = loop.time()
    if not force and _cache and now - _cache[0] < CACHE_SECONDS:
        return {"csv": _cache[1], "fetched_at": _cache[2], "sheet_name": _cache[3], "row_colors": _cache[4], "cached": True}
    async with _lock:
        now = loop.time()
        if not force and _cache and now - _cache[0] < CACHE_SECONDS:
            return {"csv": _cache[1], "fetched_at": _cache[2], "sheet_name": _cache[3], "row_colors": _cache[4], "cached": True}
        try:
            sheets = GoogleSheetsWriteback()
            sheets.spreadsheet_id = SPREADSHEET_ID
            sheet_name, values, row_colors = await asyncio.to_thread(sheets.read_latest_weekly_source)
        except GoogleSheetsError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        output = io.StringIO(newline="")
        csv.writer(output).writerows(values)
        csv_text = output.getvalue()
        if len(csv_text.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise HTTPException(status_code=502, detail="A programação online excedeu o tamanho permitido.")
        fetched_at = datetime.now(timezone.utc).isoformat()
        _cache = (now, csv_text, fetched_at, sheet_name, row_colors)
        return {"csv": csv_text, "fetched_at": fetched_at, "sheet_name": sheet_name, "row_colors": row_colors, "cached": False}
