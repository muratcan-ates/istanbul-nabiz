"""Tests for the run-once collector that Azure Container Apps Jobs executes.

The job replaces a laptop process that kept stopping, so what is checked here is what the
laptop never had to prove:

* **The İETT budget holds by arithmetic.** A process that lives for one tick never fills
  an hourly counter, so the schedule itself must keep the spend under the limit — and the
  schedule exists twice, in Python and in Bicep, so the two are compared.
* **Nothing is lost in the move.** All seven sources are collected, and the ETA prediction
  log is the laptop's, byte for byte on the same input, so the measured error stays one
  series. ``scripts/collect_forever.py`` is loaded read-only for that comparison; it is the
  running collector and is never modified.
* **The exit code means something.** A quiet night is not a failure; an unreachable
  gateway is.

Everything is offline. Where the client must be exercised for real (the budget and the
retry policy), it is given an ``httpx.MockTransport`` that serves a canned answer and counts
requests, so no test can reach İBB.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib.util
import json
import pathlib
import re
import shutil
import sys
import types
from typing import Any

import httpx
import pytest
from conftest import FIXTURES_DIR, REPO_ROOT

from ibb_mcp import http
from ibb_mcp.cache import TTLCache
from ibb_mcp.config import Settings
from ibb_mcp.http import PoliteClient
from ibb_mcp.models import Stop
from ibb_mcp.sources.base import SourceContext
from nabiz.collector import eta_log, job, kusto, lake
from nabiz.collector.snapshots import count_failed_reads, snapshot_fleet, snapshot_lines

MAIN_BICEP = REPO_ROOT / "infra" / "main.bicep"
JOBS_BICEP = REPO_ROOT / "infra" / "modules" / "collectorjobs.bicep"
CONTAINERAPPS_BICEP = REPO_ROOT / "infra" / "modules" / "containerapps.bicep"
PARAMETERS_JSON = REPO_ROOT / "infra" / "main.parameters.json"
DOCKERFILE = REPO_ROOT / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"

#: The newest position in tests/fixtures/iett_hat_500T.json is 06:08:59Z on 8 Sep. The ETA
#: engine drops stale positions relative to "now", so predictions are made as of just after.
FIXTURE_NOW = dt.datetime(2026, 9, 8, 6, 9, 30, tzinfo=dt.UTC)


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
def load_script(name: str, monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Import ``scripts/<name>.py`` read-only, under a throwaway module name.

    The script is executed, not edited: loading it defines its constants and functions
    and does nothing else (both scripts keep their work behind ``if __name__``).
    """
    path = REPO_ROOT / "scripts" / f"{name}.py"
    module_name = f"_readonly_{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def offline_ctx(fixtures_dir: pathlib.Path, transport: httpx.AsyncBaseTransport) -> SourceContext:
    return SourceContext.create(
        client=PoliteClient(transport=transport),
        cache=TTLCache(),
        settings=Settings(offline=True, fixtures_dir=fixtures_dir),
    )


class FakeIndex:
    """Just enough of ``GtfsIndex`` for the ETA engine: every target stop is known.

    Each stop sits at the mean position of the fixture buses, so the distance method has
    something to measure and the output is not trivially empty.
    """

    def __init__(self, lat: float, lon: float) -> None:
        self.lat, self.lon = lat, lon

    def lookup_stop(self, stop_code: str) -> Stop:
        return Stop(stop_code=stop_code, name=f"DURAK {stop_code}", lat=self.lat, lon=self.lon)


async def fixture_line_rows(ctx: SourceContext) -> list[dict[str, Any]]:
    return await snapshot_lines(ctx, eta_log.WATCHED_LINES)


def fake_gtfs(rows: list[dict[str, Any]]) -> tuple[FakeIndex, dict]:
    located = [r for r in rows if r["lat"] is not None and r["lon"] is not None]
    lat = sum(r["lat"] for r in located) / len(located)
    lon = sum(r["lon"] for r in located) / len(located)
    return FakeIndex(lat, lon), {}


