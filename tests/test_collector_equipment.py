"""Metro equipment collection and local history, using recordings and mock transports only."""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib.util
import json
import pathlib

import httpx
import pytest
from test_metro_equipment import envelope, live_ctx, offline_ctx, record, write_recordings

from ibb_mcp import http
from ibb_mcp.config import METRO_FAULTY_EQUIPMENTS
from ibb_mcp.sources import metro_equipment
from nabiz.collector import lake
from nabiz.collector.equipment import (
    EQUIPMENT_SOURCE,
    equipment_fault_counts,
    iter_equipment_rows,
    snapshot_equipment,
    snapshots_seen_faulty,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


async def test_snapshot_equipment_emits_one_row_per_record_without_description(tmp_path: pathlib.Path) -> None:
    records = [record(code="LIFT-1"), record(code="LIFT-2", kind="Revizyon")]
    write_recordings(tmp_path, {"Asansör": records}, [{"Name": "Asansör", "Inactive": 2}])

    rows = await snapshot_equipment(offline_ctx(tmp_path))

    assert len(rows) == 2
    assert {row["equipment_code"] for row in rows} == {"LIFT-1", "LIFT-2"}
    assert all("description" not in row for row in rows)
    assert all(row["has_record"] is True and row["ts_utc"] == row["snapshot_ts_utc"] for row in rows)


async def test_snapshot_equipment_writes_a_heartbeat_for_a_group_with_no_faults(tmp_path: pathlib.Path) -> None:
    write_recordings(tmp_path, {"Asansör": []}, [{"Name": "Asansör", "Inactive": 0}])

    rows = await snapshot_equipment(offline_ctx(tmp_path))

    assert len(rows) == 1
    assert rows[0]["has_record"] is False
    assert rows[0]["group"] == "Asansör"
    assert rows[0]["status_class"] == "unknown"
    assert rows[0]["equipment_code"] is None
    assert rows[0]["summary_inactive"] == 0


async def test_snapshot_equipment_without_a_recording_yields_no_rows(tmp_path: pathlib.Path) -> None:
    rows = await snapshot_equipment(offline_ctx(tmp_path))

    assert rows == []


async def test_snapshot_equipment_stamps_the_recording_time_not_the_wall_clock(tmp_path: pathlib.Path) -> None:
    write_recordings(tmp_path, {"Asansör": [record()]}, None)
    captured = "2026-01-01T06:00:00+00:00"
    report = [{"name": "metro_faulty_equipment_details_asansor_20260101", "captured_at_utc": captured}]
    (tmp_path / "_capture_report.json").write_text(json.dumps(report), encoding="utf-8")

    rows = await snapshot_equipment(offline_ctx(tmp_path))

    assert rows and rows[0]["snapshot_ts_utc"] == "2026-01-01T06:00:00Z"
    assert rows[0]["ts_utc"] == rows[0]["snapshot_ts_utc"]


async def test_snapshot_equipment_makes_at_most_four_requests_on_the_metro_host_and_no_iett_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(http.HOST_MIN_INTERVAL, "api.ibb.gov.tr", 0.0)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            assert str(request.url) == METRO_FAULTY_EQUIPMENTS
            return httpx.Response(200, json=envelope([{"Name": "Asansör", "Inactive": 1}]))
        group = json.loads(request.content)["EquipmentGroupName"]
        return httpx.Response(200, json=envelope([record(group=group)]))

    ctx = live_ctx(handler)
    rows = await snapshot_equipment(ctx)

    assert rows
    assert len(seen) <= 4
    assert all(request.url.host == "api.ibb.gov.tr" for request in seen)
    assert ctx.client.budgets["iett"].remaining == 80
    await ctx.aclose()


async def test_a_stale_equipment_read_is_not_recorded_as_history(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_recordings(tmp_path, {"Asansör": [record()]}, [{"Name": "Asansör", "Inactive": 1}])
    monkeypatch.setattr(metro_equipment, "EQUIPMENT_TTL", 0.05)
    ctx = offline_ctx(tmp_path)

    assert await snapshot_equipment(ctx)
    await asyncio.sleep(0.06)
    for path in tmp_path.glob("metro_faulty_equipment*.json"):
        path.unlink()
    for path in tmp_path.glob("metro_faulty_equipments*.json"):
        path.unlink()

    assert await snapshot_equipment(ctx) == []


async def test_equipment_rows_land_under_their_own_lake_source(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(lake.ENV_LAKE_DIR, str(tmp_path))
    monkeypatch.setenv(lake.ENV_LAKE_FORMAT, "json")
    rows = [{"snapshot_ts_utc": "2026-01-01T00:00:00Z", "has_record": True, "equipment_code": "LIFT-1"}]
    lake.write_rows(EQUIPMENT_SOURCE, rows, snapshot_ts=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))

    files = list((tmp_path / EQUIPMENT_SOURCE).rglob("*.ndjson.gz"))
    assert len(files) == 1
    assert list(iter_equipment_rows(tmp_path)) == rows


def test_snapshots_seen_faulty_counts_distinct_snapshots_per_code(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(lake.ENV_LAKE_DIR, str(tmp_path))
    monkeypatch.setenv(lake.ENV_LAKE_FORMAT, "json")
    stamps = [dt.datetime(2026, 1, day, tzinfo=dt.UTC) for day in (1, 2, 3)]
    for index, stamp in enumerate(stamps):
        code = "A" if index in (0, 2) else "B"
        rows = [
            {"snapshot_ts_utc": stamp.isoformat(), "has_record": True, "equipment_code": code},
            {"snapshot_ts_utc": stamp.isoformat(), "has_record": True, "equipment_code": code},
        ]
        lake.write_rows(EQUIPMENT_SOURCE, rows, snapshot_ts=stamp, backend="local-json")

    assert equipment_fault_counts(tmp_path) == {"A": 2, "B": 1}
    assert snapshots_seen_faulty("A", tmp_path) == (2, 3)
    assert snapshots_seen_faulty("unknown", tmp_path) == (0, 3)


@pytest.fixture
def collect_forever():
    spec = importlib.util.spec_from_file_location("collect_forever_equipment_test", ROOT / "scripts" / "collect_forever.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


async def test_collect_forever_tick_equipment_counts_rows_and_snapshots_in_the_state(
    collect_forever, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(lake.ENV_LAKE_DIR, str(tmp_path))
    monkeypatch.setenv(lake.ENV_LAKE_FORMAT, "json")

    async def rows(_ctx):
        return [
            {"snapshot_ts_utc": "2026-01-01T00:00:00Z", "has_record": True, "equipment_code": "A"},
            {"snapshot_ts_utc": "2026-01-01T00:00:00Z", "has_record": True, "equipment_code": "B"},
        ]

    monkeypatch.setattr(collect_forever, "snapshot_equipment", rows)
    state: dict = {}

    written = await collect_forever.tick("equipment", None, None, state)

    assert written == 2
    assert state["rows"]["equipment"] == 2
    assert state["snapshots"]["equipment"] == 1
    assert "equipment" in state["ticks"]


def test_collect_status_prints_the_ekipman_block(
    collect_forever, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(lake.ENV_LAKE_DIR, str(tmp_path / "lake"))
    monkeypatch.setenv(lake.ENV_LAKE_FORMAT, "json")
    monkeypatch.setattr(collect_forever, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(collect_forever, "LOCK_PATH", tmp_path / ".lock")
    collect_forever.STATE_PATH.write_text(json.dumps({"ticks": {}, "rows": {}}), encoding="utf-8")
    lake.write_rows(
        EQUIPMENT_SOURCE,
        [{"snapshot_ts_utc": "2026-01-01T00:00:00Z", "has_record": True, "equipment_code": "A"}],
        snapshot_ts=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )

    assert collect_forever.show_status() == 0
    output = capsys.readouterr().out
    assert "ekipman (Metro arızalı ekipman):" in output
    assert "toplam snapshot: 1" in output
    assert "farklı ekipman kodu: 1" in output
    assert "A  1/1 snapshot" in output
