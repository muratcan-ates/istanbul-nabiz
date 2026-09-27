"""Accessible support request drafts and their short-lived, separately stored records."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import pathlib
import sqlite3
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from zoneinfo import ZoneInfo

from ibb_mcp.text import fold_tr
from nabiz.console.citizen_requests import new_code, normal_code
from nabiz.console.pii_guard import mask_labels
from nabiz.console.wiring import ledger_path
from nexus_core.signals import Clock, as_utc, system_clock

PATH_ENV = "NABIZ_ESCORT_DB_PATH"
TTL_DAYS = 30
NEEDS = ("wheelchair", "walking_difficulty", "low_vision", "hearing", "cognitive", "other")
ASSISTANCE = ("meet_at_entrance", "guide_inside_station", "boarding_alighting", "transfer", "step_free_route_check")
WINDOWS_MIN = (30, 60, 120)
RETURN_KINDS = ("none", "same_day", "later")
STATUSES = ("received", "seen", "referred_official", "closed", "cancelled")
WAITING_ON = {
    "received": "operator",
    "seen": "operator",
    "referred_official": "citizen_calls_153",
    "closed": "none",
    "cancelled": "none",
}
OPERATOR_MOVES = {
    "received": ("seen",),
    "seen": ("referred_official", "closed"),
    "referred_official": ("closed",),
}
CITIZEN_MOVES = {"received": ("cancelled",), "seen": ("cancelled",), "referred_official": ("cancelled",)}
SIMULATED_NOTE = "Prototip: operatör rolü simüledir; resmî İBB hizmeti değildir."
DISCLAIMER = "Resmî İBB hizmeti değildir."
_SCHEMA = """
CREATE TABLE IF NOT EXISTS escort_requests (
    code TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
    status TEXT NOT NULL, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS escort_requests_expiry ON escort_requests (expires_at);
"""


@dataclass(frozen=True, slots=True)
class EscortDraft:
    need: str
    assistance: tuple[str, ...]
    date: dt.date
    time: str
    window_min: int
    meet_station: str
    to_station: str
    return_kind: str
    return_time: str | None
    companion: bool
    note: str


class TransitionError(ValueError):
    """The requested actor cannot make this status transition."""


def escort_path(env: Mapping[str, str] | None = None) -> pathlib.Path:
    raw = (os.environ if env is None else env).get(PATH_ENV, "").strip()
    return pathlib.Path(raw) if raw else ledger_path(env).with_name("escort_requests.db")


def _parse_time(value: Any) -> dt.time | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.time.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.strftime("%H:%M") == value else None


def _need_value(raw: Any) -> tuple[str | None, str | None]:
    return (raw, None) if raw in NEEDS else (None, "Bir ihtiyaç türü seçin.")


def _assistance_value(raw: Any) -> tuple[tuple[str, ...] | None, str | None]:
    if not isinstance(raw, list | tuple) or not 1 <= len(raw) <= len(ASSISTANCE) or any(item not in ASSISTANCE for item in raw):
        return None, "En az bir destek seçin."
    return tuple(raw), None


def _date_value(raw: Any, today: dt.date) -> tuple[dt.date | None, str | None]:
    try:
        requested_date = dt.date.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        requested_date = None
    if requested_date is None or requested_date.isoformat() != raw:
        return None, "Geçerli bir tarih seçin."
    if not today <= requested_date <= today + dt.timedelta(days=30):
        return None, "Tarih bugün ile 30 gün sonrası arasında olmalı."
    return requested_date, None


def _start_time_value(raw: Any) -> tuple[str | None, dt.time | None, str | None]:
    parsed = _parse_time(raw)
    if parsed is None or not dt.time(5, 0) <= parsed <= dt.time(23, 59):
        return None, None, "Saat 05:00 ile 23:59 arasında olmalı."
    return raw, parsed, None


def _window_value(raw: Any) -> tuple[int | None, str | None]:
    try:
        window = int(raw)
    except (TypeError, ValueError):
        return None, "Bir zaman aralığı seçin."
    if window not in WINDOWS_MIN or isinstance(raw, bool):
        return None, "Bir zaman aralığı seçin."
    return window, None


def _station_pair(meet_raw: Any, to_raw: Any, stations: tuple[str, ...] | list[str]) -> tuple[str | None, str | None, str | None]:
    station_map = {fold_tr(name): name for name in stations}
    meet = station_map.get(fold_tr(meet_raw))
    destination = station_map.get(fold_tr(to_raw))
    if meet is None:
        return None, None, "Listeden bir buluşma istasyonu seçin."
    if destination is None:
        return None, None, "Listeden bir varış istasyonu seçin."
    if fold_tr(meet) == fold_tr(destination):
        return None, None, "Buluşma ve varış istasyonları farklı olmalı."
    return meet, destination, None


def _return_value(raw_kind: Any, raw_time: Any, trip_time: dt.time) -> tuple[str | None, str | None, str | None]:
    if raw_kind not in RETURN_KINDS:
        return None, None, "Dönüş seçeneğini belirleyin."
    return_time = None
    if raw_kind == "same_day":
        return_time = raw_time
        parsed_return = _parse_time(return_time)
        if parsed_return is None or parsed_return <= trip_time:
            return None, None, "Dönüş saati yolculuk saatinden sonra olmalı."
    return raw_kind, return_time, None


def _note_value(raw: Any) -> tuple[str | None, str | None]:
    if not isinstance(raw, str) or len(raw) > 200:
        return None, "Not en fazla 200 karakter olabilir."
    return raw.strip(), None


def validate(body: Mapping[str, Any], stations: tuple[str, ...] | list[str], today: dt.date) -> EscortDraft | str:
    """Validate a submitted file without I/O, returning one Turkish field error at a time."""
    need, need_error = _need_value(body.get("need"))
    assistance, assistance_error = _assistance_value(body.get("assistance"))
    requested_date, date_error = _date_value(body.get("date"), today)
    raw_time, trip_time, time_error = _start_time_value(body.get("time"))
    window, window_error = _window_value(body.get("window_min"))
    meet, destination, station_error = _station_pair(body.get("meet_station", ""), body.get("to_station", ""), stations)
    return_kind, return_time, return_error = _return_value(
        body.get("return_kind"), body.get("return_time"), trip_time or dt.time()
    )
    companion = body.get("companion")
    companion_error = None if isinstance(companion, bool) else "Refakatçiniz olup olmadığını belirtin."
    note, note_error = _note_value(body.get("note", ""))
    for error in (
        need_error,
        assistance_error,
        date_error,
        time_error,
        window_error,
        station_error,
        return_error,
        companion_error,
        note_error,
    ):
        if error:
            return error
    assert need is not None and assistance is not None and requested_date is not None and raw_time is not None
    assert window is not None and meet is not None and destination is not None and return_kind is not None and note is not None
    return EscortDraft(
        need, assistance, requested_date, raw_time, window, meet, destination, return_kind, return_time, companion, note
    )


class EscortStore:
    """SQLite store which holds masked notes and deletes records by both time limits."""

    def __init__(self, path: str | pathlib.Path | None = None, *, clock: Clock = system_clock) -> None:
        self.path = pathlib.Path(path) if path is not None else escort_path()
        self._clock = clock
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA secure_delete = ON")
            conn.executescript(_SCHEMA)
        self.purge()

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA secure_delete = ON")
        try:
            yield conn
        finally:
            conn.close()

    def now(self) -> dt.datetime:
        return as_utc(self._clock())

    def purge(self) -> int:
        with self._lock, self._connect() as conn:
            return conn.execute("DELETE FROM escort_requests WHERE expires_at <= ?", (self.now().isoformat(),)).rowcount

    def create(self, draft: EscortDraft) -> dict[str, Any]:
        masked, count, _ = mask_labels(draft.note)
        self.purge()
        data = {
            "need": draft.need,
            "assistance": list(draft.assistance),
            "date": draft.date.isoformat(),
            "time": draft.time,
            "window_min": draft.window_min,
            "meet_station": draft.meet_station,
            "to_station": draft.to_station,
            "return_kind": draft.return_kind,
            "return_time": draft.return_time,
            "companion": draft.companion,
            "note_masked": masked,
            "masked_count": count,
            "history": [{"status": "received", "at": self.now().isoformat(), "by": "system"}],
        }
        now = self.now()
        local_expiry = dt.datetime.combine(
            draft.date + dt.timedelta(days=1), dt.time.min, tzinfo=ZoneInfo("Europe/Istanbul")
        ).astimezone(dt.UTC)
        expiry = min(now + dt.timedelta(days=TTL_DAYS), local_expiry)
        with self._lock, self._connect() as conn:
            for _ in range(8):
                code = new_code()
                if conn.execute("SELECT 1 FROM escort_requests WHERE code = ?", (code,)).fetchone() is None:
                    break
            conn.execute(
                "INSERT INTO escort_requests VALUES (?, ?, ?, ?, ?)",
                (code, now.isoformat(), expiry.isoformat(), "received", json.dumps(data, ensure_ascii=False)),
            )
        return self.get(code) or {}

    def get(self, code: str) -> dict[str, Any] | None:
        code = normal_code(code) or ""
        if not code:
            return None
        self.purge()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM escort_requests WHERE code = ? AND expires_at > ?", (code, self.now().isoformat())
            ).fetchone()
        return _row(row) if row else None

    def items(self, limit: int = 100) -> list[dict[str, Any]]:
        self.purge()
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM escort_requests WHERE expires_at > ?", (self.now().isoformat(),)).fetchall()
        items = [_row(row) for row in rows]
        return sorted(
            items, key=lambda item: (WAITING_ON[item["status"]] != "operator", item["data"]["date"], item["created_at"])
        )[:limit]

    def move(
        self, code: str, actor: Literal["citizen", "operator"], to: str, *, note: str | None = None, agency_id: str | None = None
    ) -> dict[str, Any] | None:
        self.purge()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM escort_requests WHERE code = ? AND expires_at > ?", (code, self.now().isoformat())
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return None
            data = json.loads(row["data"])
            allowed = OPERATOR_MOVES if actor == "operator" else CITIZEN_MOVES
            if to not in allowed.get(row["status"], ()):
                conn.execute("ROLLBACK")
                raise TransitionError("Bu durumdan bu geçiş yapılamaz.")
            if to == "referred_official" and not agency_id:
                conn.execute("ROLLBACK")
                raise ValueError("Yönlendirme için bir kurum seçin.")
            if to == "closed":
                if not note or not 5 <= len(note.strip()) <= 200:
                    conn.execute("ROLLBACK")
                    raise ValueError("Kapatma notu 5 ile 200 karakter arasında olmalı.")
                note_masked, _, _ = mask_labels(note.strip())
            else:
                note_masked = None
            at = self.now().isoformat()
            history: dict[str, Any] = {"status": to, "at": at, "by": actor}
            if note_masked is not None:
                history["note_masked"] = note_masked
            if agency_id:
                history["agency_id"] = agency_id
                data["agency_id"] = agency_id
            data["history"].append(history)
            conn.execute(
                "UPDATE escort_requests SET status = ?, data = ? WHERE code = ?", (to, json.dumps(data, ensure_ascii=False), code)
            )
            conn.execute("COMMIT")
        return self.get(code)


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "code": row["code"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "status": row["status"],
        "data": json.loads(row["data"]),
    }
