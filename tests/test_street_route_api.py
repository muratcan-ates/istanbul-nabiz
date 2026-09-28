"""The unmounted route router can be integrated without contacting Azure."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nabiz.console.route_provider_azure import SampleRouteProvider
from nabiz.console.street_route_api import street_route_router

FIXTURE = Path(__file__).parent / "fixtures" / "azure_maps" / "pedestrian_ornek.json"


def body(*, consent: bool = True, lang: str = "tr") -> dict:
    return {
        "origin": {"name": "A", "lat": 40.9, "lon": 29.19},
        "destination": {"name": "B", "lat": 40.9009, "lon": 29.1911},
        "needs": ["step_free"],
        "lang": lang,
        "consent": consent,
    }


def test_router_is_unmounted_on_base_app() -> None:
    app = FastAPI()
    with TestClient(app) as client:
        assert client.post("/api/route/street", json=body()).status_code == 404


def test_sample_api_and_no_consent(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: (_ for _ in ()).throw(AssertionError("network")))
    app = FastAPI()
    app.include_router(street_route_router)
    app.state.street_route_provider = SampleRouteProvider(json.loads(FIXTURE.read_text(encoding="utf-8")))
    with TestClient(app) as client:
        response = client.post("/api/route/street", json=body())
        assert response.status_code == 200
        assert len(response.json()["card"]["data"]["legs"]) >= 5
        assert response.json()["card"]["data"]["sample"] is True
        refused = client.post("/api/route/street", json=body(consent=False)).json()
        assert refused["geometry"] == [] and refused["card"]["data"]["legs"] == []
        assert client.post("/api/route/street", json={**body(), "needs": ["unknown"]}).status_code == 422


def test_no_key_api_has_no_fake_path(monkeypatch) -> None:
    monkeypatch.delenv("NABIZ_AZURE_MAPS_KEY", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: (_ for _ in ()).throw(AssertionError("network")))
    app = FastAPI()
    app.include_router(street_route_router)
    with TestClient(app) as client:
        result = client.post("/api/route/street", json=body()).json()
    assert result["provider_status"] == "kapalı"
    assert result["card"]["status"] == "unavailable"
    assert result["card"]["data"]["legs"] == []
    assert result["geometry"] == []
