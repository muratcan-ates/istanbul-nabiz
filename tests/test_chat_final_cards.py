"""P00 D2a: the chat ``final`` carries the P01 cards, validated and bounded, and never on an emergency."""

from __future__ import annotations

import json
import time

from nabiz.console import chat_cards
from nabiz.console.chat_pipeline import FinalFields, emergency_events, empty_how, final_body


def card(title: str, **changes: object) -> dict:
    return {"v": 1, "type": "info", "status": "ready", "title": title, "body": {"text": "Açıklama"}, **changes}


def fields(**changes: object) -> FinalFields:
    return FinalFields(refused=False, how=empty_how(time.monotonic(), rule_id=None), mode="answer", **changes)


def test_a_final_without_cards_says_so_with_an_empty_list() -> None:
    assert final_body("Yanıt", [], "kural", None, fields())["cards"] == []


def test_cards_are_validated_converted_and_bounded() -> None:
    v0 = {"v": 0, "id": "card-v0", "type": "event", "status": "ready", "title": "Etkinlik",
          "source": {"name": "Kaynak", "url": "https://example.org/", "observed_at": "2026-09-27T11:00:00+03:00"}}
    raw = [card("Bir"), v0, {"v": 1, "type": "unknown", "title": "Bilinmeyen"}, card(""), card("Bir")]
    raw.extend(card(f"Kart {index}") for index in range(10))
    body = final_body("Yanıt", [], "kural", None, fields(cards=raw))
    assert len(body["cards"]) == chat_cards.MAX_CARDS
    assert [item["title"] for item in body["cards"][:3]] == ["Bir", "Etkinlik", "Kart 0"]
    assert all(item["v"] == 1 for item in body["cards"])
    assert body["cards"][1] == chat_cards.validate_card(chat_cards.from_v0(v0))


def test_an_emergency_final_never_carries_a_card() -> None:
    body = final_body("", [], "kural", None, fields(emergency=True, cards=[card("Kart")]))
    assert body["cards"] == []
    event = emergency_events(None, time.monotonic())[0]
    assert json.loads(event.split("data: ", 1)[1])["cards"] == []
