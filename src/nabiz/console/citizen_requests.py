"""Citizen requests to a person: the NEXUS signal, its own table with a 30-day life, and the ledger lines.

A request is what a visitor sends when the assistant could not help and they chose, with the
consent sentence in front of them, to ask an İBB operator. It is **not** an emergency path: an
emergency never reaches this module (:mod:`nabiz.console.requests_api` sends it to the emergency card
first), and an operator is no replacement for the emergency services.

**What the server keeps.** Only the masked text (E14's :func:`~nabiz.console.pii_guard.mask_labels`),
its language, its Turkish translation, a keyword category and the times, in a table of its own
(``citizen_requests`` in ``NABIZ_REQUESTS_DB_PATH``, by default ``citizen_requests.db`` beside the
NEXUS ledger). Every row is deleted 30 days after it was made (:data:`TTL_DAYS`); the purge runs on
every open, write and read. The hash-chained ledger gets no citizen text: a ``citizen_request``
line with the code, language, category and lengths when the request arrives, and an
``operator_reply`` line with a masked summary of the reply when the operator sends one.

**The signal.** Each request is a :class:`nexus_core.Signal` of kind ``citizen_request`` (severity
``info``, source ``citizen:chat``), stored with its row. It is not handed to the NEXUS engine: no
reflex rule and no Arena seat decides anything about a person's question; the operator answers it.

**The code** is eight characters from an alphabet without look-alikes (``K7M2QX9P``): it is the
only key a visitor's device holds, and the only way to read the reply.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import pathlib
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from ibb_mcp.text import normalize_tr
from nabiz.console.pii_guard import mask_labels
from nabiz.console.wiring import ledger_path
from nexus_core.ledger import Ledger
from nexus_core.signals import Clock, Origin, Signal, as_utc, system_clock

PATH_ENV = "NABIZ_REQUESTS_DB_PATH"
TTL_DAYS = 30
#: A request's text, after invisible characters are stripped, and an operator's reply.
MAX_CHARS = 1000
#: Requests one device (the client address the server sees) may send in an hour. A design
#: parameter set by the owner's brief, not a measured value; ``NABIZ_REQUESTS_PER_HOUR`` overrides it.
PER_HOUR = 3
REMEMBERED_DEVICES = 4096
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 8
SIGNAL_KIND = "citizen_request"
REQUEST_KIND = "citizen_request"
REPLY_KIND = "operator_reply"
SUMMARY_CHARS = 160

#: Keyword categories, first match wins; folded Turkish and English words (the operator's triage hint).
CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Asansör ve erişim", ("asansor", "yuruyen merdiven", "tekerlekli", "engelli", "rampa", "elevator", "lift", "wheelchair")),
    ("İstanbulkart", ("istanbulkart", "kart ", "karti", "kartim", "bakiye", "card", "balance")),
    ("Toplu ulaşım", (
        "metro", "otobus", "tramvay", "vapur", "marmaray", "metrobus", "durak", "sefer", "hatt", "bus", "tram", "ferry",
    )),
    ("Otopark", ("otopark", "ispark", "park yeri", "parking")),
    ("Su ve altyapı", ("iski", "su kesintisi", "su ", "kanalizasyon", "dogalgaz", "igdas", "water")),
    ("Çevre ve temizlik", ("cop", "temizlik", "gurultu", "agac", "park ", "garbage", "noise")),
    ("Sosyal destek", ("sosyal destek", "yardim", "burs", "sosyal hizmet", "support", "scholarship")),
)  # fmt: skip
DEFAULT_CATEGORY = "Genel bilgi"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS citizen_requests (
    code TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS citizen_requests_expiry ON citizen_requests (expires_at);
"""


def requests_path(env: Mapping[str, str] | None = None) -> pathlib.Path:
    """``NABIZ_REQUESTS_DB_PATH``, else ``citizen_requests.db`` next to the ledger (so a scratch ledger keeps it)."""
    raw = (os.environ if env is None else env).get(PATH_ENV, "").strip()
    return pathlib.Path(raw) if raw else ledger_path(env).with_name("citizen_requests.db")


