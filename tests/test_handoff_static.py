"""The "İnsanla görüş" card (js/handoff.js): when it opens, the five-line summary it prepares on the device,
the masking it borrows from E14, and the promises it must not make (nothing is filed or forwarded)."""

from __future__ import annotations

import csv
import importlib
import json
import re

import pytest
from conftest import REPO_ROOT
from test_static_a11y import STATIC, node_json

HANDOFF = {"handoff": "js/handoff.js"}
JS = STATIC / "js" / "handoff.js"
CSS = STATIC / "css" / "handoff.css"
TCKN = "10000000146"


def run(tmp_path, body: str, modules: dict[str, str] | None = None):
    return node_json(tmp_path, modules or HANDOFF, body)


def user(text: str) -> dict:
    return {"role": "user", "text": text}


def reply(unresolved: bool = False, rule_id: str = "", emergency: bool = False) -> dict:
    return {"role": "assistant", "ruleId": rule_id, "unresolved": unresolved, "emergency": emergency}


def summary(tmp_path, turns: list[dict], mask: str = "(t) => t", modules: dict[str, str] | None = None) -> list[str]:
    body = f"console.log(JSON.stringify(handoff.buildSummary({json.dumps(turns)}, {mask})));"
    return run(tmp_path, body, modules).split("\n")


def test_asks_for_person_matches_requests_not_ordinary_questions(tmp_path) -> None:
    positive = [
        "insanla konuşmak istiyorum",
        "Bir temsilciye bağlar mısın?",
        "153'e bağla",
        "Gerçek bir kişiyle görüşmek istiyorum",
        "I want to talk to a human",
        "Temsilciyle görüşmek istiyorum",
    ]
    negative = [
        "500T 34 dakika sonra mı gelir? 153'ü aradım",
        "İnsanlar metroda neden bekliyor?",
        "Bir insanın hakkı ne?",
        "Muhtar temsilcisi kim?",
        "M2 çalışıyor mu?",
        "153 nedir?",
        "Kadıköy'de otopark var mı?",
    ]
    values = run(
        tmp_path,
        f"console.log(JSON.stringify({{pos: {json.dumps(positive)}.map(handoff.asksForPerson), "
        f"neg: {json.dumps(negative)}.map(handoff.asksForPerson)}}));",
    )
    assert values["pos"] == [True] * len(positive), dict(zip(positive, values["pos"], strict=True))
    assert values["neg"] == [False] * len(negative), dict(zip(negative, values["neg"], strict=True))


def offer(tmp_path, cases: list[list[dict]]) -> list:
    return run(tmp_path, f"console.log(JSON.stringify({json.dumps(cases)}.map(handoff.offerReason)));")


def test_one_unresolved_turn_does_not_offer_two_in_a_row_do(tmp_path) -> None:
    u = user("Bu hattın gece seferi var mı?")
    assert offer(
        tmp_path,
        [
            [u, reply(unresolved=True)],
            [u, reply(unresolved=True), u, reply(unresolved=True)],
            [u, reply(unresolved=True), u, reply(), u, reply(unresolved=True)],
        ],
    ) == [None, "unresolved", None]


def test_layer_handoff_rule_opens_the_card(tmp_path) -> None:
    u = user("anlamadım")
    assert offer(tmp_path, [[u, reply(rule_id="layer:handoff")], [u, reply(rule_id="layer:clarify")]]) == ["layer", None]


def test_emergency_turn_never_opens_the_card(tmp_path) -> None:
    asked = user("insanla konuşmak istiyorum")
    assert offer(tmp_path, [[asked, reply(emergency=True)], [asked, reply()]]) == [None, "asked"]