@pytest.fixture
def lake_dir(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    monkeypatch.setenv(lake.ENV_LAKE_DIR, str(tmp_path / "lake"))
    monkeypatch.setenv(lake.ENV_LAKE_FORMAT, "json")
    monkeypatch.delenv(lake.ENV_ACCOUNT, raising=False)
    return tmp_path / "lake"


@pytest.fixture
def no_kusto(monkeypatch: pytest.MonkeyPatch) -> kusto.KustoSink:
    monkeypatch.delenv(kusto.ENV_URI, raising=False)
    monkeypatch.delenv(kusto.ENV_MI_CLIENT_ID, raising=False)
    return kusto.KustoSink()


# --------------------------------------------------------------------------------------
# coverage: seven sources, each scheduled once, each with a table
# --------------------------------------------------------------------------------------
def test_the_jobs_cover_all_seven_sources_and_every_adx_table() -> None:
    """The Function had five timers and no ETA log; the jobs must not repeat that gap."""
    tables = [table for spec in job.SOURCES.values() for table in spec.tables]

    assert len(tables) == len(set(tables)) == 7
    assert set(tables) == set(kusto.TABLES)
    assert {"iett_line_snapshot", "eta_predictions"} <= set(tables)


def test_every_source_is_scheduled_exactly_once() -> None:
    scheduled = [name for schedule in job.SCHEDULES for name in schedule.sources]

    assert sorted(scheduled) == sorted(job.SOURCES)


# --------------------------------------------------------------------------------------
# the budget, as arithmetic
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("cron", "per_day", "peak"),
    [
        ("*/3 * * * *", 480, 20),
        ("1-59/10 * * * *", 144, 6),
        ("5 * * * *", 24, 1),
        ("10 */6 * * *", 4, 1),
        ("16 */12 * * *", 2, 1),
        ("0,30 8-9 * * *", 4, 2),
    ],
)
def test_cron_expansion(cron: str, per_day: int, peak: int) -> None:
    assert len(job.cron_minutes_of_day(cron)) == per_day
    assert job.peak_runs_per_hour(cron) == peak


@pytest.mark.parametrize("cron", ["* * * * 1-5", "0 0 1 * *", "*/3 * * *", "61 * * * *", "*/0 * * * *"])
def test_cron_expansion_refuses_what_it_cannot_count(cron: str) -> None:
    """A restriction the checker ignored would make its numbers wrong; it refuses instead."""
    with pytest.raises(ValueError):
        job.cron_minutes_of_day(cron)


async def test_the_whole_schedule_stays_under_the_iett_budget() -> None:
    """66 requests in the worst hour against PoliteClient's 80 (İETT documents 100).

    Pinned to 66, not only bounded, because DECISIONS #10 and docs/deploy.md quote the
    number: changing the schedule should be a deliberate edit of all three.
    """
    client = PoliteClient()
    limit = client.budgets["iett"].limit
    await client.aclose()

    assert job.iett_calls_peak_hour() == 66
    assert job.iett_calls_peak_hour() <= limit


def test_the_lines_job_keeps_the_cadence_the_eta_report_assumes() -> None:
    """eta_report.py treats half the tick interval as the floor on measurable error."""
    lines = next(s for s in job.SCHEDULES if "lines" in s.sources)
    minutes = job.cron_minutes_of_day(lines.cron)
    gaps = {b - a for a, b in zip(minutes, minutes[1:], strict=False)}

    eta_report = pathlib.Path(REPO_ROOT / "scripts" / "eta_report.py").read_text(encoding="utf-8")
    declared = float(re.search(r"^TICK_INTERVAL_MINUTES = ([\d.]+)", eta_report, re.MULTILINE).group(1))
    assert gaps == {int(declared)}


