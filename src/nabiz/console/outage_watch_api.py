"""API for sourced water-outage information and consented household confirmations."""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool

from ibb_mcp.knowledge.guardrails import host_allowed
from nabiz.console import text_guard
from nabiz.console.citizen_requests import HourlyLimit, normal_code, per_hour
from nabiz.console.operator import port_problem
from nabiz.console.outage_watch import (
    OutageStore,
    districts,
    history_for,
    ledger_confirmation,
    ledger_seen,
    normal_district,
    normal_neighbourhood,
    sources_data,
)
from nabiz.console.pii_guard import mask_labels
from nabiz.console.requests_api import SIMULATED_NOTE, emergency_answer, request_is_emergency
from nabiz.console.wiring import ledger_path
from nexus_core.ledger import Ledger

log = logging.getLogger("nabiz.console.outage_watch")
outage_routes = APIRouter()

NOT_FOUND = "Talep bulunamadı ya da 7 günlük saklama süresi doldu."
_TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class OutageReportBody(BaseModel):
    district: str = Field(min_length=1, max_length=80)
    neighbourhood: str = Field(min_length=1, max_length=120)
    consent: StrictBool | None = None
    announced_end: str | None = Field(default=None, max_length=5)
    note: str = Field(default="", max_length=280)
    lang: Literal["tr", "en"] = "tr"


class OutageRepeatBody(BaseModel):
    consent: StrictBool | None = None
    announced_end: str | None = Field(default=None, max_length=5)
    note: str = Field(default="", max_length=280)


class OutageDesk:
    def __init__(self, store: OutageStore, ledger: Ledger, limit: HourlyLimit) -> None:
        self.store = store
        self.ledger = ledger
        self.limit = limit


