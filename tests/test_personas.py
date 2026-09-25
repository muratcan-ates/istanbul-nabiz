"""Acceptance checks for the G2 persona behaviours, all using offline fixtures."""

from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from conftest import FIXTURES_DIR
from fastapi.testclient import TestClient

from ibb_mcp import accessibility as accessibility_module
from ibb_mcp.accessibility import SUPPORTED_NEEDS, accessible_alternative, check_needs
from ibb_mcp.eta import planned_summary
from ibb_mcp.metro_graph import MetroGraph
from ibb_mcp.models import ISTANBUL_TZ, MetroStation, PlannedDeparture, Provenance, ToolResult
from ibb_mcp.routing import DEFAULT_PARAMS, slow_walk_params
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.sources.iett import IettSource
from ibb_mcp.sources.metro_equipment import EquipmentRecord, EquipmentSnapshot
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.policy import NEEDS
from nabiz.console.step_free import CONSOLE_SUPPORTED_NEEDS, StepFreeService


def test_slow_walk_params_scale_walk_and_transfer() -> None:
    original = DEFAULT_PARAMS
    params = slow_walk_params()

    assert params.walk_kmh == pytest.approx(2.88)
    assert params.max_walk_km == pytest.approx(1.5)
    assert params.rail.transfer_seconds == 480
    assert params.comfort_per_transfer == 16
    assert original == DEFAULT_PARAMS


async def test_plan_journey_slow_walk_reports_its_assumptions(ctx: SourceContext) -> None:
    result = await Nabiz(ctx).plan_journey(origin="Taksim", destination="Kadıköy", slow_walk=True)
    assumptions = {
        item["key"]: item["value"]
        for option in result.data["options"]
        for item in option.get("assumptions", [])
    }

    assert assumptions["walk_kmh"] == pytest.approx(2.88)
    assert assumptions["rail_transfer"] == 480.0


def test_alternative_accepts_slow_walk_and_step_free_only(monkeypatch: pytest.MonkeyPatch) -> None:
    assert SUPPORTED_NEEDS == ("step_free", "slow_walk")
    assert CONSOLE_SUPPORTED_NEEDS == SUPPORTED_NEEDS
    assert check_needs(["slow_walk"]) == ("slow_walk",)
    assert check_needs(["step_free"]) == ("step_free",)
    assert check_needs([]) == ("step_free",)
    with pytest.raises(ValueError, match="Desteklenmeyen"):
        check_needs(["stroller"])

    station_rows = json.loads((FIXTURES_DIR / "metro_stations.json").read_text(encoding="utf-8"))["Data"]
    stations = [MetroStation.from_raw(row) for row in station_rows]
    record = EquipmentRecord.from_raw(
        {
            "Code": "TEST-ASN-01", "Group": "Asansör", "LineId": 3, "LineName": "M4", "StationId": 16,
            "StationName": "Kartal", "Location": None, "Type": "Arıza", "Date": "2026-09-20T08:00:00",
            "Description": None,
        }
    )
    snapshot = EquipmentSnapshot(records=[record], groups_read=["Asansör"])
    graph_params: list[Any] = []

    class DummyGraph:
        pass

    def from_stations(cls: type[MetroGraph], rows: list[MetroStation], *, params: Any = None, **kwargs: Any) -> DummyGraph:
        graph_params.append(params)
        return DummyGraph()

    monkeypatch.setattr(MetroGraph, "from_stations", classmethod(from_stations))
    monkeypatch.setattr(accessibility_module, "find_alternative", lambda *args, **kwargs: None)
    result = accessible_alternative("Kartal", ["slow_walk"], stations=stations, snapshot=snapshot)

    assert result["needs"] == ["slow_walk"]
    assert graph_params[0].transfer_seconds == 480
    assert graph_params[0].walk_speed_kmh == pytest.approx(2.88 / DEFAULT_PARAMS.walk_winding)


async def test_step_free_service_drops_unknown_needs_instead_of_failing() -> None:
    class StubNabiz:
        needs: list[str] | None = None

        async def accessible_alternative(self, station: str, needs: list[str] | None = None) -> ToolResult:
            self.needs = needs
            return ToolResult(
                data={"station": station, "lift_status": "unknown", "alternative": None, "uncertainty": []},
                provenance=Provenance(source="metro", source_url="local:test", observed_at=dt.datetime.now(dt.UTC)),
            )

    nabiz = StubNabiz()
    result = await StepFreeService(nabiz, offline=True).alternative("Kartal", ["stroller", "slow_walk"])

    assert nabiz.needs == ["slow_walk"]
    assert result["station"] == "Kartal"


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, config: Any, messages: Any, tools: Any = None, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"messages": [dict(message) for message in messages], "tools": tools})
        return {
            "content": "Metro duyurusu bulunamadı.", "tool_calls": [],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}, "model": "fake-model",
            "finish_reason": "stop", "raw": {},
        }


def _system_for_needs(ctx: SourceContext, monkeypatch: pytest.MonkeyPatch, needs: list[str]) -> str:
    fake = FakeModel()
    monkeypatch.setattr(llm, "chat", fake)
    config = llm.LlmConfig(base_url="http://model.invalid/v1", model="fake-model", provider="openai_compatible")
    app = build_console_app(
        nabiz=Nabiz(ctx), llm_config=config, guard=SpendGuard(BudgetConfig(state_path=None))
    )
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"message": "Metro hattında arıza var mı?", "needs": needs, "history": []})
    assert response.status_code == 200, response.text
    return fake.calls[0]["messages"][0]["content"]


def test_plain_language_line_reaches_the_model(ctx: SourceContext, monkeypatch: pytest.MonkeyPatch) -> None:
    system = _system_for_needs(ctx, monkeypatch, ["plain_language"])
    assert NEEDS["plain_language"] in system


