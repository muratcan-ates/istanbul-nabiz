"""Routes for "Operatöre aktar + çeviri": a visitor asks a person, the operator answers, both in their language.

Citizen side (open, like the chat):

    POST /api/requests               {text, lang: "tr"|"en"|"auto", consent: true}  -> 201 the request card
                                     an emergency -> 200 {"emergency": true, ...}: the 112 card, no request
    GET  /api/requests/{code}        the card: waiting, or the reply in the visitor's language and in Turkish

Operator side (behind the console's door, :mod:`nabiz.console.access`, because the paths start
``/api/console/``):

    GET  /api/console/requests                      the queue, newest first
    POST /api/console/requests/{code}/preview       {text_tr} -> the reply's translation, nothing sent
    POST /api/console/requests/{code}/reply         {text_tr, text_translated} -> sent, sealed in the ledger

**112 first.** The request's text is checked for an emergency before anything else (the chat's
rule, :func:`nabiz.console.policy.emergency_intent`, and the fixed classifier
:func:`nabiz.console.emergency.classify`): an emergency is never queued for an operator and costs no
model call. A Turkish translation that reads as an emergency sends the visitor to 112 too.

**A person approves every reply.** A reply in another language cannot be sent before the operator
has previewed its translation for exactly that Turkish text; what the operator sends (the model's
text, a corrected one, their own, or none) is what the visitor sees, labelled honestly.

**Limits.** 1 000 characters a request and a reply; three requests per device (client address)
per sliding hour, in memory; the model's calls count against the chat's daily ceiling. A visitor
never sees another visitor's request: the eight-character code is the only key.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool

from nabiz.console import policy, text_guard
from nabiz.console.citizen_requests import (
    MAX_CHARS,
    HourlyLimit,
    NewRequest,
    RequestStore,
    category_of,
    digest,
    ledger_reply,
    ledger_request,
    normal_code,
    per_hour,
)
from nabiz.console.emergency import classify
from nabiz.console.health_mask import mask_request
from nabiz.console.operator import port_problem
from nabiz.console.pii_guard import mask_labels
from nabiz.console.ports import OPERATOR
from nabiz.console.translate import LANG_SOURCE_TR, STATUS_TR, Translation, Translator, reply_to_citizen, request_to_turkish
from nabiz.console.wiring import ledger_path
from nexus_core.decisions import Operator
from nexus_core.ledger import Ledger

log = logging.getLogger("nabiz.console.requests")
request_routes = APIRouter()

EMERGENCY_TEXT = "Bu acil bir durum olabilir. İBB operatörü 112'nin yerine geçmez: lütfen hemen 112'yi arayın."
TOO_LONG = f"Talep en fazla {MAX_CHARS:,} karakter olabilir. Lütfen kısaltın.".replace(",", ".")
TOO_MANY = (
    "Bu cihazdan bir saatte en çok {n} talep gönderilebilir. Biraz sonra yeniden deneyin; "
    "acil bir durumdaysanız 112'yi, diğer konularda 153'ü arayabilirsiniz."
)
NOT_FOUND = "Talep bulunamadı ya da 30 günlük saklama süresi doldu."
PREVIEW_NOTE = "Önizleme; henüz hiçbir şey gönderilmedi. Çeviriyi düzeltebilir ya da boş bırakabilirsiniz."
PREVIEW_NOTE_TR = "Önizleme; henüz hiçbir şey gönderilmedi. Talep Türkçe: cevabınız yazdığınız gibi gider."
PREVIEW_FIRST = "Önce çeviriyi önizleyin: yanıt, önizlediğiniz metinle aynı olmalı."
#: What the visitor is told about the reply's translation, keyed by how it was made.
REPLY_LABELS = {
    "model": "Bu yanıt bir İBB çalışanı tarafından yazıldı ve otomatik çevrildi.",
    "edited": "Bu yanıt bir İBB çalışanı tarafından yazıldı, otomatik çevrildi ve çalışan çeviriyi düzeltti.",
    "operator": "Bu yanıt bir İBB çalışanı tarafından yazıldı ve çevirisini çalışan yaptı.",
    "not_needed": "Bu yanıt bir İBB çalışanı tarafından yazıldı.",
    "none": "Bu yanıt bir İBB çalışanı tarafından Türkçe yazıldı; çeviri şu an yok.",
}
#: The prototype's operator is simulated (console band, DECISIONS #25); the visitor is told so.
SIMULATED_NOTE = "Prototip: operatör rolü simüledir; resmî İBB hizmeti değildir."
WAITING_NOTE = "Cevap geldiğinde bu kartta görünür. Acil bir durumda beklemeyin, 112'yi arayın."


class CitizenRequestBody(BaseModel):
    # Longer than MAX_CHARS on purpose: invisible characters are stripped before the length counts.
    text: str = Field(min_length=1, max_length=4 * MAX_CHARS)
    lang: Literal["tr", "en", "auto"] = "auto"
    consent: StrictBool


class ReplyPreviewBody(BaseModel):
    text_tr: str = Field(min_length=1, max_length=4 * MAX_CHARS)


class ReplyBody(ReplyPreviewBody):
    text_translated: str | None = Field(default=None, max_length=12 * MAX_CHARS)


class RequestDesk:
    """The app's request state: the table, the ledger, the translator, the hourly limit, the previews."""

    def __init__(self, store: RequestStore, ledger: Ledger, translator: Translator, limit: HourlyLimit) -> None:
        self.store = store
        self.ledger = ledger
        self.translator = translator
        self.limit = limit
        #: code -> (digest of the previewed Turkish reply, its translation); in memory, one per request.
        self.previews: dict[str, tuple[str, Translation]] = {}
        self.sending = asyncio.Lock()


