"""Görev 0-b: a short Turkish follow-up is Turkish, and costs no model call.

``guess_language("Peki Kartal'da?")`` once said Portuguese (its "da"), which sent the message to the
emergency model layer (:mod:`nabiz.console.emergency_model`, asked only outside Turkish and English).
"""

from __future__ import annotations

import asyncio

import pytest
from test_console_chat import CLOUD, FakeModel

from nabiz.agent import llm
from nabiz.console import emergency_model
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.emergency_lang import guess_language, pick_card_lang

TURKISH_FOLLOW_UPS = ("Peki Kartal'da?", "Ya Üsküdar'a?", "Yarın da mı?", "Kadıköy'den?")


@pytest.mark.parametrize("message", TURKISH_FOLLOW_UPS)
def test_short_turkish_follow_ups_are_turkish_and_never_reach_the_model(message: str, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeModel()
    monkeypatch.setattr(llm, "chat", fake)
    assert guess_language(message) == "tr"
    assert asyncio.run(emergency_model.model_emergency(message, CLOUD, SpendGuard(BudgetConfig(state_path=None)), env={})) is None
    assert fake.calls == []


@pytest.mark.parametrize(
    ("message", "lang"),
    [("And in Kartal?", "en"), ("Und morgen?", "de"), ("و في كارتال؟", "ar"), ("و در کارتال؟", "fa"), ("12345", None)],
)
def test_other_languages_keep_their_guess(message: str, lang: str | None) -> None:
    assert guess_language(message) == lang
    assert guess_language(message, "en") == lang


def test_a_weak_short_guess_follows_the_conversation_then_turkish() -> None:
    assert guess_language("Peki Kartal?") == "tr"
    assert guess_language("Peki Kartal?", "en") == "en"
    assert guess_language("Wo ist die U-Bahn heute Abend bitte?", "tr") == "de", "a long message keeps its own vote"


def test_the_card_language_is_unchanged() -> None:
    assert pick_card_lang("Hilfe!", frozenset({"de"})) == "de"
    assert pick_card_lang("police!", frozenset({"en", "fr"})) == "en"


def test_a_word_turkish_shares_does_not_make_a_short_message_foreign() -> None:
    assert guess_language("Peki Kartal da?") == "tr"
    assert guess_language("C'è un incendio") == "it", "'un' is Italian's own"
