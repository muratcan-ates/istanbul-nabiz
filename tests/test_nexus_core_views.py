"""nexus_core.views: the console API's JSON shapes, field for field as the contract names them."""

from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest
from nexus_helpers import T0, Clock, approve, build_engine, elevator, escalator, make_signal

from nexus_core.views import decision_payload, drafts_payload, queue_payload, stats_payload, trace_payload

PROVENANCE = {"source", "url", "observed_at", "age_s", "mode"}


def test_the_queue_items_have_the_contract_fields(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    engine.process(escalator())
    clock.advance(minutes=1)
    arena = engine.process(elevator()).signal_id
    items = queue_payload(engine.states().values())["items"]
    assert [i["signal_id"] for i in items][0] == arena  # newest first
    required = {"signal_id", "kind", "title", "severity", "path", "status", "created_at", "summary", "expires_at"}
    for item in items:
        assert required <= set(item)
        assert item["status"] in {"closed_by_reflex", "awaiting_approval", "approved", "rejected", "deferred", "expired"}
        assert item["severity"] in {"info", "warning", "critical"} and item["path"] in {"reflex", "arena"}
    assert items[1]["status"] == "closed_by_reflex" and items[1]["summary"].startswith("Kadıköy")
    json.dumps(items)


def test_the_decision_card_has_the_contract_fields(tmp_path: pathlib.Path) -> None:
    clock = Clock(T0 + dt.timedelta(minutes=5))
    engine = build_engine(tmp_path, clock)
    signal_id = engine.process(elevator()).signal_id
    card = decision_payload(engine.states()[signal_id], clock.now)
    required = {
        "signal_id", "signal", "evidence", "freshness_s", "alternatives", "opinions",
        "dissent_summary", "proposed_action", "confidence", "author", "panel", "receipt", "expires_at",
    }  # fmt: skip
    assert required <= set(card)
    assert card["freshness_s"] == 300 and card["author"] == "kural"
    assert all(set(e) == {"text", "provenance"} and set(e["provenance"]) == PROVENANCE for e in card["evidence"])
    assert all(set(a) == {"label", "detail"} for a in card["alternatives"])
    for opinion in card["opinions"]:
        assert set(opinion) == {"role", "stance", "rationale", "citations"}
        assert opinion["role"] in {"Erişilebilirlik", "Operasyon", "İletişim"}
        assert all(set(c) == PROVENANCE for c in opinion["citations"])
    assert set(card["proposed_action"]) == {"kind", "text", "expires_at"}
    assert set(card["confidence"]) == {"level", "reasons", "uncertainty"}
    assert card["confidence"]["level"] in {"high", "medium", "low"}
    assert set(card["panel"]) == {"verdict", "votes", "answered", "quorum", "rounds"}
    assert set(card["receipt"]) == {"path", "reflex_ms", "arena_ms", "wall_ms", "llm_calls", "usd"}
    json.dumps(card)


def test_a_reflex_signal_has_no_decision_card(tmp_path: pathlib.Path) -> None:
    engine = build_engine(tmp_path, Clock())
    signal_id = engine.process(escalator()).signal_id
    with pytest.raises(ValueError):
        decision_payload(engine.states()[signal_id], T0)


def test_trace_stats_and_drafts_payloads(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    signal_id = engine.process(elevator()).signal_id
    engine.decide(approve(signal_id))
    trace = trace_payload(engine.trace(signal_id))
    assert trace["hash_ok"] is True and [s["kind"] for s in trace["steps"]][-1] == "approval"
    assert all(set(s) == {"at", "actor", "kind", "detail"} for s in trace["steps"])
    stats = stats_payload(engine.stats())
    contract = {"reflex_closed_today", "awaiting_approval", "median_decision_s", "citizen_update_latency_s", "approval_rate"}
    assert contract <= set(stats)
    for n in range(3):
        sid = engine.process(make_signal(entity=f"E-{n}", observed_at=clock.now, **elevator(f"O-{n}").payload)).signal_id
        engine.decide(approve(sid))
    (draft,) = drafts_payload(engine.drafts.drafts())["drafts"]
    assert set(draft) == {"draft_id", "pattern", "evidence_decisions", "proposed_rule_toml", "expires_days"}
    json.dumps([trace, stats, draft])
