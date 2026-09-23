"""Run the collector once and exit — the shape Azure Container Apps Jobs runs it in.

The history İBB does not publish only accumulates while something is collecting it, and
the laptop collector (``scripts/collect_forever.py``) keeps stopping: when the machine
sleeps, when its parent shell goes away (commit 0951bcc), and even under the supervisor
added for exactly that. Its own lake has watched-line snapshots on 4 of the 15 days from
8 to 22 September; the rest is history nobody can collect any more. The Azure Function in
:mod:`nabiz.collector.function_app` would not have fixed that on its own: its five timers
never collect watched lines or ETA predictions, which are exactly the two series the
measured ETA error is computed from. DECISIONS.md #10 moves collection to scheduled
Container Apps Jobs; this module is what each execution runs::

    python -m nabiz.collector.job --sources lines --deadline-s 140
    python -m nabiz.collector.job --sources ispark,fleet
    python -m nabiz.collector.job --plan          # the schedule and its İETT arithmetic

It reuses everything the other two collectors use — the snapshot builders, the polite
client, the lake and ADX sinks, and the ETA log — and changes only what a process that
lives for one tick has to change:

**The İETT budget is enforced by the schedule, not by a counter.** ``PoliteClient`` keeps
a sliding hourly budget of 80 İETT requests, which works for a process that runs for
hours and means nothing for one that makes three requests and exits: every execution
starts with a full budget. So the budget becomes arithmetic over :data:`SCHEDULES` — the
peak number of executions in any 60-minute window times the İETT calls each one plans,
summed over jobs — and ``tests/test_collector_job.py`` holds that sum under the client's
own limit. At run time each execution then allows itself exactly the İETT calls its
sources plan (:attr:`SourceSpec.iett_calls`) and not one more: the client's budget is
replaced with one of that size, so a change that quietly adds a call fails loudly in the
log instead of overspending a limit shared with every other consumer of the gateway.

**No retries against İETT.** A retry is an unplanned request, and with the default three
attempts a failing gateway would triple the planned spend. Runs that touch İETT use one
attempt; the next tick three minutes later is the retry. Runs that do not keep the
client's default backoff — they are not on a budget, only on the 6-second spacing.

**A deadline instead of a kill.** Container Apps stops a replica at ``replicaTimeout``,
and rows held in memory die with it. ``--deadline-s`` stops *reading* early enough to
write what was read; the infrastructure passes ``replicaTimeout`` minus a margin.

**The exit code says whether the execution failed.** An empty read is not a failure — a
watched line has no buses at 03:00 — so :func:`nabiz.collector.snapshots.count_failed_reads`
tells "İBB had nothing" from "İBB failed". The process exits ``1`` only when *every*
requested source failed, so the platform's execution history and a budget-free alert on
it mean something. A partial failure — rows written, something still missed — is logged
at WARNING, a failed source at ERROR, and every execution ends with one JSON line tagged
``collector-job``, which is what the Log Analytics queries in docs/deploy.md filter on.
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import dataclasses
import datetime as dt
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx

from ibb_mcp.config import Settings
from ibb_mcp.http import HourlyBudget, PoliteClient
from ibb_mcp.sources.base import SourceContext
from nabiz.collector.eta_log import WATCHED_LINES, build_eta_predictions
from nabiz.collector.kusto import KustoSink
from nabiz.collector.lake import awrite_rows
from nabiz.collector.snapshots import (
    build_collector_context,
    count_failed_reads,
    iso_utc,
    snapshot_air_quality,
    snapshot_fleet,
    snapshot_ispark,
    snapshot_lines,
    snapshot_metro,
    snapshot_traffic,
)

log = logging.getLogger("nabiz.collector.job")

#: The tag on the one-line JSON summary each execution ends with. Log Analytics queries
#: filter on it (docs/deploy.md), so it is a contract, not decoration.
SUMMARY_TAG = "collector-job"

#: Hours of traffic index re-read per run. The endpoint serves the last 24 hours on every
#: call; the run keeps the newest ``cadence + 1`` of them, so consecutive runs overlap by
#: one hour and a late bucket is healed rather than lost. The laptop reads 3 hours every
#: 6, which leaves three of every six hours unrecorded — visible in its own lake, where
#: the 20:54 UTC tick on 13 Sep holds 18–20 h and the next one 00–02 h.
TRAFFIC_HOURS_PER_RUN = 7

#: Hours of air-quality readings re-read per run: the laptop's value, twice the 12-hour
#: cadence, so one failed run is healed by the next. ``(station_id, ts_utc)`` makes the
#: overlap harmless.
AIR_QUALITY_HOURS_PER_RUN = 24

#: Seconds kept back from ``replicaTimeout`` for writing, so a slow gateway costs the
#: remaining reads, never the rows already read. Blob upload plus an optional ADX ingest
#: of one tick is a few seconds; thirty leaves room for a cold managed-identity token.
DEADLINE_MARGIN_S = 30


# --------------------------------------------------------------------------------------
# what each source is
# --------------------------------------------------------------------------------------
Collected = dict[str, list[dict[str, Any]]]


@dataclasses.dataclass(frozen=True)
class SourceSpec:
    """One collectable source: the lake/ADX tables it fills and what it costs İETT."""

    name: str
    tables: tuple[str, ...]
    #: İETT requests one run makes. The whole budget argument rests on this number.
    iett_calls: int
    why: str


SOURCES: dict[str, SourceSpec] = {
    "lines": SourceSpec(
        "lines",
        ("iett_line_snapshot", "eta_predictions"),
        len(WATCHED_LINES),
        "observed arrivals and the predictions scored against them: the measured ETA error",
    ),
    "ispark": SourceSpec(
        "ispark",
        ("ispark_snapshot",),
        0,
        "occupancy history behind ispark_typical_occupancy; one call covers all lots",
    ),
    "fleet": SourceSpec(
        "fleet",
        ("iett_fleet_snapshot",),
        1,
        "whole-fleet positions and speeds, kept for a line-speed profile",
    ),
    "metro": SourceSpec(
        "metro",
        ("metro_status",),
        0,
        "disruption history, including the heartbeat that proves the quiet hours",
    ),
    "traffic": SourceSpec(
        "traffic",
        ("traffic_index_hourly",),
        0,
        "city-wide congestion baseline",
    ),
    "air_quality": SourceSpec(
        "air_quality",
        ("aq_hourly",),
        0,
        "hourly PM10 history for the forecast baseline",
    ),
}


@dataclasses.dataclass(frozen=True)
class Schedule:
    """One Container Apps Job: when it runs, what it reads, and how long it may take.

    ``infra/main.bicep`` declares the same list as ``collectorJobSchedules``; the two are
    compared by ``tests/test_collector_job.py`` because Bicep cannot import Python and a
    cadence changed in one place only would break the budget arithmetic silently.
    """

    job: str
    #: Five-field cron, evaluated in UTC by Container Apps.
    cron: str
    sources: tuple[str, ...]
    replica_timeout_s: int

    @property
    def deadline_s(self) -> int:
        return self.replica_timeout_s - DEADLINE_MARGIN_S


#: The laptop cadences, grouped where they coincide. Minutes are staggered so no two jobs
#: are *scheduled* for the same minute except where a 3-minute and a 10-minute cadence
#: cannot avoid it (twice an hour, city with lines). Each job is one process with its own
#: 6-second gate, so an overlap means two request streams, not a burst: well short of the
#: ~15 rapid calls after which the gateway 503s — and the laptop collector and the MCP
#: server have always been two independent streams in the same way.
#:
#: ``replica_timeout_s`` is below the cadence for the 3-minute job so that executions of
#: the same job can never overlap, and generous elsewhere. The laptop's tick times, read
#: from its untracked logs/collector.log on 23 Sep (13–23 Sep, 247 line ticks), were:
#: lines median 12.1 s / max 51.1 s; İSPARK 0.3 s / 16.4 s; metro 0.1 s / 5.7 s; traffic
#: 5.8 s / 6.2 s; air quality 174 s / 248 s. Fleet was never collected there, so has none.
SCHEDULES: tuple[Schedule, ...] = (
    Schedule("lines", "*/3 * * * *", ("lines",), 170),
    Schedule("city", "1-59/10 * * * *", ("ispark", "fleet"), 300),
    Schedule("metro", "5 * * * *", ("metro",), 300),
    Schedule("traffic", "10 */6 * * *", ("traffic",), 300),
    Schedule("airquality", "16 */12 * * *", ("air_quality",), 900),
)


# --------------------------------------------------------------------------------------
# the schedule as arithmetic
# --------------------------------------------------------------------------------------
def _expand_field(field: str, low: int, high: int) -> list[int]:
    """Expand one cron field (``*``, ``*/n``, ``a``, ``a-b``, ``a-b/n``, lists) to values."""
    values: set[int] = set()
    for item in field.split(","):
        body, _, step_text = item.partition("/")
        step = int(step_text) if step_text else 1
        if step < 1:
            raise ValueError(f"cron step must be positive: {item!r}")
        if body == "*":
            start, stop = low, high
        elif "-" in body:
            start_text, stop_text = body.split("-", 1)
            start, stop = int(start_text), int(stop_text)
        else:
            start = int(body)
            stop = high if step_text else start
        if not low <= start <= stop <= high:
            raise ValueError(f"cron field {item!r} outside {low}-{high}")
        values.update(range(start, stop + 1, step))
    return sorted(values)


def cron_minutes_of_day(cron: str) -> list[int]:
    """Minutes after 00:00 UTC at which a five-field cron fires, for an ordinary day.

    Only minute and hour are interpreted. The day, month and weekday fields must be ``*``:
    every schedule here runs every day, and a checker that silently ignored a weekday
    restriction would report executions that never happen — so it refuses instead.
    """
    fields = cron.split()
    if len(fields) != 5:
        raise ValueError(f"expected a five-field cron, got {cron!r}")
    minute, hour, *calendar = fields
    if any(part != "*" for part in calendar):
        raise ValueError(f"day/month/weekday restrictions are not supported here: {cron!r}")
    return [h * 60 + m for h in _expand_field(hour, 0, 23) for m in _expand_field(minute, 0, 59)]


def peak_runs_per_hour(cron: str) -> int:
    """Most executions that fall in any 60-minute window, across midnight included.

    The İETT limit is per rolling hour, not per clock hour, so this slides a window over
    two consecutive days rather than counting ``HH:00``–``HH:59``.
    """
    minutes = cron_minutes_of_day(cron)
    two_days = sorted(minutes + [m + 1440 for m in minutes])
    return max(bisect.bisect_left(two_days, start + 60) - bisect.bisect_left(two_days, start) for start in range(1440))


def plan(schedules: Sequence[Schedule] = SCHEDULES) -> list[dict[str, Any]]:
    """Per job: runs per day, peak runs per hour and the İETT requests that implies."""
    rows = []
    for schedule in schedules:
        calls = sum(SOURCES[name].iett_calls for name in schedule.sources)
        peak = peak_runs_per_hour(schedule.cron)
        rows.append(
            {
                "job": schedule.job,
                "cron": schedule.cron,
                "sources": list(schedule.sources),
                "runs_per_day": len(cron_minutes_of_day(schedule.cron)),
                "peak_runs_per_hour": peak,
                "iett_calls_per_run": calls,
                "iett_calls_peak_hour": calls * peak,
                "replica_timeout_s": schedule.replica_timeout_s,
            }
        )
    return rows


def iett_calls_peak_hour(schedules: Sequence[Schedule] = SCHEDULES) -> int:
    """Upper bound on İETT requests in any hour, summed over every job.

    An upper bound because each job's peak hour is counted as if they coincided — which,
    for these uniform schedules, they do.
    """
    return sum(row["iett_calls_peak_hour"] for row in plan(schedules))


# --------------------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------------------
class _Deadline:
    """Seconds left before reading must stop. ``None`` means no deadline (local runs)."""

    def __init__(self, seconds: float | None) -> None:
        self._at = None if seconds is None else time.monotonic() + seconds

    def remaining(self) -> float | None:
        return None if self._at is None else max(0.0, self._at - time.monotonic())

    def expired(self) -> bool:
        left = self.remaining()
        return left is not None and left <= 0


async def _bounded[T](awaitable: Awaitable[T], deadline: _Deadline) -> T:
    async with asyncio.timeout(deadline.remaining()):
        return await awaitable


async def _read_lines(ctx: SourceContext, deadline: _Deadline, notes: list[str]) -> Collected:
    """Watched lines one at a time, so a deadline keeps the lines already read.

    ``snapshot_lines`` is called per line rather than once for all three: the rows are the
    same, and a gateway that stalls on the third line then costs one line of one tick
    instead of the whole tick. Predictions are computed from whatever was read, exactly
    as on the laptop, and a failure there (no GTFS in the image) is reported without
    discarding the positions — those are the ground truth and are worth more.
    """
    rows: list[dict[str, Any]] = []
    for line_code in WATCHED_LINES:
        if deadline.expired():
            notes.append(f"deadline reached before line {line_code}")
            break
        try:
            rows.extend(await _bounded(snapshot_lines(ctx, [line_code]), deadline))
        except TimeoutError:
            notes.append(f"deadline reached while reading line {line_code}")
            break

    predictions: list[dict[str, Any]] = []
    if rows:
        try:
            predictions = build_eta_predictions(rows, ctx.settings)
        except Exception as exc:  # noqa: BLE001 - positions are still worth writing
            log.error("collector-job/lines: ETA predictions failed, positions kept: %r", exc)
            notes.append(f"eta_predictions failed: {type(exc).__name__}: {exc}")
    return {"iett_line_snapshot": rows, "eta_predictions": predictions}


def _single(table: str, snapshot: Callable[[SourceContext], Awaitable[list[dict[str, Any]]]]):
    async def read(ctx: SourceContext, deadline: _Deadline, notes: list[str]) -> Collected:
        return {table: await _bounded(snapshot(ctx), deadline)}

    return read


READERS: dict[str, Callable[[SourceContext, _Deadline, list[str]], Awaitable[Collected]]] = {
    "lines": _read_lines,
    "ispark": _single("ispark_snapshot", snapshot_ispark),
    "fleet": _single("iett_fleet_snapshot", snapshot_fleet),
    "metro": _single("metro_status", snapshot_metro),
    "traffic": _single("traffic_index_hourly", lambda ctx: snapshot_traffic(ctx, hours=TRAFFIC_HOURS_PER_RUN)),
    "air_quality": _single("aq_hourly", lambda ctx: snapshot_air_quality(ctx, hours=AIR_QUALITY_HOURS_PER_RUN)),
}


# --------------------------------------------------------------------------------------
# one source, end to end
# --------------------------------------------------------------------------------------
async def run_source(name: str, ctx: SourceContext, sink: KustoSink, deadline: _Deadline) -> dict[str, Any]:
    """Read one source, write every table it fills, ingest, and classify the outcome.

    Never raises. ``outcome`` is ``ok`` when rows reached the lake, ``empty`` when the
    reads succeeded and İBB simply had nothing, and ``failed`` when nothing was written
    because something went wrong — the only case that counts towards a failed execution.
    """
    started = time.perf_counter()
    tick = dt.datetime.now(dt.UTC)
    summary: dict[str, Any] = {
        "source": name,
        "snapshot_ts_utc": iso_utc(tick),
        "outcome": "failed",
        "rows": {},
        "paths": {},
        "kusto_rows": 0,
        "failed_reads": [],
        "notes": [],
        "error": None,
        "elapsed_ms": 0,
    }
    written = 0
    failed_reads: list[str] = []
    try:
        with count_failed_reads() as failed_reads:
            if deadline.expired():
                raise TimeoutError("deadline reached before the source started")
            collected = await READERS[name](ctx, deadline, summary["notes"])
        for table, rows in collected.items():
            summary["rows"][table] = len(rows)
            if not rows:
                continue
            result = await awrite_rows(table, rows, snapshot_ts=tick)
            summary["paths"][table] = result.path
            written += result.rows
            summary["kusto_rows"] += await asyncio.to_thread(sink.ingest, table, rows)
    except TimeoutError as exc:
        summary["error"] = f"deadline: {exc}" if str(exc) else "deadline reached while reading"
    except Exception as exc:  # noqa: BLE001 - one source must not take the others down
        summary["error"] = f"{type(exc).__name__}: {exc}"
        log.exception("collector-job/%s: failed", name)
    # Read after the block, not inside it: a timeout or a failed write leaves the block
    # early, and the reads that failed before it are the explanation worth logging.
    summary["failed_reads"] = list(failed_reads)

    if written:
        summary["outcome"] = "ok"
    elif summary["error"] or summary["failed_reads"] or summary["notes"]:
        summary["outcome"] = "failed"
    else:
        summary["outcome"] = "empty"
    summary["elapsed_ms"] = round((time.perf_counter() - started) * 1000)

    if summary["outcome"] == "failed":
        level = logging.ERROR
    elif summary["error"] or summary["failed_reads"] or summary["notes"]:
        level = logging.WARNING  # partial: rows were written, something was still missed
    else:
        level = logging.INFO
    log.log(
        level,
        "collector-job/%s %s rows=%s kusto=%d failed_reads=%d %d ms%s",
        name,
        summary["outcome"],
        summary["rows"],
        summary["kusto_rows"],
        len(summary["failed_reads"]),
        summary["elapsed_ms"],
        f" error={summary['error']}" if summary["error"] else "",
    )
    return summary


def parse_sources(text: str) -> tuple[str, ...]:
    """``lines,ispark`` -> ``("lines", "ispark")``; ``all`` means every source, in order."""
    names = tuple(part.strip() for part in text.split(",") if part.strip())
    if names == ("all",):
        return tuple(SOURCES)
    unknown = [name for name in names if name not in SOURCES]
    if unknown or not names:
        raise ValueError(f"unknown source(s) {unknown or text!r}; choose from {', '.join(SOURCES)} or 'all'")
    if len(set(names)) != len(names):
        raise ValueError(f"source listed twice: {text!r}")
    return names


def planned_iett_calls(names: Sequence[str]) -> int:
    return sum(SOURCES[name].iett_calls for name in names)


def make_client(planned_iett: int, *, transport: httpx.AsyncBaseTransport | None = None) -> PoliteClient:
    """The polite client, with one attempt per request whenever İETT is on the plan.

    A retry is an unplanned request, and the budget argument is only as good as the plan.
    Runs that do not touch İETT keep the default backoff: they answer to the 6-second
    spacing, not to an hourly budget. ``transport`` is for tests, which serve recorded
    responses instead of reaching the gateway.
    """
    if planned_iett:
        return PoliteClient(max_attempts=1, transport=transport)
    return PoliteClient(transport=transport)


def build_job_context(
    names: Sequence[str],
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SourceContext:
    """A collector context whose İETT allowance is exactly what these sources plan."""
    planned = planned_iett_calls(names)
    ctx = build_collector_context(settings, client=make_client(planned, transport=transport))
    limit_budget(ctx, planned)
    return ctx


def limit_budget(ctx: SourceContext, planned: int) -> None:
    """Replace the İETT budget with one that holds exactly ``planned`` requests.

    Zero is a real value: a job that plans no İETT call is refused its first one.
    """
    ctx.client.budgets["iett"] = HourlyBudget("iett", limit=planned)


async def run(
    names: Sequence[str],
    *,
    settings: Settings | None = None,
    ctx: SourceContext | None = None,
    sink: KustoSink | None = None,
    deadline_s: float | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Run ``names`` in order and return ``(exit_code, per-source summaries)``.

    Sources run one after another, never concurrently: they share one client, and the
    6-second gate would serialise them anyway — running them in order keeps the log
    readable and the deadline meaningful. A ``ctx`` passed in (tests) is used as given,
    apart from its İETT budget, and left open for its owner to close.
    """
    owns_ctx = ctx is None
    if ctx is None:
        ctx = build_job_context(names, settings)
    else:
        limit_budget(ctx, planned_iett_calls(names))
    sink = sink or KustoSink()
    deadline = _Deadline(deadline_s)
    try:
        summaries = [await run_source(name, ctx, sink, deadline) for name in names]
    finally:
        if owns_ctx:
            await ctx.aclose()
    total_failure = bool(summaries) and all(s["outcome"] == "failed" for s in summaries)
    return (1 if total_failure else 0), summaries


