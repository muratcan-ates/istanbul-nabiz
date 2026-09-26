"""nabiz.console.rules_api: the rule registry in Turkish, and revoking a learned rule over HTTP.

Every test runs on a fixed clock and a ledger in ``tmp_path``; no source is read and no model is
called. The app is the two console routers over a :class:`NexusConsole`, as the integrator wires it.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import re
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nexus_helpers import Clock, approve, build_engine, elevator, escalator, make_signal

from nabiz.console.nexus_port import KIND_TR, NexusConsole
from nabiz.console.operator import operator_routes
from nabiz.console.ports import Ports
from nabiz.console.rules_api import rule_sentence, rules_routes
from nexus_core.engine import NexusEngine
from nexus_core.ledger import EntryKind
from nexus_core.missions import MissionRule
from nexus_core.signals import Signal

R01 = (
    "Eğer ekipman arızası sinyalinde ekipman türü asansör ve alternatif istasyon bilgisi var ise: "
    "insan onayıyla adımsız alternatif metnini yayımla."
)
DASHES = ("–", "—")


# Copied from tests/test_nexus_core_rule_drafts.py (a test module is not imported from another).
def outage(n: int, when: dt.datetime) -> Signal:
    """An elevator outage at its own elevator: separate elevators, so no repeat trigger fires."""
    return make_signal(entity=f"M2-TAKSIM-ASN-{n:02d}", observed_at=when, **elevator(f"ASN-{n:02d}@2026-09").payload)


def spread(engine: NexusEngine, clock: Clock, count: int, *, start: int = 0, action: str = "approve") -> list[str]:
    """``count`` outages, each ruled ``action`` by the operator, a day apart."""
    ids = []
    for n in range(start, start + count):
        signal_id = engine.process(outage(n, clock.now)).signal_id
        engine.decide(approve(signal_id, action, "" if action == "approve" else "Alternatif uygun değil"))
        ids.append(signal_id)
        clock.advance(days=1)
    return ids


def client(ports: Ports) -> TestClient:
    app = FastAPI()
    app.state.ports = ports
    app.include_router(operator_routes)
    app.include_router(rules_routes)
    return TestClient(app)


def wired(tmp_path: pathlib.Path) -> tuple[Clock, NexusEngine, TestClient]:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    port = NexusConsole(engine, nabiz=None, recorded=lambda: None, offline=False, ingest_every_s=0, clock=clock)  # type: ignore[arg-type]
    return clock, engine, client(Ports(console=port))


def rules(api: TestClient) -> dict[str, dict[str, Any]]:
    response = api.get("/api/console/rules")
    assert response.status_code == 200, response.text
    return {r["rule_id"]: r for r in response.json()["rules"]}


def adopt_one(engine: NexusEngine, clock: Clock, api: TestClient) -> str:
    spread(engine, clock, 3)
    (draft,) = engine.drafts.drafts()
    response = api.post(
        f"/api/console/rule-drafts/{draft.draft_id}/adopt", json={"reason": "Üç ayrı arızada aynı metin onaylandı."}
    )
    assert response.status_code == 200, response.text
    return draft.draft_id


def test_the_registry_lists_every_mission_rule_in_file_order(tmp_path: pathlib.Path) -> None:
    _, engine, api = wired(tmp_path)
    body = api.get("/api/console/rules").json()
    mission_rules = [r for r in body["rules"] if r["origin"] == "mission"]
    expected = [rule.id for mission in engine.router.missions for rule in mission.rules]
    assert [r["rule_id"] for r in mission_rules] == expected
    assert {f"R-0{n}" for n in range(1, 10)} <= set(expected)
    assert body["counts"]["mission"] == len(expected) and body["counts"]["learned"] == 0
    for row in mission_rules:
        sentence = row["sentence"]
        assert row["revocable"] is False
        assert sentence.startswith("Eğer") and " ise" in sentence
        assert not any(d in sentence for d in DASHES) and "ETA" not in sentence
        assert re.search(r"\b[a-z]+_[a-z_]+\b", sentence) is None, sentence
        assert ("insan onayıyla" in sentence) == (row["path"] == "arena"), sentence


def test_rule_sentence_speaks_turkish_and_shows_unknown_fields_raw(tmp_path: pathlib.Path) -> None:
    _, _, api = wired(tmp_path)
    table = rules(api)
    assert table["R-01"]["sentence"] == R01
    assert "arıza süresi (saat) 24 üstünde" in table["R-06"]["sentence"]
    unknown = MissionRule.model_validate(
        {
            "id": "R-X",
            "path": "reflex",
            "when": {"kind": "equipment_fault", "conditions": [{"field": "foo_bar", "op": "gt", "value": 3}]},
            "then": {"action": "publish_card", "card_template": "metin"},
        }
    )
    sentence = rule_sentence(unknown, KIND_TR)
    assert "foo_bar 3 üstünde" in sentence and "insan onayıyla" not in sentence


def test_countdown_and_staleness_follow_the_clock(tmp_path: pathlib.Path) -> None:
    clock, _, api = wired(tmp_path)
    first = rules(api)["R-01"]
    assert first["days_left"] == 29 and first["stale"] is False
    clock.advance(days=6)
    assert rules(api)["R-01"]["stale"] is False
    clock.advance(days=2)
    later = rules(api)["R-01"]
    assert later["stale"] is True and later["age_days"] == 8 and later["days_left"] == 21


def test_counters_are_per_rule_and_per_istanbul_day(tmp_path: pathlib.Path) -> None:
    clock, engine, api = wired(tmp_path)
    # Two outages of one escalator, minutes apart: two signals (same instant and entity would be one id).
    engine.process(escalator(outage_id="YM-07@a", observed_at=clock.now))
    engine.process(escalator(outage_id="YM-07@b", observed_at=clock.advance(minutes=5)))
    engine.process(elevator(observed_at=clock.now))
    table = rules(api)
    assert (table["R-03"]["matched_today"], table["R-03"]["reflex_today"]) == (2, 2)
    assert (table["R-01"]["matched_today"], table["R-01"]["reflex_today"]) == (1, 0)
    clock.advance(days=1)
    assert all(r["matched_today"] == 0 and r["reflex_today"] == 0 for r in rules(api).values())


def test_adopt_then_revoke_seals_the_ledger_and_the_router_stops(tmp_path: pathlib.Path) -> None:
    clock, engine, api = wired(tmp_path)
    adopt_one(engine, clock, api)
    first = api.get("/api/console/rules").json()["rules"][0]
    assert first["rule_id"] == "R-101" and first["origin"] == "learned" and first["revocable"] is True
    assert first["days_left"] == 30 and first["evidence_count"] == 3 and first["status"] == "active"
    assert engine.router.match(outage(9, clock.now))[0].id == "R-101"

    reason = "Alternatif istasyonun asansörü de sık arızalanıyor."
    response = api.post("/api/console/rules/R-101/revoke", json={"reason": reason})
    assert response.status_code == 200, response.text
    last = engine.ledger.entries()[-1]
    assert response.json() == {
        "rule_id": "R-101",
        "status": "revoked",
        "revoked_at": last.at.isoformat(),
        "ledger_entry_id": last.id,
    }
    assert last.kind == EntryKind.RULE_REVOKED
    after = rules(api)["R-101"]
    assert after["status"] == "revoked" and after["revoke_reason"] == reason and after["revocable"] is False
    assert engine.verify().ok is True
    assert engine.router.match(outage(9, clock.now))[0].id == "R-01"


def test_a_revoked_draft_does_not_come_back_by_itself(tmp_path: pathlib.Path) -> None:
    clock, engine, api = wired(tmp_path)
    draft_id = adopt_one(engine, clock, api)
    assert api.post("/api/console/rules/R-101/revoke", json={"reason": "Deneme bitti."}).status_code == 200
    drafts = api.get("/api/console/rule-drafts").json()
    assert draft_id not in str(drafts)
    clock.advance(hours=1)
    spread(engine, clock, 3, start=10)
    drafts = api.get("/api/console/rule-drafts").json()
    assert draft_id in str(drafts)


def test_revoke_refuses_what_it_must(tmp_path: pathlib.Path) -> None:
    clock, engine, api = wired(tmp_path)
    adopt_one(engine, clock, api)

    def revoke(rule_id: str, reason: str) -> tuple[int, dict[str, Any]]:
        response = api.post(f"/api/console/rules/{rule_id}/revoke", json={"reason": reason})
        return response.status_code, response.json()

    for blank in ("", "   "):
        assert revoke("R-101", blank) == (400, {"error": "reason_required", "message": "Kuralı geri almak için gerekçe zorunlu."})
    status, body = revoke("R-01", "Görev kuralı")
    assert status == 409 and body["message"].startswith("Görev dosyasındaki kural")
    assert revoke("R-999", "Yok") == (404, {"error": "not_found", "message": "Bu kayıt bulunamadı."})
    assert revoke("R-101", "x" * 281)[0] == 422
    assert revoke("R 1", "Boşluklu kimlik")[0] == 422  # outside ID_PATTERN: FastAPI refuses the path
    assert revoke("R-101", "İlk geri alma")[0] == 200
    assert revoke("R-101", "İkinci kez") == (409, {"error": "conflict", "message": "Bu kural zaten geri alınmış."})


def test_revoking_an_expired_learned_rule_is_a_conflict(tmp_path: pathlib.Path) -> None:
    clock, engine, api = wired(tmp_path)
    adopt_one(engine, clock, api)
    clock.advance(days=31)
    assert rules(api)["R-101"]["status"] == "expired"
    response = api.post("/api/console/rules/R-101/revoke", json={"reason": "Geç kaldık"})
    assert response.status_code == 409 and "süresi dolmuş" in response.json()["message"]


@pytest.mark.parametrize(("method", "path"), [("get", "/api/console/rules"), ("post", "/api/console/rules/R-101/revoke")])
def test_an_unwired_console_answers_503(method: str, path: str) -> None:
    api = client(Ports())
    response = api.get(path) if method == "get" else api.post(path, json={"reason": "Deneme"})
    assert response.status_code == 503 and response.json()["error"] == "not_wired"