def per_hour(env: Mapping[str, str] | None = None) -> int:
    raw = (os.environ if env is None else env).get("NABIZ_REQUESTS_PER_HOUR", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else PER_HOUR


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normal_code(raw: str) -> str | None:
    """The code as stored (upper case, no ``#`` or spaces), or ``None`` when it cannot be one."""
    code = raw.strip().lstrip("#").replace("-", "").replace(" ", "").upper()
    return code if len(code) == CODE_LENGTH and all(ch in CODE_ALPHABET for ch in code) else None


def category_of(*texts: str | None) -> str:
    """The first keyword category any of ``texts`` names (the Turkish translation first), else the default."""
    for text in texts:
        folded = f" {normalize_tr(text or '')} "
        for label, words in CATEGORIES:
            if any(f" {word}" in folded for word in words):
                return label
    return DEFAULT_CATEGORY


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def masked_summary(text: str) -> tuple[str, int]:
    """A reply's first :data:`SUMMARY_CHARS` characters, masked, for the ledger; and how many items were masked."""
    masked, count, _ = mask_labels(text)
    short = masked if len(masked) <= SUMMARY_CHARS else masked[: SUMMARY_CHARS - 3].rstrip() + "..."
    return short, count


class HourlyLimit:
    """At most ``limit`` requests per device in any sliding hour; in memory, bounded, never logged."""

    def __init__(self, limit: int = PER_HOUR, *, window_s: float = 3600.0, devices: int = REMEMBERED_DEVICES) -> None:
        self.limit = limit
        self.window_s = window_s
        self.devices = devices
        self._seen: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, device: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            times = self._seen.pop(device, deque())
            while times and now - times[0] >= self.window_s:
                times.popleft()
            allowed = len(times) < self.limit
            if allowed:
                times.append(now)
            self._seen[device] = times
            while len(self._seen) > self.devices:
                self._seen.popitem(last=False)
            return allowed


@dataclass(frozen=True)
class NewRequest:
    """What the API hands the store: already masked, translated and categorised."""

    original_masked: str
    masked_count: int
    masked_kinds: tuple[str, ...]
    lang: str
    lang_source: str
    chosen_lang: str | None
    turkish: str | None
    translation_status: str
    translation_author: str | None
    category: str
    guard: str | None


def request_signal(code: str, request: NewRequest, now: dt.datetime) -> Signal:
    """The NEXUS signal for one request: kind, entity, time and origin; the masked text stays in the row."""
    return Signal.create(
        kind=SIGNAL_KIND,
        entity_id=f"citizen_request:{code}",
        severity="info",
        observed_at=now,
        provenance=Origin(source="citizen:chat", observed_at=now, mode="live"),
        payload={"lang": request.lang, "category": request.category, "chars": len(request.original_masked)},
    )


class RequestStore:
    """The ``citizen_requests`` table: one row per request, deleted :data:`TTL_DAYS` after it was made."""

    def __init__(self, path: str | pathlib.Path | None = None, *, clock: Clock = system_clock) -> None:
        self.path = pathlib.Path(path) if path is not None else requests_path()
        self._clock = clock
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
        self.purge()

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def now(self) -> dt.datetime:
        return as_utc(self._clock())

    def purge(self) -> int:
        """Delete every row past its expiry; how many went."""
        with self._lock, self._connect() as conn:
            return conn.execute("DELETE FROM citizen_requests WHERE expires_at <= ?", (self.now().isoformat(),)).rowcount

    def create(self, request: NewRequest) -> dict[str, Any]:
        """Store a new request under a fresh code and return its row."""
        self.purge()
        now = self.now()
        expires = now + dt.timedelta(days=TTL_DAYS)
        with self._lock, self._connect() as conn:
            for _ in range(8):
                code = new_code()
                if conn.execute("SELECT 1 FROM citizen_requests WHERE code = ?", (code,)).fetchone() is None:
                    break
            signal = request_signal(code, request, now)
            data = {
                **{key: getattr(request, key) for key in NewRequest.__dataclass_fields__},
                "masked_kinds": list(request.masked_kinds),
                "signal": signal.model_dump(mode="json"),
                "reply": None,
            }
            conn.execute(
                "INSERT INTO citizen_requests VALUES (?, ?, ?, ?, ?, ?)",
                (code, signal.signal_id, now.isoformat(), expires.isoformat(), "waiting", json.dumps(data, ensure_ascii=False)),
            )
        return self.get(code) or {}

    def get(self, code: str) -> dict[str, Any] | None:
        now = self.now().isoformat()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM citizen_requests WHERE code = ? AND expires_at > ?", (code, now)).fetchone()
        return _row(row) if row is not None else None

    def items(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Newest first; waiting ones only when ``status`` says so."""
        self.purge()
        sql, params = "SELECT * FROM citizen_requests WHERE expires_at > ?", [self.now().isoformat()]
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        with self._connect() as conn:
            rows = conn.execute(sql + " ORDER BY created_at DESC LIMIT ?", (*params, limit)).fetchall()
        return [_row(row) for row in rows]

    def answer(self, code: str, reply: dict[str, Any]) -> dict[str, Any] | None:
        """Attach the operator's reply once; ``None`` when the request is gone or already answered."""
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM citizen_requests WHERE code = ? AND status = 'waiting'", (code,)).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return None
            data = json.loads(row["data"])
            data["reply"] = reply
            conn.execute(
                "UPDATE citizen_requests SET status = 'answered', data = ? WHERE code = ?",
                (json.dumps(data, ensure_ascii=False), code),
            )
            conn.execute("COMMIT")
        return self.get(code)


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return {"code": row["code"], "signal_id": row["signal_id"], "created_at": row["created_at"],
            "expires_at": row["expires_at"], "status": row["status"], **json.loads(row["data"])}  # fmt: skip


def ledger_request(ledger: Ledger, row: Mapping[str, Any]) -> int:
    """The ``citizen_request`` line: that a request came, never what it says."""
    entry = ledger.append(
        REQUEST_KIND,
        actor="vatandaş (anonim)",
        entity_id=f"citizen_request:{row['code']}",
        detail={
            "kind": REQUEST_KIND,
            "code": row["code"],
            "request_signal_id": row["signal_id"],
            "lang": row["lang"],
            "category": row["category"],
            "chars": len(row["original_masked"]),
            "masked_count": row["masked_count"],
            "translation": row["translation_status"],
        },
    )
    return entry.id


def ledger_reply(ledger: Ledger, row: Mapping[str, Any], reply: Mapping[str, Any], actor: str) -> int:
    """The ``operator_reply`` line: who, when, which request, and a masked summary of the Turkish reply."""
    summary, _ = masked_summary(reply["text_tr"])
    entry = ledger.append(
        REPLY_KIND,
        actor=actor,
        entity_id=f"citizen_request:{row['code']}",
        detail={
            "kind": REPLY_KIND,
            "code": row["code"],
            "request_signal_id": row["signal_id"],
            "lang": reply["lang"],
            "translation": reply["translation"],
            "summary_tr": summary,
            "masked_count": int(reply.get("masked_count") or 0),
            "chars": len(reply["text_tr"]),
            "sha256": digest(reply["text_tr"]),
        },
    )
    return entry.id
