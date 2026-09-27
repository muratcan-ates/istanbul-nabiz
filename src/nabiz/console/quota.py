"""Daily question and model-call quotas, in three tiers, counted in memory (DECISIONS #38).

**Three tiers.** A visitor with no account is counted by a random id their own browser made
(``X-Nabiz-Device``) together with a pseudonym of their address; a visitor who linked an example
e-mail or Google account gets more, an example İBB or İstanbulkart account the most. The numbers
live in :data:`TIERS` and nowhere else; ``NABIZ_QUOTA_<TIER>_<QUESTIONS|MODEL_CALLS>`` overrides
them (names in ``.env.example``). They are design parameters, not measured values.

**What a full quota closes.** Only the model rung. The rules still answer every question, and an
emergency (112) or a request for a person (153) is never counted and never refused: the route
decides that before it counts (:mod:`nabiz.console.quota_api`).

**What is kept.** Counters keyed by a salted SHA-256 of the device id, of the address (IPv6 by its
/64) or of the account id, for one Istanbul day. :class:`QuotaBook` keeps them in this process's
memory with a salt new on every start; the product app uses P13's
:class:`~nabiz.console.quota_store.PersistentQuotaBook` (P00 D2a), the same counters in a SQLite file
with one stored salt, so a restart or a second replica no longer hands out a fresh day; days older
than two are purged at start. Nothing here is logged. The quota is a courtesy limit, the spend
ceiling (:mod:`nabiz.console.budget`) is the hard one.

**How model calls are counted per person.** :class:`MeteredGuard` wraps the app's one
:class:`~nabiz.console.budget.SpendGuard`. A turn sets its :class:`Meter` in a context variable;
a reservation first claims the person's calls (``reserve_calls``, atomic in the persistent book),
the calls the turn really made are kept, the rest is refunded on release (``refund_calls``), and
whatever a cut-off turn still holds is refunded when the turn ends. With no meter set (tests, the
Arena) it only delegates.
"""

from __future__ import annotations

import contextvars
import datetime as dt
import hashlib
import ipaddress
import os
import re
import secrets
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ibb_mcp.models import ISTANBUL_TZ, utcnow


@dataclass(frozen=True)
class Tier:
    key: str
    label: str
    questions: int
    model_calls: int


#: The one place the numbers live. Keys are the account tiers of :mod:`nabiz.console.accounts`.
TIERS: dict[str, Tier] = {
    "cihaz": Tier("cihaz", "Hesapsız (bu cihaz)", 20, 60),
    "eposta": Tier("eposta", "Örnek e-posta / Google hesabı", 60, 180),
    "ibb": Tier("ibb", "Örnek İBB / İstanbulkart hesabı", 150, 450),
}
ENV_NAMES = {"cihaz": "ANON", "eposta": "EMAIL", "ibb": "IBB"}
#: A household or a campus shares one address: it may ask this many times one device's quota
#: before the address itself is full. A design parameter.
ADDRESS_SHARE = 5
#: Keys remembered at once; the oldest go first. Bounds memory, never refuses anyone.
MAX_KEYS = 50_000
DEVICE_ID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def tiers_from_env(env: Mapping[str, str] | None = None) -> dict[str, Tier]:
    """:data:`TIERS` with any ``NABIZ_QUOTA_*`` override that is a whole number of at least 0."""
    env = os.environ if env is None else env
    result = {}
    for key, tier in TIERS.items():
        values = {}
        for field in ("questions", "model_calls"):
            raw = (env.get(f"NABIZ_QUOTA_{ENV_NAMES[key]}_{field.upper()}") or "").strip()
            values[field] = int(raw) if raw.isdigit() else getattr(tier, field)
        result[key] = Tier(key, tier.label, values["questions"], values["model_calls"])
    return result


def address_key(host: str | None) -> str:
    """The address a counter keys on: IPv6 by its /64 (one household), anything unreadable as is."""
    host = (host or "unknown").strip()
    try:
        parsed = ipaddress.ip_address(host)
    except ValueError:
        return host[:64]
    if parsed.version == 6:
        return str(ipaddress.ip_network(f"{parsed}/64", strict=False))
    return str(parsed)


@dataclass(frozen=True)
class Holder:
    """Who a turn is counted against: the tier and the counter keys (pseudonyms, never raw ids)."""

    tier: Tier
    key: str
    address: str | None = None  # the address pseudonym, for a visitor with no account

    @property
    def has_account(self) -> bool:
        return self.tier.key != "cihaz"


