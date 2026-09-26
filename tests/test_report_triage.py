"""E29: interchange severity and read-only operator triage for citizen reports."""

from __future__ import annotations

import asyncio
import base64
import json
import pathlib
import shutil
import subprocess
from typing import Any

import pytest
from conftest import REPO_ROOT, offline_settings
from fastapi.testclient import TestClient
from nexus_helpers import Clock, approve, build_engine

from nabiz.agent import llm
from nabiz.console import agency_router
from nabiz.console.access import OperatorAccess, TurnLimiter
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.nexus_port import NexusConsole
from nabiz.console.ports import Ports
from nabiz.console.published import PublishedCards
from nabiz.console.report_api import REPORT_KIND, report_routes, report_signal
from nabiz.console.report_triage import (
    TRIAGE_NOTE,
    record_conflict,
    report_agency,
    report_priority,
    triage_items,
    triage_routes,
)


def put_static_last(app: Any) -> None:
    mount = next(route for route in app.router.routes if getattr(route, "name", None) == "static")
    app.router.routes.remove(mount)
    app.router.routes.append(mount)


def report_app(engine: Any, clock: Clock, *, access: OperatorAccess | None = None):
    console = NexusConsole(
        engine, nabiz=None, recorded=lambda: None, offline=True, ingest_every_s=0, clock=clock
    )  # type: ignore[arg-type]
    published = PublishedCards(engine, offline=True, stale_after_s=engine.stale_after_s, clock=clock)
    app = build_console_app(
        settings=offline_settings(),
        llm_config=llm.LlmConfig(),
        ports=Ports(console=console, published=published),
        guard=SpendGuard(BudgetConfig(state_path=None)),
        access=access or OperatorAccess(),
    )
    app.include_router(report_routes)
    app.include_router(triage_routes)
    put_static_last(app)
    app.state.report_clock = clock
    app.state.report_limiter = TurnLimiter(60)
    return app, published


@pytest.fixture
def triage_client(tmp_path: pathlib.Path):
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    app, published = report_app(engine, clock)
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        yield client, engine, clock, published


def post_report(client: TestClient, station: str = "Kartal", kind: str = "not_working"):
    return client.post("/api/report", json={"station": station, "kind": kind, "bucket": "now"})


def latest_report(engine: Any):
    return max(
        (state for state in engine.states().values() if state.signal.kind == REPORT_KIND),
        key=lambda state: state.received_at,
    )


def triage_for(client: TestClient, signal_id: str) -> dict[str, Any]:
    response = client.get("/api/console/report-triage")
    assert response.status_code == 200
    return response.json()["items"][signal_id]


def test_a_hub_report_is_critical_and_still_waits_for_a_person(triage_client) -> None:
    client, engine, _, published = triage_client
    station_info = asyncio.run(client.app.state.nabiz.metro_station_info("Yenikapı"))
    lines = {item["line_name"] for item in station_info.data["stations"] if item.get("line_name")}
    assert lines == {"M1A", "M1B", "M2"}

    response = post_report(client, "Yenikapı")
    assert response.status_code == 200
    state = latest_report(engine)
    assert state.signal.severity == "critical"
    assert state.reasons == ("critical",)
    assert state.rule_id == "R-10" and state.path == "arena"
    assert state.status == "awaiting_approval"
    assert asyncio.run(published.published(stations=["Yenikapı"])) == []
    priority = triage_for(client, state.signal.signal_id)["priority"]
    assert priority["label"] == "Yüksek"
    assert priority["reasons"] == [
        "aktarma istasyonu (M1A, M1B, M2)",
        "1 kişi bildirdi",
        "İBB kaydıyla çelişiyor: İBB kaydında arıza yok",
    ]
    assert engine.verify().ok


def test_a_single_line_report_keeps_the_e24_contract(triage_client) -> None:
    client, engine, clock, _ = triage_client
    signal, evidence = report_signal("Kartal", ["M4"], "data_wrong", "now", clock(), (None, None, None))
    engine.process(signal, evidence)
    state = latest_report(engine)
    assert state.signal.severity == "warning"
    assert state.reasons == ("rule_path",)
    priority = triage_for(client, state.signal.signal_id)["priority"]
    assert priority["level"] == "normal"
    assert priority["reasons"] == ["1 kişi bildirdi"]


