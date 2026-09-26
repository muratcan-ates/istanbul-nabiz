from __future__ import annotations

import ast
import csv
import json
import re
from importlib import import_module
from pathlib import Path

import pytest

from nabiz.agent.layers import LAYER_KINDS, PHRASES_PATH, TurnLayer, classify_turn, layer_reply, load_phrases

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_IMPORTS = {"__future__", "collections.abc", "functools", "pathlib", "re", "tomllib", "typing", "ibb_mcp.text"}


def _places() -> tuple[str, ...]:
    with (ROOT / "data/reference/places.csv").open(encoding="utf-8", newline="") as source:
        return tuple(row["name"] for row in csv.DictReader(source))


PLACES = _places()

# Every row is part of the brief's frozen acceptance table.
SCENARIOS = [
    pytest.param("Merhaba", [], "greeting", {"lang": "tr", "first_turn": True}, id="g-tr-merhaba"),
    pytest.param("selam!", [], "greeting", {"lang": "tr"}, id="g-tr-selam"),
    pytest.param("İyi günler", [], "greeting", {"lang": "tr"}, id="g-tr-iyi-gunler"),
    pytest.param("Günaydın", ["M2'de arıza var mı?"], "greeting", {"first_turn": False}, id="g-tr-later"),
    pytest.param("Merhaba Nabız", [], "greeting", {"lang": "tr"}, id="g-tr-address"),
    pytest.param("selam selam", [], "greeting", {}, id="g-tr-twice"),
    pytest.param("Hello", [], "greeting", {"lang": "en"}, id="g-en-hello"),
    pytest.param("Good morning!", [], "greeting", {"lang": "en"}, id="g-en-morning"),
    pytest.param("hi there", [], "greeting", {"lang": "en"}, id="g-en-hi-there"),
    # DECISIONS #35: Arabic is not supported; an Arabic greeting or thanks is no small talk and reads as Turkish.
    pytest.param("مرحبا", [], "pass", {"lang": "tr"}, id="p-ar-unsupported-marhaba"),
    pytest.param("السلام عليكم", [], "pass", {"lang": "tr"}, id="p-ar-unsupported-salam"),
    pytest.param("Teşekkürler", ["M2'de arıza var mı?"], "thanks", {"lang": "tr", "first_turn": False}, id="t-tr-tesekkurler"),
    pytest.param("sağ ol", ["M2'de arıza var mı?"], "thanks", {"lang": "tr"}, id="t-tr-sag-ol"),
    pytest.param("Çok teşekkür ederim, iyi günler", ["M2'de arıza var mı?"], "thanks", {"lang": "tr"}, id="t-tr-plus-greeting"),
    pytest.param("Eyvallah", ["M2'de arıza var mı?"], "thanks", {"lang": "tr"}, id="t-tr-eyvallah"),
    pytest.param("Thank you!", ["Is M2 working?"], "thanks", {"lang": "en"}, id="t-en-thank-you"),
    pytest.param("شكرا", ["M2"], "pass", {"lang": "tr"}, id="p-ar-unsupported-shukran"),
    pytest.param("Hey", [], "greeting", {"lang": "tr"}, id="g-tr-hey"),
    pytest.param("Merhaba, M2'de arıza var mı?", [], "pass", {}, id="p-greet-question"),
    pytest.param("Teşekkürler, peki Kadıköy'de otopark var mı?", [], "pass", {}, id="p-thanks-question"),
    pytest.param("Merhaba, yangın var", [], "pass", {}, id="p-greet-emergency"),
    pytest.param("Durak nerede?", [], "unclear", {"ask": "stop", "handoff": False}, id="u-stop"),
    pytest.param("Otobüs ne zaman gelir?", [], "unclear", {"ask": "line"}, id="u-line"),
    pytest.param("Hangi hat?", [], "unclear", {"ask": "line"}, id="u-line-hat"),
    pytest.param("Asansör çalışıyor mu?", [], "unclear", {"ask": "station"}, id="u-station"),
    pytest.param("hmm", [], "unclear", {"ask": "generic"}, id="u-generic"),
    pytest.param("???", [], "unclear", {"ask": "generic"}, id="u-generic-punct"),
    pytest.param("؟", [], "unclear", {"ask": "generic", "lang": "tr"}, id="u-generic-ar-mark"),
    pytest.param("bir sorum var", [], "unclear", {"ask": "generic"}, id="u-generic-sorum"),
    pytest.param("Where is the stop?", [], "unclear", {"ask": "stop", "lang": "en"}, id="u-en-stop"),
    pytest.param("Durak nerede?", ["Kadıköy'de otopark var mı?"], "unclear", {"ask": "stop", "unclear_streak": 1}, id="u-single"),
    pytest.param("hmm", ["Durak nerede?"], "unclear", {"ask": "generic", "unclear_streak": 2, "handoff": True}, id="u-two"),
    pytest.param(
        "???", ["hmm", "Durak nerede?"], "unclear", {"ask": "generic", "unclear_streak": 3, "handoff": True}, id="u-three"
    ),
    pytest.param(
        "hmm", ["Durak nerede?", "M2'de arıza var mı?"], "unclear", {"ask": "generic", "unclear_streak": 1}, id="u-broken"
    ),
    pytest.param("hmm", ["hmm", "Merhaba"], "unclear", {"ask": "generic", "unclear_streak": 1}, id="u-after-greeting"),
    pytest.param("Kadıköy durağı nerede?", [], "pass", {}, id="p-stop-named"),
    pytest.param("500T ne zaman gelir?", [], "pass", {}, id="p-line-coded"),
    pytest.param("Taksim asansör çalışıyor mu?", [], "pass", {}, id="p-station-named"),
    pytest.param("M2", [], "pass", {}, id="p-metro-alone"),
    pytest.param("Engelli kartı başvurusu nasıl yapılır?", [], "pass", {}, id="p-service"),
    pytest.param(
        "Peki M2'de?",
        ["M1'de arıza var mı?"],
        "followup",
        {"message": "M2'de arıza var mı?", "entity": {"type": "metro_line", "value": "M2"}},
        id="f-metro",
    ),
    pytest.param(
        "Ya 15F?",
        ["500T hattında kaç otobüs var?"],
        "followup",
        {"message": "15F hattında kaç otobüs var?", "entity": {"type": "bus_line", "value": "15F"}},
        id="f-bus",
    ),
    pytest.param(
        "Peki Beşiktaş'ta?",
        ["Kadıköy'de otopark var mı?"],
        "followup",
        {"message": "Beşiktaş'ta otopark var mı?", "entity": {"type": "place", "value": "Beşiktaş"}},
        id="f-place",
    ),
    pytest.param(
        "Peki orada hava nasıl?",
        ["Kadıköy'de otopark var mı?"],
        "followup",
        {"message": "Kadıköy hava nasıl?", "entity": {"type": "place", "value": "Kadıköy"}},
        id="f-there",
    ),
    pytest.param(
        "Peki M4'te?", ["M2'de arıza var mı?", "Teşekkürler"], "followup", {"message": "M4'te arıza var mı?"}, id="f-skip-thanks"
    ),
    pytest.param(
        "What about M2?",
        ["Is there a disruption on M1?"],
        "followup",
        {"message": "Is there a disruption on M2?", "lang": "en"},
        id="f-en",
    ),
    pytest.param(
        "Kadıköy",
        ["Durak nerede?"],
        "followup",
        {"message": "Kadıköy Durak nerede?", "entity": {"type": "place", "value": "Kadıköy"}},
        id="c-stop-answer",
    ),
    pytest.param(
        "500T",
        ["Otobüs ne zaman gelir?"],
        "followup",
        {"message": "500T Otobüs ne zaman gelir?", "entity": {"type": "bus_line", "value": "500T"}},
        id="c-line-answer",
    ),
    pytest.param(
        "Taksim",
        ["Asansör çalışıyor mu?"],
        "followup",
        {"message": "Taksim Asansör çalışıyor mu?", "entity": {"type": "place", "value": "Taksim"}},
        id="c-station-answer",
    ),
    pytest.param(
        "12345",
        ["Durak nerede?"],
        "followup",
        {"message": "12345 Durak nerede?", "entity": {"type": "stop_code", "value": "12345"}},
        id="c-stop-code",
    ),
    pytest.param("Kadıköy", ["hmm"], "pass", {}, id="c-after-generic"),
    pytest.param("Peki M2'de?", [], "pass", {}, id="f-no-history"),
    pytest.param("Peki M2'de?", ["Kadıköy'de otopark var mı?"], "pass", {}, id="f-other-type"),
    pytest.param(
        "Kadıköy'de otopark ve hava nasıl?",
        [],
        "split",
        {"parts": ["Kadıköy'de otopark nasıl?", "Kadıköy'de hava nasıl?"]},
        id="s-epic",
    ),
    pytest.param(
        "Evimin (Beşiktaş) havası ve M4 için şu an bir uyarı var mı?",
        [],
        "split",
        {"parts": ["Evimin (Beşiktaş) havası için şu an bir uyarı var mı?", "Evimin (Beşiktaş) M4 için şu an bir uyarı var mı?"]},
        id="s-journey",
    ),
    pytest.param(
        "Kadıköy'de otopark var mı ve Beşiktaş'ta trafik nasıl?",
        [],
        "split",
        {"parts": ["Kadıköy'de otopark var mı", "Beşiktaş'ta trafik nasıl?"]},
        id="s-own-context",
    ),
    pytest.param(
        "Taksim'de otopark, hava ve trafik nasıl?",
        [],
        "split",
        {"parts": ["Taksim'de otopark, hava nasıl?", "Taksim'de trafik nasıl?"]},
        id="s-three",
    ),
    pytest.param("M1 ve M2'de arıza var mı?", [], "pass", {}, id="s-same-domain"),
    pytest.param("Kadıköy ve Beşiktaş'ta otopark var mı?", [], "pass", {}, id="s-no-left-domain"),
    pytest.param(
        "Which metro line serves 4.Levent, and does the station have step-free access?", [], "pass", {}, id="s-en-not-split"
    ),
]


