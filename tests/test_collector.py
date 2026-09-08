"""Tests for the collector: the component that turns İBB's "now" into history.

Everything runs offline against ``tests/fixtures`` with the conftest client that turns
any outbound request into a failure, because the collector is precisely the code that
would otherwise hammer a gateway which 503s after fifteen rapid calls.

Two things are checked harder than the rest:

* **No number plate, anywhere.** Not as a column, not as a value, not in the bytes that
  reach the lake. ``DECISIONS.md`` §7 promises the plate is dropped at the parsing
  boundary; these tests are what makes that a guarantee rather than a habit.
* **A bad tick writes nothing.** Both failure modes — the source raising and the cache
  serving a stale entry after upstream failed — must yield ``[]``, because re-recording
  yesterday's reading under today's timestamp is inventing history.

The Azure SDKs are not installed here and are not required to be: where a backend has to
be exercised, a stub module is installed in ``sys.modules`` so the real branch runs
against a fake client rather than being skipped.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import gzip
import importlib.util
import json
import pathlib
import sys
import types
from typing import Any

import pytest
from conftest import offline_settings

from ibb_mcp.cache import TTLCache
from ibb_mcp.config import Settings
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.airquality import AirQualitySource
from ibb_mcp.sources.base import SourceContext
from nabiz.collector import function_app, kusto, lake
from nabiz.collector.snapshots import (
    SNAPSHOTS,
    iso_utc,
    snapshot_air_quality,
    snapshot_fleet,
    snapshot_ispark,
    snapshot_metro,
    snapshot_traffic,
)

STAMP = dt.datetime(2026, 9, 8, 7, 15, 0, tzinfo=dt.UTC)


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
def offline_ctx(fixtures_dir: pathlib.Path, transport: Any) -> SourceContext:
    """A context reading a specific fixture directory and refusing the network."""
    return SourceContext.create(
        client=PoliteClient(transport=transport),
        cache=TTLCache(),
        settings=Settings(offline=True, fixtures_dir=fixtures_dir),
    )


def install_fake_module(monkeypatch: pytest.MonkeyPatch, name: str, **attributes: Any) -> types.ModuleType:
    """Put a stub module (and its parent packages) into ``sys.modules``.

    The collector imports every optional SDK *inside* the function that needs it, so a
    stub registered here makes the real code path run with a fake client instead of being
    skipped for lack of a wheel.
    """
    parts = name.split(".")
    for depth in range(1, len(parts)):
        parent = ".".join(parts[:depth])
        if parent not in sys.modules:
            monkeypatch.setitem(sys.modules, parent, types.ModuleType(parent))
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    if len(parts) > 1:
        monkeypatch.setattr(sys.modules[".".join(parts[:-1])], parts[-1], module, raising=False)
    return module


@pytest.fixture
def lake_dir(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Point the lake at a temporary directory with a deterministic backend."""
    monkeypatch.setenv(lake.ENV_LAKE_DIR, str(tmp_path))
    monkeypatch.setenv(lake.ENV_LAKE_FORMAT, "json")
    monkeypatch.delenv(lake.ENV_ACCOUNT, raising=False)
    return tmp_path


@pytest.fixture
def no_kusto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guarantee the ADX sink is unconfigured, whatever the developer's shell holds."""
    monkeypatch.delenv(kusto.ENV_URI, raising=False)
    monkeypatch.delenv(kusto.ENV_MI_CLIENT_ID, raising=False)
    monkeypatch.setattr(function_app, "_sink", None)
    monkeypatch.setattr(function_app, "_context", None)


# --------------------------------------------------------------------------------------
# snapshots — İSPARK
# --------------------------------------------------------------------------------------
async def test_snapshot_ispark_emits_one_row_per_lot(ctx: SourceContext, load_fixture) -> None:
    rows = await snapshot_ispark(ctx)

    assert len(rows) == len(load_fixture("ispark_park"))
    assert set(rows[0]) == {
        "park_id",
        "ts_utc",
        "snapshot_ts_utc",
        "capacity",
        "empty",
        "occupancy_pct",
        "is_open",
        "district",
    }
    assert all(isinstance(row["park_id"], int) for row in rows)


