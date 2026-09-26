"""E33: a visitor can read the outcome of their report without an account."""

from __future__ import annotations

import asyncio
import json
import pathlib
import re
import subprocess

import pytest
from conftest import REPO_ROOT, offline_settings
from fastapi.testclient import TestClient
from nexus_helpers import Clock, approve, build_engine

from ibb_mcp.config import Settings
from nabiz.agent import llm
from nabiz.console.access import OperatorAccess, TurnLimiter
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.nexus_port import NexusConsole
from nabiz.console.ports import Ports
from nabiz.console.published import PublishedCards
from nabiz.console.report_api import REPORT_KIND, report_routes
from nabiz.console.report_outcome_api import (
    CODE_SALT,
    outcome_routes,
    report_code,
)


def put_static_last(app) -> None:
    mount = next(route for route in app.router.routes if getattr(route, "name", None) == "static")
    app.router.routes.remove(mount)
    app.router.routes.append(mount)


def outcome_app(engine, clock):
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
    app.include_router(outcome_routes)
    put_static_last(app)
    app.state.report_clock = clock
    return app, published


@pytest.fixture
def outcome_client(tmp_path: pathlib.Path):
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    app, published = outcome_app(engine, clock)
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        yield client, engine, clock, published


def post_report(client: TestClient, *, station: str = "Kartal", kind: str = "not_working", bucket: str = "now"):
    return client.post("/api/report", json={"station": station, "kind": kind, "bucket": bucket})


def code_for(client: TestClient, *, station: str = "Kartal", kind: str = "not_working") -> str:
    response = client.get("/api/report/code", params={"station": station, "kind": kind})
    assert response.status_code == 200, response.text
    return response.json()["code"]


def test_the_code_is_stable_and_uses_the_request_alphabet() -> None:
    from nabiz.console.citizen_requests import CODE_ALPHABET, normal_code

    one = report_code("signal-1")
    assert report_code("signal-1") == one
    assert report_code("signal-2") != one
    assert len(one) == 8 and all(char in CODE_ALPHABET for char in one)
    assert re.fullmatch(r"[2-9A-Z]{8}", one)
    assert normal_code(one) == one
    assert CODE_SALT == "nabiz-report-code|"


def test_a_report_gets_a_code_that_reads_waiting(outcome_client) -> None:
    client, _, _, _ = outcome_client

    created = post_report(client)
    assert created.status_code == 200
    code_response = client.get(
        "/api/report/code", params={"station": "kartal", "kind": "not_working"}
    )
    result = client.get(f"/api/report/outcome/{code_response.json()['code']}")

    assert code_response.status_code == 200 and code_response.json()["station"] == "Kartal"
    assert code_response.headers["cache-control"] == "no-store"
    assert result.json()["status"] == "waiting"
    assert result.json()["label"] == "Onay bekliyor"
    assert result.json()["support_count"] == 1
    assert result.headers["cache-control"] == "no-store"


def test_folded_reports_share_one_code(outcome_client) -> None:
    client, _, clock, _ = outcome_client
    client.app.state.report_limiter = TurnLimiter(60)

    post_report(client)
    first = code_for(client)
    clock.advance(minutes=5)
    post_report(client)
    second = code_for(client)

    assert second == first
    assert client.get(f"/api/report/outcome/{first}").json()["support_count"] == 2


def test_approved_reads_published_and_the_card_is_public(outcome_client) -> None:
    client, engine, _, published = outcome_client
    post_report(client)
    code = code_for(client)
    state = next(state for state in engine.states().values() if state.signal.kind == REPORT_KIND)
    engine.decide(
        approve(
            state.signal.signal_id,
            action="approve",
            reason="Saha teyidi",
        )
    )

    result = client.get(f"/api/report/outcome/{code}").json()
    cards = asyncio.run(published.published(stations=["Kartal"]))

    assert result["status"] == "approved"
    assert result["text"] == "Simüle operatör onayladı; bildirim Kartal kartında yayımlandı."
    assert len(cards) == 1

    post_report(client, kind="data_wrong")
    edited_code = code_for(client, kind="data_wrong")
    edited = next(
        state for state in engine.states().values() if state.signal.payload.get("report_kind") == "data_wrong"
    )
    engine.decide(
        approve(
            edited.signal.signal_id,
            action="edit",
            reason="Düzeltilen metin",
            edited_text="Kartal kaydı incelendi.",
        )
    )
    assert client.get(f"/api/report/outcome/{edited_code}").json()["status"] == "approved"


