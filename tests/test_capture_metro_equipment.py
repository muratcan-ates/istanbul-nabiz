"""The faulty-equipment capture script, run against a mock transport: nothing leaves the machine."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import httpx
import pytest
from conftest import REPO_ROOT

from ibb_mcp import http
from ibb_mcp.http import PoliteClient

_spec = importlib.util.spec_from_file_location("capture_metro_equipment", REPO_ROOT / "scripts" / "capture_metro_equipment.py")
capture = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = capture
assert _spec.loader is not None
_spec.loader.exec_module(capture)
#: Read before the fixture below sets it to zero for speed.
GAP_AS_SHIPPED = capture.MIN_GAP_S


@pytest.fixture(autouse=True)
def _no_spacing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(http.HOST_MIN_INTERVAL, "api.ibb.gov.tr", 0.0)
    monkeypatch.setattr(capture, "MIN_GAP_S", 0.0)


def test_the_plan_is_four_calls_with_valid_bodies() -> None:
    calls = capture.plan("20260925")
    assert len(calls) == capture.MAX_CALLS == 4
    assert [c.method for c in calls] == ["GET", "POST", "POST", "POST"]
    assert [c.body for c in calls[1:]] == [{"EquipmentGroupName": g} for g in ("Asansör", "Yürüyen Merdiven", "Yürüyen Bant")]
    assert calls[0].name == "metro_faulty_equipments_20260925"
    assert calls[1].name == "metro_faulty_equipment_details_asansor_20260925"


def test_a_dry_run_sends_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert capture.main([]) == 0
    assert "none sent" in capsys.readouterr().out


def test_the_spacing_rule_is_at_least_six_seconds() -> None:
    assert GAP_AS_SHIPPED >= 6.0


async def test_run_writes_good_answers_and_reports_failures_by_status_only(tmp_path: pathlib.Path) -> None:
    sent: list[tuple[str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((request.method, request.content))
        if request.method == "GET":
            return httpx.Response(200, json={"Success": True, "Error": None, "Data": [{"Name": "Asansör", "Inactive": 1}]})
        group = json.loads(request.content)["EquipmentGroupName"]
        if group == "Yürüyen Bant":
            return httpx.Response(404, text="Server Error at C:\\build\\Metro.cs")
        if group == "Yürüyen Merdiven":
            return httpx.Response(200, json={"Success": False, "Error": "System.Exception at C:\\x", "Data": None})
        return httpx.Response(200, json=[{"Code": "T1", "StationName": "Kartal"}])

    async with PoliteClient(transport=httpx.MockTransport(handler), max_attempts=1) as client:
        rows = await capture.run(capture.plan("20260101"), client=client, fixtures=tmp_path)

    assert len(sent) == 4 and all(body for method, body in sent if method == "POST")
    written = sorted(p.name for p in tmp_path.iterdir())
    assert written == ["metro_faulty_equipment_details_asansor_20260101.json", "metro_faulty_equipments_20260101.json"]
    by_name = {row["name"]: row for row in rows}
    assert by_name["metro_faulty_equipment_details_yuruyen_bant_20260101"]["status"] == 404
    assert not by_name["metro_faulty_equipment_details_yuruyen_merdiven_20260101"]["written"]
    assert "C:\\" not in json.dumps(rows)

    capture.merge_report(tmp_path, rows)
    capture.merge_report(tmp_path, rows)  # a second run replaces its rows, it does not duplicate them
    report = json.loads((tmp_path / "_capture_report.json").read_text(encoding="utf-8"))
    assert sorted(r["name"] for r in report) == sorted(written_name[:-5] for written_name in written)
    assert all("captured_at_utc" in r for r in report)


def test_a_post_without_a_body_is_never_planned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capture, "details_body", lambda group: {})
    with pytest.raises(ValueError, match="without a body"):
        capture.plan("20260925")