async def test_snapshot_ispark_occupancy_is_derived_not_invented(ctx: SourceContext) -> None:
    rows = await snapshot_ispark(ctx)

    usable = [r for r in rows if r["capacity"] and r["empty"] is not None]
    assert usable, "fixture should contain lots with both capacity and a free count"
    for row in usable:
        expected = round(100.0 * (row["capacity"] - row["empty"]) / row["capacity"], 1)
        assert row["occupancy_pct"] == expected


async def test_snapshot_ispark_timestamps_are_iso_utc(ctx: SourceContext) -> None:
    """İSPARK's list endpoint publishes no timestamp, so both stamps are our read time."""
    rows = await snapshot_ispark(ctx)

    for row in rows:
        assert row["ts_utc"].endswith("Z")
        assert row["ts_utc"] == row["snapshot_ts_utc"]
        assert dt.datetime.fromisoformat(row["ts_utc"].replace("Z", "+00:00")).tzinfo is not None


# --------------------------------------------------------------------------------------
# snapshots — İETT fleet (the privacy-critical one)
# --------------------------------------------------------------------------------------
async def test_snapshot_fleet_schema(ctx: SourceContext, load_fixture) -> None:
    rows = await snapshot_fleet(ctx)

    assert len(rows) == len(load_fixture("iett_fleet"))
    assert set(rows[0]) == {"door_no", "ts_utc", "snapshot_ts_utc", "lat", "lon", "speed_kmh"}
    assert all(row["door_no"] for row in rows)


async def test_snapshot_fleet_never_carries_a_number_plate(ctx: SourceContext, load_fixture) -> None:
    """The plate is in the upstream payload and must not survive into a single row."""
    raw = load_fixture("iett_fleet")
    plates = {str(record["Plaka"]) for record in raw if record.get("Plaka")}
    assert plates, "fixture must actually contain plates, or this test proves nothing"

    rows = await snapshot_fleet(ctx)
    serialised = json.dumps(rows, ensure_ascii=False)

    assert not any(plate in serialised for plate in plates)
    assert not any("plaka" in key.lower() or "plate" in key.lower() for row in rows for key in row)


async def test_lake_bytes_contain_no_number_plate(
    ctx: SourceContext, load_fixture, lake_dir: pathlib.Path
) -> None:
    """The same guarantee, checked on the bytes that actually land in storage."""
    plates = {str(r["Plaka"]) for r in load_fixture("iett_fleet") if r.get("Plaka")}
    rows = await snapshot_fleet(ctx)

    written = lake.write_rows("iett_fleet_snapshot", rows, snapshot_ts=STAMP)
    payload = gzip.decompress(pathlib.Path(written.path).read_bytes()).decode("utf-8")

    assert not any(plate in payload for plate in plates)


# --------------------------------------------------------------------------------------
# snapshots — metro
# --------------------------------------------------------------------------------------
async def test_snapshot_metro_records_a_live_notice(ctx: SourceContext) -> None:
    rows = await snapshot_metro(ctx)

    assert len(rows) == 1
    assert rows[0]["line_name"] == "M7"
    assert rows[0]["has_notice"] is True
    assert rows[0]["description"]


async def test_snapshot_metro_emits_a_heartbeat_when_no_line_has_a_notice(
    tmp_path: pathlib.Path, no_network_transport
) -> None:
    """An empty feed means "no disruptions" — a fact worth storing, not an absence."""
    (tmp_path / "metro_status.json").write_text(
        json.dumps({"Success": True, "Error": None, "Data": []}), encoding="utf-8"
    )
    ctx = offline_ctx(tmp_path, no_network_transport)

    rows = await snapshot_metro(ctx)

    assert len(rows) == 1
    assert rows[0]["has_notice"] is False
    assert rows[0]["line_name"] is None
    assert rows[0]["ts_utc"] == rows[0]["snapshot_ts_utc"]


