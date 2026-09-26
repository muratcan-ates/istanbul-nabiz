"""The E06 catalogs share the fixed-answer contract and the page's Turkish source text."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import warnings
from html.parser import HTMLParser

import pytest
from conftest import REPO_ROOT

from ibb_mcp.tools import Nabiz
from nabiz.agent.agent import NabizAgent, detect_language
from nabiz.agent.llm import LlmConfig
from nabiz.agent.templates import NO_DATA, OUT_OF_SCOPE
from nabiz.agent.templates_i18n import FIXED, SOURCE_IS_TURKISH, detect_lang, fixed_text, quote_frame, text_dir
from nabiz.console.policy import REFUSAL_TEXT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
I18N = STATIC / "i18n"
LANGS = ("tr", "en", "ar")
E07_KEYS = {
    "dyn.kind_page", "dyn.kind_schedule", "dyn.kind_unknown", "dyn.stale",
    "dyn.listen", "dyn.listen_stopped",
    "dynp.live", "dynp.recorded", "dynp.measured",
}


def _catalog(lang: str) -> dict:
    return json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8"))


def _values(value):
    return value if isinstance(value, list) else [value]


def _flat(catalog: dict) -> str:
    return " ".join(part for value in catalog.values() for part in _values(value))


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class _TextTree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict] = [{"tag": "root", "attrs": {}, "children": []}]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = {"tag": tag, "attrs": dict(attrs), "children": []}
        self.stack[-1]["children"].append(node)
        void_tags = {
            "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"
        }
        if tag not in void_tags:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index]["tag"] == tag:
                self.stack = self.stack[:index]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1]["children"].append(data)


def _tree_nodes(node: dict):
    yield node
    for child in node["children"]:
        if isinstance(child, dict):
            yield from _tree_nodes(child)


def _node_texts(node: dict) -> list[str]:
    parts = []

    def visit(child):
        if isinstance(child, str):
            if child.strip():
                parts.append(_normal(child))
        elif child["tag"] != "svg":
            for nested in child["children"]:
                visit(nested)

    visit(node)
    return parts


@pytest.fixture
def agent(ctx) -> NabizAgent:
    """Use the recorded offline sources and the deterministic agent path."""
    return NabizAgent(Nabiz(ctx), config=LlmConfig(), system_prompt="test prompt")


def test_catalogs_are_valid_json_with_no_empty_value() -> None:
    for lang in LANGS:
        catalog = _catalog(lang)
        assert catalog["meta.lang"] == lang
        assert catalog["meta.dir"] == ("rtl" if lang == "ar" else "ltr")
        for value in catalog.values():
            assert all(isinstance(item, str) and item.strip() for item in _values(value))


def test_catalog_key_sets_are_equal() -> None:
    catalogs = [_catalog(lang) for lang in LANGS]
    keys = set(catalogs[0])
    assert all(set(catalog) == keys for catalog in catalogs)
    assert all("examples" not in catalog for catalog in catalogs)
    assert all("note.answer_lang" in catalog and "switch.ar_draft" in catalog for catalog in catalogs)
    for key in keys:
        if isinstance(catalogs[0][key], list):
            assert len(catalogs[0][key]) == len(catalogs[1][key]) == len(catalogs[2][key])


def test_tr_page_strings_are_the_page_text() -> None:
    parser = _TextTree()
    parser.feed((STATIC / "index.html").read_text(encoding="utf-8"))
    nodes = list(_tree_nodes(parser.stack[0]))
    ids = {node["attrs"].get("id"): node for node in nodes if node["attrs"].get("id")}
    page_text = _normal(
        " ".join(_node_texts(parser.stack[0]))
        + " "
        + " ".join(str(value) for node in nodes for value in node["attrs"].values() if value)
    )
    tr = _catalog("tr")
    for key, value in tr.items():
        if key.startswith(("page.", "band.")):
            for part in _values(value):
                assert _normal(part) in page_text, (key, part)
    for key, element_id in (("page.chat_hint", "chat-hint"), ("page.attribution", "attribution"), ("page.about", "hakkinda")):
        assert tr[key] == _node_texts(ids[element_id])


def test_tr_dynamic_strings_come_from_the_modules() -> None:
    js_dir = STATIC / "js"
    sources = "\n".join(path.read_text(encoding="utf-8") for path in js_dir.glob("*.js") if path.name != "answer_card.js")
    answer_card = js_dir / "answer_card.js"
    tr = _catalog("tr")
    if not answer_card.exists():
        missing = sorted(E07_KEYS)
        warnings.warn(f"E07 bekliyor: {', '.join(missing)}", stacklevel=2)
    else:
        sources += "\n" + answer_card.read_text(encoding="utf-8")
    for key, value in tr.items():
        if not key.startswith(("dyn.", "dynp.")):
            continue
        if key in E07_KEYS and not answer_card.exists():
            continue
        escaped = value.replace("'", "\\'")
        assert value in sources or escaped in sources, (key, value)


def test_fixed_tr_values_match_their_single_sources() -> None:
    assert FIXED["NO_DATA"]["tr"] == NO_DATA["tr"]
    assert FIXED["NO_DATA"]["en"] == NO_DATA["en"]
    assert FIXED["OUT_OF_SCOPE"]["tr"] == OUT_OF_SCOPE["tr"]
    assert FIXED["OUT_OF_SCOPE"]["en"] == OUT_OF_SCOPE["en"]
    assert FIXED["SENSITIVE_REFUSAL"]["tr"] == REFUSAL_TEXT
    chat = (STATIC / "js" / "chat.js").read_text(encoding="utf-8")
    disclosure = (STATIC / "js" / "disclosure.js").read_text(encoding="utf-8")
    unknown = re.search(r'^const UNKNOWN_TEXT = "([^"]*)";$', chat, re.MULTILINE)
    emergency = re.search(r"^const EMERGENCY_TEXT = '([^']*)';$", chat, re.MULTILINE)
    ai_notice = re.search(r"^const AI_NOTICE = '([^']*)';$", disclosure, re.MULTILINE)
    privacy = re.search(r"^const PRIVACY_NOTICE = '([^']*)';$", disclosure, re.MULTILINE)
    warning = re.search(r"^const PII_WARNING = '([^']*)';$", disclosure, re.MULTILINE)
    assert unknown and FIXED["UNKNOWN"]["tr"] == unknown.group(1)
    assert emergency and FIXED["EMERGENCY"]["tr"] == emergency.group(1)
    assert ai_notice and FIXED["AI_NOTICE"]["tr"] == ai_notice.group(1)
    assert privacy and warning
    expected_privacy = [
        "Gizlilik.",
        f"{privacy.group(1)} {warning.group(1)}",
        "Kişisel veriler ve gizlilik: tam metin",
    ]
    assert _catalog("tr")["privacy.band"] == expected_privacy
    assert "Kişisel veriler ve gizlilik: tam metin" in disclosure
    assert "Soruya TC kimlik, kart numarası, sağlık belgesi gibi kişisel bilgileri yazmayın." in disclosure


def test_catalogs_carry_the_fixed_answers_verbatim() -> None:
    for lang in LANGS:
        catalog = _catalog(lang)
        for name in ("NO_DATA", "OUT_OF_SCOPE", "SENSITIVE_REFUSAL", "EMERGENCY", "UNKNOWN", "AI_NOTICE"):
            assert catalog[f"fixed.{name.lower()}"] == FIXED[name][lang]
        assert catalog["quote.source_is_turkish"] == SOURCE_IS_TURKISH[lang]


def test_help_numbers_are_the_same_in_every_language() -> None:
    catalogs = [_catalog(lang) for lang in LANGS]
    for number in ("112", "153"):
        counts = [sum(value.count(number) for value in _flat(catalog).split("\n")) for catalog in catalogs]
        assert counts[0] == counts[1] == counts[2]
    arabic = json.dumps(catalogs[2], ensure_ascii=False)
    assert re.search(r"[٠-٩۰-۹]", arabic) is None


def test_no_forbidden_words_anywhere() -> None:
    texts = [path.read_text(encoding="utf-8") for path in (I18N / "tr.json", I18N / "en.json", I18N / "ar.json")]
    for relative in ("js/i18n.js", "css/rtl.css"):
        path = STATIC / relative
        if path.exists():
            texts.append(path.read_text(encoding="utf-8"))
    texts.extend(value for translations in FIXED.values() for value in translations.values())
    combined = "\n".join(texts)
    assert re.search(r"\bETA\b", combined, re.IGNORECASE) is None
    assert "İBB onaylı" not in combined
    assert "\u2014" not in combined and "\u2013" not in combined
    assert re.search(r"\bkanca\b", combined, re.IGNORECASE) is None
    assert re.search(r"\blog[oö]\b", combined, re.IGNORECASE) is None


@pytest.mark.parametrize(
    ("question", "tool"),
    [
        ("When does the 500T bus arrive at Kartal?", "iett_next_arrivals"),
        ("What facilities does Kartal station have?", "metro_station_info"),
        ("Which car parks near Taksim have space?", "ispark_find_parking"),
        ("What is the air quality in Taksim?", "air_quality_now"),
    ],
)
async def test_english_demo_questions_are_answered_by_a_tool(agent: NabizAgent, question: str, tool: str) -> None:
    assert detect_language(question) == "en"
    assert agent.route(question)[0] == tool
    answer = await agent.ask(question)
    assert answer.tool_calls[0].ok is True
    assert answer.tool_calls[0].name == tool
    assert "doğrulanamadı" not in answer.text.casefold()
    assert "okunamadı" not in answer.text.casefold()


def test_detect_lang_uses_only_script_and_choice() -> None:
    assert detect_lang("متى يصل الباص؟") == "ar"
    assert detect_lang("Taksim'de otopark var mı?") is None
    assert detect_lang("anything", chosen="ar") == "ar"
    assert detect_lang("x", chosen="fr") is None
    assert text_dir("ar") == "rtl"


def test_quote_frame_keeps_the_quote_byte_for_byte() -> None:
    quote = 'İETT şöyle yazar:\n“Güzergâh değişti.”  '
    framed = quote_frame("en", quote, None)
    assert framed == {
        "quote": quote,
        "quote_lang": "tr",
        "url": None,
        "label": "Source text is Turkish.",
    }
    assert framed["quote"] is quote
    assert framed["quote"].encode("utf-8") == quote.encode("utf-8")
    assert quote_frame("tr", quote, None)["label"] is None


def test_fixed_text_falls_back_to_turkish() -> None:
    assert fixed_text("UNKNOWN", "de") == FIXED["UNKNOWN"]["tr"]
    assert fixed_text("unknown", "en") == FIXED["UNKNOWN"]["en"]
    assert fixed_text("sensitive_refusal", "ar") == FIXED["SENSITIVE_REFUSAL"]["ar"]
    with pytest.raises(KeyError):
        fixed_text("input_refusal", "en")


def test_bindings_point_at_keys_and_ids() -> None:
    source = (STATIC / "js" / "i18n.js").read_text(encoding="utf-8")
    bindings = re.findall(r"^\s*\['([^']+)', '([\w.]+)', '(text|lead|segments|aria|placeholder|title)'\],$", source, re.MULTILINE)
    assert len(bindings) >= 30
    catalog = _catalog("tr")
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    disclosure = (STATIC / "js" / "disclosure.js").read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([\w-]+)"', page))
    for selector, key, _mode in bindings:
        assert key in catalog, key
        for element_id in re.findall(r"#([\w-]+)", selector):
            if element_id == "privacy-band":
                assert 'id="privacy-band"' in disclosure
            else:
                assert element_id in ids, (selector, element_id)
    assert re.search(r"^export const AR_REVIEWED = (true|false);$", source, re.MULTILINE)
    assert ".quote-box blockquote" in source and ".chat-msg.is-user .chat-text" in source
    assert ".chat-msg.is-user,'" not in source


def test_catalogs_and_modules_are_served(ctx) -> None:
    from test_console_api import app_client

    nabiz = Nabiz(ctx)
    with app_client(nabiz) as client:
        catalog = client.get("/i18n/ar.json")
        module = client.get("/js/i18n.js")
        stylesheet = client.get("/css/rtl.css")
    assert catalog.status_code == 200
    assert "application/json" in catalog.headers["content-type"]
    assert module.status_code == 200
    assert stylesheet.status_code == 200
    assert "Content-Security-Policy" in module.headers


def test_rtl_css_is_scoped_logical_and_colourless() -> None:
    css = (STATIC / "css" / "rtl.css").read_text(encoding="utf-8")
    physical = r"\b(margin|padding|border)-(left|right)\b|(?<![\w-])(left|right)\s*:|text-align\s*:\s*(left|right)|\bfloat\s*:"
    assert re.search(physical, css) is None
    assert re.search(r"#[0-9a-f]{3,8}\b|(?:rgb|hsl)a?\s*\(|oklch\s*\(", css, re.IGNORECASE) is None
    rules = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    for selector, _declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", rules):
        selector = selector.strip()
        if selector.startswith("@media"):
            continue
        assert '[dir="rtl"]' in selector or '[lang="ar"]' in selector, selector


def test_i18n_js_holds_no_copy() -> None:
    source = (STATIC / "js" / "i18n.js").read_text(encoding="utf-8")
    assert "innerHTML" not in source
    assert re.search(r"[çğıöşüÇĞİÖŞÜ]", re.sub(r"Türkçe", "", source)) is None


def _node_json(tmp_path, script: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    harness = tmp_path / "i18n_harness.mjs"
    harness.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [node, str(harness)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_lookup_falls_back_to_turkish(tmp_path) -> None:
    module = (STATIC / "js" / "i18n.js").as_uri()
    values = _node_json(
        tmp_path,
        f"import {{ lookup }} from {json.dumps(module)};\n"
        "console.log(JSON.stringify([lookup({}, {a:'x'}, 'a'), lookup({a:''}, {a:'x'}, 'a'), lookup({}, {}, 'a')]));",
    )
    assert values == ["x", "x", None]


def test_pick_lang_precedence(tmp_path) -> None:
    module = (STATIC / "js" / "i18n.js").as_uri()
    values = _node_json(
        tmp_path,
        f"import {{ pickLang }} from {json.dumps(module)};\n"
        "console.log(JSON.stringify(["
        "pickLang({url:'https://example.test/?lang=en',stored:'ar',profileLang:'tr'}),"
        "pickLang({url:'?lang=ar',stored:'en',profileLang:'tr'}),"
        "pickLang({url:'?lang=fr',stored:'ar',profileLang:'en'}),"
        "pickLang({url:'?lang=fr',stored:'fr',profileLang:'tr'}),"
        "pickLang({url:'',stored:'fr',profileLang:'en'})]));",
    )
    assert values == ["en", "ar", "ar", "tr", "en"]
