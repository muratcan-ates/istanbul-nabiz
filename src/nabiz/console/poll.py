"""Storage and validation for the one-question citizen poll.

Retention limits, character limits, vote thresholds and hourly caps below are design
parameters from the E54 brief, not measured values.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import secrets
import sqlite3
import threading
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ibb_mcp.models import ISTANBUL_TZ
from ibb_mcp.text import normalize_tr
from nabiz.console.pii_guard import KINDS, mask_labels, scan_pii
from nabiz.console.text_guard import strip_invisible
from nabiz.console.wiring import ledger_path
from nexus_core.ledger import Ledger, canonical
from nexus_core.signals import Clock, as_utc, system_clock

PATH_ENV = "NABIZ_POLLS_DB_PATH"
TTL_DAYS = 30
DRAFT_TTL_DAYS = 7
QUESTION_MIN = 8
QUESTION_MAX = 140
OPTION_MIN = 2
OPTION_MAX = 5
OPTION_CHARS = 40
MIN_FOR_PERCENT = 5
VOTES_PER_HOUR = 30
PUBLISHED_KIND = "poll_published"
CLOSED_KIND = "poll_closed"
DISTRICTS = tuple(
    (  # noqa: SIM905
        "Adalar|Arnavutköy|Ataşehir|Avcılar|Bağcılar|Bahçelievler|Bakırköy|Başakşehir|Bayrampaşa|Beşiktaş|Beykoz|Beylikdüzü|"
        "Beyoğlu|Büyükçekmece|Çatalca|Çekmeköy|Esenler|Esenyurt|Eyüpsultan|Fatih|Gaziosmanpaşa|Güngören|Kadıköy|Kağıthane|Kartal|"
        "Küçükçekmece|Maltepe|Pendik|Sancaktepe|Sarıyer|Silivri|Sultanbeyli|Sultangazi|Şile|Şişli|Tuzla|Ümraniye|Üsküdar|Zeytinburnu"
    ).split("|")
)
_LINK = re.compile(
    r"(?:https?://|ftp://|www\.)|(?<![\w@])(?:[a-z0-9-]+\.)+(?:com|net|org|tr|gov|edu|istanbul|io|app|info|me|co)(?:\b|/)",
    re.IGNORECASE,
)
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS polls (id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT, closes_at TEXT, "
    "expires_at TEXT, data TEXT); CREATE INDEX IF NOT EXISTS polls_expiry ON polls (expires_at); "
    "CREATE TABLE IF NOT EXISTS poll_voters (poll_id TEXT, voter TEXT, PRIMARY KEY (poll_id, voter)); "
    "CREATE TABLE IF NOT EXISTS poll_tallies (poll_id TEXT, choice TEXT, count INTEGER NOT NULL, PRIMARY KEY (poll_id, choice));"
)


@dataclass(frozen=True)
class Draft:
    """A validated poll proposal; no identifying information is allowed in its text."""

    question: str
    options: tuple[dict[str, str], ...]
    closes_on: str
    target: dict[str, str | None]


def polls_path(env: Mapping[str, str] | None = None) -> pathlib.Path:
    """Return the configured poll store, or ``polls.db`` beside the decision ledger."""
    source = os.environ if env is None else env
    raw = (source.get(PATH_ENV) or "").strip()
    return pathlib.Path(raw) if raw else ledger_path(env).with_name("polls.db")


def votes_per_hour(env: Mapping[str, str] | None = None) -> int:
    """Return the configured address limit; invalid overrides keep the design default."""
    source = os.environ if env is None else env
    raw = (source.get("NABIZ_POLL_VOTES_PER_HOUR") or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else VOTES_PER_HOUR


def clean_poll_text(raw: str) -> str:
    """Remove invisible characters, fold whitespace and normalize long dash glyphs."""
    text, _ = strip_invisible(str(raw or ""))
    return " ".join(text.replace("\u2014", "-").replace("\u2013", "-").split())


def _text_problem(question: str, options: tuple[str, ...]) -> str | None:
    hits = scan_pii(" ".join((question, *options)))
    labels = dict(KINDS)
    kinds = list(dict.fromkeys(labels[hit.kind] for hit in hits))
    rules = (
        (not QUESTION_MIN <= len(question) <= QUESTION_MAX, "Soru en az 8, en çok 140 karakter olmalı."),
        (not OPTION_MIN <= len(options) <= OPTION_MAX, "2 ile 5 arasında seçenek yazın."),
        (any(len(value) > OPTION_CHARS for value in options), "Her seçenek en çok 40 karakter olabilir."),
        (len({normalize_tr(value) for value in options}) != len(options), "İki seçenek aynı olamaz."),
        (bool(hits), f"Soruda ya da seçeneklerde kişisel veri görünüyor ({', '.join(kinds)}). Kaldırıp yeniden deneyin."),
        (any(_LINK.search(value) for value in (question, *options)), "Ankette bağlantı olamaz."),
    )
    return next((message for failed, message in rules if failed), None)


def _target_clean(target: Mapping[str, Any]) -> dict[str, str | None] | str:
    kind = target.get("kind")
    district = target.get("district")
    return (
        {"kind": "all", "district": None}
        if kind == "all"
        else {"kind": "district", "district": str(district)}
        if kind == "district" and district in DISTRICTS
        else "İlçe listede yok."
    )


def _close_date(raw: str, today: dt.date) -> dt.date | str:
    try:
        close_date = dt.date.fromisoformat(raw)
    except (TypeError, ValueError):
        return "Bitiş günü bugün ile 14 gün sonrası arasında olmalı."
    if not today <= close_date <= today + dt.timedelta(days=14):
        return "Bitiş günü bugün ile 14 gün sonrası arasında olmalı."
    return close_date


def validate_draft(
    question: str,
    options: Sequence[str],
    closes_on: str,
    target: Mapping[str, Any],
    *,
    today: dt.date,
) -> Draft | str:
    """Validate and normalize a proposal, returning a visitor-safe Turkish error sentence."""
    clean_question = clean_poll_text(question)
    clean_options = tuple(clean_poll_text(value) for value in options)
    problem = _text_problem(clean_question, clean_options)
    if problem:
        return problem
    close_date = _close_date(closes_on, today)
    if isinstance(close_date, str):
        return close_date
    normalized_target = _target_clean(target)
    if isinstance(normalized_target, str):
        return normalized_target
    return Draft(
        question=clean_question,
        options=tuple({"key": f"o{index}", "label": label} for index, label in enumerate(clean_options, 1)),
        closes_on=close_date.isoformat(),
        target=normalized_target,
    )


def closes_at_for(closes_on: str | dt.date) -> dt.datetime:
    """Return 23:59:59 in Istanbul on the chosen day, represented in UTC."""
    day = dt.date.fromisoformat(closes_on) if isinstance(closes_on, str) else closes_on
    return dt.datetime.combine(day, dt.time(23, 59, 59), tzinfo=ISTANBUL_TZ).astimezone(dt.UTC)


def digest_of(draft: Draft) -> str:
    """Hash the canonical visitor-visible proposal that the operator reviewed."""
    payload = {
        "question": draft.question,
        "options": list(draft.options),
        "target": draft.target,
        "closes_on": draft.closes_on,
    }
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def tally(counts: Mapping[str, int], options: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    """Return counts and, after five votes, largest-remainder whole percentages totalling 100."""
    total = sum(max(0, int(counts.get(option["key"], 0))) for option in options)
    rows = [
        {"key": option["key"], "label": option["label"], "count": max(0, int(counts.get(option["key"], 0))), "percent": None}
        for option in options
    ]
    if total >= MIN_FOR_PERCENT:
        floors = [row["count"] * 100 // total for row in rows]
        left = 100 - sum(floors)
        order = sorted(range(len(rows)), key=lambda i: (-(rows[i]["count"] * 100 % total), i))
        for index in order[:left]:
            floors[index] += 1
        for row, share in zip(rows, floors, strict=True):
            row["percent"] = share
    return {"total": total, "min_for_percent": MIN_FOR_PERCENT, "rows": rows}


class PollStore:
    """The poll database and its vote separation, with expiry purged on every operation."""

    def __init__(self, path: str | pathlib.Path | None = None, *, clock: Clock = system_clock,
                 ledger: Ledger | None = None) -> None:
        self.path = pathlib.Path(path) if path is not None else polls_path()
        self._clock, self.ledger, self._lock = clock, ledger, threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
        self.purge()

    @contextlib.contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def now(self) -> dt.datetime:
        """Return the injected clock value normalized to UTC."""
        return as_utc(self._clock())

    def purge(self) -> int:
        """Delete polls and both anonymous vote tables after their retention date."""
        now = self.now().isoformat()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            expired = [row[0] for row in conn.execute("SELECT id FROM polls WHERE expires_at <= ?", (now,))]
            if expired:
                marks = ",".join("?" for _ in expired)
                conn.execute(f"DELETE FROM poll_voters WHERE poll_id IN ({marks})", expired)
                conn.execute(f"DELETE FROM poll_tallies WHERE poll_id IN ({marks})", expired)
                conn.execute(f"DELETE FROM polls WHERE id IN ({marks})", expired)
            conn.execute("COMMIT")
        return len(expired)

    def create_draft(self, draft: Draft, actor: str) -> dict[str, Any]:
        """Replace the prior draft with a fresh, seven-day proposal."""
        self.active()
        now, poll_id, salt = self.now(), uuid.uuid4().hex, secrets.token_hex(16)
        data = {
            "question": draft.question,
            "options": list(draft.options),
            "target": draft.target,
            "closes_on": draft.closes_on,
            "digest": digest_of(draft),
            "salt": salt,
            "audit": [{"act": "drafted", "at": now.isoformat(), "by": actor, "ledger_entry_id": None}],
        }
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM polls WHERE status = 'active' AND closes_at > ?", (now.isoformat(),)).fetchone():
                conn.execute("ROLLBACK")
                raise ValueError("Yayında bir anket varken yeni taslak açılamaz.")
            conn.execute("DELETE FROM polls WHERE status = 'draft'")
            conn.execute(
                "INSERT INTO polls (id, status, created_at, closes_at, expires_at, data) VALUES (?, 'draft', ?, ?, ?, ?)",
                (
                    poll_id,
                    now.isoformat(),
                    closes_at_for(draft.closes_on).isoformat(),
                    (now + dt.timedelta(days=DRAFT_TTL_DAYS)).isoformat(),
                    json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            conn.execute("COMMIT")
        return self.get(poll_id) or {}

    def get(self, poll_id: str) -> dict[str, Any] | None:
        """Read one poll with its private store fields for internal callers."""
        self.purge()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM polls WHERE id = ?", (poll_id,)).fetchone()
        return self._row(row) if row else None

    def current(self) -> dict[str, dict[str, Any] | None]:
        """Return the sole current draft and active poll, if either exists."""
        active = self.active()
        now = self.now().isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM polls WHERE status = 'draft' AND expires_at > ? ORDER BY created_at DESC LIMIT 1", (now,)
            ).fetchone()
        return {"draft": self._row(row) if row else None, "active": active}

    def active(self) -> dict[str, Any] | None:
        """Return the active poll; seal one overdue closure when the clock has passed its end."""
        now = self.now().isoformat()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM polls WHERE status = 'active' ORDER BY created_at DESC LIMIT 1").fetchone()
            if row is not None and row["closes_at"] <= now and self.ledger is not None:
                conn.execute("BEGIN IMMEDIATE")
                fresh = conn.execute("SELECT * FROM polls WHERE id = ? AND status = 'active'", (row["id"],)).fetchone()
                if fresh is not None and fresh["closes_at"] <= now:
                    self._close_expired(conn, fresh)
                conn.execute("COMMIT")
        self.purge()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM polls WHERE status = 'active' AND closes_at > ? ORDER BY created_at DESC LIMIT 1",
                (now,),
            ).fetchone()
        return self._row(row) if row else None

    def last_closed(self) -> dict[str, Any] | None:
        """Return the last sealed poll and its final aggregate counts."""
        self.purge()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM polls WHERE status = 'closed' ORDER BY created_at DESC LIMIT 1").fetchone()
            if row is None:
                return None
            result, _ = self._result_conn(conn, row)
            return {**self._row(row), "results": result}

    def publish(self, poll_id: str, digest: str, actor: str, ledger: Ledger) -> dict[str, Any]:
        """Append the human publication decision before making the proposal visible."""
        self.active()
        now = self.now()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM polls WHERE id = ? AND status = 'draft'", (poll_id,)).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise LookupError("Taslak bulunamadı ya da saklama süresi doldu.")
            data = json.loads(row["data"])
            if data["digest"] != digest:
                conn.execute("ROLLBACK")
                raise ValueError("Taslak değişti; önizlemeyi yeniden açın.")
            active = conn.execute(
                "SELECT 1 FROM polls WHERE status = 'active' AND closes_at > ? LIMIT 1", (now.isoformat(),)
            ).fetchone()
            if active:
                conn.execute("ROLLBACK")
                raise ValueError("Yayında bir anket var; önce onu bitirin.")
            entry = ledger.append(
                PUBLISHED_KIND,
                actor=actor,
                entity_id=f"poll:{poll_id}",
                detail={
                    "kind": PUBLISHED_KIND,
                    "poll_id": poll_id,
                    "question": data["question"],
                    "options": [option["label"] for option in data["options"]],
                    "target": data["target"],
                    "closes_at": row["closes_at"],
                    "sha256": data["digest"],
                },
            )
            data["audit"].append({"act": "published", "at": entry.at.isoformat(), "by": actor, "ledger_entry_id": entry.id})
            expires = closes_at_for(dt.datetime.fromisoformat(row["closes_at"]).astimezone(ISTANBUL_TZ).date())
            expires += dt.timedelta(days=TTL_DAYS)
            conn.execute(
                "UPDATE polls SET status = 'active', expires_at = ?, data = ? WHERE id = ?",
                (expires.isoformat(), json.dumps(data, ensure_ascii=False, separators=(",", ":")), poll_id),
            )
            conn.execute("COMMIT")
        return self.get(poll_id) or {}

    def vote(self, poll_id: str, device_id: str, choice: str) -> str:
        """Count one choice atomically while storing the salted voter key separately."""
        self.active()
        now = self.now().isoformat()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM polls WHERE id = ? AND status = 'active'", (poll_id,)).fetchone()
            if row is None or row["closes_at"] <= now:
                conn.execute("ROLLBACK")
                return "closed"
            data = json.loads(row["data"])
            if choice not in {option["key"] for option in data["options"]}:
                conn.execute("ROLLBACK")
                return "bad_choice"
            voter = hashlib.sha256(f"{data['salt']}:{device_id}".encode()).hexdigest()[:32]
            inserted = conn.execute(
                "INSERT INTO poll_voters (poll_id, voter) VALUES (?, ?) ON CONFLICT (poll_id, voter) DO NOTHING",
                (poll_id, voter),
            ).rowcount
            if not inserted:
                conn.execute("ROLLBACK")
                return "already"
            conn.execute(
                "INSERT INTO poll_tallies (poll_id, choice, count) VALUES (?, ?, 1) "
                "ON CONFLICT (poll_id, choice) DO UPDATE SET count = count + 1",
                (poll_id, choice),
            )
            conn.execute("COMMIT")
        return "ok"

    def close(self, poll_id: str, reason: str, actor: str, ledger: Ledger) -> dict[str, Any]:
        """Seal a human closure with masked, bounded reasoning and a final count digest."""
        self.purge()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM polls WHERE id = ? AND status = 'active'", (poll_id,)).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise LookupError("Yayındaki anket bulunamadı.")
            result, counts = self._result_conn(conn, row)
            masked, _, _ = mask_labels(clean_poll_text(reason))
            masked = masked[:160]
            entry = ledger.append(
                CLOSED_KIND,
                actor=actor,
                entity_id=f"poll:{poll_id}",
                detail=self._closed_detail(poll_id, "operator", masked, counts, result["total"]),
            )
            data = json.loads(row["data"])
            data["audit"].append(
                {"act": "closed", "at": entry.at.isoformat(), "by": actor, "how": "operator", "ledger_entry_id": entry.id}
            )
            conn.execute(
                "UPDATE polls SET status = 'closed', data = ? WHERE id = ?",
                (json.dumps(data, ensure_ascii=False, separators=(",", ":")), poll_id),
            )
            conn.execute("COMMIT")
        return {**(self.get(poll_id) or {}), "results": result}

    def results(self, poll_id: str) -> dict[str, Any] | None:
        """Read separated aggregate counts for an active or closed poll."""
        self.purge()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM polls WHERE id = ? AND status IN ('active', 'closed')", (poll_id,)).fetchone()
            if row is None:
                return None
            result, _ = self._result_conn(conn, row)
            return result

    def _close_expired(self, conn: sqlite3.Connection, row: sqlite3.Row) -> None:
        """Seal an overdue poll exactly once; the caller holds the store lock."""
        data = json.loads(row["data"])
        if any(item["act"] == "closed" for item in data["audit"]):
            conn.execute("UPDATE polls SET status = 'closed' WHERE id = ?", (row["id"],))
            return
        result, counts = self._result_conn(conn, row)
        actor = "sistem (süre doldu)"
        entry = self.ledger.append(  # type: ignore[union-attr]
            CLOSED_KIND,
            actor=actor,
            entity_id=f"poll:{row['id']}",
            detail=self._closed_detail(row["id"], "time", None, counts, result["total"]),
        )
        data["audit"].append(
            {"act": "closed", "at": entry.at.isoformat(), "by": actor, "how": "time", "ledger_entry_id": entry.id}
        )
        conn.execute(
            "UPDATE polls SET status = 'closed', data = ? WHERE id = ?",
            (json.dumps(data, ensure_ascii=False, separators=(",", ":")), row["id"]),
        )

    def _closed_detail(self, poll_id: str, how: str, reason: str | None, counts: dict[str, int], total: int) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "kind": CLOSED_KIND,
            "poll_id": poll_id,
            "how": how,
            "total": total,
            "counts": counts,
            "sha256": hashlib.sha256(canonical(counts).encode("utf-8")).hexdigest(),
        }
        if reason is not None:
            detail["reason"] = reason
        return detail

    def _result_conn(self, conn: sqlite3.Connection, row: sqlite3.Row) -> tuple[dict[str, Any], dict[str, int]]:
        data = json.loads(row["data"])
        stored = {
            item["choice"]: item["count"]
            for item in conn.execute("SELECT choice, count FROM poll_tallies WHERE poll_id = ?", (row["id"],))
        }
        counts = {option["key"]: stored.get(option["key"], 0) for option in data["options"]}
        return tally(counts, data["options"]), counts

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            **{key: row[key] for key in ("id", "status", "created_at", "closes_at", "expires_at")},
            **json.loads(row["data"]),
        }
