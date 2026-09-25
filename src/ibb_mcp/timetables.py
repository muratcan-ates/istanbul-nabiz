"""The GTFS tables behind the arrival fallback, read once per facade and off the event loop.

``ibb_mcp.eta`` falls back to the timetable when no live position is fresh enough: first the
terminal departures summarised from GTFS ``stop_times`` (:func:`ibb_mcp.gtfs.load_route_timetables`,
cached beside the tables after the first build), then İETT's planned departures. The service
calendar (:func:`ibb_mcp.gtfs.load_service_days`) filters those departures by day type; most
machines have no ``calendar.csv``, which leaves the filter off and the diagnostics say so.

The same pattern as ``Nabiz.stop_sequences``: the first caller loads in a thread, the others wait
on the lock, and an empty result (no GTFS here) is kept too, so a fresh download needs a restart.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ibb_mcp.config import Settings

Tables = tuple[dict[str, tuple[Any, ...]], dict[str, frozenset[str]]]


class ScheduleTables:
    """``(route timetables, service days)`` for one facade, loaded on first use."""

    def __init__(self) -> None:
        self._tables: Tables | None = None
        self._lock = asyncio.Lock()

    async def get(self, settings: Settings) -> Tables:
        if self._tables is None:
            async with self._lock:
                if self._tables is None:
                    self._tables = await asyncio.to_thread(_load, settings)
        return self._tables


def _load(settings: Settings) -> Tables:
    from ibb_mcp.gtfs import load_route_timetables, load_service_days

    return load_route_timetables(settings), load_service_days(settings)