def request_desk(app: FastAPI) -> RequestDesk:
    """The app's desk, built on first use over the chat's model configuration and spend guard."""
    desk = getattr(app.state, "request_desk", None)
    if desk is None:
        store = RequestStore()
        translator = Translator(app.state.chat_config, app.state.guard)
        desk = RequestDesk(store, Ledger(ledger_path()), translator, HourlyLimit(per_hour()))
        app.state.request_desk = desk
    return desk


def request_is_emergency(text: str | None) -> bool:
    return bool(text) and (policy.emergency_intent(text) or classify(text)["emergency"])


def emergency_answer(text: str) -> JSONResponse:
    body = {"emergency": True, "hazard": policy.emergency_hazard(text), "message": EMERGENCY_TEXT, "tel": "112"}
    return JSONResponse(status_code=200, content=body, headers={"Cache-Control": "no-store"})


def usable_text(raw: str) -> tuple[str | None, str | None]:
    """The text with invisible characters removed, or the reason it cannot be used."""
    text, _ = text_guard.strip_invisible(raw)
    text = text.strip()
    if not text:
        return None, "Metin boş."
    if len(text) > MAX_CHARS:
        return None, TOO_LONG
    return text, None


def citizen_view(row: dict[str, Any]) -> dict[str, Any]:
    """What the visitor's device may read: their own masked question and the reply, never the operator's name."""
    reply = row.get("reply")
    shown = None
    if reply:
        shown = {
            "text": reply["text"],
            "lang": reply["lang"],
            "text_tr": reply["text_tr"] if reply["lang"] != "tr" else None,
            "translation": reply["translation"],
            "label": REPLY_LABELS[reply["translation"]],
            "answered_at": reply["answered_at"],
        }
    no_translation = row["translation_status"] not in {"model", "not_needed"}
    return {
        "code": row["code"],
        "status": row["status"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "lang": row["lang"],
        "question": row["original_masked"],
        "masked_count": row["masked_count"],
        "translation_note": STATUS_TR[row["translation_status"]] if no_translation else None,
        "note": WAITING_NOTE,
        "simulated": SIMULATED_NOTE,
        "reply": shown,
    }


def operator_view(row: dict[str, Any]) -> dict[str, Any]:
    """The operator's card: the masked original, the Turkish text or why there is none, the hints."""
    return {
        "code": row["code"],
        "signal_id": row["signal_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "lang": row["lang"],
        "lang_source": LANG_SOURCE_TR.get(row["lang_source"], row["lang_source"]),
        "original": row["original_masked"],
        "masked_count": row["masked_count"],
        "masked_kinds": row["masked_kinds"],
        "turkish": row["turkish"],
        "translation": {"status": row["translation_status"], "label": STATUS_TR[row["translation_status"]],
                        "author": row["translation_author"]},
        "category": row["category"],
        "guard": row["guard"],
        "reply": row.get("reply"),
    }  # fmt: skip


async def _new_request(desk: RequestDesk, text: str, chosen: str | None) -> NewRequest | None:
    """Mask, translate the masked text, categorise; ``None`` when the translation reads as an emergency."""
    verdict = text_guard.check_input(text)
    guard = verdict.reason if verdict.reason in {"injection", "hidden_text"} else None
    masked, count, kinds = mask_request(text)
    translation, lang, source = await request_to_turkish(desk.translator, masked, chosen, guarded=guard is not None)
    if translation.status == "model" and request_is_emergency(translation.text):
        return None
    return NewRequest(
        original_masked=masked, masked_count=count, masked_kinds=kinds, lang=lang, lang_source=source,
        chosen_lang=chosen, turkish=translation.text, translation_status=translation.status,
        translation_author=translation.author, category=category_of(translation.text, masked), guard=guard,
    )  # fmt: skip


@request_routes.post("/api/requests")
async def create_request(request: Request, body: CitizenRequestBody) -> JSONResponse:
    if not body.consent:
        return port_problem(400, "consent_required", "Talebi iletmek için onay kutusunu işaretleyin.")
    text, problem = usable_text(body.text)
    if text is None:
        return port_problem(400, "bad_request", problem or "")
    if request_is_emergency(text):
        return emergency_answer(text)
    desk = request_desk(request.app)
    if not desk.limit.allow(request.client.host if request.client else "unknown"):
        return port_problem(429, "too_many_requests", TOO_MANY.format(n=desk.limit.limit))
    new = await _new_request(desk, text, None if body.lang == "auto" else body.lang)
    if new is None:
        return emergency_answer(text)
    try:
        row = await asyncio.to_thread(desk.store.create, new)
        await asyncio.to_thread(ledger_request, desk.ledger, row)
    except (OSError, sqlite3.Error) as exc:
        log.error("citizen request not stored (%s)", type(exc).__name__)
        return port_problem(503, "not_stored", "Talep şu an kaydedilemedi. 153'ü arayabilirsiniz.")
    return JSONResponse(status_code=201, content=citizen_view(row), headers={"Cache-Control": "no-store"})


@request_routes.get("/api/requests/{code}")
async def read_request(request: Request, code: str) -> JSONResponse:
    key = normal_code(code)
    row = await asyncio.to_thread(request_desk(request.app).store.get, key) if key else None
    if row is None:
        return port_problem(404, "not_found", NOT_FOUND)
    return JSONResponse(content=citizen_view(row), headers={"Cache-Control": "no-store"})


@request_routes.get("/api/console/requests")
async def list_requests(request: Request, status: Literal["waiting", "all"] = "all") -> dict[str, Any]:
    desk = request_desk(request.app)
    rows = await asyncio.to_thread(desk.store.items, status=None if status == "all" else "waiting")
    waiting = sum(row["status"] == "waiting" for row in rows)
    return {
        "items": [operator_view(row) for row in rows],
        "counts": {"waiting": waiting, "answered": len(rows) - waiting},
        "model": {"available": desk.translator.available},
    }


async def _waiting(desk: RequestDesk, code: str) -> dict[str, Any] | JSONResponse:
    key = normal_code(code)
    row = await asyncio.to_thread(desk.store.get, key) if key else None
    if row is None:
        return port_problem(404, "not_found", NOT_FOUND)
    if row["status"] != "waiting":
        return port_problem(409, "conflict", "Bu talep zaten yanıtlandı.")
    return row


@request_routes.post("/api/console/requests/{code}/preview")
async def preview_reply(request: Request, code: str, body: ReplyPreviewBody) -> Any:
    desk = request_desk(request.app)
    row = await _waiting(desk, code)
    if isinstance(row, JSONResponse):
        return row
    text, problem = usable_text(body.text_tr)
    if text is None:
        return port_problem(400, "bad_request", problem or "")
    translation = await reply_to_citizen(desk.translator, text, row["lang"])
    desk.previews[row["code"]] = (digest(text), translation)
    return {
        "code": row["code"],
        "lang": row["lang"],
        "translation": {"text": translation.text, "status": translation.status, "label": translation.label,
                        "author": translation.author},
        "note": PREVIEW_NOTE_TR if row["lang"] == "tr" else PREVIEW_NOTE,
    }  # fmt: skip


def reply_record(row: dict[str, Any], text: str, given: str | None, preview: Translation | None) -> dict[str, Any]:
    """The reply as stored: masked, in the visitor's language when there is a translation, and how it was made."""
    lang = row["lang"]
    given = (text_guard.strip_invisible(given or "")[0]).strip()
    if lang == "tr":
        kind, shown, shown_lang = "not_needed", text, "tr"
    elif preview is not None and preview.text and given == preview.text:
        kind, shown, shown_lang = "model", given, lang
    elif given:
        kind, shown, shown_lang = ("edited" if preview is not None and preview.text else "operator"), given, lang
    else:
        kind, shown, shown_lang = "none", text, "tr"
    masked_tr, masked_count, _ = mask_labels(text)
    return {
        "text_tr": masked_tr,
        "masked_count": masked_count,
        "text": mask_labels(shown)[0],
        "lang": shown_lang,
        "translation": kind,
        "translator": preview.author if kind in {"model", "edited"} and preview is not None else None,
        "by": OPERATOR,
    }


@request_routes.post("/api/console/requests/{code}/reply")
async def send_reply(request: Request, code: str, body: ReplyBody) -> Any:
    desk = request_desk(request.app)
    text, problem = usable_text(body.text_tr)
    if text is None:
        return port_problem(400, "bad_request", problem or "")
    async with desk.sending:
        row = await _waiting(desk, code)
        if isinstance(row, JSONResponse):
            return row
        preview = desk.previews.get(row["code"])
        if row["lang"] != "tr" and (preview is None or preview[0] != digest(text)):
            return port_problem(409, "preview_required", PREVIEW_FIRST)
        reply = reply_record(row, text, body.text_translated, preview[1] if preview else None)
        reply["answered_at"] = desk.store.now().isoformat()
        try:
            reply["ledger_entry_id"] = await asyncio.to_thread(ledger_reply, desk.ledger, row, reply, Operator().label)
            answered = await asyncio.to_thread(desk.store.answer, row["code"], reply)
        except (OSError, sqlite3.Error) as exc:
            log.error("operator reply not recorded (%s)", type(exc).__name__)
            return port_problem(503, "not_recorded", "Yanıt deftere yazılamadı; vatandaşa gönderilmedi.")
        desk.previews.pop(row["code"], None)
    return {**operator_view(answered or row), "message": "Yanıt gönderildi; vatandaşın kartında görünecek."}
