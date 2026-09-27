"""Smoke tests for the console app's static pages (``src/nabiz/console/static``).

The pages are vanilla HTML, CSS and ES modules with no build step, so these tests are the only thing
between an edit and a phone: the files the pages reference exist, the landmarks and live regions a
screen reader needs are in the markup, every icon reference resolves, the mock replies match the API
contract's field names, and no visible string carries a dash, "ETA" or "kanca" (the product rules).
No server, no network: everything is read from the tree.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
WEB_STATIC = REPO_ROOT / "src" / "nabiz" / "web" / "static"
PAGES = ("index.html", "console.html", "kolay.html", "nasil.html")
DASHES = (chr(0x2014), chr(0x2013))  # em dash, en dash

#: The contract's field names (the API SÖZLEŞMESİ of the sprint brief), checked on every mock reply.
PROVENANCE_KEYS = {"source", "url", "observed_at", "age_s", "mode"}
CARD_KEYS = {"id", "kind", "title", "body", "status", "provenance", "author", "how"}
QUEUE_ITEM_KEYS = {"signal_id", "kind", "title", "severity", "path", "status", "created_at", "summary"}
DECISION_KEYS = {
    "signal_id",
    "signal",
    "evidence",
    "freshness_s",
    "alternatives",
    "opinions",
    "dissent_summary",
    "proposed_action",
    "confidence",
    "author",
}
FINAL_KEYS = {
    "answer", "answer_text", "citations", "author", "memory_suggestion", "refused", "how", "mode", "steps", "emergency",
}


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def mock(name: str) -> dict:
    return json.loads(read(f"mock/{name}.json"))


def visible_text(html: str) -> str:
    """Text and the attributes a person reads, without the sprite and the comments."""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"<svg class=\"sprite\".*?</svg>", "", html, flags=re.S)
    return html


@pytest.mark.parametrize("name", PAGES)
def test_every_file_the_page_references_exists(name: str) -> None:
    html = read(name)
    refs = re.findall(r'(?:href|src)="(/(?:css|js|fonts)/[^"#?]+)"', html)
    assert refs, "the page links its stylesheets and scripts"
    for ref in refs:
        assert (STATIC / ref.lstrip("/")).is_file(), f"{name} references {ref}, which is missing"
    entry = re.search(r'<script type="module" src="([^"]+)"', html)
    assert entry, "one module entry"
    assert f'<link rel="modulepreload" href="{entry.group(1)}">' in html


def test_every_import_between_modules_resolves() -> None:
    js = STATIC / "js"
    for path in sorted(js.glob("*.js")):
        for spec in re.findall(r"""from\s+['"](\.[^'"]+)['"]""", path.read_text(encoding="utf-8")):
            assert (path.parent / spec).resolve().is_file(), f"{path.name} imports {spec}, which is missing"


@pytest.mark.parametrize("name", PAGES)
def test_landmarks_headings_and_live_regions(name: str) -> None:
    html = read(name)
    assert '<html lang="tr">' in html
    for landmark in ("<header", "<main", "<footer", "<nav" if name == "index.html" else "<main"):
        assert landmark in html, f"{name} lacks {landmark}"
    assert html.count("<h1") == 1, "exactly one h1"
    assert 'class="skip-link"' in html and 'id="main"' in html
    assert 'role="status"' in html, "a status region for what the scripts announce"
    assert re.search(r"aria-live=\"polite\"", html), "a live region"
    assert "prefers-reduced-motion" in read("css/base.css")
    # Every section a script fills has a heading it is labelled by.
    for label in re.findall(r'aria-labelledby="([\w-]+)"', html):
        assert f'id="{label}"' in html, f"{name}: aria-labelledby points at a missing id {label}"


def test_the_honesty_bands_are_on_both_pages() -> None:
    index, console = read("index.html"), read("console.html")
    assert "Resmî İBB hizmeti" in index and "Resmî İBB hizmeti" in console
    # The AI notice text has one source, disclosure.js (G15); chat.js shows it by importing its markup.
    assert "Ben İstanbul şehir bilgi asistanıyım ve yapay zekâ kullanıyorum." in read("js/disclosure.js")
    assert "import { aiNoticeMarkup } from './disclosure.js';" in read("js/chat.js")
    assert "Simüle operatör" in console
    assert "İBB onaylı" not in index and "İBB onaylı" not in console
    for page in (index, console):
        assert "logo" not in page.lower()


@pytest.mark.parametrize("name", PAGES)
def test_no_dash_eta_or_kanca_in_the_page(name: str) -> None:
    text = visible_text(read(name))
    for dash in DASHES:
        assert dash not in text, f"{name} carries a dash"
    assert not re.search(r"\bETA\b", text)
    assert "kanca" not in text.lower()


def test_no_dash_or_eta_in_scripts_styles_and_mocks() -> None:
    files = [*(STATIC / "js").glob("*.js"), *(STATIC / "css").glob("*.css"), *(STATIC / "mock").glob("*.json")]
    for path in sorted(files):
        text = path.read_text(encoding="utf-8")
        for dash in DASHES:
            assert dash not in text, f"{path.name} carries a dash"
        assert not re.search(r"\bETA\b", text), f"{path.name} says ETA"


def test_no_decimal_minutes_in_scripts() -> None:
    """Single-minute rule: a card says "42 dk", never "41,5 dk". A minute value is rounded to a whole number
    before " dk" is appended, so no script formats it with a fractional digit."""
    decimal_minutes = re.compile(r"num\([^;]*?,\s*[1-9]\)\}?[^;\n]{0,3}\bdk\b")
    for path in sorted((STATIC / "js").glob("*.js")):
        text = path.read_text(encoding="utf-8")
        assert not decimal_minutes.search(text), f"{path.name} shows a decimal minute"
    compare = read("js/compare.js")
    assert "Math.round(Number(value))" in compare
    assert "wholeMinutes(option.minutes)" in compare and "wholeMinutes(reliability.median_headway_min)" in compare


def test_every_icon_reference_resolves() -> None:
    external = set(re.findall(r'<symbol id="i-([\w-]+)"', read("icons.svg")))
    assert len(external) >= 50
    for name in PAGES:
        html = read(name)
        inline = set(re.findall(r'<symbol id="i-([\w-]+)"', html))
        for ref in re.findall(r'<use href="#i-([\w-]+)"', html):
            assert ref in inline, f"{name}: #i-{ref} is not in the inline sprite"
        for ref in re.findall(r'<use href="/icons.svg#i-([\w-]+)"', html):
            assert ref in external
    for path in sorted((STATIC / "js").glob("*.js")):
        source = path.read_text(encoding="utf-8")
        for ref in re.findall(r"icon\('([\w-]+)'", source):
            assert ref in external, f"{path.name} asks for icon {ref}, which icons.svg lacks"


def test_tokens_are_the_web_pages_tokens() -> None:
    """One palette for both apps: the console copy is byte-for-byte the generated file."""
    assert read("css/tokens.css") == (WEB_STATIC / "css" / "tokens.css").read_text(encoding="utf-8")


def test_colour_literals_live_only_in_tokens() -> None:
    colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(")
    for path in sorted((STATIC / "css").glob("*.css")):
        if path.name == "tokens.css":
            continue
        text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        assert not colour.search(text), f"{path.name} holds a colour literal"


def test_mock_replies_follow_the_contract() -> None:
    brief = mock("brief")
    assert {"cards", "generated_at"}.issubset(brief)
    for card in brief["cards"]:
        assert CARD_KEYS.issubset(card)
        assert card["status"] in {"ok", "warning", "stale", "unverified"}
        assert card["author"] in {"kural", "model", "yerel model"}
        assert PROVENANCE_KEYS.issubset(card["provenance"])
    arrival = mock("arrival")
    assert {"line", "stop", "minutes", "display", "provenance"}.issubset(arrival)
    assert re.fullmatch(r"\d+ dk|tarifeye göre|doğrulanamadı", arrival["display"])
    alternative = mock("alternative")
    assert {"station", "lift_status", "alternative", "operator_approved", "provenance"}.issubset(alternative)
    for name in ("chat", "chat-memory", "chat-refused", "chat-quote"):
        events = mock(name)["events"]
        assert events[-1]["event"] == "final"
        assert FINAL_KEYS.issubset(events[-1]["data"])
        assert all(e["event"] in {"session_started", "token", "tool", "final"} for e in events)
    quote = mock("chat-quote")["events"][-1]["data"]
    assert quote["mode"] == "quote_only" and quote["citations"][0]["quote"]
    for item in mock("console-queue")["items"]:
        assert QUEUE_ITEM_KEYS.issubset(item)
        assert item["path"] in {"reflex", "arena"}
    for name in ("console-decision-sig-001", "console-decision-sig-006", "console-decision-default"):
        decision = mock(name)
        assert DECISION_KEYS.issubset(decision)
        assert {o["role"] for o in decision["opinions"]} == {"Erişilebilirlik", "Operasyon", "İletişim"}
        assert decision["confidence"]["level"] in {"high", "medium", "low"}
    assert {"steps", "hash_ok"}.issubset(mock("console-trace"))
    assert {"ok", "entries"}.issubset(mock("console-ledger-verify"))
    assert {"reflex_closed_today", "awaiting_approval", "median_decision_s", "citizen_update_latency_s", "approval_rate"} <= mock(
        "console-stats"
    ).keys()
    for draft in mock("console-rule-drafts")["drafts"]:
        assert {"draft_id", "pattern", "evidence_decisions", "proposed_rule_toml", "expires_days"}.issubset(draft)
        assert len(draft["evidence_decisions"]) >= 3, "a rule draft needs three approvals; one event is never a rule"
    assert {"rule_id", "expires_at"}.issubset(mock("console-adopt"))
    assert {"signal_id"}.issubset(mock("console-simulate"))
    assert {"status", "ledger_entry_id"}.issubset(mock("console-decision-post"))


def test_the_lift_line_never_says_working() -> None:
    """R-02: the best a lift row says is "arıza yok"; the citizen never reads "çalışıyor" about a lift."""
    for path in sorted((STATIC / "mock").glob("*.json")) + [STATIC / "js" / "cards.js"]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"asansör[^.\n]{0,40}\bçalışıyor\b", text, flags=re.I), f"{path.name} says a lift is working"


def test_every_module_parses(tmp_path) -> None:
    node = shutil.which("node")
    if node is None:  # pragma: no cover - CI without node still runs the static checks above
        pytest.skip("node is not installed")
    for path in sorted((STATIC / "js").glob("*.js")):
        proc = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, f"{path.name}: {proc.stderr}"


def test_the_home_screen_has_the_question_box_before_city_cards() -> None:
    html = read("index.html")
    assert html.index('id="home-screen"') < html.index('id="chat-input"') < html.index('id="quick-cards"')
    assert html.index('id="quick-cards"') < html.index('id="city-cards"') < html.index('id="cards"')
    question = html[html.index('id="chat-input"'):html.index('id="chat-submit"')]
    assert 'placeholder="Örnek: M2\'de arıza var mı?"' in question
    assert "autofocus" not in question and 'tabindex="0"' in question
    textarea = re.search(r'<textarea\b[^>]*\bid="chat-input"[^>]*>\s*</textarea>', html)
    assert textarea, "the composer accepts multiline questions without opening the mobile keyboard on load"
    assert 'name="q"' in textarea.group() and 'rows="3"' in textarea.group()
    assert 'aria-describedby="chat-hint"' in textarea.group()
    source = read("js/home.js")
    assert 'role="button" tabindex="0"' in source and "button[data-seed]" in source
    assert "requestSubmit()" in source and "localStorage" not in source
    assert "İstanbul ulaşımı için resmî bilgi nerede?" in source
    # E21's chips replace these once /api/quick answers; the İSKİ seed survives there as an agency chip (DECISIONS #43).
    quick = json.loads((REPO_ROOT / "data/knowledge/quick_questions.json").read_text(encoding="utf-8"))
    seeds = {chip["soru_tr"]: chip["kind"] for chip in quick["sorular"]}
    assert "İSKİ ve fatura işlemleri için nereye başvurabilirim?" in source
    assert seeds["İSKİ ve fatura işlemleri için nereye başvurabilirim?"] == "agency"


def test_unknown_text_is_verbatim() -> None:
    source = read("js/chat.js")
    match = re.search(r'^const UNKNOWN_TEXT = "([^\"]*)";$', source, flags=re.M)
    assert match
    expected = (
        "Bu konuda doğrulayabildiğim güncel bir İBB kaynağı bulamadım. Tahmin yürütmek istemiyorum. "
        "153'e bağlanabilir veya ilgili resmî sayfaya gidebilirsin."
    )
    assert match.group(1) == expected


def test_ai_notice_appears_once_per_page_session() -> None:
    source = read("js/chat.js")
    # The text itself lives once, in disclosure.js (G15); chat.js only shows it once per session.
    assert "const AI_NOTICE =" not in source and "AI_NOTICE" not in source
    assert "import { aiNoticeMarkup } from './disclosure.js';" in source
    assert "event === 'session_started'" in source
    assert "if (!sessionStarted)" in source
    assert source.count("aiNoticeMarkup()") == 1
    # The band at the top of the log is the one notice: the first answer does not repeat it.
    disclosure = read("js/disclosure.js")
    assert "chat-ai-notice" not in disclosure and "MutationObserver" not in disclosure
    assert "chat-ai-notice" not in source


def test_the_emergency_answer_shows_the_how_panel_and_the_legacy_unknown_path_does_not() -> None:
    source = read("js/chat.js")
    unknown_path = source[source.index("const unknown ="):source.index("return html;", source.index("const unknown ="))]
    assert "if (!unknown)" in unknown_path
    emergency_path = source[source.index("if (mode === 'redirect'"):source.index("const unknown =")]
    assert "howPanel(how, turnId)" in emergency_path


def test_the_console_first_screen_is_the_work_desk_and_the_tables_sit_in_closed_disclosures() -> None:
    """P00 G1 layout: counters under the desk title, four closed disclosures below, nav untouched."""
    html = read("console.html")
    title = html.index('id="desk-title"')
    counters = html.index('<ul class="work-counters" id="work-counters" aria-label="İşler" hidden></ul>')
    assert title < counters < html.index('id="queue"')
    order = [
        '<span>Sistem durumu</span>', 'id="approval-health"', 'id="outcomes-mount"',
        '<span>Bildirimler</span>', 'id="report-map"', 'id="incidents-mount"', 'id="report-timeline-mount"',
        'id="photo-reports-mount"', 'id="chronic-mount"',
        '<span>Vatandaş talepleri</span>', 'id="citizen-requests"', 'id="escort-mount"', 'id="polls-mount"',
        'id="outage-watch-mount"',
        '<span>Kurallar ve taslaklar</span>',
        '<span>Bilgi ve planlama</span>', 'id="knowledge-planning"', 'id="knowledge-editor-mount"', 'id="scenario-mount"',
        '<span>Karar motoru</span>',
    ]
    at = [html.index(marker) for marker in order]
    assert at == sorted(at), "the disclosures and their mounts keep the vision's order"
    assert "<details open" not in html and "Bildirim haritası</span>" not in html
    nav = html[html.index('<nav class="console-nav"'):html.index("</nav>")]
    assert "knowledge-planning" not in nav and nav.count("<li>") == 8


#: A DOM just big enough for console_work_counters.js: lists, details, headings, focus (P00).
FAKE_DOM = """
      class El {
        constructor(tag, id = '') { this.tagName = tag.toUpperCase(); this.id = id; this.children = [];
          this.dataset = {}; this.hidden = false; this.attrs = {}; this.parent = null; this.textContent = ''; }
        append(child) { child.parent = this; this.children.push(child); }
        get firstElementChild() { return this.children[0]; }
        addEventListener(kind, fn) { this.onclick = fn; }
        matches(sel) { return sel.split(',').map((s) => s.trim().toUpperCase()).includes(this.tagName); }
        querySelector(sel) { for (const c of this.children) { if (c.matches(sel)) return c;
          const hit = c.querySelector(sel); if (hit) return hit; } return null; }
        closest(sel) { let el = this; while (el && !el.matches(sel)) el = el.parent; return el; }
        hasAttribute(n) { return n in this.attrs; }
        setAttribute(n, v) { this.attrs[n] = v; }
        focus() { doc.focused = this; }
      }
