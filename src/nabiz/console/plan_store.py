"""Consent-gated, owner-scoped SQLite calendar records."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from nabiz.console.operation_ledger import Operation, OperationConflict, OperationLedger

DEFAULT_PATH = Path("data/nexus/plans.sqlite3")
TIME_ZONE = "Europe/Istanbul"
_FIELDS = ("title", "starts_at", "ends_at", "all_day", "time_zone", "place", "source_url", "source_date", "conversation_id")


def plans_path() -> Path:
    """``NABIZ_PLAN_DB_PATH``, else the default file."""
    return Path(os.environ.get("NABIZ_PLAN_DB_PATH") or DEFAULT_PATH)


class PlanNotFound(LookupError):
    """No plan belongs to this principal under the requested identifier."""


def _fingerprint(action: str, target_id: str, fields: dict[str, Any]) -> str:
    raw = json.dumps([action, target_id, fields], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _validate_dates(fields: dict[str, Any]) -> None:
    start, end = fields["starts_at"], fields["ends_at"]
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError("Tarih geçersiz.")
    try:
        if fields["all_day"]:
            if date.fromisoformat(start).isoformat() != start or date.fromisoformat(end).isoformat() != end:
                raise ValueError
            first, last = date.fromisoformat(start), date.fromisoformat(end)
        else:
            first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
            if first.tzinfo is not None or last.tzinfo is not None:
                raise ValueError
    except ValueError as exc:
        raise ValueError("Tarih biçimi geçersiz.") from exc
    if last <= first:
        raise ValueError("Bitiş başlangıçtan sonra olmalı.")


def _validate_optional(fields: dict[str, Any]) -> None:
    for key, limit in (("place", 200), ("conversation_id", 128)):
        value = fields[key]
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            raise ValueError(f"{key} geçersiz.")
    source_url = fields["source_url"]
    if source_url is not None and (
        not isinstance(source_url, str) or len(source_url) > 2048
        or urlparse(source_url).scheme != "https" or not urlparse(source_url).hostname
    ):
        raise ValueError("Kaynak adresi geçersiz.")
    source_date = fields["source_date"]
    if source_date is not None:
        try:
            if not isinstance(source_date, str) or date.fromisoformat(source_date).isoformat() != source_date:
                raise ValueError
        except ValueError as exc:
            raise ValueError("Kaynak tarihi geçersiz.") from exc


def _validate(fields: dict[str, Any]) -> dict[str, Any]:
    if set(fields) != set(_FIELDS):
        raise ValueError("Plan alanları eksik veya fazla.")
    title = fields["title"]
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise ValueError("Başlık geçersiz.")
    if fields["time_zone"] != TIME_ZONE or not isinstance(fields["all_day"], bool):
        raise ValueError("Saat dilimi veya tüm gün değeri geçersiz.")
    _validate_dates(fields)
    _validate_optional(fields)
    return {key: fields[key] for key in _FIELDS}


class PlanStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, title TEXT NOT NULL,
                    starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, all_day INTEGER NOT NULL,
                    time_zone TEXT NOT NULL, place TEXT, source_url TEXT, source_date TEXT,
                    conversation_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS plans_owner ON plans(owner_id, starts_at)")
            OperationLedger.create_schema(db)

    def erase_owner(self, owner_id: str) -> int:
        """Every plan and operation of an account, for the account's erasure (P00 D2a); the plans removed."""
        with self._db() as db:
            db.execute("DELETE FROM operation_ledger WHERE owner_id = ?", (owner_id,))
            return db.execute("DELETE FROM plans WHERE owner_id = ?", (owner_id,)).rowcount

    @classmethod
    def from_env(cls) -> PlanStore:
        return cls(plans_path())

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _identity(owner_id: str, operation_id: str) -> None:
        if not isinstance(owner_id, str) or not owner_id or len(owner_id) > 128:
            raise ValueError("Kullanıcı kimliği gerekli.")
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 128:
            raise ValueError("İşlem kimliği gerekli.")

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["all_day"] = bool(result["all_day"])
        result.pop("owner_id")
        return result

    def get(self, owner_id: str, plan_id: str) -> dict[str, Any]:
        with self._db() as db:
            row = db.execute("SELECT * FROM plans WHERE owner_id = ? AND id = ?", (owner_id, plan_id)).fetchone()
            if row is None:
                raise PlanNotFound("Plan bulunamadı.")
            return self._row(row)

    def list(self, owner_id: str) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM plans WHERE owner_id = ? ORDER BY starts_at, id", (owner_id,)).fetchall()
            return [self._row(row) for row in rows]

    def save(self, owner_id: str, operation_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self._identity(owner_id, operation_id)
        clean = _validate(fields)
        fingerprint = _fingerprint("save", "", clean)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            ledger = OperationLedger(db)
            existing = ledger.require_same(owner_id, operation_id, "save", fingerprint)
            if existing:
                return existing.result["plan"]
            plan_id = str(uuid.uuid4())
            now = datetime.now().astimezone().isoformat()
            db.execute(
                "INSERT INTO plans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (plan_id, owner_id, clean["title"], clean["starts_at"], clean["ends_at"], int(clean["all_day"]),
                 clean["time_zone"], clean["place"], clean["source_url"], clean["source_date"],
                 clean["conversation_id"], now, now),
            )
            row = db.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
            plan = self._row(row)
            ledger.record(owner_id, operation_id, "save", fingerprint, plan_id, "saved", {"plan": plan})
            return plan

    def update(self, owner_id: str, plan_id: str, operation_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self._identity(owner_id, operation_id)
        clean = _validate(fields)
        fingerprint = _fingerprint("update", plan_id, clean)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            ledger = OperationLedger(db)
            existing = ledger.require_same(owner_id, operation_id, "update", fingerprint)
            if existing and existing.target_id != plan_id:
                raise OperationConflict("İşlem kimliği farklı planda kullanılmış.")
            row = db.execute("SELECT * FROM plans WHERE id = ? AND owner_id = ?", (plan_id, owner_id)).fetchone()
            if row is None:
                raise PlanNotFound("Plan bulunamadı.")
            if existing:
                return existing.result["plan"]
            db.execute(
                "UPDATE plans SET title=?, starts_at=?, ends_at=?, all_day=?, time_zone=?, place=?, "
                "source_url=?, source_date=?, conversation_id=?, updated_at=? WHERE id=? AND owner_id=?",
                (clean["title"], clean["starts_at"], clean["ends_at"], int(clean["all_day"]), clean["time_zone"],
                 clean["place"], clean["source_url"], clean["source_date"], clean["conversation_id"],
                 datetime.now().astimezone().isoformat(), plan_id, owner_id),
            )
            row = db.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
            plan = self._row(row)
            ledger.record(owner_id, operation_id, "update", fingerprint, plan_id, "saved", {"plan": plan})
            return plan

    def outlook_operation(self, owner_id: str, plan_id: str, operation_id: str) -> Operation:
        self._identity(owner_id, operation_id)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM plans WHERE id=? AND owner_id=?", (plan_id, owner_id)).fetchone() is None:
                raise PlanNotFound("Plan bulunamadı.")
            ledger = OperationLedger(db)
            existing = ledger.require_same(owner_id, operation_id, "outlook", plan_id)
            if existing:
                return existing
            ledger.record(owner_id, operation_id, "outlook", plan_id, plan_id, "verifying", {"result": "outlook_verifying"})
            return ledger.get(owner_id, operation_id)  # type: ignore[return-value]

    def set_outlook_result(self, owner_id: str, operation_id: str, state: str, result: dict[str, Any]) -> None:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            operation = OperationLedger(db).get(owner_id, operation_id)
            if operation is None or operation.action != "outlook":
                raise OperationConflict("Outlook işlemi bulunamadı.")
            if operation.state == "added":
                return
            OperationLedger(db).set_result(owner_id, operation_id, state, result)