class QuotaBook:
    """Today's counts per pseudonym, in memory, reset when the Istanbul day turns."""

    def __init__(
        self,
        tiers: Mapping[str, Tier] | None = None,
        *,
        clock: Callable[[], dt.datetime] = utcnow,
        salt: bytes | None = None,
        max_keys: int = MAX_KEYS,
    ) -> None:
        self.tiers = dict(tiers or TIERS)
        self._clock = clock
        self._salt = salt or secrets.token_bytes(16)
        self._max_keys = max_keys
        self._lock = threading.Lock()
        self._day = self._today()
        self._counts: OrderedDict[str, list[int]] = OrderedDict()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> QuotaBook:
        return cls(tiers_from_env(env))

    def _today(self) -> str:
        return self._clock().astimezone(ISTANBUL_TZ).date().isoformat()

    def pseudonym(self, kind: str, raw: str) -> str:
        digest = hashlib.sha256(self._salt + f"{kind}:{raw}".encode()).hexdigest()[:24]
        return f"{kind}:{digest}"

    def holder(self, *, device: str | None, host: str | None, account_id: str | None = None, tier: str = "cihaz") -> Holder:
        """An account counts on its own id; a visitor on the device id (when well formed) and the address."""
        if account_id:
            return Holder(self.tiers.get(tier, self.tiers["cihaz"]), self.pseudonym("hesap", account_id))
        address = self.pseudonym("adres", address_key(host))
        if device and DEVICE_ID.match(device):
            return Holder(self.tiers["cihaz"], self.pseudonym("cihaz", device), address)
        return Holder(self.tiers["cihaz"], address)

    def _row(self, key: str) -> list[int]:
        """``[questions, model_calls]`` for today; the lock is held by the caller."""
        today = self._today()
        if today != self._day:
            self._day, self._counts = today, OrderedDict()
        row = self._counts.pop(key, None) or [0, 0]
        self._counts[key] = row
        while len(self._counts) > self._max_keys:
            self._counts.popitem(last=False)
        return row

    def _left(self, holder: Holder) -> tuple[int, int]:
        tier = holder.tier
        own = self._row(holder.key)
        questions = tier.questions - own[0]
        calls = tier.model_calls - own[1]
        if holder.address is not None and holder.address != holder.key:
            shared = self._row(holder.address)
            questions = min(questions, tier.questions * ADDRESS_SHARE - shared[0])
            calls = min(calls, tier.model_calls * ADDRESS_SHARE - shared[1])
        return max(0, questions), max(0, calls)

    def _add(self, holder: Holder, index: int, amount: int) -> None:
        keys = {holder.key, holder.address} - {None}
        for key in keys:
            self._row(str(key))[index] += max(0, int(amount))

    def admit(self, holder: Holder) -> bool:
        """Count one question when the tier still has room; ``False`` means: rules only this turn."""
        with self._lock:
            questions, _ = self._left(holder)
            if questions <= 0:
                return False
            self._add(holder, 0, 1)
            return True

    def calls_left(self, holder: Holder) -> int:
        with self._lock:
            return self._left(holder)[1]

    def reserve_calls(self, holder: Holder, calls: int) -> bool:
        """Claim ``calls`` model calls when they fit today; ``False`` claims nothing."""
        if calls <= 0:
            return False
        with self._lock:
            if self._left(holder)[1] < calls:
                return False
            self._add(holder, 1, calls)
            return True

    def purge_old_days(self, *, keep_days: int = 2) -> int:
        """The persistent book's start-up purge; in memory only today is ever kept, so nothing to do."""
        return 0

    def refund_calls(self, holder: Holder, calls: int) -> None:
        """Give back an unused claim, never below zero."""
        with self._lock:
            for key in {holder.key, holder.address} - {None}:
                row = self._row(str(key))
                row[1] -= min(max(0, int(calls)), row[1])

    def spend_calls(self, holder: Holder, calls: int) -> None:
        with self._lock:
            self._add(holder, 1, calls)

    def status(self, holder: Holder) -> dict[str, Any]:
        """What the page's strip shows: the tier, what is left today, and whether the model is open."""
        with self._lock:
            questions, calls = self._left(holder)
        tier = holder.tier
        return {
            "tier": tier.key,
            "tier_label": tier.label,
            "questions_limit": tier.questions,
            "questions_left": questions,
            "model_calls_limit": tier.model_calls,
            "model_calls_left": calls,
            "model_open": questions > 0 and calls > 0,
            "day": self._day,
        }

    def table(self) -> list[dict[str, Any]]:
        """The three tiers as the account screen's table shows them."""
        return [
            {"tier": t.key, "label": t.label, "questions": t.questions, "model_calls": t.model_calls} for t in self.tiers.values()
        ]


@dataclass
class Meter:
    """One turn's view of a person's quota: whether the model may run, and where its calls go."""

    book: QuotaBook
    holder: Holder
    model_open: bool
    held: int = 0  # claimed in the book, not yet made or refunded

    def room(self, calls: int) -> bool:
        return self.model_open and self.book.calls_left(self.holder) >= calls

    def reserve(self, calls: int) -> bool:
        if not self.model_open or not self.book.reserve_calls(self.holder, calls):
            return False
        self.held += calls
        return True

    def spent(self, calls: int) -> None:
        """Calls made: taken from the claim first; beyond it (a release before the record) counted anew."""
        taken = min(max(0, calls), self.held)
        self.held -= taken
        if calls > taken:
            self.book.spend_calls(self.holder, calls - taken)

    def refund(self, calls: int) -> None:
        given = min(max(0, calls), self.held)
        self.held -= given
        if given:
            self.book.refund_calls(self.holder, given)


CURRENT_METER: contextvars.ContextVar[Meter | None] = contextvars.ContextVar("nabiz_quota_meter", default=None)


class MeteredGuard:
    """The app's spend guard, seen through the current turn's :class:`Meter` (none: plain delegation)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def allows(self, provider: str) -> bool:
        meter = CURRENT_METER.get()
        return (meter is None or meter.room(1)) and self.inner.allows(provider)

    def reserve(self, provider: str, calls: int) -> bool:
        meter = CURRENT_METER.get()
        if meter is None:
            return self.inner.reserve(provider, calls)
        if not meter.reserve(calls):
            return False
        if self.inner.reserve(provider, calls):
            return True
        meter.refund(calls)
        return False

    def release(self, provider: str, calls: int) -> None:
        self.inner.release(provider, calls)
        meter = CURRENT_METER.get()
        if meter is not None:
            meter.refund(calls)

    def record(self, provider: str, usage: Mapping[str, Any], calls: int) -> None:
        self.inner.record(provider, usage, calls)
        meter = CURRENT_METER.get()
        if meter is not None:
            meter.spent(calls)
