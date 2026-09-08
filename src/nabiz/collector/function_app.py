"""The Azure Functions app: five timers, one shared client, one line of log per tick.

Everything that could fail interestingly lives in :mod:`nabiz.collector.snapshots`,
:mod:`nabiz.collector.lake` and :mod:`nabiz.collector.kusto`. What is left here is
scheduling, and three decisions worth stating:

**All crons are UTC.** Flex Consumption ignores ``WEBSITE_TIME_ZONE``, so writing an
Istanbul-local schedule would silently drift by three hours. Nothing here needs a local
clock: the rows carry UTC timestamps and the analytics layer converts on read.

**The three hourly timers are staggered by five minutes.** The gateway starts returning
503 to *every* İBB service after roughly fifteen rapid calls, and the shared client holds
six seconds between calls to the same host. Firing metro, traffic and air quality at
``:00`` — on top of an İSPARK tick and a fleet tick that also land there — would make
each one wait behind the others and put a burst on a gateway that answers everybody.
Spreading them costs nothing: the data is hourly.

**One :class:`SourceContext` for the whole worker.** That is what makes the per-host
spacing and the İETT hourly budget global rather than per-invocation. Two timers that
overlap therefore queue politely instead of racing, which is the intended behaviour.

``azure.functions`` is imported inside a ``try``: this module must be importable — and
testable — on a machine with no Azure SDK, and ``python -m nabiz.collector.function_app``
runs every job once locally against exactly the same code path.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ibb_mcp.config import Settings
from ibb_mcp.sources.base import SourceContext
from nabiz.collector.kusto import KustoSink
from nabiz.collector.lake import awrite_rows
from nabiz.collector.snapshots import (
    build_collector_context,
    iso_utc,
    snapshot_air_quality,
    snapshot_fleet,
    snapshot_ispark,
    snapshot_metro,
    snapshot_traffic,
)

try:  # pragma: no cover - present only inside the Functions runtime
    import azure.functions as func
except ImportError:  # the SDK is an optional extra; tests and local runs do without it
    func = None  # type: ignore[assignment]

log = logging.getLogger("nabiz.collector")


@dataclass(frozen=True)
class TimerJob:
    """One timer: what it reads, where the rows go, and how often."""

    name: str
    cron: str
    source: str
    snapshot: Callable[[SourceContext], Awaitable[list[dict[str, Any]]]]
    why: str


#: İSPARK refreshes roughly every ten minutes and one call covers all 249 lots, so this
#: is the natural cadence: six gateway requests an hour for the entire occupancy history.
ISPARK = TimerJob(
    name="ispark",
    cron="0 */10 * * * *",
    source="ispark_snapshot",
    snapshot=snapshot_ispark,
    why="occupancy history behind ispark_typical_occupancy",
)

#: 30 requests an hour against İETT's documented budget of 100, for the whole 6 900
#: vehicle fleet. Two minutes is close enough to see a bus move between stops, which is
#: what the line-hour speed profile and the ETA accuracy log both need.
FLEET = TimerJob(
    name="fleet",
    cron="0 */2 * * * *",
    source="iett_fleet_snapshot",
    snapshot=snapshot_fleet,
    why="line speed profiles and the ETA accuracy log",
)

METRO = TimerJob(
    name="metro",
    cron="0 5 * * * *",
    source="metro_status",
    snapshot=snapshot_metro,
    why="disruption history, including proof of the quiet hours",
)

TRAFFIC = TimerJob(
    name="traffic",
    cron="0 10 * * * *",
    source="traffic_index_hourly",
    snapshot=snapshot_traffic,
    why="city-wide congestion baseline",
)

#: Last of the hourly three because it is the longest: 28 stations read one at a time
#: behind a six-second gateway gate is about three minutes of mostly waiting.
AIR_QUALITY = TimerJob(
    name="air_quality",
    cron="0 15 * * * *",
    source="aq_hourly",
    snapshot=snapshot_air_quality,
    why="hourly PM10 history for the forecast baseline",
)

JOBS: tuple[TimerJob, ...] = (ISPARK, FLEET, METRO, TRAFFIC, AIR_QUALITY)


# --------------------------------------------------------------------------------------
# process-wide singletons
# --------------------------------------------------------------------------------------
_context: SourceContext | None = None
_sink: KustoSink | None = None


def get_context(settings: Settings | None = None) -> SourceContext:
    """The one :class:`SourceContext` for this worker, built on first use."""
    global _context
    if _context is None:
        _context = build_collector_context(settings)
    return _context


def get_sink() -> KustoSink:
    """The one ADX sink for this worker. Disabled and harmless when unconfigured."""
    global _sink
    if _sink is None:
        _sink = KustoSink()
    return _sink


async def reset_state() -> None:
    """Drop the singletons, closing the HTTP client. Used by tests and by ``__main__``."""
    global _context, _sink
    if _context is not None:
        await _context.aclose()
    _context = None
    _sink = None


# --------------------------------------------------------------------------------------
# the work
# --------------------------------------------------------------------------------------
async def run_job(job: TimerJob, *, ctx: SourceContext | None = None) -> dict[str, Any]:
    """Take one snapshot, write it to the lake, ingest it, and log one line.

    Nothing is allowed to escape. A timer that raises turns one bad tick into a failed
    invocation and, on the fleet job, into a retry storm against a gateway that is
    already unhappy — while the actual remedy is simply the next tick two minutes later.
    Failures are logged at ERROR so Application Insights still shows them, and the
    returned summary carries the reason.
    """
    started = time.perf_counter()
    snapshot_ts = dt.datetime.now(dt.UTC)
    summary: dict[str, Any] = {
        "job": job.name,
        "source": job.source,
        "snapshot_ts_utc": iso_utc(snapshot_ts),
        "rows": 0,
        "backend": None,
        "path": None,
        "kusto_rows": 0,
        "elapsed_ms": 0,
        "error": None,
    }

    try:
        rows = await job.snapshot(ctx or get_context())
        summary["rows"] = len(rows)
        if rows:
            written = await awrite_rows(job.source, rows, snapshot_ts=snapshot_ts)
            summary["backend"] = written.backend
            summary["path"] = written.path
            summary["kusto_rows"] = await asyncio.to_thread(get_sink().ingest, job.source, rows)
    except Exception as exc:  # noqa: BLE001 - a timer must not die; the next tick retries
        summary["error"] = f"{type(exc).__name__}: {exc}"
        log.exception("collector/%s: tick failed", job.name)

    summary["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    log.info(
        "collector/%s rows=%d lake=%s kusto=%d %d ms%s",
        job.name,
        summary["rows"],
        summary["path"] or summary["backend"] or "-",
        summary["kusto_rows"],
        summary["elapsed_ms"],
        f" error={summary['error']}" if summary["error"] else "",
    )
    return summary


async def run_all_once(
    jobs: tuple[TimerJob, ...] = JOBS,
    *,
    ctx: SourceContext | None = None,
) -> list[dict[str, Any]]:
    """Run every job once, in order. The local dry run, and the smoke test in CI."""
    return [await run_job(job, ctx=ctx) for job in jobs]


# --------------------------------------------------------------------------------------
# timer registration
# --------------------------------------------------------------------------------------
async def collect_ispark() -> dict[str, Any]:
    return await run_job(ISPARK)


async def collect_fleet() -> dict[str, Any]:
    return await run_job(FLEET)


async def collect_metro() -> dict[str, Any]:
    return await run_job(METRO)


async def collect_traffic() -> dict[str, Any]:
    return await run_job(TRAFFIC)


async def collect_air_quality() -> dict[str, Any]:
    return await run_job(AIR_QUALITY)


if func is not None:  # pragma: no cover - exercised only by the Functions host
    app = func.FunctionApp()

    @app.function_name(name="IsparkCollector")
    @app.timer_trigger(schedule=ISPARK.cron, arg_name="timer", run_on_startup=False, use_monitor=True)
    async def ispark_timer(timer: func.TimerRequest) -> None:
        await collect_ispark()

    @app.function_name(name="FleetCollector")
    @app.timer_trigger(schedule=FLEET.cron, arg_name="timer", run_on_startup=False, use_monitor=True)
    async def fleet_timer(timer: func.TimerRequest) -> None:
        await collect_fleet()

    @app.function_name(name="MetroCollector")
    @app.timer_trigger(schedule=METRO.cron, arg_name="timer", run_on_startup=False, use_monitor=True)
    async def metro_timer(timer: func.TimerRequest) -> None:
        await collect_metro()

    @app.function_name(name="TrafficCollector")
    @app.timer_trigger(schedule=TRAFFIC.cron, arg_name="timer", run_on_startup=False, use_monitor=True)
    async def traffic_timer(timer: func.TimerRequest) -> None:
        await collect_traffic()

    @app.function_name(name="AirQualityCollector")
    @app.timer_trigger(schedule=AIR_QUALITY.cron, arg_name="timer", run_on_startup=False, use_monitor=True)
    async def air_quality_timer(timer: func.TimerRequest) -> None:
        await collect_air_quality()
else:
    #: The Functions host looks for a module-level ``app``. Absent the SDK there is
    #: nothing to register, and the module stays importable for tests and dry runs.
    app = None


# --------------------------------------------------------------------------------------
# local dry run
# --------------------------------------------------------------------------------------
async def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the collector jobs once, locally.")
    parser.add_argument("--job", action="append", choices=[job.name for job in JOBS], help="run only these jobs")
    parser.add_argument("--offline", action="store_true", help="read tests/fixtures instead of İBB")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    chosen = tuple(job for job in JOBS if not args.job or job.name in args.job)
    settings = Settings(offline=True) if args.offline else None

    try:
        summaries = await run_all_once(chosen, ctx=get_context(settings))
    finally:
        await reset_state()

    failed = [s for s in summaries if s["error"]]
    total = sum(s["rows"] for s in summaries)
    log.info("collector: %d job(s), %d rows, %d failed", len(summaries), total, len(failed))
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(asyncio.run(_main()))