def test_rejected_reads_not_published(outcome_client) -> None:
    client, engine, _, published = outcome_client
    post_report(client)
    code = code_for(client)
    state = next(state for state in engine.states().values() if state.signal.kind == REPORT_KIND)
    engine.decide(approve(state.signal.signal_id, action="reject", reason="Saha teyidi yok"))

    result = client.get(f"/api/report/outcome/{code}").json()

    assert result["status"] == "not_published"
    assert asyncio.run(published.published(stations=["Kartal"])) == []


def test_an_unanswered_card_reads_expired_without_writing(outcome_client) -> None:
    client, engine, clock, _ = outcome_client
    client.app.state.report_limiter = TurnLimiter(60)
    post_report(client)
    code = code_for(client)
    before = len(engine.ledger.entries())
    clock.advance(hours=engine.ttl_hours + 1)

    result = client.get(f"/api/report/outcome/{code}").json()
    after = len(engine.ledger.entries())
    engine.expire()
    sealed = client.get(f"/api/report/outcome/{code}").json()

    assert result["status"] == sealed["status"] == "expired"
    assert before == after

    post_report(client, kind="data_wrong")
    deferred_code = code_for(client, kind="data_wrong")
    deferred = next(state for state in engine.states().values() if state.signal.payload.get("report_kind") == "data_wrong")
    engine.decide(approve(deferred.signal.signal_id, action="defer", reason="Ek bilgi bekleniyor"))
    clock.advance(hours=engine.ttl_hours + 1)
    assert client.get(f"/api/report/outcome/{deferred_code}").json()["status"] == "waiting"


def test_after_a_decision_a_new_report_gets_a_new_code(outcome_client) -> None:
    client, engine, clock, _ = outcome_client
    client.app.state.report_limiter = TurnLimiter(60)
    post_report(client)
    old_code = code_for(client)
    state = next(state for state in engine.states().values() if state.signal.kind == REPORT_KIND)
    engine.decide(approve(state.signal.signal_id, action="reject", reason="Saha teyidi yok"))
    clock.advance(minutes=5)
    post_report(client)
    new_code = code_for(client)

    assert old_code != new_code
    assert client.get(f"/api/report/outcome/{old_code}").json()["status"] == "not_published"


def test_errors_are_plain(outcome_client) -> None:
    client, _, _, _ = outcome_client
    assert client.get("/api/report/code", params={"station": "Kartal", "kind": "not_working"}).json()[
        "error"
    ] == "no_open_report"
    assert client.get("/api/report/code", params={"station": "Kart", "kind": "not_working"}).json()[
        "error"
    ] == "unknown_station"
    assert client.get("/api/report/code", params={"station": "Kartal", "kind": "broken"}).json()[
        "error"
    ] == "invalid_request"
    assert client.get("/api/report/outcome/abc").json()["error"] == "invalid_code"
    assert client.get("/api/report/outcome/23456789").json()["error"] == "report_not_found"

    unwired = build_console_app(settings=Settings(offline=True), ports=Ports())
    unwired.include_router(outcome_routes)
    put_static_last(unwired)
    with TestClient(unwired) as other:
        code = other.get("/api/report/code", params={"station": "Kartal", "kind": "not_working"})
        outcome = other.get("/api/report/outcome/23456789")
    assert code.status_code == outcome.status_code == 503
    assert code.json()["error"] == outcome.json()["error"] == "not_wired"


def test_reading_writes_nothing_and_spends_no_quota(outcome_client) -> None:
    client, engine, _, _ = outcome_client
    responses = []
    for _ in range(3):
        responses.append(post_report(client))
        code = code_for(client)
        before = len(engine.ledger.entries())
        for _ in range(10):
            assert client.get("/api/report/code", params={"station": "Kartal", "kind": "not_working"}).status_code == 200
            assert client.get(f"/api/report/outcome/{code}").status_code == 200
        assert len(engine.ledger.entries()) == before
    fourth = post_report(client)

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert fourth.status_code == 429
    assert engine.verify().ok


