from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import REPO_ROOT

from nabiz.agent.templates_i18n import FIXED
from nabiz.console import policy
from nabiz.console.emergency import EMERGENCY_LINES, classify, fold_same_length

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
JS = STATIC / "js" / "emergency.js"
CSS = STATIC / "css" / "emergency.css"
PYTHON = REPO_ROOT / "src" / "nabiz" / "console" / "emergency.py"

POSITIVE_MESSAGES = (
    "Gaz kokusu var",
    "Doğalgaz kokuyor",
    "Bina çatladı",
    "Binada çatlak oluştu, bina çöküyor",
    "Annem bayıldı",
    "Adam bayılmış",
    "Polis çağırın",
    "Elektrik çarptı",
    "Çocuk zehirlendi",
    "İmdat!",
    "Yardım edin!",
    "Yardım edin",
    "Enkaz altında kaldı",
    "انهار المبنى",
    "Yaralı yok ama yangın var",
    "Acil ambulans lazım",
    "Someone fell on the tracks",
    "There is a gas leak",
    "My father is not breathing",
    "حريق في المبنى",
    "اتصلوا بالإسعاف",
    "لا يتنفس",
    "تسرب غاز في الشقة",
    "Annem düştü",
    "Biri düştü",
    "Çocuğum düştü",
    "Kalp krizi geçiriyor",
    "Nefes alamıyorum",
    "Boğuluyorum",
    "Bilincini kaybetti",
    "Kanıyor",
    "Kanama var",
    "Kaza oldu",
    "Kazası ağır",
    "İntihar girişimi var",
    "Saldırıya uğradı",
    "Gaz kaçağı var",
    "gaz kaçağı var",
    "Doğalgaz kaçağı var galiba",
    "Evde gaz kaçıyor",
    "Mutfakta doğalgaz sızıntısı var",
    "Doğalgaz kokusu var",
    "Bina çatlağı oluştu",
    "Bina çöktü",
    "Bina çökmüş",
    "Binada bina çatlağı var",
    "Elektrik çarpması oldu",
    "Çocuk zehirlenmiş",
    "Acil yardım lazım",
    "Acil doktor çağırın",
    "Bıçakla yaralandı",
    "Polise haber verin",
    "Bir yaralı var",
    "Yaralanma oldu",
    "Yaralandı",
    "Biri raylara düştü",
    "Acil hastaneye götürün",
    "Acil kaza oldu",
    "Acil yaralı var",
    "Saldırı var",
    "Doğalgaz kokusu geldi",
    "Gaz kokuyor",
    "Polis çağırın, yaralı var",
    "Kalp durdu",
    "Bayılıyorum",
    "Bayıldı",
    "Şiddet var",
    "There is a gas leak in the kitchen",
    "I smell gas",
    "There is a smell of gas",
    "The person is injured",
    "An ambulance is needed",
    "Police, please",
    "An accident happened",
    "Someone is unconscious",
    "I am choking",
    "Someone is drowning",
    "Someone was stabbed",
    "Possible overdose",
    "Emergency help is needed",
    "A fire started",
    "Can't breathe",
    "Cannot breathe",
    "Bleeding heavily",
    "نجدة!",
    "حادث خطير",
    "نزيف شديد",
    "أغمي عليه",
    "رائحة الغاز في الشقة",
    "ساعدوني!",
    "انهار البناء",
    "انهار السقف",
)

