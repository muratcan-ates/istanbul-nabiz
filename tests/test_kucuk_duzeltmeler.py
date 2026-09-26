from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

from nabiz.console.policy import refuses

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
KOLAY_JS = STATIC / "js" / "kolay.js"


def node_json(source: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    url = json.dumps(KOLAY_JS.as_uri())
    script = f"import * as easy from {url};\n{source}"
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_kolay_gas_emergency_shows_187_after_112() -> None:
    markup = node_json(
        "console.log(JSON.stringify(easy.answerMarkup({mode:'redirect',emergency:true,hazard:'gas'})));"
    )
    assert markup.index("tel:112") < markup.index("tel:187") < markup.index("tel:153")
    assert 'class="kolay-call kolay-call-187"' in markup


def test_kolay_other_emergencies_do_not_show_187() -> None:
    markups = node_json(
        "const rows=[{mode:'redirect',emergency:true},{mode:'redirect',emergency:true,hazard:'fire'}];"
        "console.log(JSON.stringify(rows.map(easy.answerMarkup)));"
    )
    assert all("tel:187" not in markup for markup in markups)


def test_kolay_gas_line_matches_the_main_card_text() -> None:
    emergency_text_url = json.dumps((STATIC / "js" / "emergency_text.js").as_uri())
    gas_line, card_text = node_json(
        f"const {{CARD_TEXT}}=await import({emergency_text_url});"
        "console.log(JSON.stringify([easy.GAS_LINE,CARD_TEXT.tr.gas]));"
    )
    assert gas_line in card_text


def test_kolay_loads_handoff_after_its_own_modules() -> None:
    source = (STATIC / "kolay.html").read_text(encoding="utf-8")
    modules = re.findall(r'<script type="module" src="([^"]+)">', source)
    assert modules[:3] == ["/js/kolay.js", "/js/voice.js", "/js/handoff.js"]
    scripts = re.findall(r"<script\b[^>]*>", source)
    assert scripts and all(re.search(r"\bsrc=", script) for script in scripts)


def test_kolay_answer_carries_the_rule_for_handoff() -> None:
    result = node_json(
        "const parts={'.chat-text':{textContent:''},'.chat-final':{innerHTML:''},'.kolay-progress':{hidden:false}};"
        "const li={dataset:{},querySelector:key=>parts[key],classList:{add(){}},setAttribute(){}};"
        "easy.renderFinal(li,{mode:'handoff',rule_id:'layer:handoff',answer_text:'153 ile görüşebilirsiniz.'},'Bilinmiyor');"
        "console.log(JSON.stringify(li.dataset.ruleId));"
    )
    assert result == "layer:handoff"


@pytest.mark.parametrize(
    "question",
    [
        "Ev kirası ne kadar?",
        "Ev kirası yardımı var mı?",
        "Kiraya yardım yapılıyor mu?",
        "Ev kirasına destek",
        "Kirası yüksek evler",
        "Kiracıyım, ev sahibi çıkarmak istiyor",
        "Kiraları kim öder?",
        "Kirasını ödeyemeyen aileler",
        "Kira yardımı başvurusu",
        "Is there rent assistance?",
    ],
)
def test_rent_questions_are_sensitive(question: str) -> None:
    assert refuses(question)


@pytest.mark.parametrize(
    "question",
    [
        "Kiralık ev ilanları nerede?",
        "Bisiklet kiralama nasıl?",
        "İsbike kiralama noktası nerede?",
        "Kiraladığım bisikleti nereye bırakırım?",
        "Araç kiralama",
    ],
)
def test_renting_a_bike_or_a_car_is_not_sensitive(question: str) -> None:
    assert not refuses(question)


def test_one_ai_sentence_everywhere() -> None:
    disclosure = (STATIC / "js" / "disclosure.js").read_text(encoding="utf-8")
    match = re.search(r"const AI_NOTICE = '([^']+)';", disclosure)
    assert match
    ai_notice = match.group(1)
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    page_match = re.search(r'<div class="band" role="note">\s*<p>([^<]+)<span', index, re.S)
    assert page_match
    page_notice = page_match.group(1).strip()
    tr = json.loads((STATIC / "i18n" / "tr.json").read_text(encoding="utf-8"))
    en = json.loads((STATIC / "i18n" / "en.json").read_text(encoding="utf-8"))
    assert ai_notice == page_notice == tr["band.ai"] == tr["fixed.ai_notice"]
    assert en["band.ai"] == en["fixed.ai_notice"]
