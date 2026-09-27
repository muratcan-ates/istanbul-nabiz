"""Example-family membership with two-sided consent and opt-in sharing.

The family tables share the example-account SQLite file. Every association is tied to an
account or membership with cascading foreign keys, so deleting a follow, member, or account
also removes the related family data.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import re
import secrets
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from ibb_mcp.models import ISTANBUL_TZ, utcnow
from nabiz.console.accounts import AccountStore
from nabiz.console.pii_guard import scan_pii
from nabiz.console.text_guard import strip_invisible

FAMILY_MAX_MEMBERS, CODE_LENGTH, CODE_TTL_HOURS, REQUEST_TTL_DAYS = 6, 6, 24, 7
JOIN_FAILS_PER_DAY, DISPLAY_NAME_MAX, FAMILY_STOP_LIMIT, FAMILY_CONSENT_VERSION = 10, 24, 6, "2026-09-26"
# Similar-looking symbols and Turkish letter pairs are excluded for spoken, keyboard entry.
CODE_ALPHABET = "23456789ADEFHJKMNPRTY"
FAMILY_CONSENT_TEXT = (
    "Açık rızamla, ailede görünecek adımın ve yalnız benim seçtiğim takip konularımla durak adlarımın, "
    "onayladığım ya da beni onaylayan en çok 5 aile üyesine gösterilmesini kabul ediyorum. E-posta adresim, "
    "konumum ve sorularım paylaşılmaz. Aileden ayrıldığımda ya da hesabımı sildiğimde aile kaydım ve "
    "paylaşımlarım silinir."
)
FAMILY_BAND = "Örnek aile · örnek hesaplarla çalışır · gerçek İBB ya da e-Devlet aile bağı kurulmaz · konum paylaşılmaz"
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS family_groups (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL UNIQUE REFERENCES accounts(id) ON "
    "DELETE CASCADE, code TEXT NOT NULL UNIQUE, code_expires_at TEXT NOT NULL, created_at TEXT NOT NULL);"
    "CREATE TABLE IF NOT EXISTS family_members (id TEXT PRIMARY KEY, group_id TEXT NOT NULL REFERENCES family_groups(id) ON "
    "DELETE CASCADE, account_id TEXT NOT NULL UNIQUE REFERENCES accounts(id) ON DELETE CASCADE, display_name TEXT NOT NULL, "
    "role TEXT NOT NULL CHECK(role IN ('owner','member')), consent_at TEXT NOT NULL, consent_version TEXT NOT NULL, joined_at "
    "TEXT NOT NULL);"
    "CREATE TABLE IF NOT EXISTS family_requests (id TEXT PRIMARY KEY, group_id TEXT NOT NULL REFERENCES family_groups(id) ON "
    "DELETE CASCADE, account_id TEXT NOT NULL UNIQUE REFERENCES accounts(id) ON DELETE CASCADE, display_name TEXT NOT NULL, "
    "check_number INTEGER NOT NULL, consent_at TEXT NOT NULL, consent_version TEXT NOT NULL, requested_at TEXT NOT NULL);"
    "CREATE TABLE IF NOT EXISTS family_shared_follows (member_id TEXT NOT NULL REFERENCES family_members(id) ON DELETE "
    "CASCADE, follow_id TEXT NOT NULL REFERENCES follows(id) ON DELETE CASCADE, PRIMARY KEY(member_id, follow_id));"
    "CREATE TABLE IF NOT EXISTS family_shared_stops (member_id TEXT NOT NULL REFERENCES family_members(id) ON DELETE CASCADE, "
    "line TEXT NOT NULL, stop TEXT NOT NULL, PRIMARY KEY(member_id, line, stop));"
    "CREATE TABLE IF NOT EXISTS family_attempts (account_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE, day "
    "TEXT NOT NULL, failures INTEGER NOT NULL);"
)


class FamilyError(ValueError):
    """An expected family rule failure with its HTTP status and stable public error code."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _error(code: str, message: str, status: int = 400) -> FamilyError:
    return FamilyError(status, code, message)


def _today(now: dt.datetime) -> str:
    return now.astimezone(ISTANBUL_TZ).date().isoformat()


def _stamp(now: dt.datetime) -> str:
    return now.astimezone(dt.UTC).isoformat(timespec="seconds")