NEGATIVE_MESSAGES = (
    "Acil değil, sadece soruyorum",
    "Acil servis saatleri nedir?",
    "Yangın merdiveni nerede?",
    "Gaz faturası nereden ödenir?",
    "Polisiye dizi önerir misin?",
    "Şiddetli yağmur uyarısı var mı?",
    "Bayilik başvurusu nasıl yapılır?",
    "Kalp hastanesine nasıl giderim?",
    "Kazan dairesi nerede?",
    "Yangın yok, merak ettim",
    "Lütfen yardım edin, otobüs kaçta geçer?",
    "Lütfen yardım edin, Kadıköy'e nasıl giderim?",
    "Enkaz kaldırma başvurusu nasıl yapılır?",
    "Fiyat düştü",
    "Proje çöktü",
    "Otobüs fiyatı düştü mü?",
    "Seferlerin sayısı düştü mü?",
    "Acil durum toplanma alanı nerede?",
    "Acil çıkış hangi tarafta?",
    "Acil bir durum değil",
    "Yangın çıkış kapısı nerede?",
    "Yangın tüpü nasıl kullanılır?",
    "Yangın söndürme eğitimi ne zaman?",
    "Yangın sigortası nasıl alınır?",
    "Gaz sayacı nerede?",
    "Kalp merkezine nasıl giderim?",
    "Doğalgaz faturası nereden ödenir?",
    "Doğalgaz aboneliği nasıl yapılır?",
    "Gaz faturası nereden ödenir?",
    "Kanama yok",
    "Kaza olmadı",
    "Yaralı yok",
    "İntihar olmadı",
    "Polisiye roman önerisi",
    "Bayilik ofisinin adresi nedir?",
    "Şiddetli rüzgar uyarısı var mı?",
    "Acil servis randevusu nasıl alınır?",
    "Acil çıkış kapısı açık mı?",
    "Enkaz kaldırma ekibi başvurusu",
    "Yangın merdivenleri yönetmeliği nedir?",
    "Gaz faturası ödeme noktası nerede?",
    "Kalp hastane randevusu nasıl alınır?",
    "Hastaneye nasıl giderim?",
    "Where is the fire exit?",
    "It is not an emergency, when does the ferry leave?",
    "Emergency room opening hours?",
    "Where is the fire escape?",
    "No fire here",
    "We are not bleeding",
    "Where is the emergency assembly point?",
    "I have no gas leak",
    "I am not injured",
    "No accident happened",
    "Emergency phone number",
    "The gas bill is due",
    "أين مخرج الطوارئ؟",
    "ليست حالة طوارئ",
    "فاتورة الغاز",
    "ما هي أنهار إسطنبول؟",
    "ساعدوني في العثور على محطة الحافلات",
    "قسم طوارئ المستشفى في أي طابق؟",
    "لا حالة طوارئ",
    "ليس هناك حريق",
    "لا يوجد تسرب غاز",
)


@pytest.mark.parametrize("message", POSITIVE_MESSAGES)
def test_positive_messages_are_emergencies(message: str) -> None:
    assert classify(message)["emergency"], message


@pytest.mark.parametrize("message", NEGATIVE_MESSAGES)
def test_negative_messages_are_not_emergencies(message: str) -> None:
    assert not classify(message)["emergency"], message


def test_lines_are_only_153() -> None:
    # Owner's decision, 30 Sep 2026: the card names 153 only; 112 and 187 are gone from the server side.
    result = classify("Yangın çıktı")
    assert result["lines"] == ["153"]
    result["lines"].clear()
    assert classify("Yangın çıktı")["lines"] == ["153"]
    assert classify("Acil değil")["lines"] == []
    forbidden = re.compile(r"\b(?:155|110)\b")
    for path in (PYTHON, JS, CSS):
        assert not forbidden.search(path.read_text(encoding="utf-8")), path
    for path in (PYTHON, JS, CSS):
        assert not re.search(r"\b(?:112|187)\b", path.read_text(encoding="utf-8")), path
    assert JS.read_text(encoding="utf-8").count('href="tel:187"') == 0
    assert EMERGENCY_LINES == ("153",)


def test_no_emergency_line_is_left_on_the_server_side() -> None:
    # Owner's decision, 30 Sep 2026: Nabız never sends anyone to 112 or İGDAŞ 187; the card names 153 only.
    backend = [path for suffix in ("*.py", "*.md", "*.toml") for path in (REPO_ROOT / "src").rglob(suffix)]
    offenders = [str(path) for path in backend if re.search(r"\b(?:112|187)\b", path.read_text(encoding="utf-8"))]
    assert offenders == []


def test_no_emergency_line_is_left_on_the_page() -> None:
    # Owner's decision, 30 Sep 2026: the page never names 112 or İGDAŞ 187 (text, tel: link, key or selector).
    skip = {"vendor", "images", "fonts", "icons"}
    page = [
        path for path in STATIC.rglob("*")
        if path.is_file() and path.suffix in {".js", ".css", ".html", ".json", ".webmanifest"}
        and not skip.intersection(path.relative_to(STATIC).parts)
    ]
    offenders = [str(path) for path in page if re.search(r"\b(?:112|187)\b", path.read_text(encoding="utf-8"))]
    assert page and offenders == []


