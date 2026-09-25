"""Performance budgets, measured offline with the harness in ``scripts/perf_report.py``.

Counts are the gate; time is only a backstop (docs/ENGINEERING.md §14). An upstream call,
a GTFS parse or a profile read is counted exactly and identically on every machine, so
those budgets are tight. A millisecond is not, so the latency budgets carry a wide,
stated margin and exist only to catch an order-of-magnitude regression: a parse moved
onto the request path, a cache bypassed.

Every budget states its reason. The upstream budgets are ceilings (``<=``), so an
optimisation never fails them; lowering one after an optimisation is encouraged, raising
one needs the reason in the same change, because it raises what every question costs the
gateway İBB shares with everyone else.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys

import pytest
from conftest import REPO_ROOT

_spec = importlib.util.spec_from_file_location("perf_report", REPO_ROOT / "scripts" / "perf_report.py")
perf = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = perf
_spec.loader.exec_module(perf)

from ibb_mcp import eta_profile, gtfs, occupancy, reference, reliability  # noqa: E402
from ibb_mcp.cache import DEFAULT_TTL  # noqa: E402
from ibb_mcp.http import PoliteClient  # noqa: E402
from ibb_mcp.server import TOOL_COSTS, build_server  # noqa: E402
from ibb_mcp.sources.ispark import DETAIL_TTL_S, ENRICH_LIMIT  # noqa: E402
from ibb_mcp.sources.places import PlaceIndex  # noqa: E402

# --------------------------------------------------------------------------------------
# 1. upstream calls per tool invocation (the shared İBB budget, DECISIONS #3)
# --------------------------------------------------------------------------------------
#: tool -> (max upstream calls on a cold cache, why). Warm is always 0. Measured with
#: ``make perf-report`` on 2026-09-23; each value is also bounded by the tool's price in
#: ``ibb_mcp.server.TOOL_COSTS`` (see the test after the next one).
UPSTREAM_COLD: dict[str, tuple[int, str]] = {
    "places_resolve": (0, "the gazetteer is a local file"),
    "ispark_find_parking": (1 + ENRICH_LIMIT, "one bulk list, plus ParkDetay for the nearest ENRICH_LIMIT lots (cached a day)"),
    "ispark_typical_occupancy": (0, "history this project measured; a local file"),
    "iett_stops_search": (0, "GTFS stops; a local file"),
    "iett_line_buses": (1, "line positions (İETT)"),
    "iett_next_arrivals": (2, "line positions and fleet speeds, both İETT; the timetable only when no bus reports"),
    "metro_status": (1, "service notices"),
    "metro_station_info": (1, "the station list, cached a day"),
    "metro_equipment_status": (5, "the summary, a detail POST per equipment group (three) and the station list (cached a day)"),
    "traffic_index": (2, "the live index, plus the 28-day history behind 'usually at this hour' (memoised 6 h)"),
    "air_quality_now": (2, "the station list (a day) and the readings (30 min)"),
    "air_quality_forecast": (2, "the station list and the readings"),
    "city_freshness": (0, "cache counters only"),
    "plan_journey": (5, "traffic, its history, metro stations, metro status, the İSPARK list; no İETT call offline"),
    "line_reliability": (0, "history this project measured; a local file"),
    "check_alerts": (5, "the sample subscription watches metro, one car park, air quality (two reads) and traffic"),
    "ibb_services_search": (0, "the local knowledge index; offline, no embedding call"),
}


async def _advertised_tools() -> set[str]:
    with perf.offline_settings() as settings:
        return {tool.name for tool in await build_server(settings).list_tools()}


def test_every_tool_has_an_upstream_budget_and_a_sample_call() -> None:
    """A new MCP tool fails here until it has a budget line and a representative call."""
    advertised = asyncio.run(_advertised_tools())
    assert set(UPSTREAM_COLD) == set(perf.TOOL_CALLS) == advertised


@pytest.mark.parametrize("tool", sorted(UPSTREAM_COLD))
def test_upstream_calls_cold_within_budget_and_zero_when_warm(tool: str) -> None:
    with perf.offline_settings() as settings:
        numbers = asyncio.run(perf.measure_tool(settings, tool, runs=5, warmup=1))
    budget, why = UPSTREAM_COLD[tool]
    assert numbers.cold_upstream <= budget, f"{tool}: {numbers.cold_upstream} cold calls > {budget} ({why}): {numbers.cold_keys}"
    assert numbers.warm_upstream == 0, f"{tool}: a warm call reached upstream {numbers.warm_upstream} time(s)"


@pytest.mark.parametrize("tool", sorted(UPSTREAM_COLD))
def test_the_public_price_covers_what_a_cold_call_costs(tool: str) -> None:
    """``TOOL_COSTS`` charges 1 per answer, 1 per gateway call and 4 per İETT call, worst case.

    If a tool starts reaching further upstream than its price says, the public endpoint
    undercharges for it, and a caller can spend the shared budget faster than the edge
    believes (DECISIONS #15).
    """
    with perf.offline_settings() as settings:
        numbers = asyncio.run(perf.measure_tool(settings, tool, runs=1, warmup=0))
    gateway = numbers.cold_upstream - numbers.cold_iett
    assert 1 + gateway + 4 * numbers.cold_iett <= TOOL_COSTS[tool], numbers


# --------------------------------------------------------------------------------------
# 2. cache behaviour through the real tool path, not only the TTLCache unit
# --------------------------------------------------------------------------------------
def test_fifty_concurrent_questions_cost_what_one_costs() -> None:
    """Single flight end to end (DECISIONS #3: fifty 'parking near Taksim' make one request)."""

    async def run(n: int) -> int:
        with perf.offline_settings() as settings:
            app, cache = perf.fresh_app(settings)
            await asyncio.gather(*(app.ispark_find_parking(place="Taksim Meydanı") for _ in range(n)))
            await app.aclose()
            return sum(cache.upstream.values())

    one = asyncio.run(run(1))
    assert one > 0, "the harness must see the cold calls at all"
    assert asyncio.run(run(50)) == one


def test_an_expired_entry_is_served_stale_when_the_upstream_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stale on error end to end: the answer survives the failure and says it is stale."""

    async def run() -> object:
        with perf.offline_settings() as settings:
            app, _ = perf.fresh_app(settings, ttl_by_source={"metro_status": 0.0})  # expires at once
            await app.metro_status()

            def gateway_down(name: str) -> object:
                raise OSError("503 from the gateway")

            monkeypatch.setattr(app.ctx, "load_fixture", gateway_down)
            result = await app.metro_status()
            await app.aclose()
            return result

    result = asyncio.run(run())
    assert result.provenance.cached, "a stale answer must say it is stale"


def test_ttls_match_the_documented_table() -> None:
    """DECISIONS #3 publishes these. A TTL is an upstream bill: change it there too."""
    documented = {
        "ispark": 300.0,
        "iett_line": 90.0,
        "iett_fleet": 120.0,
        "iett_schedule": 86400.0,
        "metro_status": 300.0,
        "metro_stations": 86400.0,
        "traffic": 300.0,
        "aq_readings": 1800.0,
    }
    assert {key: DEFAULT_TTL[key] for key in documented} == documented
    assert DETAIL_TTL_S == 86400.0


def test_one_hot_line_fits_the_hourly_iett_budget() -> None:
    """Arrivals for one line asked about nonstop must not run out of İETT budget (OPT-3).

    ``iett_next_arrivals`` reads the line's positions and the fleet, each at most once per
    TTL. At 60 s for the line that was 3600/60 + 3600/120 = 90 calls an hour against
    PoliteClient's 80, so after about 53 minutes every İETT answer went stale; 90 s makes it
    40 + 30 = 70, and the 10 left over are headroom for a second line or the schedule.
    """
    per_hour = 3600 / DEFAULT_TTL["iett_line"] + 3600 / DEFAULT_TTL["iett_fleet"]
    assert per_hour == 70
    assert per_hour <= PoliteClient().budgets["iett"].limit


# --------------------------------------------------------------------------------------
# 3. work once per process
# --------------------------------------------------------------------------------------
PARSERS = (
    (gtfs.GtfsIndex, "load"),
    (gtfs, "build_stop_sequences"),
    (PlaceIndex, "load"),
    (occupancy.OccupancyProfile, "from_dict"),
    (reliability.ReliabilityTable, "from_dict"),
    (eta_profile.EtaProfile, "from_dict"),
)
LOCAL_FILE_TOOLS = ("iett_next_arrivals", "iett_stops_search", "ispark_typical_occupancy", "line_reliability", "plan_journey")


@pytest.mark.parametrize("mode", ["default", "calibrated"])
def test_expensive_loads_happen_at_most_once_per_process(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """20 rounds of every tool that reads a local file: each file is parsed at most once.

    The reference tables grow with the history the collector keeps adding, so a parse on
    the request path gets slower every week without anyone touching the code.
    """
    import dataclasses

    monkeypatch.setenv("NABIZ_ETA_PROFILE", str(REPO_ROOT / "data" / "reference" / "eta_profile.json"))
    reference.clear()

    async def rounds() -> None:
        with perf.offline_settings() as settings:
            app, _ = perf.fresh_app(dataclasses.replace(settings, eta_profile_mode=mode))
            for _ in range(20):
                for tool in LOCAL_FILE_TOOLS:
                    await getattr(app, tool)(**perf.call_kwargs(app, tool))
            await app.aclose()

    with perf.count_calls(*PARSERS) as calls:
        asyncio.run(rounds())
    over = {name: count for name, count in calls.items() if count > 1}
    assert not over, f"parsed more than once per process: {over}"
    if mode == "default":
        assert calls["EtaProfile.from_dict"] == 0, "the default mode must not read the calibrated profile at all"


# --------------------------------------------------------------------------------------
# 4. latency backstop and GTFS on the committed mini fixture
# --------------------------------------------------------------------------------------
#: Measured 2026-09-23 on the owner's laptop with `make perf-report`: the slowest warm p95
#: was plan_journey at 3.9 ms, the slowest cold call plan_journey at 27.5 ms. 50 ms is about
#: 13x the first, room for a shared runner being several times slower; 500 ms is about 18x
#: the second, and still trips on a real-GTFS parse (0.27 s for the index alone on the
#: laptop's full export, docs/ENGINEERING.md §14, OPT-6) or an accidental sleep.
WARM_P95_MS = 50.0
COLD_OFFLINE_MS = 500.0


@pytest.mark.parametrize("tool", sorted(perf.TOOL_CALLS))
def test_warm_latency_backstop(tool: str) -> None:
    with perf.offline_settings() as settings:
        numbers = asyncio.run(perf.measure_tool(settings, tool, runs=30, warmup=3))
    assert numbers.warm_p95_ms <= WARM_P95_MS, numbers
    assert numbers.cold_ms <= COLD_OFFLINE_MS, numbers


#: Measured 2026-09-23 on the mini fixture: index 13.8 ms and 578 KiB peak, sequence
#: build 2.3 ms and 44 KiB. tracemalloc counts allocations, so the memory budget is
#: machine-independent and the real gate; 4 MiB is 7x the larger peak.
GTFS_MINI_PEAK_KIB = 4096
GTFS_MINI_MS = 250.0


def test_gtfs_mini_index_and_sequences_stay_small() -> None:
    with perf.offline_settings() as settings:
        numbers = perf.gtfs_mini_numbers(settings)
    assert numbers["index_peak_kib"] <= GTFS_MINI_PEAK_KIB, numbers
    assert numbers["sequences_build_peak_kib"] <= GTFS_MINI_PEAK_KIB, numbers
    assert numbers["index_load_ms"] <= GTFS_MINI_MS and numbers["sequences_build_ms"] <= GTFS_MINI_MS, numbers


# --------------------------------------------------------------------------------------
# 5. the server starts light (every VS Code or Claude session starts one, DECISIONS #8)
# --------------------------------------------------------------------------------------
FORBIDDEN_AT_SERVER_IMPORT = ("nabiz", "fastapi", "azure", "openai", "deltalake", "pyarrow", "agent_framework")


def test_importing_the_server_loads_no_app_and_no_optional_extra() -> None:
    code = "import sys, json, ibb_mcp.server; print(json.dumps(sorted({m.split('.')[0] for m in sys.modules})))"
    env = {**os.environ, "NABIZ_OFFLINE": "1", "PYTHONPATH": str(REPO_ROOT / "src")}
    command = [sys.executable, "-c", code]
    out = subprocess.run(command, capture_output=True, text=True, check=True, env=env, cwd=REPO_ROOT, timeout=60)
    loaded = set(json.loads(out.stdout))
    assert not loaded & set(FORBIDDEN_AT_SERVER_IMPORT), sorted(loaded & set(FORBIDDEN_AT_SERVER_IMPORT))


# --------------------------------------------------------------------------------------
# 6. the harness itself can go red: a budget test that cannot fail proves nothing
# --------------------------------------------------------------------------------------
def test_the_harness_sees_a_disabled_cache() -> None:
    async def warm_calls_with_zero_ttl() -> int:
        with perf.offline_settings() as settings:
            app, cache = perf.fresh_app(settings, ttl_by_source=dict.fromkeys(DEFAULT_TTL, 0.0))
            await app.metro_status()
            before = sum(cache.upstream.values())
            await app.metro_status()
            await app.aclose()
            return sum(cache.upstream.values()) - before

    assert asyncio.run(warm_calls_with_zero_ttl()) == 1


def test_the_harness_counts_a_read_beside_the_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """A source that reads upstream next to ``ctx.cached`` on every call: 0 at the cache, so the
    count at the boundary is what catches it (live, that read is a request to İBB per question)."""
    from ibb_mcp.sources.traffic import TrafficSource

    cached_read = TrafficSource.index_history

    async def and_a_raw_read(self, *args, **kwargs):
        self.ctx.load_fixture("traffic_index_1h")
        return await cached_read(self, *args, **kwargs)

    monkeypatch.setattr(TrafficSource, "index_history", and_a_raw_read)
    with perf.offline_settings() as settings:
        numbers = asyncio.run(perf.measure_tool(settings, "traffic_index", runs=10, warmup=1))
    assert numbers.warm_upstream == 10, numbers


def test_the_harness_counts_a_parse_moved_onto_the_request_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the per-version cache, 20 questions parse the reliability table 20 times."""

    async def rounds() -> None:
        with perf.offline_settings() as settings:
            app, _ = perf.fresh_app(settings)
            for _ in range(20):
                await app.line_reliability(line_code="500T")
            await app.aclose()

    reference.clear()
    monkeypatch.setattr(reference, "_PARSED", type("NeverCaches", (dict,), {"__setitem__": lambda self, k, v: None})())
    with perf.count_calls((reliability.ReliabilityTable, "from_dict")) as calls:
        asyncio.run(rounds())
    assert calls["ReliabilityTable.from_dict"] == 20
