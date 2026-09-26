"""E24: private citizen reports are folded into one card for a human."""

from __future__ import annotations

import asyncio
import json
import pathlib
import threading
import time
from collections.abc import Sequence

import pytest
from conftest import REPO_ROOT, offline_settings
from fastapi.testclient import TestClient
from nexus_helpers import Clock, approve, build_engine

from ibb_mcp.config import Settings
from nabiz.agent import llm
from nabiz.console import report_api
from nabiz.console.access import OperatorAccess, TurnLimiter
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.nexus_port import NexusConsole
from nabiz.console.ports import Ports
from nabiz.console.published import PublishedCards
from nabiz.console.report_api import (
    BUCKET_TR,
    KIND_TR_TEXT,
    REPORT_KIND,
    SUPPORT_ENTRY,
    confirmation,
    report_routes,
    support_count,
    support_counts,
    support_step_text,
    support_summary,
)
from nexus_core.arena import EvidenceItem, Opinion
from nexus_core.missions import EscalationSettings, load_mission, load_missions
from nexus_core.signals import Signal


def put_static_last(app) -> None:
    mount = next(route for route in app.router.routes if getattr(route, "name", None) == "static")
    app.router.routes.remove(mount)
    app.router.routes.append(mount)


def report_app(engine, clock):
    console = NexusConsole(
        engine, nabiz=None, recorded=lambda: None, offline=True, ingest_every_s=0, clock=clock
    )  # type: ignore[arg-type]
    published = PublishedCards(engine, offline=True, stale_after_s=engine.stale_after_s, clock=clock)
    app = build_console_app(
        settings=offline_settings(),
        llm_config=llm.LlmConfig(),
        ports=Ports(console=console, published=published),
        guard=SpendGuard(BudgetConfig(state_path=None)),
        access=OperatorAccess(),
    )
    app.include_router(report_routes)
    put_static_last(app)
    app.state.report_clock = clock
    return app, published


@pytest.fixture
def report_client(tmp_path: pathlib.Path):
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    app, published = report_app(engine, clock)
    with TestClient(app) as client:
        yield client, engine, clock, published


class GatedSeats:
    """Arena seats that hold the card in the Arena until the test lets it go (a slow model seat)."""

    author = "model"
    label = "Bekleyen model koltukları"

    def __init__(self) -> None:
        self.release = threading.Event()

    def opinions(self, signal: Signal, evidence: Sequence[EvidenceItem]) -> list[Opinion]:
        self.release.wait(timeout=10)
        return [
            Opinion(role="Erişilebilirlik", stance="support", rationale="Kanıt yeterli."),
            Opinion(role="Operasyon", stance="conditional", rationale="Saha teyidi yok."),
            Opinion(role="İletişim", stance="conditional", rationale="Tek kaynak."),
        ]


def citizen_states(engine):
    return [state for state in engine.states().values() if state.signal.kind == REPORT_KIND]


def post_report(client: TestClient, *, station: str = "Kartal", kind: str = "not_working", bucket: str = "now"):
    return client.post("/api/report", json={"station": station, "kind": kind, "bucket": bucket})


def test_a_report_becomes_one_arena_card_awaiting_a_person(report_client) -> None:
    client, engine, _, _ = report_client

    response = post_report(client)

    assert response.status_code == 200
    assert response.json()["folded"] is False
    assert response.json()["support_count"] == 1
    states = citizen_states(engine)
    assert len(states) == 1
    state = states[0]
    assert state.status == "awaiting_approval"
    assert state.path == "arena" and state.rule_id == "R-10"
    assert state.reasons == ("rule_path",)
    assert state.decision.proposed_action.text.startswith("Kartal istasyonunda")
    assert engine.verify().ok


def test_reports_within_thirty_minutes_fold_into_one_card(report_client) -> None:
    client, engine, clock, _ = report_client
    client.app.state.report_limiter = TurnLimiter(60)

    replies = []
    for _ in range(3):
        replies.append(post_report(client).json())
        clock.advance(minutes=5)

    states = citizen_states(engine)
    assert len(states) == 1
    assert replies[-1]["support_count"] == 3
    assert len(engine.ledger.entries(kinds=[SUPPORT_ENTRY])) == 2
    assert support_count(engine, states[0].signal.signal_id) == 3
    assert engine.verify().ok


@pytest.mark.parametrize("action", ["reject", "approve"])
def test_after_a_decision_a_new_report_opens_a_new_card(report_client, action: str) -> None:
    client, engine, clock, _ = report_client

    post_report(client)
    first_state = citizen_states(engine)[0]
    clock.advance(minutes=5)
    engine.decide(approve(first_state.signal.signal_id, action=action, reason="Saha teyidi yok"))
    clock.advance(minutes=5)

    reply = post_report(client).json()

    states = citizen_states(engine)
    assert reply["folded"] is False and reply["support_count"] == 1
    assert len(states) == 2
    assert states[-1].signal.signal_id != first_state.signal.signal_id
    assert states[-1].status == "awaiting_approval"
    assert engine.ledger.entries(signal_id=first_state.signal.signal_id, kinds=[SUPPORT_ENTRY]) == []
    assert client.get("/api/report/status", params={"station": "Kartal", "kind": "not_working"}).json()[
        "support_count"
    ] == 1


