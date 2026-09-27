"""A health statement in a citizen's request never reaches the operator, the model, the table or the log.

P02 rule: a health statement is added to no request, operator or calendar; a health condition is KVKK
special category data. The mask is :func:`nabiz.console.health_mask.mask_request`, applied in
:func:`nabiz.console.requests_api._new_request` before anything is stored, translated or categorised.
Functional needs ("tekerlekli sandalye", "adımsız erişim") and place names stay: the operator needs them.
"""

from __future__ import annotations

import json
import logging
import pathlib

import pytest
from test_citizen_requests import ask, client, ledger_entries, model_json, paths  # noqa: F401  (paths is a fixture)
from test_console_chat import CLOUD, FakeModel

from nabiz.agent import llm
from nabiz.console.health_mask import CITIZEN_NOTE, HEALTH_KIND, HEALTH_LABEL, HEALTH_LABEL_OTHER, mask_health, mask_request

RAMP = "Diyabetim var, sokağımızdaki rampa kırık"


@pytest.mark.parametrize(
    ("text", "gone"),
    [
        (RAMP, "diyabet"),
        ("Şeker hastasıyım, durakta bank yok", "hasta"),
        ("Kalp hastasıyım, M4'te asansör var mı?", "hasta"),
        ("Diyalize gidiyorum, Kartal'dan servis var mı?", "diyaliz"),
        ("Annem kanser tedavisi görüyor, otobüs durağı taşındı", "kanser"),
        ("Epilepsim var, metroda ışıklar yanıp sönüyor", "epilepsi"),
        ("HIV pozitifim, sağlık ocağına nasıl giderim?", "hiv"),
        ("Hamileyim, metrobüste yer yok", "hamile"),
        ("İnsülin kullanıyorum, buzdolabı olan bir yer var mı?", "insülin"),
        ("Depresyondayım, parkta gürültü var", "depresyon"),
        ("I have diabetes and the ramp is broken", "diabetes"),
        ("Ich bin Diabetiker, die Rampe ist kaputt", "diabetiker"),
        ("أنا مريض بالسكري والمنحدر مكسور", "سكري"),
        ("У меня диабет, пандус сломан", "диабет"),
    ],
)
def test_health_statements_are_masked_in_five_languages(text: str, gone: str) -> None:
    masked, count, kinds = mask_request(text)
    assert gone not in masked.casefold() and (HEALTH_LABEL in masked or HEALTH_LABEL_OTHER in masked)
    assert count >= 1 and kinds[0] == HEALTH_KIND


def test_the_rest_of_the_sentence_stays() -> None:
    masked, count = mask_health(RAMP)
    assert masked == f"{HEALTH_LABEL}, sokağımızdaki rampa kırık" and count == 1


def test_a_latin_request_in_another_language_keeps_its_language() -> None:
    """The Turkish label's letters would make a German request read as Turkish and skip its translation."""
    from nabiz.console.translate import guess_request_language

    masked, _ = mask_health("Ich bin Diabetiker, die Rampe ist kaputt")
    assert HEALTH_LABEL_OTHER in masked and guess_request_language(masked)[0] != "tr"


@pytest.mark.parametrize(
    "text",
    [
        "Tekerlekli sandalye kullanıyorum, rampa kırık",
        "Adımsız erişim lazım, asansör çalışıyor mu?",
        "Görme engelliyim, sesli anons yok",
        "Kalp Damar Hastanesi'ne otobüs var mı?",
        "Şeker aldım, kalbim seninle",
        "Gebze'ye otobüs var mı?",
        "عسكري",
        "حامل البطاقة",
        "Rakı değil, ramp",
    ],
)
def test_functional_needs_place_names_and_ordinary_words_are_not_masked(text: str) -> None:
    assert mask_request(text) == (text, 0, ())


def test_identity_numbers_are_still_masked_after_the_health_words() -> None:
    masked, count, kinds = mask_request("TC 10000000146, diyabetliyim")
    assert "10000000146" not in masked and "diyabet" not in masked.casefold()
    assert count == 2 and kinds == (HEALTH_KIND, "TC KİMLİK")


def test_the_citizen_note_is_the_decided_sentence() -> None:
    assert CITIZEN_NOTE == "Sağlık bilginiz operatöre gösterilmez."


# ---- the route: queue, console, table, ledger and log ----------------------------------------------


def test_a_health_statement_never_reaches_the_queue_the_table_the_ledger_or_the_log(
    paths: pathlib.Path,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    c = client()
    created = ask(c, RAMP, lang="tr")
    assert created.status_code == 201, created.text
    card = created.json()
    queue = c.get("/api/console/requests").json()
    item = queue["items"][0]
    assert "diyabet" not in json.dumps(queue, ensure_ascii=False).casefold()
    assert "rampa kırık" in item["original"] and HEALTH_LABEL in item["original"]
    assert HEALTH_KIND in item["masked_kinds"] and item["category"] == "Asansör ve erişim"
    assert "diyabet" not in card["question"].casefold()
    assert b"iyabet" not in (paths / "requests.db").read_bytes()
    assert "iyabet" not in json.dumps([e.detail for e in ledger_entries(paths)], ensure_ascii=False)
    assert "iyabet" not in caplog.text.casefold()


def test_the_translation_model_never_sees_the_health_word(paths: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    fake = FakeModel(model_json("de", f"{HEALTH_LABEL}, evimin önündeki rampa kırık"))
    monkeypatch.setattr(llm, "chat", fake)
    c = client(CLOUD)
    assert ask(c, "Ich bin Diabetiker, die Rampe vor meinem Haus ist kaputt").status_code == 201
    assert fake.calls and "diabetiker" not in repr(fake.calls).casefold()
    item = c.get("/api/console/requests").json()["items"][0]
    assert "diabetiker" not in json.dumps(item, ensure_ascii=False).casefold()


def test_a_wheelchair_need_reaches_the_operator_as_written(paths: pathlib.Path) -> None:  # noqa: F811
    text = "Tekerlekli sandalye kullanıyorum, Kadıköy kütüphanesine giden otobüste rampa yok"
    assert ask(client(), text, lang="tr").status_code == 201
    item = client().get("/api/console/requests").json()["items"][0]
    assert item["original"] == text and item["masked_count"] == 0


def test_the_story_three_sentence_keeps_the_need_and_drops_the_diagnosis(paths: pathlib.Path) -> None:  # noqa: F811
    text = "Diyabetim var ve tekerlekli sandalye kullanıyorum, Kadıköy kütüphanesine rampa var mı?"
    c = client()
    assert ask(c, text, lang="tr").status_code == 201
    item = c.get("/api/console/requests").json()["items"][0]
    assert "diyabet" not in str(item).casefold() and "tekerlekli sandalye" in item["original"]