# --------------------------------------------------------------------------------------
# snapshots — traffic
# --------------------------------------------------------------------------------------
async def test_snapshot_traffic_keeps_only_the_newest_hours(ctx: SourceContext) -> None:
    """The endpoint returns 24 hours every call; storing all of them each hour is waste."""
    rows = await snapshot_traffic(ctx, hours=3)

    assert len(rows) == 3
    stamps = [row["ts_utc"] for row in rows]
    assert stamps == sorted(stamps), "rows must be oldest → newest"
    assert stamps[-1] == "2026-09-08T06:00:00Z"  # 09:00 Istanbul, the newest fixture point
    assert set(rows[0]) == {"traffic_index", "ts_utc", "snapshot_ts_utc"}
    assert all(1 <= row["traffic_index"] <= 99 for row in rows)


# --------------------------------------------------------------------------------------
# snapshots — air quality
# --------------------------------------------------------------------------------------
async def test_snapshot_air_quality_covers_every_station_without_duplicates(
    ctx: SourceContext, load_fixture
) -> None:
    stations = load_fixture("aq_stations")
    readings = load_fixture("aq_readings")

    rows = await snapshot_air_quality(ctx, hours=2)

    assert len({row["station_id"] for row in rows}) == len(stations)
    assert len(rows) == len(stations) * len(readings)
    keys = [(row["station_id"], row["ts_utc"]) for row in rows]
    assert len(set(keys)) == len(keys), "(station_id, ts_utc) must be unique after dedup"


