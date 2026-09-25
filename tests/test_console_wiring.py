"""The product app wired to the decision core: signals in, a card for the simulated operator,
a sealed ruling, the citizen's alternative marked approved. And the model's Arena seats.

Every İBB answer here is a recording. The Metro equipment records are written by the tests in
the verified field shape (``tests/test_metro_equipment.py``) with test values, not İBB data; the
city watch reads the committed fixtures. The ledger lives in ``tmp_path``; no model is called:
the model seats run against a fake ``llm.chat``.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import json
import pathlib
import shutil
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from conftest import FIXTURES_DIR, offline_settings, refuse_network
from fastapi.testclient import TestClient
from test_metro_equipment import record, write_recordings

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.models import Provenance, ToolResult
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console import arena_seats
from nabiz.console.app import build_console_app
from nabiz.console.arena_seats import NOT_IN_EVIDENCE, ModelSeats, parse_opinion
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.nexus_port import NO_RECORDING, already_on_board, board_key, pick_replay
from nabiz.console.signals import CITY_WATCH, Incoming, alert_incoming, city_watch, equipment_incoming
from nabiz.console.wiring import MISSIONS_DIR, wire_ports
from nexus_core import EvidenceItem, Ledger, NexusEngine, Origin, Signal, load_missions
from nexus_core.arena import convene

NOW = dt.datetime(2026, 9, 25, 9, 0, tzinfo=dt.UTC)


def unlimited() -> SpendGuard:
    return SpendGuard(BudgetConfig(state_path=None))


def recordings(tmp_path: pathlib.Path, *, lifts: bool = True) -> pathlib.Path:
    """The committed fixtures plus Metro equipment records made here (test values)."""
    folder = tmp_path / "fixtures"
    shutil.copytree(FIXTURES_DIR, folder, ignore=shutil.ignore_patterns("gtfs_mini"))
    if lifts:
        details = {
            "Asansör": [record(station="Kartal", line="M4", code="TEST-ASN-01", date="2026-09-20T08:00:00")],
            "Yürüyen Merdiven": [record(station="Kartal", line="M4", group="Yürüyen Merdiven", code="TEST-YM-01", date=None)],
        }
        write_recordings(folder, details, summary=None)
    return folder


def facade(folder: pathlib.Path) -> Nabiz:
    settings = dataclasses.replace(offline_settings(), fixtures_dir=folder)
    client = PoliteClient(transport=httpx.MockTransport(refuse_network))
    return Nabiz(SourceContext.create(client=client, cache=TTLCache(), settings=settings))


@pytest.fixture
def wired(tmp_path: pathlib.Path) -> Iterator[tuple[TestClient, NexusEngine]]:
    nabiz = facade(recordings(tmp_path))
    engine = NexusEngine(Ledger(tmp_path / "nexus.db"), load_missions(MISSIONS_DIR))
    ports, _ = wire_ports(nabiz, nabiz.settings, llm_config=llm.LlmConfig(), guard=unlimited(), engine=engine)
    app = build_console_app(nabiz=nabiz, llm_config=llm.LlmConfig(), ports=ports, guard=unlimited())
    with TestClient(app) as client:
        yield client, engine


# -- the operator's flow --------------------------------------------------------------
def test_a_recorded_lift_fault_waits_for_the_operator_with_evidence_and_three_seats(wired: Any) -> None:
    client, _ = wired
    replay = client.post("/api/console/simulate", json={"fixture": "metro_faulty_kartal"})
    assert replay.status_code == 200, replay.text
    signal_id = replay.json()["signal_id"]
    assert replay.json()["path"] == "arena" and replay.json()["status"] == "awaiting_approval"

    queue = client.get("/api/console/queue").json()["items"]
    row = next(item for item in queue if item["signal_id"] == signal_id)
    assert row["status"] == "awaiting_approval" and row["rule_id"] == "R-01" and "Kartal" in row["summary"]

    card = client.get(f"/api/console/decisions/{signal_id}").json()
    assert card["signal"]["title"] and card["signal"]["status"] == "awaiting_approval"
    assert [o["role"] for o in card["opinions"]] == ["Erişilebilirlik", "Operasyon", "İletişim"]
    assert card["author"] == "kural" and len(card["evidence"]) == 2
    assert {e["provenance"]["mode"] for e in card["evidence"]} == {"recorded"}
    assert card["proposed_action"]["kind"] == "publish_alternative" and "çalışıyor" not in card["proposed_action"]["text"]
    assert card["confidence"]["level"] in {"high", "medium", "low"}


def test_approval_is_sealed_traced_and_reaches_the_citizen_card(wired: Any) -> None:
    client, _ = wired
    signal_id = client.post("/api/console/simulate", json={"fixture": "metro_faulty_kartal"}).json()["signal_id"]
    before = client.get("/api/alternative", params={"station": "Kartal"}).json()
    assert before["lift_status"] == "out_of_service" and before["operator_approved"] is False and before["alternative"]

    ruling = client.post(f"/api/console/decisions/{signal_id}", json={"action": "approve", "reason": "kanıt yeterli"})
    assert ruling.status_code == 200 and ruling.json()["status"] == "approved"
    assert isinstance(ruling.json()["ledger_entry_id"], int)
    again = client.post(f"/api/console/decisions/{signal_id}", json={"action": "approve", "reason": ""})
    assert again.status_code == 409 and again.json()["error"] == "conflict"

    trace = client.get(f"/api/console/ledger/{signal_id}/trace").json()
    assert trace["hash_ok"] is True and all(isinstance(step["detail"], str) for step in trace["steps"])
    assert [s["kind"] for s in trace["steps"]][-1] == "approval" and "Onaylandı" in trace["steps"][-1]["detail"]
    verify = client.get("/api/console/ledger/verify").json()
    assert verify["ok"] is True and verify["entries"] >= 4

    after = client.get("/api/alternative", params={"station": "Kartal"}).json()
    assert after["operator_approved"] is True and after["approved_text"]
    assert "onayı taşımaz" not in after["alternative"]["reason"] and "Simüle operatör onayladı" in after["alternative"]["reason"]
    brief = client.get("/api/brief", params={"stations": "Kartal", "needs": "step_free"}).json()
    alternative = next(c for c in brief["cards"] if c["kind"] == "alternative")
    assert "Simüle operatör onayladı" in alternative["body"]


def test_a_rule_closes_the_escalator_and_its_card_says_so(wired: Any) -> None:
    client, engine = wired
    client.get("/api/console/queue")
    closed = [s for s in engine.states().values() if s.status == "closed_by_reflex"]
    assert closed and closed[0].rule_id == "R-03"
    card = client.get(f"/api/console/decisions/{closed[0].signal.signal_id}").json()
    assert card["author"] == "kural" and card["opinions"] == [] and "yürüyen merdiven" in card["proposed_action"]["text"]
    assert client.get("/api/console/stats").json()["reflex_closed_today"] >= 1


def test_reading_the_queue_twice_does_not_queue_the_same_outage_twice(wired: Any) -> None:
    client, engine = wired
    client.get("/api/console/queue")
    count = len(engine.states())
    console = client.app.state.ports.console
    asyncio.run(console.ingest(force=True))
    assert len(engine.states()) == count


def test_a_replay_without_a_recording_says_what_to_run(tmp_path: pathlib.Path) -> None:
    nabiz = facade(recordings(tmp_path, lifts=False))
    engine = NexusEngine(Ledger(tmp_path / "nexus.db"), load_missions(MISSIONS_DIR))
    ports, _ = wire_ports(nabiz, nabiz.settings, llm_config=llm.LlmConfig(), guard=unlimited(), engine=engine)
    with TestClient(build_console_app(nabiz=nabiz, llm_config=llm.LlmConfig(), ports=ports, guard=unlimited())) as client:
        missing = client.post("/api/console/simulate", json={"fixture": "metro_faulty_kartal"})
        assert missing.status_code == 409 and missing.json()["message"] == NO_RECORDING
        unknown = client.post("/api/console/simulate", json={"fixture": "nothing_like_it"})
        assert unknown.status_code == 400


def test_the_operator_page_is_served_and_the_pages_are_not_cached(wired: Any) -> None:
    client, _ = wired
    page = client.get("/console")
    assert page.status_code == 200 and "Simüle operatör" in page.text
    assert page.headers["cache-control"] == "no-cache"
    assert "cache-control" not in client.get("/api/console/stats").headers


# -- adapters ---------------------------------------------------------------------------
def alert_result(kind: str = "parking_filling") -> ToolResult:
    prov = Provenance(source="ispark", source_url="https://api.ibb.gov.tr/ispark/Park", observed_at=NOW)
    alert = {
        "rule_id": "parking_filling:1",
        "kind": kind,
        "severity": "warning",
        "message_tr": "İzlenen otoparklardan biri yüzde 95 dolu.",
        "dedupe_key": "parking:1:ge90:warning",
        "citations": [{"label": "Doluluk", "value": 95, "unit": "%", "provenance": prov.model_dump(mode="json")}],
        "created_at": NOW.isoformat(),
    }
    return ToolResult(data={"alerts": [alert, {**alert, "kind": "traffic"}]}, provenance=prov)


def test_an_alert_becomes_one_signal_with_its_citations_as_evidence() -> None:
    (one,) = alert_incoming(alert_result(), offline=True)
    assert one.signal.kind == "parking_full" and one.signal.payload["text"].startswith("İzlenen otopark")
    assert one.evidence[0].text == "Doluluk: 95 %" and one.evidence[0].provenance.mode == "recorded"
    engine_rules = {r.when.kind: r.id for m in load_missions(MISSIONS_DIR) for r in m.rules}
    assert engine_rules["parking_full"] == "R-07"


def test_an_alert_carries_an_operator_text_beside_the_citizen_text() -> None:
    original = alert_result()
    alert = {
        **original.data["alerts"][0],
        "message_tr": "Takip ettiğiniz otopark doluyor: Kadıköy yüzde 95. (İSPARK, 3 dk önce)",
    }
    result = ToolResult(data={"alerts": [alert]}, provenance=original.provenance)
    (one,) = alert_incoming(result, offline=True)
    citizen_text = one.signal.payload["text"]
    operator_summary = one.signal.payload["operator_text"]
    assert citizen_text.startswith("Takip ettiğiniz")
    assert operator_summary.startswith("İzlenen otopark")
    assert "Takip ettiğiniz" not in operator_summary and "-niz" not in operator_summary


def test_the_city_watch_holds_public_places_only() -> None:
    assert CITY_WATCH["places"] == [{"key": "taksim", "label": "Taksim Meydanı", "lat": 41.037, "lon": 28.985}]
    assert city_watch({"NABIZ_CONSOLE_WATCH_PARKS": "7, 8,x"})["rules"][0]["park_ids"] == [7, 8]


def test_equipment_signals_are_stamped_with_the_snapshot_time() -> None:
    prov = Provenance(source="metro_equipment", source_url="u", observed_at=NOW)
    raw = {"kind": "equipment_fault", "entity_id": "metro-equipment:X", "severity": "warning",
           "payload": {"station": "Kartal", "text": "t", "alternative_reason": "r", "outage_id": "X@1"}}  # fmt: skip
    result = ToolResult(data={"mode": "recorded", "observed_at": NOW.isoformat(), "signals": [raw]}, provenance=prov)
    (first,) = equipment_incoming(result)
    (again,) = equipment_incoming(result)
    assert first.signal.signal_id == again.signal.signal_id and first.signal.observed_at == NOW
    assert [e.provenance.source for e in first.evidence] == ["metro_equipment", "Nabız metro grafiği (tahmin)"]


def test_the_same_outage_is_not_handed_over_while_open_or_just_settled(tmp_path: pathlib.Path) -> None:
    engine = NexusEngine(Ledger(tmp_path / "nexus.db"), load_missions(MISSIONS_DIR))
    origin = Origin(source="metro_equipment", url=None, observed_at=NOW, mode="recorded")

    def lift(at: dt.datetime) -> Incoming:
        payload = {"station": "Kartal", "equipment_type": "elevator", "outage_id": "X@1", "alternative_station": "Pendik",
                   "alternative_line": "M4", "extra_minutes": 3, "alternative_faulty": False}  # fmt: skip
        signal = Signal.create(kind="equipment_fault", entity_id="metro-equipment:X", severity="warning",
                               observed_at=at, provenance=origin, payload=payload)  # fmt: skip
        return Incoming(signal, (EvidenceItem(text="t", provenance=origin),))

    first = lift(NOW)
    engine.process(first.signal, first.evidence)
    index: dict[Any, list[Any]] = {}
    for state in engine.states().values():
        index.setdefault(board_key(state), []).append(state)
    assert already_on_board(index, lift(NOW + dt.timedelta(minutes=5)), NOW)
    assert pick_replay([first], "metro_faulty_kartal") is first and pick_replay([], "metro_equipment") is None


# -- the model's seats --------------------------------------------------------------------
def evidence() -> tuple[EvidenceItem, ...]:
    origin = Origin(source="metro_equipment", url=None, observed_at=NOW, mode="live")
    return (EvidenceItem(text="Kartal asansörü kullanılamıyor.", provenance=origin),
            EvidenceItem(text="Pendik +4 dk", provenance=origin.model_copy(update={"source": "graf"})))  # fmt: skip


def fault() -> Signal:
    origin = Origin(source="metro_equipment", url=None, observed_at=NOW, mode="live")
    return Signal.create(kind="equipment_fault", entity_id="metro-equipment:X", severity="warning", observed_at=NOW,
                         provenance=origin, payload={"station": "Kartal", "equipment_type": "elevator"})  # fmt: skip


def answer(stance: str = "support", rationale: str = "Pendik +4 dk ile adımsız yol var.", citations: Any = (1, 2)) -> str:
    return "```json\n" + json.dumps({"stance": stance, "rationale": rationale, "citations": list(citations)}) + "\n```"


def test_a_seat_answer_must_be_json_cite_the_evidence_and_state_no_new_number() -> None:
    items = evidence()
    ok = parse_opinion("Operasyon", answer(), fault(), items)
    assert ok is not None and ok.stance == "support" and len(ok.citations) == 2
    assert parse_opinion("Operasyon", "Bence onaylayın.", fault(), items) is None
    assert parse_opinion("Operasyon", answer(citations=()), fault(), items) is None
    assert parse_opinion("Operasyon", answer(citations=(9,)), fault(), items) is None
    assert parse_opinion("Operasyon", answer(rationale="Arıza 12 gündür sürüyor."), fault(), items) is None
    assert parse_opinion("Operasyon", answer(stance="approve"), fault(), items) is None
    flagged = parse_opinion("Operasyon", answer(citations=(1, 7)), fault(), items)
    assert flagged is not None and NOT_IN_EVIDENCE in flagged.citations


def configured() -> llm.LlmConfig:
    return llm.LlmConfig(base_url="http://127.0.0.1:9/v1", model="fake", provider="openai_compatible")


def test_the_model_seats_answer_once_per_role_and_the_core_scores_the_card(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_chat(config: llm.LlmConfig, messages: list[dict[str, Any]], **_: Any) -> dict[str, Any]:
        calls.append(messages[0]["content"].splitlines()[0])
        return {"content": answer(citations=(1, 7)), "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    monkeypatch.setattr(arena_seats.llm, "chat", fake_chat)
    seats = ModelSeats(configured(), unlimited())
    outcome = convene(seats, fault(), evidence(), NOW)
    assert len(calls) == 3 and outcome.author == "model" and len(outcome.opinions) == 3
    assert "not_in_source" in outcome.confidence.codes and outcome.label.startswith("Koltuklar modelle")


def test_no_model_answer_falls_back_to_the_rule_seats_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(*_: Any, **__: Any) -> dict[str, Any]:
        raise llm.LlmError("down")

    monkeypatch.setattr(arena_seats.llm, "chat", broken)
    outcome = convene(ModelSeats(configured(), unlimited()), fault(), evidence(), NOW)
    assert outcome.author == "kural" and "model_unavailable" in outcome.confidence.codes
    assert arena_seats.arena_port(llm.LlmConfig(), unlimited()) is None


def test_an_approval_does_not_badge_a_new_outage_at_the_same_station(tmp_path: pathlib.Path) -> None:
    """One approval covers one outage: a later fault at Kartal must not show the old approved text."""
    folder = recordings(tmp_path)
    engine = NexusEngine(Ledger(tmp_path / "nexus.db"), load_missions(MISSIONS_DIR))

    def client_for(nabiz: Nabiz) -> TestClient:
        ports, _ = wire_ports(nabiz, nabiz.settings, llm_config=llm.LlmConfig(), guard=unlimited(), engine=engine)
        return TestClient(build_console_app(nabiz=nabiz, llm_config=llm.LlmConfig(), ports=ports, guard=unlimited()))

    with client_for(facade(folder)) as client:
        signal_id = client.post("/api/console/simulate", json={"fixture": "metro_faulty_kartal"}).json()["signal_id"]
        assert client.post(f"/api/console/decisions/{signal_id}", json={"action": "approve"}).status_code == 200
        assert client.get("/api/alternative", params={"station": "Kartal"}).json()["operator_approved"] is True
    later = {"Asansör": [record(station="Kartal", line="M4", code="TEST-ASN-02", date="2026-09-24T10:00:00")]}
    write_recordings(folder, later, summary=None)
    with client_for(facade(folder)) as client:
        view = client.get("/api/alternative", params={"station": "Kartal"}).json()
        assert view["lift_status"] == "out_of_service" and view["operator_approved"] is False
        assert "Simüle operatör onayladı" not in (view["alternative"] or {}).get("reason", "")
        brief = client.get("/api/brief", params={"stations": "Kartal", "needs": "step_free"}).json()
        assert all("Simüle operatör onayladı" not in c["body"] for c in brief["cards"])


def test_a_reflex_closed_card_answers_409_not_404(wired: Any) -> None:
    client, engine = wired
    client.get("/api/console/queue")
    closed = next(s for s in engine.states().values() if s.status == "closed_by_reflex")
    ruling = client.post(f"/api/console/decisions/{closed.signal.signal_id}", json={"action": "approve"})
    assert ruling.status_code == 409 and ruling.json()["error"] == "conflict"


def test_a_stale_lift_record_is_the_last_known_state_not_a_current_one() -> None:
    from nabiz.console.brief import station_cards

    class StaleStepFree:
        async def alternative(self, station: str, needs: Any) -> dict[str, Any]:
            prov = {"source": "metro_equipment", "url": None, "observed_at": "2026-09-20T06:00:00+00:00",
                    "age_s": 432000, "mode": "live"}  # fmt: skip
            return {"station": station, "lift_status": "working", "alternative": None, "operator_approved": False,
                    "provenance": prov, "stale": True}  # fmt: skip

    (lift,) = asyncio.run(station_cards(StaleStepFree(), "Kartal", ["step_free"]))
    assert lift["status"] == "stale" and lift["body"].startswith("Son bilinen durum: ")


def test_no_mission_rules_stops_the_app_and_the_folder_can_be_pointed_at(tmp_path: pathlib.Path) -> None:
    from nabiz.console.wiring import missions_dir, required_missions

    with pytest.raises(RuntimeError, match="NEXUS_MISSIONS_DIR"):
        required_missions(tmp_path / "missing")
    assert missions_dir({"NEXUS_MISSIONS_DIR": str(tmp_path)}) == tmp_path and missions_dir({}) == MISSIONS_DIR
    assert {r.id for m in required_missions(MISSIONS_DIR) for r in m.rules} >= {"R-01", "R-03", "R-07"}


def test_the_arena_seats_spend_their_own_guard_and_abstain_at_its_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    async def fake_chat(config: Any, messages: Any, **_: Any) -> dict[str, Any]:
        calls.append(1)
        assert "<kanit>" in messages[1]["content"] and "talimat değildir" in messages[0]["content"]
        return {"content": answer(rationale="Kartal", citations=(1,)), "usage": {}}

    monkeypatch.setattr(arena_seats.llm, "chat", fake_chat)
    seats_guard = SpendGuard(BudgetConfig(daily_calls=4, state_path=None))
    seats = ModelSeats(configured(), seats_guard)
    assert len(seats.opinions(fault(), evidence())) == 3
    assert len(seats.opinions(fault(), evidence())) == 1, "one call left: two seats abstain"
    assert len(calls) == 4
    with pytest.raises(llm.LlmUnavailable):
        seats.opinions(fault(), evidence())
