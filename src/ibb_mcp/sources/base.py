"""Shared plumbing for every source module.

A :class:`SourceContext` bundles the one HTTP client, the one cache and the settings.
Sources never construct their own client: that is what keeps the per-host spacing and the
İETT hourly budget global rather than per-source.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ibb_mcp.cache import CacheEntry, TTLCache
from ibb_mcp.config import SOURCE_URLS, Settings
from ibb_mcp.http import PoliteClient
from ibb_mcp.models import Provenance


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
        return json.loads(path.read_text(encoding="utf-8"))

    async def cached(
        self,
        key: str,
        loader: Callable[[], Awaitable[Any]],
        *,
        source: str,
        ttl: float | None = None,
    ) -> tuple[Any, CacheEntry[Any]]:
        return await self.cache.get_or_fetch(key, loader, source=source, ttl=ttl)


def make_provenance(
    source: str,
    *,
    entry: CacheEntry[Any] | None = None,
    reported_at: dt.datetime | None = None,
    url: str | None = None,
) -> Provenance:
    """Build the provenance stamp attached to every tool result."""
    observed = entry.stored_at_utc if entry is not None else dt.datetime.now(dt.UTC)
    return Provenance(
        source=source,
        source_url=url or SOURCE_URLS.get(source, ""),
        observed_at=observed,
        reported_at=reported_at,
        cached=bool(entry is not None and not entry.fresh),
    )
