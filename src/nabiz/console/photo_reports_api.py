"""Citizen and operator endpoints for consented photo reports (E51)."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from ibb_mcp.text import fold_tr
from nabiz.console.access import TurnLimiter
from nabiz.console.citizen_requests import HourlyLimit, normal_code
from nabiz.console.operator import port_problem
from nabiz.console.photo_image import MAX_PHOTO_BYTES, MAX_PHOTO_EDGE, PhotoRejected, clean_photo
from nabiz.console.photo_reports import (
    MAX_DESCRIPTION_CHARS,
    MAX_REASON_CHARS,
    PHOTO_DISTRICTS,
    STATUS_TRANSITIONS,
    NewPhotoReport,
    PhotoReportStore,
    StoreFull,
    photo_per_hour,
    photo_report_ledger_request,
    photo_report_ledger_status,
    photo_report_ledger_withdrawn,
)
from nabiz.console.pii_guard import mask_labels
from nabiz.console.requests_api import SIMULATED_NOTE, emergency_answer, request_is_emergency
from nabiz.console.text_guard import strip_invisible
from nabiz.console.wiring import ledger_path
from nexus_core.ledger import Ledger

log = logging.getLogger("nabiz.console.photo_reports")
photo_report_routes = APIRouter()
MAX_BODY_BYTES = 3 * 1024 * 1024
MAX_STATUS_BODY_BYTES = 64 * 1024
TOO_MANY = "Bu cihazdan bir saatte en çok {n} fotoğraflı bildirim gönderilebilir. Biraz sonra yeniden deneyin."
NOT_FOUND = "Bildirim bulunamadı ya da 30 günlük saklama süresi doldu."
STATUS_LABELS = {"new": "Alındı", "reviewed": "İncelendi", "forwarded": "İletildi", "closed": "Kapatıldı"}
CATEGORIES = (
    {"key": "pavement", "tr": "Kaldırım ve yol", "en": "Sidewalk and road"},
    {"key": "lift", "tr": "Asansör ve yürüyen merdiven", "en": "Elevator and escalator"},
    {"key": "litter", "tr": "Çöp ve temizlik", "en": "Waste and cleanliness"},
    {"key": "lighting", "tr": "Aydınlatma", "en": "Lighting"},
    {"key": "other", "tr": "Diğer", "en": "Other"},
)


class PhotoPlace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["station", "district"]
    name: str = Field(min_length=1, max_length=80)


class PhotoReportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photo: str = Field(min_length=1, max_length=MAX_BODY_BYTES)
    category: Literal["pavement", "lift", "litter", "lighting", "other"]
    description: str = Field(default="", max_length=MAX_BODY_BYTES)
    place: PhotoPlace
    lang: Literal["tr", "en"]
    consent: StrictBool


class PhotoStatusBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["reviewed", "forwarded", "closed"]
    reason: str = ""


@dataclass
class _PhotoReportDesk:
    store: PhotoReportStore
    ledger: Ledger
    hourly: HourlyLimit
    reads: TurnLimiter
    status_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def photo_report_desk(request: Request) -> _PhotoReportDesk:
    """Build the photo-report desk once for this app process."""
    desk = getattr(request.app.state, "photo_desk", None)
    if desk is None:
        desk = _PhotoReportDesk(
            PhotoReportStore(), Ledger(ledger_path()), HourlyLimit(photo_per_hour()), TurnLimiter(30)
        )
        request.app.state.photo_desk = desk
    return desk


def _no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    return response


def _problem(status: int, code: str, message: str) -> Response:
    return _no_store(port_problem(status, code, message))


def _citizen_view(row: dict[str, Any]) -> dict[str, Any]:
    """The code holder's card: masked text and status history, never photo bytes or a photo URL."""
    return {
        "code": row["code"],
        "status": row["status"],
        "category": row["category"],
        "place": row["place"],
        "description": row["description"],
        "masked_count": row["masked_count"],
        "lang": row["lang"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "history": row["history"],
        "simulated": SIMULATED_NOTE,
    }


async def _read_body(request: Request, limit: int = MAX_BODY_BYTES) -> bytes | None:
    raw_length = request.headers.get("content-length", "").strip()
    if raw_length:
        try:
            if int(raw_length) > limit:
                return None
        except ValueError:
            return b""
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > limit:
            return None
    return bytes(chunks)


async def _validated_body(request: Request) -> PhotoReportBody | Response:
    raw = await _read_body(request)
    if raw is None:
        return _problem(413, "body_too_large", "Fotoğraf isteği 3 MB sınırını aşıyor. Daha küçük bir fotoğraf seçin.")
    try:
        return PhotoReportBody.model_validate_json(raw)
    except ValidationError:
        return _problem(
            422,
            "invalid_request",
            "İstek geçersiz: fotoğraf, kategori, açıklama, yer, dil ve rıza alanlarını denetleyin.",
        )


async def _validated_status_body(request: Request) -> PhotoStatusBody | Response:
    raw = await _read_body(request, MAX_STATUS_BODY_BYTES)
    if raw is None:
        return _problem(413, "body_too_large", "Durum isteği sınırı aşıyor. Gerekçeyi kısaltıp yeniden deneyin.")
    try:
        return PhotoStatusBody.model_validate_json(raw)
    except ValidationError:
        return _problem(422, "invalid_request", "İstek geçersiz: durum ve gerekçe alanlarını denetleyin.")


def _description(body: PhotoReportBody) -> str | Response:
    if body.consent is not True:
        return _problem(400, "consent_required", "Bildirimi iletmek için açık rıza kutusunu işaretleyin.")
    text, _ = strip_invisible(body.description)
    text = text.strip()
    if len(text) > MAX_DESCRIPTION_CHARS:
        return _problem(400, "description_too_long", "Açıklama en çok 280 karakter olabilir. Lütfen kısaltın.")
    if request_is_emergency(text):
        return _no_store(emergency_answer(text))
    return text


def _clean_encoded_photo(encoded: str):
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return _problem(400, "photo_malformed", "Fotoğraf okunamadı. Başka bir fotoğraf seçin.")
    try:
        return clean_photo(data)
    except PhotoRejected as exc:
        return _photo_problem(exc)


def _canonical_place(request: Request, place: PhotoPlace) -> dict[str, str] | Response:
    if place.kind == "district":
        match = next((name for name in PHOTO_DISTRICTS if fold_tr(name) == fold_tr(place.name)), None)
        if match is None:
            return _problem(400, "unknown_place", "İlçe bulunamadı; listeden seçin ya da istasyon seçin.")
        return {"kind": "district", "name": match}
    nabiz = getattr(request.app.state, "nabiz", None)
    places = getattr(getattr(nabiz, "places", None), "places", ())
    match = next(
        (
            item.name for item in places
            if getattr(item, "kind", None) == "metro_station"
            and getattr(item, "name", None)
            and fold_tr(item.name) == fold_tr(place.name)
        ),
        None,
    )
    if match is None:
        return _problem(400, "unknown_place", "İstasyon bulunamadı; listeden seçin ya da ilçe seçin.")
    return {"kind": "station", "name": str(match)}


def _photo_problem(exc: PhotoRejected) -> Response:
    problems = {
        "too_large": (413, "too_large", "Fotoğraf 2 MB sınırını aşıyor. Daha küçük bir fotoğraf seçin."),
        "bad_type": (415, "bad_type", "Yalnız JPEG, PNG ya da WebP fotoğraf seçin."),
        "too_many_pixels": (400, "too_many_pixels", "Fotoğrafın uzun kenarı 1600 pikseli aşmamalı."),
        "malformed": (400, "photo_malformed", "Fotoğraf okunamadı. Başka bir fotoğraf seçin."),
    }
    status, code, message = problems[exc.code]
    return _problem(status, code, message)


@photo_report_routes.get("/api/photo-reports/options")
async def photo_report_options() -> Response:
    return _no_store(Response(
        content=json.dumps({
            "categories": CATEGORIES,
            "districts": PHOTO_DISTRICTS,
            "limits": {
                "max_bytes": MAX_PHOTO_BYTES,
                "max_edge": MAX_PHOTO_EDGE,
                "text_chars": MAX_DESCRIPTION_CHARS,
                "ttl_days": 30,
                "per_hour": photo_per_hour(),
            },
        }, ensure_ascii=False),
        media_type="application/json",
    ))


@photo_report_routes.post("/api/photo-reports")
async def create_photo_report(request: Request) -> Response:
    validated = await _validated_body(request)
    if isinstance(validated, Response):
        return validated
    body = validated
    description = _description(body)
    if isinstance(description, Response):
        return description
    desk = photo_report_desk(request)
    device = request.client.host if request.client else "unknown"
    if not desk.hourly.allow(device):
        return _problem(429, "too_many_requests", TOO_MANY.format(n=desk.hourly.limit))
    place = _canonical_place(request, body.place)
    if isinstance(place, Response):
        return place
    clean = _clean_encoded_photo(body.photo)
    if isinstance(clean, Response):
        return clean
    masked, count, kinds = mask_labels(description)
    draft = NewPhotoReport(
        category=body.category,
        place=place,
        description=masked,
        masked_count=count,
        masked_kinds=kinds,
        lang=body.lang,
        photo_meta={"type": clean.kind, "bytes": len(clean.data), "width": clean.width, "height": clean.height},
        photo=clean.data,
        photo_type=clean.kind,
    )
    row = await _persist_report(desk, draft)
    if isinstance(row, Response):
        return row
    return _no_store(Response(
        content=json.dumps(_citizen_view(row), ensure_ascii=False),
        status_code=201,
        media_type="application/json",
    ))


async def _persist_report(desk: _PhotoReportDesk, draft: NewPhotoReport) -> dict[str, Any] | Response:
    row: dict[str, Any] | None = None
    try:
        row = await asyncio.to_thread(desk.store.create, draft)
        await asyncio.to_thread(photo_report_ledger_request, desk.ledger, row)
        return row
    except StoreFull:
        return _problem(503, "store_full", "Şu an fotoğraflı bildirim alınamıyor. 153'ü arayabilirsiniz.")
    except (OSError, sqlite3.Error) as exc:
        if row is not None:
            await asyncio.to_thread(desk.store.withdraw, row["code"])
        log.error("photo report not stored (%s)", type(exc).__name__)
        return _problem(503, "not_stored", "Bildirim şu an kaydedilemedi. 153'ü arayabilirsiniz.")


def _allow_read(request: Request) -> Response | None:
    desk = photo_report_desk(request)
    device = request.client.host if request.client else "unknown"
    if desk.reads.allow(device):
        return None
    return _problem(429, "too_many_requests", "Çok sık sorgu geldi. Bir dakika sonra yeniden deneyin.")


@photo_report_routes.get("/api/photo-reports/{code}")
async def get_photo_report(request: Request, code: str) -> Response:
    if problem := _allow_read(request):
        return problem
    key = normal_code(code)
    row = await asyncio.to_thread(photo_report_desk(request).store.get, key) if key else None
    if row is None:
        return _problem(404, "not_found", NOT_FOUND)
    return _no_store(Response(content=json.dumps(_citizen_view(row), ensure_ascii=False), media_type="application/json"))


@photo_report_routes.delete("/api/photo-reports/{code}")
async def delete_photo_report(request: Request, code: str) -> Response:
    if problem := _allow_read(request):
        return problem
    key = normal_code(code)
    if key is None:
        return _problem(404, "not_found", NOT_FOUND)
    desk = photo_report_desk(request)
    row = await asyncio.to_thread(desk.store.get, key)
    if row is None or not await asyncio.to_thread(desk.store.withdraw, key):
        return _problem(404, "not_found", NOT_FOUND)
    try:
        await asyncio.to_thread(photo_report_ledger_withdrawn, desk.ledger, key)
    except (OSError, sqlite3.Error) as exc:
        log.error("photo report withdrawal ledger failed (%s)", type(exc).__name__)
        return _problem(503, "not_stored", "Silme kaydı şu an mühürlenemedi. Biraz sonra yeniden deneyin.")
    return _no_store(Response(content='{"deleted":true}', media_type="application/json"))


@photo_report_routes.get("/api/console/photo-reports")
async def list_photo_reports(request: Request) -> Response:
    status = request.query_params.get("status", "open")
    if status not in {"open", "all"}:
        return _problem(422, "invalid_request", "Durum filtresi open ya da all olmalı.")
    desk = photo_report_desk(request)
    items = await asyncio.to_thread(desk.store.items, open_only=status == "open")
    all_items = items if status == "all" else await asyncio.to_thread(desk.store.items, open_only=False)
    counts = {name: sum(item["status"] == name for item in all_items) for name in STATUS_TRANSITIONS}
    payload = {"items": items, "counts": counts}
    return _no_store(Response(content=json.dumps(payload, ensure_ascii=False), media_type="application/json"))


@photo_report_routes.get("/api/console/photo-reports/{code}/photo")
async def get_operator_photo(request: Request, code: str) -> Response:
    key = normal_code(code)
    photo = await asyncio.to_thread(photo_report_desk(request).store.photo, key) if key else None
    if photo is None:
        return _problem(404, "not_found", "Fotoğraf bulunamadı ya da bildirim kapatıldı.")
    data, kind = photo
    media = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[kind]
    return _no_store(Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": "inline",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    ))


@photo_report_routes.post("/api/console/photo-reports/{code}/status")
async def set_photo_report_status(request: Request, code: str) -> Response:
    body = await _validated_status_body(request)
    if isinstance(body, Response):
        return body
    key = normal_code(code)
    if key is None:
        return _problem(404, "not_found", NOT_FOUND)
    reason, _ = strip_invisible(body.reason)
    reason = reason.strip()
    if not reason:
        return _problem(400, "reason_required", "Durum değiştirmek için gerekçe yazın.")
    if len(reason) > MAX_REASON_CHARS:
        return _problem(400, "reason_too_long", "Gerekçe en çok 280 karakter olabilir. Lütfen kısaltın.")
    masked, masked_count, _ = mask_labels(reason)
    desk = photo_report_desk(request)
    async with desk.status_lock:
        try:
            row = await asyncio.to_thread(desk.store.set_status, key, body.status, masked, masked_count=masked_count)
        except ValueError:
            return _problem(409, "transition_not_allowed", "Bu durumdan seçilen geçiş yapılamaz. Bildirimi yeniden açın.")
        if row is None:
            return _problem(404, "not_found", NOT_FOUND)
        before = row["history"][-2]["status"]
        try:
            entry_id = await asyncio.to_thread(photo_report_ledger_status, desk.ledger, before, row)
        except (OSError, sqlite3.Error) as exc:
            log.error("photo report status ledger failed (%s)", type(exc).__name__)
            return _problem(503, "ledger_failed", "Durum değişti ancak defter kaydı mühürlenemedi. Entegratöre başvurun.")
    message = f"Durum: {STATUS_LABELS[row['status']]}. Defter kaydı {entry_id}."
    return _no_store(Response(
        content=json.dumps({"item": row, "ledger_entry_id": entry_id, "message": message}, ensure_ascii=False),
        media_type="application/json",
    ))


__all__ = [
    "CATEGORIES", "MAX_BODY_BYTES", "PhotoPlace", "PhotoReportBody", "PhotoStatusBody", "photo_report_desk",
    "photo_report_routes",
]
