"""Durable per-identity Istanbul-day quotas with atomic SQLite admissions."""

from __future__ import annotations

import datetime as dt
import os
import pathlib
import secrets
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.models import ISTANBUL_TZ, utcnow
from nabiz.console.quota import ADDRESS_SHARE, DEVICE_ID, Holder, QuotaBook, Tier, address_key, tiers_from_env

DEFAULT_DB = "data/accounts/quota.sqlite"


class PersistentQuotaBook(QuotaBook):
    """The QuotaBook public API backed by transactions shared across processes and restarts."""

    def __init__(
        self, path: str | pathlib.Path, tiers: Mapping[str, Tier] | None = None, *,
        clock: Callable[[], dt.datetime] = utcnow,
    ) -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
            except FileExistsError:
                pass
        self.tiers = dict(tiers or tiers_from_env())
        self._clock = clock
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS quota_meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS quota_counts ("
                       "day TEXT NOT NULL, holder_key TEXT NOT NULL, questions INTEGER NOT NULL DEFAULT 0, "
                       "model_calls INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(day, holder_key))")
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO quota_meta VALUES ('salt', ?)", (secrets.token_hex(32),))
            self._salt = bytes.fromhex(db.execute("SELECT value FROM quota_meta WHERE name = 'salt'").fetchone()[0])
            db.commit()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> PersistentQuotaBook:
        env = os.environ if env is None else env
        path = pathlib.Path(env.get("NABIZ_QUOTA_DB") or DEFAULT_DB).expanduser()
        return cls(path if path.is_absolute() else REPO_ROOT / path, tiers_from_env(env))

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout = 10000")
        try:
            yield db
        finally:
            db.close()

    def _day_now(self) -> str:
        return self._clock().astimezone(ISTANBUL_TZ).date().isoformat()

    def holder(self, *, device: str | None, host: str | None, account_id: str | None = None, tier: str = "cihaz") -> Holder:
        """A device gets its own bucket under its address's shared cap, as in QuotaBook, so a
        client that mints a fresh device id per request cannot mint fresh model calls."""
        if account_id:
            return Holder(self.tiers.get(tier, self.tiers["cihaz"]), self.pseudonym("hesap", account_id))
        address = self.pseudonym("adres", address_key(host))
        if device and DEVICE_ID.fullmatch(device):
            return Holder(self.tiers["cihaz"], self.pseudonym("cihaz", device), address)
        return Holder(self.tiers["cihaz"], address)

    @staticmethod
    def _counts(db: sqlite3.Connection, day: str, key: str) -> tuple[int, int]:
        row = db.execute("SELECT questions, model_calls FROM quota_counts WHERE day = ? AND holder_key = ?",
                         (day, key)).fetchone()
        return (int(row[0]), int(row[1])) if row else (0, 0)

    def _left(self, db: sqlite3.Connection, day: str, holder: Holder) -> tuple[int, int]:
        tier = holder.tier
        questions, calls = self._counts(db, day, holder.key)
        q_left, c_left = tier.questions - questions, tier.model_calls - calls
        if holder.address is not None and holder.address != holder.key:
            shared_q, shared_c = self._counts(db, day, holder.address)
            q_left = min(q_left, tier.questions * ADDRESS_SHARE - shared_q)
            c_left = min(c_left, tier.model_calls * ADDRESS_SHARE - shared_c)
        return max(0, q_left), max(0, c_left)

    @staticmethod
    def _keys(holder: Holder) -> set[str]:
        return {holder.key} | ({holder.address} if holder.address else set())

    @staticmethod
    def _add(db: sqlite3.Connection, day: str, key: str, *, questions: int = 0, calls: int = 0) -> None:
        db.execute("INSERT INTO quota_counts(day, holder_key, questions, model_calls) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT(day, holder_key) DO UPDATE SET questions = questions + excluded.questions, "
                   "model_calls = model_calls + excluded.model_calls", (day, key, questions, calls))

    def admit(self, holder: Holder) -> bool:
        day = self._day_now()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            allowed = self._left(db, day, holder)[0] > 0
            if allowed:
                for key in self._keys(holder):
                    self._add(db, day, key, questions=1)
            db.commit()
        return allowed

    def reserve_calls(self, holder: Holder, calls: int) -> bool:
        """Atomically claim model-call capacity before provider reservation."""
        if calls <= 0:
            return False
        day = self._day_now()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            allowed = calls <= self._left(db, day, holder)[1]
            if allowed:
                for key in self._keys(holder):
                    self._add(db, day, key, calls=calls)
            db.commit()
        return allowed

    def refund_calls(self, holder: Holder, calls: int) -> None:
        """Return an unused reservation; callers may refund only their own reserved amount."""
        if calls <= 0:
            return
        day = self._day_now()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            for key in self._keys(holder):
                _, spent = self._counts(db, day, key)
                self._add(db, day, key, calls=-min(calls, spent))
            db.commit()

    def calls_left(self, holder: Holder) -> int:
        with self._db() as db:
            return self._left(db, self._day_now(), holder)[1]

    def spend_calls(self, holder: Holder, calls: int) -> None:
        """Compatibility with Meter; P00 must use reserve/refund for concurrent model requests."""
        if calls > 0:
            self.reserve_calls(holder, calls)

    def status(self, holder: Holder) -> dict[str, Any]:
        day = self._day_now()
        with self._db() as db:
            q_left, c_left = self._left(db, day, holder)
        return {
            "tier": holder.tier.key, "tier_label": holder.tier.label,
            "questions_limit": holder.tier.questions, "questions_left": q_left,
            "model_calls_limit": holder.tier.model_calls, "model_calls_left": c_left,
            "model_open": q_left > 0 and c_left > 0, "day": day,
        }

    def erase_account(self, account_id: str) -> int:
        """Forget all quota counters for a deleted account without touching other holders."""
        key = self.pseudonym("hesap", account_id)
        with self._db() as db:
            return db.execute("DELETE FROM quota_counts WHERE holder_key = ?", (key,)).rowcount

    def purge_old_days(self, *, keep_days: int = 2) -> int:
        cutoff = (self._clock().astimezone(ISTANBUL_TZ).date() - dt.timedelta(days=keep_days)).isoformat()
        with self._db() as db:
            return db.execute("DELETE FROM quota_counts WHERE day < ?", (cutoff,)).rowcount