async def test_snapshot_air_quality_window_is_anchored_to_now_not_to_the_station_cache(
    ctx: SourceContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The station list is cached for a day; anchoring to it would re-read a stale window.

    Regression test: the station cache is aged 20 hours here while staying *fresh* (its
    TTL is a day), which is exactly the state every tick after the first one is in. A
    window derived from that entry's observation time would ask İBB for yesterday's
    readings, on every hourly tick, forever.
    """
    windows: list[tuple[dt.datetime, dt.datetime]] = []
    original = AirQualitySource.readings

    async def spy(self, station_id, start, end):
        windows.append((start, end))
        return await original(self, station_id, start, end)

    monkeypatch.setattr(AirQualitySource, "readings", spy)

    await AirQualitySource(ctx).stations()
    entry = ctx.cache.peek("aq:stations")
    entry.stored_at_utc = entry.stored_at_utc - dt.timedelta(hours=20)
    assert entry.fresh, "the station list must still be a cache hit, just an old one"

    rows = await snapshot_air_quality(ctx, hours=2)

    start, end = windows[0]
    assert (end - start) == dt.timedelta(hours=2)
    assert abs((dt.datetime.now(dt.UTC) - end).total_seconds()) < 60
    assert rows[0]["snapshot_ts_utc"] == iso_utc(end)


async def test_snapshot_air_quality_publishes_no_pm25(ctx: SourceContext) -> None:
    """PM2.5 is absent from this İBB service; no column may imply otherwise."""
    rows = await snapshot_air_quality(ctx, hours=2)

    assert set(rows[0]) == {
        "station_id",
        "station_name",
        "ts_utc",
        "snapshot_ts_utc",
        "pm10",
        "so2",
        "o3",
        "no2",
        "co",
        "aqi_index",
        "dominant",
    }
    assert not any("2_5" in key or "25" in key for key in rows[0])


# --------------------------------------------------------------------------------------
# snapshots — failure behaviour
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("snapshot", list(SNAPSHOTS.values()), ids=list(SNAPSHOTS))
async def test_a_failing_source_yields_no_rows_instead_of_raising(
    snapshot, tmp_path: pathlib.Path, no_network_transport
) -> None:
    """Timers must survive an upstream outage; an empty tick is the correct outcome."""
    ctx = offline_ctx(tmp_path, no_network_transport)  # no fixtures here at all

    assert await snapshot(ctx) == []


async def test_a_stale_cache_read_is_not_recorded_as_a_new_snapshot(
    tmp_path: pathlib.Path, fixtures_dir: pathlib.Path, no_network_transport
) -> None:
    """Stale-on-error keeps live answers working; for the collector it would fake history."""
    ctx = SourceContext.create(
        client=PoliteClient(transport=no_network_transport),
        cache=TTLCache(ttl_by_source={"ispark": 0.05}),
        settings=Settings(offline=True, fixtures_dir=fixtures_dir),
    )

    first = await snapshot_ispark(ctx)
    assert first, "the first read must succeed so there is something to go stale"

    await asyncio.sleep(0.06)
    ctx.settings = Settings(offline=True, fixtures_dir=tmp_path)  # the fixture disappears
    second = await snapshot_ispark(ctx)

    assert second == []
    assert ctx.cache.stats["ispark"].stale_served == 1


# --------------------------------------------------------------------------------------
# lake
# --------------------------------------------------------------------------------------
def test_lake_round_trips_rows(lake_dir: pathlib.Path) -> None:
    rows = [
        {"park_id": 1, "ts_utc": "2026-09-08T07:15:00Z", "district": "ÜMRANİYE", "empty": None},
        {"park_id": 2, "ts_utc": "2026-09-08T07:15:00Z", "district": "ŞİŞLİ", "empty": 3},
    ]

    written = lake.write_rows("ispark_snapshot", rows, snapshot_ts=STAMP)

    assert written.backend == "local-json"
    assert written.rows == 2
    assert lake.read_rows(written.path) == rows


def test_lake_partitions_by_source_and_hour_in_utc(lake_dir: pathlib.Path) -> None:
    written = lake.write_rows("aq_hourly", [{"a": 1}], snapshot_ts=STAMP)

    relative = pathlib.Path(written.path).relative_to(lake_dir)
    assert relative.parent.as_posix() == "aq_hourly/year=2026/month=09/day=08/hour=07"
    assert relative.name.startswith("20260908T071500Z-")
    assert relative.name.endswith(".ndjson.gz")


def test_lake_naming_is_content_addressed(lake_dir: pathlib.Path) -> None:
    """A retried tick with identical rows must overwrite its file, not add a second one."""
    rows = [{"traffic_index": 47, "ts_utc": "2026-09-08T04:00:00Z"}]

    first = lake.write_rows("traffic_index_hourly", rows, snapshot_ts=STAMP)
    again = lake.write_rows("traffic_index_hourly", rows, snapshot_ts=STAMP)
    different = lake.write_rows("traffic_index_hourly", [{"traffic_index": 48}], snapshot_ts=STAMP)

    assert first.path == again.path
    assert different.path != first.path
    assert len(list(pathlib.Path(first.path).parent.iterdir())) == 2


def test_lake_naming_ignores_sub_second_jitter_in_the_tick(lake_dir: pathlib.Path) -> None:
    """The only production caller stamps every tick with ``datetime.now(UTC)``.

    Regression test: the hashed part of the name used to carry microseconds while the
    visible prefix carried seconds, so two writes of byte-identical rows inside one second
    produced two files and the module's idempotency guarantee was unreachable from
    ``run_job``. Distinct seconds must still produce distinct files.
    """
    rows = [{"traffic_index": 47, "ts_utc": "2026-09-08T04:00:00Z"}]
    early = STAMP.replace(microsecond=123456)
    late = STAMP.replace(microsecond=987654)

    first = lake.write_rows("traffic_index_hourly", rows, snapshot_ts=early)
    again = lake.write_rows("traffic_index_hourly", rows, snapshot_ts=late)
    next_second = lake.write_rows("traffic_index_hourly", rows, snapshot_ts=STAMP + dt.timedelta(seconds=1))

    assert first.path == again.path
    assert next_second.path != first.path
    assert len(list(pathlib.Path(first.path).parent.iterdir())) == 2


def test_lake_skips_an_empty_snapshot(lake_dir: pathlib.Path) -> None:
    """No rows means the tick learned nothing; an empty file would look like data."""
    written = lake.write_rows("metro_status", [], snapshot_ts=STAMP)

    assert written.skipped is True
    assert written.rows == 0
    assert not any(lake_dir.iterdir())


def test_lake_backend_follows_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(lake.ENV_ACCOUNT, raising=False)
    monkeypatch.setenv(lake.ENV_LAKE_FORMAT, "json")
    assert lake.choose_backend() == "local-json"

    monkeypatch.setenv(lake.ENV_ACCOUNT, "nabizstore")
    assert lake.choose_backend() == "blob"


def test_lake_uses_delta_when_the_wheels_are_present(
    lake_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    def write_deltalake(uri, data, **kwargs):
        calls.append({"uri": uri, "data": data, **kwargs})

    install_fake_module(monkeypatch, "pyarrow")
    install_fake_module(monkeypatch, "deltalake", write_deltalake=write_deltalake)
    monkeypatch.setenv(lake.ENV_LAKE_FORMAT, "auto")

    assert lake.choose_backend() == "local-delta"
    written = lake.write_rows("ispark_snapshot", [{"park_id": 1}], snapshot_ts=STAMP)

    assert written.backend == "local-delta"
    assert calls[0]["partition_by"] == ["year", "month", "day", "hour"]
    assert calls[0]["mode"] == "append"
    assert calls[0]["data"][0] == {"park_id": 1, "year": "2026", "month": "09", "day": "08", "hour": "07"}


def test_lake_uploads_to_blob_when_a_storage_account_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploads: list[dict[str, Any]] = []

    class FakeBlobClient:
        def __init__(self, container: str, blob: str) -> None:
            self.container, self.blob = container, blob

        def upload_blob(self, data: bytes, overwrite: bool = False) -> None:
            uploads.append({"container": self.container, "blob": self.blob, "data": data, "overwrite": overwrite})

    class FakeBlobServiceClient:
        def __init__(self, account_url: str | None = None, credential: Any = None) -> None:
            self.account_url, self.credential = account_url, credential

        def get_blob_client(self, container: str, blob: str) -> FakeBlobClient:
            return FakeBlobClient(container, blob)

    install_fake_module(monkeypatch, "azure.storage.blob", BlobServiceClient=FakeBlobServiceClient)
    install_fake_module(monkeypatch, "azure.identity", DefaultAzureCredential=lambda: "managed-identity")
    monkeypatch.setenv(lake.ENV_ACCOUNT, "nabizstore")
    monkeypatch.setenv(lake.ENV_CONTAINER, "bronze")
    monkeypatch.delenv(lake.ENV_CONNECTION_STRING, raising=False)

    written = lake.write_rows("iett_fleet_snapshot", [{"door_no": "A-001"}], snapshot_ts=STAMP)

    assert written.backend == "blob"
    assert uploads[0]["container"] == "bronze"
    assert uploads[0]["blob"].startswith("iett_fleet_snapshot/year=2026/month=09/day=08/hour=07/")
    assert uploads[0]["overwrite"] is True
    assert lake.decode_ndjson_gz(uploads[0]["data"]) == [{"door_no": "A-001"}]


async def test_lake_async_wrapper_matches_the_sync_writer(lake_dir: pathlib.Path) -> None:
    written = await lake.awrite_rows("metro_status", [{"line_name": "M7"}], snapshot_ts=STAMP)

    assert lake.read_rows(written.path) == [{"line_name": "M7"}]


# --------------------------------------------------------------------------------------
# kusto
# --------------------------------------------------------------------------------------
def test_kusto_is_a_silent_no_op_when_unconfigured(no_kusto: None) -> None:
    """The free cluster is optional; the lake is the durable copy."""
    sink = kusto.KustoSink()

    assert sink.enabled is False
    assert sink.ingest("ispark_snapshot", [{"park_id": 1}]) == 0


def test_kusto_ensure_tables_emits_create_merge_and_streaming_policy() -> None:
    commands = kusto.ensure_tables()

    creates = [c for c in commands if c.startswith(".create-merge table")]
    policies = [c for c in commands if "policy streamingingestion enable" in c]
    mappings = [c for c in commands if "ingestion json mapping" in c]

    assert len(creates) == len(policies) == len(mappings) == len(kusto.TABLES)
    assert ".create-merge table traffic_index_hourly (traffic_index:int, ts_utc:datetime, snapshot_ts_utc:datetime)" in creates
    assert ".alter table aq_hourly policy streamingingestion enable" in policies


def test_kusto_principal_command_matches_the_documented_gate() -> None:
    command = kusto.principal_command("11111111-2222-3333-4444-555555555555", "tenant-id", database="nabiz")

    assert command == ".add database nabiz ingestors ('aadapp=11111111-2222-3333-4444-555555555555;tenant-id')"


async def test_kusto_table_columns_match_the_snapshot_rows(ctx: SourceContext) -> None:
    """The ingestion mapping is generated from these columns, so a drift here is silent."""
    for source, snapshot in SNAPSHOTS.items():
        rows = await snapshot(ctx)
        assert rows, f"{source} produced no rows to compare against"
        columns = {name for name, _ in kusto.TABLES[source].columns}
        assert columns == set(rows[0]), f"{source} row keys and ADX columns disagree"


def test_kusto_defines_no_plate_column() -> None:
    for table in kusto.TABLES.values():
        for name, _ in table.columns:
            assert "plaka" not in name.lower()
            assert "plate" not in name.lower()


def test_kusto_ingests_through_the_streaming_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Free clusters have no ingest- endpoint, so streaming ingestion is the only path."""
    ingested: list[dict[str, Any]] = []

    class FakeStreamingClient:
        def __init__(self, kcsb: Any) -> None:
            self.kcsb = kcsb

        def ingest_from_stream(self, stream: Any, properties: Any) -> None:
            ingested.append({"payload": stream.read(), "properties": properties})

    class FakeProperties:
        def __init__(self, database: str, table: str, data_format: Any, ingestion_mapping_reference: str) -> None:
            self.database, self.table = database, table
            self.data_format, self.mapping = data_format, ingestion_mapping_reference

    class FakeKcsb:
        @staticmethod
        def with_aad_managed_service_identity_authentication(uri: str, client_id: str) -> str:
            return f"msi:{uri}:{client_id}"

    install_fake_module(monkeypatch, "azure.kusto.data", KustoConnectionStringBuilder=FakeKcsb, KustoClient=object)
    install_fake_module(monkeypatch, "azure.kusto.data.data_format", DataFormat=types.SimpleNamespace(JSON="json"))
    install_fake_module(
        monkeypatch,
        "azure.kusto.ingest",
        KustoStreamingIngestClient=FakeStreamingClient,
        IngestionProperties=FakeProperties,
    )
    monkeypatch.setenv(kusto.ENV_URI, "https://nabiz.kusto.windows.net")
    monkeypatch.setenv(kusto.ENV_MI_CLIENT_ID, "client-id")

    sink = kusto.KustoSink()
    accepted = sink.ingest("traffic_index_hourly", [{"traffic_index": 47}, {"traffic_index": 48}])

    assert sink.enabled is True
    assert accepted == 2
    assert ingested[0]["properties"].table == "traffic_index_hourly"
    assert ingested[0]["properties"].mapping == "traffic_index_hourly_mapping"
    assert ingested[0]["payload"].decode().splitlines() == ['{"traffic_index":47}', '{"traffic_index":48}']
    assert sink.client().kcsb == "msi:https://nabiz.kusto.windows.net:client-id"


def test_kusto_ingest_failure_keeps_the_tick_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADX is explicitly not on the critical path; the rows are already in the lake."""

    class ExplodingClient:
        def __init__(self, kcsb: Any) -> None:
            raise RuntimeError("cluster is asleep")

    install_fake_module(monkeypatch, "azure.kusto.data", KustoConnectionStringBuilder=object, KustoClient=object)
    install_fake_module(monkeypatch, "azure.kusto.data.data_format", DataFormat=types.SimpleNamespace(JSON="json"))
    install_fake_module(
        monkeypatch,
        "azure.kusto.ingest",
        KustoStreamingIngestClient=ExplodingClient,
        IngestionProperties=lambda **kwargs: kwargs,
    )
    monkeypatch.setenv(kusto.ENV_URI, "https://nabiz.kusto.windows.net")
    monkeypatch.setenv(kusto.ENV_MI_CLIENT_ID, "client-id")

    assert kusto.KustoSink().ingest("metro_status", [{"line_name": "M7"}]) == 0


def test_kusto_auth_order_is_managed_identity_then_cli_then_device(monkeypatch: pytest.MonkeyPatch) -> None:
    """Device code must be unreachable in Azure: it needs a human at a browser."""
    monkeypatch.delenv(kusto.ENV_AUTH, raising=False)
    monkeypatch.setenv(kusto.ENV_MI_CLIENT_ID, "client-id")
    assert kusto.choose_auth() == "msi"

    monkeypatch.delenv(kusto.ENV_MI_CLIENT_ID)
    monkeypatch.setattr(kusto.shutil, "which", lambda name: "/usr/local/bin/az")
    assert kusto.choose_auth() == "azcli"

    monkeypatch.setattr(kusto.shutil, "which", lambda name: None)  # a Functions host
    assert kusto.choose_auth() == "device"

    monkeypatch.setenv(kusto.ENV_AUTH, "azcli")
    assert kusto.choose_auth() == "azcli"


def test_kusto_refuses_an_unknown_source() -> None:
    assert kusto.KustoSink(uri="https://x").ingest("not_a_table", [{"a": 1}]) == 0


# --------------------------------------------------------------------------------------
# function app
# --------------------------------------------------------------------------------------
def test_function_app_imports_without_the_azure_sdk() -> None:
    """The module has to be importable — and testable — with no Functions runtime."""
    if function_app.func is None:
        assert function_app.app is None, "without the SDK there is nothing to register"
    else:  # pragma: no cover - only when azure-functions is installed locally
        assert function_app.app is not None
    assert len(function_app.JOBS) == 5
    assert {job.source for job in function_app.JOBS} == set(SNAPSHOTS)


def test_timers_register_against_the_functions_v2_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-import the module with a stub SDK, so the decorator wiring is actually executed.

    Without this the whole registration block is dead code until it reaches Azure, where a
    typo in an argument name costs a deployment instead of a test.
    """
    registered: list[dict[str, Any]] = []

    class FakeFunctionApp:
        def function_name(self, name: str):
            def decorate(fn):
                registered.append({"name": name, "fn": fn})
                return fn

            return decorate

        def timer_trigger(self, *, schedule: str, arg_name: str, **kwargs: Any):
            def decorate(fn):
                registered.append({"schedule": schedule, "arg_name": arg_name, "fn": fn, **kwargs})
                return fn

            return decorate

    install_fake_module(
        monkeypatch,
        "azure.functions",
        FunctionApp=FakeFunctionApp,
        TimerRequest=object,
    )

    # Loaded under a throwaway name so the package-level module keeps its SDK-less state.
    # It has to be in sys.modules before exec: dataclasses resolves string annotations
    # through sys.modules[cls.__module__].
    name = "nabiz_collector_function_app_stubbed"
    spec = importlib.util.spec_from_file_location(name, function_app.__file__)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)

    assert isinstance(module.app, FakeFunctionApp)
    names = [entry["name"] for entry in registered if "name" in entry]
    schedules = [entry["schedule"] for entry in registered if "schedule" in entry]
    assert names == [
        "IsparkCollector",
        "FleetCollector",
        "MetroCollector",
        "TrafficCollector",
        "AirQualityCollector",
    ]
    assert schedules == [job.cron for job in function_app.JOBS]
    assert all(entry["arg_name"] == "timer" for entry in registered if "arg_name" in entry)
    assert all(entry["run_on_startup"] is False for entry in registered if "run_on_startup" in entry)