"""


def test_a_work_counter_at_zero_hides_and_its_link_opens_the_table(tmp_path) -> None:
    node = shutil.which("node")
    if node is None:  # pragma: no cover - CI without node still runs the static checks above
        pytest.skip("node is not installed")
    module = (STATIC / "js" / "console_work_counters.js").as_uri()
    script = f"""
      {FAKE_DOM}
      const list = new El('ul', 'work-counters'); list.hidden = true;
      const details = new El('details'); const section = new El('section', 'report-timeline');
      const h2 = new El('h2'); details.append(new El('summary')); details.append(section); section.append(h2);
      const doc = {{ getElementById: (id) => (id === 'work-counters' ? list : null), createElement: (t) => new El(t),
        querySelector: (sel) => (sel === '#report-timeline' ? section : null), focused: null }};
      const m = await import({json.dumps(module)});
      const zero = m.setWorkCounter('timeline', 'Sizi bekleyen bildirim', 0, '#report-timeline', doc);
      const afterZero = {{ item: zero.hidden, list: list.hidden }};
      m.setWorkCounter('timeline', 'Sizi bekleyen bildirim', 3, '#report-timeline', doc);
      let prevented = false;
      list.children[0].firstElementChild.onclick({{ preventDefault: () => {{ prevented = true; }} }});
      console.log(JSON.stringify({{ afterZero, items: list.children.length, text: list.children[0].firstElementChild.textContent,
        listHidden: list.hidden, open: details.open === true, focused: doc.focused === h2, tabindex: h2.attrs.tabindex,
        prevented, missing: m.setWorkCounter('x', 'y', 1, '#x', {{ getElementById: () => null }}) }}));
    """
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["afterZero"] == {"item": True, "list": True}
    assert out["items"] == 1 and out["text"] == "Sizi bekleyen bildirim: 3" and out["listHidden"] is False
    assert out["open"] and out["focused"] and out["tabindex"] == "-1" and out["prevented"]
    assert out["missing"] is None
    assert len((STATIC / "js" / "console_work_counters.js").read_text(encoding="utf-8").splitlines()) <= 60


def test_the_three_counters_count_only_what_waits_for_the_operator(tmp_path) -> None:
    """P00 G2: the E66, E71 and E54 counters read their panels' endpoints; a failed read shows no counter."""
    node = shutil.which("node")
    if node is None:  # pragma: no cover - CI without node still runs the static checks above
        pytest.skip("node is not installed")
    module = (STATIC / "js" / "console_work_counters.js").as_uri()
    bodies = {
        "/api/console/report-timeline": {"items": [{"waiting_on": w} for w in ("operator", "citizen", "operator")]},
        "/api/console/escort": {"items": [{"status": "received"}, {"status": "seen"}]},
    }
    script = f"""
      {FAKE_DOM}
      const list = new El('ul', 'work-counters'); list.hidden = true;
      const doc = {{ getElementById: (id) => (id === 'work-counters' ? list : null), createElement: (t) => new El(t),
        querySelector: () => null, focused: null }};
      const m = await import({json.dumps(module)});
      const bodies = {json.dumps(bodies)};
      await m.refreshWorkCounters(async (path) => {{ if (!(path in bodies)) throw new Error('503'); return bodies[path]; }}, doc);
      console.log(JSON.stringify({{ listHidden: list.hidden,
        rows: list.children.map((li) => [li.dataset.counter, li.firstElementChild.textContent, li.hidden]) }}));
    """
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["listHidden"] is False
    assert sorted(out["rows"]) == [["escort", "Yeni destek talebi: 1", False], ["timeline", "Sizi bekleyen bildirim: 2", False]]
