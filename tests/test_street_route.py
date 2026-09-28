"""Offline pedestrian directions and route card contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from nabiz.console.route_provider_azure import AzureMapsRouteProvider, SampleRouteProvider, parse_directions
from nabiz.console.street_route import make_street_route, maneuver_text

FIXTURE = Path(__file__).parent / "fixtures" / "azure_maps" / "pedestrian_ornek.json"
ORIGIN = (40.9, 29.19)
DESTINATION = (40.9009, 29.1911)


def sample_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", ["tr", "en"])
async def test_sample_has_turns_and_honest_contract(lang: str) -> None:
    provider = SampleRouteProvider(sample_payload())
    result = await make_street_route(provider, ORIGIN, DESTINATION, ("A", "B"), needs=["step_free"], lang=lang, consent=True)
    card = result["card"]
    assert set(card) == {
        "v",
        "id",
        "conversation_id",
        "message_id",
        "type",
        "status",
        "title",
        "source",
        "linked",
        "actions",
        "data",
        "sensitive",
    }
    assert card["v"] == 0 and card["type"] == "route" and card["status"] == "ready"
    assert card["conversation_id"] is None and card["message_id"] is None
    assert card["actions"] == [] and card["sensitive"] is False
    assert set(card["data"]) == {
        "from",
        "to",
        "needs",
        "legs",
        "unknown_segments",
        "street_geometry",
        "provider",
        "sample",
        "disclaimer",
    }
    assert card["data"]["provider"] == "sahte" and card["data"]["sample"] is True
    assert card["data"]["street_geometry"] is False
    assert card["source"]["freshness"] == "kayitli"
    assert len(card["data"]["legs"]) >= 5
    assert sum(leg["title"] in {"Sağa dönün.", "Sola dönün.", "Turn right.", "Turn left."} for leg in card["data"]["legs"]) >= 5
    assert len(card["data"]["unknown_segments"]) == 3
    assert all(leg["kind"] == "walk" and leg["lift_text"] is None for leg in card["data"]["legs"])
    assert result["geometry"] == []
    assert ("Sağa dönün." if lang == "tr" else "Turn right.") in [leg["title"] for leg in card["data"]["legs"]]
    assert ("Sola dönün." if lang == "tr" else "Turn left.") in [leg["title"] for leg in card["data"]["legs"]]
    assert ("Düz devam edin." if lang == "tr" else "Continue straight.") in [leg["title"] for leg in card["data"]["legs"]]
    assert (
        card["id"]
        == (await make_street_route(provider, ORIGIN, DESTINATION, ("A", "B"), needs=["step_free"], lang=lang, consent=True))[
            "card"
        ]["id"]
    )


@pytest.mark.asyncio
async def test_missing_key_never_builds_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NABIZ_AZURE_MAPS_KEY", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: pytest.fail("HTTP client must remain unused"))
    provider = AzureMapsRouteProvider()
    result = await make_street_route(provider, ORIGIN, DESTINATION, ("A", "B"), needs=[], lang="tr", consent=True)
    assert result["provider_status"] == "kapalı"
    assert result["card"]["status"] == "unavailable"
    assert result["card"]["data"]["legs"] == []
    assert result["card"]["data"]["street_geometry"] is False
    assert result["geometry"] == []


@pytest.mark.asyncio
async def test_real_adapter_requests_pedestrian_only_with_consent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")
    monkeypatch.delenv("NABIZ_OFFLINE", raising=False)
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=sample_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = AzureMapsRouteProvider(key="placeholder", client=client)
        assert await provider.directions(ORIGIN, DESTINATION, consent=False) is None
        result = await make_street_route(provider, ORIGIN, DESTINATION, ("A", "B"), needs=[], lang="en", consent=True)
    assert len(requests) == 1
    assert requests[0].url.host == "atlas.microsoft.com"
    assert requests[0].url.params["travelMode"] == "pedestrian"
    assert requests[0].headers["subscription-key"] == "placeholder"
    assert result["card"]["data"]["provider"] == "azure_maps"
    assert result["card"]["data"]["sample"] is False
    assert result["card"]["data"]["street_geometry"] is True
    assert f"{ORIGIN[0]}" not in caplog.text, "a request log line carried the coordinates"


@pytest.mark.asyncio
async def test_offline_and_provider_failure_never_return_a_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NABIZ_OFFLINE", "1")
    provider = AzureMapsRouteProvider(key="placeholder")
    assert provider.status == "kapalı"
    assert await provider.directions(ORIGIN, DESTINATION, consent=True) is None

    monkeypatch.delenv("NABIZ_OFFLINE")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as client:
        provider = AzureMapsRouteProvider(key="placeholder", client=client)
        result = await make_street_route(provider, ORIGIN, DESTINATION, ("A", "B"), needs=[], lang="tr", consent=True)
    assert result["provider_status"] == "doğrulanamadı"
    assert result["card"]["status"] == "unavailable"
    assert result["geometry"] == []


def test_bad_provider_shape_and_unknown_turn_are_not_invented() -> None:
    assert parse_directions({"routes": []}, sample=False) is None
    payload = sample_payload()
    payload["routes"][0]["guidance"]["instructions"][0]["pointIndex"] = 99
    assert parse_directions(payload, sample=False) is None
    assert maneuver_text("UnsupportedTurn", "tr") == "Yön adımı bilinmiyor."
    assert maneuver_text("UnsupportedTurn", "en") == "Direction step is unknown."