def test_summary_masks_like_python(tmp_path) -> None:
    if not (STATIC / "js" / "pii_badge.js").is_file():
        pytest.skip("E14 pii_badge.js tabanda yok")
    try:
        pii_guard = importlib.import_module("nabiz.console.pii_guard")
    except ImportError:
        pytest.skip("E14 nabiz.console.pii_guard tabanda yok")
    modules = {**HANDOFF, "pii_badge": "js/pii_badge.js"}
    samples = [
        f"TC {TCKN} kartım neden dolmadı?",
        "500T 34 dk sonra mı? 153'ü aradım",
        "Ücret 1500 TL mi, No: 12 kapı mı?",
        "0555 000 00 01 numaramdan arayın",
    ]
    for index, question in enumerate(samples):
        lines = summary(tmp_path, [user(question), reply()], "(t) => pii_badge.maskPii(t).masked", modules)
        assert lines[1] == "Soru: " + pii_guard.mask(question)[0]
        if index == 0:
            assert TCKN not in "\n".join(lines) and "[TC KİMLİK]" in lines[1]
        if index in (1, 2):
            assert lines[1] == f"Soru: {question}"


def test_summary_fails_closed_without_the_masker(tmp_path) -> None:
    lines = summary(tmp_path, [user(f"TC {TCKN} kartım"), reply(unresolved=True)], "null")
    assert lines[1] == "Soru: (kişisel veri denetimi yüklenemedi; sorunuzu kendiniz yazın)"
    assert TCKN not in "\n".join(lines)
    assert lines[0] == "Konu: Genel bilgi" and lines[2] == "İlçe: belirtilmedi"


def test_summary_has_five_ordered_lines_topic_and_district(tmp_path) -> None:
    lines = summary(
        tmp_path,
        [user("Kadıköy'de asansör çalışıyor mu?"), reply(unresolved=True), user("insanla konuşmak istiyorum"), reply()],
    )
    assert [line.split(": ", 1)[0] for line in lines] == ["Konu", "Soru", "İlçe", "Denenen", "İstenen"]
    assert lines[:3] == ["Konu: Asansör ve adımsız erişim", "Soru: Kadıköy'de asansör çalışıyor mu?", "İlçe: Kadıköy"]
    assert lines[3] == "Denenen: İstanbul Nabız asistanına 2 soru soruldu; 1 cevapta asistan doğrulanmış bir cevap veremedi."
    assert lines[4] == "İstenen: Bu konuda bir 153 görevlisinden bilgi almak istiyorum."

    ferry = summary(tmp_path, [user("Üsküdar'dan vapur var mı?"), reply()])
    assert ferry[0] == "Konu: Toplu ulaşım" and ferry[2] == "İlçe: Üsküdar"
    vague = summary(tmp_path, [user("hmm"), reply()])
    assert vague[0] == "Konu: Genel bilgi" and vague[2] == "İlçe: belirtilmedi"
    assert summary(tmp_path, [user("Hatırım için sor"), reply()])[0] == "Konu: Genel bilgi"

    long = summary(tmp_path, [user("a" * 300), reply()])
    # G2: the question is cut at 237 characters plus "...", so 240 after the six-character "Soru: " prefix.
    assert len(long[1]) == len("Soru: ") + 240 and long[1].endswith("...")
    assert len(summary(tmp_path, [user("birinci satır\nikinci satır\r\nüçüncü"), reply()])) == 5

    resolved = summary(tmp_path, [user("M2 çalışıyor mu?"), reply(), user("temsilciye bağlar mısın?"), reply()])
    assert resolved[3] == "Denenen: İstanbul Nabız asistanına 2 soru soruldu."
    assert resolved[1] == "Soru: M2 çalışıyor mu?"
    for text in (lines, resolved):
        assert "kaynak bulunamadı" not in "\n".join(text)


