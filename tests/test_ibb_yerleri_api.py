"""The recorded places API never needs an upstream request or a writable data store."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nabiz.console import ibb_yerleri_api as places_api


def payload(category: str, rows: list[list[Any]] | None = None, *, status: str = "alindi") -> dict[str, Any]:
    return {
        "schema": 1,
        "category": category,
        "status": status,
        "reason": None if status == "alindi" else "başlık tanınmadı",
        "title": f"{category} veri seti",
        "dataset_url": f"https://data.ibb.gov.tr/dataset/{category}",
        "resource_url": f"https://data.ibb.gov.tr/dataset/{category}/download/file.xlsx",
        "resource_last_modified": "2026-04-03T12:00:00+00:00",
        "captured_at": "2026-09-27T00:00:00+00:00",
        "license": "İBB Açık Veri Lisansı",
        "license_url": "https://data.ibb.gov.tr/license",
        "columns": ["name", "district", "address", "lat", "lon"],
        "rows": rows or [],
        "count": len(rows or []),
    }


def rows(count: int = 65) -> list[list[Any]]:
    return [
        [f"Nokta {index:02d}", "KADIKÖY", f"Mahalle {index}", 41.01 + (index % 5) * 0.001, 29.01 + (index % 7) * 0.001]
        for index in range(count)
    ]


def make_client(directory: Path, logged_queries: list[bytes] | None = None) -> TestClient:
    directory.mkdir(parents=True, exist_ok=True)
    for category in places_api.CATEGORIES:
        item = payload(
            category, rows() if category == "halk_ekmek" else [], status="veri_alinamadi" if category == "wifi" else "alindi"
        )
        if category == "wifi":
            item["resource_last_modified"] = "2023-03-15T21:11:55+00:00"
        (directory / f"{category}.json").write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
    places_api._CACHE.clear()
    os.environ[places_api.DATA_ENV] = str(directory)
    app = FastAPI()
    app.include_router(places_api.ibb_yerleri_routes)
    if logged_queries is not None:

        @app.middleware("http")
        async def capture_query_after_route(request, call_next):
            response = await call_next(request)
            logged_queries.append(request.scope["query_string"])
            return response

    return TestClient(app)


def test_index_has_categories_districts_disclaimer_and_cache_control(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(places_api.DATA_ENV, str(tmp_path))
    client = make_client(tmp_path)
    response = client.get("/api/ibb-places")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "max-age=300"
    body = response.json()
    assert [item["id"] for item in body["categories"]] == list(places_api.CATEGORIES)
    assert body["categories"][0]["count"] == 65
    assert body["categories"][-1]["status"] == "veri_alinamadi"
    assert body["categories"][-1]["count"] == 0
    assert body["categories"][-1]["stale"] is True
    assert len(body["districts"]) == 39
    assert body["disclaimer"] == "Resmî İBB hizmeti değildir."


def test_district_matches_folded_turkish_and_caps_at_sixty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(places_api.DATA_ENV, str(tmp_path))
    client = make_client(tmp_path)
    response = client.get("/api/ibb-places/halk_ekmek", params={"district": "kadıköy"})
    body = response.json()
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert body["total"] == 65 and body["shown"] == 60 and body["truncated"] is True
    assert len(body["points"]) == 60
    assert [item["id"] for item in body["points"]] == [f"halk_ekmek-{index}" for index in range(60)]


def test_bbox_orders_by_center_distance_then_name(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(places_api.DATA_ENV, str(tmp_path))
    client = make_client(tmp_path)
    response = client.get("/api/ibb-places/halk_ekmek", params={"bbox": "29.00,41.00,29.04,41.04"})
    points = response.json()["points"]
    center = (41.02, 29.02)

    def distance(point: dict[str, Any]) -> float:
        return places_api._distance_m(center, (point["lat"], point["lon"]))

    assert response.status_code == 200
    assert points[0] == min(points, key=lambda point: (distance(point), places_api.fold_tr(point["name"]), point["name"]))
    assert all("id" in point and len(point) == 6 for point in points)


def test_unavailable_category_is_an_honest_empty_success(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(places_api.DATA_ENV, str(tmp_path))
    body = make_client(tmp_path).get("/api/ibb-places/wifi", params={"district": "Kadıköy"}).json()
    assert body["status"] == "veri_alinamadi"
    assert body["points"] == []
    assert body["reason"]


def test_missing_and_malformed_files_are_reported_as_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(places_api.DATA_ENV, str(tmp_path))
    client = make_client(tmp_path)
    client.get("/api/ibb-places")
    malformed = tmp_path / "sosyal_tesis.json"
    malformed.write_text("{broken", encoding="utf-8")
    os.utime(malformed, ns=(malformed.stat().st_atime_ns, malformed.stat().st_mtime_ns + 10_000_000))
    broken = client.get("/api/ibb-places/sosyal_tesis", params={"district": "Kadıköy"}).json()
    assert broken["status"] == "veri_alinamadi" and broken["points"] == []
    (tmp_path / "wifi.json").unlink()
    missing = client.get("/api/ibb-places/wifi", params={"district": "Kadıköy"}).json()
    assert missing["status"] == "veri_alinamadi" and missing["points"] == []


def test_bad_bbox_and_missing_or_multiple_filters_return_400(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(places_api.DATA_ENV, str(tmp_path))
    client = make_client(tmp_path)
    values = [
        {},
        {"district": "Kadıköy", "bbox": "29.00,41.00,29.04,41.04"},
        {"bbox": "bad"},
        {"bbox": "29.00,41.00,30.00,41.04"},
        {"bbox": "27.00,41.00,27.04,41.04"},
    ]
    for params in values:
        response = client.get("/api/ibb-places/halk_ekmek", params=params)
        assert response.status_code == 400
        assert response.json()["error"] == "bad_request"


def test_unknown_category_is_404(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(places_api.DATA_ENV, str(tmp_path))
    response = make_client(tmp_path).get("/api/ibb-places/unknown", params={"district": "Kadıköy"})
    assert response.status_code == 404


def test_query_values_are_not_logged_and_api_does_not_write_files(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.setenv(places_api.DATA_ENV, str(tmp_path))
    caplog.set_level(logging.INFO)
    logged_queries: list[bytes] = []
    client = make_client(tmp_path, logged_queries)
    query = "29.01,41.01,29.05,41.05"
    client.get("/api/ibb-places/halk_ekmek", params={"bbox": query})
    assert query not in caplog.text
    assert logged_queries == [b""]
    assert sorted(path.name for path in tmp_path.iterdir()) == [f"{category}.json" for category in places_api.CATEGORIES]


def test_a_changed_mtime_reloads_the_recorded_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(places_api.DATA_ENV, str(tmp_path))
    client = make_client(tmp_path)
    path = tmp_path / "halk_ekmek.json"
    assert client.get("/api/ibb-places").json()["categories"][0]["count"] == 65
    item = payload("halk_ekmek", rows(2))
    path.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 10_000_000))
    response = client.get("/api/ibb-places", headers={"Cache-Control": "no-cache"})
    assert response.json()["categories"][0]["count"] == 2


def test_district_comes_from_the_address_or_the_name_when_the_file_has_no_district_column(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(places_api.DATA_ENV, str(tmp_path))
    client = make_client(tmp_path)
    no_column = [
        ["ARNAVUTKÖY SOSYAL TESİSİ", "", "Bebek Arnavutköy Cd No:72, 34345 Beşiktaş/İstanbul", 41.067, 29.044],
        ["ÇAPA KENT LOKANTASI", "", "TURGUT ÖZAL MİLLET CADDESİ, NO.109/A FATİH", 41.012, 28.94],
        ["TUZLA KENT LOKANTASI", "", "A2 BLOK 22 NO’LU (0 ADA, 6598 PARSEL)", 40.83, 29.3],
        ["EYÜP KENT LOKANTASI", "", "WHİTE HİLL ALIŞVERİŞ MERKEZİ", 41.05, 28.93],
        ["IETT Otobus", "", "", 41.0, 29.0],
    ]
    target = tmp_path / "sosyal_tesis.json"
    target.write_text(json.dumps(payload("sosyal_tesis", no_column), ensure_ascii=False), encoding="utf-8")
    places_api._CACHE.clear()

    def names(district: str) -> list[str]:
        body = client.get("/api/ibb-places/sosyal_tesis", params={"district": district}).json()
        return [point["name"] for point in body["points"]]

    assert names("Beşiktaş") == ["ARNAVUTKÖY SOSYAL TESİSİ"]  # the address's last district, not the first one it names
    assert names("Arnavutköy") == []
    assert names("Fatih") == ["ÇAPA KENT LOKANTASI"]
    assert names("Tuzla") == ["TUZLA KENT LOKANTASI"]
    assert names("Eyüpsultan") == ["EYÜP KENT LOKANTASI"]  # data/agencies.json district_aliases
    bbox = client.get("/api/ibb-places/sosyal_tesis", params={"bbox": "28.95,40.95,29.05,41.05"}).json()
    assert [point["district"] for point in bbox["points"]] == [""]  # no district is guessed for a bus


def test_the_captured_files_serve_every_category(monkeypatch) -> None:
    captured = Path(__file__).resolve().parents[1] / "data" / "reference" / "ibb_places"
    if not all((captured / f"{category}.json").exists() for category in places_api.CATEGORIES):
        import pytest

        pytest.skip("captured reference files are absent")
    monkeypatch.setenv(places_api.DATA_ENV, str(captured))
    places_api._CACHE.clear()
    app = FastAPI()
    app.include_router(places_api.ibb_yerleri_routes)
    client = TestClient(app)
    index = {item["id"]: item for item in client.get("/api/ibb-places").json()["categories"]}
    assert all(item["status"] == "alindi" and item["count"] > 0 for item in index.values())
    assert index["wifi"]["stale"] is True  # the ibbWiFi resource dates from 2023: the page says "Bu kayıt eski"
    assert not any(index[category]["stale"] for category in ("halk_ekmek", "kent_lokantasi", "sosyal_tesis"))
    for category in places_api.CATEGORIES:
        body = client.get(f"/api/ibb-places/{category}", params={"district": "Üsküdar"}).json()
        assert body["status"] == "alindi" and body["total"] > 0, category
        assert all(places_api.fold_tr(point["district"]) == "uskudar" for point in body["points"])
        near = client.get(f"/api/ibb-places/{category}", params={"bbox": "28.90,40.95,29.10,41.10"}).json()
        assert 0 < near["shown"] <= places_api.MAX_POINTS, category
        assert all(28.90 <= p["lon"] <= 29.10 and 40.95 <= p["lat"] <= 41.10 for p in near["points"])
    places_api._CACHE.clear()
