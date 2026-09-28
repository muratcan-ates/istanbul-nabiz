"""E66 routes: untrusted text is screened, masked and kept off logs and the ledger."""

from __future__ import annotations

import asyncio
import json
import pathlib
import sqlite3

import pytest
from conftest import offline_settings
from fastapi.testclient import TestClient
from nexus_helpers import Clock, approve, build_engine
from test_map_layers_api import offline_nabiz
from test_report_outcome import put_static_last

from nabiz.agent import llm
from nabiz.console.access import OperatorAccess
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.nexus_port import NexusConsole
from nabiz.console.ports import Ports
from nabiz.console.published import PublishedCards
from nabiz.console.report_api import REPORT_KIND, report_routes, report_signal
from nabiz.console.report_outcome_api import outcome_routes, report_code
from nabiz.console.report_timeline import TimelineStore
from nabiz.console.report_timeline_api import timeline_routes
from nabiz.console.requests_api import EMERGENCY_TEXT


@pytest.fixture
def timeline_client(tmp_path: pathlib.Path):
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    nabiz = offline_nabiz(tmp_path)
    console = NexusConsole(engine, nabiz=nabiz, recorded=lambda: None, offline=True, ingest_every_s=0, clock=clock)
    published = PublishedCards(engine, offline=True, stale_after_s=engine.stale_after_s, clock=clock)
    app = build_console_app(
        nabiz=nabiz, settings=offline_settings(), llm_config=llm.LlmConfig(), ports=Ports(console=console, published=published),
        guard=SpendGuard(BudgetConfig(state_path=None)), access=OperatorAccess(),
    )
    app.state.report_clock = clock
    app.state.report_timeline = TimelineStore(tmp_path / "timeline.db", clock=clock)
    app.include_router(report_routes)
    app.include_router(outcome_routes)
    app.include_router(timeline_routes)
    put_static_last(app)
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        yield client, engine, clock
    asyncio.run(nabiz.aclose())


def create_report(client: TestClient, engine, clock: Clock, *, kind: str = "not_working") -> str:
    signal, evidence = report_signal("Kartal", ["M4"], kind, "now", clock(), (None, None, None))
    result = engine.process(signal, evidence)
    return report_code(result.signal_id)


def report_path(code: str) -> str:
    return f"/api/report/timeline/{code}"


def resolution(client: TestClient, code: str) -> None:
    assert client.post(f"/api/console/report-timeline/{code}/advance", json={"to": "reviewing"}).status_code == 200
    result = client.post(f"/api/console/report-timeline/{code}/advance", json={
        "to": "resolution_reported", "note": "Bakım tamamlandı.",
    })
    assert result.status_code == 200


def test_get_validates_codes_and_does_not_create_a_timeline(timeline_client) -> None:
    client, engine, clock = timeline_client
    assert client.get(report_path("bad")).status_code == 422
    assert client.get(report_path("23456789")).status_code == 404
    code = create_report(client, engine, clock)
    result = client.get(report_path(code))
    assert result.status_code == 200 and result.json()["stage"] == "recorded"
    assert "signal_id" not in result.json()
    with client.app.state.report_timeline._connect() as conn:
        assert conn.execute("SELECT count(*) FROM report_timeline").fetchone()[0] == 0


def test_operator_moves_require_notes_and_reject_disallowed_targets(timeline_client) -> None:
    client, engine, clock = timeline_client
    code = create_report(client, engine, clock)
    url = f"/api/console/report-timeline/{code}/advance"
    assert client.post(url, json={"to": "reviewing"}).status_code == 200
    assert client.post(url, json={"to": "resolution_reported"}).status_code == 400
    assert client.post(url, json={"to": "confirmed"}).status_code == 409
    assert client.post(url, json={"to": "resolution_reported", "note": "Bakım tamamlandı."}).status_code == 200


def test_citizen_fixed_confirms_and_confirmation_is_terminal(timeline_client) -> None:
    client, engine, clock = timeline_client
    code = create_report(client, engine, clock)
    resolution(client, code)
    result = client.post(report_path(code) + "/respond", json={"action": "fixed"})
    assert result.status_code == 200 and result.json()["stage"] == "confirmed"
    assert client.post(report_path(code) + "/respond", json={"action": "fixed"}).status_code == 409


def test_citizen_ongoing_needs_consent_reopens_and_code_limit_is_three(timeline_client) -> None:
    client, engine, clock = timeline_client
    code = create_report(client, engine, clock)
    resolution(client, code)
    path = report_path(code) + "/respond"
    text = "Asansör hâlâ kapalı ve arızalı."
    assert client.post(path, json={"action": "ongoing", "text": text}).status_code == 400
    result = client.post(path, json={"action": "ongoing", "text": text, "consent": True})
    assert result.status_code == 200 and result.json()["stage"] == "reopened"
    assert result.json()["reopen_count"] == 1
    assert client.post(path, json={"action": "fixed"}).status_code == 409
    assert client.post(path, json={"action": "fixed"}).status_code == 409
    assert client.post(path, json={"action": "fixed"}).status_code == 429