def test_card_has_copy_153_112_and_no_tid_until_verified(tmp_path) -> None:
    values = run(
        tmp_path,
        "console.log(JSON.stringify({"
        "plain: handoff.cardMarkup('Konu: Genel bilgi', {tid: null}),"
        "tid: handoff.cardMarkup('Konu: Genel bilgi', {tid: 'https://example.invalid/tid'}),"
        "script: handoff.cardMarkup('<script>alert(1)</script>', {tid: null})}));",
    )
    plain = values["plain"]
    for needle in (
        'href="tel:153"',
        'href="tel:112"',
        'data-handoff="copy"',
        'data-handoff="close"',
        '<label for="handoff-summary"',
        'role="status"',
        'aria-labelledby="handoff-title"',
        'aria-live="off"',
        'class="handoff-body"',
    ):
        assert needle in plain, needle
    assert "TİD" not in plain and "Çözüm Merkezi" not in plain
    # Tab order follows the markup: textarea, copy, 153, (TİD), 112, close.
    order = [plain.index(s) for s in ("<textarea", '"copy"', '"call"', '"emergency"', '"close"')]
    assert order == sorted(order)
    assert 'data-handoff="tid"' in values["tid"] and 'rel="noopener noreferrer"' in values["tid"]
    assert "&lt;script&gt;" in values["script"] and "<script>" not in values["script"]


def test_tid_href_needs_a_visible_https_link(tmp_path) -> None:
    body = """
const doc = (href) => ({ querySelector: () => (href === undefined ? null : { getAttribute: () => href }) });
console.log(JSON.stringify([handoff.tidHref(doc()), handoff.tidHref(doc('#')),
  handoff.tidHref(doc('https://example.invalid/tid'))]));
"""
    assert run(tmp_path, body) == [None, None, "https://example.invalid/tid"]
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert page.count('<span data-pending="tid" hidden>') == 2


FORBIDDEN = [
    "iletildi",
    "iletilmiştir",
    "oluşturuldu",
    "başvurunuz",
    "kaydınız",
    "talebiniz alındı",
    "gönderildi",
    "sıra numarası",
]


def test_no_claim_of_filing_or_forwarding() -> None:
    for path in (JS, CSS):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\bETA\b", text), path.name
        assert "—" not in text and "–" not in text, path.name
        folded = text.lower()
        for word in FORBIDDEN:
            assert not re.search(r"(?<![^\W\d_])" + re.escape(word) + r"(?![^\W\d_])", folded), (path.name, word)


def test_handoff_never_sends_or_stores() -> None:
    source = JS.read_text(encoding="utf-8")
    for banned in ("localStorage", "sessionStorage", "indexedDB", "fetch(", "XMLHttpRequest", "sendBeacon", "from './api.js'"):
        assert banned not in source, banned
    assert re.findall(r"import\(\s*['\"]([^'\"]+)['\"]\s*\)", source) == ["./pii_badge.js"]
    assert source.count("import(") == 1
    static = re.findall(r"""from\s+['"](\.[^'"]+)['"]""", source)
    assert static and set(static) <= {"./format.js", "./icons.js"}
    for spec in static:
        assert (JS.parent / spec).resolve().is_file()


def test_handoff_css_uses_tokens_big_targets_and_narrow_layout() -> None:
    css = CSS.read_text(encoding="utf-8")
    bare = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(", bare)
    assert "calc(var(--tap) * 1.25)" in bare
    assert "@media (max-width: 30rem)" in bare
    block = re.search(r"\.handoff-card\s*\{[^}]*\}", bare)
    assert block and re.search(r"flex-direction:\s*column", block.group(0))
    assert re.search(r"align-items:\s*stretch", block.group(0))
    assert "animation" not in bare and "transition" not in bare
    assert not re.search(r"width:\s*\d{3,}px", bare)


def test_module_sizes_and_district_list(tmp_path) -> None:
    assert len(JS.read_text(encoding="utf-8").splitlines()) <= 300
    assert len(CSS.read_text(encoding="utf-8").splitlines()) <= 350
    districts = run(tmp_path, "console.log(JSON.stringify(handoff.ILCELER));")
    assert len(districts) == 39 and len(set(districts)) == 39
    with (REPO_ROOT / "data" / "reference" / "places.csv").open(encoding="utf-8") as handle:
        listed = {row["name"] for row in csv.DictReader(handle) if row["kind"] == "district"}
    assert listed, "places.csv lists districts"
    for name in listed:
        assert {"Eyüp": "Eyüpsultan"}.get(name, name) in districts, name
