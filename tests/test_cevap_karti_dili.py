from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
CARD_JS = STATIC / "js" / "answer_card.js"
ACTION_JS = STATIC / "js" / "answer_actions.js"
CARD_CSS = STATIC / "css" / "answer_card.css"


def _node_json(tmp_path: Path, body: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    harness = tmp_path / "answer_actions_harness.mjs"
    harness.write_text(body, encoding="utf-8")
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _card_harness(tmp_path: Path, body: str) -> object:
    return _node_json(
        tmp_path,
        f"const card = await import({json.dumps(CARD_JS.as_uri())});\n"
        f"const actions = await import({json.dumps(ACTION_JS.as_uri())});\n{body}",
    )


def test_an_answer_card_has_no_filled_primary(tmp_path: Path) -> None:
    value = _card_harness(
        tmp_path,
        "const citations=[{source:'metro_status',mode:'recorded',observed_at:'2026-07-27T09:27:00+03:00'}];"
        "const answer=card.renderAnswerCard({mode:'answer',answer_text:'M4 açık.',citations});"
        "const quote=card.renderAnswerCard({mode:'quote_only',citations:[{source:'local:knowledge',url:'https://example.invalid',"
        "title:'Hizmet sayfası',quote:'Kaynak cümlesi'}]});"
        "console.log(JSON.stringify({answer,quote}));",
    )
    for html in value.values():
        assert "btn-primary" not in html
        assert 'class="btn btn-quiet ac-copy" data-ac-copy' in html
        assert 'class="btn btn-quiet ac-call153" href="tel:153"' in html


def test_refused_and_unknown_cards_have_one_primary_153(tmp_path: Path) -> None:
    value = _card_harness(
        tmp_path,
        "const refused=card.renderAnswerCard({mode:'refused'});"
        "const unknown=card.renderAnswerCard({mode:'unknown'});"
        "console.log(JSON.stringify({refused,unknown}));",
    )
    for html in value.values():
        assert html.count("btn-primary") == 1
        assert 'href="tel:153"' in html


def test_card_headings_are_sentence_case_eyebrows(tmp_path: Path) -> None:
    html = _card_harness(
        tmp_path,
        "console.log(JSON.stringify(card.renderAnswerCard({mode:'answer',answer_text:'Yanıt',steps:['Birinci adım'],"
        "citations:[{source:'metro_status',mode:'recorded',observed_at:'2026-07-27T09:27:00Z'}]})));",
    )
    for heading in ('<h3 class="eyebrow">Kısa cevap</h3>', '<h3 class="eyebrow">Kaynak</h3>',
                    '<h3 class="eyebrow">Nasıl yapılır</h3>'):
        assert heading in html
    assert "KISA CEVAP" not in html
    assert '<ol class="ac-steps-list">' in html


def test_the_freshness_badge_never_calls_recorded_data_live(tmp_path: Path) -> None:
    value = _card_harness(
        tmp_path,
        "const recorded=card.kindTag({source:'metro_status',mode:'recorded',observed_at:'2026-07-27T09:27:00Z'});"
        "const live=card.kindTag({source:'metro_status',mode:'live',age_s:120},{beat:true});"
        "const old=card.kindTag({source:'metro_status',mode:'old',age_s:9000});"
        "console.log(JSON.stringify({recorded,live,old}));",
    )
    assert 'class="ac-kind fresh is-recorded"' in value["recorded"]
    assert "fresh-dot" not in value["recorded"] and "Canlı" not in value["recorded"]
    assert 'class="ac-kind fresh is-current is-beat"' in value["live"]
    assert 'class="fresh-dot" aria-hidden="true"' in value["live"]
    assert 'class="ac-kind fresh is-recorded"' in value["old"] and "Ölçüm" in value["old"]


def test_the_pulse_dot_beats_once(tmp_path: Path) -> None:
    value = _card_harness(
        tmp_path,
        "const payload={mode:'answer',answer_text:'Yanıt',citations:[{source:'metro_status',mode:'live',age_s:120}]};"
        "const first=card.renderAnswerCard(payload,{turnId:'pulse'});"
        "const again=card.renderAnswerCard(payload,{turnId:'pulse'});"
        "console.log(JSON.stringify({first,again}));",
    )
    assert 'data-beaten="true"' in value["first"] and "is-beat" in value["first"]
    assert 'data-beaten="true"' not in value["again"] and "is-beat" not in value["again"]
    css = (STATIC / "css" / "components.css").read_text(encoding="utf-8")
    assert css.count("@keyframes nd-beat") == 1


def test_copy_text_carries_source_and_age(tmp_path: Path) -> None:
    value = _card_harness(
        tmp_path,
        "const copied=actions.copyText({mode:'answer',answer_text:'M4 duyurusu.',citations:[{source:'metro_status',"
        "mode:'recorded',observed_at:'2026-07-27T09:27:00+03:00',age_s:120}]});"
        "const noSource=actions.copyText({answer_text:'Kaynağı olmayan yanıt.'});"
        "console.log(JSON.stringify({copied,noSource}));",
    )
    assert value["copied"] == "M4 duyurusu.\nKaynak: Metro İstanbul duyuruları · Kayıtlı veri · 27.07.2026 09:27"
    assert "canlı" not in value["copied"].lower()
    assert value["noSource"] == "Kaynağı olmayan yanıt."


def test_next_chips_are_from_the_verified_list(tmp_path: Path) -> None:
    value = _card_harness(
        tmp_path,
        "const payload={categories:[{id:'first',chips:[{id:'a',text_tr:'İlk soru',text_en:'First question'},"
        "{id:'b',text_tr:'Sorulan soru',text_en:'Asked question'},{id:'c',text_tr:'İkinci soru',text_en:'Second question'},"
        "{id:'d',text_tr:'Üçüncü soru'}]},{id:'other',chips:[{id:'x',text_tr:'Başka konu',text_en:'Other topic'}]}]};"
        "console.log(JSON.stringify({tr:actions.nextChips(payload,'  SORULAN   SORU ', 'tr'),"
        "en:actions.nextChips(payload,'Asked question','en'),empty:actions.nextChips({},'x','tr')}));",
    )
    assert value["tr"] == [{"id": "a", "text": "İlk soru"}, {"id": "c", "text": "İkinci soru"}]
    assert value["en"] == [{"id": "a", "text": "First question"}, {"id": "c", "text": "Second question"}]
    assert value["empty"] == []


def test_the_emergency_card_is_unchanged(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    harness = tmp_path / "emergency_harness.mjs"
    harness.write_text(
        "globalThis.window={location:{search:''}};\n"
        f"const chat=await import({json.dumps((STATIC / 'js' / 'chat.js').as_uri())});\n"
        "const how={rule_id:'emergency',chain:[],checks:{}};\n"
        "const html=chat.answerCard({mode:'redirect',emergency:true,how},'emergency');\n"
        "console.log(JSON.stringify({html}));",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    source = (STATIC / "js" / "chat.js").read_text(encoding="utf-8")
    assert "const EMERGENCY_TEXT = 'Bu acil bir durum olabilir. Lütfen doğrudan ara: 112 (Acil) veya 153 (İBB).';" in source
    html = value["html"]
    assert html.index('href="tel:112"') < html.index('href="tel:153"')
    assert html.index("Bu nasıl bulundu?") > html.index("</div></div></div>")
    assert "Kopyala" not in html and "Şunu da sorabilirsiniz" not in html


def test_card_motion_is_guarded() -> None:
    css = CARD_CSS.read_text(encoding="utf-8")
    plain, _, guarded = css.partition("@media (prefers-reduced-motion: no-preference)")
    assert "animation:" not in plain and "transition:" not in plain
    assert "animation:" in guarded and "transition:" in guarded
    assert "var(--nd-moment)" in css
    assert css.count("var(--nd-moment)") == 1
    assert "text-transform" not in css


def test_new_strings_have_both_catalog_entries() -> None:
    catalogs = [json.loads((STATIC / "i18n" / f"{lang}.json").read_text(encoding="utf-8")) for lang in ("tr", "en")]
    keys = ("dyn.copy", "dyn.copied", "dyn.copy_failed", "dyn.next_title", "dyn.stop", "dyn.stopped",
            "dyn.answer_short", "dyn.how", "dyn.source")
    assert all(set(catalog) == set(catalogs[0]) for catalog in catalogs)
    assert all(key in catalog for catalog in catalogs for key in keys)
    sources = "\n".join(path.read_text(encoding="utf-8") for path in (STATIC / "js").glob("*.js"))
    assert all(catalogs[0][key] in sources for key in keys)
