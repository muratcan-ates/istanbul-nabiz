"""Private SQLite persistence for reasoned, reversible operator incident actions."""

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

from nabiz.console.pii_guard import mask_labels
from nabiz.console.wiring import ledger_path
from nexus_core.decisions import REASON_MAX
from nexus_core.ledger import Ledger
from nexus_core.signals import Clock, system_clock

PATH_ENV = "NABIZ_INCIDENTS_DB_PATH"
# This retention period matches citizen report cards; it is a design parameter, not a measurement.
TTL_DAYS = 30

_SCHEMA = """
CREATE TABLE IF NOT EXISTS incident_actions (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL, incident_id TEXT NOT NULL,
  data TEXT NOT NULL, reason TEXT NOT NULL, actor TEXT NOT NULL, ledger_entry INTEGER NOT NULL,
  undone_at TEXT, undo_reason TEXT, undo_ledger_entry INTEGER, expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS incident_actions_expiry ON incident_actions (expires_at);
CREATE TABLE IF NOT EXISTS incident_priority (
  incident_id TEXT PRIMARY KEY, level TEXT NOT NULL, reason TEXT NOT NULL, actor TEXT NOT NULL,
  at TEXT NOT NULL, suggested_level TEXT NOT NULL, ledger_entry INTEGER NOT NULL, expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS incident_priority_expiry ON incident_priority (expires_at);
CREATE TABLE IF NOT EXISTS incident_priority_history (
  id INTEGER PRIMARY KEY, incident_id TEXT NOT NULL, level TEXT NOT NULL, reason TEXT NOT NULL,
  actor TEXT NOT NULL, at TEXT NOT NULL, suggested_level TEXT NOT NULL, ledger_entry INTEGER NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS incident_priority_history_expiry ON incident_priority_history (expires_at);
"""

_LOCK = threading.RLock()


class AlreadyUndone(ValueError):
    """An action already has its append-only undo record."""


def incidents_path(env: Mapping[str, str] | None = None) -> pathlib.Path:
    source = os.environ if env is None else env
    raw = (source.get(PATH_ENV) or "").strip()
    return pathlib.Path(raw) if raw else ledger_path(env).with_name("incidents.db")


def clean_reason(reason: str) -> str:
    cleaned = reason.strip()
    if len(cleaned) < 5:
        raise ValueError("Gerekçe en az 5 karakter olmalıdır.")
    if len(cleaned) > REASON_MAX:
        raise ValueError("Gerekçe en fazla 280 karakter olabilir.")
    masked, count, _labels = mask_labels(cleaned)
    if count or masked != cleaned:
        raise ValueError("Gerekçede kişisel bilgi olamaz.")
    return cleaned


def _entry_id(entry: Any) -> int:
    return int(entry.id if hasattr(entry, "id") else entry)


