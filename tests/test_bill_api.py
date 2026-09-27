"""Read-only endpoint contract for the source catalogue."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nabiz.console import bill_api, bill_helper
from nabiz.console.forbidden_terms import find_forbidden


def client() -> TestClient:
    app = FastAPI()
    app.include_router(bill_api.bill_routes)
    return TestClient(app)


def response_texts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in response_texts(item)]
    if isinstance(value, list):
        return [text for item in value for text in response_texts(item)]
    return []


def test_catalog_is_bilingual_read_only_and_uncached_by_clients() -> None:
    response = client().get("/api/bill/catalog?lang=en&amount=12345")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"version", "lang", "agencies", "items", "tariff", "concepts", "notice", "disclaimer", "captured_at"}
    assert body["lang"] == "en"
    assert body["items"][0]["label"] == "Water charge"
    assert body["agencies"]["igdas"]["name"] == "İGDAŞ"
    assert "Not an official İBB service." in body["notice"]
    text = " ".join(response_texts(body))
    assert "canlı" not in text.casefold()
    assert "\u2014" not in text and "\u2013" not in text
    assert find_forbidden(text) == ()


def test_invalid_language_gets_port_problem() -> None:
    response = client().get("/api/bill/catalog?lang=fr")
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_lang"


def test_broken_catalog_is_not_served(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(bill_api, "BILL_ITEMS_PATH", tmp_path / "missing.json")
    bill_helper.load_bill_catalog.cache_clear()
    response = client().get("/api/bill/catalog")
    assert response.status_code == 503
    assert response.json()["error"] == "bill_catalog_unavailable"
    assert response.headers["cache-control"] == "no-store"


def test_catalog_has_no_write_method() -> None:
    response = client().post("/api/bill/catalog", json={"amount": 88})
    assert response.status_code == 405