def test_timer_schedules_are_six_field_ncrontab() -> None:
    """Flex Consumption ignores WEBSITE_TIME_ZONE, so these are UTC by necessity."""
    for job in function_app.JOBS:
        assert len(job.cron.split()) == 6, f"{job.name}: {job.cron}"

    assert function_app.ISPARK.cron == "0 */10 * * * *"
    assert function_app.FLEET.cron == "0 */2 * * * *"

    hourly = [function_app.METRO, function_app.TRAFFIC, function_app.AIR_QUALITY]
    minutes = [job.cron.split()[1] for job in hourly]
    assert len(set(minutes)) == len(minutes), "hourly timers must not all fire on the same minute"


async def test_run_all_once_writes_every_source(
    ctx: SourceContext, lake_dir: pathlib.Path, no_kusto: None
) -> None:
    summaries = await function_app.run_all_once(ctx=ctx)

    assert [s["job"] for s in summaries] == [job.name for job in function_app.JOBS]
    assert all(s["error"] is None for s in summaries)
    assert all(s["rows"] > 0 for s in summaries)
    assert all(s["kusto_rows"] == 0 for s in summaries)  # ADX unconfigured, lake unaffected
    assert all(isinstance(s["elapsed_ms"], int) for s in summaries)

    for summary in summaries:
        rows = lake.read_rows(summary["path"])
        assert len(rows) == summary["rows"]
    assert sorted(p.name for p in lake_dir.iterdir()) == sorted(SNAPSHOTS)


