"""P26 source cards preserve evidence, safe links and sentence provenance."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from html import unescape
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


@pytest.mark.parametrize("separator,latitude,longitude,evidence", [
    (", ", "41,0422", "29,0053", {"citations": [{"source": "gazetteer"}]}),
    (" — ", "41,0422", "29,0053", {"how": {"tool": "places_resolve"}}),
    (" — ", "41.0422", "29.0053", {"how": {"tools": [{"name": "places_resolve"}]}}),
])
def test_place_coordinates_and_known_footer_move_to_existing_details(
    tmp_path, separator, latitude, longitude, evidence,
):
    original = (
        f"• Beşiktaş İskele (Beşiktaş){separator}{latitude}, {longitude}\n"
        "İskele geçici olarak kapalı; yola çıkmadan teyit edin.\n"
        "Veri: kayıtlı · 28.09 16:45.\n"
        "Kaynak: İBB Açık Veri (CC BY 4.0) · resmî bir servis değildir."
    )
    payload = {"mode": "answer", "author": "kural", "answer_text": original, **evidence}
    rendered = node_json(tmp_path, f"console.log(JSON.stringify(answer.renderAnswerCard({json.dumps(payload)})));")
    primary, details = rendered.split('<details class="ac-details">')
    assert "• Beşiktaş İskele (Beşiktaş)" in primary
    assert "İskele geçici olarak kapalı; yola çıkmadan teyit edin." in primary
    assert latitude not in primary and longitude not in primary
    assert "Veri: kayıtlı" not in primary and "Kaynak: İBB Açık Veri" not in primary
    retained = re.search(r'<p class="ac-technical" data-er-skip>(.*?)</p>', details, re.S).group(1)
    assert unescape(retained) == original
    assert rendered.count("<details") == 1


@pytest.mark.parametrize("original", [
    "3 kişi için 1.250,50 TL; 40 dakika ve 2,5 km.",
    "• Ücret (TL), 40,99, 29,02",
    "• Beşiktaş İskele (Beşiktaş), 91,0422, 29,0053",
    "• Beşiktaş İskele (Beşiktaş), 41,0422, 181,0053",
    "• Beşiktaş İskele (Beşiktaş), 41,0422, 29,0053 km",
    "Uyarı: 41,0422, 29,0053 konumunda giriş kapalı.",
    "Veri: eski olabilir; 153 ile teyit edin.\nKaynak: Başka kurum.",
])
def test_presentation_preserves_ordinary_numbers_units_and_unrecognised_lines(tmp_path, original):
    payload = {"mode": "answer", "answer_text": original, "citations": [{"source": "gazetteer"}]}
    rendered = node_json(tmp_path, f"console.log(JSON.stringify(answer.renderAnswerCard({json.dumps(payload)})));")
    assert original in unescape(rendered.split('<details class="ac-details">')[0])
    assert 'class="ac-technical"' not in rendered


def test_place_cleanup_needs_evidence_and_never_changes_sentence_mapping(tmp_path):
    original = "• Beşiktaş İskele (Beşiktaş), 41,0422, 29,0053"
    payload = {"mode": "answer", "answer_text": original}
    mapped = {**payload, "citations": [{"source": "gazetteer"}], "how": {"citation_map": {
        "sentences": [{"text": original, "status": "supported", "support": [{"citation": 0}]}],
    }}}
    value = node_json(tmp_path, f"console.log(JSON.stringify({{plain:answer.renderAnswerCard({json.dumps(payload)}),"
                      f"mapped:answer.renderAnswerCard({json.dumps(mapped)})}}));")
    for rendered in value.values():
        assert original in unescape(rendered.split('<details class="ac-details">')[0])
        assert 'class="ac-technical"' not in rendered
    assert re.search(r'href="#ac-cite-\d+-1" aria-label="Kaynak 1">\[1\]</a>', value["mapped"])


def test_coordinate_cleanup_keeps_exact_quote_once_and_escapes_untrusted_text(tmp_path):
    quote = "  • Kaynak <script>alert(1)</script> — 41.0422, 29.0053\nSon koşul aynen kalır.  "
    original = "• İskele <img src=x onerror=alert(1)> (Beşiktaş), 41,0422, 29,0053"
    citation = {"source": "local:knowledge", "quote": quote}
    payload = {"mode": "answer", "author": "model", "answer_text": original,
               "citations": [{"source": "gazetteer"}, citation]}
    quote_only = {"mode": "quote_only", "author": "kural", "answer_text": original, "citations": [citation]}
    value = node_json(tmp_path, f"console.log(JSON.stringify({{normal:answer.renderAnswerCard({json.dumps(payload)}),"
                      f"quote:answer.renderAnswerCard({json.dumps(quote_only)})}}));")
    for rendered in value.values():
        assert "<script>" not in rendered and "<img" not in rendered
        assert unescape(rendered).count(quote) == 1
    assert '41,0422' not in value["normal"].split('<details class="ac-details">')[0]
    raw = re.search(r'<p class="ac-technical" data-er-skip>(.*?)</p>', value["normal"], re.S).group(1)
    assert unescape(raw) == original
    assert quote in unescape(value["quote"].split('<details class="ac-details">')[0])
    assert 'class="ac-technical"' not in value["quote"]



def test_citizen_answer_has_no_source_dump_or_raw_coordinates_and_does_not_mutate_payload(tmp_path):
    payload = {"mode": "answer", "author": "kural", "answer_text": (
        "• Beşiktaş İskele (Beşiktaş), 41,0422, 29,0053\n"
        "Giriş kapalı olabilir; yola çıkmadan teyit edin.\n"
        "Veri: kayıtlı · 28.09 16:45.\n"
        "Kaynak: İBB Açık Veri (CC BY 4.0) · resmî bir servis değildir."
    ), "citations": [{"source": "gazetteer", "url": "https://example.test/source"}],
        "how": {"tools": [{"name": "places_resolve"}], "rule_id": "TECHNICAL_RULE"}}
    value = node_json(tmp_path, f"const payload={json.dumps(payload)},before=JSON.stringify(payload);"
                      "const html=answer.renderAnswerCard(payload,{surface:'citizen'});"
                      "console.log(JSON.stringify({html,unchanged:JSON.stringify(payload)===before,"
                      "same:html===answer.renderCitizenAnswerCard(payload)}));")
    rendered = value["html"]
    assert value["unchanged"] and value["same"]
    assert 'data-citizen-answer="true"' in rendered
    assert "• Beşiktaş İskele (Beşiktaş)" in rendered
    assert "Giriş kapalı olabilir; yola çıkmadan teyit edin." in rendered
    for absent in ("41,0422", "29,0053", "İBB Açık Veri", "https://", "citation-card", "ac-technical",
                   "ac-sources", "cevabı yazan", "TECHNICAL_RULE", "ac-how", "data-ac-copy"):
        assert absent not in rendered
    assert '<button type="button" class="btn btn-quiet ac-copy" data-citizen-copy>Kopyala</button>' in rendered
    assert '<details class="ac-details"><summary>Daha fazla</summary><div class="ac-details-content"></div></details>' in rendered


def test_citizen_surface_is_explicit_or_selected_only_by_the_citizen_body(tmp_path):
    value = node_json(tmp_path, "const payload={mode:'answer',answer_text:'Yanıt',citations:[{source:'gazetteer'}]};"
                      "const ordinary=answer.renderAnswerCard(payload);"
                      "globalThis.document={body:{classList:{contains:value=>value==='citizen-page'}}};"
                      "const citizen=answer.renderAnswerCard(payload);"
                      "const operator=answer.renderAnswerCard(payload,{surface:'operator'});"
                      "document.body.classList.contains=()=>false;const other=answer.renderAnswerCard(payload);"
                      "console.log(JSON.stringify({ordinary,citizen,operator,other}));")
    assert 'data-citizen-answer="true"' in value["citizen"]
    assert 'class="citation-card"' not in value["citizen"]
    for key in ("ordinary", "operator", "other"):
        assert 'data-citizen-answer=' not in value[key]
        assert 'class="citation-card"' in value[key]


@pytest.mark.parametrize("mode", ["quote_only", "answer"])
def test_citizen_source_only_primary_quote_is_exact_without_source_chrome(tmp_path, mode):
    quote = '  Başvuru <script>alert(1)</script> ile değil, merkezden yapılır.\nSon koşul aynen kalır.  '
    payload = {"mode": mode, "author": "kural", "answer_text": "MODEL_UNUSED",
               "citations": [{"source": "local:knowledge", "title": "SOURCE_TITLE_UNUSED",
                              "url": "https://example.test/source", "quote": quote}]}
    rendered = node_json(tmp_path, f"console.log(JSON.stringify(answer.renderCitizenAnswerCard({json.dumps(payload)})));")
    primary = rendered.split('<details class="ac-details">')[0]
    assert quote in unescape(primary) and unescape(rendered).count(quote) == 1
    assert 'class="answer-short ac-short"' in primary and 'class="quote-text quote-exact" data-er-skip' in primary
    for absent in ("<script>", "figcaption", "href=", "SOURCE_TITLE_UNUSED", "MODEL_UNUSED", "ac-sources"):
        assert absent not in rendered


def test_citizen_renders_only_real_text_steps_and_preserves_all_numeric_conditions(tmp_path):
    payload = {"mode": "answer", "answer_text": "M2 için 15 dakika ayırın; 2 aktarma var.",
               "steps": ["M2'ye binin.", {"text": "OBJECT_NOT_A_STEP"}, "", "Aktarmada 300 metre yürüyün."]}
    rendered = node_json(tmp_path, f"console.log(JSON.stringify(answer.renderCitizenAnswerCard({json.dumps(payload)})));")
    primary, details = rendered.split('<details class="ac-details">')
    for text in ("M2 için 15 dakika ayırın; 2 aktarma var.", "M2'ye binin.", "Aktarmada 300 metre yürüyün."):
        assert text in unescape(primary)
    assert primary.count('<li data-er-target>') == 2 and 'OBJECT_NOT_A_STEP' not in rendered
    assert '[object Object]' not in rendered and '<li' not in details


def test_citizen_preserves_stale_missing_source_and_conflict_warnings_without_source_links(tmp_path):
    payload = {"mode": "answer", "answer_text": "OLD_TEXT", "citations": [{
        "source": "local:knowledge", "source_updated_at": "2020-01-01T00:00:00Z",
    }], "how": {"citation_map": {"sentences": [
        {"text": "Koşul korunur.", "status": "supported", "support": [{"citation": 0}]},
        {"text": "Doğrulanmayan bölüm.", "status": "no_source"},
    ], "conflicts": [{"sentence": 0}], "labels": {"no_source": "KAYNAK_YOK", "conflict": "CELISKI_VAR"}}}}
    rendered = node_json(tmp_path, f"console.log(JSON.stringify(answer.renderCitizenAnswerCard({json.dumps(payload)})));")
    for text in ("Koşul korunur.", "Doğrulanmayan bölüm.", "KAYNAK_YOK", "CELISKI_VAR", "Eski olabilir, 153 ile teyit edin"):
        assert text in rendered
    assert "OLD_TEXT" not in rendered and 'href=' not in rendered and 'ac-sentence-source' not in rendered


def test_citizen_safety_modes_do_not_expose_answer_steps_or_sources(tmp_path):
    value = node_json(tmp_path, "const data={answer_text:'UNSAFE_UNUSED',steps:['STEP_UNUSED'],"
                      "citations:[{source:'local:knowledge',quote:'QUOTE_UNUSED'}],how:{rule_id:'RULE_UNUSED'}};"
                      "console.log(JSON.stringify({refused:answer.renderCitizenAnswerCard({...data,mode:'refused'}),"
                      "unknown:answer.renderCitizenAnswerCard({...data,mode:'unknown'}),"
                      "emergency:answer.renderCitizenAnswerCard({...data,mode:'answer',emergency:true}),"
                      "empty:answer.renderCitizenAnswerCard({mode:'answer'}),refusalText:answer.REFUSAL_TEXT}));")
    assert value["emergency"] == ""
    assert value["refusalText"] in unescape(value["refused"])
    for key in ("unknown", "empty"):
        assert 'Bu bilgiyi doğrulayamadım.' in value[key]
        assert 'href="tel:153"' in value[key]
    for key in ("refused", "unknown", "empty"):
        assert not re.search(r"UNSAFE_UNUSED|STEP_UNUSED|QUOTE_UNUSED|RULE_UNUSED", value[key])
        assert 'ac-sources' not in value[key] and 'cevabı yazan' not in value[key]
        assert '<span class="chat-foot" hidden aria-hidden="true"></span>' in value[key]
