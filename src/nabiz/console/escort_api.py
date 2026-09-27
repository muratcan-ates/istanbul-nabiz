"""The accessible-support request API, mounted by the integrator beside request_routes."""

from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import pathlib
import sqlite3
from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from ibb_mcp.config import Settings
from ibb_mcp.text import fold_tr
from nabiz.console.citizen_requests import HourlyLimit
from nabiz.console.escort_request import (
    ASSISTANCE,
    DISCLAIMER,
    NEEDS,
    OPERATOR_MOVES,
    RETURN_KINDS,
    SIMULATED_NOTE,
    WAITING_ON,
    WINDOWS_MIN,
    EscortDraft,
    EscortStore,
    TransitionError,
    normal_code,
    validate,
)
from nabiz.console.operator import port_problem
from nabiz.console.quota import address_key
from nabiz.console.requests_api import emergency_answer, request_is_emergency, usable_text
from nabiz.console.wiring import REPO_ROOT

log = logging.getLogger("nabiz.console.escort")
escort_routes = APIRouter()

TR_MONTHS = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık")
EN_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
NEED_NAMES = {
    "tr": dict(
        zip(NEEDS, ("Tekerlekli sandalye", "Yürümekte zorlanma", "Az görme", "İşitme", "Bilişsel destek", "Diğer"), strict=True)
    ),
    "en": dict(
        zip(NEEDS, ("Wheelchair", "Walking difficulty", "Low vision", "Hearing", "Cognitive support", "Other"), strict=True)
    ),
}
ASSISTANCE_NAMES = {
    "tr": {
        "meet_at_entrance": "Girişte buluşma",
        "guide_inside_station": "İstasyon içinde yön bulma",
        "boarding_alighting": "Araca binme veya inme",
        "transfer": "Aktarma",
        "step_free_route_check": "Adımsız yolu kontrol etme",
    },
    "en": {
        "meet_at_entrance": "Meet at the entrance",
        "guide_inside_station": "Find the way inside the station",
        "boarding_alighting": "Boarding or alighting",
        "transfer": "Transfer",
        "step_free_route_check": "Check a step-free route",
    },
}
RETURN_NAMES = {"tr": {"none": "Yok", "later": "Daha sonra bildireceğim"}, "en": {"none": "None", "later": "I'll say later"}}
STATUS_TEXT = {
    "tr": {
        "received": "Alındı. Nabız örnek operatörü henüz görmedi. Bu kayıt bir refakat düzenlemesi anlamına gelmez.",
        "seen": "Nabız örnek operatörü dosyanızı gördü. Refakat olanağını 153'e sorabilirsiniz.",
        "referred_official": "Resmî kanala yönlendirildi: {agency}. Nabız kurumdan teyit almadı; 153'e sorabilirsiniz.",
        "closed": "Kapatıldı.",
        "cancelled": "Siz iptal ettiniz.",
    },
    "en": {
        "received": (
            "Received. The Nabız example operator has not seen this file yet. "
            "This record does not mean an escort has been arranged."
        ),
        "seen": "The Nabız example operator has seen your file. You can ask 153 whether an escort option is available.",
        "referred_official": (
            "Referred to the official channel: {agency}. Nabız has not received confirmation from the agency; you can ask 153."
        ),
        "closed": "Closed.",
        "cancelled": "You cancelled this request.",
    },
}


def load_stations(path: str | pathlib.Path | None = None) -> tuple[str, ...]:
    file_path = pathlib.Path(path) if path is not None else Settings.from_env().places_csv
    try:
        with file_path.open(encoding="utf-8-sig", newline="") as source:
            values: dict[str, str] = {}
            for row in csv.DictReader(source):
                name = row.get("name", "").strip()
                if row.get("kind") == "metro_station" and name:
                    values.setdefault(fold_tr(name), name)
    except OSError:
        return ()
    return tuple(sorted(values.values(), key=fold_tr))