def test_the_outcome_never_leaks_the_operator_or_the_card(outcome_client) -> None:
    client, engine, _, _ = outcome_client
    post_report(client)
    code = code_for(client)
    state = next(state for state in engine.states().values() if state.signal.kind == REPORT_KIND)
    engine.decide(approve(state.signal.signal_id, action="reject", reason="iç not: saha ekibi yok"))

    body = json.dumps(client.get(f"/api/report/outcome/{code}").json(), ensure_ascii=False)

    for hidden in ("iç not", "op-1", "signal_id", "sig-", "reason", "edited_text", "lift_text", "operator_text", "testclient"):
        assert hidden not in body
    assert not re.search(r"\d{4}-\d{2}-\d{2}T", body)


def test_outcome_markup_in_node() -> None:
    script = REPO_ROOT / "src" / "nabiz" / "console" / "static" / "js" / "report.js"
    javascript = script.read_text(encoding="utf-8")
    source = f"""
globalThis.window = {{ location: {{ search: '' }} }};
globalThis.document = {{ querySelector: () => null, getElementById: () => null }};
const {{ outcomeMarkup }} = await import({json.dumps(script.as_uri())});
const base = {{ code: 'K7M2QX9P', station: '<script>', kind_text: 'asansör kapalıydı', text: '<script>', label: 'Durum' }};
const cases = [
  ['waiting', 'is-info', 'Onay bekliyor', 'clock'],
  ['approved', 'is-ok', 'Onaylandı', 'circle-check'],
  ['not_published', '', 'Yayımlanmadı', 'info-circle'],
  ['expired', 'is-warn', 'Süresi doldu', 'clock'],
];
for (const [status, cls, label, glyph] of cases) {{
  const html = outcomeMarkup({{ ...base, status, label }});
  if (!html.includes(`is-${{status}}`) || (cls && !html.includes(`tag ${{cls}}`))) throw new Error(status);
  if (!html.includes(`/icons.svg#i-${{glyph}}`)) throw new Error('icon');
  if (!html.includes(label) || html.includes('<script>')) throw new Error('escaping');
  if (!html.includes('data-outcome="remove"')) throw new Error('remove');
}}
"""
    result = subprocess.run(["node", "--input-type=module", "-e", source], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    e33 = javascript.split("/* E33 · Bildirimim ne oldu? */", 1)[1]
    for forbidden in ("oluşturuldu", "iletildi", "başvurunuz", "çözüldü", "giderildi", "ETA", "—", "–", "çalışıyor"):
        assert forbidden not in e33


def test_the_device_store_reuses_the_request_pattern() -> None:
    script = REPO_ROOT / "src" / "nabiz" / "console" / "static" / "js" / "report.js"
    javascript = script.read_text(encoding="utf-8")
    status_script = REPO_ROOT / "src" / "nabiz" / "console" / "static" / "js" / "request_status.js"

    assert "import { parseStored, POLL_MS } from './request_status.js';" in javascript
    for expected in (
        "nabiz.report-codes.v1",
        'id="report-outcomes"',
        'aria-labelledby="report-outcomes-title"',
        'id="report-outcomes-status"',
        "setInterval",
        "nabiz:report-sent",
        "/api/report/code",
        "/api/report/outcome/",
        'role="status"',
        "tel:153",
    ):
        assert expected in javascript
    for forbidden in ("EventSource", "WebSocket", "fetch("):
        assert forbidden not in javascript
    styles = REPO_ROOT / "src" / "nabiz" / "console" / "static" / "css" / "report.css"
    assert ".report-outcomes[hidden] { display: none; }" in styles.read_text(encoding="utf-8")
    scripts = REPO_ROOT / "src" / "nabiz" / "console" / "static" / "js"
    assert not any("report_status" in path.name or "outcome" in path.name for path in scripts.iterdir())
    assert len(status_script.read_text(encoding="utf-8").splitlines()) <= 300
