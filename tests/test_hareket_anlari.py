"""Contracts for E47's event driven console motion."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src/nabiz/console/static"
JS = STATIC / "js/console_flow.js"
CSS_FILES = (STATIC / "css/console_flow.css", STATIC / "css/console_day.css")
DASHES = (chr(0x2014), chr(0x2013))


def flow_examples() -> dict[str, dict]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = """
      import { flowFor } from './js/console_flow.js';
      const flows = {
        approve: flowFor('approve', true),
        edit: flowFor('edit', true),
        approveWithoutCitizenCard: flowFor('approve', true, false),
        reject: flowFor('reject', true),
        defer: flowFor('defer', true),
        pending: flowFor(null, true),
        empty: flowFor(null, false),
      };
      process.stdout.write(JSON.stringify(flows));
    """
    result = subprocess.run(
        [node, "--experimental-default-type=module", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        cwd=STATIC,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_flow_for_matches_the_ledger_and_citizen_paths() -> None:
    flows = flow_examples()
    all_steps = ["signal", "arena", "human", "ledger", "citizen"]
    ledger_steps = all_steps[:4]
    assert flows["approve"] == {
        "lit": all_steps,
        "stop": "citizen",
        "citizen": "published",
        "message": "Onaylandı: karar deftere yazıldı, metin vatandaş yüzünde yayımlandı.",
    }
    assert flows["edit"] == flows["approve"]
    assert flows["approveWithoutCitizenCard"] == {
        "lit": ledger_steps,
        "stop": "ledger",
        "citizen": "not_published",
        "message": "Onaylandı: karar deftere yazıldı; vatandaş yüzünde yayımlanmadı.",
    }
    assert flows["reject"] == {
        "lit": ledger_steps,
        "stop": "ledger",
        "citizen": "not_published",
        "message": "Reddedildi: karar gerekçesiyle deftere yazıldı; vatandaşa yayımlanmadı.",
    }
    assert flows["defer"] == {
        "lit": ledger_steps,
        "stop": "ledger",
        "citizen": None,
        "message": "Ertelendi: kart yeniden karara gelecek.",
    }
    assert flows["pending"] == {
        "lit": all_steps[:2],
        "stop": "human",
        "citizen": None,
        "message": "İnsan onayı bekliyor.",
    }
    assert flows["empty"] == {"lit": [], "stop": None, "citizen": None, "message": ""}


def _motion_blocks(source: str) -> list[tuple[int, int]]:
    blocks = []
    pattern = re.compile(r"@media\s*\(prefers-reduced-motion:\s*no-preference\)\s*\{")
    for match in pattern.finditer(source):
        depth = 1
        index = match.end()
        while index < len(source) and depth:
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
            index += 1
        blocks.append((match.end(), index - 1))
    return blocks


@pytest.mark.parametrize("path", CSS_FILES)
def test_motion_rules_are_opt_in_finite_and_tokenized(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    motion_declarations = re.finditer(r"\b(?:transition|animation)(?:-[a-z-]+)?\s*:", source)
    blocks = _motion_blocks(source)
    for declaration in motion_declarations:
        assert any(start <= declaration.start() < end for start, end in blocks), declaration.group(0)
    assert "infinite" not in source.lower()
    assert not re.search(r"#[0-9a-f]{3,8}\b|\b(?:rgb|rgba|hsl|hsla)\s*\(", source, flags=re.I)
    if path.name == "console_flow.css":
        assert ".flow-connector.is-filled > span { transform: scaleX(1); }" in source


def test_flow_module_and_console_wiring_stay_local_and_non_looping() -> None:
    source = JS.read_text(encoding="utf-8")
    page = (STATIC / "console.html").read_text(encoding="utf-8")
    service_worker = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert source.count("setInterval") == 0
    assert "requestAnimationFrame" not in source
    assert not re.search(r"addEventListener\s*\(\s*['\"]scroll", source)
    assert "nabiz:decided" in source
    assert "CustomEvent" not in source
    assert page.count('<script type="module" src="/js/console_flow.js"></script>') == 1
    shell = service_worker.split("const SHELL = [", 1)[1].split("];", 1)[0]
    assert "console_flow" not in shell
    for text in (source, page):
        for dash in DASHES:
            assert dash not in text


def test_day_summary_replays_only_for_a_changed_number_without_live_announcement() -> None:
    source = (STATIC / "js/console_day.js").read_text(encoding="utf-8")
    style = (STATIC / "css/console_day.css").read_text(encoding="utf-8")
    assert "displayedDecisionCount !== humanDecisions" in source
    assert "is-number-entering" in source
    assert "nabiz:decided" in source
    assert not re.search(r"brief-value[^\n]*aria-live", source + style)
    assert "prefers-reduced-motion: no-preference" in style