@contextlib.contextmanager
def _connect(path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA secure_delete = ON")
    try:
        yield conn
    finally:
        conn.close()


def _now(clock: Clock) -> dt.datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("incident clock must return a timezone-aware datetime")
    return value.astimezone(dt.UTC)


def _purge(conn: sqlite3.Connection, clock: Clock) -> None:
    now = _now(clock).isoformat()
    for table in ("incident_actions", "incident_priority", "incident_priority_history"):
        conn.execute(f"DELETE FROM {table} WHERE expires_at <= ?", (now,))


def _begin(conn: sqlite3.Connection, clock: Clock) -> None:
    conn.execute("BEGIN IMMEDIATE")
    _purge(conn, clock)


def _expires(now: dt.datetime) -> str:
    return (now + dt.timedelta(days=TTL_DAYS)).isoformat()


def _action_row(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["data"] = json.loads(value["data"])
    return value


def _priority_row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


class IncidentStore:
    """Short-lived connections keep each read and write's expiry purge current."""

    def __init__(self, path: str | pathlib.Path | None = None, *, clock: Clock = system_clock) -> None:
        self.path = pathlib.Path(path) if path is not None else incidents_path()
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, _connect(self.path) as conn:
            conn.executescript(_SCHEMA)
            _purge(conn, self.clock)

    def actions(self) -> list[dict[str, Any]]:
        with _LOCK, _connect(self.path) as conn:
            _begin(conn, self.clock)
            rows = conn.execute("SELECT * FROM incident_actions ORDER BY at, id").fetchall()
            conn.execute("COMMIT")
        return [_action_row(row) for row in rows]

    def add_action(
        self,
        kind: str,
        incident_id: str,
        data: Mapping[str, Any],
        reason: str,
        actor: str,
        ledger: Ledger,
    ) -> dict[str, Any]:
        if kind not in {"split", "merge"}:
            raise ValueError("Bilinmeyen olay eylemi.")
        cleaned = clean_reason(reason)
        allowed = {"split": {"ref", "station_key"}, "merge": {"source", "target", "station_key"}}[kind]
        stored = {key: str(value) for key, value in data.items() if key in allowed and value is not None}
        if kind == "split" and not stored.get("ref"):
            raise ValueError("Olay üyesi bulunamadı.")
        if kind == "merge" and (not stored.get("source") or not stored.get("target")):
            raise ValueError("Birleştirme hedefi bulunamadı.")
        now = _now(self.clock)
        expires = _expires(now)
        detail = {
            "action": kind,
            "incident_id": incident_id,
            "refs": [stored["ref"]] if kind == "split" else [],
            "target": stored.get("target"),
            "undoes": None,
            "reason": cleaned,
        }
        with _LOCK, _connect(self.path) as conn:
            _begin(conn, self.clock)
            try:
                action_id = int(conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM incident_actions").fetchone()[0])
                entry = ledger.append(
                    "incident_changed",
                    actor=actor,
                    detail=detail,
                    signal_id=None,
                    entity_id=f"incident:{incident_id}",
                )
                conn.execute(
                    "INSERT INTO incident_actions "
                    "(id, at, kind, incident_id, data, reason, actor, ledger_entry, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        action_id,
                        now.isoformat(),
                        kind,
                        incident_id,
                        json.dumps(stored, sort_keys=True),
                        cleaned,
                        actor,
                        _entry_id(entry),
                        expires,
                    ),
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            row = conn.execute("SELECT * FROM incident_actions WHERE id = ?", (action_id,)).fetchone()
        return _action_row(row)

    def undo(self, action_id: int, reason: str, actor: str, ledger: Ledger) -> dict[str, Any]:
        cleaned = clean_reason(reason)
        with _LOCK, _connect(self.path) as conn:
            _begin(conn, self.clock)
            try:
                original = conn.execute("SELECT * FROM incident_actions WHERE id = ?", (action_id,)).fetchone()
                if original is None:
                    raise LookupError(action_id)
                if original["undone_at"]:
                    raise AlreadyUndone(action_id)
                now = _now(self.clock)
                entry = ledger.append(
                    "incident_changed",
                    actor=actor,
                    detail={
                        "action": "undo",
                        "incident_id": original["incident_id"],
                        "refs": [_action_row(original)["data"].get("ref")] if original["kind"] == "split" else [],
                        "target": _action_row(original)["data"].get("target"),
                        "undoes": original["ledger_entry"],
                        "reason": cleaned,
                    },
                    signal_id=None,
                    entity_id=f"incident:{original['incident_id']}",
                )
                conn.execute(
                    "UPDATE incident_actions SET undone_at = ?, undo_reason = ?, undo_ledger_entry = ? WHERE id = ?",
                    (now.isoformat(), cleaned, _entry_id(entry), action_id),
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            row = conn.execute("SELECT * FROM incident_actions WHERE id = ?", (action_id,)).fetchone()
        return _action_row(row)

    def overrides(self) -> dict[str, dict[str, Any]]:
        with _LOCK, _connect(self.path) as conn:
            _begin(conn, self.clock)
            rows = conn.execute("SELECT * FROM incident_priority ORDER BY incident_id").fetchall()
            conn.execute("COMMIT")
        return {row["incident_id"]: _priority_row(row) for row in rows}

    def priority_history(self, incident_id: str) -> list[dict[str, Any]]:
        with _LOCK, _connect(self.path) as conn:
            _begin(conn, self.clock)
            rows = conn.execute(
                "SELECT incident_id, level, reason, actor, at, suggested_level, ledger_entry "
                "FROM incident_priority_history WHERE incident_id = ? ORDER BY at, id",
                (incident_id,),
            ).fetchall()
            conn.execute("COMMIT")
        return [dict(row) for row in rows]

    def set_priority(
        self,
        incident_id: str,
        level: str,
        reason: str,
        suggested_level: str,
        actor: str,
        ledger: Ledger,
    ) -> dict[str, Any]:
        if level not in {"high", "medium", "normal"}:
            raise ValueError("Öncelik seviyesi geçersiz.")
        cleaned = clean_reason(reason)
        now = _now(self.clock)
        expires = _expires(now)
        with _LOCK, _connect(self.path) as conn:
            _begin(conn, self.clock)
            try:
                previous = conn.execute(
                    "SELECT level FROM incident_priority WHERE incident_id = ?",
                    (incident_id,),
                ).fetchone()
                entry = ledger.append(
                    "incident_priority_set",
                    actor=actor,
                    detail={
                        "incident_id": incident_id,
                        "from": previous["level"] if previous else suggested_level,
                        "to": level,
                        "suggested_level": suggested_level,
                        "reason": cleaned,
                    },
                    signal_id=None,
                    entity_id=f"incident:{incident_id}",
                )
                ledger_id = _entry_id(entry)
                conn.execute(
                    "INSERT INTO incident_priority VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(incident_id) DO UPDATE SET level=excluded.level, reason=excluded.reason, "
                    "actor=excluded.actor, at=excluded.at, suggested_level=excluded.suggested_level, "
                    "ledger_entry=excluded.ledger_entry, expires_at=excluded.expires_at",
                    (incident_id, level, cleaned, actor, now.isoformat(), suggested_level, ledger_id, expires),
                )
                conn.execute(
                    "INSERT INTO incident_priority_history "
                    "(incident_id, level, reason, actor, at, suggested_level, ledger_entry, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (incident_id, level, cleaned, actor, now.isoformat(), suggested_level, ledger_id, expires),
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return {
            "incident_id": incident_id,
            "level": level,
            "reason": cleaned,
            "actor": actor,
            "at": now.isoformat(),
            "suggested_level": suggested_level,
            "ledger_entry": ledger_id,
        }

    def clear_priority(
        self,
        incident_id: str,
        reason: str,
        actor: str,
        ledger: Ledger,
    ) -> dict[str, Any]:
        cleaned = clean_reason(reason)
        now = _now(self.clock)
        expires = _expires(now)
        with _LOCK, _connect(self.path) as conn:
            _begin(conn, self.clock)
            try:
                previous = conn.execute(
                    "SELECT * FROM incident_priority WHERE incident_id = ?",
                    (incident_id,),
                ).fetchone()
                if previous is None:
                    raise LookupError(incident_id)
                entry = ledger.append(
                    "incident_priority_set",
                    actor=actor,
                    detail={
                        "incident_id": incident_id,
                        "from": previous["level"],
                        "to": "suggested",
                        "suggested_level": previous["suggested_level"],
                        "reason": cleaned,
                    },
                    signal_id=None,
                    entity_id=f"incident:{incident_id}",
                )
                ledger_id = _entry_id(entry)
                conn.execute("DELETE FROM incident_priority WHERE incident_id = ?", (incident_id,))
                conn.execute(
                    "INSERT INTO incident_priority_history "
                    "(incident_id, level, reason, actor, at, suggested_level, ledger_entry, expires_at) "
                    "VALUES (?, 'suggested', ?, ?, ?, ?, ?, ?)",
                    (incident_id, cleaned, actor, now.isoformat(), previous["suggested_level"], ledger_id, expires),
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return {
            "incident_id": incident_id,
            "level": "suggested",
            "reason": cleaned,
            "actor": actor,
            "at": now.isoformat(),
            "suggested_level": previous["suggested_level"],
            "ledger_entry": ledger_id,
        }
