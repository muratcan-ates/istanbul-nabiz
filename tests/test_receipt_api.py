from __future__ import annotations

import re

from conftest import offline_settings
from fastapi.testclient import TestClient
from nexus_helpers import Clock, build_engine, elevator, escalator
from test_nexus_core_receipts import MeteredSeats

from nabiz.agent import llm
from nabiz.console.access import OperatorAccess
from nabiz.console.app import build_console_app
from nabiz.console.arena_seats import ModelSeats
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.model_api import model_routes
from nabiz.console.nexus_port import NexusConsole
from nabiz.console.ports import Ports
from nabiz.console.receipt_api import receipt_routes
from nexus_core.engine import NexusEngine


def make_app(*, config=None, guard=None, ports=None, access=None):
    app = build_console_app(
        settings=offline_settings(),
        llm_config=config if config is not None else llm.LlmConfig(),
        ports=ports if ports is not None else Ports(),
        guard=guard if guard is not None else SpendGuard(BudgetConfig(state_path=None)),
        access=access if access is not None else OperatorAccess(),
    )
    app.include_router(model_routes)
    app.include_router(receipt_routes)
    mount = next(route for route in app.router.routes if getattr(route, "name", None) == "static")
    app.router.routes.remove(mount)
    app.router.routes.append(mount)
    return app


def client(*, config=None, guard=None, ports=None, access=None):
    return TestClient(make_app(config=config, guard=guard, ports=ports, access=access), base_url="http://127.0.0.1:8090")


def cloud_config() -> llm.LlmConfig:
    # These synthetic values exercise configuration only; no model request is made.
    return llm.LlmConfig(
        base_url="https://example.invalid/v1",
        api_key="test-key-not-a-secret",
        model="test-model",
        provider="openai_compatible",
    )


def console_port(engine: NexusEngine, clock: Clock) -> NexusConsole:
    return NexusConsole(engine, None, recorded=lambda: None, offline=True, clock=clock)  # type: ignore[arg-type]


def test_spend_in_dollars_when_both_prices_are_set() -> None:
    guard = SpendGuard(BudgetConfig(
        price_in_per_mtok=100.0,
        price_out_per_mtok=200.0,
        daily_usd=1.0,
        state_path=None,
    ))
    guard.record("openai_compatible", {"prompt_tokens": 1000, "completion_tokens": 100}, 1)
    result = client(guard=guard).get("/api/console/spend").json()
    assert result["chat"]["text"] == "Bugün 0,12 $ / 1,00 $"
    assert result["chat"]["kind"] == "usd"
    assert result["chat"]["level"] == "ok"


def test_spend_in_calls_when_a_price_is_missing() -> None:
    guard = SpendGuard(BudgetConfig(daily_calls=100, state_path=None))
    guard.record("openai_compatible", {}, 3)
    result = client(guard=guard).get("/api/console/spend").json()
    assert result["chat"]["text"] == "Bugün 3 / 100 model çağrısı"
    assert "$" not in result["chat"]["text"]


def test_three_quarters_turn_the_strip_yellow() -> None:
    guard = SpendGuard(BudgetConfig(daily_calls=4, state_path=None))
    guard.record("openai_compatible", {}, 3)
    result = client(config=cloud_config(), guard=guard).get("/api/console/spend").json()
    assert result["chat"]["level"] == "warn"
    assert "%75" in result["badge"]["text"]


def test_a_full_ceiling_says_answers_come_by_rule() -> None:
    guard = SpendGuard(BudgetConfig(daily_calls=1, state_path=None))
    guard.record("openai_compatible", {}, 1)
    result = client(config=cloud_config(), guard=guard).get("/api/console/spend").json()
    assert result["badge"]["text"] == "Model tavanı doldu: cevaplar kural yolundan"


def test_the_arena_line_counts_its_own_guard(tmp_path) -> None:
    clock = Clock()
    arena_guard = SpendGuard(BudgetConfig(daily_calls=30, state_path=None), clock=clock)
    engine = build_engine(tmp_path, clock, arena=ModelSeats(cloud_config(), arena_guard))
    arena_guard.record("openai_compatible", {}, 4)
    guard = SpendGuard(BudgetConfig(daily_calls=100, state_path=None), clock=clock)
    result = client(guard=guard, ports=Ports(console=console_port(engine, clock))).get("/api/console/spend").json()
    assert result["arena"]["text"] == "Arena 4/30"
    assert result["arena"]["remaining"] == 26
    assert result["chat"]["calls"] == 0