def test_executions_of_one_job_can_never_overlap() -> None:
    """replicaTimeout below the shortest gap means a slow tick is killed before the next."""
    for schedule in job.SCHEDULES:
        minutes = job.cron_minutes_of_day(schedule.cron)
        wrapped = minutes + [minutes[0] + 1440]
        shortest_gap_s = min(b - a for a, b in zip(wrapped, wrapped[1:], strict=False)) * 60
        assert schedule.replica_timeout_s < shortest_gap_s, schedule.job
        assert schedule.deadline_s > 0, schedule.job


def test_only_lines_and_city_ever_start_in_the_same_minute() -> None:
    """A 3-minute and a 10-minute cadence must meet twice an hour; nothing else may."""
    starts = {s.job: set(job.cron_minutes_of_day(s.cron)) for s in job.SCHEDULES}
    shared = {
        (a, b): len(starts[a] & starts[b])
        for i, a in enumerate(starts)
        for b in list(starts)[i + 1 :]
        if starts[a] & starts[b]
    }

    assert shared == {("lines", "city"): 48}


# --------------------------------------------------------------------------------------
# the schedule exists twice: Python and Bicep must agree
# --------------------------------------------------------------------------------------
def bicep_job_schedules() -> list[tuple[str, str, tuple[str, ...], int]]:
    """The ``collectorJobSchedules`` default in main.bicep, read without a Bicep compiler."""
    text = MAIN_BICEP.read_text(encoding="utf-8")
    block = re.search(r"^param collectorJobSchedules array = \[\n(.*?)^\]", text, re.MULTILINE | re.DOTALL)
    assert block, "main.bicep no longer declares collectorJobSchedules as a literal array"
    entries = re.findall(
        r"\{\s*name: '([^']+)'\s*cron: '([^']+)'\s*sources: '([^']+)'\s*replicaTimeout: (\d+)\s*\}",
        block.group(1),
    )
    return [(name, cron, tuple(sources.split(",")), int(timeout)) for name, cron, sources, timeout in entries]


def test_bicep_declares_exactly_the_python_schedule() -> None:
    declared = bicep_job_schedules()

    assert declared == [(s.job, s.cron, s.sources, s.replica_timeout_s) for s in job.SCHEDULES]


def test_bicep_sources_parse_as_the_job_parses_them() -> None:
    for _name, _cron, sources, _timeout in bicep_job_schedules():
        assert job.parse_sources(",".join(sources)) == sources


def test_job_names_fit_the_container_apps_naming_rule() -> None:
    """caj-<name>-<13-char uniqueString>: 2-32 chars, lowercase letters, digits, hyphens."""
    for schedule in job.SCHEDULES:
        worst = f"caj-{schedule.job}-{'x' * 13}"
        assert len(worst) <= 32, worst
        assert re.fullmatch(r"[a-z][a-z0-9-]*[a-z0-9]", worst), worst


def test_the_job_module_is_consumption_only_single_replica_and_secret_free() -> None:
    """The settings that decide the bill and the budget, asserted on the template text."""
    code = "\n".join(line.split("//", 1)[0] for line in JOBS_BICEP.read_text(encoding="utf-8").splitlines())

    assert "'Microsoft.App/jobs@2024-03-01'" in code
    assert "triggerType: 'Schedule'" in code
    assert re.search(r"parallelism: 1\b", code)
    assert re.search(r"replicaCompletionCount: 1\b", code)
    assert re.search(r"replicaRetryLimit: 0\b", code), "a retried execution is an unplanned İETT request"
    assert "workloadProfileName" not in code, "a workload profile bills per hour; the free grant is Consumption"
    assert "secrets" not in code and "listKeys" not in code
    assert re.search(r"param deadlineMarginSeconds int = (\d+)", code).group(1) == str(job.DEADLINE_MARGIN_S)
    assert "'nabiz.collector.job'" in code


