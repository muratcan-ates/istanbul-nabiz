"""Source checks and API contract for the device-only disaster file."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.knowledge.guardrails import host_allowed
from nabiz.console import disaster_kit
from nabiz.console.disaster_kit_api import disaster_kit_routes
from nabiz.console.forbidden_terms import find_forbidden

CAPTURE = REPO_ROOT / "data/reference/disaster_kit/akom_sss.json"
INDEX = REPO_ROOT / "data/knowledge/knowledge.db"
CATALOG = REPO_ROOT / "data/reference/ibb_catalog.json"


def api_client() -> TestClient:
    app = FastAPI()
    app.include_router(disaster_kit_routes)
    return TestClient(app)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_reviewed_catalog_has_sources_for_all_content() -> None:
    kit = disaster_kit.load_kit()
    assert disaster_kit.validate_kit(kit) == []
    assert len(kit["kit_items"]) == 19
    assert len({item["id"] for item in kit["kit_items"]}) == 19
    assert len(kit["kit_care"]) == 6
    for source in kit["sources"].values():
        assert host_allowed(urlsplit(source["url"]).hostname or "")
    rendered = json.dumps(kit, ensure_ascii=False).lower()
    assert "afad.gov.tr" not in rendered and "turkiye.gov.tr" not in rendered
    assert "barınma indeksi" not in " ".join(kit["assembly"]["catalog_check"]["terms"])


def test_akom_items_care_and_quotes_match_the_capture() -> None:
    kit, capture = disaster_kit.load_kit(), read_json(CAPTURE)
    question = next(item for item in capture["qa"] if item["question"] == "Afet çantasında nelerin olması gerekir?")
    expected = [
        "Dayanıklı, enerji veren gıdalar (bisküvi v.b.)",
        "Su",
        "Hijyenik Eldiven",
        "Yarabandı",
        "Sargı Bezi",
        "Pamuk",
        "Kolonya",
        "Makas",
        "Çekiç",
        "Düdük",
        "Yedek pilleriyle radyo",
        "Yedek pilleriyle fener",
        "Çok amaçlı bıçak",
        (
            "İçinde önemli telefon numaralarının, iletişime geçilecek kişilerin "
            "bilgilerinin, önemli evrakların fotokopilerinin bulunduğu su "
            "geçirmeyen bir dosya"
        ),
        "Bozuk para",
        "Telefon kartı",
        "Mendil",
        "Sürekli kullanılan özel ilaç",
        "Yağmurluk",
    ]
    assert [item["quote"] for item in kit["kit_items"]] == expected
    assert [item["quote"] for item in kit["kit_care"]] == question["answer"][4:]
    assert kit["contact_basis"]["quote"] == question["answer"][1]
    assert disaster_kit.quotes_in_capture(kit, capture) == []
    assert kit["captured_at"] == capture["fetched_at"]
    assert kit["sources"]["akom_sss"]["source_updated_at"] == capture["source_updated_at"] == "2022-09-30T13:18:42+03:00"
    afis = next(
        item for item in capture["qa"] if item["question"] == "Bazı mahallelerde bulunan deprem konteynırları AKOM’a mı ait?"
    )
    assert kit["assembly"]["afis"]["quote"] == afis["answer"][0]


@pytest.mark.skipif(not INDEX.is_file(), reason="the knowledge index is built locally and not committed (CI has none)")
def test_store_quotes_and_catalog_search_are_read_only_and_exact() -> None:
    kit = disaster_kit.load_kit()
    before = (INDEX.stat().st_size, INDEX.stat().st_mtime_ns)
    assert disaster_kit.quotes_in_store(kit, disaster_kit.readonly_documents(INDEX)) == []
    assert (INDEX.stat().st_size, INDEX.stat().st_mtime_ns) == before
    catalog = read_json(CATALOG)
    terms = kit["assembly"]["catalog_check"]["terms"]
    matches = disaster_kit.catalog_matches(catalog, terms)
    assert matches == kit["assembly"]["catalog_check"]["matches"]
    assert len(catalog["datasets"]) == kit["assembly"]["catalog_check"]["count"] == 557
    assert catalog["meta"]["captured_at_utc"] == kit["assembly"]["catalog_check"]["captured_at_utc"]
    assert len(matches) == 1
    assert matches[0]["name"] == "istanbul-da-devredilen-sozlesmeli-iskeleler"
    assert "IMM assembly" in matches[0]["notes"]
    assert not any("Barınma İndeksi" in item["title"] for item in matches)


def test_catalogues_only_the_public_language_and_keeps_quotes_turkish() -> None:
    kit = disaster_kit.load_kit()
    payload = disaster_kit.public_kit(kit, "en")
    assert payload["lang"] == "en"
    assert payload["items"][0]["label"] == "Durable, energy-giving food (such as biscuits)"
    assert payload["items"][0]["quote"] == "Dayanıklı, enerji veren gıdalar (bisküvi v.b.)"
    assert payload["notice"].startswith("This file stays on this device.")
    assert "capture_file" not in payload["sources"]["akom_sss"]
    assert payload["assembly"]["dataset_found"] is False
    assert "IMM assembly" not in json.dumps(payload, ensure_ascii=False)


def test_disaster_kit_api_is_get_only_and_never_caches() -> None:
    client = api_client()
    response = client.get("/api/disaster-kit")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert set(response.json()) == {
        "version",
        "lang",
        "sources",
        "items",
        "care",
        "contact_basis",
        "assembly",
        "building",
        "channels",
        "notice",
        "disclaimer",
        "captured_at",
    }
    assert len(response.json()["items"]) == 19
    assert client.get("/api/disaster-kit", params={"lang": "en"}).json()["lang"] == "en"
    assert client.get("/api/disaster-kit", params={"lang": "de"}).status_code == 400
    assert client.post("/api/disaster-kit").status_code == 405
    body = json.dumps(response.json(), ensure_ascii=False)
    assert find_forbidden(body) == ()
    assert "canlı" not in body and "—" not in body and "–" not in body


def test_unreadable_local_catalog_returns_503(monkeypatch) -> None:
    disaster_kit.load_kit.cache_clear()
    monkeypatch.setattr(disaster_kit, "DISASTER_KIT_PATH", REPO_ROOT / "data/knowledge/E70-missing.json")
    response = api_client().get("/api/disaster-kit")
    assert response.status_code == 503
    assert response.json()["error"] == "disaster_kit_unavailable"
    assert response.headers["cache-control"] == "no-store"
