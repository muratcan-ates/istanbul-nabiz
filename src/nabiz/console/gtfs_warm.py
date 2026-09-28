"""Warm the GTFS tables at start-up, so the first arrival question does not wait for them.

A fresh process reads the stop index (``ibb_mcp.gtfs.get_index``, a 1.5 MB CSV) on its first
``iett_line_buses`` or ``iett_next_arrivals`` and the terminal departures (``load_route_timetables``,
a 1.3 MB gzip JSON) on its first arrival fallback. On the full export that was about 0.35 s and
0.45 s of the first answer. The lifespan starts :func:`warm_gtfs` in the background: start-up does
not wait for it, and a question that arrives while it runs waits on the facade's own lock instead of
loading a second copy. It reads local files only, never İBB.

``NABIZ_WARM_GTFS=0`` turns it off; the test suite does (``tests/conftest.py``), because every test
app would otherwise load the tables in a worker thread.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Mapping

from ibb_mcp.tools import Nabiz

log = logging.getLogger("nabiz.console")

WARM_GTFS_ENV = "NABIZ_WARM_GTFS"
#: The loop keeps only weak references to its tasks; a warm-up nobody holds could be collected mid-run.
_RUNNING: set[asyncio.Task[None]] = set()


def warm_gtfs_enabled(env: Mapping[str, str] | None = None) -> bool:
    """On unless ``NABIZ_WARM_GTFS`` is ``0``."""
    values = os.environ if env is None else env
    return (values.get(WARM_GTFS_ENV) or "").strip() != "0"


async def warm_gtfs(nabiz: Nabiz) -> None:
    """Load the facade's stop index, stop orders and departure tables, each in a worker thread."""
    started = time.perf_counter()
    try:
        await nabiz.gtfs()
        await nabiz.stop_sequences()
        # The departures are cached per facade (ibb_mcp.timetables.ScheduleTables), not per process like
        # get_index, so loading a copy of our own would be thrown away. Nabiz is at its class-size cap
        # (scripts/architecture_baseline.json), hence its own cache and lock here, not a new public method.
        await nabiz._schedule_tables.get(nabiz.settings)
    except Exception as exc:  # noqa: BLE001 - a failed warm-up leaves the load to the first question, as before
        log.warning("GTFS warm-up failed, the first arrival question loads it: %s", type(exc).__name__)
        return
    log.info("GTFS tables warm in %.0f ms", 1000 * (time.perf_counter() - started))


def start_gtfs_warm(nabiz: Nabiz) -> asyncio.Task[None] | None:
    """Start :func:`warm_gtfs` on the running loop and return at once; ``None`` when it is switched off."""
    if not warm_gtfs_enabled():
        return None
    task = asyncio.get_running_loop().create_task(warm_gtfs(nabiz), name="nabiz-gtfs-warm")
    _RUNNING.add(task)
    task.add_done_callback(_RUNNING.discard)
    return task