def new_family_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(raw: Any) -> str | None:
    code = re.sub(r"[\s-]", "", str(raw or "")).upper()
    return code if len(code) == CODE_LENGTH and all(char in CODE_ALPHABET for char in code) else None


def format_code(code: str) -> str:
    return code[:3] + " " + code[3:]


def clean_display_name(raw: Any) -> str:
    cleaned, _ = strip_invisible(str(raw or ""))
    name = " ".join(cleaned.split())
    if not name or len(name) > DISPLAY_NAME_MAX:
        raise ValueError(f"Görünen ad 1 ile {DISPLAY_NAME_MAX} karakter arasında olmalı.")
    if "@" in name or scan_pii(name):
        raise ValueError("Görünen ada e-posta, telefon ya da kimlik numarası yazmayın.")
    return name


def clean_stop(line: Any, stop: Any) -> tuple[str, str]:
    route, _ = strip_invisible(str(line or ""))
    name, _ = strip_invisible(str(stop or ""))
    route, name = " ".join(route.split()).upper(), " ".join(name.split())
    if not 1 <= len(route) <= 12 or not all(char.isalnum() for char in route):
        raise ValueError("Hat adı 1 ile 12 harf ya da rakamdan oluşmalı.")
    if not 1 <= len(name) <= 80 or scan_pii(name):
        raise ValueError("Durak adı geçersiz ya da kişisel bilgi içeriyor.")
    return route, name


class _FamilyViewMixin:
    def _view(self, db: sqlite3.Connection, account_id: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "state": "none",
            "pending": None,
            "family": None,
            "mine": None,
            "message": "",
            "band": FAMILY_BAND,
            "consent": {"text": FAMILY_CONSENT_TEXT, "version": FAMILY_CONSENT_VERSION},
            "limits": {"members": FAMILY_MAX_MEMBERS, "stops": FAMILY_STOP_LIMIT},
        }
        member = self._member(db, account_id)
        if not member:
            pending = db.execute(
                "SELECT check_number, requested_at FROM family_requests WHERE account_id = ?", (account_id,)
            ).fetchone()
            if pending:
                result.update(state="pending", pending={"check": str(pending[0]), "requested_at": pending[1]})
            return result
        result["state"] = "owner" if member[2] == "owner" else "member"
        group = self._group(db, member[1])
        now = self._clock()
        count = self._family_count(db, member[1])
        members = self._members_view(db, member[1], account_id)
        family: dict[str, Any] = {"count": count, "limit": FAMILY_MAX_MEMBERS, "members": members}
        if member[2] == "owner":
            family["code"] = (
                {
                    "code": group[2],
                    "display": format_code(group[2]),
                    "expires_at": group[3],
                    "expired": group[3] <= _stamp(now),
                }
                if count < FAMILY_MAX_MEMBERS
                else None
            )
            family["requests"] = self._requests_view(db, member[1])
        result["family"] = family
        result["mine"] = self._mine_view(db, member[0], account_id)
        return result

    def _members_view(self, db: sqlite3.Connection, group_id: str, account_id: str) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT id, account_id, display_name, role, joined_at FROM family_members "
            "WHERE group_id = ? ORDER BY CASE role WHEN 'owner' THEN 0 ELSE 1 END, joined_at, id",
            (group_id,),
        ).fetchall()
        return [
            {
                "id": row[0],
                "display_name": row[2],
                "role": row[3],
                "is_me": row[1] == account_id,
                "joined_at": row[4],
                "shares": self._member_shares(db, row[0]),
            }
            for row in rows
        ]

    def _member_shares(self, db: sqlite3.Connection, member_id: str) -> dict[str, Any]:
        follows = db.execute(
            "SELECT f.kind, f.value, f.label FROM family_shared_follows s JOIN follows f ON f.id = s.follow_id "
            "WHERE s.member_id = ? ORDER BY f.added_at, f.id",
            (member_id,),
        ).fetchall()
        stops = db.execute(
            "SELECT line, stop FROM family_shared_stops WHERE member_id = ? ORDER BY line, stop", (member_id,)
        ).fetchall()
        return {
            "follows": [{"kind": row[0], "value": row[1], "label": row[2]} for row in follows],
            "stops": [{"line": row[0], "stop": row[1]} for row in stops],
        }

    def _requests_view(self, db: sqlite3.Connection, group_id: str) -> list[dict[str, Any]]:
        return [
            {"id": row[0], "display_name": row[1], "check": str(row[2]), "requested_at": row[3]}
            for row in db.execute(
                "SELECT id, display_name, check_number, requested_at FROM family_requests "
                "WHERE group_id = ? ORDER BY requested_at, id",
                (group_id,),
            ).fetchall()
        ]

    def _mine_view(self, db: sqlite3.Connection, member_id: str, account_id: str) -> dict[str, Any]:
        follows = self.accounts.follows(account_id)
        shared_ids = {
            row[0] for row in db.execute("SELECT follow_id FROM family_shared_follows WHERE member_id = ?", (member_id,))
        }
        return {
            "follows": [
                {
                    "id": follow["id"],
                    "kind": follow["kind"],
                    "value": follow["value"],
                    "label": follow["label"],
                    "shared": follow["id"] in shared_ids,
                }
                for follow in follows
            ],
            "stops": self._member_shares(db, member_id)["stops"],
        }

    def view(self, account_id: str) -> dict[str, Any]:
        with self._tx() as db:
            return self._view(db, account_id)


