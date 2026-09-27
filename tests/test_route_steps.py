"""Offline contract tests for the bilingual, speakable accessible-route view."""

from __future__ import annotations

import json
import re

import httpx
from conftest import offline_settings, refuse_network
from fastapi.routing import Mount
from fastapi.testclient import TestClient

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.route_steps import lift_sentence, route_view, step_cards
from nabiz.console.route_steps_api import route_steps_routes


def build_app():
    settings = offline_settings()
    nabiz = Nabiz(SourceContext.create(
        client=PoliteClient(transport=httpx.MockTransport(refuse_network)),
        cache=TTLCache(),
        settings=settings,
    ))
    app = build_console_app(
        settings=settings,
        nabiz=nabiz,
        llm_config=llm.LlmConfig(),
        guard=SpendGuard(BudgetConfig(state_path=None)),
    )
    app.include_router(route_steps_routes)
    added_route = app.router.routes.pop()
    static_index = next(
        index for index, route in enumerate(app.router.routes)
        if isinstance(route, Mount) and route.name == "static"
    )
    app.router.routes.insert(static_index, added_route)
    return app


def route(client: TestClient, origin: str, destination: str, lang: str = "tr") -> dict:
    response = client.get("/api/route/steps", params={"from": origin, "to": destination, "needs": "step_free", "lang": lang})
    assert response.status_code == 200, response.text
    return response.json()


def test_recorded_zeytinburnu_to_bagcilar_has_four_merged_cards() -> None:
    with TestClient(build_app()) as client:
        result = route(client, "Zeytinburnu", "Bağcılar")
    assert result["available"] is True
    assert [card["kind"] for card in result["cards"]] == ["ride", "transfer", "ride", "walk"]
    first, transfer, second, walk = result["cards"]
    assert first["stops"] == 1 and first["next_stop"] == "Bakırköy-İncirli"
    assert transfer["title"].startswith("İncirli istasyonunda M3")
    assert second["stops"] == 5 and second["between"]
    assert result["freshness"]["text"].startswith("kayıtlı · ")
    assert result["sample"] is False


def test_english_route_copy_and_recorded_stamp() -> None:
    with TestClient(build_app()) as client:
        result = route(client, "Zeytinburnu", "Bağcılar", "en")
    assert result["available"] is True and len(result["cards"]) == 4
    assert result["freshness"]["text"].startswith("recorded · ")
    copy = " ".join(
        [result["summary"], result["disclaimer"], *result["notes"]]
        + [
            value for card in result["cards"]
            for value in (card["title"], card["detail"], card["lift_text"], card["speech"])
        ]
    )
    for station in (
        "Zeytinburnu", "Bağcılar", "Bakırköy-İncirli", "İncirli", "Kirazlı-Bağcılar",
        "Haznedar", "İlkyuva", "Yıldıztepe", "Molla Gürani",
    ):
        copy = copy.replace(station, " ")
    for word in ("istasyon", "yürüy", "binin", "inin", "aktarma", " dk", "durak", "yaklaşık", "tahmin", "sokak"):
        assert word not in copy.lower()


def test_maltepe_to_pendik_is_one_ride_and_drops_zero_walks() -> None:
    with TestClient(build_app()) as client:
        result = route(client, "Maltepe", "Pendik")
    assert result["available"] is True
    assert len(result["cards"]) == 1
    assert result["cards"][0]["kind"] == "ride"
    assert result["cards"][0]["stops"] == 8


def test_unavailable_routes_and_english_reason_are_cautious() -> None:
    with TestClient(build_app()) as client:
        kabatas = route(client, "Kabataş", "Taksim")
        kabatas_en = route(client, "Kabataş", "Taksim", "en")
        unknown = route(client, "Zzzyx", "Levent", "en")
    assert kabatas["available"] is False and kabatas["cards"] == [] and kabatas["reason"]
    assert "lift on this route" in kabatas_en["reason"]
    assert unknown["available"] is False and "could not be found" in unknown["reason"].lower()


def test_query_validation_rejects_bad_language_missing_origin_and_long_origin() -> None:
    with TestClient(build_app()) as client:
        invalid_language = client.get("/api/route/steps", params={"from": "A", "to": "B", "lang": "ar"})
        missing_origin = client.get("/api/route/steps", params={"to": "B"})
        long_origin = client.get("/api/route/steps", params={"from": "A" * 121, "to": "B"})
    assert [invalid_language.status_code, missing_origin.status_code, long_origin.status_code] == [422, 422, 422]


def test_pure_cards_use_station_fields_not_walk_descriptions_and_note_alternatives() -> None:
    steps = [
        {"kind": "walk", "description": "ignore this", "minutes": 0},
        {"kind": "ride", "line": "M1", "from_station": "A", "to_station": "B", "minutes": 2, "lift_status": "working"},
        {"kind": "walk", "description": "untrusted prose", "minutes": 4, "lift_status": "unknown"},
        {"kind": "ride", "line": "M2", "from_station": "C", "to_station": "D", "minutes": 3},
        {"kind": "walk", "description": "ignore this too", "minutes": 0},
        {"kind": "unknown", "minutes": 1},
    ]
    cards = step_cards(steps, "D", "tr")
    assert [card["kind"] for card in cards] == ["ride", "walk", "ride"]
    assert cards[1]["title"] == "B istasyonundan C istasyonuna yürüyün"
    assert cards[0]["lift_text"] == "B için İBB kaydında asansör arızası yok."
    assert lift_sentence("out_of_service", "C", "tr").startswith("İBB kaydına göre C istasyonunda")
    view = route_view({
        "available": True, "from": "A", "to": "D", "steps": steps,
        "alternative_used": {"station": "C", "avoided_station": "B"}, "extra_minutes": 5,
    }, "en")
    assert "instead of B" in view["notes"][0]
    assert "unknown_step_kind" in view["uncertainty"]


def test_access_walk_titles_distinguish_station_entry_from_exit() -> None:
    cards = step_cards([
        {"kind": "walk", "description": "not parsed", "minutes": 3},
        {"kind": "ride", "line": "M1", "from_station": "A", "to_station": "B", "minutes": 4},
        {"kind": "walk", "description": "also not parsed", "minutes": 6},
    ], "Destination", "tr")
    assert cards[0]["title"] == "A istasyonuna yürüyün"
    assert cards[-1]["title"] == "B istasyonundan çıkın"


def test_route_responses_and_mock_have_no_forbidden_claims_or_long_dashes() -> None:
    with TestClient(build_app()) as client:
        outputs = [route(client, "Zeytinburnu", "Bağcılar"), route(client, "Maltepe", "Pendik"),
                   route(client, "Kabataş", "Taksim"), route(client, "Zzzyx", "Levent")]
    for output in outputs:
        encoded = json.dumps(output, ensure_ascii=False).casefold()
        assert not any(mark in encoded for mark in ("\u2014", "\u2013", "canlı", "çalışıyor"))
        assert not re.search(r"\blive\b|\beta\b", encoded)


def test_mock_has_sample_badge_and_records_the_generated_route() -> None:
    from conftest import REPO_ROOT

    mock = json.loads((REPO_ROOT / "src/nabiz/console/static/mock/route-steps.json").read_text(encoding="utf-8"))
    assert mock["sample"] is True
    assert mock["sample_route"] == "Zeytinburnu → Bağcılar"
    assert len(mock["cards"]) == 4
    assert mock["cards"] == route(TestClient(build_app()), "Zeytinburnu", "Bağcılar")["cards"]
