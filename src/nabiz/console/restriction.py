"""Session scoped request limits and temporary, reasoned restrictions.

The caller supplies a trusted, opaque session or account key. A network address is never a
restriction key: people on a shared connection must remain independent. This in-memory
provider is for offline tests; production wiring must supply durable identity and storage.
"""

from __future__ import annotations

import datetime as dt
import os
import threading
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass

AUTO_HOURS = 24
MAX_HUMAN_HOURS = 30 * 24
WINDOW_SECONDS = 60
REQUESTS_PER_WINDOW = 10
BURST_DENIALS = 3
PROTECTED = frozenset({"model", "upload"})
ALWAYS_OPEN = frozenset({"emergency", "appeal", "follow", "delete"})
AUTO_REASON = "Tekrarlanan otomatik istek yoğunluğu"
REASON_CODES = {"automated_burst": AUTO_REASON, "reviewed_abuse": "İnsan incelemesinde kötüye kullanım doğrulandı."}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        raise ValueError("Saat dilimi gerekli.")
    return value.astimezone(dt.UTC)


def validate_subject(subject: str) -> str:
    """Accept only a server-resolved opaque key, never arbitrary display text."""
    if not isinstance(subject, str) or not (8 <= len(subject) <= 128) or not all(
        char.isascii() and (char.isalnum() or char in "_-:") for char in subject
    ):
        raise ValueError("Güvenilir oturum kimliği gerekli.")
    return subject


@dataclass(frozen=True)
class Restriction:
    subject: str
    reason: str
    until: dt.datetime
    source: str

    def public(self) -> dict[str, str]:
        return {"reason": self.reason, "until": self.until.isoformat(), "scope": "model_and_upload", "source": self.source}


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    code: str
    restriction: Restriction | None = None


class RestrictionBook:
    """A deterministic fake provider with per-subject buckets and atomic decisions."""

    def __init__(self, *, clock: Callable[[], dt.datetime] = _now) -> None:
        self.clock = clock
        self._lock = threading.RLock()
        self._requests: dict[str, deque[dt.datetime]] = defaultdict(deque)
        self._denials: dict[str, deque[dt.datetime]] = defaultdict(deque)
        self._restrictions: dict[str, Restriction] = {}

    @staticmethod
    def _trim(bucket: deque[dt.datetime], now: dt.datetime) -> None:
        cutoff = now - dt.timedelta(seconds=WINDOW_SECONDS)
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    def current(self, subject: str) -> Restriction | None:
        key = validate_subject(subject)
        now = _utc(self.clock())
        with self._lock:
            active = self._restrictions.get(key)
            if active is not None and active.until <= now:
                self._restrictions.pop(key, None)
                return None
            return active

    def check(self, subject: str, operation: str, *, address: str | None = None) -> GateResult:
        """Admit one protected action; address is deliberately never counted or stored."""
        del address
        if operation in ALWAYS_OPEN:
            return GateResult(True, "open")
        if operation not in PROTECTED:
            raise ValueError("Tanınmayan işlem.")
        key = validate_subject(subject)
        now = _utc(self.clock())
        with self._lock:
            active = self.current(key)
            if active is not None:
                return GateResult(False, "restricted", active)
            requests = self._requests[key]
            self._trim(requests, now)
            if len(requests) < REQUESTS_PER_WINDOW:
                requests.append(now)
                return GateResult(True, "open")
            denials = self._denials[key]
            self._trim(denials, now)
            denials.append(now)
            # The owner's decision (P00 D2a): no automatic restriction unless NABIZ_AUTO_RESTRICTION=1; a burst is
            # only rate limited, and a person, never the machine, restricts longer (24 hours stays the automatic cap).
            if len(denials) < BURST_DENIALS or os.environ.get("NABIZ_AUTO_RESTRICTION", "0") != "1":
                return GateResult(False, "rate_limited")
            active = Restriction(key, AUTO_REASON, now + dt.timedelta(hours=AUTO_HOURS), "automatic")
            self._restrictions[key] = active
            requests.clear()
            denials.clear()
            return GateResult(False, "restricted", active)

    def restrict(self, subject: str, *, reason: str, hours: int, human: bool) -> Restriction:
        """Manual decisions may last longer; automatic decisions cannot."""
        key = validate_subject(subject)
        if reason not in REASON_CODES:
            raise ValueError("Kısıt için kodlanmış gerekçe gerekli.")
        if type(hours) is not int or hours < 1 or hours > MAX_HUMAN_HOURS or (hours > AUTO_HOURS and not human):
            raise ValueError("Uzun kısıt yalnız insan kararıyla verilir.")
        if not human and reason != "automated_burst":
            raise ValueError("Otomatik kısıt yalnız istek yoğunluğu gerekçesiyle verilir.")
        now = _utc(self.clock())
        active = Restriction(key, REASON_CODES[reason], now + dt.timedelta(hours=hours), "human" if human else "automatic")
        with self._lock:
            self._restrictions[key] = active
        return active

    def reopen(self, subject: str) -> bool:
        key = validate_subject(subject)
        with self._lock:
            self._requests.pop(key, None)
            self._denials.pop(key, None)
            return self._restrictions.pop(key, None) is not None
