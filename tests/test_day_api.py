"""The console day view is a read-only summary of the real decision ledger."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from conftest import offline_settings
from fastapi.testclient import TestClient
from nexus_helpers import OPERATOR, T0, Clock, approve, build_engine, elevator, make_signal, origin

from nabiz.agent import llm
from nabiz.console.access import OperatorAccess
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.day_api import (
    HANDOFF_MAX,
    day_payload,
    day_routes,
    expiring_rules,
    handoff_text,
    istanbul_day,
    open_cards,
    summarize_day,
)
from nabiz.console.nexus_port import NexusConsole
from nabiz.console.ports import Ports
from nexus_core.engine import default_evidence
from nexus_core.ledger import EntryKind, Ledger
from nexus_core.router import REASON_TEXT
from nexus_core.signals import Signal

STATIC = Path(__file__).parents[1] / "src" / "nabiz" / "console" / "static"


def long_outage(clock: Clock, key: str) -> Signal:
    return make_signal(
        "long_outage",
        entity="metro-equipment:ASN-9",
        observed_at=clock.now,
        station="Kartal",
        outage_id=key,
        outage_hours=120.0,
        text="Kartal (M4): asansör kullanılamıyor.",
    )


def parking(clock: Clock) -> Signal:
    key = f"parking:{clock.now.isoformat()}"
    return make_signal(
        "parking_full",
        entity=f"alert:{key}",
        observed_at=clock.now,
        provenance=origin(clock.now, source="ispark"),
        text="İzlenen otopark yüzde 92 dolu.",
        dedupe_key=key,
    )


def process(engine: Any, signal: Signal) -> str:
    return engine.process(signal, default_evidence(signal)).signal_id


def seeded(tmp_path: Path):
    clock = Clock()
    engine = build_engine(tmp_path, clock)

    clock.now = T0 - dt.timedelta(days=1)
    signal_id = process(engine, long_outage(clock, "ASN-9@yesterday"))
    clock.advance(minutes=2)
    engine.decide(approve(signal_id))
    clock.advance(minutes=1)
    signal_id = process(engine, parking(clock))
    clock.advance(minutes=1)
    engine.decide(approve(signal_id, "reject", "Eşik ölçümü eski"))

    clock.now = T0
    signal_id = process(engine, long_outage(clock, "ASN-9@today"))
    clock.advance(minutes=5)
    engine.decide(approve(signal_id, "defer", "Yarın doğrulanacak"))
    elevator_id = process(engine, elevator(observed_at=clock.now))
    clock.advance(minutes=1, seconds=30)
    engine.decide(approve(elevator_id))
    clock.advance(minutes=5)
    process(engine, elevator(observed_at=clock.now))
    clock.advance(seconds=30)
    process(engine, parking(clock))
    return engine, clock


def client(engine=None, *, access: OperatorAccess | None = None, clock: Clock | None = None) -> TestClient:
    ports = Ports()
    if engine is not None:
        ports.console = NexusConsole(engine, nabiz=None, recorded=lambda: None, offline=True, clock=clock or Clock())  # type: ignore[arg-type]
    app = build_console_app(
        settings=offline_settings(),
        llm_config=llm.LlmConfig(),
        ports=ports,
        guard=SpendGuard(BudgetConfig(state_path=None)),
        access=access or OperatorAccess(),
    )
    app.include_router(day_routes)
    mount = next(route for route in app.router.routes if getattr(route, "name", None) == "static")
    app.router.routes.remove(mount)
    app.router.routes.append(mount)
    return TestClient(app, base_url="http://127.0.0.1:8090")


def test_today_lists_every_human_ruling_newest_first(tmp_path: Path) -> None:
    engine, clock = seeded(tmp_path)
    response = client(engine, clock=clock).get("/api/console/day?date=2026-09-25")
    assert response.status_code == 200
    rows = response.json()["decisions"]
    assert len(rows) == 2
    assert (rows[0]["action"], rows[0]["decision_s"]) == ("approve", 90.0)
    assert (rows[1]["action"], rows[1]["reason"], rows[1]["decision_s"]) == ("defer", "Yarın doğrulanacak", 300.0)
    assert rows[1]["title"].startswith("Uzun süren arıza")


def test_rows_carry_no_person(tmp_path: Path) -> None:
    engine, clock = seeded(tmp_path)
    body = client(engine, clock=clock).get("/api/console/day?date=2026-09-25").json()
    rendered = json.dumps(body, ensure_ascii=False)
    assert "op-1" not in rendered and "simule-operator" not in rendered
    assert all("actor" not in row for row in body["decisions"])
    assert body["role"] == "Simüle operatör"


def test_yesterday_summary_counts_every_kind(tmp_path: Path) -> None:
    clock = Clock(T0)
    ledger = Ledger(tmp_path / "summary.db", clock=clock)
    ledger.append(EntryKind.REFLEX_CLOSED, actor="system", detail={})
    for status in ("approved", "approved", "rejected", "deferred"):
        ledger.append(EntryKind.APPROVAL, actor="system", detail={"status": status})
    ledger.append("expired", actor="system", detail={})
    summary = summarize_day(ledger.entries(), istanbul_day(T0))
    assert [summary[key] for key in ("reflex_closed", "approved", "rejected", "deferred", "expired", "total")] == [
        1,
        2,
        1,
        1,
        1,
        6,
    ]
    assert summary["sentence"] == "Dün: 2 onay, 1 red, 1 erteleme, 1 süresi dolan kart; refleksle kapanan 1."


def test_an_empty_day_says_no_record() -> None:
    assert summarize_day([], dt.date(2026, 9, 25))["sentence"] == "Dün kayıt yok."


def test_the_day_turns_at_istanbul_midnight(tmp_path: Path) -> None:
    at = dt.datetime(2026, 9, 24, 21, 30, tzinfo=dt.UTC)
    clock = Clock(at)
    ledger = Ledger(tmp_path / "midnight.db", clock=clock)
    ledger.append("expired", actor="system", detail={})
    assert summarize_day(ledger.entries(), dt.date(2026, 9, 25))["expired"] == 1


def test_open_cards_keep_their_reasons(tmp_path: Path) -> None:
    engine, _ = seeded(tmp_path)
    rows = open_cards(engine.states())
    assert len(rows) == 2
    assert rows[0]["status_label"] == "ertelendi" and rows[0]["reason"] == "Yarın doğrulanacak"
    assert rows[1]["status_label"] == "onay bekliyor"
    expected = "; ".join(REASON_TEXT.get(code, code) for code in engine.states()[rows[1]["signal_id"]].reasons)
    assert rows[1]["reason"] == expected


def test_rules_expiring_within_three_days(tmp_path: Path) -> None:
    from test_nexus_core_rule_drafts import spread

    clock = Clock()
    engine = build_engine(tmp_path, clock)
    spread(engine, clock, 3)
    draft = engine.drafts.drafts()[0]
    adopted = engine.drafts.adopt(draft.draft_id, "Üç onay", OPERATOR)
    now = adopted.expires_at - dt.timedelta(days=2)
    rules = expiring_rules(engine.drafts.adopted(), now)
    assert len(rules) == 1 and rules[0]["days_left"] == 2
    assert expiring_rules(engine.drafts.adopted(), adopted.expires_at - dt.timedelta(days=4)) == []
    engine.drafts.revoke(adopted.rule_id, "Kontrol için geri alındı", OPERATOR)
    assert expiring_rules(engine.drafts.adopted(), now) == []


def test_handoff_is_deterministic_short_and_nameless(tmp_path: Path) -> None:
    engine, clock = seeded(tmp_path)
    day = dt.date(2026, 9, 25)
    first = day_payload(engine, day, clock.now)["handoff"]
    second = day_payload(engine, day, clock.now)["handoff"]
    assert first == second and len(first) <= HANDOFF_MAX
    assert "simüle operatör" in first and "Resmî İBB hizmeti değildir" in first
    assert "op-1" not in first and "simule-operator" not in first
    assert "—" not in first and "–" not in first and re.search(r"\bETA\b", first) is None


def test_handoff_fits_with_many_open_cards() -> None:
    now = T0
    today = {"sentence": "Bugün: 0 onay, 0 red, 0 erteleme, 0 süresi dolan kart; refleksle kapanan 0."}
    open_items = [
        {"title": f"Uzun süren arıza, kayıt {number}", "status_label": "ertelendi", "reason": "x" * 280} for number in range(60)
    ]
    handoff = handoff_text(
        now=now,
        today=today,
        open_items=open_items,
        expiring=[],
        verify={"ok": True, "entries": 0, "head": "0" * 64},
    )
    assert len(handoff) <= HANDOFF_MAX and "kart daha" in handoff


def test_without_an_engine_the_day_answers_503_not_wired() -> None:
    response = client().get("/api/console/day")
    assert response.status_code == 503 and response.json()["error"] == "not_wired"


def test_bound_to_a_network_without_a_token_the_day_stays_shut() -> None:
    response = client(access=OperatorAccess(bound_host="0.0.0.0")).get("/api/console/day")
    assert response.status_code == 503 and response.json()["error"] == "console_locked"


def test_a_bad_date_is_refused(tmp_path: Path) -> None:
    engine, clock = seeded(tmp_path)
    with client(engine, clock=clock) as web:
        invalid_calendar_date = web.get("/api/console/day?date=2026-13-40")
        invalid_shape = web.get("/api/console/day?date=abc")
    assert invalid_calendar_date.status_code == 400 and invalid_calendar_date.json()["error"] == "bad_request"
    assert invalid_shape.status_code == 422


def test_no_dash_in_the_day_answer(tmp_path: Path) -> None:
    engine, clock = seeded(tmp_path)
    body = json.dumps(client(engine, clock=clock).get("/api/console/day?date=2026-09-25").json(), ensure_ascii=False)
    assert "—" not in body and "–" not in body


def test_the_panel_files_follow_the_page_rules() -> None:
    script = (STATIC / "js" / "console_day.js").read_text(encoding="utf-8")
    style = (STATIC / "css" / "console_day.css").read_text(encoding="utf-8")
    for required in (
        "aria-labelledby",
        'scope="col"',
        'scope="row"',
        "navigator.clipboard",
        'role="status"',
        "/api/console/day",
        "/trace",
    ):
        assert required in script
    assert "max-width: 40rem" in style and "overflow-wrap: anywhere" in style
    assert "outline: var(--focus-ring);" not in style and "outline: none" not in style
