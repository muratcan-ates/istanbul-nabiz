"""The E46 decision desk keeps the operator's queue, choices and ledger summary clear."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "nabiz" / "console" / "static"


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


def test_the_desk_comes_first() -> None:
    source = (STATIC / "console.html").read_text(encoding="utf-8")
    desk_at = source.index('<section class="desk"')
    today_at = source.index('id="today"')
    desk = source[desk_at:today_at]
    assert desk_at < today_at
    assert 'id="desk-title"' in desk and 'id="queue"' in desk and 'id="decision"' in desk


def test_the_decision_card_has_one_primary_and_a_quiet_reject() -> None:
    payload = json.loads((STATIC / "mock" / "console-decision-sig-001.json").read_text(encoding="utf-8"))
    card = node_json("cards.decisionCard(input)", payload)
    assert card.count('class="btn btn-primary"') == 1
    assert re.search(r'data-act="approve"[^>]*aria-disabled="true"[^>]*aria-describedby="evidence-gate"', card)
    reject = re.search(r'<button[^>]*data-act="reject"[^>]*>(.*?)</button>', card)
    assert reject and 'class="btn btn-danger"' not in reject.group(0) and "Reddet" in reject.group(1)
    assert re.search(r'<button[^>]*class="btn btn-quiet"[^>]*data-act="edit"', card)
    assert re.search(r'<button[^>]*class="btn btn-quiet"[^>]*data-act="defer"', card)


def test_the_actions_bar_is_sticky_and_calm() -> None:
    css = (STATIC / "css" / "console.css").read_text(encoding="utf-8")
    bar = re.search(r"\.actions-bar\s*\{([^}]+)\}", css)
    disabled = re.search(r'\.actions \.btn\[aria-disabled="true"\]\s*\{([^}]+)\}', css)
    assert bar and "position: sticky" in bar.group(1) and "bottom: 0" in bar.group(1)
    assert disabled and "opacity: 1" in disabled.group(1)


def test_reasons_open_inline_for_reject_and_defer() -> None:
    script = (STATIC / "js" / "console.js").read_text(encoding="utf-8")
    assert "submitDecision(act, btn)" in script
    assert "(action === 'reject' || action === 'defer') && !code" in script
    assert "more.open = true" in script and "error.hidden = false" in script
    assert "Ret ve erteleme için gerekçe kodu seçin." in script


def test_deadline_says_what_it_is() -> None:
    source = (STATIC / "js" / "console-cards.js").read_text(encoding="utf-8")
    assert source.count("Karar son tarihi:") == 2
    assert "Son karar:" not in source


def test_the_brief_counts_only_human_rulings() -> None:
    script = (STATIC / "js" / "console_day.js").read_text(encoding="utf-8")
    for field in ("data.today.approved", "data.today.rejected", "data.today.deferred"):
        assert field in script
    assert "if (humanDecisions === 0)" in script
    assert "Bugün henüz insan kararı yok." in script
    assert "reflex_closed" not in script
    assert 'class="brief-impact is-risk"' in script
    assert "--bad" not in (STATIC / "css" / "console_day.css").read_text(encoding="utf-8")


def test_the_brief_footnote_names_the_ledger_and_its_seal() -> None:
    script = (STATIC / "js" / "console_day.js").read_text(encoding="utf-8")
    assert "Kaynak: karar defteri" in script
    assert "mühür doğrulandı" in script and "mühür DOĞRULANAMADI" in script
    assert "Kişi bazında metrik yok." in script


def test_system_panels_live_under_one_disclosure() -> None:
    source = (STATIC / "console.html").read_text(encoding="utf-8")
    day = source.index('id="day"')
    disclosure = source.index('id="system-more"')
    today = source.index('id="today"')
    health = source.index('id="approval-health"')
    end = source.index("</details>", disclosure)
    assert day < disclosure < today < health < end


def test_system_summary_does_not_claim_a_disabled_chat_switch_is_open() -> None:
    script = (STATIC / "js" / "console.js").read_text(encoding="utf-8")
    assert "toggle.getAttribute('aria-disabled') === 'true'" in script
    assert "checked === null" in script
    assert "Vatandaş sohbeti durumu okunamadı" in script


def test_drills_are_behind_a_disclosure() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    module = json.dumps((STATIC / "js" / "console_drill.js").as_uri())
    script = (
        "globalThis.window = {location: {search: '', origin: 'http://localhost'}};\n"
        f"const {{drillControls, DRILL_KINDS}} = await import({module});\n"
        "console.log(JSON.stringify({controls: drillControls(), kinds: DRILL_KINDS.map((item) => item.kind)}));\n"
    )
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    controls = rendered["controls"]
    assert controls.startswith('<details class="more nx-drill"><summary>')
    assert all(f'data-nx-drill="{kind}"' in controls for kind in rendered["kinds"])


def test_console_motion_is_guarded_and_one_line() -> None:
    for path in (STATIC / "css" / "console.css", STATIC / "css" / "console_day.css"):
        css = path.read_text(encoding="utf-8")
        guarded = re.findall(r"@media \(prefers-reduced-motion: no-preference\) \{[^\n]*\}", css)
        unguarded = css
        for block in guarded:
            unguarded = unguarded.replace(block, "", 1)
        assert not re.search(r"\b(?:animation|transition)\s*:", unguarded)
        assert not re.search(r"#[\da-fA-F]{3,8}\b", css)
        for line in css.splitlines():
            if "--bad" in line:
                assert ".is-critical" in line or ".is-bad" in line
