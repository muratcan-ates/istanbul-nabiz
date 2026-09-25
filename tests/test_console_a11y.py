"""Accessible console structure and the optional decision-card contract."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
CONSOLE = STATIC / "console.html"


def node_json(expression: str, payload: object | None = None) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = (
        "import fs from 'node:fs';\n"
        "import * as cards from './js/console-cards.js';\n"
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


def test_console_has_one_h1_that_names_the_page_and_no_skipped_levels() -> None:
    source = CONSOLE.read_text(encoding="utf-8")
    matches = re.findall(r"<h([1-6])\b[^>]*>(.*?)</h\1>", source, flags=re.S)
    headings = [(int(level), re.sub(r"<[^>]+>", "", html.unescape(text)).strip()) for level, text in matches]
    assert len([level for level, _ in headings if level == 1]) == 1
    assert headings[0] == (1, "Nabız konsol: simüle operatör")
    assert all(level <= previous + 1 for previous, (level, _) in zip([item[0] for item in headings], headings[1:], strict=False))
    assert '<h2 id="stats-title">Bugün</h2>' in source
    assert re.search(r"<summary>\s*<h3>.*?Refleksle kapananlar", source, flags=re.S)


def test_the_status_region_lives_outside_the_rerendered_card() -> None:
    source = CONSOLE.read_text(encoding="utf-8")
    region = re.search(r'<p[^>]*id="console-status"[^>]*role="status"[^>]*>', source)
    body = source.index('<div id="decision-body">')
    assert region and region.start() < body and 'aria-live="polite"' in region.group(0)
    assert not re.search(r'<span id="ledger-badge"[^>]*aria-live=', source)
    card = node_json("cards.decisionCard(input)", json.loads((STATIC / "mock/console-decision-sig-001.json").read_text()))
    assert 'role="status"' not in card


def test_the_approve_button_is_gated_until_evidence_is_opened() -> None:
    mock = json.loads((STATIC / "mock/console-decision-sig-001.json").read_text(encoding="utf-8"))
    result = node_json(
        "({card: cards.decisionCard(input), actions: ['approve', 'edit', 'reject'].map(cards.gatedAction)})",
        mock,
    )
    assert re.search(r'data-act="approve"[^>]*aria-disabled="true"[^>]*aria-describedby="evidence-gate"', result["card"])
    assert result["actions"] == [True, True, False]
    assert 'id="decision-wait"' in result["card"]
    assert "Vatandaşa yayımlanacak metin:" in result["card"]


def test_reason_codes_are_turkish_labels_and_compose_under_the_limit() -> None:
    result = node_json(
        "({codes: cards.REASON_CODES, long: cards.composeReason("
        "'evidence_current', 'x'.repeat(240)), empty: cards.composeReason(null, '')})"
    )
    labels = [item["label"] for group in result["codes"].values() for item in group]
    assert len(labels) == 10
    assert all("-" not in label and "–" not in label and "—" not in label and "kanca" not in label.lower() for label in labels)
    assert len(result["long"]) <= 280
    assert result["empty"] is None


def test_disabled_approve_is_not_faded_and_console_css_adds_no_unguarded_motion() -> None:
    css = (STATIC / "css/console.css").read_text(encoding="utf-8")
    rule = re.search(r'\.actions \.btn\[aria-disabled="true"\]\s*\{([^}]+)\}', css)
    assert rule
    for declaration in (
        "opacity: 1",
        "background: var(--surface-sunken)",
        "color: var(--text-muted)",
        "border-color: var(--border-strong)",
    ):
        assert declaration in rule.group(1)
    guarded_motion = re.findall(r"@media \(prefers-reduced-motion: no-preference\) \{[^\n]*\}", css)
    without_guarded_motion = css
    for block in guarded_motion:
        without_guarded_motion = without_guarded_motion.replace(block, "", 1)
    assert not re.search(r"\b(?:animation|transition)\s*:", without_guarded_motion)
    assert ".queue-item:focus-visible { outline-width: 3px; }" in css
    assert "@media (max-width: 480px)" in css


def test_the_card_draws_the_lifecycle_fields_only_when_they_are_present() -> None:
    mock = json.loads((STATIC / "mock/console-decision-sig-001.json").read_text(encoding="utf-8"))
    result = node_json(
        """(() => {
          const plain = cards.decisionCard(input);
          const empty = {
            ...input,
            confidence: {...input.confidence, uncertainty: []},
            receipt: {wall_ms: null, llm_calls: null, usd: null},
            folded_repeats: 0,
            expires_at: null,
            panel: null,
            stakes: null,
          };
          const base = {
            ...input,
            confidence: {...input.confidence, uncertainty: [{
              code: 'stale_source', label: 'Kaynak eski', detail: 'Yeni kayıt bekleniyor'
            }]},
            receipt: {reflex_ms: null, arena_ms: 80, wall_ms: 125.5, llm_calls: 0, usd: 0.0125},
            folded_repeats: 2,
            expires_at: '2026-09-25T10:45:00+03:00',
            panel: {verdict: 'publish', votes: {support: 2, oppose: 0, conditional: 1}},
            stakes: {required_level: 'high'},
          };
          return {
            plain,
            empty: cards.decisionCard(empty),
            pending: cards.decisionCard(base),
            expired: cards.decisionCard({...base, signal: {...base.signal, status: 'expired'}}),
            executed: cards.decisionCard({...base, signal: {...base.signal, status: 'executed'}}),
            queue: cards.queueItem({
              signal_id: 'x', kind: 'parking_full', title: 'Otopark', severity: 'warning', path: 'arena',
              status: 'awaiting_approval', created_at: '2026-09-25T10:00:00+03:00', summary: 'Vatandaş özeti',
              operator_summary: 'Operatör özeti', folded_repeats: 2, expires_at: '2026-09-25T10:45:00+03:00'
            }, false),
          };
        })()""",
        mock,
    )
    assert result["empty"] == result["plain"]
    absent = ("Neden emin değilim", "tekrar katlandı", "Süresi doldu", "Uygulandı (simülasyon)", "Süre:")
    assert all(text not in result["plain"] for text in absent)
    for rendered in (result["expired"], result["executed"]):
        assert "Neden emin değilim" in rendered
        assert "2 tekrar katlandı" in rendered
        assert "Süre:" in rendered and "model çağrısı: 0" in rendered and "USD" in rendered
        assert "Panel önerisi: yayımla (destek 2, karşı 0, şartlı 1)" in rendered and "Gereken güven: yüksek" in rendered
        assert "publish" not in rendered.replace('value="publish', "")
    assert "Süresi doldu" in result["expired"] and "Uygulandı (simülasyon)" in result["executed"]
    assert "Son karar:" in result["pending"]
    assert "Son karar:" not in result["expired"] and "Son karar:" not in result["executed"]
    assert "Operatör özeti" in result["queue"] and "Vatandaş özeti" not in result["queue"]
    assert "2 tekrar katlandı" in result["queue"] and "Son karar:" in result["queue"]
