"""The live organ map reads only the ledger and keeps every count attributable to a stage."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import shutil
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nexus_helpers import OPERATOR, T0, Clock, approve, build_engine, elevator

from nabiz.agent import llm
from nabiz.console.operator import operator_routes
from nabiz.console.organs_api import ORGANS, learning_loop, organ_status, organs_payload, organs_routes, public_summary
from nabiz.console.ports import Ports
from nabiz.console.wiring import wire_ports

STATIC = pathlib.Path(__file__).parents[1] / "src" / "nabiz" / "console" / "static"


def _rows(payload: dict) -> dict[str, dict]:
    return {organ["key"]: organ for organ in payload["organs"]}


def _stage(loop: dict, key: str) -> dict:
    return next(stage for stage in loop["stages"] if stage["key"] == key)


def test_an_empty_ledger_shows_every_organ_idle_today(tmp_path: pathlib.Path) -> None:
    engine = build_engine(tmp_path, Clock())
    payload = organs_payload(engine, now=T0)
    rows = _rows(payload)

    assert len(organ_status(engine, now=T0)) == 7
    assert payload["empty"] is True
    assert len(rows) == 7
    assert all(row["state"] == "idle" and row["state_label"] == "bugün boş" for key, row in rows.items() if key != "ledger")
    assert rows["ledger"]["state"] == "ok" and rows["ledger"]["state_label"] == "zincir sağlam"
    assert rows["ledger"]["entries"] == rows["ledger"]["total_count"] == 0
    assert payload["loop"]["empty"] is True
    assert all(stage["count"] is None for stage in payload["loop"]["stages"])


def test_every_ledger_kind_but_the_signal_lands_on_exactly_one_organ() -> None:
    kinds = ["routed", "reflex_closed", "reflex_failed", "arena_drafted", "approval", "expired", "rule_adopted", "rule_revoked"]
    expected = {
        "routed": "router", "reflex_closed": "reflex", "reflex_failed": "reflex", "arena_drafted": "arena",
        "approval": "approval", "expired": "lifecycle", "rule_adopted": "rules", "rule_revoked": "rules",
    }
    for kind in kinds:
        destinations = [organ["key"] for organ in ORGANS if kind in organ["kinds"]]
        assert destinations == [expected[kind]]
    assert all(sum(kind in organ["kinds"] for organ in ORGANS) == 1 for kind in kinds)


def test_a_chat_pause_decision_shows_on_the_approval_organ(tmp_path: pathlib.Path) -> None:
    engine = build_engine(tmp_path, Clock())
    for kind in ("chat_pause", "chat_paused", "chat_resumed"):
        engine.ledger.append(kind, actor="test", detail={"action": kind})

    payload = organs_payload(engine, now=T0)
    assert _rows(payload)["approval"]["today_count"] == 3
    assert _stage(payload["loop"], "approved")["count"] == 0


def test_an_unexpected_approval_action_type_is_ignored(tmp_path: pathlib.Path) -> None:
    engine = build_engine(tmp_path, Clock())
    engine.ledger.append("approval", actor="test", detail={"action": ["approve"]})

    assert _stage(learning_loop(engine), "approved")["count"] == 0


def _queue_app(tmp_path: pathlib.Path, clock: Clock) -> tuple[FastAPI, object]:
    from test_console_wiring import facade, recordings, unlimited

    nabiz = facade(recordings(tmp_path))
    engine = build_engine(tmp_path, clock)
    ports, _ = wire_ports(
        nabiz, nabiz.settings, llm_config=llm.LlmConfig(), guard=unlimited(), engine=engine,
    )
    app = FastAPI()
    app.state.ports = ports
    app.include_router(operator_routes)
    app.include_router(organs_routes)
    return app, engine


def test_the_page_order_lights_the_router_and_the_arena(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    monkeypatch.setattr("nabiz.console.organs_api.system_clock", clock)
    app, _ = _queue_app(tmp_path, clock)
    with TestClient(app) as client:
        assert client.get("/api/console/queue").status_code == 200
        rows = _rows(client.get("/api/console/organs").json())
    assert rows["router"]["state"] == "active"
    assert rows["arena"]["state"] == "active"


def test_the_same_queue_read_lights_the_reflex_with_the_test_escalator(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recorded TEST-ASN and TEST-YM fixtures light R-03; the deployed Metro file has no such record."""
    clock = Clock()
    monkeypatch.setattr("nabiz.console.organs_api.system_clock", clock)
    app, _ = _queue_app(tmp_path, clock)
    with TestClient(app) as client:
        client.get("/api/console/queue")
        rows = _rows(client.get("/api/console/organs").json())
    assert rows["reflex"]["state"] == "active"
    assert rows["reflex"]["today_count"] >= 1


