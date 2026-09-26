"""The console port's extension for G26: two ledger kinds, expiry on a queue read, the section nav,
the rules section with its dialog, and the renderers behind them.

Every Python test runs on a fixed clock and a ledger in ``tmp_path``; the page tests read the
static files, and the renderer tests import the pure JS modules in node (skipped without node).
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT
from nexus_helpers import Clock, approve, build_engine, make_signal

from nabiz.console.nexus_port import NexusConsole, describe_step
from nabiz.console.signals import Incoming
from nexus_core.engine import default_evidence
from nexus_core.ledger import GENESIS, EntryKind, Ledger, canonical, entry_hash
from nexus_core.signals import Signal
from nexus_core.state import replay

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
CONSOLE = STATIC / "console.html"
DASHES = ("–", "—")


def node_json(expression: str, payload: object | None = None) -> object:
    """Copied from tests/test_console_a11y.py, with the rules module imported too."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = (
        "import fs from 'node:fs';\n"
        "import * as cards from './js/console-cards.js';\n"
        "import * as rules from './js/console_rules.js';\n"
        "const input = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
        f"const output = {expression};\n"
        "console.log(JSON.stringify(output));\n"
    )
    result = subprocess.run(
        [node, "--experimental-default-type=module", "--input-type=module", "-e", script],
        input=json.dumps(payload or {}),
        capture_output=True,
        text=True,
        cwd=STATIC,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def long_outage(clock: Clock, n: int = 9) -> Signal:
    return make_signal(
        "long_outage",
        entity=f"metro-equipment:ASN-{n}",
        observed_at=clock.now,
        station="Kartal",
        outage_id=f"ASN-{n}@2026-09-20",
        outage_hours=120.0,
        text="Kartal (M4): asansör kullanılamıyor.",
    )


def test_entry_kinds_keep_their_values_and_add_two() -> None:
    expected = {
        "SIGNAL": "signal_received",
        "ROUTED": "routed",
        "REFLEX_CLOSED": "reflex_closed",
        "REFLEX_FAILED": "reflex_failed",
        "ARENA_DRAFTED": "arena_drafted",
        "APPROVAL": "approval",
        "EXPIRED": "expired",
        "RULE_ADOPTED": "rule_adopted",
        "RULE_REVOKED": "rule_revoked",
        "CHAT_PAUSED": "chat_paused",
        "CHAT_RESUMED": "chat_resumed",
    }
    assert {name: EntryKind[name].value for name in expected} == expected


def test_the_hash_formula_did_not_change() -> None:
    detail = canonical({"rule_id": "R-101", "reason": "deneme"})
    fields = (1, "2026-09-25T09:00:00+00:00", None, None, "Simüle operatör (simule-operator)", "rule_revoked", detail, GENESIS)
    assert entry_hash(fields) == "ff187fbedbe07ab8567fbbaa4711f0be59a18177c30e2a71610f2b15fa7950e5"


def test_an_old_ledger_still_verifies(tmp_path: pathlib.Path) -> None:
    ledger = Ledger(tmp_path / "nexus.db", clock=Clock())
    for kind in ("approval", "rule_adopted", "chat_pause"):  # plain-text kinds, E20's interim one included
        ledger.append(kind, actor="deneme", detail={"n": kind})
    ledger.append(EntryKind.CHAT_PAUSED, actor="deneme", detail={"paused": True})
    ledger.append(EntryKind.CHAT_RESUMED, actor="deneme", detail={"paused": False})
    assert ledger.verify().ok is True
    assert [e.kind for e in ledger.entries()][-2:] == ["chat_paused", "chat_resumed"]
    assert replay(ledger.entries()) == {}


def test_a_queue_read_expires_an_unanswered_card(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    port = NexusConsole(engine, nabiz=None, recorded=lambda: None, offline=False, clock=clock)  # type: ignore[arg-type]
    port.ingest_every_s = 0  # no source is read
    waiting, deferred = port._process_all(
        [Incoming(s, default_evidence(s)) for s in (long_outage(clock), long_outage(clock, 10))]
    )
    assert engine.states()[waiting].status == "awaiting_approval"
    engine.decide(approve(deferred, action="defer", reason="Yarın doğrulanacak"))
    clock.advance(hours=73)
    rows = {i["signal_id"]: i for i in asyncio.run(port.queue())["items"]}
    assert rows[waiting]["status"] == "expired"
    assert rows[deferred]["status"] == "deferred"
    last = engine.ledger.entries(kinds=[EntryKind.EXPIRED])[-1]
    assert last.signal_id == waiting and last.actor == "system:timeout"
    assert engine.verify().ok is True


def test_the_trace_names_an_expiry_in_turkish() -> None:
    assert describe_step("expired", {}).startswith("Süresi doldu")
    assert describe_step("bilinmeyen", {}) == "bilinmeyen"


def html() -> str:
    return CONSOLE.read_text(encoding="utf-8")


def test_the_console_nav_lists_eight_sections_in_order() -> None:
    source = html()
    nav = re.search(r'<nav class="console-nav" aria-label="Konsol bölümleri">(.*?)</nav>', source, re.S)
    assert nav is not None
    links = re.findall(r'<a href="(#[\w-]+)">([^<]+)</a>', nav.group(1))
    assert [h for h, _ in links] == [
        "#today", "#queue", "#report-map", "#citizen-requests", "#rules", "#nx-organs", "#approval-health", "#service-receipt",
    ]  # fmt: skip
    assert [t for _, t in links] == [
        "Bugün", "Sinyal kutusu", "Bildirim haritası", "Talepler", "Kurallar", "Karar motoru", "Sağlık", "Maliyet",
    ]  # fmt: skip
    queue_title = re.search(r'<h2 id="queue-title">([^<]+)</h2>', source)
    assert queue_title is not None and dict((h, t) for h, t in links)["#queue"] == queue_title.group(1)
    skip = source.index('<a class="skip-link" href="#main">')
    assert skip < source.index('<nav class="console-nav"')
    assert '<section id="today" aria-labelledby="stats-title">' in source and '<h2 id="stats-title">Bugün</h2>' in source


def test_the_console_nav_stays_visible_below_the_topbar() -> None:
    css = (STATIC / "css" / "console.css").read_text(encoding="utf-8")
    rule = re.search(r"\.console-nav \{([^}]*)\}", css)
    assert rule is not None
    body = rule.group(1)
    assert "position: sticky" in body and "z-index: var(--z-sticky)" in body
    top = re.search(r"top:\s*([^;]+);", body)
    assert top is not None and top.group(1).strip() != "0"
    assert "var(--console-topbar-h" in top.group(1) or "var(--topbar-h)" in top.group(1)
    padding = re.search(r"html \{[^}]*scroll-padding-top:([^;]+);", css)
    assert padding is not None and "--console-nav-h" in padding.group(1)
    assert not re.search(r"section\[id\][^{]*\{[^}]*scroll-margin-top", css), "scroll-padding and scroll-margin would add up"
    script = (STATIC / "js" / "console.js").read_text(encoding="utf-8")
    desk = (STATIC / "js" / "console_desk.js").read_text(encoding="utf-8")
    assert "from './console_desk.js'" in script
    assert "ResizeObserver" in desk and "--console-topbar-h" in desk


def test_panel_sections_are_not_precreated() -> None:
    # Wave-1 (DECISIONS #31) fixed the order of its panels with one placeholder each; the rest
    # are still built by their own modules, and the nav hides a link whose target is missing.
    source = html()
    for panel in ("nx-organs", "approval-health", "day"):
        assert source.count(f'id="{panel}"') == 1
    for panel in ("service-receipt", "chat-pause"):
        assert f'id="{panel}"' not in source


def test_the_rules_section_and_dialog_are_labelled() -> None:
    source = html()
    assert '<section id="rules" aria-labelledby="rules-title">' in source
    assert '<h2 id="rules-title">Kurallar</h2>' in source
    assert '<dialog id="revoke-dialog"' in source and 'maxlength="280"' in source
    assert '<link rel="modulepreload" href="/js/console_rules.js">' in source
    assert '<link rel="modulepreload" href="/js/console_desk.js">' in source
    assert source.count('<script type="module" src="/js/console.js"></script>') == 1
    assert 'src="/js/console_rules.js"' not in source  # imported by console.js, never a second entry
    script = (STATIC / "js" / "console.js").read_text(encoding="utf-8")
    assert "from './console_rules.js'" in script
    assert all(word in script for word in ("nabiz:decided", "nabiz:ledger-changed"))
    assert "MutationObserver" in (STATIC / "js" / "console_desk.js").read_text(encoding="utf-8")
    rules = (STATIC / "js" / "console_rules.js").read_text(encoding="utf-8")
    assert "showModal" in rules and "'close'" in rules and "'cancel'" in rules


RULES = {
    "mission": {
        "rule_id": "R-01", "origin": "mission", "path": "arena", "path_label": "insan onayı", "status": "active",
        "days_left": 29, "stale": False, "age_days": 0, "revocable": False, "matched_today": 1, "reflex_today": 0,
        "sentence": "Eğer ekipman arızası sinyalinde ekipman türü asansör ise: insan onayıyla adımsız alternatifi yayımla.",
        "mission": {"id": "erisilebilir-yolculuk", "title": "Erişilebilir yolculuk", "source": "erisilebilir_yolculuk.toml"},
    },
    "learned": {
        "rule_id": "R-101", "origin": "learned", "path": "reflex", "path_label": "refleks", "status": "active",
        "days_left": 30, "stale": False, "age_days": 0, "revocable": True, "matched_today": 0, "reflex_today": 0,
        "sentence": "Eğer ekipman arızası sinyalinde ekipman türü asansör ise: Adımsız alternatif metnini yayımla.",
        "mission": None, "reviewed_at": "2026-09-28T09:00:00+00:00", "adopted_reason": "Üç onay", "evidence_count": 3,
        "revoked_at": None, "revoke_reason": None,
    },
}  # fmt: skip


def test_rule_card_renderers() -> None:
    revoked = {**RULES["learned"], "status": "revoked", "revocable": False, "days_left": None,
               "revoked_at": "2026-09-29T09:00:00+00:00", "revoke_reason": "Deneme bitti"}  # fmt: skip
    result = node_json(
        """({
          countdown: [
            {status: 'revoked'}, {status: 'expired'}, {status: 'not_started'},
            {status: 'active', days_left: 0}, {status: 'active', days_left: 12}, {status: 'active', days_left: null},
          ].map(rules.countdownText),
          stale: rules.staleText({stale: true, age_days: 9}),
          fresh: rules.staleText({stale: false, age_days: 1}),
          mission: rules.ruleCard(input.mission),
          learned: rules.ruleCard(input.learned),
          revoked: rules.ruleCard(input.revoked),
          empty: rules.rulesList({rules: []}),
        })""",
        {**RULES, "revoked": revoked},
    )
    assert result["countdown"] == ["geri alındı", "süresi doldu", "henüz başlamadı", "bugün bitiyor", "12 gün kaldı", "süresiz"]
    assert "bayat" in result["stale"] and "9" in result["stale"] and result["fresh"] == ""
    assert "data-revoke" not in result["mission"] and "Görev dosyasındaki kural" in result["mission"]
    assert 'data-revoke="R-101"' in result["learned"] and "Geri al" in result["learned"]
    assert "data-revoke" not in result["revoked"] and "Deneme bitti" in result["revoked"]
    assert "Kural yok." in result["empty"]
    for text in result.values():
        assert not any(d in str(text) for d in DASHES)


def test_console_cards_name_citizen_reports_and_expiry() -> None:
    result = node_json(
        """({
          queue: cards.queueItem({signal_id: 'x', kind: 'citizen_report', title: 'Bildirim', severity: 'info', path: 'arena',
            status: 'awaiting_approval', created_at: '2026-09-25T10:00:00+03:00', summary: 'Özet'}, false),
          trace: cards.traceList({steps: [{kind: 'expired', at: '2026-09-28T09:00:00+00:00', actor: 'system:timeout',
            detail: 'Süresi doldu'}], hash_ok: true}),
        })"""
    )
    assert "vatandaş bildirimi" in result["queue"]
    assert "süre doldu" in result["trace"]


def test_a_receipt_says_the_price_is_unknown_only_when_a_model_was_called() -> None:
    mock = json.loads((STATIC / "mock/console-decision-sig-001.json").read_text(encoding="utf-8"))
    result = node_json(
        """({
          called: cards.decisionCard({...input, receipt: {wall_ms: 10, llm_calls: 2, usd: null}}),
          none: cards.decisionCard({...input, receipt: {wall_ms: 10, llm_calls: 0, usd: null}}),
          priced: cards.decisionCard({...input, receipt: {wall_ms: 10, llm_calls: 2, usd: 0.04}}),
        })""",
        mock,
    )
    assert "fiyat tanımsız" in result["called"]
    assert "fiyat tanımsız" not in result["none"] and "fiyat tanımsız" not in result["priced"]
