"""Example accounts: an e-mail and followed topics, kept on the server only with explicit consent.

This is the one exception to "no personal data server-side" (``docs/NABIZ.md`` §1.3), decided
by the owner on 26 Sep 2026 and recorded as DECISIONS #38. Its limits are the design:

* **Nothing without consent.** :meth:`AccountStore.create` refuses (:class:`ConsentRequired`)
  before it opens a transaction when the consent box was not ticked; no row, no outbox file.
* **What a row holds:** an e-mail address, which example provider was used, the tier, when and to
  which consent text the person agreed, and the topics they follow (a metro line, a station, a
  bus line or a keyword: never a location, never a coordinate). The sign-in token is stored only
  as its SHA-256.
* **Example sign-in only.** No İBB, İstanbulkart or Google account is contacted: the providers in
  :data:`PROVIDERS` are labelled "(örnek)", the SMS code is shown on the screen, and no address is
  verified. So a sign-in always makes a new account; typing someone's address never opens theirs.
* **Deletion.** :meth:`AccountStore.delete` removes the account and its follows in one transaction;
  the API also deletes its outbox files. An account unused for :data:`INACTIVE_DAYS` is purged.

The database is a small SQLite file (``NABIZ_ACCOUNTS_DB``, default ``data/accounts/accounts.sqlite``,
gitignored). Nothing here logs an address or a token.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import secrets
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.models import ISTANBUL_TZ, utcnow

DEFAULT_DB = "data/accounts/accounts.sqlite"
#: An account nobody used for this long is deleted with its follows (KVKK: kept no longer than needed).
INACTIVE_DAYS = 365
#: Followed topics per account; a visitor without one keeps up to three on the device.
ACCOUNT_FOLLOW_LIMIT = 10
DEVICE_FOLLOW_LIMIT = 3
CONSENT_VERSION = "2026-09-26"
CONSENT_TEXT = (
    "Açık rızamla e-posta adresimin ve takip ettiğim konuların (hat, istasyon ya da anahtar kelime) bu "
    "projenin sunucusunda saklanmasını ve takip ettiğim konularda günde en çok bir özet e-posta "
    "hazırlanmasını kabul ediyorum. Hesabımı sildiğimde ya da 12 ay kullanmadığımda kayıt silinir. "
    "Konum, kimlik ve sağlık bilgisi istenmez ve saklanmaz."
)
#: The example sign-ins. None of them contacts the real service; every screen says so.
EXAMPLE_BAND = "Örnek hesap · gerçek İBB/İstanbulkart bağlantısı yok · entegrasyon İBB izni gerektirir"
EXAMPLE_SMS_CODE = "123456"
PROVIDERS: dict[str, dict[str, str]] = {
    "ibb": {"label": "İBB hesabı ile giriş (örnek)", "tier": "ibb", "flow": "email"},
    "istanbulkart": {"label": "İstanbulkart hesabı ile SMS girişi (örnek)", "tier": "ibb", "flow": "sms"},
    "google": {"label": "Google ile giriş (örnek)", "tier": "eposta", "flow": "email"},
}
EMAIL = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}$")


class ConsentRequired(ValueError):
    """The consent box was not ticked: nothing is written."""


class FollowLimit(ValueError):
    """The account already follows :data:`ACCOUNT_FOLLOW_LIMIT` topics."""


@dataclass(frozen=True)
class Account:
    id: str
    email: str
    provider: str
    tier: str
    consent_at: str
    consent_version: str
    created_at: str
    last_seen_on: str
    last_digest_on: str | None = None

    def public(self) -> dict[str, Any]:
        """What the person's own page shows about their account."""
        return {
            "email": self.email,
            "provider": self.provider,
            "provider_label": PROVIDERS.get(self.provider, {}).get("label", self.provider),
            "tier": self.tier,
            "consent_at": self.consent_at,
            "consent_version": self.consent_version,
            "created_at": self.created_at,
            "example": True,
        }


def valid_email(value: str) -> str:
    """The address, trimmed and lower-cased, or :class:`ValueError`. Syntax only: nothing is verified."""
    email = str(value or "").strip().lower()
    if len(email) > 254 or not EMAIL.match(email):
        raise ValueError("E-posta adresi geçerli görünmüyor.")
    return email


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def db_path_from_env() -> pathlib.Path:
    path = pathlib.Path(os.environ.get("NABIZ_ACCOUNTS_DB") or DEFAULT_DB).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


def _today(now: dt.datetime) -> str:
    return now.astimezone(ISTANBUL_TZ).date().isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    provider TEXT NOT NULL,
    tier TEXT NOT NULL,
    consent_at TEXT NOT NULL,
    consent_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_on TEXT NOT NULL,
    last_digest_on TEXT
);
CREATE TABLE IF NOT EXISTS follows (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    label TEXT NOT NULL,
    added_at TEXT NOT NULL,
    last_state TEXT,
    UNIQUE (account_id, kind, value)
);
CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
_ACCOUNT_COLUMNS = "id, email, provider, tier, consent_at, consent_version, created_at, last_seen_on, last_digest_on"


