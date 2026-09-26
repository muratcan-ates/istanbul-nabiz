#!/usr/bin/env python3
"""Run the collector continuously on this machine, and log ETA predictions as it goes.

Why this exists alongside the Azure Functions app: the history İBB does not publish only
accumulates while something is running, and the Azure deployment is blocked behind the
Day-0 gates in PLAN.md §10. Every hour spent waiting is an hour of parking occupancy and
bus movement that can never be recovered. This script starts collecting now, writes the
same rows in the same layout as the Function, and can be thrown away the moment the cloud
collector takes over.

What it collects, and why on these cadences:

======================  ==========  ==================================================
source                  cadence     reason
======================  ==========  ==================================================
İSPARK occupancy        10 min      no public history; one call covers all 249 lots
İETT watched lines      3 min       no public history; the only ETA ground truth
Metro status            60 min      current-state only, and it changes rarely
Traffic index           6 h         the endpoint itself serves 30 days of history
Air quality             12 h        the endpoint itself serves years of history
Metro faulty equipment  15 min      no public history; at most 4 calls on the Metro host, none on İETT
======================  ==========  ==================================================

Steady-state cost is roughly 6 + 60 + 1 upstream calls an hour. The İETT budget in
:class:`~ibb_mcp.http.PoliteClient` caps that source at 80/hour against a documented
limit of 100, and every call is spaced at least six seconds apart.

Each watched-line tick also runs the ETA engine for a fixed set of (line, stop) pairs and
appends its predictions to the lake. Nothing extra is fetched: the prediction is computed
from the positions already in hand. ``scripts/eta_report.py`` later pairs each prediction
with the arrival that actually happened and reports the error.

Usage::

    .venv/bin/python scripts/collect_forever.py            # run until Ctrl-C
    .venv/bin/python scripts/collect_forever.py --once     # one tick of everything
    .venv/bin/python scripts/collect_forever.py --status   # what has been collected
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import json
import logging
import os
import pathlib
import signal
import subprocess
import sys
import time
from collections.abc import Awaitable

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from ibb_mcp.config import Settings  # noqa: E402
from ibb_mcp.eta import EtaParams, estimate_arrivals  # noqa: E402
from ibb_mcp.gtfs import get_index, load_stop_sequences  # noqa: E402
from ibb_mcp.models import BusPosition, utcnow  # noqa: E402
from nabiz.collector import lake  # noqa: E402
from nabiz.collector.equipment import (  # noqa: E402
    EQUIPMENT_INTERVAL_S,
    EQUIPMENT_SOURCE,
    equipment_fault_counts,
    iter_equipment_rows,
    snapshot_equipment,
)
from nabiz.collector.snapshots import (  # noqa: E402
    build_collector_context,
    iso_utc,
    parse_iso_utc,
    snapshot_air_quality,
    snapshot_ispark,
    snapshot_lines,
    snapshot_metro,
    snapshot_traffic,
)

log = logging.getLogger("nabiz.collect_forever")

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "data" / "lake" / ".collector.lock"
STATE_PATH = ROOT / "data" / "lake" / ".collector_state.json"

#: Lines watched for ETA ground truth. Chosen to be long, busy and geographically spread,
#: so the sample covers both free-flowing and congested conditions. 500T is the verified
#: reference route (Şifa Sondurak <-> 4. Levent Metro, 64 stops).
WATCHED_LINES: tuple[str, ...] = ("500T", "34", "15F")

#: (line, stop_code) pairs the ETA is predicted for on every watched-line tick.
#:
#: All mid-route, and that is a correction rather than a preference. The first run used
#: ``301341`` (4. LEVENT METRO), which is the *terminus* of 500T. A bus sits there on
#: layover while still reporting it as its nearest stop, so "arrival" absorbed the whole
#: rest break: fitting the 161 resolved predictions gave ``actual ≈ 17 min + 1.6 min/stop``,
#: and a 17-minute constant is not a property of traffic. Terminus targets were dropped
#: before any calibration was attempted, because calibrating against a measurement
#: artefact would have baked it into the engine.
#:
#: Positions are taken at roughly 30%, 50% and 70% along each route so the sample spans
#: both free-flowing and congested sections.
ETA_TARGETS: tuple[tuple[str, str], ...] = (
    ("500T", "205501"),  # ATATÜRK CADDESİ (~30% along)
    ("500T", "261262"),  # MEHMET ALİ TUNGA CAMİ (~50%)
    ("500T", "206042"),  # ANADOLU ADALET SARAYI (~70%)
    ("15F", "219532"),  # PAŞABAHÇE (~30%)
    ("15F", "260141"),  # ŞEHİT MURAT AKDEMİR (~50%)
    ("34", "900121"),  # DARÜLACEZE PERPA (~50%, metrobüs)
)

INTERVALS_S = {
    "ispark": 600,
    "lines": 180,
    "metro": 3600,
    "traffic": 21_600,
    "air_quality": 43_200,
    "equipment": EQUIPMENT_INTERVAL_S,
}


def _now() -> float:
    return time.monotonic()


def _process_start(pid: int) -> str:
    """The start time ``ps`` reports for ``pid``, or "" when it cannot tell."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
        return out.stdout.strip()
    return ""