def test_without_model_seats_the_spend_still_answers_200(tmp_path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    result = client(ports=Ports(console=console_port(engine, clock))).get("/api/console/spend")
    assert result.status_code == 200
    assert result.json()["arena"]["wired"] is False
    assert "kural koltukları" in result.json()["arena"]["text"]
    unbound = client().get("/api/console/spend")
    assert unbound.status_code == 200 and "karar çekirdeği bağlı değil" in unbound.json()["line"]


def test_the_line_joins_spend_active_and_arena(tmp_path) -> None:
    clock = Clock()
    arena_guard = SpendGuard(BudgetConfig(daily_calls=30, state_path=None), clock=clock)
    engine = build_engine(tmp_path, clock, arena=ModelSeats(cloud_config(), arena_guard))
    arena_guard.record("openai_compatible", {}, 4)
    guard = SpendGuard(BudgetConfig(daily_calls=100, state_path=None), clock=clock)
    guard.record("openai_compatible", {}, 3)
    result = client(config=cloud_config(), guard=guard, ports=Ports(console=console_port(engine, clock)))
    assert result.get("/api/console/spend").json()["line"] == (
        "Bugün 3 / 100 model çağrısı · aktif: bulut modeli · Arena 4/30"
    )


def test_author_split_only_when_the_chat_counts_it() -> None:
    app = make_app()
    web = TestClient(app, base_url="http://127.0.0.1:8090")
    uncounted = web.get("/api/console/spend").json()
    assert uncounted["authors"] is None and uncounted["authors_note"] == "bağlanmadı"
    app.state.author_counts = {"kural": 3, "model": 1, "yerel model": -4, "ignored": 20}
    counted = web.get("/api/console/spend").json()
    assert counted["authors"] == {"model": 1, "yerel model": 0, "kural": 3}


def test_receipts_list_every_run_newest_first(tmp_path) -> None:
    clock = Clock()
    seats = MeteredSeats()
    engine = build_engine(tmp_path, clock, arena=seats)
    engine.process(escalator())
    clock.advance(minutes=1)
    arena = engine.process(elevator())
    result = client(ports=Ports(console=console_port(engine, clock))).get("/api/console/receipts").json()
    assert len(result["receipts"]) == 2
    assert result["receipts"][0]["path"] == "arena"
    assert result["receipts"][0]["llm_calls"] == 1
    assert result["receipts"][0]["signal_id"] == arena.signal_id
    assert result["receipts"][1]["path"] == "reflex"
    assert result["receipts"][1]["result_label"] == "refleksle kapandı"


def test_unpriced_receipts_say_price_undefined(tmp_path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock, arena=MeteredSeats())
    engine.process(elevator())
    result = client(ports=Ports(console=console_port(engine, clock))).get("/api/console/receipts").json()
    assert result["receipts"][0]["usd"] is None
    assert result["receipts"][0]["usd_label"] == "fiyat tanımsız"
    assert result["totals"]["usd"] is None
    assert result["price_note"] == "fiyat tanımsız"


def test_priced_receipts_are_labelled_estimates(tmp_path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock, arena=MeteredSeats(), usd_per_call=0.02)
    engine.process(elevator())
    result = client(ports=Ports(console=console_port(engine, clock))).get("/api/console/receipts").json()
    row = result["receipts"][0]
    assert row["usd"] == 0.02
    assert row["usd_label"] == "tahmin"
    assert result["totals"]["usd"] == 0.02
    assert "ölçüldü" not in row["line"]


def test_receipts_without_an_engine_answer_503_not_wired() -> None:
    response = client().get("/api/console/receipts")
    assert response.status_code == 503
    assert response.json()["error"] == "not_wired"


def test_reading_receipts_makes_no_model_call(tmp_path) -> None:
    clock = Clock()
    seats = MeteredSeats()
    engine = build_engine(tmp_path, clock, arena=seats)
    engine.process(elevator())
    before = seats.calls_made
    client(ports=Ports(console=console_port(engine, clock))).get("/api/console/receipts")
    assert seats.calls_made == before


def test_no_dash_or_eta_in_the_answers(tmp_path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock, arena=MeteredSeats())
    engine.process(elevator())
    web = client(ports=Ports(console=console_port(engine, clock)))
    for response in (web.get("/api/console/spend"), web.get("/api/console/receipts")):
        assert response.status_code == 200
        for forbidden in ("—", "–"):
            assert forbidden not in response.text
        assert re.search(r"\bETA\b", response.text) is None


def test_strip_files_follow_the_page_rules() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "nabiz" / "console" / "static"
    console_js = (root / "js" / "console_receipt.js").read_text(encoding="utf-8")
    model_js = (root / "js" / "model_strip.js").read_text(encoding="utf-8")
    css = (root / "css" / "console_receipt.css").read_text(encoding="utf-8")
    required_console = (
        "/api/console/spend", "/api/console/receipts", "aria-labelledby", 'scope="col"', 'scope="row"',
        'role="status"',
    )
    for required in required_console:
        assert required in console_js
    for required in ("max-width: 40rem", "overflow-wrap: anywhere", "#receipt-badge .tag { white-space: normal; }"):
        assert required in css
    assert "/api/model/status" in model_js and "chat-hint" in model_js
    for forbidden in ("usd", "ratio", "$"):
        assert forbidden not in model_js
