"""Source-linked life-event plans and their private, expiring work files."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import pathlib
import re
import secrets
import sqlite3
import threading
import uuid
from collections.abc import Iterator, Mapping
from typing import Any

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.models import ISTANBUL_TZ, utcnow
from nabiz.console.accounts import token_hash
from nabiz.console.pii_guard import scan_pii
from nabiz.console.text_guard import strip_invisible

PATH_ENV = "NABIZ_CASE_FILES_DB_PATH"
PLAN_PATH = REPO_ROOT / "data/knowledge/life_events.json"
TTL_DAYS = 90
MAX_FILES_PER_OWNER = 3
NOTE_MAX = 280
REF_MAX = 40
REMIND_MAX_DAYS = 365
CREATES_PER_HOUR = 10
CASE_HEADER = "x-nabiz-case"
CONSENT_VERSION = "2026-09-26"
CONSENT_TEXT = (
    "Açık rızamla, seçtiğim planın adımlarını, işaretlerimi, notlarımı, referans kodlarımı ve hatırlatma "
    "tarihlerimi bu prototipin sunucusunda saklamasını kabul ediyorum. Kimlik, kart, telefon ya da e-posta "
    "yazmayacağım. İş dosyamı istediğim an silebilirim; 90 gün değişiklik yapmazsam kendiliğinden silinir."
)
BAND = "Örnek iş dosyası · kurumlara hiçbir şey gönderilmez · resmî işlem bağlantıları kurumların kendi sayfalarıdır"


class PlanError(ValueError):
    """A plan definition or one of its cited source fragments is invalid."""


class CaseFileError(ValueError):
    """A safe error that the API can show without revealing another owner's file."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class CaseConsentRequired(CaseFileError):
    def __init__(self) -> None:
        super().__init__(400, "consent_required", "İş dosyası için açık rıza kutusunu işaretleyin.")


class _FileNotFound(CaseFileError):
    def __init__(self) -> None:
        super().__init__(404, "file_not_found", "İş dosyası bulunamadı ya da 90 günlük saklama süresi doldu.")


