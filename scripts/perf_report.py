#!/usr/bin/env python3
"""Offline performance measurements: the one place numbers about speed and cost come from.

``tests/test_performance_budgets.py`` asserts budgets with these functions, and a change
that claims to make something faster or cheaper pastes this script's output from before
and after (docs/ENGINEERING.md §14, OPT-1). Same code for both, so a number in a commit
message and a number CI enforces cannot drift apart.

What is measured, and why it is measured this way:

* **Upstream calls per tool**, cold and warm, counted twice. Once at the cache: every loader
  ``TTLCache.get_or_fetch`` runs is one fetch. And once at the boundary itself: offline, a
  source reads a recorded response (``SourceContext.load_fixture``) where live it would send
  a request, and any request that does reach the client's transport is counted before it is
  refused. The reported number is the larger of the two, because nothing forces a source to
  go through the cache: AGENTS.md §4 asks for it, and guardrail ``no-raw-ibb-calls`` only
  checks that a request goes through ``PoliteClient``. Until 2026-09-23 only the cache was
  counted, and a second read beside it on every call passed every gate;
  ``test_the_harness_counts_a_read_beside_the_cache`` keeps that case red. Counted, not
  timed: exact, and the same on a laptop and a runner. Both counters keep the source of
  every call, so İETT calls, which spend the 80-an-hour budget, can be told apart.
* **Expensive loads per process** (GTFS index, stop sequences, reference tables): counted
  by spies around the parsers.
* **Warm latency**, p50/p95 after warm-up: a coarse backstop against order-of-magnitude
  regressions, never a target.
* **GTFS on the committed mini fixture**: time and tracemalloc peak.

Offline only: settings with ``offline=True`` and a client whose transport raises. Nothing
here can reach api.ibb.gov.tr, and nothing is written outside a temporary directory.

Usage::

    NABIZ_OFFLINE=1 .venv/bin/python scripts/perf_report.py            # markdown table
    NABIZ_OFFLINE=1 .venv/bin/python scripts/perf_report.py --json
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import contextlib
import functools
import inspect
import json
import pathlib
import shutil
import statistics
import sys
import tempfile
import time
import tracemalloc
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ibb_mcp import gtfs  # noqa: E402
from ibb_mcp.cache import TTLCache  # noqa: E402
from ibb_mcp.config import Settings  # noqa: E402
from ibb_mcp.http import PoliteClient  # noqa: E402
from ibb_mcp.sources.base import SourceContext  # noqa: E402
from ibb_mcp.tools import Nabiz  # noqa: E402

#: Cache sources whose loader is an İETT SOAP call, charged to the hourly İETT budget.
IETT_SOURCES = frozenset({"iett_line", "iett_fleet", "iett_schedule"})
#: The recorded responses that stand in for those calls offline.
IETT_FIXTURES = frozenset({"iett_hat_500T", "iett_fleet", "iett_planlanan"})

#: One sample subscription for ``check_alerts``: one rule of each live kind.
SUBSCRIPTION: dict[str, Any] = {
    "version": 1,
    "places": [{"key": "home", "label": "Ev", "lat": 40.99, "lon": 29.03}],
    "rules": [
        {"kind": "metro_disruption", "lines": ["M4"]},
        {"kind": "parking_filling", "park_ids": [3068], "threshold_pct": 85},
        {"kind": "air_quality", "place": "home", "aqi_threshold": 100},
        {"kind": "traffic", "threshold_index": 60},
        {"kind": "lift_outage", "stations": ["Kartal"]},
    ],
}

#: One representative call per MCP tool, arguments as in eval/journeys.jsonl.
TOOL_CALLS: dict[str, dict[str, Any]] = {
    "places_resolve": {"query": "Taksim"},
    "ispark_find_parking": {"place": "Taksim Meydanı", "radius_km": 1.5, "min_free": 1},
    "ispark_typical_occupancy": {"park_id": 3068, "weekday": 1, "hour": 18},
    "iett_stops_search": {"query": "Kavacık Köprüsü", "limit": 5},
    "iett_line_buses": {"line_code": "500T"},
    "iett_next_arrivals": {"line_code": "500T", "stop": "220641", "limit": 3},
    "metro_status": {"line": "M4"},
    "metro_station_info": {"name": "Kartal"},
    "metro_equipment_status": {"station": "Kartal"},
    "traffic_index": {"window": "now"},
    "air_quality_now": {"place": "Beşiktaş"},
    "air_quality_forecast": {"place": "Kadıköy", "horizon_hours": 6},
    "city_freshness": {},
    "plan_journey": {"origin": "Kadıköy", "destination": "Taksim"},
    "line_reliability": {"line_code": "500T"},
    "check_alerts": {"subscription": SUBSCRIPTION},
    "ibb_services_search": {"query": "su aboneliği", "limit": 5},
    "ibb_datasets_search": {"query": "otopark", "limit": 5},
}


class CountingCache(TTLCache):
    """A TTLCache that counts loader invocations per key: one invocation, one upstream call."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.upstream: collections.Counter[str] = collections.Counter()
        self.source_of: dict[str, str] = {}

    async def get_or_fetch(self, key, loader, *, source, ttl=None):  # type: ignore[override]
        async def counted():
            self.upstream[key] += 1
            self.source_of[key] = source
            return await loader()

        return await super().get_or_fetch(key, counted, source=source, ttl=ttl)

    def iett_calls(self) -> int:
        return sum(n for key, n in self.upstream.items() if self.source_of.get(key) in IETT_SOURCES)


