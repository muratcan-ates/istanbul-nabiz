"""A local, explicitly exemplary library seat booking store."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import hmac
import os
import pathlib
import re
import secrets
import sqlite3
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ibb_mcp.text import fold_tr
from nabiz.console import culture_api
from nabiz.console.accounts import ConsentRequired
from nabiz.console.cards import display_text
from nabiz.console.citizen_requests import CODE_ALPHABET, new_code, normal_code
from nabiz.console.wiring import ledger_path
from nexus_core.signals import Clock, as_utc, system_clock
from nexus_core.stats import ISTANBUL

# These are design parameters for the example, not measured library capacity or demand.
TTL_DAYS = 30
WINDOW_DAYS = 7
SLOT_MINUTES = 120
MIN_SLOT_MINUTES = 60
MAX_ACTIVE = 2
PER_HOUR = 6
PATH_ENV = "NABIZ_BOOKING_DB_PATH"
NOTICE = "Örnek: İBB kütüphane randevu sistemine bağlı değildir."
ROOM_NOTE = (
    "Salon planı ve kapasite örnektir; kütüphanenin gerçek doluluğunu göstermez. "
    "Dolu koltuklar yalnız Nabız'da alınan örnek randevulardır."
)
CONSENT_TEXT = (
    "Kütüphane, gün, saat ve koltuk seçimimin, bu cihazın ya da örnek hesabımın kodunun özetiyle birlikte "
    "Nabız sunucusunda en çok 30 gün saklanmasını kabul ediyorum. Ad, telefon ve TC kimlik istenmez; "
    "iptal ettiğimde kayıt hemen silinir."
)
CONSENT_VERSION = "2026-09-27"


@dataclass(frozen=True)
class Room:
    name: str
    rows: str
    seats_per_row: int
    aisle_after: int
    accessible: tuple[str, ...]
    capacity: int


SAMPLE_ROOM = Room("Çalışma salonu (örnek)", "ABCDEF", 6, 3, ("A1", "A2"), 36)


@dataclass(frozen=True)
class Library:
    key: str
    name: str
    district: str
    days: frozenset[int]
    hours: tuple[dt.time, dt.time] | Literal["always"]
    hours_text: str
    days_text: str


@dataclass(frozen=True)
class Slot:
    start: int
    end: int


@dataclass(frozen=True)
class DayPlan:
    date: str
    weekday: int
    open: bool
    reason: Literal["closed", "no_slots_left"] | None
    slots: tuple[dict[str, int | bool], ...]


class NotOffered(ValueError):
    """The recorded schedule does not offer this date or time."""


class BadSeat(ValueError):
    """The seat is outside the example room plan."""


class SeatTaken(ValueError):
    """Another booking already holds this seat."""


class SlotHeld(ValueError):
    """This owner already has a booking at the same date and time."""


class ActiveLimit(ValueError):
    """The owner already holds the maximum number of upcoming bookings."""


def seat_ids(room: Room = SAMPLE_ROOM) -> tuple[str, ...]:
    return tuple(f"{row}{number}" for row in room.rows for number in range(1, room.seats_per_row + 1))


def library_key(district: str, name: str) -> str:
    folded = fold_tr(f"{district} {name}").lower()
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:80].rstrip("-")


def bookable_libraries(directory: pathlib.Path | None = None) -> dict[str, Library]:
    source = pathlib.Path(directory) if directory is not None else pathlib.Path(culture_api.CULTURE_DIR)
    venues, _ = culture_api.load_venues(source)
    result: dict[str, Library] = {}
    for venue in venues:
        if venue.kind != "library" or not venue.district:
            continue
        days = culture_api.parse_days(venue.days_text)
        hours = culture_api.parse_hours(venue.hours_text) or culture_api.parse_hours(venue.days_text)
        if hours == "always":
            days = frozenset(range(7))
        if days is None or hours is None or not venue.hours_text or not venue.days_text:
            continue
        district = culture_api.district_name(venue.district)
        if not district:
            continue
        key = library_key(district, display_text(venue.name))
        result[key] = Library(
            key=key,
            name=display_text(venue.name),
            district=display_text(district),
            days=days,
            hours=hours,
            hours_text=display_text(venue.hours_text),
            days_text=display_text(venue.days_text),
        )
    return result


def _minutes(value: dt.time) -> int:
    return value.hour * 60 + value.minute


def slots_for(hours: tuple[dt.time, dt.time] | Literal["always"]) -> tuple[Slot, ...]:
    if hours == "always":
        opening, closing = 0, 1440
    else:
        opening, closing = (_minutes(value) for value in hours)
    slots: list[Slot] = []
    cursor = opening
    while closing - cursor >= MIN_SLOT_MINUTES:
        end = min(cursor + SLOT_MINUTES, closing)
        slots.append(Slot(cursor, end))
        cursor = end
    return tuple(slots)


def _local(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=ISTANBUL) if value.tzinfo is None else value.astimezone(ISTANBUL)


def day_plan(library: Library, now: dt.datetime) -> list[DayPlan]:
    local = _local(now)
    today = local.date()
    plan: list[DayPlan] = []
    for offset in range(WINDOW_DAYS):
        date = today + dt.timedelta(days=offset)
        if date.weekday() not in library.days:
            plan.append(DayPlan(date.isoformat(), date.weekday(), False, "closed", ()))
            continue
        is_today = offset == 0
        now_minute = local.hour * 60 + local.minute
        slots = tuple(
            {"start": slot.start, "end": slot.end, "bookable": not is_today or slot.start > now_minute}
            for slot in slots_for(library.hours)
        )
        has_bookable = any(slot["bookable"] for slot in slots)
        plan.append(
            DayPlan(
                date.isoformat(), date.weekday(), True, None if has_bookable else "no_slots_left", slots
            )
        )
    return plan


def check_choice(library: Library, day: str, start: int, now: dt.datetime) -> Slot:
    try:
        selected = dt.date.fromisoformat(day)
    except (TypeError, ValueError) as exc:
        raise NotOffered from exc
    local = _local(now)
    if selected.isoformat() != day or not local.date() <= selected < local.date() + dt.timedelta(days=WINDOW_DAYS):
        raise NotOffered
    if selected.weekday() not in library.days:
        raise NotOffered
    if not isinstance(start, int) or not 0 <= start < 1440:
        raise NotOffered
    slot = next((item for item in slots_for(library.hours) if item.start == start), None)
    if slot is None or (selected == local.date() and start <= local.hour * 60 + local.minute):
        raise NotOffered
    return slot


def booking_path(env: Mapping[str, str] | None = None) -> pathlib.Path:
    raw = (os.environ if env is None else env).get(PATH_ENV, "").strip()
    return pathlib.Path(raw) if raw else ledger_path(env).with_name("library_bookings.db")


def _row_is_future(row: sqlite3.Row, now_local: dt.datetime) -> bool:
    day = dt.date.fromisoformat(row["day"])
    end = row["end_min"]
    if day > now_local.date():
        return True
    if day < now_local.date():
        return False
    return end > now_local.hour * 60 + now_local.minute


class BookingStore:
    """SQLite store for example bookings; raw owner credentials never enter this database."""

    def __init__(self, path: str | pathlib.Path | None = None, *, clock: Clock = system_clock) -> None:
        self.path = pathlib.Path(path) if path is not None else booking_path()
        self._clock = clock
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS library_bookings (
                    code TEXT PRIMARY KEY, library_key TEXT NOT NULL, day TEXT NOT NULL,
                    start_min INTEGER NOT NULL, end_min INTEGER NOT NULL, seat TEXT NOT NULL,
                    holder TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                    consent_version TEXT NOT NULL,
                    UNIQUE (library_key, day, start_min, seat),
                    UNIQUE (holder, day, start_min)
                );
                CREATE INDEX IF NOT EXISTS library_bookings_expiry ON library_bookings (expires_at);
                CREATE INDEX IF NOT EXISTS library_bookings_holder ON library_bookings (holder);
                CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                """
            )
        self.purge()

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def now(self) -> dt.datetime:
        return as_utc(self._clock())

    def purge(self) -> int:
        with self._lock, self._connect() as connection:
            return connection.execute(
                "DELETE FROM library_bookings WHERE expires_at <= ?", (self.now().isoformat(),)
            ).rowcount

    def salt(self) -> bytes:
        self.purge()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT value FROM meta WHERE name = 'holder_salt'").fetchone()
            if row is None:
                value = secrets.token_hex(32)
                connection.execute("INSERT INTO meta (name, value) VALUES ('holder_salt', ?)", (value,))
            else:
                value = row[0]
            connection.commit()
        return bytes.fromhex(value)

    def holder_of(self, kind: Literal["device", "account"], raw: str) -> str:
        digest = hmac.new(self.salt(), f"{kind}:{raw}".encode(), hashlib.sha256).hexdigest()
        return digest[:32]

    def create(
        self, library: Library, day: str, start: int, seat: str, holder: str, consent: bool
    ) -> dict[str, Any]:
        if consent is not True:
            raise ConsentRequired
        slot = check_choice(library, day, start, self.now())
        if seat not in seat_ids():
            raise BadSeat
        self.purge()
        now = self.now()
        local_now = now.astimezone(ISTANBUL)
        expires = now + dt.timedelta(days=TTL_DAYS)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM library_bookings WHERE holder = ?", (holder,)
            ).fetchall()
            active = [row for row in existing if _row_is_future(row, local_now)]
            if len(active) >= MAX_ACTIVE:
                connection.rollback()
                raise ActiveLimit
            if any(row["day"] == day and row["start_min"] == start for row in active):
                connection.rollback()
                raise SlotHeld
            if connection.execute(
                "SELECT 1 FROM library_bookings WHERE library_key = ? AND day = ? AND start_min = ? AND seat = ?",
                (library.key, day, start, seat),
            ).fetchone():
                connection.rollback()
                raise SeatTaken
            code = new_code()
            for _ in range(8):
                if connection.execute("SELECT 1 FROM library_bookings WHERE code = ?", (code,)).fetchone() is None:
                    break
                code = new_code()
            try:
                connection.execute(
                    "INSERT INTO library_bookings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        code, library.key, day, start, slot.end, seat, holder, now.isoformat(), expires.isoformat(),
                        CONSENT_VERSION,
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise SeatTaken from exc
        return {
            "code": code, "library_key": library.key, "day": day, "start": start, "end": slot.end,
            "seat": seat, "expires_at": expires.isoformat(),
        }

    def taken(self, key: str, day: str, start: int) -> set[str]:
        self.purge()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT seat FROM library_bookings WHERE library_key = ? AND day = ? AND start_min = ?",
                (key, day, start),
            ).fetchall()
        return {row[0] for row in rows}

    def holding(self, holder: str, key: str, day: str, start: int) -> dict[str, Any] | None:
        self.purge()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT seat, code FROM library_bookings WHERE holder = ? AND library_key = ? AND day = ? AND start_min = ?",
                (holder, key, day, start),
            ).fetchone()
        return {"seat": row["seat"], "code": row["code"]} if row else None

    def mine(self, holder: str) -> list[dict[str, Any]]:
        self.purge()
        now_local = self.now().astimezone(ISTANBUL)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT code, library_key, day, start_min, end_min, seat FROM library_bookings "
                "WHERE holder = ? ORDER BY day, start_min",
                (holder,),
            ).fetchall()
        return [
            {
                "code": row["code"], "library_key": row["library_key"], "day": row["day"],
                "start": row["start_min"], "end": row["end_min"], "seat": row["seat"],
            }
            for row in rows if _row_is_future(row, now_local)
        ]

    def cancel(self, code: str, holder: str) -> Literal["ok", "not_found", "not_yours"]:
        self.purge()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT holder FROM library_bookings WHERE code = ?", (code,)).fetchone()
            if row is None:
                connection.rollback()
                return "not_found"
            if row["holder"] != holder:
                connection.rollback()
                return "not_yours"
            connection.execute("DELETE FROM library_bookings WHERE code = ?", (code,))
            connection.commit()
        return "ok"

    def delete_holder(self, holder: str) -> int:
        self.purge()
        with self._lock, self._connect() as connection:
            return connection.execute("DELETE FROM library_bookings WHERE holder = ?", (holder,)).rowcount


__all__ = [
    "TTL_DAYS", "WINDOW_DAYS", "SLOT_MINUTES", "MIN_SLOT_MINUTES", "MAX_ACTIVE", "PER_HOUR", "PATH_ENV",
    "NOTICE", "ROOM_NOTE", "CONSENT_TEXT", "CONSENT_VERSION", "Room", "SAMPLE_ROOM", "Library", "Slot",
    "DayPlan", "NotOffered", "BadSeat", "SeatTaken", "SlotHeld", "ActiveLimit", "ConsentRequired",
    "seat_ids", "library_key", "bookable_libraries", "slots_for", "day_plan", "check_choice", "booking_path",
    "BookingStore", "CODE_ALPHABET", "normal_code",
]