@pytest.mark.parametrize(("message", "history", "kind", "expected"), SCENARIOS)
def test_layer_scenarios(message: str, history: list[str], kind: str, expected: dict[str, object]) -> None:
    turn = classify_turn(message, history, places=PLACES)
    assert turn["kind"] == kind
    for field, value in expected.items():
        assert turn[field] == value
    assert turn["kind"] in LAYER_KINDS


def test_greeting_never_calls_a_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from nabiz.agent import llm

    calls: list[object] = []
    monkeypatch.setattr(llm, "chat", lambda *args, **kwargs: calls.append((args, kwargs)))
    for scenario in SCENARIOS:
        message, history, kind, _ = scenario.values
        if kind in {"greeting", "thanks"}:
            turn = classify_turn(message, history, places=PLACES)
            assert layer_reply(turn) is not None
    assert calls == []


def test_layers_import_no_model_or_network() -> None:
    tree = ast.parse((ROOT / "src/nabiz/agent/layers.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert imported <= ALLOWED_IMPORTS


def _ai_notice() -> str:
    source = (ROOT / "src/nabiz/console/static/js/disclosure.js").read_text(encoding="utf-8")
    match = re.search(r"^const AI_NOTICE = '([^']*)';$", source, re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_layer_replies_never_repeat_the_ai_notice() -> None:
    notice = _ai_notice()
    turns = [
        classify_turn("Merhaba"),
        classify_turn("Merhaba", ["M2'de arıza var mı?"]),
        classify_turn("Teşekkürler"),
        classify_turn("Hello"),
        classify_turn("Thank you!", ["Is M2 working?"]),
        classify_turn("Durak nerede?"),
    ]
    answers = [layer_reply(turn)["answer"] for turn in turns]
    assert all(notice not in answer for answer in answers)
    assert answers[0] == load_phrases()["greeting"]["reply"]["tr"]


def test_layer_replies_never_repeat_localized_ai_notice() -> None:
    try:
        fixed = import_module("nabiz.agent.templates_i18n").FIXED
    except (ImportError, AttributeError):
        pytest.skip("E06 henüz yok")
    notice = fixed["AI_NOTICE"]
    turns = [classify_turn("Hello"), classify_turn("Thank you!", ["Is M2 working?"]), classify_turn("Durak nerede?")]
    for turn in turns:
        assert notice[turn["lang"]] not in layer_reply(turn)["answer"]


def test_ai_notice_has_one_source() -> None:
    source = PHRASES_PATH.read_text(encoding="utf-8")
    assert _ai_notice() not in source
    assert "ai_notice" not in load_phrases()


def test_one_unclear_turn_has_no_handoff_two_have() -> None:
    one = classify_turn("Durak nerede?", places=PLACES)
    two = classify_turn("hmm", ["Durak nerede?"], places=PLACES)
    assert one["handoff"] is False
    assert "153" not in layer_reply(one)["answer"]
    assert two["handoff"] is True
    assert "153" in layer_reply(two)["answer"]
    assert layer_reply(two)["rule_id"] == "layer:handoff"


def test_every_clarify_reply_asks_exactly_one_question() -> None:
    for ask in ("stop", "line", "station", "generic"):
        for lang in ("tr", "en"):
            for handoff in (False, True):
                turn: TurnLayer = {
                    "kind": "unclear",
                    "lang": lang,
                    "message": "hmm",
                    "parts": [],
                    "entity": None,
                    "ask": ask,
                    "unclear_streak": 2 if handoff else 1,
                    "handoff": handoff,
                    "first_turn": True,
                }
                answer = layer_reply(turn)["answer"]
                assert answer.count("?") == 1


def test_followup_reads_only_the_history_it_is_given() -> None:
    with_history = classify_turn("Peki M2'de?", ["M1'de arıza var mı?"], places=PLACES)
    without_history = classify_turn("Peki M2'de?", places=PLACES)
    assert with_history["kind"] == "followup"
    assert without_history["kind"] == "pass"


def test_split_gives_at_most_two_parts() -> None:
    turn = classify_turn("Taksim'de otopark ve hava ve trafik ve metro durumu nasıl?", places=PLACES)
    assert turn["kind"] == "split"
    assert len(turn["parts"]) == 2
    assert all(part.strip() for part in turn["parts"])


def test_no_journey_question_is_small_talk_unclear_or_followup() -> None:
    names = ("journeys.jsonl", "journeys.g2.jsonl", "journeys.karsilastir.jsonl")
    for name in names:
        with (ROOT / "eval" / name).open(encoding="utf-8") as source:
            for line in source:
                question = json.loads(line)["question"]
                turn = classify_turn(question, places=PLACES)
                assert turn["kind"] in {"pass", "split"}, (name, question, turn)


def test_phrase_file_is_complete_and_a_broken_one_fails(tmp_path: Path) -> None:
    phrases = load_phrases()
    assert load_phrases() is phrases
    assert all(lang in phrases["greeting"]["reply"] for lang in ("tr", "en"))
    assert "ar" not in phrases["greeting"]["reply"]
    broken = tmp_path / "selamlar.toml"
    broken.write_text(
        PHRASES_PATH.read_text(encoding="utf-8").replace('en = "Which stop do you mean? Write the stop name or code."\n', ""),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="selamlar.toml: clarify.stop"):
        load_phrases(broken)
    malformed = tmp_path / "malformed.toml"
    malformed.write_text("not = [valid", encoding="utf-8")
    with pytest.raises(ValueError, match="selamlar.toml:"):
        load_phrases(malformed)


def _phrase_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _phrase_strings(item)]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in _phrase_strings(item)]
    return []


def test_layer_texts_have_no_dash_or_abbreviation() -> None:
    all_text = "\n".join(_phrase_strings(load_phrases()))
    assert "\u2014" not in all_text and "\u2013" not in all_text
    assert re.search(r"\bETA\b", all_text, re.IGNORECASE) is None
    numbers = set(re.findall(r"\b\d{3}\b", all_text))
    assert numbers <= {"112", "153", "500"}


def test_layers_never_swallow_emergency_or_refusal() -> None:
    from nabiz.console.policy import emergency_intent, refuses

    messages = (
        "Merhaba, yangın var",
        "Selam, ambulans lazım",
        "Merhaba, bilet ne kadar?",
        "Teşekkürler, İstanbulkart indirimi var mı?",
    )
    for message in messages:
        turn = classify_turn(message, places=PLACES)
        assert turn["kind"] == "pass"
        assert emergency_intent(message) or refuses(message)


def test_rewritten_message_fits_the_request_limit() -> None:
    anchor = "M1'de " + "uzun " * 98 + "arıza var mı?"
    turn = classify_turn("Peki M2'de?", [anchor], places=PLACES)
    assert turn["kind"] == "followup"
    assert len(turn["message"]) <= 1000


def test_chat_answers_a_greeting_without_the_model_once_wired(monkeypatch: pytest.MonkeyPatch) -> None:
    chat_paths = (ROOT / "src/nabiz/console/chat.py", ROOT / "src/nabiz/console/chat_pipeline.py")
    if not any(path.exists() and "classify_turn" in path.read_text(encoding="utf-8") for path in chat_paths):
        pytest.skip("B01 henüz bağlamadı")
    from test_console_chat import CLOUD, FakeModel, ask, client_for, nabiz

    from nabiz.agent import llm

    fixture = nabiz.__wrapped__()
    chat_nabiz = next(fixture)
    fake = FakeModel()
    monkeypatch.setattr(llm, "chat", fake)
    _, final = ask(client_for(chat_nabiz, CLOUD), "Merhaba")
    assert fake.calls == []
    assert final["mode"] == "small_talk"
    assert final["author"] == "kural"
    fixture.close()