def test_the_third_card_in_the_window_is_a_repeat(triage_client) -> None:
    client, engine, clock, _ = triage_client
    states = []
    for index in range(3):
        assert post_report(client).status_code == 200
        state = latest_report(engine)
        states.append(state)
        if index < 2:
            engine.decide(approve(state.signal.signal_id, action="reject", reason="Saha teyidi yok"))
            clock.advance(minutes=5)

    state = states[-1]
    assert "repeat" in state.reasons
    assert state.repeats == 3
    assert state.rule_id == "R-10" and state.path == "arena"
    priority = triage_for(client, state.signal.signal_id)["priority"]
    assert priority["label"] == "Yüksek"
    assert "son 14 günde bu istasyonda 3. kart" in priority["reasons"]


def test_folded_reports_raise_a_single_line_card_to_medium(triage_client) -> None:
    client, engine, clock, _ = triage_client
    for _ in range(3):
        assert post_report(client).status_code == 200
        clock.advance(minutes=5)
    reports = [state for state in engine.states().values() if state.signal.kind == REPORT_KIND]
    assert len(reports) == 1
    priority = triage_for(client, reports[0].signal.signal_id)["priority"]
    assert priority["level"] == "medium"
    assert "3 kişi bildirdi" in priority["reasons"]


def test_a_record_conflict_is_named_without_saying_working(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    signal, _ = report_signal(
        "Kartal", ["M4"], "not_working", "now", clock(),
        ("working", "Kartal için İBB kaydında arıza yok", None),
    )
    engine.process(signal)
    state = engine.states()[signal.signal_id]
    priority = report_priority(state, 1, engine.router.escalation.settings.window_hours)
    assert priority["level"] == "medium"
    assert "İBB kaydıyla çelişiyor: İBB kaydında arıza yok" in priority["reasons"]
    assert record_conflict({"report_kind": "data_wrong", "lift_status": "out_of_service"}) == "İBB kaydında arıza var"
    assert record_conflict({"report_kind": "data_wrong", "lift_status": "unknown"}) is None
    serialized = json.dumps(priority, ensure_ascii=False)
    assert "çalışıyor" not in serialized and "working" not in serialized


def test_citizen_requests_are_not_reports(triage_client) -> None:
    client, engine, _, _ = triage_client
    engine.ledger.append(
        "citizen_request",
        actor="vatandaş (anonim)",
        detail={"kind": "citizen_request", "code": "K7M2QX9P", "lang": "tr", "category": "Asansör ve erişim"},
        signal_id="sig-req-1",
        entity_id="citizen-request:K7M2QX9P",
    )
    assert post_report(client).status_code == 200
    item = latest_report(engine)
    items = triage_items(engine)
    assert list(items) == [item.signal.signal_id]
    assert "1 kişi bildirdi" in items[item.signal.signal_id]["priority"]["reasons"]
    source = (REPO_ROOT / "src/nabiz/console/report_triage.py").read_text(encoding="utf-8")
    assert all(word not in source for word in ("citizen_request", "citizen_requests", "requests_api", "talep"))
    assert engine.verify().ok


def test_the_agency_comes_from_the_router_and_nothing_is_assigned(triage_client) -> None:
    client, engine, _, _ = triage_client
    before = len(engine.ledger.entries())
    suggestion = report_agency()
    route = agency_router.route("metro istasyonu asansör")
    assert suggestion["id"] == "metro"
    assert suggestion["name"] == "Metro İstanbul"
    assert suggestion["rule"] == "metro"
    assert (suggestion["id"], suggestion["name"], suggestion["url"], suggestion["rule"]) == (
        route.agency, route.name, route.url, route.matched
    )
    assert client.get("/api/console/report-triage").json()["note"] == TRIAGE_NOTE
    assert len(engine.ledger.entries()) == before
    source = (REPO_ROOT / "src/nabiz/console/report_triage.py").read_text(encoding="utf-8")
    forbidden = ("ledger.append", ".decide(", "@triage_routes.post", "httpx", "smtplib", "requests.")
    assert all(term not in source for term in forbidden)


def test_triage_is_behind_the_operator_door_and_needs_the_core() -> None:
    locked_app = build_console_app(
        settings=offline_settings(),
        llm_config=llm.LlmConfig(),
        ports=Ports(),
        guard=SpendGuard(BudgetConfig(state_path=None)),
        access=OperatorAccess(bound_host="0.0.0.0"),
    )
    locked_app.include_router(triage_routes)
    put_static_last(locked_app)
    with TestClient(locked_app, base_url="http://127.0.0.1:8090") as client:
        locked = client.get("/api/console/report-triage")
        assert locked.status_code == 503 and locked.json()["error"] == "console_locked"

    unwired_app = build_console_app(
        settings=offline_settings(),
        llm_config=llm.LlmConfig(),
        ports=Ports(),
        guard=SpendGuard(BudgetConfig(state_path=None)),
        access=OperatorAccess(),
    )
    unwired_app.include_router(triage_routes)
    put_static_last(unwired_app)
    with TestClient(unwired_app, base_url="http://127.0.0.1:8090") as client:
        response = client.get("/api/console/report-triage")
        assert response.status_code == 503 and response.json()["error"] == "not_wired"


def test_the_citizen_never_sees_priority(triage_client) -> None:
    client, engine, _, published = triage_client
    response = post_report(client)
    status = client.get("/api/report/status", params={"station": "Kartal", "kind": "not_working"})
    state = latest_report(engine)
    engine.decide(approve(state.signal.signal_id, reason="Saha teyit etti"))
    public_cards = asyncio.run(published.published(stations=["Kartal"]))
    serialized = json.dumps([response.json(), status.json(), public_cards], ensure_ascii=False)
    for forbidden in ("priority", "Öncelik", "Yüksek", "Orta", "Olağan", "agency", "Metro İstanbul"):
        assert forbidden not in serialized


def test_triage_markup_in_node_and_page_rules() -> None:
    script = REPO_ROOT / "src/nabiz/console/static/js/console_report_triage.js"
    styles = REPO_ROOT / "src/nabiz/console/static/css/console_report_triage.css"
    javascript = script.read_text(encoding="utf-8")
    css = styles.read_text(encoding="utf-8")
    node = shutil.which("node")
    assert node is not None
    subprocess.run([node, "--check", str(script)], check=True, capture_output=True, text=True)

    module = javascript
    module = module.replace("import { MOCK, get } from './api.js';", "const { MOCK, get } = globalThis.triageApi;")
    module = module.replace("import { esc } from './format.js';", "const { esc } = globalThis.triageFormat;")
    module = module.replace("import { icon } from './icons.js';", "const { icon } = globalThis.triageIcons;")
    data_url = "data:text/javascript;base64," + base64.b64encode(module.encode()).decode()
    cases = [
        {
            "priority": {
                "level": "high", "label": "Yüksek", "reasons": ["<script>"],
                "codes": ["critical"], "code_text": ["Kritik sinyal"],
            },
            "agency": {
                "name": "Metro İstanbul", "url": "https://www.metro.istanbul/",
                "why": "raylı istasyon asansörü",
            },
            "note": TRIAGE_NOTE,
        },
        {
            "priority": {"level": "medium", "label": "Orta", "reasons": ["3 kişi bildirdi"]},
            "agency": {}, "note": TRIAGE_NOTE,
        },
        {
            "priority": {"level": "normal", "label": "Olağan", "reasons": ["1 kişi bildirdi"]},
            "agency": {}, "note": TRIAGE_NOTE,
        },
    ]
    runtime = (
        "globalThis.triageApi={MOCK:true,get:async()=>({})};"
        "globalThis.triageFormat={esc:v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('\\\"','&quot;').replaceAll(\"'\",'&#39;')};"
        "globalThis.triageIcons={icon:()=>'<svg aria-hidden=\\\"true\\\"></svg>'};"
        "globalThis.document={getElementById:()=>null};"
        f"const {{triageMarkup}}=await import({json.dumps(data_url)});"
        f"console.log(JSON.stringify({json.dumps(cases)}.map(triageMarkup)));"
    )
    output = subprocess.run(
        [node, "--input-type=module", "-e", runtime], check=True, capture_output=True, text=True
    )
    markup = json.loads(output.stdout)
    assert "tag is-bad" in markup[0] and "&lt;script&gt;" in markup[0]
    assert "tag is-warn" in markup[1] and "is-bad" not in markup[1]
    assert "tag is-bad" not in markup[2] and "is-warn" not in markup[2]
    assert "Eskalasyon tetiği yok; kart R-10 kuralıyla insana geldi." in markup[1]
    assert "<button" not in "".join(markup)

    for expected in (
        "/api/console/report-triage",
        "decision-body",
        "Öneri. Nabız hiçbir ekibe iş atamaz",
    ):
        assert expected in javascript
    for forbidden in ("post(", "Ata", "atandı", "gönderildi"):
        assert forbidden not in javascript
    assert "color:" not in css and "#" not in css and "rgb(" not in css.lower()
