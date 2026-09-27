"""A private, expiring timeline for citizen reports and their confirmation."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import pathlib
import sqlite3
import threading
from collections.abc import Iterator, Mapping
from typing import Any

from nabiz.console.agency_router import load_agencies
from nabiz.console.pii_guard import mask_labels
from nabiz.console.wiring import ledger_path
from nexus_core.signals import Clock, as_utc, system_clock

PATH_ENV = "NABIZ_REPORT_TIMELINE_DB_PATH"
TTL_DAYS = 30
STAGES = ("recorded", "reviewing", "info_needed", "referred", "resolution_reported", "confirmed")
WAITING_ON = {
    "recorded": "operator", "reviewing": "operator", "info_needed": "citizen", "referred": "agency",
    "resolution_reported": "citizen", "reopened": "operator", "confirmed": "none",
}
OPERATOR_MOVES = {
    "recorded": ("reviewing",),
    "reviewing": ("info_needed", "referred", "resolution_reported"),
    "info_needed": ("reviewing",),
    "referred": ("reviewing", "resolution_reported"),
    "reopened": ("reviewing",),
}
CITIZEN_MOVES = {
    "resolution_reported": {"fixed": "confirmed", "ongoing": "reopened"},
    "info_needed": {"info": "reviewing"},
}
_KIND_TEXT = {"not_working": "asansör kapalıydı", "data_wrong": "kayıt yanlış görünüyor"}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS report_timeline (
    code TEXT PRIMARY KEY, signal_id TEXT NOT NULL, station TEXT, kind TEXT, stage TEXT NOT NULL,
    reopen_count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS report_timeline_expiry ON report_timeline (expires_at);
"""


class TransitionError(Exception):
    """A requested transition is not allowed from the current stage."""


def timeline_path(env: Mapping[str, str] | None = None) -> pathlib.Path:
    values = os.environ if env is None else env
    raw = values.get(PATH_ENV, "").strip()
    return pathlib.Path(raw) if raw else ledger_path(env).with_name("report_timeline.db")


def next_stage(current: str, actor: str, action: str) -> str | None:
    if actor == "operator" and action in OPERATOR_MOVES.get(current, ()):
        return action
    return CITIZEN_MOVES.get(current, {}).get(action) if actor == "citizen" else None


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return {**dict(row), "data": json.loads(row["data"])}


