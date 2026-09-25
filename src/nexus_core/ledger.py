"""The decision ledger: an append-only SQLite log where every entry seals the one before it.

Each entry holds when, who, what kind of step, which signal and a JSON detail, plus the hash
of the previous entry and its own hash over all of that. :meth:`Ledger.verify` recomputes the
chain: an edited detail, a reordered or a deleted row breaks it at the first bad entry.
:meth:`Ledger.trace` returns one signal's steps in order, the "Bu karar nasıl verildi?"
replay. The rest of NEXUS derives its state by replaying these entries (``state.py``), so the
queue, the stats and the rule drafts are all readings of the same sealed record.

What the chain cannot catch on its own: someone deleting the newest entries and nothing else.
:attr:`VerifyResult.head` is the last hash; writing it down elsewhere (a commit, a report)
anchors the tail.

Storage is one SQLite file, by default ``data/nexus/nexus.db`` (``NEXUS_DB_PATH`` overrides
it; tests pass a temporary path). Each call opens its own short connection and appends run
inside ``BEGIN IMMEDIATE`` under a process lock, so the console's worker threads never
interleave two appends into one chain position. Details hold decisions and reasons, never a
citizen's profile: there is none on the server to write.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import pathlib
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from nexus_core.signals import Clock, as_utc, system_clock

DEFAULT_PATH = pathlib.Path("data/nexus/nexus.db")
PATH_ENV = "NEXUS_DB_PATH"
GENESIS = "0" * 64

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    signal_id TEXT,
    entity_id TEXT,
    actor TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS entries_signal ON entries (signal_id);
CREATE INDEX IF NOT EXISTS entries_entity ON entries (entity_id);
"""


class EntryKind(StrEnum):
    SIGNAL = "signal_received"
    ROUTED = "routed"
    REFLEX_CLOSED = "reflex_closed"
    REFLEX_FAILED = "reflex_failed"
    ARENA_DRAFTED = "arena_drafted"
    APPROVAL = "approval"
    RULE_ADOPTED = "rule_adopted"
    RULE_REVOKED = "rule_revoked"


class LedgerEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    at: dt.datetime
    signal_id: str | None
    entity_id: str | None
    actor: str
    kind: str
    detail: dict[str, Any]
    prev_hash: str
    hash: str


class VerifyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    entries: int
    head: str
    first_bad_id: int | None = None
    problem: str | None = None


class TraceStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry_id: int
    at: dt.datetime
    actor: str
    kind: str
    detail: dict[str, Any]


class Trace(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_id: str
    steps: tuple[TraceStep, ...]
    hash_ok: bool


def default_path() -> pathlib.Path:
    """``NEXUS_DB_PATH`` when set, else ``data/nexus/nexus.db`` under the working directory."""
    return pathlib.Path(os.environ.get(PATH_ENV) or DEFAULT_PATH)


def canonical(detail: dict[str, Any]) -> str:
    """The one JSON spelling of a detail: sorted keys, no spaces, UTF-8 kept."""
    return json.dumps(detail, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def entry_hash(fields: tuple[Any, ...]) -> str:
    """sha256 over ``(id, at, signal_id, entity_id, actor, kind, detail, prev_hash)``."""
    return hashlib.sha256(json.dumps(list(fields), ensure_ascii=False).encode("utf-8")).hexdigest()


def _row_entry(row: sqlite3.Row) -> LedgerEntry:
    return LedgerEntry(
        id=row["id"],
        at=dt.datetime.fromisoformat(row["at"]),
        signal_id=row["signal_id"],
        entity_id=row["entity_id"],
        actor=row["actor"],
        kind=row["kind"],
        detail=json.loads(row["detail"]),
        prev_hash=row["prev_hash"],
        hash=row["hash"],
    )


def _row_fields(row: sqlite3.Row) -> tuple[Any, ...]:
    return (row["id"], row["at"], row["signal_id"], row["entity_id"], row["actor"], row["kind"], row["detail"], row["prev_hash"])


class Ledger:
    """The hash-chained log. Append, read back, verify, trace."""

    def __init__(self, path: str | pathlib.Path | None = None, *, clock: Clock = system_clock) -> None:
        self.path = pathlib.Path(path) if path is not None else default_path()
        self._clock = clock
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def append(
        self,
        kind: EntryKind | str,
        *,
        actor: str,
        detail: dict[str, Any],
        signal_id: str | None = None,
        entity_id: str | None = None,
    ) -> LedgerEntry:
        """Seal one entry onto the end of the chain and return it."""
        at = as_utc(self._clock()).isoformat()
        text = canonical(detail)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                last = conn.execute("SELECT id, hash FROM entries ORDER BY id DESC LIMIT 1").fetchone()
                entry_id, prev = (last["id"] + 1, last["hash"]) if last else (1, GENESIS)
                fields = (entry_id, at, signal_id, entity_id, actor, str(kind), text, prev)
                digest = entry_hash(fields)
                conn.execute("INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (*fields, digest))
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return LedgerEntry(
            id=entry_id,
            at=dt.datetime.fromisoformat(at),
            signal_id=signal_id,
            entity_id=entity_id,
            actor=actor,
            kind=str(kind),
            detail=json.loads(text),
            prev_hash=prev,
            hash=digest,
        )

    def entries(
        self,
        *,
        signal_id: str | None = None,
        entity_id: str | None = None,
        kinds: Iterable[str] | None = None,
    ) -> list[LedgerEntry]:
        """Entries in chain order, optionally for one signal, one entity or some kinds."""
        clauses, params = [], []
        if signal_id is not None:
            clauses.append("signal_id = ?")
            params.append(signal_id)
        if entity_id is not None:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        if kinds is not None:
            wanted = [str(k) for k in kinds]
            if not wanted:
                return []
            clauses.append(f"kind IN ({', '.join('?' for _ in wanted)})")
            params.extend(wanted)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            # Only the fixed clauses above are formatted in; every value is a bound parameter.
            rows = conn.execute(f"SELECT * FROM entries{where} ORDER BY id", params).fetchall()
        return [_row_entry(row) for row in rows]

    def has_signal(self, signal_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM entries WHERE signal_id = ? LIMIT 1", (signal_id,)).fetchone()
        return row is not None

    def verify(self) -> VerifyResult:
        """Recompute every hash and link; report the first entry that does not fit."""
        prev, count = GENESIS, 0
        with self._connect() as conn:
            for row in conn.execute("SELECT * FROM entries ORDER BY id"):
                count += 1
                problem = self._check(row, count, prev)
                if problem:
                    return VerifyResult(ok=False, entries=count, head=prev, first_bad_id=row["id"], problem=problem)
                prev = row["hash"]
        return VerifyResult(ok=True, entries=count, head=prev)

    @staticmethod
    def _check(row: sqlite3.Row, position: int, prev: str) -> str | None:
        if row["id"] != position:
            return f"entry {position} is missing (found id {row['id']})"
        if row["prev_hash"] != prev:
            return "prev_hash does not match the entry before"
        if entry_hash(_row_fields(row)) != row["hash"]:
            return "hash does not match the entry's content"
        return None

    def trace(self, signal_id: str) -> Trace:
        """One signal's steps in order, with the whole chain's verification."""
        steps = tuple(
            TraceStep(entry_id=e.id, at=e.at, actor=e.actor, kind=e.kind, detail=e.detail)
            for e in self.entries(signal_id=signal_id)
        )
        return Trace(signal_id=signal_id, steps=steps, hash_ok=self.verify().ok)
