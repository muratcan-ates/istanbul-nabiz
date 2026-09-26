from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"


def node_json(tmp_path, imports: dict[str, str], body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    lines = [f"import * as {name} from {json.dumps((STATIC / path).as_uri())};" for name, path in imports.items()]
    harness = tmp_path / "easy_read_harness.mjs"
    harness.write_text("\n".join([*lines, body]), encoding="utf-8")
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def glossary():
    return json.loads((STATIC / "data" / "glossary_tr.json").read_text(encoding="utf-8"))


def tr_lower(value: str) -> str:
    return value.replace("I", "ı").replace("İ", "i").lower()


def test_glossary_shape_and_size() -> None:
    data = glossary()
    assert data["version"] == 1 and data["lang"] == "tr" and data["note"]
    assert 35 <= len(data["terms"]) <= 60
    excluded = {"belediye", "ilçe belediyesi", "muhtarlık", "çözüm merkezi", "muafiyet", "kişisel veri"}
    for item in data["terms"]:
        assert set(item) == {"id", "term", "forms", "plain"}
        assert re.fullmatch(r"[a-z]+(?:-[a-z]+)*", item["id"])
        assert item["forms"] and tr_lower(item["term"]) in {tr_lower(form) for form in item["forms"]}
        assert tr_lower(item["term"]) not in excluded
        assert not excluded.intersection(map(tr_lower, item["forms"]))


def test_glossary_has_no_digit_money_or_rights_words() -> None:
    text = " ".join(
        [glossary()["note"], *(value for item in glossary()["terms"] for value in [item["term"], item["plain"], *item["forms"]])]
    )
    assert not re.search(r"\d|₺|\b(?:TL|lira|ücret|ceza|indirim|fiyat|sağlık|yüzde)\b", text, re.I)
    assert not re.search(r"\bhak(kı|ları|larınız|kınız)?\b", text, re.I)
    assert not re.search(r"\b(?:ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık)\b", text, re.I)


def test_glossary_plain_is_one_short_sentence() -> None:
    for item in glossary()["terms"]:
        plain = item["plain"]
        assert plain[0].isupper() and plain.endswith(".") and len(plain) <= 110
        assert not re.search(r"[.!?].+[.!?]", plain)


def test_glossary_terms_and_forms_are_unique() -> None:
    data = glossary()
    ids = [item["id"] for item in data["terms"]]
    terms = [tr_lower(item["term"]) for item in data["terms"]]
    forms = [tr_lower(form) for item in data["terms"] for form in item["forms"]]
    assert len(ids) == len(set(ids))
    assert len(terms) == len(set(terms))
    assert len(forms) == len(set(forms))


def test_glossary_has_no_dash_eta_or_kanca() -> None:
    text = json.dumps(glossary(), ensure_ascii=False)
    assert "—" not in text and "–" not in text
    assert not re.search(r"\bETA\b|\bkanca\b", text, re.I)


def test_split_sentences_keeps_every_character(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"read": "js/easy_read.js"},
        """
const examples = [
  "Hatta bildirilen arıza yok. Seferler sürüyor. Resmî sayfaya bakın.",
  "Saat 12.30'da kalkar. Sonra biner.",
  "Asansör, rampa vb. araçlar. Tamam."
];
console.log(JSON.stringify(examples.map((text) => {
  const parts = read.splitSentences(text);
  return { parts, joined: parts.join('') };
})));
""",
    )
    assert [len(item["parts"]) for item in values] == [3, 2, 2]
    assert all(
        item["joined"] == original
        for item, original in zip(
            values,
            [
                "Hatta bildirilen arıza yok. Seferler sürüyor. Resmî sayfaya bakın.",
                "Saat 12.30'da kalkar. Sonra biner.",
                "Asansör, rampa vb. araçlar. Tamam.",
            ],
            strict=True,
        )
    )


def test_mark_terms_keeps_text_and_matches_whole_words(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"read": "js/easy_read.js"},
        """
const index = read.buildTermIndex({terms:[
  {id:"hat",term:"hat",forms:["hat"],plain:"Araçların izlediği belirli yol veya yön bütünüdür."},
  {id:"istasyon",term:"istasyon",forms:["istasyonda"],plain:"Tren veya metro yolcularının kullandığı durma ve binme yeridir."}
]});
const seen = new Set();
const a = read.markTerms("hatalı; hatta istasyonda, istasyonda.", index, seen);
console.log(JSON.stringify({text:a.map((part)=>part.text).join(""),ids:a.filter((part)=>part.id).map((part)=>part.id)}));
""",
    )
    assert values["text"] == "hatalı; hatta istasyonda, istasyonda."
    assert values["ids"] == ["istasyon"]