class TimelineStore:
    """One row per report code; reads and writes purge the 30-day table first."""

    def __init__(self, path: str | pathlib.Path | None = None, *, clock: Clock = system_clock) -> None:
        self.path = pathlib.Path(path) if path is not None else timeline_path()
        self._clock = clock
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
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
            return conn.execute("DELETE FROM report_timeline WHERE expires_at <= ?", (self.now().isoformat(),)).rowcount

    def get(self, code: str) -> dict[str, Any] | None:
        self.purge()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM report_timeline WHERE code = ?", (code,)).fetchone()
        return _row(row) if row else None

    def ensure(self, code: str, signal_id: str, station: str, kind: str, received_at: dt.datetime) -> dict[str, Any]:
        self.purge()
        at = as_utc(received_at)
        expires = self.now() + dt.timedelta(days=TTL_DAYS)
        history = [{"stage": "recorded", "at": at.isoformat(), "by": "system"}]
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM report_timeline WHERE code = ?", (code,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO report_timeline VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
                    (code, signal_id, station, kind, "recorded", at.isoformat(), at.isoformat(), expires.isoformat(),
                     json.dumps({"history": history}, ensure_ascii=False)),
                )
                row = conn.execute("SELECT * FROM report_timeline WHERE code = ?", (code,)).fetchone()
            conn.execute("COMMIT")
        return _row(row)

    @staticmethod
    def virtual_view(code: str, signal_id: str, station: str, kind: str, received_at: dt.datetime) -> dict[str, Any]:
        at = as_utc(received_at)
        stamp = at.isoformat()
        return {
            "code": code, "signal_id": signal_id, "station": station, "kind": kind, "stage": "recorded",
            "reopen_count": 0, "created_at": stamp, "updated_at": stamp,
            "expires_at": (at + dt.timedelta(days=TTL_DAYS)).isoformat(),
            "data": {"history": [{"stage": "recorded", "at": stamp, "by": "system"}]},
        }

    def apply(
        self, code: str, actor: str, action: str, *, to: str | None = None, text: str | None = None,
        agency_id: str | None = None,
    ) -> dict[str, Any]:
        self.purge()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM report_timeline WHERE code = ?", (code,)).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise LookupError(code)
            current = row["stage"]
            target = next_stage(current, actor, to or action)
            if target is None:
                conn.execute("ROLLBACK")
                raise TransitionError(current)
            now = self.now()
            record = self._event(actor, action, target, text, agency_id, now)
            data = json.loads(row["data"])
            data["history"].append(record)
            reopened = row["reopen_count"] + int(target == "reopened")
            conn.execute(
                "UPDATE report_timeline SET stage = ?, reopen_count = ?, updated_at = ?, expires_at = ?, data = ? WHERE code = ?",
                (target, reopened, now.isoformat(), (now + dt.timedelta(days=TTL_DAYS)).isoformat(),
                 json.dumps(data, ensure_ascii=False), code),
            )
            updated = conn.execute("SELECT * FROM report_timeline WHERE code = ?", (code,)).fetchone()
            conn.execute("COMMIT")
        return _row(updated)

    @staticmethod
    def _event(
        actor: str, action: str, target: str, text: str | None, agency_id: str | None, at: dt.datetime,
    ) -> dict[str, Any]:
        required = (actor == "operator" and target in {"info_needed", "resolution_reported"}) or (
            actor == "citizen" and action in {"ongoing", "info"}
        )
        minimum, maximum = (5, 200) if actor == "operator" else (5, 500)
        clean = (text or "").strip()
        if required and not minimum <= len(clean) <= maximum:
            raise ValueError("note_required")
        event: dict[str, Any] = {"stage": target, "at": as_utc(at).isoformat(), "by": actor}
        if clean and (actor == "operator" or action in {"ongoing", "info"}):
            masked, count, _ = mask_labels(clean)
            event.update(note_masked=masked, masked_count=count)
        if target == "referred":
            agencies = load_agencies()["agencies"]
            known = next((item for item in agencies if item.get("id") == agency_id), None)
            if known is None:
                raise ValueError("agency_required")
            event["agency_id"] = known["id"]
        elif agency_id is not None:
            raise ValueError("agency_not_allowed")
        return event


def timeline_view(row: Mapping[str, Any], outcome_status: str, now: dt.datetime, agencies: Mapping[str, Any]) -> dict[str, Any]:
    history = row["data"]["history"]
    latest = {event["stage"]: event for event in history}
    stage = row["stage"]
    current = "reviewing" if stage == "reopened" else stage
    steps = [
        {"stage": item, "reached": item in latest or (item == "reviewing" and stage == "reopened"),
         "at": latest.get(item, {}).get("at"), "current": item == current}
        for item in STAGES
    ]
    agency_id = latest.get("referred", {}).get("agency_id")
    agency = next((item for item in agencies.get("agencies", []) if item.get("id") == agency_id), None)
    note_event = latest.get(stage) if stage in {"info_needed", "resolution_reported"} else None
    confirmation = "confirmed" if stage == "confirmed" else None
    if stage == "resolution_reported":
        at = dt.datetime.fromisoformat(latest[stage]["at"])
        confirmation = "none_7_days" if as_utc(now) - as_utc(at) >= dt.timedelta(days=7) else "awaiting"
    call_agency = next((item for item in agencies.get("agencies", []) if item.get("id") == "cozum_153"), None)
    return {
        "code": row["code"], "station": row["station"], "kind": row["kind"],
        "kind_text": _KIND_TEXT.get(row["kind"], "asansör bildirimi"), "stage": stage,
        "waiting_on": WAITING_ON[stage], "reopen_count": row["reopen_count"], "steps": steps,
        "history": history, "agency": agency, "note": (note_event or {}).get("note_masked"),
        "confirmation": confirmation, "publication": outcome_status,
        "official": {"available": False, "call": agencies.get("call", "153"), "agency": call_agency},
    }