class FamilyStore(_FamilyViewMixin):
    """Transactional family membership and selective shares in the account SQLite file."""

    def __init__(self, accounts: AccountStore, *, clock: Any = utcnow) -> None:
        self.accounts, self.path, self._clock = accounts, pathlib.Path(accounts.path), clock
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._purge(self._db)
                yield self._db
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    def _purge(self, db: sqlite3.Connection) -> None:
        cutoff = _stamp(self._clock() - dt.timedelta(days=REQUEST_TTL_DAYS))
        db.execute("DELETE FROM family_requests WHERE requested_at < ?", (cutoff,))
        db.execute("DELETE FROM family_attempts WHERE day < ?", (_today(self._clock()),))

    def purge(self) -> int:
        cutoff = _stamp(self._clock() - dt.timedelta(days=REQUEST_TTL_DAYS))
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                cursor = self._db.execute("DELETE FROM family_requests WHERE requested_at < ?", (cutoff,))
                count = cursor.rowcount
                self._db.execute("DELETE FROM family_attempts WHERE day < ?", (_today(self._clock()),))
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")
        return count

    def _member(self, db: sqlite3.Connection, account_id: str) -> tuple[Any, ...] | None:
        return db.execute(
            "SELECT id, group_id, role, display_name, joined_at FROM family_members WHERE account_id = ?",
            (account_id,),
        ).fetchone()

    def _group(self, db: sqlite3.Connection, group_id: str) -> tuple[Any, ...]:
        return db.execute(
            "SELECT id, owner_id, code, code_expires_at, created_at FROM family_groups WHERE id = ?", (group_id,)
        ).fetchone()

    def _family_count(self, db: sqlite3.Connection, group_id: str) -> int:
        return db.execute("SELECT COUNT(*) FROM family_members WHERE group_id = ?", (group_id,)).fetchone()[0]

    def _has_request(self, db: sqlite3.Connection, account_id: str) -> bool:
        return db.execute("SELECT 1 FROM family_requests WHERE account_id = ?", (account_id,)).fetchone() is not None

    def _unique_code(self, db: sqlite3.Connection, group_id: str | None = None) -> str:
        for _ in range(8):
            code = new_family_code()
            if (
                db.execute("SELECT 1 FROM family_groups WHERE code = ? AND id != COALESCE(?, '')", (code, group_id)).fetchone()
                is None
            ):
                return code
        raise _error("share_invalid", "Kod oluşturulamadı. Yeniden deneyin.", 409)

    def _new_group(self, db: sqlite3.Connection, account_id: str, name: str, now: dt.datetime) -> None:
        group_id, member_id, stamp = secrets.token_hex(12), secrets.token_hex(12), _stamp(now)
        code = self._unique_code(db)
        db.execute(
            "INSERT INTO family_groups (id, owner_id, code, code_expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (group_id, account_id, code, _stamp(now + dt.timedelta(hours=CODE_TTL_HOURS)), stamp),
        )
        db.execute(
            "INSERT INTO family_members VALUES (?, ?, ?, ?, 'owner', ?, ?, ?)",
            (member_id, group_id, account_id, name, stamp, FAMILY_CONSENT_VERSION, stamp),
        )

    def create_code(self, account_id: str, display_name: str, consent: bool) -> dict[str, Any]:
        if consent is not True:
            raise _error("consent_required", "Açık rıza vermeden aile kodu oluşturulamaz.")
        name = _clean_name(display_name)
        with self._tx() as db:
            member = self._member(db, account_id)
            if member and member[2] != "owner":
                raise _error("already_in_family", "Zaten bir aileye üyesiniz.", 409)
            if self._has_request(db, account_id):
                raise _error("request_pending", "Bekleyen katılma isteğiniz var.", 409)
            if not member:
                self._new_group(db, account_id, name, self._clock())
            return self._view(db, account_id)

    def renew_code(self, account_id: str) -> dict[str, Any]:
        with self._tx() as db:
            member = self._member(db, account_id)
            if not member or member[2] != "owner":
                raise _error("not_owner", "Bu işlem yalnız kod sahibine açık.", 403)
            now = self._clock()
            db.execute(
                "UPDATE family_groups SET code = ?, code_expires_at = ? WHERE id = ?",
                (self._unique_code(db, member[1]), _stamp(now + dt.timedelta(hours=CODE_TTL_HOURS)), member[1]),
            )
            return self._view(db, account_id)

    def request_join(self, account_id: str, code: str, display_name: str, consent: bool) -> dict[str, Any]:
        if consent is not True:
            raise _error("consent_required", "Açık rıza vermeden katılma isteği gönderilemez.")
        name, normalized = _clean_name(display_name), normalize_code(code)
        bad_code = False
        answer: dict[str, Any] | None = None
        with self._tx() as db:
            day = _today(self._clock())
            row = db.execute("SELECT day, failures FROM family_attempts WHERE account_id = ?", (account_id,)).fetchone()
            if row and row[0] == day and row[1] >= JOIN_FAILS_PER_DAY:
                raise _error("too_many_attempts", "Bugünkü kod deneme sınırı doldu. Yarın yeniden deneyin.", 429)
            if normalized is None:
                raise _error("code_format", "Kod 6 geçerli harf ya da rakamdan oluşmalı.")
            group = db.execute("SELECT id, owner_id, code_expires_at FROM family_groups WHERE code = ?", (normalized,)).fetchone()
            now = self._clock()
            if not group or group[2] <= _stamp(now):
                self._failed_attempt(db, account_id, day, row)
                bad_code = True
            elif group[1] == account_id:
                raise _error("own_code", "Kendi kodunuzla ailenize katılamazsınız.", 409)
            elif self._member(db, account_id):
                raise _error("already_in_family", "Zaten bir aileye üyesiniz.", 409)
            elif self._has_request(db, account_id):
                raise _error("request_pending", "Bekleyen katılma isteğiniz var.", 409)
            elif self._family_count(db, group[0]) >= FAMILY_MAX_MEMBERS:
                raise _error("family_full", "Aile dolu. Yeni istek alınamıyor.", 409)
            else:
                requested_at = _stamp(now)
                request_id, check = secrets.token_hex(12), secrets.randbelow(900) + 100
                db.execute(
                    "INSERT INTO family_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (request_id, group[0], account_id, name, check, requested_at, FAMILY_CONSENT_VERSION, requested_at),
                )
                db.execute("DELETE FROM family_attempts WHERE account_id = ?", (account_id,))
                answer = {"check": str(check), "requested_at": requested_at}
        if bad_code:
            raise _error("code_not_found", "Bu kod bulunamadı ya da süresi doldu. Kod sahibinden güncel kodu isteyin.", 404)
        return answer or {}

    def _failed_attempt(self, db: sqlite3.Connection, account_id: str, day: str, row: Any) -> None:
        failures = row[1] + 1 if row and row[0] == day else 1
        db.execute(
            "INSERT INTO family_attempts VALUES (?, ?, ?) ON CONFLICT(account_id) "
            "DO UPDATE SET day = excluded.day, failures = excluded.failures",
            (account_id, day, failures),
        )

    def cancel_request(self, account_id: str) -> dict[str, Any]:
        with self._tx() as db:
            removed = db.execute("DELETE FROM family_requests WHERE account_id = ?", (account_id,)).rowcount
            if not removed:
                raise _error("request_not_found", "Bekleyen katılma isteği bulunamadı.", 404)
            return self._view(db, account_id)

    def decide(self, owner_id: str, request_id: str, approve: bool) -> dict[str, Any]:
        with self._tx() as db:
            owner = self._member(db, owner_id)
            if not owner or owner[2] != "owner":
                raise _error("not_owner", "Bu işlem yalnız kod sahibine açık.", 403)
            request = db.execute(
                "SELECT id, account_id, display_name, check_number, consent_at, consent_version, requested_at "
                "FROM family_requests WHERE id = ? AND group_id = ?",
                (request_id, owner[1]),
            ).fetchone()
            if not request:
                raise _error("request_not_found", "Katılma isteği bulunamadı.", 404)
            if approve:
                if self._family_count(db, owner[1]) >= FAMILY_MAX_MEMBERS:
                    raise _error("family_full", "Aile dolu. İstek onaylanamadı.", 409)
                db.execute(
                    "INSERT INTO family_members VALUES (?, ?, ?, ?, 'member', ?, ?, ?)",
                    (secrets.token_hex(12), owner[1], request[1], request[2], request[4], request[5], request[6]),
                )
            db.execute("DELETE FROM family_requests WHERE id = ?", (request_id,))
            return self._view(db, owner_id)

    def leave(self, account_id: str) -> dict[str, Any]:
        with self._tx() as db:
            member = self._member(db, account_id)
            if not member:
                raise _error("member_not_found", "Aile üyeliği bulunamadı.", 404)
            dissolved = member[2] == "owner"
            if dissolved:
                db.execute("DELETE FROM family_groups WHERE id = ?", (member[1],))
            else:
                db.execute("DELETE FROM family_members WHERE id = ?", (member[0],))
            return {"dissolved": dissolved, "view": self._view(db, account_id)}

    def remove_member(self, owner_id: str, member_id: str) -> dict[str, Any]:
        with self._tx() as db:
            owner = self._member(db, owner_id)
            if not owner or owner[2] != "owner":
                raise _error("not_owner", "Bu işlem yalnız kod sahibine açık.", 403)
            target = db.execute(
                "SELECT id FROM family_members WHERE id = ? AND group_id = ? AND role = 'member'",
                (member_id, owner[1]),
            ).fetchone()
            if not target:
                raise _error("member_not_found", "Aile üyesi bulunamadı.", 404)
            db.execute("DELETE FROM family_members WHERE id = ?", (target[0],))
            return self._view(db, owner_id)

    def set_shares(self, account_id: str, follow_ids: Sequence[str], stops: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if len(follow_ids) > 10:
            raise _error("share_invalid", "En çok 10 takip konusu paylaşabilirsiniz.")
        try:
            clean_stops = list(dict.fromkeys(clean_stop(item.get("line"), item.get("stop")) for item in stops))
        except (AttributeError, TypeError, ValueError) as exc:
            raise _error("share_invalid", "Seçilen durak geçersiz.") from exc
        if len(clean_stops) > FAMILY_STOP_LIMIT:
            raise _error("share_invalid", f"En çok {FAMILY_STOP_LIMIT} durak paylaşabilirsiniz.")
        with self._tx() as db:
            member = self._member(db, account_id)
            if not member:
                raise _error("member_not_found", "Aile üyeliği bulunamadı.", 404)
            own = {row["id"] for row in self.accounts.follows(account_id)}
            if len(set(follow_ids)) != len(follow_ids) or not set(follow_ids) <= own:
                raise _error("share_invalid", "Yalnız kendi takip ettiğiniz konuları paylaşabilirsiniz.")
            db.execute("DELETE FROM family_shared_follows WHERE member_id = ?", (member[0],))
            db.execute("DELETE FROM family_shared_stops WHERE member_id = ?", (member[0],))
            db.executemany(
                "INSERT INTO family_shared_follows VALUES (?, ?)", ((member[0], follow_id) for follow_id in follow_ids)
            )
            db.executemany(
                "INSERT INTO family_shared_stops VALUES (?, ?, ?)",
                ((member[0], line, stop) for line, stop in clean_stops),
            )
            return self._view(db, account_id)


def _clean_name(value: Any) -> str:
    try:
        return clean_display_name(value)
    except ValueError as exc:
        code = "display_name"
        raise _error(code, str(exc)) from exc