def outage_citizen_view(row: Mapping[str, Any]) -> dict[str, Any]:
    """Expose only this visitor's report, masked note and user-stated confirmations."""
    return {
        "code": row["code"],
        "status": row["status"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "district": row["district"],
        "neighbourhood": row["neighbourhood"],
        "lang": row.get("lang", "tr"),
        "confirmations": [
            {"at": item["at"], "source": "user", "label": "Siz bildirdiniz", "announced_end": item.get("announced_end")}
            for item in row["confirmations"]
        ],
        "note_masked": row.get("note_masked"),
        "masked_count": row.get("masked_count", 0),
        "simulated_note": "Prototip; bu teyit İSKİ'ye iletilmez.",
    }


def outage_operator_view(row: Mapping[str, Any]) -> dict[str, Any]:
    """Expose a compact operator card with already masked free text."""
    return {
        "code": row["code"],
        "status": row["status"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "district": row["district"],
        "neighbourhood": row["neighbourhood"],
        "confirmations": [
            {"at": item["at"], "source": "user", "announced_end": item.get("announced_end")} for item in row["confirmations"]
        ],
        "note_masked": row.get("note_masked"),
        "masked_count": row.get("masked_count", 0),
        "masked_kinds": row.get("masked_kinds", []),
        "lang": row.get("lang", "tr"),
    }


def outage_desk(request: Request) -> OutageDesk:
    desk = getattr(request.app.state, "outage_desk", None)
    if desk is None:
        desk = OutageDesk(OutageStore(), Ledger(ledger_path()), HourlyLimit(per_hour()))
        request.app.state.outage_desk = desk
    return desk


def _source_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    host = parsed.hostname or ""
    return parsed.scheme == "https" and host_allowed(host) and host not in {"igdas.istanbul", "www.igdas.istanbul"}


def _info_payload() -> dict[str, Any]:
    data = sources_data()
    source_by_id = {item["id"]: item for item in data.get("sources", []) if item.get("id")}
    official = dict(data.get("official") or {})
    capture = data.get("iski_capture") or {}
    if capture.get("list_status") == "veri_alinamadi_js":
        official.update(status="not_connected", list=None)
    else:
        official.setdefault("status", "recorded")
    official["page_url"] = official.get("page_url") if _source_url(official.get("page_url")) else None
    for quote in official.get("quotes", []):
        source = source_by_id.get(quote.get("source_id"), {})
        quote["source_url"] = source.get("url") if _source_url(source.get("url")) else None
        quote["captured_at"] = source.get("captured_at")
    gas = dict(data.get("gas") or {})
    for line in gas.get("lines", []):
        source = source_by_id.get(line.get("source_id"), {})
        line["source_url"] = source.get("url") if _source_url(source.get("url")) else None
        line["captured_at"] = source.get("captured_at")
        line["quotes"] = []
        for evidence_id in line.get("quote_ids", []):
            evidence = (data.get("evidence") or {}).get(evidence_id, {})
            quote_source = source_by_id.get(evidence.get("source_id") or line.get("source_id"), {})
            if evidence.get("text") and _source_url(quote_source.get("url")):
                line["quotes"].append({"text": evidence["text"], "source_url": quote_source["url"]})
    history = dict(data.get("history") or {})
    history["source_url"] = history.get("source_url") if _source_url(history.get("source_url")) else None
    history["dataset"] = history.get("dataset") if _source_url(history.get("dataset")) else None
    return {
        "official": official,
        "gas": gas,
        "notes": {"simulated": SIMULATED_NOTE, "not_official": "Resmî İBB hizmeti değildir."},
        "districts": districts(),
        # This captured public summary lets the device show history without uploading its saved area.
        "history": history,
    }


@outage_routes.get("/api/outage-watch/info")
async def outage_info() -> JSONResponse:
    try:
        return JSONResponse(_info_payload(), headers={"Cache-Control": "public, max-age=300"})
    except (OSError, ValueError) as exc:
        log.error("outage source snapshot unavailable (%s)", type(exc).__name__)
        return port_problem(503, "source_unavailable", "Kesinti kaynakları şu an açılamıyor.")


@outage_routes.get("/api/outage-watch/history")
async def outage_history(district: str = "", neighbourhood: str = "") -> dict[str, Any]:
    try:
        history = sources_data().get("history") or {}
    except (OSError, ValueError):
        return {"area": None}
    official_district = normal_district(district)
    cleaned = normal_neighbourhood(neighbourhood)
    area = history_for(history, official_district, cleaned[0]) if official_district and cleaned else None
    return {
        "period": history.get("period", "2023-2024"),
        "source_url": history.get("source_url"),
        "dataset": history.get("dataset"),
        "license": history.get("license"),
        "area": area,
    }


@outage_routes.post("/api/outage-watch/reports")
async def create_outage_report(request: Request, body: OutageReportBody) -> JSONResponse:
    if body.consent is not True:
        return port_problem(400, "consent_required", "Teyidi göndermek için onay kutusunu işaretleyin.")
    district = normal_district(body.district)
    if not district:
        return port_problem(400, "bad_request", "İlçeyi listeden seçin.")
    neighbourhood = normal_neighbourhood(body.neighbourhood)
    if not neighbourhood:
        return port_problem(400, "bad_request", "Mahalle adında kişisel bilgi olmamalı; yalnız mahalle adını yazın.")
    if body.announced_end and not _TIME.fullmatch(body.announced_end):
        return port_problem(400, "bad_request", "Duyurulan bitiş saatini saat ve dakika olarak yazın.")
    note, _ = text_guard.strip_invisible(body.note)
    note = note.strip()
    if request_is_emergency(note):
        return emergency_answer(note)
    if len(note) > 280:
        return port_problem(400, "bad_request", "Not en fazla 280 karakter olabilir.")
    masked, masked_count, masked_kinds = mask_labels(note) if note else ("", 0, ())
    desk = outage_desk(request)
    client = request.client.host if request.client else "unknown"
    if not desk.limit.allow(client):
        return port_problem(
            429,
            "too_many_requests",
            "Bu cihazdan bir saatte en çok 3 teyit gönderilebilir. Biraz sonra yeniden deneyin; acil durumda 112'yi arayın.",
        )
    try:
        row = await asyncio.to_thread(
            desk.store.create,
            district,
            neighbourhood[0],
            announced_end=body.announced_end,
            note_masked=masked or None,
            masked_count=masked_count,
            masked_kinds=masked_kinds,
            lang=body.lang,
        )
        try:
            await asyncio.to_thread(ledger_confirmation, desk.ledger, row)
        except (OSError, sqlite3.Error):
            await asyncio.to_thread(desk.store.discard, row["code"])
            raise
    except (OSError, sqlite3.Error) as exc:
        log.error("outage report not stored (%s)", type(exc).__name__)
        return port_problem(503, "not_stored", "Teyit şu an kaydedilemedi. Su kesintisi için 185'i arayabilirsiniz.")
    return JSONResponse(status_code=201, content=outage_citizen_view(row), headers={"Cache-Control": "no-store"})


@outage_routes.post("/api/outage-watch/reports/{code}/again")
async def confirm_outage_again(request: Request, code: str, body: OutageRepeatBody) -> JSONResponse:
    if body.consent is not True:
        return port_problem(400, "consent_required", "Teyidi göndermek için onay kutusunu işaretleyin.")
    key = normal_code(code)
    desk = outage_desk(request)
    current = await asyncio.to_thread(desk.store.get, key) if key else None
    if current is None:
        return port_problem(404, "not_found", NOT_FOUND)
    announced_end = body.announced_end
    if announced_end is not None and (not isinstance(announced_end, str) or not _TIME.fullmatch(announced_end)):
        return port_problem(400, "bad_request", "Duyurulan bitiş saatini saat ve dakika olarak yazın.")
    raw_note, _ = text_guard.strip_invisible(body.note)
    raw_note = raw_note.strip()
    if request_is_emergency(raw_note):
        return emergency_answer(raw_note)
    if len(raw_note) > 280:
        return port_problem(400, "bad_request", "Not en fazla 280 karakter olabilir.")
    masked, masked_count, masked_kinds = mask_labels(raw_note) if raw_note else ("", 0, ())
    if not desk.limit.allow(request.client.host if request.client else "unknown"):
        return port_problem(
            429,
            "too_many_requests",
            "Bu cihazdan bir saatte en çok 3 teyit gönderilebilir. Biraz sonra yeniden deneyin; acil durumda 112'yi arayın.",
        )
    updated = await asyncio.to_thread(
        desk.store.confirm_again,
        key,
        announced_end=announced_end,
        note_masked=masked or None,
        masked_count=masked_count,
        masked_kinds=masked_kinds,
    )
    if updated is None:
        return port_problem(409, "too_soon", "Bu dosyaya son 30 dakikada teyit eklendi.")
    try:
        await asyncio.to_thread(ledger_confirmation, desk.ledger, updated)
    except (OSError, sqlite3.Error) as exc:
        await asyncio.to_thread(desk.store.rollback_confirmation, key, updated["updated_at"], current)
        log.error("repeat outage ledger entry failed (%s)", type(exc).__name__)
        return port_problem(503, "not_stored", "Teyit şu an kaydedilemedi. Su kesintisi için 185'i arayabilirsiniz.")
    return JSONResponse(status_code=201, content=outage_citizen_view(updated), headers={"Cache-Control": "no-store"})


@outage_routes.get("/api/outage-watch/reports/{code}")
async def read_outage_report(request: Request, code: str) -> JSONResponse:
    key = normal_code(code)
    row = await asyncio.to_thread(outage_desk(request).store.get, key) if key else None
    if row is None:
        return port_problem(404, "not_found", NOT_FOUND)
    return JSONResponse(content=outage_citizen_view(row), headers={"Cache-Control": "no-store"})


@outage_routes.get("/api/console/outage-watch")
async def list_outage_reports(request: Request) -> dict[str, Any]:
    rows = await asyncio.to_thread(outage_desk(request).store.items)
    waiting = sum(row["status"] == "waiting" for row in rows)
    return {
        "items": [outage_operator_view(row) for row in rows],
        "areas": await asyncio.to_thread(outage_desk(request).store.area_counts),
        "counts": {"waiting": waiting, "seen": len(rows) - waiting},
    }


@outage_routes.post("/api/console/outage-watch/{code}/seen")
async def mark_outage_seen(request: Request, code: str) -> JSONResponse:
    key = normal_code(code)
    desk = outage_desk(request)
    if not key or await asyncio.to_thread(desk.store.get, key) is None:
        return port_problem(404, "not_found", NOT_FOUND)
    row = await asyncio.to_thread(desk.store.mark_seen, key)
    if row is None:
        return port_problem(409, "already_seen", "Operatör bu dosyayı daha önce gördü.")
    try:
        await asyncio.to_thread(ledger_seen, desk.ledger, row, "operatör (simüle)")
    except (OSError, sqlite3.Error) as exc:
        await asyncio.to_thread(desk.store.rollback_seen, key)
        log.error("outage seen ledger entry failed (%s)", type(exc).__name__)
        return port_problem(503, "not_stored", "Görüldü bilgisi şu an kaydedilemedi.")
    return JSONResponse(content=outage_operator_view(row), headers={"Cache-Control": "no-store"})