def load_sources(path: str | pathlib.Path | None = None) -> list[dict[str, Any]]:
    source_path = pathlib.Path(path) if path is not None else REPO_ROOT / "data" / "escort_sources.json"
    sources = json.loads(source_path.read_text(encoding="utf-8"))
    agencies_data = json.loads((REPO_ROOT / "data" / "agencies.json").read_text(encoding="utf-8"))
    agency_ids = {agency["id"] for agency in agencies_data["agencies"]}
    allowed = {
        line.split("\t", 1)[0]
        for line in (REPO_ROOT / "data" / "knowledge" / "sources.txt").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }
    for source in sources:
        if source.get("agency_id") not in agency_ids or source.get("url", "").split(":", 1)[0] != "https":
            raise ValueError("Kaynak kurumu veya güvenli bağlantısı geçersiz.")
        if source["url"] not in allowed:
            raise ValueError("Kaynak URL'si izin listesinde bulunamadı.")
    knowledge_db = REPO_ROOT / "data" / "knowledge" / "knowledge.db"
    if knowledge_db.is_file():
        with sqlite3.connect(knowledge_db) as db:
            active = {row[0] for row in db.execute("SELECT canonical_url FROM documents WHERE active = 1").fetchall()}
        if any(item["url"] not in active for item in sources):
            raise ValueError("Kaynağın etkin bilgi belgesi bulunamadı.")
    return sources


def add_minutes(value: str, minutes: int) -> str:
    return (dt.datetime.strptime(value, "%H:%M") + dt.timedelta(minutes=minutes)).strftime("%H:%M")


def _ends_next_day(value: str, minutes: int) -> bool:
    return int(value[:2]) * 60 + int(value[3:]) + minutes >= 24 * 60


def summary_lines(draft: EscortDraft, lang: str = "tr") -> list[str]:
    language = "en" if lang == "en" else "tr"
    month = (EN_MONTHS if language == "en" else TR_MONTHS)[draft.date.month - 1]
    end_time = add_minutes(draft.time, draft.window_min)
    if _ends_next_day(draft.time, draft.window_min):
        end_time += " (next day)" if language == "en" else " (ertesi gün)"
    return_text = RETURN_NAMES[language].get(draft.return_kind, "")
    if draft.return_kind == "same_day":
        return_text = f"same day at {draft.return_time}" if language == "en" else f"aynı gün {draft.return_time}"
    if language == "en":
        lines = [
            f"Need: {NEED_NAMES[language][draft.need]}",
            f"Requested support: {', '.join(ASSISTANCE_NAMES[language][item] for item in draft.assistance)}",
            f"Date: {draft.date.day} {month} {draft.date.year}, between {draft.time} and {end_time}",
            f"Meeting point: {draft.meet_station} station",
            f"Destination: {draft.to_station} station",
            f"Return: {return_text}",
            f"Companion with me: {'Yes' if draft.companion else 'No'}",
        ]
        if draft.note:
            lines.append(f"Note: {draft.note}")
        return lines
    lines = [
        f"İhtiyaç: {NEED_NAMES[language][draft.need]}",
        f"İstenen destek: {', '.join(ASSISTANCE_NAMES[language][item] for item in draft.assistance)}",
        f"Tarih: {draft.date.day} {month} {draft.date.year}, {draft.time} ile {end_time} arası",
        f"Buluşma: {draft.meet_station} istasyonu",
        f"Varış: {draft.to_station} istasyonu",
        f"Dönüş: {return_text}",
        f"Refakatçim var: {'Evet' if draft.companion else 'Hayır'}",
    ]
    if draft.note:
        lines.append(f"Not: {draft.note}")
    return lines


def _view_draft(data: Mapping[str, Any]) -> EscortDraft:
    return EscortDraft(
        data["need"],
        tuple(data["assistance"]),
        dt.date.fromisoformat(data["date"]),
        data["time"],
        data["window_min"],
        data["meet_station"],
        data["to_station"],
        data["return_kind"],
        data.get("return_time"),
        data["companion"],
        data.get("note_masked", ""),
    )


def escort_citizen_view(
    row: Mapping[str, Any], sources: list[dict[str, Any]], agencies: Mapping[str, dict[str, Any]]
) -> dict[str, Any]:
    data = row["data"]
    lang = "en" if data.get("lang") == "en" else "tr"
    agency = agencies.get(data.get("agency_id", ""))
    text = STATUS_TEXT[lang][row["status"]].format(agency=agency["name"] if agency else "")
    history = [{"status": entry["status"], "at": entry["at"]} for entry in data["history"]]
    note = next((entry.get("note_masked") for entry in reversed(data["history"]) if entry.get("note_masked")), None)
    return {
        "code": row["code"],
        "status": row["status"],
        "waiting_on": WAITING_ON[row["status"]],
        "status_text": text,
        "summary": summary_lines(_view_draft(data)),
        "history": history,
        "agency": {key: agency[key] for key in ("id", "name", "url")} if agency else None,
        "operator_note": note,
        "official": {"call": "153", "agency": agencies["cozum_153"]},
        "sources": sources,
        "simulated": SIMULATED_NOTE,
        "disclaimer": DISCLAIMER,
    }