async def test_run_job_records_a_write_failure_without_raising(
    ctx: SourceContext, lake_dir: pathlib.Path, no_kusto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*args: Any, **kwargs: Any) -> None:
        raise OSError("storage account unreachable")

    monkeypatch.setattr(function_app, "awrite_rows", boom)

    summary = await function_app.run_job(function_app.METRO, ctx=ctx)

    assert summary["error"] == "OSError: storage account unreachable"
    assert summary["rows"] == 1
    assert summary["path"] is None


async def test_run_job_on_a_dead_source_writes_nothing_and_reports_no_error(
    tmp_path: pathlib.Path, lake_dir: pathlib.Path, no_kusto: None, no_network_transport
) -> None:
    """An outage is an ordinary, expected event: zero rows, no exception, no file."""
    dead = offline_ctx(tmp_path, no_network_transport)

    summary = await function_app.run_job(function_app.ISPARK, ctx=dead)

    assert summary == {
        "job": "ispark",
        "source": "ispark_snapshot",
        "snapshot_ts_utc": summary["snapshot_ts_utc"],
        "rows": 0,
        "backend": None,
        "path": None,
        "kusto_rows": 0,
        "elapsed_ms": summary["elapsed_ms"],
        "error": None,
    }
    assert not any(lake_dir.iterdir())


def test_collector_context_shortens_only_the_live_ttls() -> None:
    """Long TTLs are right for serving users and wrong for taking observations."""
    ctx = function_app.build_collector_context(offline_settings())

    assert ctx.cache.ttl_for("ispark") == 5.0
    assert ctx.cache.ttl_for("iett_fleet") == 5.0
    assert ctx.cache.ttl_for("metro_stations") == 86400.0  # static reference data


def test_iso_utc_normalises_naive_and_aware_moments() -> None:
    assert iso_utc(None) is None
    assert iso_utc(dt.datetime(2026, 9, 8, 7, 15)) == "2026-09-08T07:15:00Z"
    assert iso_utc(dt.datetime(2026, 9, 8, 10, 15, tzinfo=dt.timezone(dt.timedelta(hours=3)))) == "2026-09-08T07:15:00Z"