def test_a_second_queue_read_adds_no_new_signal(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    monkeypatch.setattr("nabiz.console.organs_api.system_clock", clock)
    app, engine = _queue_app(tmp_path, clock)
    with TestClient(app) as client:
        client.get("/api/console/queue")
        first = _rows(client.get("/api/console/organs").json())["router"]["total_count"]
        client.get("/api/console/queue")
        second = _rows(client.get("/api/console/organs").json())["router"]["total_count"]
    assert second == first
    assert engine.ledger.verify().ok


def test_today_is_counted_in_istanbul_time(tmp_path: pathlib.Path) -> None:
    utc = dt.datetime(2026, 9, 25, 21, 30, tzinfo=dt.UTC)
    clock = Clock(utc)
    engine = build_engine(tmp_path, clock)
    engine.ledger.append("routed", actor="test", detail={})

    row = _rows(organs_payload(engine, now=dt.datetime(2026, 9, 25, 21, 30, tzinfo=dt.UTC)))["router"]
    assert row["today_count"] == 1
    assert row["last_activity"] == utc.isoformat()


def test_yesterdays_activity_is_idle_today_but_keeps_its_total(tmp_path: pathlib.Path) -> None:
    yesterday = dt.datetime(2026, 9, 24, 11, 32, tzinfo=dt.UTC)
    engine = build_engine(tmp_path, Clock(yesterday))
    engine.ledger.append("routed", actor="test", detail={})

    row = _rows(organs_payload(engine, now=T0))["router"]
    assert row["state"] == "idle" and row["today_count"] == 0
    assert row["total_count"] == 1 and row["last_activity"] == yesterday.isoformat()


def test_the_learning_loop_counts_a_learned_rule_closing_a_signal(tmp_path: pathlib.Path) -> None:
    from test_nexus_core_rule_drafts import outage, spread

    clock = Clock()
    engine = build_engine(tmp_path, clock)
    spread(engine, clock, 3)
    (draft,) = engine.drafts.drafts()
    engine.drafts.adopt(draft.draft_id, "Üç ayrı onay", OPERATOR)
    result = engine.process(outage(77, clock.now))

    loop = learning_loop(engine)
    assert _stage(loop, "approved")["count"] == 3
    assert _stage(loop, "drafts")["count"] == 0
    assert _stage(loop, "adopted")["count"] == 1
    assert _stage(loop, "learned_closed")["count"] == 1
    assert result.rule_id == "R-101"


def test_an_approved_alternative_closing_the_next_snapshot_is_counted(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    first = engine.process(elevator(observed_at=clock.now)).signal_id
    engine.decide(approve(first, reason="Kanıt yeterli"))
    clock.advance(minutes=5)
    result = engine.process(elevator(observed_at=clock.now))

    assert result.rule_id and result.rule_id.startswith("OA-")
    assert _stage(learning_loop(engine), "bound_closed")["count"] == 1


def test_reading_the_organs_writes_nothing_to_the_ledger(tmp_path: pathlib.Path) -> None:
    engine = build_engine(tmp_path, Clock())
    engine.ledger.append("routed", actor="test", detail={})
    before = engine.ledger.entries()
    organs_payload(engine, now=T0)
    after = engine.ledger.entries()
    assert after == before


def test_an_unwired_console_answers_503(tmp_path: pathlib.Path) -> None:
    app = FastAPI()
    app.state.ports = Ports()
    app.include_router(organs_routes)
    with TestClient(app) as client:
        response = client.get("/api/console/organs")
    assert response.status_code == 503
    assert response.json()["error"] == "not_wired"
    assert "bağlı değil" in response.json()["message"]


def test_the_public_summary_carries_no_person_reason_or_place(tmp_path: pathlib.Path) -> None:
    engine = build_engine(tmp_path, Clock())
    engine.ledger.append(
        "approval", actor=OPERATOR.label,
        detail={"actor": "op-1", "reason": "Taksim Kartal gizli gerekçe", "action": "approve"},
        signal_id="sig-private", entity_id="Kartal",
    )

    summary = json.dumps(public_summary(engine, now=T0), ensure_ascii=False)
    assert public_summary(None) is None
    for private in ("actor", "reason", "Simüle operatör", "op-1", "sig-", "Kartal", "Taksim"):
        assert private not in summary


def test_the_organ_styles_stack_on_a_narrow_screen_and_move_only_when_allowed() -> None:
    css = (STATIC / "css" / "console_organs.css").read_text(encoding="utf-8")
    assert "@media (max-width: 480px)" in css
    guarded = re.findall(r"@media \(prefers-reduced-motion: no-preference\) \{[^\n]*\}", css)
    unguarded = css
    for block in guarded:
        unguarded = unguarded.replace(block, "", 1)
    assert not re.search(r"\b(?:animation|transition)\s*:", unguarded)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", css)


def test_the_organ_cards_say_their_state_in_words(tmp_path: pathlib.Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = """
globalThis.window = { location: { search: '', origin: 'http://localhost' } };
const organs = await import('./js/console_organs.js');
const active = organs.organCard({key:'router',name:'Yönlendirici',what:'Görev.',state:'active',today_count:1,
  total_count:4,last_activity:'2026-09-25T11:32:00+00:00'});
const idle = organs.organCard({key:'router',name:'Yönlendirici',what:'Görev.',state:'idle',today_count:0,
  total_count:2,last_activity:'2026-09-24T11:32:00+00:00'});
const unknown = organs.loopStrip({stages:[{key:'signals',label:'Sinyal',count:null}]});
const router = {key:'router',name:'Yönlendirici',what:'Görev.',state:'active',today_count:1,total_count:3};
const empty = organs.organsSection({metro_signals:0,organs:[router],loop:{stages:[]}});
console.log(JSON.stringify({active,idle,unknown,empty}));
"""
    result = subprocess.run(
        [node, "--experimental-default-type=module", "--input-type=module", "-e", script],
        cwd=STATIC, capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    assert "bugün çalıştı" in rendered["active"] and "is-ok" in rendered["active"]
    assert "bugün boş" in rendered["idle"] and "is-ok" not in rendered["idle"]
    assert "toplam 4" in rendered["active"] and "son: 14:32" in rendered["active"]
    assert "toplam 2" in rendered["idle"] and "son: 24.09.2026 14:32" in rendered["idle"]
    assert "son: 14:32" not in rendered["idle"]
    assert "veri yok" in rendered["unknown"]
    assert "Metro arıza kaydı yok" in rendered["empty"]
    assert "kayıtlı veriden okundu" in rendered["empty"]
    assert "<button" not in rendered["empty"] and "data-nx-sim" not in rendered["empty"]
    assert "capture_metro_equipment" not in rendered["empty"]