def escort_operator_view(row: Mapping[str, Any]) -> dict[str, Any]:
    data = row["data"]
    history = [
        {
            "status": entry["status"],
            "at": entry["at"],
            "by": entry["by"],
            "agency_id": entry.get("agency_id"),
            "note_masked": entry.get("note_masked"),
        }
        for entry in data["history"]
    ]
    return {
        "code": row["code"],
        "status": row["status"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "summary": summary_lines(_view_draft(data)),
        "need": data["need"],
        "date": data["date"],
        "time": data["time"],
        "window_min": data["window_min"],
        "meet_station": data["meet_station"],
        "to_station": data["to_station"],
        "note_masked": data.get("note_masked", ""),
        "masked_count": data.get("masked_count", 0),
        "history": history,
    }


class EscortBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    need: str
    assistance: list[str]
    date: str
    time: str
    window_min: int
    meet_station: str
    to_station: str
    return_kind: str
    return_time: str | None = None
    companion: StrictBool
    note: str = Field(default="", max_length=800)
    consent: StrictBool


class MoveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: str
    note: str | None = Field(default=None, max_length=800)
    agency_id: str | None = Field(default=None, max_length=80)


def _problem(status: int, kind: str, message: str) -> JSONResponse:
    response = port_problem(status, kind, message)
    response.headers["Cache-Control"] = "no-store"
    return response


def _json(status: int, content: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=content, headers={"Cache-Control": "no-store"})


def _store(app: FastAPI) -> EscortStore:
    value = getattr(app.state, "escort_store", None)
    if value is None:
        value = EscortStore()
        app.state.escort_store = value
    return value


def _catalogs() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    sources = load_sources()
    agencies_data = json.loads((REPO_ROOT / "data" / "agencies.json").read_text(encoding="utf-8"))
    agencies = {agency["id"]: agency for agency in agencies_data["agencies"]}
    return sources, agencies


def _client_key(request: Request) -> str:
    return address_key(request.client.host if request.client else None)


def _limit(app: FastAPI) -> HourlyLimit:
    value = getattr(app.state, "escort_limit", None)
    if value is None:
        value = HourlyLimit(3)
        app.state.escort_limit = value
    return value


def _view(row: dict[str, Any]) -> dict[str, Any]:
    sources, agencies = _catalogs()
    return escort_citizen_view(row, sources, agencies)


@escort_routes.get("/api/escort/options")
async def escort_options() -> JSONResponse:
    stations = load_stations()
    if not stations:
        return _problem(503, "stations_missing", "İstasyon listesi bu sunucuda yok. 153'ü arayabilirsiniz.")
    try:
        sources, agencies = _catalogs()
    except (OSError, ValueError, json.JSONDecodeError):
        return _problem(503, "sources_unavailable", "Kaynak listesi şu an açılamıyor. 153'ü arayabilirsiniz.")
    return _json(
        200,
        {
            "stations": stations,
            "needs": NEEDS,
            "assistance": ASSISTANCE,
            "windows": WINDOWS_MIN,
            "return_kinds": RETURN_KINDS,
            "sources": sources,
            "official": {"call": "153", "agency": agencies["cozum_153"]},
        },
    )


@escort_routes.post("/api/escort/requests")
async def create_escort(request: Request, body: EscortBody) -> JSONResponse:
    if body.consent is not True:
        return _problem(400, "consent_required", "Talebi göndermek için açık rıza kutusunu işaretleyin.")
    note, problem = usable_text(body.note) if body.note else ("", None)
    if note is None:
        return _problem(400, "bad_request", problem or "Not alanı geçersiz.")
    if note and request_is_emergency(note):
        return emergency_answer(note)
    candidate = body.model_dump()
    candidate["note"] = note or ""
    stations = load_stations()
    if not stations:
        return _problem(503, "stations_missing", "İstasyon listesi bu sunucuda yok. 153'ü arayabilirsiniz.")
    draft = validate(candidate, stations, dt.datetime.now(ZoneInfo("Europe/Istanbul")).date())
    if isinstance(draft, str):
        return _problem(400, "bad_request", draft)
    if not _limit(request.app).allow(_client_key(request)):
        return _problem(429, "too_many", "Bu cihazdan bir saatte en çok 3 talep gönderilebilir. 153'ü arayabilirsiniz.")
    try:
        return _json(201, _view(_store(request.app).create(draft)))
    except (OSError, sqlite3.Error):
        return _problem(503, "not_stored", "Talep şu an kaydedilemedi. 153'ü arayabilirsiniz.")


@escort_routes.get("/api/escort/requests/{code}")
async def read_escort(request: Request, code: str) -> JSONResponse:
    normalized = normal_code(code)
    if normalized is None:
        return _problem(404, "not_found", "Talep bulunamadı ya da saklama süresi doldu.")
    try:
        row = _store(request.app).get(normalized)
        return _json(200, _view(row)) if row else _problem(404, "not_found", "Talep bulunamadı ya da saklama süresi doldu.")
    except (OSError, sqlite3.Error):
        return _problem(503, "not_stored", "Talep şu an okunamıyor. 153'ü arayabilirsiniz.")


@escort_routes.post("/api/escort/requests/{code}/cancel")
async def cancel_escort(request: Request, code: str) -> JSONResponse:
    normalized = normal_code(code)
    if normalized is None:
        return _problem(404, "not_found", "Talep bulunamadı ya da saklama süresi doldu.")
    try:
        row = _store(request.app).move(normalized, "citizen", "cancelled")
        return _json(200, _view(row)) if row else _problem(404, "not_found", "Talep bulunamadı ya da saklama süresi doldu.")
    except TransitionError:
        return _problem(409, "not_now", "Bu talep artık iptal edilemiyor.")
    except (OSError, sqlite3.Error):
        return _problem(503, "not_stored", "Talep şu an güncellenemiyor. 153'ü arayabilirsiniz.")


@escort_routes.get("/api/console/escort")
async def console_escorts(request: Request) -> JSONResponse:
    try:
        rows = _store(request.app).items()
        counts = {status: sum(row["status"] == status for row in rows) for status in ("received", "seen", "referred_official")}
        _, agencies = _catalogs()
        return _json(
            200,
            {
                "items": [escort_operator_view(row) for row in rows],
                "counts": counts,
                "agencies": [{key: agency[key] for key in ("id", "name", "url")} for agency in agencies.values()],
            },
        )
    except (OSError, sqlite3.Error):
        return _problem(503, "not_stored", "Talep listesi şu an okunamıyor.")


@escort_routes.post("/api/console/escort/{code}/move")
async def move_escort(request: Request, body: MoveBody, code: str) -> JSONResponse:
    normalized = normal_code(code)
    if normalized is None:
        return _problem(404, "not_found", "Talep bulunamadı ya da saklama süresi doldu.")
    if body.to not in {move for options in OPERATOR_MOVES.values() for move in options}:
        return _problem(409, "not_allowed", "Bu geçişe izin verilmiyor.")
    agency_ids: set[str] = set()
    try:
        _, agencies = _catalogs()
        agency_ids = set(agencies)
    except (OSError, ValueError, json.JSONDecodeError):
        return _problem(503, "sources_unavailable", "Kurum listesi şu an açılamıyor.")
    if body.to == "referred_official" and body.agency_id not in agency_ids:
        return _problem(400, "agency_required", "Listeden bir kurum seçin.")
    if body.agency_id and body.agency_id not in agency_ids:
        return _problem(400, "unknown_agency", "Bu kurum listede bulunmuyor.")
    try:
        row = _store(request.app).move(normalized, "operator", body.to, note=body.note, agency_id=body.agency_id)
        if row is None:
            return _problem(404, "not_found", "Talep bulunamadı ya da saklama süresi doldu.")
        log.info("escort move status=%s", row["status"])
        return _json(200, escort_operator_view(row))
    except TransitionError:
        return _problem(409, "not_allowed", "Bu geçişe izin verilmiyor.")
    except ValueError as exc:
        return _problem(400, "invalid_move", str(exc))
    except (OSError, sqlite3.Error):
        return _problem(503, "not_stored", "Talep şu an güncellenemiyor.")