class AccountStore:
    """The accounts file. One connection, one lock: a handful of writes a day."""

    def __init__(self, path: str | pathlib.Path, *, clock: Any = utcnow) -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)

    @classmethod
    def from_env(cls) -> AccountStore:
        return cls(db_path_from_env())

    def close(self) -> None:
        self._db.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    def secret(self) -> bytes:
        """This file's own random key, for the unsubscribe links in its e-mails."""
        with self._tx() as db:
            row = db.execute("SELECT value FROM meta WHERE name = 'link_key'").fetchone()
            if row is None:
                value = secrets.token_hex(32)
                db.execute("INSERT INTO meta (name, value) VALUES ('link_key', ?)", (value,))
                return bytes.fromhex(value)
            return bytes.fromhex(row[0])

    # -- accounts ------------------------------------------------------------------------
    def create(self, *, email: str, provider: str, consent: bool) -> tuple[Account, str]:
        """A new example account and its sign-in token. Refuses before writing without consent."""
        if consent is not True:
            raise ConsentRequired("Hesap için açık rıza kutusu işaretlenmeli.")
        if provider not in PROVIDERS:
            raise ValueError("Bilinmeyen örnek sağlayıcı.")
        address = valid_email(email)
        now = self._clock()
        token = secrets.token_urlsafe(32)
        account = Account(
            id=secrets.token_hex(12),
            email=address,
            provider=provider,
            tier=PROVIDERS[provider]["tier"],
            consent_at=now.isoformat(timespec="seconds"),
            consent_version=CONSENT_VERSION,
            created_at=now.isoformat(timespec="seconds"),
            last_seen_on=_today(now),
        )
        with self._tx() as db:
            db.execute(
                "INSERT INTO accounts (id, token_hash, email, provider, tier, consent_at, consent_version, created_at, "
                "last_seen_on) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (account.id, token_hash(token), account.email, account.provider, account.tier, account.consent_at,
                 account.consent_version, account.created_at, account.last_seen_on),
            )  # fmt: skip
        return account, token

    def by_token(self, token: str | None) -> Account | None:
        """The account a token opens, marked as used today; ``None`` for no token or an unknown one."""
        if not token or len(token) > 128:
            return None
        today = _today(self._clock())
        with self._tx() as db:
            row = db.execute(f"SELECT {_ACCOUNT_COLUMNS} FROM accounts WHERE token_hash = ?", (token_hash(token),)).fetchone()
            if row is None:
                return None
            if row[7] != today:
                db.execute("UPDATE accounts SET last_seen_on = ? WHERE id = ?", (today, row[0]))
        return Account(*row[:7], today, row[8])

    def delete(self, account_id: str) -> bool:
        """Remove the account and every follow of it. ``True`` when there was one."""
        with self._tx() as db:
            db.execute("DELETE FROM follows WHERE account_id = ?", (account_id,))
            return db.execute("DELETE FROM accounts WHERE id = ?", (account_id,)).rowcount > 0

    def purge_inactive(self, days: int = INACTIVE_DAYS) -> list[str]:
        """Delete accounts not used for ``days``; the ids deleted, so their outbox goes too."""
        cutoff = (self._clock().astimezone(ISTANBUL_TZ).date() - dt.timedelta(days=days)).isoformat()
        with self._tx() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM accounts WHERE last_seen_on < ?", (cutoff,))]
            for account_id in ids:
                db.execute("DELETE FROM follows WHERE account_id = ?", (account_id,))
                db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        return ids

    def accounts_with_follows(self) -> list[Account]:
        with self._lock:
            rows = self._db.execute(
                f"SELECT {_ACCOUNT_COLUMNS} FROM accounts WHERE id IN (SELECT account_id FROM follows) ORDER BY created_at"
            ).fetchall()
        return [Account(*row) for row in rows]

    def mark_digest(self, account_id: str, day: str) -> None:
        with self._tx() as db:
            db.execute("UPDATE accounts SET last_digest_on = ? WHERE id = ?", (day, account_id))

    def follows(self, account_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, kind, value, label, added_at, last_state FROM follows WHERE account_id = ? ORDER BY added_at, id",
                (account_id,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "kind": r[1],
                "value": r[2],
                "label": r[3],
                "added_at": r[4],
                "last_state": json.loads(r[5]) if r[5] else None,
            }
            for r in rows
        ]

    def add_follow(self, account_id: str, *, kind: str, value: str, label: str) -> dict[str, Any]:
        """Follow a topic (an existing one comes back as it is). :class:`FollowLimit` past the limit."""
        with self._tx() as db:
            row = db.execute(
                "SELECT id, added_at FROM follows WHERE account_id = ? AND kind = ? AND value = ?", (account_id, kind, value)
            ).fetchone()
            if row is not None:
                return {"id": row[0], "kind": kind, "value": value, "label": label, "added_at": row[1]}
            held = db.execute("SELECT COUNT(*) FROM follows WHERE account_id = ?", (account_id,)).fetchone()[0]
            if held >= ACCOUNT_FOLLOW_LIMIT:
                raise FollowLimit(f"Hesapla en çok {ACCOUNT_FOLLOW_LIMIT} konu takip edilebilir.")
            follow = {"id": secrets.token_hex(8), "kind": kind, "value": value, "label": label,
                      "added_at": self._clock().isoformat(timespec="seconds")}  # fmt: skip
            db.execute(
                "INSERT INTO follows (id, account_id, kind, value, label, added_at) VALUES (?, ?, ?, ?, ?, ?)",
                (follow["id"], account_id, kind, value, label, follow["added_at"]),
            )
        return follow

    def follow_owner(self, follow_id: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT account_id FROM follows WHERE id = ?", (follow_id,)).fetchone()
        return row[0] if row else None

    def remove_follow(self, account_id: str, follow_id: str) -> bool:
        with self._tx() as db:
            return db.execute("DELETE FROM follows WHERE id = ? AND account_id = ?", (follow_id, account_id)).rowcount > 0

    def set_follow_state(self, follow_id: str, state: dict[str, str]) -> None:
        """The alerts a follow saw last time (key → sentence): public city data, for the next diff."""
        with self._tx() as db:
            db.execute("UPDATE follows SET last_state = ? WHERE id = ?", (json.dumps(state, ensure_ascii=False), follow_id))