def test_every_policy_term_is_an_emergency() -> None:
    terms = [*policy.EMERGENCY_TERMS["acil"], *policy._EMERGENCY_WORDS, *policy._EMERGENCY_STEMS]
    for term in terms:
        assert classify(term)["emergency"], term


def test_no_journey_question_is_an_emergency() -> None:
    for path in sorted((REPO_ROOT / "eval").glob("journeys*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                assert not classify(row["question"])["emergency"], (path.name, row["id"])


def test_fold_keeps_length() -> None:
    for value in ("İSTANBUL", "ısırgan", "Straße", "ŞİDDET", "İ", "حَرِيق", "طوارئ"):
        assert len(fold_same_length(value)) == len(value)
    assert fold_same_length("İıI") == "iii"


def test_word_boundaries_and_negation() -> None:
    checks = {
        "polisiye": False,
        "polise haber verin": True,
        "kazan": False,
        "kaza oldu": True,
        "acil değil": False,
        "Yaralı yok ama yangın var": True,
        "ليست حالة طوارئ": False,
        "Lütfen yardım edin, otobüs kaçta geçer?": False,
        "Yardım edin!": True,
        "ما هي أنهار إسطنبول؟": False,
        "انهار المبنى": True,
        "Enkaz kaldırma başvurusu nasıl yapılır?": False,
        "Enkaz altında kaldı": True,
    }
    for message, expected in checks.items():
        assert classify(message)["emergency"] is expected, message


def test_classifier_imports_no_model_or_network() -> None:
    tree = ast.parse(PYTHON.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
    assert imports <= {"__future__", "re", "dataclasses", "typing", "ibb_mcp.text"}
    assert not {"nabiz.agent", "httpx", "openai", "llm"} & imports


def test_result_shape() -> None:
    assert set(classify("").keys()) == {"emergency", "lines"}
    assert classify("") == {"emergency": False, "lines": []}
    assert classify("x" * 1000)["emergency"] is False


def test_emergency_assets_exist_and_imports_resolve() -> None:
    assert JS.is_file()
    assert CSS.is_file()
    source = JS.read_text(encoding="utf-8")
    for imported in re.findall(r"from\s+['\"](\./[^'\"]+\.js)['\"]", source):
        assert (JS.parent / imported.removeprefix("./")).is_file(), imported


def node_json(body: str, tmp_path: Path) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    harness = tmp_path / "emergency_harness.mjs"
    harness.write_text(
        f"import * as emergency from {json.dumps(JS.as_uri())};\n{body}\n",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_card_markup_has_the_actions(tmp_path: Path) -> None:
    values = node_json(
        "console.log(JSON.stringify([emergency.cardMarkup(), emergency.cardMarkup('en'), "
        "emergency.cardMarkup('ar'), emergency.cardMarkup('xx')]));",
        tmp_path,
    )
    tr, en, arabic, unknown = values
    for required in (
        'href="tel:153"', "Konumumu göster", 'data-act="copy"',
        "Acil değil, geri dön", 'role="alertdialog"', 'aria-live="assertive"', "Resmî İBB hizmeti değildir",
    ):
        assert required in tr
    assert re.findall(r'href="(tel:[^"]+)"', tr) == ["tel:153"]
    assert "Nabız acil durumlarda yardımcı olamaz" in tr and "İBB'ye 153'ten ulaşabilirsiniz." in tr
    assert "Call 153" in en and "Not an official İBB service" in en
    # DECISIONS #40 (supersedes #35 for the card only): Arabic is a card language again, right to left inside
    # the card; an unknown code still falls back to Turkish.
    assert 'lang="ar" dir="rtl"' in arabic and "اتصل بالرقم 153" in arabic
    assert re.findall(r'href="(tel:[^"]+)"', arabic) == ["tel:153"]
    assert unknown == tr


def test_the_gas_card_is_the_plain_card_with_153_only(tmp_path: Path) -> None:
    values = node_json(
        "console.log(JSON.stringify([emergency.cardMarkup('tr', 'gas'), emergency.cardMarkup('en', 'gas'), "
        "emergency.cardMarkup('tr', null), emergency.cardMarkup('tr', 'fire')]));",
        tmp_path,
    )
    gas_tr, gas_en, plain, other = values
    # Owner's decision, 30 Sep 2026: a gas hazard gets the same card; no İGDAŞ 187 and no 112.
    assert gas_tr == plain and other == plain
    assert re.findall(r'href="(tel:[^"]+)"', plain) == ["tel:153"]
    assert re.findall(r'href="(tel:[^"]+)"', gas_en) == ["tel:153"]
    assert not re.search(r"\b(?:112|187)\b", gas_tr + gas_en)


def test_format_coords_and_messages(tmp_path: Path) -> None:
    values = node_json(
        "console.log(JSON.stringify([emergency.formatCoords(41.0123456, 28.9761234), "
        "emergency.formatCoords(NaN, 1), emergency.formatCoords(91, 0), "
        "emergency.locationMessage('denied'), emergency.locationMessage('denied', null, 'en'), "
        "emergency.locationMessage('shown', '41.01235, 28.97612', 'xx'), "
        "emergency.pickLang('en-US'), emergency.pickLang(''), emergency.pickLang('ar'), emergency.pickLang('xx')]));",
        tmp_path,
    )
    assert values == [
        "41.01235, 28.97612", None, None,
        "Konum alınamadı.",
        "Could not get your location.",
        "Konumunuz: 41.01235, 28.97612.",
        "en", "tr", "ar", "tr",
    ]


def test_emergency_js_never_sends_stores_or_sounds() -> None:
    source = JS.read_text(encoding="utf-8")
    forbidden = (
        "fetch", "XMLHttpRequest", "sendBeacon", "WebSocket", "localStorage", "sessionStorage", "indexedDB",
        "./api.js", "vibrate", "Audio", "AudioContext", "speechSynthesis", "watchPosition",
    )
    for phrase in forbidden:
        assert phrase not in source, phrase
    assert source.count("getCurrentPosition") == 1
    assert "writeText" in source
    assert "nabiz:emergency" in source
    assert "is-emergency" in source
    assert "new MutationObserver" in source


def _css_block(source: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{([^{{}}]*)\}}", source)
    assert match, f"missing CSS selector: {selector}"
    return match.group(1)


def _properties(block: str) -> dict[str, str]:
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block))


def _resolve(value: str, properties: dict[str, str], fallbacks: dict[str, str]) -> str:
    match = re.fullmatch(r"var\((--[\w-]+)\)", value.strip())
    if match:
        name = match.group(1)
        return _resolve(properties.get(name, fallbacks.get(name, "")), properties, fallbacks)
    return value.strip()


def _luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_emergency_css_contrast_and_motion() -> None:
    source = CSS.read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}|\b(?:rgb|hsl|oklch)\s*\(", source)
    assert not re.search(r"animation|transition|@keyframes", source, re.IGNORECASE)
    call = _css_block(source, ".emergency-card .emergency-call")
    assert re.search(r"min-height\s*:\s*64px\s*;", call)
    assert all(int(value) <= 320 for value in re.findall(r"(?:min-)?width\s*:\s*(\d+)px", source))

    token_source = (STATIC / "css" / "tokens.css").read_text(encoding="utf-8")
    light = _properties(_css_block(token_source, ":root"))
    dark = _properties(_css_block(token_source, ':root[data-theme="dark"]'))
    fallback = {**light, **dark}
    light_card = _properties(_css_block(source, ".emergency-card"))
    dark_card = _properties(_css_block(source, ':root[data-theme="dark"] .emergency-card'))
    for card, tokens in ((light_card, light), (dark_card, fallback)):
        background = _resolve(card["--emergency-bg"], tokens, light)
        ink = _resolve(card["--emergency-ink"], tokens, light)
        call_background = _resolve(card["--emergency-call-bg"], tokens, light)
        call_ink = _resolve(card["--emergency-call-ink"], tokens, light)
        assert _contrast(background, ink) >= 7
        assert _contrast(call_background, call_ink) >= 7


def test_no_dash_or_eta_in_emergency_assets() -> None:
    for path in (PYTHON, JS, CSS):
        source = path.read_text(encoding="utf-8")
        assert "\u2014" not in source
        assert "\u2013" not in source
        assert not re.search(r"\bETA\b", source)


# ---- KARAR 5: a stated condition next to an everyday question (Görev 0-c) ---------------------------------
# Safety direction: when in doubt the card opens. A missed emergency costs more than a false alarm, so an
# acute sign anywhere in the message keeps the rules as they were, and with a stated condition opens the
# card by itself; only a condition with nothing acute next to it is set aside.
from nabiz.console import emergency_lang  # noqa: E402

CHRONIC_QUESTIONS = (
    "Kalp hastasıyım, M4'te asansör var mı?",
    "Diyaliz hastasıyım, Kadıköy'den Kartal'a nasıl giderim?",
    "Şeker hastasıyım, Üsküdar'a hangi otobüs gider?",
    "I have a heart condition, is there a lift at Kadıköy?",
)
ACUTE_WITH_CONDITION = (
    "Kalp hastasıyım, göğsüm çok ağrıyor",
    "Diyabetim var, bayılacak gibiyim",
    "Annem nefes alamıyor",
    "Kalp hastası babam yere yığıldı",
    "I have diabetes and I feel faint",
    "I have a heart condition and my chest hurts",
    "Ich bin Diabetiker und bin gestürzt",
    "У меня диабет, мне очень плохо",
    "أنا مريض بالسكري ولا أستطيع التنفس",
)


@pytest.mark.parametrize("message", CHRONIC_QUESTIONS)
def test_a_stated_condition_with_an_everyday_question_is_answered_not_redirected(message: str) -> None:
    assert not policy.emergency_intent(message)
    assert not policy.refuses(message), "the question is judged, not the person"
    assert emergency_lang.chronic_note(message) == FIXED["EMERGENCY"]["tr"]
    assert "112" not in emergency_lang.chronic_note(message)


@pytest.mark.parametrize("message", ACUTE_WITH_CONDITION)
def test_an_acute_sign_still_opens_the_card(message: str) -> None:
    assert policy.emergency_intent(message)


def test_medical_advice_after_a_condition_stays_refused() -> None:
    assert policy.refuses("Diyabetim var, hangi ilacı kullanmalıyım?")
    assert policy.refuses("Kalp hastasıyım, ilacımı ne zaman almalıyım?")
    assert policy.refuses("hastasıyım"), "a bare statement is refused as before"


def test_without_a_condition_the_rules_are_as_they_were() -> None:
    assert policy.emergency_intent("Kalp krizi geçiriyor")
    assert policy.emergency_intent("Yangın var")
    assert emergency_lang.without_calm_condition("M4'te asansör var mı?") == "M4'te asansör var mı?"
    assert emergency_lang.chronic_note("M4'te asansör var mı?") is None


def test_the_chat_answers_the_question_on_the_rules_path() -> None:
    """The rules path runs the same tool it runs without the statement; no emergency card, no refusal."""
    import httpx
    from conftest import offline_settings, refuse_network
    from fastapi.testclient import TestClient
    from test_console_chat import ask

    from ibb_mcp.cache import TTLCache
    from ibb_mcp.http import PoliteClient
    from ibb_mcp.sources.base import SourceContext
    from ibb_mcp.tools import Nabiz
    from nabiz.agent import llm
    from nabiz.console.app import build_console_app
    from nabiz.console.budget import BudgetConfig, SpendGuard

    context = SourceContext.create(
        client=PoliteClient(transport=httpx.MockTransport(refuse_network)), cache=TTLCache(), settings=offline_settings()
    )
    app = build_console_app(nabiz=Nabiz(context), llm_config=llm.LlmConfig(), guard=SpendGuard(BudgetConfig(state_path=None)))
    with TestClient(app) as client:
        stream, final = ask(client, "Kalp hastasıyım, M4'te asansör var mı?")
        _, plain = ask(client, "M4'te asansör var mı?")
    assert final["emergency"] is False and final["refused"] is False and final["mode"] == "answer"
    assert [data["name"] for kind, data in stream if kind == "tool"][:1] == ["metro_status"]
    assert final["answer"] == plain["answer"]


@pytest.mark.parametrize(
    "message",
    ["Kalp hastasıyım bugün yürüyebilir miyim?", "I have asthma; is it safe for me to go outside today?",
     "Hava kirliliği astımıma dokunur mu?"],
)  # fmt: skip
def test_health_advice_after_a_condition_is_refused_without_a_travel_question(message: str) -> None:
    assert policy.refuses(message)