class SingleInstance:
    """A pid lock, so two runs cannot double the request rate against İBB.

    The lock holds the pid and the start time of the process that took it. A live pid alone
    is not proof: after a reboot or a kill -9 the exit path never runs, and the old pid can
    belong to an unrelated process, which used to keep the collector down until someone
    noticed. A lock written before the start time was recorded falls back to the pid check.
    """

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.acquired = False

    def __enter__(self) -> SingleInstance:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                pid_line, _, start = self.path.read_text().strip().partition("\n")
                pid = int(pid_line)
                os.kill(pid, 0)
                if start and _process_start(pid) != start:
                    raise ProcessLookupError(pid)
            except (ValueError, ProcessLookupError, PermissionError):
                log.warning("stale lock at %s, taking over", self.path)
            else:
                raise SystemExit(f"collector already running as pid {pid} ({self.path})")
        self.path.write_text(f"{os.getpid()}\n{_process_start(os.getpid())}\n")
        self.acquired = True
        return self

    def __exit__(self, *exc: object) -> None:
        if self.acquired:
            with contextlib.suppress(OSError):
                self.path.unlink()


def _load_state() -> dict:
    if STATE_PATH.exists():
        with contextlib.suppress(ValueError, OSError):
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"ticks": {}, "rows": {}, "started_utc": iso_utc(utcnow())}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


def _rows_to_positions(rows: list[dict]) -> list[BusPosition]:
    """Rebuild models from snapshot rows so the ETA engine can be run on them."""
    positions: list[BusPosition] = []
    for row in rows:
        positions.append(
            BusPosition(
                door_no=row["door_no"],
                lat=row.get("lat"),
                lon=row.get("lon"),
                line_code=row.get("line_code"),
                route_code=row.get("route_code"),
                direction=row.get("direction"),
                nearest_stop_code=row.get("nearest_stop_code"),
                reported_at=parse_iso_utc(row.get("ts_utc")),
            )
        )
    return positions


def build_eta_predictions(rows: list[dict], settings: Settings) -> list[dict]:
    """Predict arrivals for every configured target, from positions already fetched.

    Each row is one prediction about one vehicle reaching one stop, stamped with the
    method that produced it. ``scripts/eta_report.py`` joins these to observed arrivals on
    ``(line_code, door_no, stop_code)`` and reports the error per method, which is the only
    honest way to publish an ETA accuracy number.
    """
    if not rows:
        return []
    index = get_index(settings)
    sequences = load_stop_sequences(settings)
    now = utcnow()
    predictions: list[dict] = []

    by_line: dict[str, list[dict]] = {}
    for row in rows:
        by_line.setdefault(row["line_code"], []).append(row)

    for line_code, stop_code in ETA_TARGETS:
        target = index.lookup_stop(stop_code)
        line_rows = by_line.get(line_code.upper())
        if target is None or not line_rows:
            continue
        arrivals, diagnostics = estimate_arrivals(
            buses=_rows_to_positions(line_rows),
            target=target,
            index=index,
            sequences=sequences,
            params=EtaParams(max_results=6),
            now=now,
        )
        for arrival in arrivals:
            predictions.append(
                {
                    "predicted_at_utc": iso_utc(now),
                    "line_code": line_code.upper(),
                    "stop_code": stop_code,
                    "stop_name": target.name,
                    "door_no": arrival.door_no,
                    "eta_minutes": arrival.eta_minutes,
                    "method": arrival.method,
                    "confidence": arrival.confidence,
                    "stops_away": arrival.stops_away,
                    "distance_km": arrival.distance_km,
                    "buses_considered": diagnostics.get("buses_received"),
                }
            )
    return predictions


