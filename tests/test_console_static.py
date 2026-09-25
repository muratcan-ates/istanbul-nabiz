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
PAGES = ("index.html", "console.html")
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
    chat = read("js/chat.js")
    assert "Ben İstanbul şehir bilgi asistanıyım ve yapay zekâ kullanıyorum." in chat
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
    assert 'placeholder="İstanbul hakkında ne öğrenmek istiyorsun?"' in question
    assert "autofocus" in question and 'tabindex="0"' in question
    source = read("js/home.js")
    assert 'role="button" tabindex="0"' in source and "button[data-seed]" in source
    assert "requestSubmit()" in source and "localStorage" not in source
    assert "İstanbul ulaşımı için resmî bilgi nerede?" in source


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
    assert source.count("const AI_NOTICE =") == 1
    assert "event === 'session_started'" in source
    assert "if (!sessionStarted)" in source


def test_unknown_and_emergency_answers_do_not_show_provenance_panels() -> None:
    source = read("js/chat.js")
    unknown_path = source[source.index("const unknown ="):source.index("return html;", source.index("const unknown ="))]
    assert "if (!unknown)" in unknown_path
    emergency_path = source[source.index("if (mode === 'redirect'"):source.index("const unknown =")]
    assert "howPanel" not in emergency_path
