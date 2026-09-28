"""Story 1: an accessible journey, with a voice (docs/acceptance/HIKAYE-1.md).

The base has the step-free journey card, the lift record in the chat and the offer to remember a
need; the speakable step cards, the recorded Wi-Fi places and the saved journeys come with P00 G3,
the place correction with G1. The voice itself runs in the browser and is checked by hand.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from test_console_chat import FakeModel

from acceptance.support import (
    AFTER_G1,
    CLOUD,
    OFFLINE_MODES,
    after,
    assert_offline_citations,
    build_app,
    chat,
    offline_nabiz,
    sign_in,
    tools_started,
)
from nabiz.agent import llm

JOURNEY = {"from": "Kadıköy", "to": "Levent", "needs": "step_free"}


# ---- the base -------------------------------------------------------------------------------------------


def test_step_free_journey_says_why_it_cannot_route_and_how_old_its_record_is(client: TestClient) -> None:
    """Step 3: an unverified lift on the way is named; no step list is made up around it."""
    body = client.get("/api/journey/accessible", params=JOURNEY).json()
    assert body["needs"] == ["step_free"]
    if body["available"]:
        assert body["steps"], "an available journey lists its steps"
    else:
        assert body["steps"] == [] and "asansör" in body["reason"].casefold()
        assert body["uncertainty"], "what could not be verified is listed"
    provenance = body["provenance"]
    assert provenance["mode"] in OFFLINE_MODES and provenance["mode"] != "live"
    assert isinstance(provenance["age_s"], int) and provenance["age_s"] >= 0, "the record's age is shown"
    assert "tahmin" in body["disclaimer"]


def test_a_typed_place_it_does_not_know_gets_examples_not_a_guess(client: TestClient) -> None:
    """Step 2 (location permission refused): the person types a place; an unknown one is said so."""
    body = client.get("/api/journey/accessible", params={**JOURNEY, "from": "Zzyzx"}).json()
    assert body["available"] is False and body["steps"] == []
    assert "Zzyzx" in body["reason"] and "Kadıköy" in body["reason"], "the answer names real examples to type"
    assert body["provenance"]["mode"] == "unknown"


def test_nearby_needs_a_position_the_person_chose_to_share(client: TestClient) -> None:
    """Step 2: without the permission the page sends no coordinates, and the server invents none."""
    refused = client.get("/api/nearby", params={"needs": "step_free"})
    assert refused.status_code == 422 and refused.json()["error"] == "invalid_request"
    shared = client.get("/api/nearby", params={"lat": 40.99, "lon": 29.03, "needs": "step_free"}).json()
    assert shared["stops"], "a shared position lists stops"
    assert all(stop["provenance"]["mode"] in OFFLINE_MODES for stop in shared["stops"])


def test_the_lift_answer_quotes_the_record_and_offers_to_remember_without_saving(client: TestClient) -> None:
    """Steps 4 and 5: the lift record, never "it works"; a need asked twice is offered, never stored."""
    earlier = ["Asansörlü istasyon lazım, merdiven çıkamıyorum"]
    question = "Kartal metrosunda asansör var mı? Merdivensiz gitmem lazım"
    stream, final = chat(client, question, history=earlier)
    assert "metro_equipment_status" in tools_started(stream)
    assert "İBB kaydında" in final["answer"] and "çalışıyor" not in final["answer"]
    assert_offline_citations(final)
    assert final["memory_suggestion"] == {"key": "step_free", "label": "Adımsız erişim (asansör, rampa)"}
    _, again = chat(client, question, history=earlier)
    assert again["memory_suggestion"] is not None, "the server kept nothing: only the person's yes saves it, on the device"
    _, saved = chat(client, question, history=earlier, needs=["step_free"])
    assert saved["memory_suggestion"] is None, "a need the device already holds is not offered again"


def test_a_follow_up_with_another_place_answers_for_that_place(client: TestClient) -> None:
    """Step 6 (correction, base form): "Peki Kartal'da?" after a Kadıköy question is about Kartal."""
    stream, final = chat(client, "Peki Kartal'da?", history=["Kadıköy'de otopark var mı?"])
    assert "ispark_find_parking" in tools_started(stream)
    assert "Kartal" in final["answer"] and "Kadıköy" not in final["answer"]
    assert_offline_citations(final)


def test_a_model_that_does_not_answer_leaves_the_rules_answer_labelled(stores: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Step 9 (an outage): the model is down; the rules answer and say so, nothing waits on the model."""
    fake = FakeModel(*(httpx.ConnectError("model down") for _ in range(3)))
    monkeypatch.setattr(llm, "chat", fake)
    with TestClient(build_app(offline_nabiz(), config=CLOUD)) as client:
        stream, final = chat(client, "Kartal metrosunda asansör var mı?")
    assert fake.calls, "the model was tried"
    assert final["author"] == "kural" and final["refused"] is False and final["mode"] == "answer"
    assert "metro_equipment_status" in tools_started(stream)
    assert_offline_citations(final)


