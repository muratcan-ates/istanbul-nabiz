"""TTL cache with single-flight and stale fallback.

Three behaviours matter for this project:

1. **Single flight.** If fifty users ask "is there parking near Taksim" at once, exactly
   one request reaches İBB and the rest wait on it.
2. **Stale-on-error.** When the gateway 503s, an expired entry is still far better than
   an error. We return it and mark the provenance as stale so the agent says "veri X dk
   önceki" instead of pretending it is live.
3. **Observability.** Hit/miss/stale counters feed the ``city_freshness`` tool and the
   data-quality report.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("ibb_mcp.cache")


#: Per-source time-to-live in seconds. Tuned to how fast the upstream actually moves and
#: to how hard we are willing to hit the gateway.
DEFAULT_TTL = {
    "ispark": 300.0,       # occupancy refreshes roughly every 10 minutes
    "iett_line": 60.0,     # vehicle positions move every few seconds, but the budget is 100/h
    "iett_fleet": 120.0,
    "iett_schedule": 86400.0,
    "metro_status": 300.0,
    "metro_stations": 86400.0,
    "traffic": 300.0,
    "aq_stations": 86400.0,
    "aq_readings": 1800.0,
}


@dataclass
class CacheEntry[T]:
    value: T
    stored_at: float
    stored_at_utc: dt.datetime
    ttl: float
    #: When the source says the data was measured, if it says so. ``stored_at_utc`` is when
    #: Nabız read it: a 14-day-old reading fetched a minute ago is a minute old by that clock
    #: and 14 days old by this one. Set by ``make_provenance``, which is where it is known.
    reported_at: dt.datetime | None = None

    @property
    def age(self) -> float:
        return time.monotonic() - self.stored_at

    @property
    def fresh(self) -> bool:
        return self.age < self.ttl


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    stale_served: int = 0
    errors: int = 0
    last_success_utc: dt.datetime | None = None
    last_error: str | None = None
    #: The entry stored by the last successful fetch, so ``freshness`` can report its data age.
    last_entry: CacheEntry[Any] | None = None


class TTLCache:
    """Async TTL cache keyed by string, with per-key single-flight locking."""

    def __init__(self, ttl_by_source: dict[str, float] | None = None) -> None:
        self._entries: dict[str, CacheEntry[Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._ttl = {**DEFAULT_TTL, **(ttl_by_source or {})}
        self.stats: dict[str, CacheStats] = {}

    def ttl_for(self, source: str) -> float:
        return self._ttl.get(source, 300.0)

    def _stats(self, source: str) -> CacheStats:
        return self.stats.setdefault(source, CacheStats())

    def peek(self, key: str) -> CacheEntry[Any] | None:
        return self._entries.get(key)

    async def get_or_fetch[T](
        self,
        key: str,
        loader: Callable[[], Awaitable[T]],
        *,
        source: str,
        ttl: float | None = None,
    ) -> tuple[T, CacheEntry[T]]:
        """Return a cached value, refreshing it if stale.

        On upstream failure an expired entry is returned rather than raising, so a
        gateway wobble degrades the answer instead of breaking it.
        """
        stats = self._stats(source)
        effective_ttl = ttl if ttl is not None else self.ttl_for(source)

        entry = self._entries.get(key)
        if entry is not None and entry.fresh:
            stats.hits += 1
            return entry.value, entry

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Another coroutine may have refreshed while we waited for the lock.
            entry = self._entries.get(key)
            if entry is not None and entry.fresh:
                stats.hits += 1
                return entry.value, entry

            stats.misses += 1
            try:
                value = await loader()
            except Exception as exc:  # noqa: BLE001 - deliberately broad: any failure falls back
                stats.errors += 1
                stats.last_error = f"{type(exc).__name__}: {exc}"
                if entry is not None:
                    stats.stale_served += 1
                    log.warning("%s: upstream failed (%s); serving stale entry aged %.0fs", source, exc, entry.age)
                    return entry.value, entry
                raise

            now = time.monotonic()
            new_entry = CacheEntry(
                value=value,
                stored_at=now,
                stored_at_utc=dt.datetime.now(dt.UTC),
                ttl=effective_ttl,
            )
            self._entries[key] = new_entry
            stats.last_success_utc = new_entry.stored_at_utc
            stats.last_entry = new_entry
            stats.last_error = None
            return value, new_entry

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._entries.clear()
        else:
            self._entries.pop(key, None)

    def freshness(self) -> dict[str, dict[str, Any]]:
        """Summary used by the ``city_freshness`` tool.

        Two ages per source, because they answer different questions. ``age_seconds`` is how
        long ago Nabız last read the source (the fetch). ``data_age_seconds`` is how old the
        data of that read is: from the source's own timestamp (``reported_at_utc``) when it
        states one, otherwise from the fetch, the same rule every answer's provenance uses.
        Offline, a recorded traffic reading is minutes old by the first and days old by the
        second, and only the second may be called fresh. ``healthy`` means the last fetch
        did not fail; it says nothing about the data's age.
        """
        now = dt.datetime.now(dt.UTC)
        out: dict[str, dict[str, Any]] = {}
        for source, stats in self.stats.items():
            entry = stats.last_entry
            reported = entry.reported_at if entry is not None else None
            out[source] = {
                "last_success_utc": stats.last_success_utc.isoformat() if stats.last_success_utc else None,
                "age_seconds": _seconds_since(stats.last_success_utc, now),
                "reported_at_utc": reported.isoformat() if reported else None,
                "data_age_seconds": _seconds_since(reported or (entry.stored_at_utc if entry else None), now),
                "healthy": stats.last_error is None and stats.last_success_utc is not None,
                "hits": stats.hits,
                "misses": stats.misses,
                "stale_served": stats.stale_served,
                "errors": stats.errors,
                "last_error": stats.last_error,
            }
        return out


def _seconds_since(moment: dt.datetime | None, now: dt.datetime) -> float | None:
    """Seconds from ``moment`` to ``now`` to a tenth; never negative, ``None`` when unknown."""
    if moment is None:
        return None
    return round(max(0.0, (now - moment).total_seconds()), 1)