def test_a_report_while_the_arena_still_runs_folds_into_that_card(tmp_path, monkeypatch) -> None:
    clock = Clock()
    seats = GatedSeats()
    engine = build_engine(tmp_path, clock, arena=seats)
    app, _ = report_app(engine, clock)
    monkeypatch.setattr(report_api, "REPORT_WAIT_S", 0.05)
    with TestClient(app) as client:
        first = post_report(client).json()
        deadline = time.monotonic() + 5
        while not citizen_states(engine) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert [state.status for state in citizen_states(engine)] == ["received"]
        clock.advance(minutes=1)

        second = post_report(client).json()

        seats.release.set()
        deadline = time.monotonic() + 5
        while citizen_states(engine)[0].status == "received" and time.monotonic() < deadline:
            time.sleep(0.01)
    states = citizen_states(engine)
    assert first["folded"] is False and second["folded"] is True and second["support_count"] == 2
    assert len(states) == 1 and states[0].status == "awaiting_approval"
    assert support_count(engine, states[0].signal.signal_id) == 2
    assert engine.verify().ok


def test_after_thirty_minutes_a_new_card_opens(report_client) -> None:
    client, engine, clock, _ = report_client
    post_report(client)
    clock.advance(minutes=31)

    response = post_report(client)

    assert response.status_code == 200
    assert response.json()["folded"] is False and response.json()["support_count"] == 1
    assert len(citizen_states(engine)) == 2


def test_a_wrong_record_report_is_its_own_card(report_client) -> None:
    client, engine, clock, _ = report_client
    post_report(client, kind="not_working")
    clock.advance(minutes=1)

    response = post_report(client, kind="data_wrong", bucket="today")

    assert response.status_code == 200 and response.json()["folded"] is False
    assert {state.signal.payload["report_kind"] for state in citizen_states(engine)} == {"not_working", "data_wrong"}


@pytest.mark.parametrize(
    "body",
    [
        {"station": "Kartal", "kind": "not_working", "bucket": "now", "note": "Yazı"},
        {"station": "Kartal", "kind": "not_working", "bucket": "now", "equipment_code": "E-1"},
        {"station": "Kartal", "kind": "broken", "bucket": "now"},
        {"station": "Kartal", "kind": "not_working", "bucket": "yesterday"},
        {"kind": "not_working", "bucket": "now"},
        {"station": "K" * 61, "kind": "not_working", "bucket": "now"},
        {"station": "<script>", "kind": "not_working", "bucket": "now"},
    ],
)
def test_anything_beyond_the_three_fields_is_refused(report_client, body: dict[str, object]) -> None:
    client, engine, _, _ = report_client
    before = len(engine.ledger.entries())

    response = client.post("/api/report", json=body)

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"
    assert len(engine.ledger.entries()) == before


def test_an_unknown_or_partial_station_is_refused(report_client) -> None:
    client, _, _, _ = report_client

    partial = post_report(client, station="Kart")
    unknown = post_report(client, station="Asdfgh")
    folded = post_report(client, station="kartal")

    assert partial.status_code == unknown.status_code == 422
    assert partial.json()["error"] == unknown.json()["error"] == "unknown_station"
    assert folded.status_code == 200 and folded.json()["station"] == "Kartal"


def test_the_fourth_report_in_a_minute_is_refused(report_client) -> None:
    client, engine, _, _ = report_client
    client.app.state.report_limiter = TurnLimiter(3)

    responses = [post_report(client) for _ in range(4)]

    assert [response.status_code for response in responses] == [200, 200, 200, 429]
    assert responses[-1].json()["error"] == "too_many_reports"
    assert "testclient" not in repr(engine.ledger.entries())
    assert all("signal_id" not in response.json() for response in responses[:3])


def test_the_public_card_does_not_change_on_a_report(report_client) -> None:
    client, _, _, published = report_client
    before_cards = asyncio.run(published.published(stations=["Kartal"]))
    before_alternative = client.get("/api/alternative", params={"station": "Kartal"}).json()

    post_report(client)

    after_cards = asyncio.run(published.published(stations=["Kartal"]))
    after_alternative = client.get("/api/alternative", params={"station": "Kartal"}).json()
    assert before_cards == after_cards == []
    assert before_alternative == after_alternative


def test_only_a_person_publishes_a_report(report_client) -> None:
    client, engine, _, published = report_client
    post_report(client)
    state = citizen_states(engine)[0]

    engine.decide(approve(state.signal.signal_id))

    cards = asyncio.run(published.published(stations=["Kartal"]))
    assert len(cards) == 1
    assert "Bu bilgi vatandaş bildirimidir" in cards[0]["body"]
    assert "(Simüle operatör onayladı.)" in cards[0]["body"]


def test_rejection_does_not_publish_a_report(report_client) -> None:
    client, engine, _, published = report_client
    post_report(client)
    state = citizen_states(engine)[0]

    engine.decide(approve(state.signal.signal_id, action="reject", reason="Saha teyidi yok"))

    assert asyncio.run(published.published(stations=["Kartal"])) == []