def test_answer_en_need_reaches_system_prompt(ctx: SourceContext, monkeypatch: pytest.MonkeyPatch) -> None:
    with_language = _system_for_needs(ctx, monkeypatch, ["answer_en"])
    without_language = _system_for_needs(ctx, monkeypatch, [])

    assert NEEDS["answer_en"] in with_language
    assert NEEDS["answer_en"] not in without_language


def test_planned_summary_first_last_and_empty_day(load_fixture) -> None:
    departures = [PlannedDeparture.from_raw(row) for row in load_fixture("iett_planlanan")]
    summary = planned_summary(departures, "C")
    empty = planned_summary(departures, "I")

    assert len(departures) == 40 and all(row.line_code == "500T" and row.day_type == "C" for row in departures)
    assert summary == {"day_type": "C", "first_departure": "05:50", "last_departure": "12:20", "count": 40}
    assert empty == {"day_type": "I", "first_departure": None, "last_departure": None, "count": 0}
    after_midnight = [PlannedDeparture(line_code="500T", day_type="C", departure_time="24:30")]
    assert planned_summary(after_midnight, "C")["last_departure"] == "24:30"


async def test_next_arrivals_planned_flag_adds_the_block_and_changes_nothing_else(
    ctx: SourceContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ibb_mcp.eta as eta_module
    import ibb_mcp.tools as tools_module

    fixed = dt.datetime(2026, 9, 26, 5, 0, tzinfo=ISTANBUL_TZ)
    monkeypatch.setattr(tools_module, "day_type_for", lambda moment=None: "C")
    monkeypatch.setattr(tools_module, "utcnow", lambda: fixed)
    monkeypatch.setattr(eta_module, "utcnow", lambda: fixed)
    calls: list[str] = []
    original_schedule = IettSource.schedule

    async def schedule(source: IettSource, line_code: str, day_type: str | None = None):
        calls.append(day_type or "")
        return await original_schedule(source, line_code, day_type)

    monkeypatch.setattr(IettSource, "schedule", schedule)
    nabiz = Nabiz(ctx)
    regular = await nabiz.iett_next_arrivals("500T", "401351")
    count_after_regular = len(calls)
    planned = await nabiz.iett_next_arrivals("500T", "401351", planned=True)

    assert len(calls) == count_after_regular + 1 and calls[-1] == "C"
    assert "planned" not in regular.data
    assert planned.data["planned"] == {"day_type": "C", "first_departure": "05:50", "last_departure": "12:20", "count": 40}
    for key in regular.data:
        assert planned.data[key] == regular.data[key]


def _node(source: str) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    profile_url = (Path(__file__).resolve().parents[1] / "src/nabiz/console/static/js/profile.js").as_uri()
    script = f"import * as profile from {json.dumps(profile_url)};\n{source}"
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_profile_review_is_due_after_thirty_days() -> None:
    values = _node(
        "console.log(JSON.stringify(["
        "profile.profileReview({saved_at:'2026-01-01T00:00:00.000Z'},'2026-01-30T23:59:59.999Z'),"
        "profile.profileReview({saved_at:'2026-01-01T00:00:00.000Z'},'2026-01-31T00:00:00.000Z')]))"
    )

    assert values == [{"due": False, "days": 29}, {"due": True, "days": 30}]


def test_set_and_read_answer_language_are_pure() -> None:
    values = _node(
        "const storage=new Map();"
        "globalThis.window={localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)}};"
        "const original={consent:true,needs:[],stations:['Kartal'],lines:[]};"
        "const english=profile.setAnswerLanguage(original,'en');"
        "const invalid=profile.setAnswerLanguage(english,'xx');"
        "profile.writeProfile(english);const loaded=profile.readProfile();"
        "console.log(JSON.stringify({original,english,invalid,answer:profile.answerLanguage(english),"
        "fallback:profile.answerLanguage(invalid),stored:loaded.saved_at,storedNeeds:loaded.needs}))"
    )

    assert values["original"]["needs"] == []
    assert "answer_en" in values["english"]["needs"]
    assert values["answer"] == "en" and values["fallback"] == "tr"
    assert "answer_en" not in values["invalid"]["needs"]
    assert values["stored"] and values["storedNeeds"] == ["answer_en"]


def test_page_has_the_tid_line() -> None:
    page = (Path(__file__).resolve().parents[1] / "src/nabiz/console/static/index.html").read_text(encoding="utf-8")
    expected = '<a href="#" data-pending-url="tid-istanbul-senin">TİD görüntülü görüşme (İstanbul Senin)</a>'

    assert page.count(expected) == 2
    # No verified address yet: both mentions stay hidden until one is confirmed (integration, 25 Sep).
    assert page.count('<span data-pending="tid" hidden>') == 2
    assert "istanbulsenin.istanbul" not in page.casefold()
    assert "text-toggle" not in page


def test_chat_lang_button_only_toggles_reply_language() -> None:
    page = (Path(__file__).resolve().parents[1] / "src/nabiz/console/static/index.html").read_text(encoding="utf-8")

    language_row = (
        '<p id="chat-lang">Cevap dili: <button type="button" class="btn" id="chat-lang-en" '
        'aria-pressed="false">English</button></p>'
    )
    assert language_row in page
    for label in ("Profilim", "İhtiyaçlarım", "Kayıtlı yerlerim", "Gönder", "Profili sil"):
        assert label in page
    profile_js = (Path(__file__).resolve().parents[1] / "src/nabiz/console/static/js/profile.js").read_text(encoding="utf-8")
    assert "function setAnswerLanguage(profile, lang)" in profile_js
    assert "function answerLanguage(profile)" in profile_js