def test_should_touch_refuses_protected_and_nested_nodes(tmp_path) -> None:
    value = node_json(
        tmp_path,
        {"read": "js/easy_read.js"},
        """
const fake = (childElementCount, match) => ({
  childElementCount,
  closest(selector) {
    if (selector === read.PROTECTED_SELECTOR && match && selector.split(",").map((part)=>part.trim()).includes(match)) return {};
    return null;
  }
});
console.log(JSON.stringify([
  read.shouldTouch(fake(0, ".quote-exact")),
  read.shouldTouch(fake(1, null)),
  read.shouldTouch(fake(0, null)),
  read.shouldTouch(fake(0, ".is-refused .answer-short")),
  read.PROTECTED_SELECTOR
]));
""",
    )
    assert value[:4] == [False, False, True, False]
    assert all(
        selector in value[4]
        for selector in [".quote-exact", ".quote-box", "blockquote", ".is-refused .answer-short", ".is-refused .ac-fixed"]
    )


def test_easy_read_writes_to_no_quote_node() -> None:
    source = (STATIC / "js" / "easy_read.js").read_text(encoding="utf-8")
    quote_lines = [line for line in source.splitlines() if "quote" in line.lower()]
    assert len(quote_lines) == 1 and "PROTECTED_SELECTOR" in quote_lines[0]
    assert source.count("replaceChildren(") == 1
    body = source.split("function wrapElement", 1)[1]
    assert body.index("if (!shouldTouch(el)) return;") < body.index("replaceChildren(")
    assert "innerHTML" not in source and "outerHTML" not in source


def test_listen_module_writes_nothing_and_calls_no_one() -> None:
    source = (STATIC / "js" / "easy_read_listen.js").read_text(encoding="utf-8")
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "textContent =",
        "insertAdjacent",
        "replaceChildren",
        "replaceWith",
        ".append(",
        ".prepend(",
        "createElement",
        "fetch(",
        "XMLHttpRequest",
        "sendBeacon",
        "WebSocket",
        "MediaRecorder",
        "getUserMedia",
        "SpeechRecognition",
        "localStorage",
    ):
        assert forbidden not in source
    assert "import { pickVoice } from './voice.js'" in source
    assert "'tr-TR'" in source


def test_listen_plan_and_rates(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"read": "js/easy_read.js", "speak": "js/easy_read_listen.js"},
        """
const blocks = [{kind:"answer",text:"İlk cümle. İkinci cümle."},{kind:"quote",text:"Kaynak sözü."}];
const plan = speak.listenPlan(blocks);
const joined = blocks.map((block)=>plan.filter((part)=>part.block === block).map((part)=>part.text).join(""));
const bad = [
  read.parseEasyPrefs("{"), read.parseEasyPrefs('{"version":2,"on":true,"rate":1}'),
  read.parseEasyPrefs('{"version":1,"on":true,"rate":2}')
];
console.log(JSON.stringify({rates:speak.RATES, kinds:plan.map((part)=>part.block.kind), joined, bad}));
""",
    )
    assert values["rates"] == [0.8, 1, 1.2]
    assert values["kinds"] == ["answer", "answer", "quote"]
    assert values["joined"] == ["İlk cümle. İkinci cümle.", "Kaynak sözü."]
    assert values["bad"] == [{"version": 1, "on": False, "rate": 1}] * 3


def test_easy_read_css_and_fonts() -> None:
    css = (STATIC / "css" / "easy_read.css").read_text(encoding="utf-8")
    assert "max-width: 60ch" in css and "line-height: 1.8" in css
    for forbidden in ("@font-face", "font-family", "@keyframes", "animation", "transition"):
        assert forbidden not in css
    assert not re.search(r"#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(|oklch\(", css, re.I)
    assert {path.name for path in (STATIC / "fonts").iterdir()} == {"OFL.txt", "nabiz-sans-tr-v1.woff2"}


def test_both_card_shapes_and_the_quote_only_card(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"read": "js/easy_read.js", "speak": "js/easy_read_listen.js"},
        """
const refusal = (needle) => ({
  childElementCount:0,
  closest(selector) {
    if (selector === read.PROTECTED_SELECTOR && selector.split(",").map((part)=>part.trim()).includes(needle)) return {};
    return null;
  }
});
console.log(JSON.stringify({
  targets:read.TARGET_SELECTOR,
  sources:speak.LISTEN_SOURCES,
  protected:[
    read.shouldTouch(refusal(".is-refused .answer-short")),
    read.shouldTouch(refusal(".quote-exact")),
    read.shouldTouch(refusal(".quote-box"))
  ]
}));
""",
    )
    targets = values["targets"]
    for selector in (".answer-short p", ".answer-card .ac-short p", ".answer-card .ac-steps li", ".answer-card .ac-fixed"):
        assert selector in targets
    sources = values["sources"]
    assert [item["kind"] for item in sources] == ["answer", "quote", "step"]
    assert ".quote-exact" in sources[1]["selector"] and ".quote-box blockquote.quote-text" in sources[1]["selector"]
    assert ".answer-short p" in sources[0]["selector"] and ".answer-card .ac-short p" in sources[0]["selector"]
    chat = (STATIC / "js" / "chat.js").read_text(encoding="utf-8")
    assert "shell.classList.add('is-refused')" in chat
    assert values["protected"] == [False, False, False]