def test_without_an_engine_the_report_answers_503(tmp_path: pathlib.Path) -> None:
    app = build_console_app(settings=Settings(offline=True), ports=Ports())
    app.include_router(report_routes)
    put_static_last(app)
    with TestClient(app) as client:
        response = post_report(client)
    assert response.status_code == 503 and response.json()["error"] == "not_wired"


def test_status_counts_only_the_window(report_client) -> None:
    client, engine, clock, _ = report_client
    params = {"station": "Kartal", "kind": "not_working"}
    assert client.get("/api/report/status", params=params).json()["support_count"] == 0
    post_report(client)
    clock.advance(minutes=5)
    post_report(client)
    before = len(engine.ledger.entries())

    assert client.get("/api/report/status", params=params).json()["support_count"] == 2
    assert len(engine.ledger.entries()) == before
    clock.advance(minutes=31)
    assert client.get("/api/report/status", params=params).json()["support_count"] == 0
    assert len(engine.ledger.entries()) == before


def test_the_mission_sends_every_citizen_report_to_a_person() -> None:
    path = REPO_ROOT / "missions" / "vatandas_bildirimi.toml"
    mission = load_mission(path)
    rule, = mission.rules
    all_missions = load_missions(REPO_ROOT / "missions")
    existing = [item for item in all_missions if item.id != mission.id]
    ids = [rule.id for item in all_missions for rule in item.rules]
    mission_text = path.read_text(encoding="utf-8")

    assert (rule.id, rule.path, rule.when.kind) == ("R-10", "arena", REPORT_KIND)
    assert rule.then.action == "publish_card"
    assert len(ids) == len(set(ids))
    assert EscalationSettings.merged(item.escalation for item in all_missions) == EscalationSettings.merged(
        item.escalation for item in existing
    )
    assert "çalışıyor" not in mission_text and "ETA" not in mission_text


def test_support_summary_and_counts_are_plain(report_client) -> None:
    client, engine, clock, _ = report_client
    client.app.state.report_limiter = TurnLimiter(60)
    for _ in range(3):
        post_report(client)
        clock.advance(minutes=1)
    state = citizen_states(engine)[0]
    summary = support_summary(state, 3)

    assert support_counts(engine) == {state.signal.signal_id: 3}
    assert "3 kişi bildirdi" in summary and len(summary) <= 300
    assert "—" not in summary and "–" not in summary and "12:00" in summary
    assert KIND_TR_TEXT["not_working"] in summary and BUCKET_TR["now"] in summary
    assert confirmation(2).endswith("kuyruğuna düştü (simüle operatör) · 2 kişi")
    assert "oluşturuldu" not in confirmation(2) and "iletildi" not in confirmation(2)
    assert support_step_text({"support_count": 3}) == "Vatandaş bildirimi katlandı: toplam 3 kişi."
    assert support_step_text({}) == "Vatandaş bildirimi katlandı."


def test_bildirim_journeys_replay(report_client) -> None:
    client, engine, _, published = report_client
    client.app.state.report_limiter = TurnLimiter(60)
    scenarios = [
        json.loads(line)
        for line in (REPO_ROOT / "eval" / "journeys.bildirim.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    for scenario in scenarios:
        request = scenario["request"]
        response = client.request(
            request["method"],
            request["path"],
            json=request.get("json"),
        )
        actual = {"status": response.status_code}
        body = response.json()
        for key in ("error", "folded", "support_count"):
            if key in body:
                actual[key] = body[key]
        states = citizen_states(engine)
        actual["cards"] = len(states)
        if "card_status" in scenario["expect"]:
            actual["card_status"] = states[-1].status
        if "path" in scenario["expect"]:
            actual["path"] = states[-1].path
        if "rule_id" in scenario["expect"]:
            actual["rule_id"] = states[-1].rule_id
        if "published" in scenario["expect"]:
            actual["published"] = len(asyncio.run(published.published(stations=["Kartal"])))
        for field, expected in scenario["expect"].items():
            assert actual[field] == expected, scenario["id"]


def test_report_files_follow_the_page_rules() -> None:
    script = REPO_ROOT / "src" / "nabiz" / "console" / "static" / "js" / "report.js"
    styles = REPO_ROOT / "src" / "nabiz" / "console" / "static" / "css" / "report.css"
    javascript = script.read_text(encoding="utf-8")
    css = styles.read_text(encoding="utf-8")

    for expected in (
        "Asansör kapalıydı, bildir",
        "Kayıt yanlış görünüyor, bildir",
        "Zaten bildirildi",
        "/api/report",
        "/api/report/status",
        'role="status"',
        "aria-expanded",
        "tel:153",
    ):
        assert expected in javascript
    for forbidden in ("oluşturuldu", "iletildi", "başvurunuz", "ETA", "—", "–", "çalışıyor"):
        assert forbidden not in javascript
    assert "min-height: var(--tap)" in css
    assert "@media (forced-colors: active)" in css
