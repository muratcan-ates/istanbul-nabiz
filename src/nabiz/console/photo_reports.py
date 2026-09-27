"""Short-lived, consented photo reports and their privacy-limited decision ledger entries."""

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
from typing import Any

from nabiz.console.citizen_requests import new_code
from nabiz.console.wiring import ledger_path
from nexus_core.decisions import Operator
from nexus_core.ledger import Ledger
from nexus_core.signals import Clock, as_utc, system_clock

TTL_DAYS = 30
MAX_DESCRIPTION_CHARS = 280
MAX_REASON_CHARS = 280
MAX_OPEN_REPORTS = 500
MAX_STORED_BYTES = 200 * 1024 * 1024
CONSENT_VERSION = "e51-1"
PHOTO_REPORTS_PATH_ENV = "NABIZ_PHOTO_REPORTS_DB_PATH"
PHOTO_REPORTS_PER_HOUR = 3
STATUS_TRANSITIONS = {
    "new": frozenset({"reviewed", "forwarded", "closed"}),
    "reviewed": frozenset({"forwarded", "closed"}),
    "forwarded": frozenset({"closed"}),
    "closed": frozenset(),
}
PHOTO_DISTRICTS = (
    "Adalar", "Arnavutköy", "Ataşehir", "Avcılar", "Bağcılar", "Bahçelievler", "Bakırköy", "Başakşehir",
    "Bayrampaşa", "Beşiktaş", "Beykoz", "Beylikdüzü", "Beyoğlu", "Büyükçekmece", "Çatalca", "Çekmeköy",
    "Esenler", "Esenyurt", "Eyüpsultan", "Fatih", "Gaziosmanpaşa", "Güngören", "Kadıköy", "Kağıthane",
    "Kartal", "Küçükçekmece", "Maltepe", "Pendik", "Sancaktepe", "Sarıyer", "Silivri", "Sultanbeyli",
    "Sultangazi", "Şile", "Şişli", "Tuzla", "Ümraniye", "Üsküdar", "Zeytinburnu",
)
_PHOTO_SCHEMA = """
CREATE TABLE IF NOT EXISTS photo_reports (
    code TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL,
    data TEXT NOT NULL,
    photo BLOB,
    photo_type TEXT
);
CREATE INDEX IF NOT EXISTS photo_reports_expiry ON photo_reports (expires_at);
"""
_REPORT_COLUMNS = "code, created_at, expires_at, status, data, photo IS NOT NULL AS has_photo"


class StoreFull(RuntimeError):
    """The store reached its bounded open-row or photo-byte capacity."""


@dataclass(frozen=True)
class NewPhotoReport:
    category: str
    place: dict[str, str]
    description: str
    masked_count: int
    masked_kinds: tuple[str, ...]
    lang: str
    photo_meta: dict[str, Any]
    photo: bytes
    photo_type: str


def photo_reports_path(env: Mapping[str, str] | None = None) -> pathlib.Path:
    values = os.environ if env is None else env
    raw = (values.get(PHOTO_REPORTS_PATH_ENV) or "").strip()
    return pathlib.Path(raw) if raw else ledger_path(env).with_name("photo_reports.db")