# --------------------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------------------
async def _print_plan() -> int:
    rows = plan()
    print(f"{'job':<11} {'cron':<17} {'sources':<18} {'runs/day':>8} {'peak/h':>6} {'İETT/run':>8} {'İETT/h':>6}")
    for row in rows:
        print(
            f"{row['job']:<11} {row['cron']:<17} {','.join(row['sources']):<18} {row['runs_per_day']:>8} "
            f"{row['peak_runs_per_hour']:>6} {row['iett_calls_per_run']:>8} {row['iett_calls_peak_hour']:>6}"
        )
    # Read from a real client rather than restated, so the printout cannot disagree with it.
    client = PoliteClient()
    limit = client.budgets["iett"].limit
    await client.aclose()
    print(f"İETT requests in the peak hour, all jobs: {iett_calls_peak_hour()} (in-process limit {limit}; İETT documents 100)")
    return 0


async def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run collector sources once and exit (Container Apps Jobs).")
    parser.add_argument("--sources", help=f"comma-separated: {', '.join(SOURCES)}, or 'all'")
    parser.add_argument("--deadline-s", type=float, default=None, help="stop reading after this many seconds")
    parser.add_argument("--offline", action="store_true", help="read tests/fixtures instead of İBB")
    parser.add_argument("--plan", action="store_true", help="print the schedule and its İETT arithmetic, then exit")
    args = parser.parse_args(argv)

    if args.plan:
        return await _print_plan()
    if not args.sources:
        parser.error("--sources is required (or --plan)")
    try:
        names = parse_sources(args.sources)
    except ValueError as exc:
        parser.error(str(exc))

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs every request at INFO, and so does the Azure SDK's HTTP logging policy —
    # headers included — for every blob upload and token call. At ~19,600 executions a
    # month every console line is Log Analytics ingestion against a 0.16 GB/day cap (the free
    # grant spread over a month), so only warnings from either get through.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("azure").setLevel(logging.WARNING)

    settings = Settings(offline=True) if args.offline else Settings.from_env()
    started = time.perf_counter()
    code, summaries = await run(names, settings=settings, deadline_s=args.deadline_s)
    log.info(
        "%s %s",
        SUMMARY_TAG,
        json.dumps(
            {
                "sources": list(names),
                "exit_code": code,
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "outcomes": {s["source"]: s["outcome"] for s in summaries},
                "rows": {table: n for s in summaries for table, n in s["rows"].items()},
                "failed_reads": sum(len(s["failed_reads"]) for s in summaries),
            },
            ensure_ascii=False,
        ),
    )
    return code


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_main(argv))


if __name__ == "__main__":  # pragma: no cover - the container entry point
    raise SystemExit(main())