@dataclass
class BoundaryContext(SourceContext):
    """A SourceContext that counts what reaches the upstream boundary, cache or no cache."""

    boundary: collections.Counter[str] = field(default_factory=collections.Counter)

    def load_fixture(self, name: str) -> Any:
        self.boundary[name] += 1
        return super().load_fixture(name)

    def boundary_calls(self) -> tuple[int, int]:
        """(all, of which İETT)."""
        return sum(self.boundary.values()), sum(n for name, n in self.boundary.items() if name in IETT_FIXTURES)


def refusing_transport(boundary: collections.Counter[str]) -> httpx.MockTransport:
    """Counts a request that reached the client, then refuses it: nothing here may use the network."""

    def refuse(request: httpx.Request) -> httpx.Response:
        boundary[f"network:{request.url.host}"] += 1
        raise AssertionError(f"the perf harness tried the network: {request.url}")

    return httpx.MockTransport(refuse)


@contextlib.contextmanager
def offline_settings(repo: pathlib.Path = ROOT) -> Iterator[Settings]:
    """Settings over a private copy of the mini GTFS (``load_stop_sequences`` writes a cache beside it)."""
    with tempfile.TemporaryDirectory(prefix="nabiz-perf-") as tmp:
        gtfs_dir = pathlib.Path(tmp) / "gtfs"
        skip = shutil.ignore_patterns("*.py", "*.md", "__pycache__")
        shutil.copytree(repo / "tests/fixtures/gtfs_mini", gtfs_dir, ignore=skip)
        gtfs.reset_index_cache()
        try:
            places = repo / "data/reference/places.csv"
            yield Settings(offline=True, fixtures_dir=repo / "tests/fixtures", gtfs_dir=gtfs_dir, places_csv=places)
        finally:
            gtfs.reset_index_cache()


def fresh_app(settings: Settings, **cache_kwargs: Any) -> tuple[Nabiz, CountingCache]:
    """A facade with an empty counting cache, a boundary counter (``app.ctx.boundary``) and a
    client that refuses the network."""
    cache = CountingCache(**cache_kwargs)
    boundary: collections.Counter[str] = collections.Counter()
    client = PoliteClient(transport=refusing_transport(boundary))
    return Nabiz(BoundaryContext(client=client, cache=cache, settings=settings, boundary=boundary)), cache


@dataclass
class ToolNumbers:
    tool: str
    cold_upstream: int
    cold_iett: int
    warm_upstream: int
    cold_ms: float
    warm_p50_ms: float
    warm_p95_ms: float
    cold_keys: dict[str, int] = field(default_factory=dict)


def call_kwargs(app: Nabiz, tool: str) -> dict[str, Any]:
    fn = getattr(app, tool)
    return {k: v for k, v in TOOL_CALLS[tool].items() if k in inspect.signature(fn).parameters}


