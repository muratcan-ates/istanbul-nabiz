"""HTTP contract for example library bookings."""

from __future__ import annotations

import datetime as dt
import os
import re
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from nabiz.console import culture_api
from nabiz.console.accounts import ConsentRequired
from nabiz.console.accounts_api import ACCOUNT_HEADER, DEVICE_HEADER, current_account
from nabiz.console.booking import (
    CONSENT_TEXT,
    CONSENT_VERSION,
    MAX_ACTIVE,
    NOTICE,
    PER_HOUR,
    ROOM_NOTE,
    SAMPLE_ROOM,
    SLOT_MINUTES,
    TTL_DAYS,
    ActiveLimit,
    BadSeat,
    BookingStore,
    NotOffered,
    SeatTaken,
    SlotHeld,
    bookable_libraries,
    check_choice,
    day_plan,
)
from nabiz.console.cards import display_text
from nabiz.console.citizen_requests import HourlyLimit, normal_code
from nabiz.console.operator import port_problem


class NoStoreRoute(APIRoute):
    """Mark successes and framework validation errors as private responses."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def add_header(request: Request) -> Response:
            response = await original(request)
            response.headers["Cache-Control"] = "no-store"
            return response

        return add_header


booking_routes = APIRouter(route_class=NoStoreRoute)
DEVICE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


class BookingBody(BaseModel):
    library: str = Field(max_length=100)
    day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    start: int = Field(ge=0, le=1439)
    seat: str = Field(max_length=3)
    consent: bool = False


def booking_store(app: Any) -> BookingStore:
    state = app.state
    if getattr(state, "booking_store", None) is None:
        state.booking_store = BookingStore()
    return state.booking_store


def booking_holder(request: Request) -> tuple[str, str] | None:
    token = request.headers.get(ACCOUNT_HEADER)
    account = current_account(request) if token else None
    if account is not None:
        return "account", account.id
    device = request.headers.get(DEVICE_HEADER, "")
    if DEVICE_PATTERN.fullmatch(device):
        return "device", device
    return None


def _per_hour() -> int:
    raw = os.environ.get("NABIZ_BOOKING_PER_HOUR", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else PER_HOUR


def _limit(request: Request) -> HourlyLimit:
    state = request.app.state
    if getattr(state, "booking_limit", None) is None:
        state.booking_limit = HourlyLimit(_per_hour())
    return state.booking_limit


def _libraries() -> dict[str, Any]:
    return bookable_libraries()


def _library_payload(library: Any) -> dict[str, str]:
    return {"key": library.key, "name": library.name, "district": library.district}


def _known_library(key: str) -> Any | None:
    return _libraries().get(key)


def _problem(status: int, kind: str, message: str, *, limit: int | None = None) -> Response:
    if limit is not None:
        return JSONResponse(
            status_code=status,
            content={"error": kind, "message": display_text(message), "limit": limit},
            headers={"Cache-Control": "no-store"},
        )
    response = port_problem(status, kind, display_text(message))
    response.headers["Cache-Control"] = "no-store"
    return response


def _booking_problem(error: Exception) -> Response:
    if isinstance(error, ConsentRequired):
        return _problem(400, "consent_required", "Randevu için onay kutusunu işaretleyin.")
    if isinstance(error, NotOffered):
        return _problem(422, "not_offered", "Seçtiğiniz gün ya da saat sunulmuyor.")
    if isinstance(error, BadSeat):
        return _problem(422, "bad_seat", "Seçtiğiniz koltuk örnek salon planında yok.")
    if isinstance(error, SlotHeld):
        return _problem(409, "slot_held", "Bu saat aralığında zaten bir randevunuz var.")
    if isinstance(error, SeatTaken):
        return _problem(409, "seat_taken", "Bu koltuk az önce ayrıldı; başka bir koltuk seçin.")
    if isinstance(error, ActiveLimit):
        return _problem(409, "active_limit", "En çok 2 yaklaşan randevunuz olabilir; önce birini iptal edin.", limit=MAX_ACTIVE)
    return _problem(500, "booking_failed", "Randevu kaydedilemedi; lütfen daha sonra yeniden deneyin.")


def _provenance(metadata: dict[str, Any], now: dt.datetime) -> dict[str, Any]:
    observed = metadata.get("resource_last_modified")
    package_id = metadata.get("package_id")
    try:
        observed_at = dt.datetime.fromisoformat(str(observed).replace("Z", "+00:00")) if observed else None
    except ValueError:
        observed_at = None
    if observed_at is not None and observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=dt.UTC)
    return {
        "source": "ibb_open_data",
        "mode": "recorded",
        "observed_at": observed,
        "captured_at": metadata.get("captured_at"),
        "age_s": max(0, int((now - observed_at.astimezone(dt.UTC)).total_seconds())) if observed_at else None,
        "url": f"https://data.ibb.gov.tr/dataset/{package_id}" if package_id else None,
    }


@booking_routes.get("/api/booking/libraries")
async def booking_libraries() -> dict[str, Any]:
    values = _libraries()
    return {
        "example": True,
        "notice": display_text(NOTICE),
        "disclaimer": display_text(culture_api.DISCLAIMER),
        "libraries": [_library_payload(item) for item in values.values()],
    }


@booking_routes.get("/api/booking/libraries/{key}")
async def booking_library(key: str, request: Request) -> Any:
    library = _known_library(key)
    if library is None:
        return _problem(404, "unknown_library", "Bu kütüphane kayıtlarda bulunamadı.")
    store = booking_store(request.app)
    plan = day_plan(library, store.now())
    venues, metadata = culture_api.load_venues(culture_api.CULTURE_DIR)
    del venues
    return {
        "example": True,
        "notice": display_text(NOTICE),
        "disclaimer": display_text(culture_api.DISCLAIMER),
        "notes": [display_text(ROOM_NOTE), display_text(culture_api.NOTES[1])],
        "library": {
            **_library_payload(library),
            "hours_text": display_text(library.hours_text),
            "days_text": display_text(library.days_text),
        },
        "days": [
            {
                "date": item.date,
                "weekday": item.weekday,
                "open": item.open,
                "reason": item.reason,
                "slots": list(item.slots),
            }
            for item in plan
        ],
        "room": {
            "name": display_text(SAMPLE_ROOM.name),
            "rows": SAMPLE_ROOM.rows,
            "seats_per_row": SAMPLE_ROOM.seats_per_row,
            "aisle_after": SAMPLE_ROOM.aisle_after,
            "accessible": list(SAMPLE_ROOM.accessible),
            "capacity": SAMPLE_ROOM.capacity,
        },
        "limits": {"max_active": MAX_ACTIVE, "ttl_days": TTL_DAYS, "slot_minutes": SLOT_MINUTES},
        "consent": {"text": display_text(CONSENT_TEXT), "version": CONSENT_VERSION},
        "provenance": _provenance(metadata.get("library", {}), store.now()),
    }


@booking_routes.get("/api/booking/seats")
async def booking_seats(
    request: Request,
    library: str = Query(max_length=100),
    day: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    start: int = Query(ge=0, le=1439),
) -> Any:
    selected = _known_library(library)
    if selected is None:
        return _problem(404, "unknown_library", "Bu kütüphane kayıtlarda bulunamadı.")
    store = booking_store(request.app)
    try:
        slot = check_choice(selected, day, start, store.now())
    except NotOffered:
        return _problem(422, "not_offered", "Seçtiğiniz gün ya da saat sunulmuyor.")
    owner = booking_holder(request)
    held = store.holder_of(owner[0], owner[1]) if owner else None
    mine = store.holding(held, library, day, start) if held else None
    return {
        "library": library,
        "day": day,
        "start": start,
        "end": slot.end,
        "taken": sorted(store.taken(library, day, start)),
        "mine": mine,
    }


@booking_routes.post("/api/booking", status_code=201)
async def create_booking(request: Request, body: BookingBody) -> Any:
    owner = booking_holder(request)
    if owner is None:
        return _problem(400, "no_holder", "Bu tarayıcı randevu kodunu saklayamıyor; randevu alınamıyor.")
    if body.consent is not True:
        return _problem(400, "consent_required", "Randevu için onay kutusunu işaretleyin.")
    store = booking_store(request.app)
    holder = store.holder_of(owner[0], owner[1])
    if not _limit(request).allow(holder):
        return _problem(429, "too_many", "Bu saat içinde çok deneme oldu; biraz sonra tekrar deneyin.")
    library = _known_library(body.library)
    if library is None:
        return _problem(404, "unknown_library", "Bu kütüphane kayıtlarda bulunamadı.")
    try:
        saved = store.create(library, body.day, body.start, body.seat, holder, body.consent)
    except (ConsentRequired, NotOffered, BadSeat, SlotHeld, SeatTaken, ActiveLimit) as error:
        return _booking_problem(error)
    return {
        **saved,
        "library": _library_payload(library),
        "held_by": owner[0],
        "example": True,
        "notice": display_text(NOTICE),
    }


@booking_routes.get("/api/booking/mine")
async def my_bookings(request: Request) -> dict[str, Any]:
    owner = booking_holder(request)
    if owner is None:
        return {"bookings": [], "held_by": None}
    store = booking_store(request.app)
    holder = store.holder_of(owner[0], owner[1])
    libraries = _libraries()
    bookings = []
    for item in store.mine(holder):
        library = libraries.get(item["library_key"])
        if library is not None:
            bookings.append(
                {
                    "code": item["code"],
                    "library": _library_payload(library),
                    "day": item["day"],
                    "start": item["start"],
                    "end": item["end"],
                    "seat": item["seat"],
                }
            )
    return {"bookings": bookings, "held_by": owner[0]}


@booking_routes.delete("/api/booking/{code}")
async def cancel_booking(request: Request, code: str) -> Any:
    owner = booking_holder(request)
    if owner is None:
        return _problem(400, "no_holder", "Bu tarayıcı randevu kodunu saklayamıyor; randevu alınamıyor.")
    normalized = normal_code(code)
    if normalized is None:
        return _problem(404, "not_found", "Bu randevu bulunamadı.")
    store = booking_store(request.app)
    holder = store.holder_of(owner[0], owner[1])
    result = store.cancel(normalized, holder)
    if result == "not_found":
        return _problem(404, "not_found", "Bu randevu bulunamadı.")
    if result == "not_yours":
        return _problem(403, "not_yours", "Bu randevu size ait değil.")
    return {"cancelled": True, "code": normalized}