# ---- P00 G1: the place correction on the chat -----------------------------------------------------------


@AFTER_G1
def test_kadikoy_degil_kartal_moves_the_question_to_kartal(client: TestClient) -> None:
    stream, final = chat(client, "Kadıköy değil Kartal", history=["Kadıköy'de otopark var mı?"])
    assert "ispark_find_parking" in tools_started(stream)
    assert "Kartal" in final["answer"] and "Kadıköy" not in final["answer"]
    assert_offline_citations(final)


# ---- P00 G3: speakable steps, recorded places, saved journeys --------------------------------------------


@after("G3", "/api/route/steps")
def test_route_steps_are_the_journey_cards_and_never_a_sample(client: TestClient) -> None:
    response = client.get("/api/route/steps", params=JOURNEY)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sample"] is False, "the demo's steps come from the record, not from mock data"
    assert body["provenance"].get("mode") in OFFLINE_MODES
    if body["available"]:
        assert body["cards"] and all(card["text"] for card in body["cards"])
    else:
        assert body["cards"] == [] and body["reason"], "an unavailable route says why"
    assert body["disclaimer"] and body["freshness"]
    english = client.get("/api/route/steps", params={**JOURNEY, "lang": "en"}).json()
    assert english["lang"] == "en" and english["sample"] is False


@after("G3", "/api/ibb-places/{category}")
def test_wifi_places_are_recorded_and_marked_stale(client: TestClient) -> None:
    response = client.get("/api/ibb-places/wifi", params={"district": "Üsküdar"})
    assert response.status_code == 200, response.text
    assert response.headers.get("cache-control") == "no-store"
    body = response.json()
    assert isinstance(body["source"]["stale"], bool)
    if body["status"] == "alindi":
        assert body["source"]["stale"] is True, "a captured list is never shown as current"
        assert all(point["district"] == "Üsküdar" for point in body["points"])
    else:
        assert body["points"] == [] and body["reason"], "no recorded file: an honest empty answer"


@after("G3", "/api/account/journeys", "POST")
def test_deleting_the_account_leaves_no_saved_journey(client: TestClient) -> None:
    account = sign_in(client, "yolcu@example.org")
    journey = {"from": "Kadıköy", "to": "Levent", "time": "08:30", "needs": ["step_free"]}
    saved = client.post("/api/account/journeys", headers=account, json={"journey": journey, "consent": True})
    assert saved.status_code == 200, saved.text
    assert client.delete("/api/account", headers=account).status_code == 200
    assert client.get("/api/account/journeys", headers=account).status_code == 401
    again = sign_in(client, "yolcu@example.org")
    assert client.get("/api/account/journeys", headers=again).json()["journeys"] == [], "the rows went with the account"


@after("G3", "/api/account/journeys", "POST")
def test_a_journey_is_kept_only_with_its_own_consent(client: TestClient) -> None:
    """Criterion 3: an account alone does not let the server keep a journey; its own consent box does."""
    account = sign_in(client, "onaysiz@example.org")
    journey = {"from": "Kadıköy", "to": "Levent", "time": "08:30", "needs": ["step_free"]}
    refused = client.post("/api/account/journeys", headers=account, json={"journey": journey, "consent": False})
    assert refused.status_code == 400 and refused.json()["error"] == "consent_required"
    assert client.get("/api/account/journeys", headers=account).json()["journeys"] == []
