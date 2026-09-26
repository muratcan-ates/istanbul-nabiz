"""The multilingual 112 card (DECISIONS #40): rules per card language, the optional model layer, the card.

No test here reaches a model: ``nabiz.agent.llm.chat`` is replaced by scripted fakes. The card's markup is
built by node from ``static/js/emergency.js``; a test skips when node is missing, as ``test_emergency`` does.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_ROOT

from nabiz.agent import llm
from nabiz.console import emergency_model, policy
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.emergency_lang import card_lang_for, fold_for_emergency, guess_language, rule_match
from nabiz.console.emergency_text import CARD_LANGS, CARD_TEXT, REVIEWED_LANGS, RTL_LANGS, TR_BLOCK, UNVERIFIED_LABEL

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
JS = STATIC / "js" / "emergency.js"
TEXT_JS = STATIC / "js" / "emergency_text.js"
CSS = STATIC / "css" / "emergency.css"
CLOUD = llm.LlmConfig(base_url="http://model.invalid/v1", model="fake-model", provider="openai_compatible")

#: Per card language: messages that must open the card in that language.
POSITIVE = {
    "en": ["Help me!", "My father is not breathing", "There is a fire in the building", "Someone fell on the tracks",
           "Call an ambulance", "car crash near the bridge, people injured"],
    "ru": ["помогите, пожар", "Пожар!", "Вызовите скорую, человек без сознания", "мой отец не дышит", "Помогите!"],
    "de": ["Hilfe, mein Vater hat einen Herzinfarkt", "Es brennt!", "Rufen Sie einen Krankenwagen", "Hilfe!",
           "Meine Mutter ist bewusstlos"],
    "fa": ["کمک کنید آتش سوزی", "آتش‌سوزی در ساختمان", "آمبولانس لازم داریم", "پدرم نفس نمی‌کشد", "کمک!"],
    "ar": ["النجدة حريق", "اتصلوا بالإسعاف", "أبي لا يتنفس", "ساعدوني!", "انهار المبنى"],
    "es": ["ayuda, accidente de coche", "¡Fuego!", "Llamen a una ambulancia", "mi madre no respira", "¡Ayuda!"],
    "fr": ["au secours, il ne respire pas", "Au feu !", "Appelez une ambulance", "Il y a un incendie", "Aidez-moi !"],
    "it": ["aiuto, incidente stradale", "Aiuto!", "Chiamate un'ambulanza", "mio padre non respira", "C'è un incendio"],
    "uk": ["допоможіть, пожежа", "Викличте швидку допомогу", "мій батько не дихає", "Допоможіть!", "Пожежа в будинку"],
}  # fmt: skip

#: Per language: questions a visitor may really ask, with an emergency word in them, that are not emergencies.
NEGATIVE = {
    "en": ["fire sale at the bazaar", "Where is the fire exit?", "Is this a fire hazard?", "help me find the metro",
           "Where is the emergency room?", "No fire here, just asking", "I got it by accident"],
    "ru": ["пожарная лестница план", "Где пожарный выход?", "нет пожара, просто вопрос", "Где находится метро?",
           "помогите найти автобус до Таксима"],
    "de": ["Feuerwerk heute Abend?", "Wo ist die Polizeiwache?", "Kein Feuer, nur eine Frage", "Was tun im Notfall?",
           "Wo finde ich einen Feuerlöscher?"],
    "fa": ["آتش بازی امشب کجاست؟", "ایستگاه آتش نشانی کجاست؟", "برای کمک به توریست‌ها چه خدماتی هست؟",
           "خروج اضطراری کجاست؟"],
    "ar": ["أين مخرج الطوارئ؟", "ما هي أنهار إسطنبول؟", "ساعدوني في العثور على محطة الحافلات", "لا يوجد حريق",
           "فاتورة الغاز"],
    "es": ["fuegos artificiales esta noche", "necesito ayuda con el billete", "¿Dónde está la salida de emergencia?",
           "No hay fuego, solo pregunto"],
    "fr": ["Où est le feu rouge ?", "feu d'artifice ce soir", "Où est la sortie de secours ?", "pas de feu, merci",
           "Je paie à l'aide de ma carte"],
    "it": ["fuochi d'artificio stasera", "Dov'è il pronto soccorso?", "non c'è fuoco, grazie",
           "Dov'è l'uscita di emergenza?"],
    "uk": ["пожежна драбина план", "Де аварійний вихід?", "немає пожежі, просто питаю", "Де знаходиться метро?"],
}  # fmt: skip

GAS = {
    "en": "There is a gas leak in the kitchen", "ru": "Утечка газа в квартире", "de": "Es riecht nach Gas",
    "fa": "بوی گاز میاد", "ar": "تسرب غاز في الشقة", "es": "Huele a gas en la cocina", "fr": "Fuite de gaz chez moi",
    "it": "Fuga di gas in cucina", "uk": "Витік газу в під'їзді",
}  # fmt: skip

#: The smoke list the owner named, with the card each must open (None: no card).
SMOKE = [
    ("помогите, пожар", "ru"), ("Hilfe, mein Vater hat einen Herzinfarkt", "de"), ("کمک کنید آتش سوزی", "fa"),
    ("النجدة حريق", "ar"), ("ayuda, accidente de coche", "es"), ("au secours, il ne respire pas", "fr"),
    ("допоможіть, пожежа", "uk"), ("fire sale at the bazaar", None),
]  # fmt: skip


# --------------------------------------------------------------------------------------
# the rule layer
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(("lang", "message"), [(lang, m) for lang, items in POSITIVE.items() for m in items])
def test_each_language_opens_the_card_in_its_own_language(lang: str, message: str) -> None:
    assert policy.emergency_intent(message), message
    assert policy.emergency_card(message)["lang"] == lang, message


@pytest.mark.parametrize(("lang", "message"), [(lang, m) for lang, items in NEGATIVE.items() for m in items])
def test_each_language_has_questions_that_are_not_emergencies(lang: str, message: str) -> None:
    assert not policy.emergency_intent(message), (lang, message)


@pytest.mark.parametrize(("message", "lang"), SMOKE)
def test_the_owners_smoke_list(message: str, lang: str | None) -> None:
    assert policy.emergency_intent(message) is (lang is not None)
    if lang:
        assert policy.emergency_card(message) == {"lang": lang, "hazard": None}


@pytest.mark.parametrize(("lang", "message"), GAS.items())
def test_a_gas_leak_names_the_gas_hazard_in_every_language(lang: str, message: str) -> None:
    assert policy.emergency_card(message) == {"lang": lang, "hazard": "gas"}


def test_only_gas_gets_the_gas_hazard() -> None:
    for items in POSITIVE.values():
        for message in items:
            assert policy.emergency_card(message)["hazard"] is None, message
    assert policy.emergency_card("gaz kaçağı var") == {"lang": "tr", "hazard": "gas"}


def test_turkish_keeps_its_rules_and_its_card() -> None:
    assert policy.emergency_card("Yangın çıktı, ambulans lazım") == {"lang": "tr", "hazard": None}
    assert policy.emergency_card("Acil yardım lazım")["lang"] == "tr"
    # "acil" alone and "urgent" alone are not emergencies, in either language (the person-context rule).
    for message in ("Acil durum toplanma alanı nerede?", "Is it urgent to renew my card?", "Dringend: Fahrplan?"):
        assert not policy.emergency_intent(message), message
    assert policy.emergency_intent("Urgent, someone collapsed")


def test_folding_covers_cyrillic_arabic_persian_and_latin_accents() -> None:
    assert fold_for_emergency("BRÛLE") == fold_for_emergency("brule") == "brule"
    assert fold_for_emergency("Ёлка") == "елка"
    assert fold_for_emergency("إسعاف") == fold_for_emergency("اسعاف")
    assert fold_for_emergency("حَرِيق") == "حريق"
    assert fold_for_emergency("آتش‌سوزی") == fold_for_emergency("اتش سوزي")
    assert fold_for_emergency("İSTANBUL") == "istanbul"
    assert fold_for_emergency("Hilfe!!") == "hilfe ! !"


def test_rule_match_is_pure_and_names_every_language_that_fired() -> None:
    hit = rule_match("Police! Polizei!")
    assert hit is not None and {"en", "fr", "de"} <= hit.langs and hit.gas is False
    assert rule_match("M2 metrosu çalışıyor mu?") is None


@pytest.mark.parametrize(
    ("message", "lang"),
    [("Где метро?", "ru"), ("Скільки коштує квиток?", "uk"), ("این اتوبوس کجا می‌رود؟", "fa"), ("أين المترو؟", "ar"),
     ("Metro nerede?", "tr"), ("Where is the metro?", "en"), ("Wo ist die U-Bahn?", "de"), ("地铁在哪里", "zh"),
     ("지하철 어디", "ko"), ("12345", None)],
)  # fmt: skip
def test_guess_language(message: str, lang: str | None) -> None:
    assert guess_language(message) == lang


def test_a_language_the_card_does_not_speak_falls_back_to_a_near_one() -> None:
    assert card_lang_for("ru") == "ru" and card_lang_for("az") == "tr" and card_lang_for("uz") == "ru"
    assert card_lang_for("zh") == "en" and card_lang_for(None) == "en" and card_lang_for("FA-IR") == "fa"


# --------------------------------------------------------------------------------------
# the model layer: asked only outside Turkish and English, silent on every failure
# --------------------------------------------------------------------------------------
def reply(content: str, *, provider: str = "openai_compatible") -> dict[str, Any]:
    return {"content": content, "tool_calls": [], "usage": {"prompt_tokens": 90, "completion_tokens": 10}, "provider": provider}


class Scripted:
    def __init__(self, *steps: Any) -> None:
        self.steps = list(steps)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, config: llm.LlmConfig, messages: Any, tools: Any = None, **kw: Any) -> dict[str, Any]:
        self.calls.append({"messages": [dict(m) for m in messages], "kw": kw})
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            return await step()
        return step


def guard(calls: int | None = None) -> SpendGuard:
    return SpendGuard(BudgetConfig(state_path=None) if calls is None else BudgetConfig(daily_calls=calls, state_path=None))


def check(message: str, spend: SpendGuard, env: dict[str, str] | None = None) -> dict[str, str | None] | None:
    return asyncio.run(emergency_model.model_emergency(message, CLOUD, spend, env=env or {}))


def test_the_model_opens_the_card_for_a_language_the_rules_do_not_know(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = Scripted(reply('{"emergency": true, "gas": false, "lang": "zh"}'))
    monkeypatch.setattr(llm, "chat", fake)
    spend = guard()
    assert check("救命！我爸爸晕倒了", spend) == {"lang": "en", "hazard": None}
    assert len(fake.calls) == 1 and fake.calls[0]["kw"]["temperature"] == 0
    assert fake.calls[0]["messages"][0]["role"] == "system" and "JSON" in fake.calls[0]["messages"][0]["content"]
    assert spend.today()["calls"] == 1


def test_a_model_yes_on_gas_names_the_hazard_and_a_known_language(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "chat", Scripted(reply('Sure: {"emergency": true, "gas": true, "lang": "ru"}')))
    assert check("В подъезде странно пахнет, мне плохо", guard()) == {"lang": "ru", "hazard": "gas"}


def test_a_model_no_or_an_unreadable_answer_is_no_card(monkeypatch: pytest.MonkeyPatch) -> None:
    for content in ('{"emergency": false, "lang": "ru"}', "yes", "", '{"emergency": "yes"}'):
        monkeypatch.setattr(llm, "chat", Scripted(reply(content)))
        assert check("Где ближайшая аптека?", guard()) is None, content


def test_turkish_and_english_never_reach_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = Scripted()
    monkeypatch.setattr(llm, "chat", fake)
    for message in ("Metro çalışıyor mu?", "Where is the nearest metro?", "12345"):
        assert check(message, guard()) is None
    assert fake.calls == []


def test_a_timeout_is_silent_and_still_counted(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    async def slow() -> dict[str, Any]:
        await asyncio.sleep(5)
        return reply('{"emergency": true, "lang": "ru"}')

    monkeypatch.setattr(emergency_model, "TIMEOUT_S", 0.05)
    monkeypatch.setattr(llm, "chat", Scripted(slow))
    spend = guard()
    assert check("Где ближайшая аптека?", spend) is None
    assert spend.today()["calls"] == 1, "a timed-out call is spent like any other"
    assert "аптека" not in caplog.text, "the message is never logged"


def test_an_error_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    for error in (llm.LlmError("endpoint said no"), RuntimeError("socket gone")):
        monkeypatch.setattr(llm, "chat", Scripted(error))
        assert check("Где ближайшая аптека?", guard()) is None


def test_the_ceiling_keeps_the_model_out(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = Scripted()
    monkeypatch.setattr(llm, "chat", fake)
    spent = guard(calls=3)
    spent.record(CLOUD.provider, {}, 3)
    assert check("Где ближайшая аптека?", spent) is None
    assert fake.calls == []


def test_the_switch_and_a_missing_model_keep_it_out(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = Scripted()
    monkeypatch.setattr(llm, "chat", fake)
    assert check("Где ближайшая аптека?", guard(), env={"NABIZ_EMERGENCY_MODEL": "0"}) is None
    assert asyncio.run(emergency_model.model_emergency("Где аптека?", llm.LlmConfig(), guard(), env={})) is None
    assert fake.calls == []


def test_the_timeout_is_one_and_a_half_seconds() -> None:
    assert emergency_model.TIMEOUT_S == 1.5


# --------------------------------------------------------------------------------------
# the card: text parity, RTL, the Turkish block, 187 only for gas, accessibility
# --------------------------------------------------------------------------------------
def node_json(body: str, tmp_path: Path) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    harness = tmp_path / "card_harness.mjs"
    harness.write_text(
        f"import * as card from {json.dumps(JS.as_uri())};\nimport * as text from {json.dumps(TEXT_JS.as_uri())};\n{body}\n",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_python_and_js_hold_the_same_text(tmp_path: Path) -> None:
    js = node_json(
        "console.log(JSON.stringify({card: text.CARD_TEXT, reviewed: text.REVIEWED_LANGS, rtl: text.RTL_LANGS, "
        "label: text.UNVERIFIED_LABEL, block: text.TR_BLOCK}));",
        tmp_path,
    )
    assert js == {
        "card": CARD_TEXT, "reviewed": list(REVIEWED_LANGS), "rtl": list(RTL_LANGS), "label": UNVERIFIED_LABEL, "block": TR_BLOCK,
    }  # fmt: skip
    keys = set(CARD_TEXT["tr"])
    assert all(set(texts) == keys for texts in CARD_TEXT.values())
    assert all("{coords}" in texts[kind] for texts in CARD_TEXT.values() for kind in ("shown", "copied", "copyfail"))


def test_every_card_language_has_rules_and_the_list_has_at_most_ten() -> None:
    from nabiz.console.emergency_vocab import VOCAB

    assert CARD_LANGS[0] == "tr" and len(CARD_LANGS) <= 10
    assert set(VOCAB) == set(CARD_LANGS) - {"tr"}


def test_every_card_is_whole_rtl_where_needed_and_labelled_when_unchecked(tmp_path: Path) -> None:
    cards = node_json(
        "const out = {};\nfor (const lang of Object.keys(text.CARD_TEXT)) {\n"
        "  out[lang] = {plain: card.cardMarkup(lang), gas: card.cardMarkup(lang, 'gas')};\n}\n"
        "console.log(JSON.stringify(out));",
        tmp_path,
    )
    assert set(cards) == set(CARD_LANGS)
    for lang, markup in cards.items():
        plain, gas = markup["plain"], markup["gas"]
        direction = "rtl" if lang in RTL_LANGS else "ltr"
        assert f'lang="{lang}" dir="{direction}"' in plain, lang
        assert CARD_TEXT[lang]["title"] in plain and CARD_TEXT[lang]["show"] in plain
        # The Turkish block on every card, left to right and in Turkish even inside an RTL card.
        assert f'lang="tr" dir="ltr" tabindex="-1"><p class="emergency-tr-plea">{TR_BLOCK["plea"]}</p>' in plain
        assert 'data-act="grow"' in plain and 'aria-controls="emergency-tr"' in plain
        # 187 only on the gas card: once as a link after 112, once in the Turkish block.
        assert "187" not in plain and TR_BLOCK["gas"] not in plain
        assert re.findall(r'href="(tel:[^"]+)"', plain) == ["tel:112", "tel:153"]
        assert re.findall(r'href="(tel:[^"]+)"', gas) == ["tel:112", "tel:187", "tel:153"]
        assert TR_BLOCK["gas"] in gas and CARD_TEXT[lang]["gas"] in gas
        assert (UNVERIFIED_LABEL in plain) is (lang not in REVIEWED_LANGS), lang


def test_the_card_never_changes_the_page_language_or_direction() -> None:
    source = JS.read_text(encoding="utf-8")
    assert "documentElement.dir" not in source and "documentElement.lang =" not in source
    assert "setAttribute('dir'" not in source and "setAttribute('lang'" not in source


def test_accessibility_of_the_card(tmp_path: Path) -> None:
    markup = node_json("console.log(JSON.stringify(card.cardMarkup('ru', 'gas')));", tmp_path)
    required = (
        'role="alertdialog"', 'aria-modal="true"', 'aria-labelledby="emergency-title"', 'aria-describedby="emergency-desc"',
        'aria-live="assertive"', 'role="status"', 'aria-pressed="false"',
    )  # fmt: skip
    for item in required:
        assert item in markup, item
    source = JS.read_text(encoding="utf-8")
    assert "card.querySelector('.emergency-call').focus();" in source, "the call button takes the focus on open"
    assert ".textContent = CARD_TEXT[selectedLang].live" in source, "the live region speaks the card language"
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"\.emergency-card a,\s*\.emergency-card button\s*\{[^}]*min-height:\s*48px", css)
    assert re.search(r"\.emergency-call\s*\{[^}]*min-height:\s*64px", css)
    assert re.search(r"\.is-grown \.emergency-tr p\s*\{[^}]*font-size", css)


def test_the_grow_button_toggles_and_says_so(tmp_path: Path) -> None:
    values = node_json(
        "const classes = new Set(); const attrs = {};\n"
        "const button = {setAttribute: (k, v) => { attrs[k] = v; }};\n"
        "const classList = {contains: (c) => classes.has(c), toggle: (c, on) => on ? classes.add(c) : classes.delete(c)};\n"
        "const fake = {classList,\n"
        "  querySelector: (s) => s.includes('grow') ? button : {scrollIntoView() {}}};\n"
        "const first = card.toggleTurkish(fake); const pressed = attrs['aria-pressed'];\n"
        "const second = card.toggleTurkish(fake);\n"
        "console.log(JSON.stringify([first, pressed, second, attrs['aria-pressed'], classes.has('is-grown')]));",
        tmp_path,
    )
    assert values == [True, "true", False, "false", False]


def test_rtl_coordinates_stay_left_to_right(tmp_path: Path) -> None:
    values = node_json(
        "console.log(JSON.stringify([card.locationMessage('shown', '41.01235, 28.97612', 'ar'), "
        "card.locationMessage('shown', '41.01235, 28.97612', 'ru'), card.locationMessage('denied', null, 'fa')]));",
        tmp_path,
    )
    assert "⁦41.01235, 28.97612⁩" in values[0]
    assert values[1] == "Ваше местоположение: 41.01235, 28.97612. Продиктуйте эти цифры службе 112."
    assert values[2] == CARD_TEXT["fa"]["denied"]


def test_card_text_has_no_dash_and_no_forbidden_number() -> None:
    blob = json.dumps(CARD_TEXT, ensure_ascii=False) + TEXT_JS.read_text(encoding="utf-8")
    assert "—" not in blob and "–" not in blob
    assert not re.search(r"\b(?:155|110)\b", blob)