class _SchemaError(CaseFileError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(400, code, message)


def case_files_path(env: Mapping[str, str] | None = None) -> pathlib.Path:
    values = os.environ if env is None else env
    raw = values.get(PATH_ENV, "").strip()
    path = pathlib.Path(raw or "data/accounts/case_files.sqlite").expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


def _plan_index(path: pathlib.Path | None = None) -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads((path or PLAN_PATH).read_text(encoding="utf-8"))
        return {plan["id"]: plan for plan in raw["plans"]}
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise PlanError("Yaşam olayı planları okunamadı.") from exc


def _fold_space(value: str) -> str:
    return " ".join(value.split())


def water_route(choice_id: str) -> dict[str, Any]:
    routes = {
        "iptal": (0, "Seçtiğiniz duruma göre ilgili İSKİ sayfası bu. Karar İSKİ'nindir."),
        "yenileme": (1, "Seçtiğiniz duruma göre ilgili İSKİ sayfası bu. Karar İSKİ'nindir."),
        "yeni": (2, "Seçtiğiniz duruma göre ilgili İSKİ sayfası bu. Karar İSKİ'nindir."),
        "bilmiyorum": (None, "Bu durum kaynakta açıkça anlatılmıyor. İSKİ'ye ya da 153'e sorun."),
    }
    if choice_id not in routes:
        raise ValueError("Bilinmeyen su aboneliği seçeneği.")
    source_index, message = routes[choice_id]
    return {"choice": choice_id, "source_index": source_index, "message": message}


def clean_note(raw: str) -> str:
    value = _fold_space(strip_invisible(str(raw))[0])
    if len(value) > NOTE_MAX:
        raise _SchemaError("note_invalid", "Not en çok 280 karakter olabilir.")
    if scan_pii(value):
        raise _SchemaError("note_invalid", "Buraya kimlik, kart, telefon ya da e-posta yazmayın.")
    return value


def clean_ref(raw: str) -> str:
    value = _fold_space(strip_invisible(str(raw))[0])
    if len(value) > REF_MAX or any(not (character.isalnum() or character in " ./-") for character in value):
        raise _SchemaError("ref_invalid", "Referans kodunu kısaltıp harf, rakam ya da işaretle yazın.")
    if scan_pii(value):
        raise _SchemaError("ref_invalid", "Buraya kimlik, kart, telefon ya da e-posta yazmayın.")
    return value


def clean_remind(raw: str, today: dt.date) -> str | None:
    value = raw.strip()
    if not value:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise _SchemaError("date_invalid", "Hatırlatma tarihi geçerli görünmüyor.")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise _SchemaError("date_invalid", "Hatırlatma tarihi geçerli görünmüyor.") from exc
    if parsed < today or parsed > today + dt.timedelta(days=REMIND_MAX_DAYS):
        raise _SchemaError("date_invalid", "Hatırlatma bugünden başlayıp bir yıl içinde olmalı.")
    return parsed.isoformat()


def progress(file: dict[str, Any], plan: dict[str, Any]) -> dict[str, int]:
    done = sum(bool(step.get("done_at")) for step in file.get("steps", []))
    return {"done": done, "total": len(plan.get("steps", []))}


def due_reminders(file: dict[str, Any], plan: dict[str, Any], today: dt.date) -> list[dict[str, str]]:
    titles = {step["id"]: step["title"] for step in plan.get("steps", [])}
    return [
        {"step_id": step["step_id"], "title": titles.get(step["step_id"], ""), "remind_on": step["remind_on"]}
        for step in file.get("steps", [])
        if step.get("remind_on") and step["remind_on"] <= today.isoformat() and not step.get("done_at")
    ]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS case_files (
 id TEXT PRIMARY KEY, owner_kind TEXT NOT NULL CHECK (owner_kind IN ('account', 'device')), owner_ref TEXT NOT NULL,
 plan_id TEXT NOT NULL, answers TEXT NOT NULL DEFAULT '{}', consent_at TEXT NOT NULL, consent_version TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT NOT NULL, UNIQUE (owner_kind, owner_ref, plan_id)
);
CREATE INDEX IF NOT EXISTS case_files_expiry ON case_files (expires_at);
CREATE TABLE IF NOT EXISTS case_steps (
 file_id TEXT NOT NULL REFERENCES case_files(id) ON DELETE CASCADE, step_id TEXT NOT NULL, done_at TEXT, note TEXT,
 ref_code TEXT, remind_on TEXT, updated_at TEXT NOT NULL, PRIMARY KEY (file_id, step_id)
);
"""


class CaseFileStore:
    """One SQLite connection and lock; expired and orphaned rows are purged on every operation."""

    def __init__(
        self,
        path: str | pathlib.Path | None = None,
        *,
        clock: Any = utcnow,
        accounts_path: str | pathlib.Path | None = None,
    ) -> None:
        self.path = pathlib.Path(path) if path is not None else case_files_path()
        if not self.path.is_absolute():
            self.path = REPO_ROOT / self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.accounts_path = pathlib.Path(accounts_path) if accounts_path is not None else None
        self._clock = clock
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)
        self.purge()

    def close(self) -> None:
        self._db.close()

    def _now(self) -> dt.datetime:
        now = self._clock()
        return now.replace(tzinfo=dt.UTC) if now.tzinfo is None else now.astimezone(dt.UTC)

    @contextlib.contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            else:
                self._db.execute("COMMIT")

    def _account_ids(self) -> set[str] | None:
        if self.accounts_path is None:
            return None
        if not self.accounts_path.is_file():
            return set()
        uri = self.accounts_path.resolve().as_uri() + "?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True) as conn:
                return {str(row[0]) for row in conn.execute("SELECT id FROM accounts")}
        except sqlite3.Error:
            return None

    def purge(self) -> int:
        with self._transaction() as db:
            return self._purge_in(db, self._now())

    def _plan(self, plan_id: str) -> dict[str, Any]:
        plan = _plan_index().get(plan_id)
        if plan is None:
            raise _SchemaError("plan_unknown", "Bu plan bulunamadı.")
        return plan

    @staticmethod
    def _owner(owner: tuple[str, str]) -> tuple[str, str]:
        kind, ref = owner
        if kind not in {"account", "device"} or not ref:
            raise CaseFileError(401, "no_owner", "Bu cihazda iş dosyası yok.")
        return kind, ref

    def _file_in(self, db: sqlite3.Connection, owner: tuple[str, str], file_id: str) -> dict[str, Any]:
        row = db.execute(
            "SELECT * FROM case_files WHERE id=? AND owner_kind=? AND owner_ref=?",
            (file_id, owner[0], owner[1]),
        ).fetchone()
        if row is None:
            raise _FileNotFound()
        steps = db.execute("SELECT * FROM case_steps WHERE file_id=? ORDER BY rowid", (file_id,)).fetchall()
        return {
            "id": row["id"],
            "plan_id": row["plan_id"],
            "answers": json.loads(row["answers"]),
            "steps": [
                {key: step[key] for key in ("step_id", "done_at", "note", "ref_code", "remind_on", "updated_at")}
                for step in steps
            ],
            "consent_at": row["consent_at"],
            "consent_version": row["consent_version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "expires_at": row["expires_at"],
        }

    def create(self, owner: tuple[str, str], plan_id: str, consent: bool) -> tuple[dict[str, Any], str | None]:
        if consent is not True:
            raise CaseConsentRequired()
        kind, raw_ref = owner
        if kind not in {"account", "device"} or (kind == "account" and not raw_ref):
            raise CaseFileError(401, "no_owner", "Bu cihazda iş dosyası yok.")
        device_key = None
        owner_ref = raw_ref
        if kind == "device":
            device_key = raw_ref or secrets.token_urlsafe(24)
            owner_ref = token_hash(device_key)
            if raw_ref:
                device_key = None
        plan = self._plan(plan_id)
        now = self._now()
        file_id = uuid.uuid4().hex
        expires = now + dt.timedelta(days=TTL_DAYS)
        with self._transaction() as db:
            self._purge_in(db, now)
            if db.execute(
                "SELECT 1 FROM case_files WHERE owner_kind=? AND owner_ref=? AND plan_id=?", (kind, owner_ref, plan_id)
            ).fetchone():
                raise CaseFileError(409, "plan_exists", "Bu plan için bir iş dosyanız zaten var.")
            count = db.execute(
                "SELECT COUNT(*) FROM case_files WHERE owner_kind=? AND owner_ref=?", (kind, owner_ref)
            ).fetchone()[0]
            if count >= MAX_FILES_PER_OWNER:
                raise CaseFileError(409, "too_many_files", "En çok üç iş dosyası açabilirsiniz.")
            db.execute(
                "INSERT INTO case_files VALUES (?, ?, ?, ?, '{}', ?, ?, ?, ?, ?)",
                (
                    file_id,
                    kind,
                    owner_ref,
                    plan_id,
                    now.isoformat(),
                    CONSENT_VERSION,
                    now.isoformat(),
                    now.isoformat(),
                    expires.isoformat(),
                ),
            )
            db.executemany(
                "INSERT INTO case_steps (file_id, step_id, updated_at) VALUES (?, ?, ?)",
                [(file_id, step["id"], now.isoformat()) for step in plan["steps"]],
            )
            result = self._file_in(db, (kind, owner_ref), file_id)
        return result, device_key

    def _purge_in(self, db: sqlite3.Connection, now: dt.datetime) -> int:
        count = db.execute("DELETE FROM case_files WHERE expires_at <= ?", (now.isoformat(),)).rowcount
        account_ids = self._account_ids()
        if account_ids is None:
            return count
        rows = db.execute("SELECT id, owner_ref FROM case_files WHERE owner_kind='account'").fetchall()
        for file_id in [row["id"] for row in rows if row["owner_ref"] not in account_ids]:
            count += db.execute("DELETE FROM case_files WHERE id=?", (file_id,)).rowcount
        return count

    def files(self, owner: tuple[str, str]) -> list[dict[str, Any]]:
        owner = self._owner(owner)
        now = self._now()
        with self._transaction() as db:
            self._purge_in(db, now)
            rows = db.execute(
                "SELECT id FROM case_files WHERE owner_kind=? AND owner_ref=? ORDER BY created_at",
                owner,
            ).fetchall()
            return [self._file_in(db, owner, row["id"]) for row in rows]

    def set_answer(self, owner: tuple[str, str], file_id: str, step_id: str, choice: str) -> dict[str, Any]:
        owner = self._owner(owner)
        now = self._now()
        with self._transaction() as db:
            self._purge_in(db, now)
            file = self._file_in(db, owner, file_id)
            plan = self._plan(file["plan_id"])
            step = next((item for item in plan["steps"] if item["id"] == step_id), None)
            choices = step.get("choices", []) if step else []
            if step is None:
                raise _SchemaError("step_unknown", "Bu plan adımı bulunamadı.")
            if step.get("kind") != "choice" or choice not in {item["id"] for item in choices}:
                raise _SchemaError("choice_unknown", "Bu seçim bu adımda yok.")
            file["answers"][step_id] = choice
            db.execute(
                "UPDATE case_files SET answers=?, updated_at=?, expires_at=? WHERE id=?",
                (
                    json.dumps(file["answers"], ensure_ascii=False),
                    now.isoformat(),
                    (now + dt.timedelta(days=TTL_DAYS)).isoformat(),
                    file_id,
                ),
            )
            db.execute("UPDATE case_steps SET updated_at=? WHERE file_id=? AND step_id=?", (now.isoformat(), file_id, step_id))
            return self._file_in(db, owner, file_id)

    def set_step(
        self,
        owner: tuple[str, str],
        file_id: str,
        step_id: str,
        *,
        done: bool | None = None,
        note: str | None = None,
        ref_code: str | None = None,
        remind_on: str | None = None,
    ) -> dict[str, Any]:
        owner = self._owner(owner)
        plan = self._plan(self._file_plan(owner, file_id))
        if step_id not in {step["id"] for step in plan["steps"]}:
            raise _SchemaError("step_unknown", "Bu plan adımı bulunamadı.")
        clean_values: dict[str, Any] = {}
        if note is not None:
            clean_values["note"] = clean_note(note) or None
        if ref_code is not None:
            clean_values["ref_code"] = clean_ref(ref_code) or None
        if remind_on is not None:
            clean_values["remind_on"] = clean_remind(remind_on, self._now().astimezone(ISTANBUL_TZ).date())
        if done is not None and not isinstance(done, bool):
            raise _SchemaError("step_unknown", "Adım işareti geçerli değil.")
        now = self._now()
        with self._transaction() as db:
            self._purge_in(db, now)
            file = self._file_in(db, owner, file_id)
            step = next((item for item in file["steps"] if item["step_id"] == step_id), None)
            if step is None:
                raise _SchemaError("step_unknown", "Bu plan adımı bulunamadı.")
            if done is not None:
                clean_values["done_at"] = now.isoformat() if done else None
            clean_values["updated_at"] = now.isoformat()
            assignments = ", ".join(f"{key}=?" for key in clean_values)
            values = list(clean_values.values())
            if assignments:
                db.execute(f"UPDATE case_steps SET {assignments} WHERE file_id=? AND step_id=?", (*values, file_id, step_id))
            db.execute(
                "UPDATE case_files SET updated_at=?, expires_at=? WHERE id=?",
                (
                    now.isoformat(),
                    (now + dt.timedelta(days=TTL_DAYS)).isoformat(),
                    file_id,
                ),
            )
            return self._file_in(db, owner, file_id)

    def _file_plan(self, owner: tuple[str, str], file_id: str) -> str:
        self.purge()
        with self._lock:
            row = self._db.execute(
                "SELECT plan_id FROM case_files WHERE id=? AND owner_kind=? AND owner_ref=?",
                (file_id, owner[0], owner[1]),
            ).fetchone()
        if row is None:
            raise _FileNotFound()
        return str(row[0])

    def delete(self, owner: tuple[str, str], file_id: str) -> None:
        owner = self._owner(owner)
        now = self._now()
        with self._transaction() as db:
            self._purge_in(db, now)
            cursor = db.execute(
                "DELETE FROM case_files WHERE id=? AND owner_kind=? AND owner_ref=?",
                (file_id, owner[0], owner[1]),
            )
            if cursor.rowcount == 0:
                raise _FileNotFound()


__all__ = [
    "BAND",
    "CASE_HEADER",
    "CONSENT_TEXT",
    "CONSENT_VERSION",
    "CREATES_PER_HOUR",
    "MAX_FILES_PER_OWNER",
    "NOTE_MAX",
    "PATH_ENV",
    "REF_MAX",
    "REMIND_MAX_DAYS",
    "TTL_DAYS",
    "CaseFileError",
    "CaseFileStore",
    "CaseConsentRequired",
    "PlanError",
    "case_files_path",
    "clean_note",
    "clean_ref",
    "clean_remind",
    "due_reminders",
    "progress",
    "water_route",
]
