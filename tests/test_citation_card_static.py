"""P26 source cards preserve evidence, safe links and sentence provenance."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src/nabiz/console/static"
CITATION = STATIC / "js/citation_card.js"
ANSWER = STATIC / "js/answer_card.js"
CATALOG = {
    "tr": {
        "ui.citation.open": "Kaynağı aç", "ui.citation.open_name": "kaynağını aç",
        "ui.citation.quote_above": "Alıntı yukarıda", "ui.citation.quote_source": "Alıntının kaynağı",
        "ui.citation.more": "Diğer kaynaklar ({count})", "ui.citation.source": "Kaynak {number}",
        "ui.citation.no_source": "Bu cümle için kaynak henüz yok",
        "ui.citation.conflict": "İki kaynak farklı değer veriyor; hangisinin geçerli olduğu doğrulanmadı. 153'e sorun.",
        "ui.citation.no_date": "Sayfa tarih vermiyor", "ui.citation.page": "Kaynak sayfası",
        "ui.citation.institution": "Kurum belirtilmemiş", "ui.citation.recorded": "Kayıtlı veri",
        "ui.citation.unknown_age": "Veri yaşı bilinmiyor", "ui.citation.updated": "son güncelleme: {date}",
        "ui.citation.stale": "Eski olabilir, 153 ile teyit edin",
        "ui.citation.measured": "Ölçüm", "ui.citation.schedule": "Tarifeye göre",
        "ui.citation.page_quote": "Resmî sayfadan alıntı",
    },
    "en": {
        "ui.citation.open": "Open source", "ui.citation.open_name": "open source",
        "ui.citation.quote_above": "Quote above", "ui.citation.quote_source": "Source of quote",
        "ui.citation.more": "Other sources ({count})", "ui.citation.source": "Source {number}",
        "ui.citation.no_source": "No source yet for this sentence",
        "ui.citation.conflict": "Two sources give different values; which one applies has not been verified. Ask 153.",
        "ui.citation.no_date": "The page gives no date", "ui.citation.page": "Source page",
        "ui.citation.institution": "Institution not specified", "ui.citation.recorded": "Recorded data",
        "ui.citation.unknown_age": "Source age unknown", "ui.citation.updated": "last updated: {date}",
        "ui.citation.stale": "May be outdated; confirm with 153",
        "ui.citation.measured": "Measurement", "ui.citation.schedule": "Based on the timetable",
        "ui.citation.page_quote": "Quoted from the official page",
    },
}
DOM = r"""
class Element {
  constructor(tag) { this.tag = tag; this.attrs = {}; this.children = []; this.text = ''; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  append(...children) { this.children.push(...children); }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const doc = {createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag),
  createTextNode: value => ({textContent: value})};
const all = root => [root, ...(root.children || []).flatMap(all)];
const find = (root, tag) => all(root).find(node => node.tag === tag);
"""


def node_json(tmp_path: Path, body: str, *, dom: bool = False):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    harness = tmp_path / "citation_harness.mjs"
    harness.write_text(
        f"const citation = await import({json.dumps(CITATION.as_uri())});\n"
        f"const answer = await import({json.dumps(ANSWER.as_uri())});\n"
        f"const i18n = await import({json.dumps((STATIC / 'js/i18n_text.js').as_uri())});\n"
        + (DOM + "globalThis.document=doc;\n" if dom else "") + body,
        encoding="utf-8",
    )
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_exact_quote_and_accessible_source_link_use_inert_dom(tmp_path):
    value = node_json(tmp_path, r"""
const quote = '  Kaynak <img src=x onerror=alert(1)> & "birebir"\nson satır  ';
const input = {source:'local:knowledge', institution:'ISKI', title:'Abonelik', quote,
  url:'https://iski.istanbul/abonelik', fetched_at:'2026-09-28T06:27:00Z'};
const before = JSON.stringify(input);
const card = citation.citationCard(input, {index:0, answerId:12, now:1790568000000});
const link = find(card, 'a');
const names = link.attrs['aria-labelledby'].split(' ').map(id => all(card).find(node => node.attrs?.id === id).textContent);
const label = names.join(' ');
console.log(JSON.stringify({quote:find(card,'blockquote').textContent, input:quote, unchanged:before===JSON.stringify(input),
  label, link:link.attrs, icon:find(card,'svg').attrs, tags:all(card).map(node=>node.tag), text:card.textContent}));
""", dom=True)
    assert value["quote"] == value["input"] and value["unchanged"]
    assert value["label"] == "İSKİ, Abonelik kaynağını aç"
    assert value["link"]["href"] == "https://iski.istanbul/abonelik"
    assert "noopener" in value["link"]["rel"] and value["icon"]["aria-hidden"] == "true"
    assert "img" not in value["tags"]
    assert "Kayıtlı veri 28.09.2026 09:27" in value["text"]
    assert "Sayfa tarih vermiyor" in value["text"]


@pytest.mark.parametrize("url", [
    "http://unsafe.test", "javascript:alert(1)", "//unsafe.test", "data:text/html,x", "https://user:pass@example.com", "https://",
])
def test_unsafe_sources_never_become_links(tmp_path, url):
    value = node_json(tmp_path, f"const card=citation.citationCard({{title:'Kaynak',url:{json.dumps(url)}}});"
                      "console.log(JSON.stringify({links:all(card).filter(node=>node.tag==='a').length,"
                      "quote:find(card,'blockquote')||null}));", dom=True)
    assert value == {"links": 0, "quote": None}


def test_language_fallback_and_catalog_are_complete(tmp_path):
    assert CATALOG["tr"].keys() == CATALOG["en"].keys()
    value = node_json(tmp_path, f"const catalog={json.dumps(CATALOG)};const result={{}};"
                      "for(const lang of ['tr','en']) {i18n.setCatalogs(lang,{},{}); result[lang]={};"
                      "for(const key of Object.keys(catalog[lang])) "
                      "result[lang][key]=citation.citationText(key.slice(12),lang); }"
                      "console.log(JSON.stringify(result));")
    assert value == CATALOG
    strings = " ".join(CATALOG["tr"].values()) + " " + " ".join(CATALOG["en"].values())
    assert not re.search(r"[\u2013\u2014]|\b(canlı|live|sen)\b", strings, re.I)


def test_answer_puts_all_sources_in_one_disclosure_without_duplicate_quotes(tmp_path):
    value = node_json(tmp_path, "const citations=Array.from({length:4},(_,i)=>({source:'local:knowledge',institution:'ISKI',"
                      "title:`Sayfa ${i}`,quote:`ALINTI_${i}`,url:'https://iski.istanbul/page'}));"
                      "const payload={mode:'answer',author:'model',answer_text:'Yanıt',citations};"
                      "console.log(JSON.stringify({first:answer.renderAnswerCard(payload),second:answer.renderAnswerCard(payload)}));")
    first, second = value["first"], value["second"]
    assert first.count('class="citation-card"') == 4
    before, after = first.split('<details class="ac-details">')
    assert "Yanıt" in before and 'class="citation-card"' not in before and "ALINTI_" not in before
    assert after.count('class="citation-card"') == 4
    assert first.count("<details") == first.count("<summary>") == 1
    assert "Ayrıntılar" in after and '<details class="ac-details" open' not in first
    for index in range(4):
        assert first.count(f"ALINTI_{index}") == 1
    ids = re.findall(r' id="(ac-(?:cite|quote)-\d+-\d+)"', first)
    assert len(ids) == len(set(ids)) == 8
    assert not set(ids) & set(re.findall(r' id="(ac-(?:cite|quote)-\d+-\d+)"', second))
    for target in re.findall(r'href="#(ac-(?:cite|quote)-\d+-\d+)"', first):
        assert target in ids


def test_sentence_map_targets_support_and_exposes_unknown_and_conflict(tmp_path):
    html = node_json(tmp_path, "const citations=Array.from({length:3},()=>({source:'metro_status',mode:'recorded'}));"
                    "console.log(JSON.stringify(answer.renderAnswerCard({mode:'answer',answer_text:'OLD_TEXT',citations,how:{citation_map:{"
                    "sentences:[{text:'Destekli.',status:'supported',support:[{citation:2}]},{text:'Bilinmeyen.',status:'no_source'},"
                    "{text:'<script>',status:'supported',support:[{citation:99}]}],conflicts:[{sentence:0}],"
                    "labels:{no_source:'KAYNAK_YOK',conflict:'CELISKI_VAR'}}}}))); ")
    assert "OLD_TEXT" not in html and "Destekli." in html and "&lt;script&gt;" in html
    match = re.search(r'href="#(ac-cite-\d+-3)" aria-label="Kaynak 3">\[3\]</a>', html)
    assert match and f'id="{match.group(1)}"' in html
    assert '<span class="ac-no-source">KAYNAK_YOK</span>' in html
    assert '<p class="ac-conflict ac-stale">CELISKI_VAR</p>' in html
    assert "[100]" not in html


def test_source_styles_remain_static_and_quiet():
    js = CITATION.read_text()
    css = (STATIC / "css/answer_card.css").read_text()
    assert len(js.splitlines()) <= 200 and len(css.splitlines()) <= 350
    assert "from './provenance.js'" in js and "ageText(" in js
    assert "textContent" in js and "innerHTML" not in js
    assert 'id="i-list-details"' in (STATIC / "icons.svg").read_text()
    for forbidden in ("fetch(", "registerCardType(", "btn-primary", "danger", "role: 'alert'"):
        assert forbidden not in js
    assert "animation:" not in css and "transition:" not in css
    assert "var(--bad)" not in css and "var(--bad-wash)" not in css
    assert ".ac-kind.is-recorded { color: var(--text-muted);" in css
    assert ".citation-card .ac-kind.fresh { border: 1px solid var(--nd-line-strong); }" in css
    assert ".citation-card .ac-kind.fresh.is-unverified { border-style: dashed; }" in css
    assert '.ac-short > h3' in css and 'clip-path: inset(50%)' in css
    assert '@media (min-width: 481px) { .ac-actions .btn { white-space: nowrap; } }' in css


def test_source_card_metadata_has_two_parts_without_dot_separators(tmp_path):
    value = node_json(tmp_path, "const updated=citation.citationCard({source:'local:knowledge',institution:'ISKI',"
                      "title:'Başlık',fetched_at:'2026-09-28T09:00:00Z',source_updated_at:'2026-09-20T09:00:00Z'});"
                      "const recorded=citation.citationCard({source:'metro_status',mode:'recorded',"
                      "observed_at:'2026-09-28T09:00:00Z'}, {lang:'en'});"
                      "console.log(JSON.stringify({updated:updated.textContent,recorded:recorded.textContent}));", dom=True)
    assert " · " not in value["updated"] and " · " not in value["recorded"]
    assert "Recorded data 28.09.2026 12:00" in value["recorded"]


def test_emergency_payload_never_reaches_the_citation_renderer(tmp_path):
    value = node_json(tmp_path, "console.log(JSON.stringify(answer.renderAnswerCard({mode:'answer',emergency:true,"
                      "answer_text:'Not an ordinary answer',citations:[{source:'local:knowledge',quote:'QUOTE'}]})));")
    assert value == ""


@pytest.mark.parametrize(("source", "expected"), [
    ({"mode": "old", "age_s": 600}, "Measurement 10 min ago"),
    ({"mode": "old", "age_s": 172800}, "Measurement 2 d ago"),
    ({"mode": "recorded"}, "Recorded data source age unknown"),
])
def test_english_freshness_has_no_turkish_age_fragments(tmp_path, source, expected):
    html = node_json(tmp_path, f"console.log(JSON.stringify(citation.citationMarkup({json.dumps(source)}, {{lang:'en'}})));")
    badge = re.search(r'<span class="ac-kind fresh[^"]*">([^<]*)</span>', html).group(1)
    assert badge == expected
    assert not re.search(r"önce|gün|veri yaşı|bilinmiyor", badge)


ANSWER_CATALOG = {
    "tr": {"ui.answer.details": "Ayrıntılar"},
    "en": {"ui.answer.details": "Details"},
}


def test_one_disclosure_holds_steps_and_trace_after_the_complete_answer(tmp_path):
    value = node_json(tmp_path, "const payload={mode:'answer',author:'model',"
                      "answer_text:'Kullanıcı cevabı. Önemli koşul aynen kalır.',steps:['İlk adım'],"
                      "citations:[{source:'local:knowledge',quote:'BİREBİR_ALINTI'}],how:{tools:[{name:'places_resolve'}]}};"
                      "console.log(JSON.stringify({tr:answer.renderAnswerCard(payload,{lang:'tr'}),"
                      "en:answer.renderAnswerCard(payload,{lang:'en'})}));")
    assert ANSWER_CATALOG["tr"].keys() == ANSWER_CATALOG["en"].keys()
    for lang, html in value.items():
        primary, details = html.split('<details class="ac-details">')
        assert 'Kullanıcı cevabı. Önemli koşul aynen kalır.' in primary
        assert 'İlk adım' not in primary and 'BİREBİR_ALINTI' not in primary
        assert 'İlk adım' in details and 'BİREBİR_ALINTI' in details and 'Bu nasıl bulundu?' in details
        assert html.count('<details') == html.count('<summary>') == 1
        assert f'<summary>{ANSWER_CATALOG[lang]["ui.answer.details"]}</summary>' in details


@pytest.mark.parametrize("mode,author", [("quote_only", "kural"), ("answer", "kural")])
def test_source_only_answer_remains_visible_and_exact(tmp_path, mode, author):
    payload = {"mode": mode, "author": author, "citations": [{
        "source": "local:knowledge", "quote": "Gerekli işlem. Kritik koşul korunur.",
        "source_updated_at": "2020-01-01T00:00:00Z",
    }]}
    html = node_json(tmp_path, f"console.log(JSON.stringify(answer.renderAnswerCard({json.dumps(payload)})));")
    primary, details = html.split('<details class="ac-details">')
    assert "Gerekli işlem. Kritik koşul korunur." in primary
    assert "Eski olabilir, 153 ile teyit edin" in primary
    assert html.count("Gerekli işlem. Kritik koşul korunur.") == 1
    assert 'class="ac-sources"' in details and 'class="quote-text quote-exact"' in primary


def test_steps_only_answer_is_not_hidden_behind_an_empty_disclosure(tmp_path):
    html = node_json(tmp_path, "console.log(JSON.stringify(answer.renderAnswerCard({mode:'answer',steps:['Gerekli işlem']})));")
    assert 'Gerekli işlem' in html.split('<details class="ac-details">')[0]