def photo_per_hour(env: Mapping[str, str] | None = None) -> int:
    values = os.environ if env is None else env
    raw = (values.get("NABIZ_PHOTO_REPORTS_PER_HOUR") or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else PHOTO_REPORTS_PER_HOUR


def photo_report_ledger_request(ledger: Ledger, row: Mapping[str, Any]) -> int:
    """Seal receipt facts without the description, place name, photo bytes, or a photo digest."""
    entry = ledger.append(
        "photo_report",
        actor="vatandaş (anonim)",
        entity_id=f"photo_report:{row['code']}",
        detail={
            "code": row["code"],
            "category": row["category"],
            "place_kind": row["place"]["kind"],
            "photo_meta": row["photo_meta"],
            "description_chars": len(row["description"]),
            "masked_count": row["masked_count"],
            "consent_version": CONSENT_VERSION,
        },
    )
    return entry.id


def photo_report_ledger_status(ledger: Ledger, before: str, row: Mapping[str, Any]) -> int:
    """Seal a status change with only its masked, short reason summary."""
    history = row["history"]
    reason = str(history[-1].get("reason") or "")
    from nabiz.console.citizen_requests import masked_summary

    summary, _ = masked_summary(reason)
    masked_count = int(history[-1].get("masked_count") or 0)
    entry = ledger.append(
        "photo_report_status",
        actor=Operator().label,
        entity_id=f"photo_report:{row['code']}",
        detail={
            "code": row["code"],
            "from": before,
            "to": row["status"],
            "reason_summary": summary,
            "reason_chars": len(reason),
            "masked_count": masked_count,
        },
    )
    return entry.id


def photo_report_ledger_withdrawn(ledger: Ledger, code: str) -> int:
    entry = ledger.append(
        "photo_report_withdrawn",
        actor="vatandaş (anonim)",
        entity_id=f"photo_report:{code}",
        detail={"code": code},
    )
    return entry.id


class PhotoReportStore:
    """SQLite storage with expiry purging, secure-delete, and an immediate status transaction."""

    def __init__(self, path: str | pathlib.Path | None = None, *, clock: Clock = system_clock) -> None:
        self.path = pathlib.Path(path) if path is not None else photo_reports_path()
        self._clock = clock
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_PHOTO_SCHEMA)
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
            return conn.execute(
                "DELETE FROM photo_reports WHERE expires_at <= ?", (self.now().isoformat(),)
            ).rowcount

    def create(self, report: NewPhotoReport) -> dict[str, Any]:
        self.purge()
        now = self.now()
        expires = now + dt.timedelta(days=TTL_DAYS)
        data = {
            "category": report.category,
            "place": report.place,
            "description": report.description,
            "masked_count": report.masked_count,
            "masked_kinds": list(report.masked_kinds),
            "lang": report.lang,
            "consent_version": CONSENT_VERSION,
            "photo_meta": report.photo_meta,
            "history": [{"status": "new", "at": now.isoformat(), "reason": None}],
        }
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            open_count = conn.execute("SELECT count(*) FROM photo_reports WHERE status != 'closed'").fetchone()[0]
            stored_bytes = conn.execute("SELECT coalesce(sum(length(photo)), 0) FROM photo_reports").fetchone()[0]
            if open_count >= MAX_OPEN_REPORTS or stored_bytes + len(report.photo) > MAX_STORED_BYTES:
                conn.execute("ROLLBACK")
                raise StoreFull
            code = ""
            for _ in range(8):
                candidate = new_code()
                if conn.execute("SELECT 1 FROM photo_reports WHERE code = ?", (candidate,)).fetchone() is None:
                    code = candidate
                    break
            if not code:
                conn.execute("ROLLBACK")
                raise StoreFull
            conn.execute(
                "INSERT INTO photo_reports VALUES (?, ?, ?, ?, ?, ?, ?)",
                (code, now.isoformat(), expires.isoformat(), "new", json.dumps(data, ensure_ascii=False),
                 sqlite3.Binary(report.photo), report.photo_type),
            )
            conn.execute("COMMIT")
        return self.get(code) or {}

    def get(self, code: str) -> dict[str, Any] | None:
        self.purge()
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_REPORT_COLUMNS} FROM photo_reports WHERE code = ? AND expires_at > ?",
                (code, self.now().isoformat()),
            ).fetchone()
        return _photo_report_row(row) if row is not None else None

    def photo(self, code: str) -> tuple[bytes, str] | None:
        self.purge()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT photo, photo_type, status FROM photo_reports WHERE code = ? AND expires_at > ?",
                (code, self.now().isoformat()),
            ).fetchone()
        if row is None or row["status"] == "closed" or row["photo"] is None:
            return None
        return bytes(row["photo"]), str(row["photo_type"])

    def items(self, *, open_only: bool = True) -> list[dict[str, Any]]:
        self.purge()
        sql = f"SELECT {_REPORT_COLUMNS} FROM photo_reports WHERE expires_at > ?"
        values: tuple[Any, ...] = (self.now().isoformat(),)
        if open_only:
            sql += " AND status != 'closed'"
        with self._connect() as conn:
            rows = conn.execute(sql + " ORDER BY created_at DESC LIMIT 500", values).fetchall()
        return [_photo_report_row(row) for row in rows]

    def set_status(self, code: str, target: str, reason: str, *, masked_count: int = 0) -> dict[str, Any] | None:
        self.purge()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            raw = conn.execute(
                f"SELECT {_REPORT_COLUMNS} FROM photo_reports WHERE code = ? AND expires_at > ?",
                (code, self.now().isoformat()),
            ).fetchone()
            if raw is None:
                conn.execute("ROLLBACK")
                return None
            current = str(raw["status"])
            if target not in STATUS_TRANSITIONS.get(current, frozenset()):
                conn.execute("ROLLBACK")
                raise ValueError("transition_not_allowed")
            data = json.loads(raw["data"])
            data["history"].append({
                "status": target,
                "at": self.now().isoformat(),
                "reason": reason,
                "masked_count": masked_count,
            })
            if target == "closed":
                conn.execute(
                    "UPDATE photo_reports SET status = ?, data = ?, photo = NULL, photo_type = NULL WHERE code = ?",
                    (target, json.dumps(data, ensure_ascii=False), code),
                )
            else:
                conn.execute(
                    "UPDATE photo_reports SET status = ?, data = ? WHERE code = ?",
                    (target, json.dumps(data, ensure_ascii=False), code),
                )
            conn.execute("COMMIT")
        return self.get(code)

    def withdraw(self, code: str) -> bool:
        self.purge()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM photo_reports WHERE code = ? AND expires_at > ?", (code, self.now().isoformat())
            )
            return cursor.rowcount > 0


def _photo_report_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "code": row["code"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "status": row["status"],
        **json.loads(row["data"]),
        "has_photo": bool(row["has_photo"]),
    }


__all__ = [
    "CONSENT_VERSION", "MAX_DESCRIPTION_CHARS", "MAX_OPEN_REPORTS", "MAX_REASON_CHARS", "MAX_STORED_BYTES",
    "PHOTO_DISTRICTS", "PHOTO_REPORTS_PATH_ENV", "PHOTO_REPORTS_PER_HOUR", "STATUS_TRANSITIONS", "StoreFull",
    "TTL_DAYS", "NewPhotoReport", "PhotoReportStore", "photo_per_hour", "photo_report_ledger_request",
    "photo_report_ledger_status", "photo_report_ledger_withdrawn", "photo_reports_path",
]