def test_the_jobs_are_never_deployed_with_a_placeholder_image() -> None:
    """A placeholder web server in a scheduled job would run until replicaTimeout every tick."""
    code = MAIN_BICEP.read_text(encoding="utf-8")

    assert re.search(r"var deployJobs = deployContainerApp && deployCollectorJobs && !empty\(collectorImage\)", code)
    assert re.search(r"module collectorJobs 'modules/collectorjobs.bicep' = if \(deployJobs\)", code)
    assert "placeholder" not in JOBS_BICEP.read_text(encoding="utf-8").split("resource collectorJobs", 1)[1]
    parameters = json.loads(PARAMETERS_JSON.read_text(encoding="utf-8"))["parameters"]
    assert parameters["mcpDeployedImage"]["value"] == "${SERVICE_MCP_IMAGE_NAME=}"


def test_the_collector_identity_may_pull_the_image() -> None:
    main = MAIN_BICEP.read_text(encoding="utf-8")
    apps = CONTAINERAPPS_BICEP.read_text(encoding="utf-8")

    assert "acrPullPrincipalIds: deployCollectorJobs ? [collectorIdentity.outputs.principalId] : []" in main
    assert re.search(r"for principalId in acrPullPrincipalIds: if \(createRegistry\)", apps)


# --------------------------------------------------------------------------------------
# the image the jobs run
# --------------------------------------------------------------------------------------
def test_the_image_carries_what_the_collector_needs() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    ignore = DOCKERIGNORE.read_text(encoding="utf-8").splitlines()

    # The SDKs the lake and ADX sinks import, installed and proven importable at build time.
    assert 'pip install --no-cache-dir ".[job]"' in dockerfile
    for module in ("azure.identity", "azure.storage.blob", "azure.kusto.ingest"):
        assert module in dockerfile
    # The ETA log finds GTFS through this variable; the jobs set no GTFS path of their own.
    assert "NABIZ_GTFS_DIR=/app/data/reference/gtfs" in dockerfile
    # Allow-list: the reference data is in, the 150 MB stop_times file is not.
    assert "*" in ignore and "!src" in ignore and "!data/reference" in ignore
    assert "data/reference/gtfs/stop_times.txt" in ignore


# --------------------------------------------------------------------------------------
# the ETA log is the laptop's
# --------------------------------------------------------------------------------------
def test_eta_targets_are_the_laptop_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    laptop = load_script("collect_forever", monkeypatch)

    assert eta_log.WATCHED_LINES == laptop.WATCHED_LINES
    assert eta_log.ETA_TARGETS == laptop.ETA_TARGETS
    assert laptop.INTERVALS_S["lines"] == 180, "the laptop's line cadence the lines job copies"