def test_emergency_returns_112_without_writing(timeline_client) -> None:
    client, engine, clock = timeline_client
    code = create_report(client, engine, clock)
    resolution(client, code)
    body = {"action": "ongoing", "text": "Yangın çıktı, duman var.", "consent": True}
    response = client.post(report_path(code) + "/respond", json=body)
    assert response.status_code == 200 and response.json() == {"emergency": True, "text": EMERGENCY_TEXT}
    row = client.app.state.report_timeline.get(code)
    assert row["stage"] == "resolution_reported"


def test_console_routes_use_operator_access(timeline_client) -> None:
    client, engine, clock = timeline_client
    create_report(client, engine, clock)
    client.app.state.access = OperatorAccess(token="test-token")
    assert client.get("/api/console/report-timeline").status_code == 401
    authorized = client.get("/api/console/report-timeline", headers={"X-Nabiz-Operator": "test-token"})
    assert authorized.status_code == 200 and len(authorized.json()["items"]) == 1


def test_citizen_response_contains_no_signal_or_unmasked_text(timeline_client, caplog) -> None:
    caplog.set_level("INFO")
    client, engine, clock = timeline_client
    code = create_report(client, engine, clock)
    resolution(client, code)
    text = "Telefon 0555 123 45 67 ve e-posta person@example.com; arıza sürüyor."
    result = client.post(report_path(code) + "/respond", json={"action": "ongoing", "text": text, "consent": True})
    encoded = json.dumps(result.json(), ensure_ascii=False)
    assert result.status_code == 200
    assert "signal_id" not in encoded and "simule-operator" not in encoded
    assert "0555 123 45 67" not in encoded and "person@example.com" not in encoded
    client.get(report_path(code.lower()))
    application_logs = "\n".join(record.getMessage() for record in caplog.records if record.name.startswith("nabiz.console"))
    assert "0555 123 45 67" not in application_logs
    assert "person@example.com" not in application_logs and code not in application_logs
    assert result.headers["cache-control"] == "no-store"


def test_rejected_report_is_readable_but_not_tracked(timeline_client) -> None:
    client, engine, clock = timeline_client
    code = create_report(client, engine, clock)
    state = next(item for item in engine.states().values() if item.signal.kind == REPORT_KIND)
    engine.decide(approve(state.signal.signal_id, action="reject", reason="Saha teyidi yok"))
    result = client.get(report_path(code))
    assert result.status_code == 200 and result.json()["publication"] == "not_published"
    assert client.post(report_path(code) + "/respond", json={"action": "fixed"}).json()["error"] == "not_tracked"
    assert client.post(f"/api/console/report-timeline/{code}/advance", json={"to": "reviewing"}).json()["error"] == "not_tracked"


def test_every_endpoint_response_is_no_store(timeline_client) -> None:
    client, engine, clock = timeline_client
    code = create_report(client, engine, clock)
    responses = [client.get(report_path(code)), client.get("/api/console/report-timeline")]
    responses += [client.get(report_path("bad")), client.post(report_path(code) + "/respond", json={"action": "fixed"})]
    responses.append(client.post(report_path(code) + "/respond", json={"action": "unknown"}))
    assert all(item.headers.get("cache-control") == "no-store" for item in responses)


def test_operator_step_and_its_ledger_seal_land_together_or_not_at_all(timeline_client, monkeypatch) -> None:
    client, engine, clock = timeline_client
    code = create_report(client, engine, clock)
    url = f"/api/console/report-timeline/{code}/advance"
    assert client.post(url, json={"to": "reviewing"}).status_code == 200

    def broken(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(engine.ledger, "append", broken)
    failed = client.post(url, json={"to": "resolution_reported", "note": "Bakım tamamlandı."})
    assert failed.status_code == 503 and failed.json()["error"] == "ledger_failed"
    assert failed.headers["cache-control"] == "no-store"
    row = client.app.state.report_timeline.get(code)
    assert row["stage"] == "reviewing" and [event["stage"] for event in row["data"]["history"]] == ["recorded", "reviewing"]
    monkeypatch.undo()
    sealed = client.post(url, json={"to": "resolution_reported", "note": "Bakım tamamlandı."})
    assert sealed.status_code == 200 and sealed.json()["stage"] == "resolution_reported"
    entry = engine.ledger.entries()[-1]
    assert entry.kind == "report_timeline_advanced" and entry.id == sealed.json()["ledger_entry_id"]
    assert entry.detail["from"] == "reviewing" and entry.detail["to"] == "resolution_reported"
    assert "Bakım" not in json.dumps(entry.detail, ensure_ascii=False)