async def measure_tool(settings: Settings, tool: str, runs: int = 30, warmup: int = 3) -> ToolNumbers:
    """One cold call on an empty cache, ``warmup`` untimed calls, then ``runs`` timed warm calls.

    Upstream counts are the larger of the cache count and the boundary count (module docstring).
    """
    app, cache = fresh_app(settings)
    fn, kwargs = getattr(app, tool), call_kwargs(app, tool)
    start = time.perf_counter()
    await fn(**kwargs)
    cold_ms = (time.perf_counter() - start) * 1000
    cold, cold_iett = dict(cache.upstream), cache.iett_calls()
    cold_boundary, cold_boundary_iett = app.ctx.boundary_calls()
    for _ in range(warmup):
        await fn(**kwargs)
    before, before_boundary = sum(cache.upstream.values()), app.ctx.boundary_calls()[0]
    samples = []
    for _ in range(runs):
        start = time.perf_counter()
        await fn(**kwargs)
        samples.append((time.perf_counter() - start) * 1000)
    await app.aclose()
    samples.sort()
    warm_cache = sum(cache.upstream.values()) - before
    warm_boundary = app.ctx.boundary_calls()[0] - before_boundary
    return ToolNumbers(
        tool=tool,
        cold_upstream=max(sum(cold.values()), cold_boundary),
        cold_iett=max(cold_iett, cold_boundary_iett),
        warm_upstream=max(warm_cache, warm_boundary),
        cold_ms=round(cold_ms, 2),
        warm_p50_ms=round(statistics.median(samples), 3),
        warm_p95_ms=round(samples[int(0.95 * (len(samples) - 1))], 3),
        cold_keys=cold,
    )


@contextlib.contextmanager
def count_calls(*targets: tuple[object, str]) -> Iterator[collections.Counter[str]]:
    """Spy on functions or methods for the duration of the block; the originals come back after."""
    counter: collections.Counter[str] = collections.Counter()
    saved = []
    for owner, name in targets:
        original = getattr(owner, name)
        label = f"{getattr(owner, '__name__', owner)}.{name}"

        def wrapper(*args, _original=original, _label=label, **kwargs):
            counter[_label] += 1
            return _original(*args, **kwargs)

        # The raw attribute, so a classmethod is restored as a classmethod, not a bound method.
        saved.append((owner, name, inspect.getattr_static(owner, name)))
        setattr(owner, name, functools.wraps(original)(wrapper))
    try:
        yield counter
    finally:
        for owner, name, original in saved:
            setattr(owner, name, original)


def gtfs_mini_numbers(settings: Settings) -> dict[str, float]:
    """Index load and stop-sequence build on the mini fixture: milliseconds and tracemalloc peak."""
    gtfs.reset_index_cache()
    tracemalloc.start()
    start = time.perf_counter()
    gtfs.get_index(settings)
    index_ms = (time.perf_counter() - start) * 1000
    index_peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    tracemalloc.start()
    start = time.perf_counter()
    gtfs.build_stop_sequences(settings)
    build_ms = (time.perf_counter() - start) * 1000
    build_peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return {
        "index_load_ms": round(index_ms, 2),
        "index_peak_kib": round(index_peak / 1024, 1),
        "sequences_build_ms": round(build_ms, 2),
        "sequences_build_peak_kib": round(build_peak / 1024, 1),
    }


async def report() -> dict[str, Any]:
    with offline_settings() as settings:
        tools = [asdict(await measure_tool(settings, name)) for name in TOOL_CALLS]
        return {"tools": tools, "gtfs_mini": gtfs_mini_numbers(settings)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="perf_report", description=__doc__.split("\n", 1)[0])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    data = asyncio.run(report())
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return 0
    print("| tool | upstream cold | of which İETT | upstream warm | cold ms | warm p50 ms | warm p95 ms |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for t in data["tools"]:
        keys = ("tool", "cold_upstream", "cold_iett", "warm_upstream", "cold_ms", "warm_p50_ms", "warm_p95_ms")
        print("| " + " | ".join(str(t[key]) for key in keys) + " |")
    print("\nGTFS mini fixture: " + ", ".join(f"{k} {v}" for k, v in data["gtfs_mini"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
