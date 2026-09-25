"""Shared plumbing for every source module.

A :class:`SourceContext` bundles the one HTTP client, the one cache and the settings.
Sources never construct their own client: that is what keeps the per-host spacing and the
İETT hourly budget global rather than per-source.
"""

from __future__ import annotations

import contextvars
import datetime as dt
import json
import pathlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ibb_mcp.cache import CacheEntry, TTLCache
from ibb_mcp.config import SOURCE_URLS, Settings
from ibb_mcp.http import PoliteClient
from ibb_mcp.models import Provenance, utcnow
from ibb_mcp.reference import parse_once

#: Written by ``scripts/capture_fixtures.py`` beside the recorded responses: one entry per
#: call, named like the fixture file, with ``captured_at_utc`` when the call was made.
CAPTURE_REPORT = "_capture_report.json"

#: Capture times of the fixtures the loader now running has read. A context variable, not an
#: attribute, because concurrent loaders share one ``SourceContext``.
_fixture_captures: contextvars.ContextVar[list[dt.datetime] | None] = contextvars.ContextVar("fixture_captures", default=None)


@dataclass
class SourceContext:
    """Everything a source needs. Build one per process with :meth:`create`."""

    client: PoliteClient
    cache: TTLCache
    settings: Settings

    @classmethod
    def create(
        cls,
        *,
        client: PoliteClient | None = None,
        cache: TTLCache | None = None,
        settings: Settings | None = None,
    ) -> SourceContext:
        return cls(
            client=client or PoliteClient(),
            cache=cache or TTLCache(),
            settings=settings or Settings.from_env(),
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    def load_fixture(self, name: str) -> Any:
        """Read a recorded response. Used when ``settings.offline`` is set and by tests."""
        path = self.settings.fixtures_dir / f"{name}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        captures = _fixture_captures.get()
        if captures is not None:
            captures.append(fixture_captured_at(self.settings.fixtures_dir, name))
        return payload

    async def cached(
        self,
        key: str,
        loader: Callable[[], Awaitable[Any]],
        *,
        source: str,
        ttl: float | None = None,
    ) -> tuple[Any, CacheEntry[Any]]:
        if not self.settings.offline:
            return await self.cache.get_or_fetch(key, loader, source=source, ttl=ttl)

        # Offline, the entry's observed time is when its fixture was recorded, not when it was
        # read: the İSPARK list, Metro and air-quality stations and the İETT timetable carry no
        # timestamp of their own, so the read time made weeks-old recordings look live.
        captures: list[dt.datetime] = []

        async def recording_loader() -> Any:
            token = _fixture_captures.set(captures)
            try:
                return await loader()
            finally:
                _fixture_captures.reset(token)

        value, entry = await self.cache.get_or_fetch(key, recording_loader, source=source, ttl=ttl)
        # No await since the cache returned, so a single-flight waiter never sees the entry unstamped.
        if captures and entry.captured_at is None:
            entry.captured_at = min(captures)
        return value, entry


def fixture_captured_at(fixtures_dir: pathlib.Path, name: str) -> dt.datetime:
    """When the recorded response ``name`` was fetched from İBB.

    From the capture report when it lists the call with a time. Otherwise the fixture file's
    modification time: a file is never written before its capture, so that age can only be
    too young, never invented. The report is parsed once per file version.
    """
    try:
        captured = parse_once(fixtures_dir / CAPTURE_REPORT, _capture_times, kind="capture-report")
    except (OSError, ValueError):  # absent, unreadable or not JSON: no report
        captured = {}
    moment = captured.get(name)
    if moment is not None:
        return moment
    return dt.datetime.fromtimestamp((fixtures_dir / f"{name}.json").stat().st_mtime, dt.UTC)


def _capture_times(report: Any) -> dict[str, dt.datetime]:
    """``{call name: captured_at_utc}`` for every call in the report that records a time."""
    times: dict[str, dt.datetime] = {}
    for call in report if isinstance(report, list) else []:
        stamp = call.get("captured_at_utc") if isinstance(call, dict) else None
        if isinstance(stamp, str):
            moment = dt.datetime.fromisoformat(stamp)
            times[str(call.get("name"))] = moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)
    return times


def make_provenance(
    source: str,
    *,
    entry: CacheEntry[Any] | None = None,
    reported_at: dt.datetime | None = None,
    url: str | None = None,
) -> Provenance:
    """Build the provenance stamp attached to every tool result.

    The entry keeps ``reported_at`` too, so ``city_freshness`` reports the data's own age
    and not only when Nabız last read the source (see ``TTLCache.freshness``).
    """
    observed = entry.observed_at_utc if entry is not None else utcnow()
    if entry is not None and reported_at is not None:
        entry.reported_at = reported_at
    return Provenance(
        source=source,
        source_url=url or SOURCE_URLS.get(source, ""),
        observed_at=observed,
        reported_at=reported_at,
        cached=bool(entry is not None and not entry.fresh),
    )