async def tick(name: str, ctx, settings: Settings, state: dict) -> int:
    """Run one source, write its rows, and return how many were written."""
    started = _now()
    written = 0
    try:
        if name == "ispark":
            rows = await snapshot_ispark(ctx)
            written = lake.write_rows("ispark_snapshot", rows).rows
        elif name == "lines":
            rows = await snapshot_lines(ctx, WATCHED_LINES)
            written = lake.write_rows("iett_line_snapshot", rows).rows
            predictions = build_eta_predictions(rows, settings)
            if predictions:
                lake.write_rows("eta_predictions", predictions)
                state.setdefault("rows", {})["eta_predictions"] = (
                    state.get("rows", {}).get("eta_predictions", 0) + len(predictions)
                )
        elif name == "metro":
            rows = await snapshot_metro(ctx)
            written = lake.write_rows("metro_status", rows).rows
        elif name == "traffic":
            rows = await snapshot_traffic(ctx)
            written = lake.write_rows("traffic_index_hourly", rows).rows
        elif name == "air_quality":
            rows = await snapshot_air_quality(ctx, hours=24)
            written = lake.write_rows("aq_hourly", rows).rows
        elif name == "equipment":
            rows = await snapshot_equipment(ctx)
            written = lake.write_rows(EQUIPMENT_SOURCE, rows).rows
            if written:
                state.setdefault("snapshots", {})["equipment"] = state.get("snapshots", {}).get("equipment", 0) + 1
    except Exception as exc:  # noqa: BLE001 - a loop must outlive any single tick
        log.error("tick %s failed: %r", name, exc)
        return 0

    elapsed = (_now() - started) * 1000
    state.setdefault("ticks", {})[name] = iso_utc(utcnow())
    state.setdefault("rows", {})[name] = state.get("rows", {}).get(name, 0) + written
    log.info("tick %-12s rows=%-6d %6.0f ms", name, written, elapsed)
    return written


async def until_stopped(stopping: asyncio.Event, work: Awaitable[int]) -> bool:
    """Run one tick, but give it up the moment a stop is asked for.

    A tick can wait minutes on İBB (the polite client's gaps, retries, a slow source), and the
    stop event used to be read only between ticks, so SIGTERM from ``make collect-stop`` went
    unheard and the process needed ``kill -9``. The in-flight tick is cancelled instead: its
    snapshot is lost, which the next run's first tick makes up. True when the tick finished.
    """
    task = asyncio.ensure_future(work)
    waiter = asyncio.ensure_future(stopping.wait())
    try:
        await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        waiter.cancel()
    if task.done():
        return True
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    return False


async def run(once: bool = False) -> int:
    settings = Settings.from_env()
    ctx = build_collector_context(settings)
    state = _load_state()
    stopping = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stopping.set)

    due = dict.fromkeys(INTERVALS_S, 0.0)
    try:
        while not stopping.is_set():
            now = _now()
            for name, interval in INTERVALS_S.items():
                if stopping.is_set():
                    break
                if now >= due[name]:
                    if not await until_stopped(stopping, tick(name, ctx, settings, state)):
                        log.info("stop asked during the %s tick; it was cancelled", name)
                        break
                    due[name] = _now() + interval
            _save_state(state)
            if once:
                break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stopping.wait(), timeout=20)
    finally:
        _save_state(state)
        await ctx.aclose()
        log.info("collector stopped; totals: %s", state.get("rows"))
    return 0


def show_status() -> int:
    state = _load_state()
    print(f"started: {state.get('started_utc')}")
    print(f"now:     {iso_utc(utcnow())}")
    running = LOCK_PATH.exists()
    print(f"running: {'yes (pid ' + LOCK_PATH.read_text().strip() + ')' if running else 'no'}")
    print("\nlast tick per source:")
    for name in INTERVALS_S:
        print(f"  {name:14s} {state.get('ticks', {}).get(name) or '-'}")
    print("\nrows written this run:")
    for name, count in sorted(state.get("rows", {}).items()):
        print(f"  {name:20s} {count:>9,}")

    equipment_root = pathlib.Path(os.getenv("NABIZ_LAKE_DIR", ROOT / "data" / "lake"))
    equipment_rows = list(iter_equipment_rows(equipment_root))
    equipment_snapshots = {row.get("snapshot_ts_utc") for row in equipment_rows if row.get("snapshot_ts_utc")}
    print("\nekipman (Metro arızalı ekipman):")
    if not equipment_snapshots:
        print("  henüz snapshot yok")
    else:
        counts = equipment_fault_counts(equipment_root)
        print(f"  toplam snapshot: {len(equipment_snapshots)}")
        print(f"  farklı ekipman kodu: {len(counts)}")
        for code, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]:
            print(f"  {code}  {count}/{len(equipment_snapshots)} snapshot")

    lake_dir = pathlib.Path(os.getenv("NABIZ_LAKE_DIR", ROOT / "data" / "lake"))
    if lake_dir.exists():
        print(f"\nlake at {lake_dir}:")
        for source_dir in sorted(p for p in lake_dir.iterdir() if p.is_dir()):
            files = list(source_dir.rglob("*.ndjson.gz")) + list(source_dir.rglob("*.parquet"))
            size = sum(f.stat().st_size for f in files)
            newest = max((f.stat().st_mtime for f in files), default=0)
            age = f"{(dt.datetime.now().timestamp() - newest) / 60:.0f} dk önce" if newest else "-"
            print(f"  {source_dir.name:24s} {len(files):>5} dosya  {size / 1024:>8.0f} KB  son: {age}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="run one tick of every source and exit")
    parser.add_argument("--status", action="store_true", help="show what has been collected and exit")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.status:
        return show_status()
    with SingleInstance(LOCK_PATH):
        return asyncio.run(run(once=args.once))


if __name__ == "__main__":
    raise SystemExit(main())
