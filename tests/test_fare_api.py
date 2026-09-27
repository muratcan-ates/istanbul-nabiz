"""HTTP contract for fare estimates without touching app.py or a persistent store."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nabiz.console import fare_api
from nabiz.console.fare_sources import FareCatalogError, load_fare_catalog


def client() -> TestClient:
    app = FastAPI()
    app.include_router(fare_api.fare_routes)
    return TestClient(app)


def pattern(**updates: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "days_per_week": 5,
        "round_trip": True,
        "tariff": "tam",
        "legs": [{"mode": "metro"}],
        "within_window": False,
        "personalized": False,
    }
    value.update(updates)
    return value


def test_catalog_and_estimate_are_no_store_and_have_only_the_expected_shapes() -> None:
    http = client()
    catalog = http.get("/api/fare/catalog", params={"lang": "tr"})
    assert catalog.status_code == 200
    assert catalog.headers["cache-control"] == "no-store"
    assert {"ferry_routes", "sources", "missing", "notice", "disclaimer"} <= set(catalog.json())
    assert catalog.json()["missing"]["bus"]["status"] == "alinamadi"

    estimate = http.post("/api/fare/estimate", json=pattern())
    assert estimate.status_code == 200
    assert estimate.headers["cache-control"] == "no-store"
    body = estimate.json()
    assert {"estimate", "notice", "disclaimer"} <= set(body)
    assert [row["id"] for row in body["estimate"]["options"]] == ["card_single", "eticket", "subscription"]
    assert "canlı" not in str(body).casefold()
    assert "\u2014" not in str(body) and "\u2013" not in str(body)


def test_invalid_language_and_closed_pattern_schema_return_400() -> None:
    http = client()
    invalid_language = http.get("/api/fare/catalog", params={"lang": "tr-TR"})
    assert invalid_language.status_code == 400
    assert invalid_language.headers["cache-control"] == "no-store"
    assert invalid_language.json()["error"] == "invalid_lang"

    for value in (
        pattern(extra_field="not accepted"),
        pattern(days_per_week=8),
        pattern(legs=[{"mode": "metro"}] * 5),
        pattern(legs=[{"mode": "ferry", "route": "not-in-catalog"}]),
    ):
        response = http.post("/api/fare/estimate", json=value)
        assert response.status_code == 400
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["error"] == "invalid_pattern"
        assert response.json()["fields"]


def test_large_body_is_rejected_before_pattern_parsing() -> None:
    response = client().post("/api/fare/estimate", content=b"{" + (b" " * 2050) + b"}")
    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"] == "pattern_too_large"


def test_unavailable_catalog_returns_503(monkeypatch) -> None:
    def unavailable():
        raise FareCatalogError("unavailable")

    monkeypatch.setattr(fare_api, "load_fare_catalog", unavailable)
    http = client()
    for response in (http.get("/api/fare/catalog"), http.post("/api/fare/estimate", json=pattern())):
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["error"] == "fare_catalog_unavailable"


def test_put_and_delete_are_not_registered() -> None:
    http = client()
    assert http.put("/api/fare/estimate", json=pattern()).status_code == 405
    assert http.delete("/api/fare/estimate").status_code == 405


def test_pattern_values_are_not_written_to_logs(caplog) -> None:
    load_fare_catalog.cache_clear()
    sample = pattern(days_per_week=7)
    caplog.set_level(logging.DEBUG)
    response = client().post("/api/fare/estimate", json=sample)
    assert response.status_code == 200
    assert '"days_per_week": 7' not in caplog.text
    assert '"legs":' not in caplog.text
    assert "fare estimate" not in caplog.text.casefold()
