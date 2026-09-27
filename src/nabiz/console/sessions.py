"""SQLite-backed OIDC flow and server session records; raw session tokens never reach disk."""

from __future__ import annotations

import hashlib
import os
import pathlib
import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi import Response

COOKIE = "nabiz_session"
FLOW_SECONDS = 600
SESSION_SECONDS = 12 * 3600


@dataclass(frozen=True)
class PendingFlow:
    nonce: str
    verifier: str


@dataclass(frozen=True)
class Session:
    account_id: str
    provider: str
    subject: str
    expires_at: int


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SessionStore:
    """Short-lived one-use flows and revocable sessions, safe across server processes."""

    def __init__(self, path: str | pathlib.Path) -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
            except FileExistsError:
                pass
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS pending_flows (
                    state_hash TEXT PRIMARY KEY, provider TEXT NOT NULL, nonce TEXT NOT NULL,
                    verifier TEXT NOT NULL, expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL, provider TEXT NOT NULL,
                    subject TEXT NOT NULL, expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_by_account ON sessions(account_id);
            """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout = 10000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def put_flow(self, state: str, provider: str, nonce: str, verifier: str, *, now: int | None = None) -> None:
        now = int(time.time()) if now is None else now
        with self._connect() as db:
            db.execute("INSERT INTO pending_flows VALUES (?, ?, ?, ?, ?)",
                       (_hash(state), provider, nonce, verifier, now + FLOW_SECONDS))

    def take_flow(self, state: str, provider: str, *, now: int | None = None) -> PendingFlow | None:
        now = int(time.time()) if now is None else now
        if not state or len(state) > 128:
            return None
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT provider, nonce, verifier, expires_at FROM pending_flows WHERE state_hash = ?",
                             (_hash(state),)).fetchone()
            db.execute("DELETE FROM pending_flows WHERE state_hash = ?", (_hash(state),))
            db.commit()
        if row is None or row[0] != provider or row[3] <= now:
            return None
        return PendingFlow(row[1], row[2])

    def create(self, account_id: str, provider: str, subject: str, *, now: int | None = None) -> str:
        """Return a fresh bearer cookie only after an account has consented and been resolved by provider+subject."""
        if not account_id or not provider or not subject:
            raise ValueError("A verified account identity is required")
        now = int(time.time()) if now is None else now
        token = secrets.token_urlsafe(32)
        with self._connect() as db:
            db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                       (_hash(token), account_id, provider, subject, now + SESSION_SECONDS))
        return token

    def get(self, token: str | None, *, now: int | None = None) -> Session | None:
        now = int(time.time()) if now is None else now
        if not token or len(token) > 128:
            return None
        with self._connect() as db:
            row = db.execute("SELECT account_id, provider, subject, expires_at FROM sessions "
                             "WHERE token_hash = ? AND expires_at > ?", (_hash(token), now)).fetchone()
        return Session(*row) if row else None

    def revoke(self, token: str | None) -> bool:
        if not token or len(token) > 128:
            return False
        with self._connect() as db:
            return db.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),)).rowcount > 0

    def revoke_account(self, account_id: str) -> int:
        with self._connect() as db:
            return db.execute("DELETE FROM sessions WHERE account_id = ?", (account_id,)).rowcount

    def purge_expired(self, *, now: int | None = None) -> tuple[int, int]:
        now = int(time.time()) if now is None else now
        with self._connect() as db:
            flows = db.execute("DELETE FROM pending_flows WHERE expires_at <= ?", (now,)).rowcount
            sessions = db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,)).rowcount
        return flows, sessions


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, secure=True, samesite="lax", path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="lax", path="/")