async def test_eta_predictions_match_the_laptop_on_the_same_input(
    ctx: SourceContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same rows, same index, same clock: the two builders must produce identical rows."""
    rows = await fixture_line_rows(ctx)
    index, sequences = fake_gtfs(rows)
    laptop = load_script("collect_forever", monkeypatch)
    for module in (laptop, eta_log):
        monkeypatch.setattr(module, "get_index", lambda settings, index=index: index)
        monkeypatch.setattr(module, "load_stop_sequences", lambda settings, sequences=sequences: sequences)
    monkeypatch.setattr(laptop, "utcnow", lambda: FIXTURE_NOW)

    ours = eta_log.build_eta_predictions(rows, ctx.settings, now=FIXTURE_NOW)
    theirs = laptop.build_eta_predictions(rows, ctx.settings)

    assert ours, "the fixture should yield predictions, or this comparison proves nothing"
    assert ours == theirs


async def test_eta_prediction_rows_match_the_adx_table(ctx: SourceContext, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = await fixture_line_rows(ctx)
    index, sequences = fake_gtfs(rows)
    monkeypatch.setattr(eta_log, "get_index", lambda settings: index)
    monkeypatch.setattr(eta_log, "load_stop_sequences", lambda settings: sequences)

    predictions = eta_log.build_eta_predictions(rows, ctx.settings, now=FIXTURE_NOW)

    assert predictions
    assert set(predictions[0]) == {name for name, _ in kusto.TABLES["eta_predictions"].columns}
    assert not any("plaka" in key.lower() or "plate" in key.lower() for key in predictions[0])


def test_rows_to_positions_keeps_the_stored_timestamp() -> None:
    """The lake's ``...Z`` stamp must survive the round trip: an arrival with no age is withheld."""
    rows = [{"door_no": "C-1", "lat": 41.0, "lon": 29.0, "line_code": "500T", "ts_utc": "2026-09-08T06:08:53Z"}]

    (bus,) = eta_log.rows_to_positions(rows)

    assert bus.reported_at == dt.datetime(2026, 9, 8, 6, 8, 53, tzinfo=dt.UTC)


def test_eta_predictions_refuse_to_hide_missing_gtfs(tmp_path: pathlib.Path) -> None:
    """An image without GTFS must say so on every tick, not log nothing forever."""
    rows = [{"line_code": "500T", "door_no": "C-1", "lat": 41.0, "lon": 29.0, "ts_utc": "2026-09-08T06:00:00Z"}]

    with pytest.raises(FileNotFoundError):
        eta_log.build_eta_predictions(rows, Settings(offline=True, gtfs_dir=tmp_path))
    assert eta_log.build_eta_predictions([], Settings(offline=True, gtfs_dir=tmp_path)) == []


# --------------------------------------------------------------------------------------
# running: outcomes and the exit code
# --------------------------------------------------------------------------------------
async def test_one_run_writes_all_seven_tables(
    ctx: SourceContext, lake_dir: pathlib.Path, no_kusto: kusto.KustoSink, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = await fixture_line_rows(ctx)
    index, sequences = fake_gtfs(rows)
    monkeypatch.setattr(eta_log, "get_index", lambda settings: index)
    monkeypatch.setattr(eta_log, "load_stop_sequences", lambda settings: sequences)
    monkeypatch.setattr(eta_log, "utcnow", lambda: FIXTURE_NOW)

    code, summaries = await job.run(tuple(job.SOURCES), ctx=ctx, sink=no_kusto)

    assert code == 0
    assert {s["source"]: s["outcome"] for s in summaries} == dict.fromkeys(job.SOURCES, "ok")
    assert sorted(p.name for p in lake_dir.iterdir()) == sorted(kusto.TABLES)
    for summary in summaries:
        for table, path in summary["paths"].items():
            assert len(lake.read_rows(path)) == summary["rows"][table]


async def test_traffic_is_read_with_an_overlap_instead_of_the_laptop_gap(
    ctx: SourceContext, lake_dir: pathlib.Path, no_kusto: kusto.KustoSink
) -> None:
    """Every 6 hours, 7 hourly buckets: the laptop's 3 left half of each window unrecorded."""
    code, summaries = await job.run(["traffic"], ctx=ctx, sink=no_kusto)

    assert code == 0
    assert summaries[0]["rows"] == {"traffic_index_hourly": job.TRAFFIC_HOURS_PER_RUN}
    traffic = next(s for s in job.SCHEDULES if "traffic" in s.sources)
    cadence_h = 24 // len(job.cron_minutes_of_day(traffic.cron))
    assert cadence_h + 1 == job.TRAFFIC_HOURS_PER_RUN


async def test_a_quiet_night_is_empty_not_failed(
    tmp_path: pathlib.Path, lake_dir: pathlib.Path, no_kusto: kusto.KustoSink, no_network_transport
) -> None:
    """No buses on the watched lines is an ordinary 03:00, and exits 0."""
    (tmp_path / "iett_hat_500T.json").write_text("[]", encoding="utf-8")
    quiet = offline_ctx(tmp_path, no_network_transport)

    code, summaries = await job.run(["lines"], ctx=quiet, sink=no_kusto)

    assert code == 0
    assert summaries[0]["outcome"] == "empty"
    assert summaries[0]["failed_reads"] == []
    assert not lake_dir.exists() or not any(lake_dir.iterdir())


async def test_an_unreachable_upstream_fails_the_execution(
    tmp_path: pathlib.Path, lake_dir: pathlib.Path, no_kusto: kusto.KustoSink, no_network_transport
) -> None:
    dead = offline_ctx(tmp_path, no_network_transport)  # no fixtures at all

    code, summaries = await job.run(["ispark", "metro"], ctx=dead, sink=no_kusto)

    assert code == 1
    assert [s["outcome"] for s in summaries] == ["failed", "failed"]
    assert summaries[0]["failed_reads"] == ["ispark"]
    assert summaries[1]["failed_reads"] == ["metro_status"]


async def test_one_failed_source_does_not_fail_the_execution(
    tmp_path: pathlib.Path, lake_dir: pathlib.Path, no_kusto: kusto.KustoSink, no_network_transport
) -> None:
    shutil.copy(FIXTURES_DIR / "ispark_park.json", tmp_path / "ispark_park.json")
    half = offline_ctx(tmp_path, no_network_transport)

    code, summaries = await job.run(["ispark", "metro"], ctx=half, sink=no_kusto)

    assert code == 0
    assert [s["outcome"] for s in summaries] == ["ok", "failed"]


async def test_a_failed_write_is_a_failed_source(
    ctx: SourceContext, no_kusto: kusto.KustoSink, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rows that never reached the lake were not collected, however well they were read."""

    async def unreachable(*args: Any, **kwargs: Any) -> None:
        raise OSError("storage account unreachable")

    monkeypatch.setattr(job, "awrite_rows", unreachable)

    code, summaries = await job.run(["metro"], ctx=ctx, sink=no_kusto)

    assert code == 1
    assert summaries[0]["outcome"] == "failed"
    assert summaries[0]["error"] == "OSError: storage account unreachable"


async def test_missing_gtfs_keeps_the_positions(
    ctx: SourceContext, lake_dir: pathlib.Path, no_kusto: kusto.KustoSink, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The observed arrivals are the ground truth; losing predictions must not lose them."""

    def no_gtfs(settings: Settings) -> None:
        raise FileNotFoundError("GTFS reference files missing")

    monkeypatch.setattr(eta_log, "get_index", no_gtfs)

    code, summaries = await job.run(["lines"], ctx=ctx, sink=no_kusto)

    assert code == 0
    assert summaries[0]["outcome"] == "ok"
    assert summaries[0]["rows"]["iett_line_snapshot"] > 0
    assert summaries[0]["rows"]["eta_predictions"] == 0
    assert any("eta_predictions failed" in note for note in summaries[0]["notes"])


# --------------------------------------------------------------------------------------
# the deadline
# --------------------------------------------------------------------------------------
async def test_the_deadline_keeps_the_lines_already_read(
    ctx: SourceContext, lake_dir: pathlib.Path, no_kusto: kusto.KustoSink, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gateway stalling on the second line must cost that line, not the whole tick."""
    real = job.snapshot_lines

    async def stall_after_the_first(context: SourceContext, codes: list[str]) -> list[dict[str, Any]]:
        if codes == [eta_log.WATCHED_LINES[0]]:
            return await real(context, codes)
        await asyncio.sleep(30)
        return []

    monkeypatch.setattr(job, "snapshot_lines", stall_after_the_first)
    monkeypatch.setattr(job, "build_eta_predictions", lambda rows, settings: [])

    code, summaries = await job.run(["lines"], ctx=ctx, sink=no_kusto, deadline_s=0.3)

    assert code == 0
    assert summaries[0]["outcome"] == "ok"
    assert summaries[0]["rows"]["iett_line_snapshot"] > 0
    assert any("deadline" in note for note in summaries[0]["notes"])


async def test_a_deadline_already_spent_fails_the_remaining_sources(
    ctx: SourceContext, lake_dir: pathlib.Path, no_kusto: kusto.KustoSink
) -> None:
    code, summaries = await job.run(["metro", "traffic"], ctx=ctx, sink=no_kusto, deadline_s=0)

    assert code == 1
    assert all(s["outcome"] == "failed" and s["error"].startswith("deadline") for s in summaries)


# --------------------------------------------------------------------------------------
# the budget and the retry policy, exercised through the real client
# --------------------------------------------------------------------------------------
class CountingTransport(httpx.AsyncBaseTransport):
    """Answers every request with one status and counts them. Never reaches a network."""

    def __init__(self, status: int = 503) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, text="")


@pytest.fixture
def online_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings that take the live code path — against CountingTransport only.

    The 6-second gate is zeroed so three calls do not cost eighteen seconds of test time;
    the gate itself is covered by the client's own tests.
    """
    monkeypatch.setitem(http.HOST_MIN_INTERVAL, "api.ibb.gov.tr", 0.0)
    return Settings(offline=False, fixtures_dir=FIXTURES_DIR)


async def test_iett_is_tried_once_per_planned_call(online_settings: Settings) -> None:
    """With the default three attempts a failing gateway would triple the planned spend."""
    transport = CountingTransport(503)
    fleet_ctx = job.build_job_context(["fleet"], online_settings, transport=transport)
    try:
        with count_failed_reads() as failed:
            assert await snapshot_fleet(fleet_ctx) == []
    finally:
        await fleet_ctx.aclose()

    assert len(transport.requests) == 1
    assert failed == ["iett_fleet"]


async def test_a_job_that_plans_no_iett_call_is_refused_one(online_settings: Settings) -> None:
    transport = CountingTransport(200)
    metro_only = job.build_job_context(["metro"], online_settings, transport=transport)
    try:
        with count_failed_reads() as failed:
            assert await snapshot_fleet(metro_only) == []
    finally:
        await metro_only.aclose()

    assert transport.requests == [], "the budget must refuse before anything is sent"
    assert failed == ["iett_fleet"]


async def test_an_unplanned_extra_iett_call_fails_instead_of_overspending(
    online_settings: Settings, lake_dir: pathlib.Path, no_kusto: kusto.KustoSink, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Add a fourth watched line without updating the plan: the fourth request is refused."""
    transport = CountingTransport(503)
    lines_ctx = job.build_job_context(["lines"], online_settings, transport=transport)
    monkeypatch.setattr(job, "WATCHED_LINES", (*eta_log.WATCHED_LINES, "99X"))
    try:
        code, summaries = await job.run(["lines"], ctx=lines_ctx, sink=no_kusto)
    finally:
        await lines_ctx.aclose()

    assert len(transport.requests) == job.SOURCES["lines"].iett_calls == 3
    assert len(summaries[0]["failed_reads"]) == 4
    assert code == 1


# --------------------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------------------
def test_parse_sources() -> None:
    assert job.parse_sources("ispark,fleet") == ("ispark", "fleet")
    assert job.parse_sources(" lines ") == ("lines",)
    assert job.parse_sources("all") == tuple(job.SOURCES)
    for bad in ("", "lines,lines", "bus", "lines,bus"):
        with pytest.raises(ValueError):
            job.parse_sources(bad)


def test_main_runs_offline_and_ends_with_one_json_summary(
    lake_dir: pathlib.Path, no_kusto: kusto.KustoSink, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="nabiz.collector.job")

    code = job.main(["--sources", "metro,traffic", "--offline", "--deadline-s", "60"])

    assert code == 0
    tagged = [r.getMessage() for r in caplog.records if r.getMessage().startswith(job.SUMMARY_TAG + " ")]
    assert len(tagged) == 1
    summary = json.loads(tagged[0].split(" ", 1)[1])
    assert summary["exit_code"] == 0
    assert summary["outcomes"] == {"metro": "ok", "traffic": "ok"}


def test_main_rejects_an_unknown_source() -> None:
    with pytest.raises(SystemExit) as exit_info:
        job.main(["--sources", "bus"])
    assert exit_info.value.code == 2


def test_main_plan_prints_the_budget(capsys: pytest.CaptureFixture[str]) -> None:
    assert job.main(["--plan"]) == 0
    out = capsys.readouterr().out
    assert "İETT requests in the peak hour, all jobs: 66" in out
    for schedule in job.SCHEDULES:
        assert schedule.cron in out
