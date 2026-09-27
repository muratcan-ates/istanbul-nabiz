"""The event plan only carries phrases verified against the local knowledge index."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from conftest import REPO_ROOT

from ibb_mcp.knowledge.guardrails import host_allowed
from ibb_mcp.knowledge.store import KnowledgeStore
from ibb_mcp.text import normalize_tr
from nabiz.console.case_file_api import load_plans

PLAN_PATH = REPO_ROOT / "data/knowledge/life_events.json"
REAL_INDEX = REPO_ROOT / "data/knowledge/knowledge.db"
AGENCIES_PATH = REPO_ROOT / "data/agencies.json"
WATER_URLS = (
    "https://iski.istanbul/abone-hizmetleri/abone-rehberi/abonelik-iptal-islemleri/",
    "https://iski.istanbul/abone-hizmetleri/abone-rehberi/yenileme-abonelik-islemleri/",
    "https://grafikgoster.iski.gov.tr/abone-hizmetleri/abone-rehberi/yeni-abonelik-islemleri/",
)
PRICE_URL = "https://iski.istanbul/abone-hizmetleri/abone-rehberi/su-birim-fiyatlari"


def _reader(path: Path) -> KnowledgeStore:
    """Use the existing SELECT method without the constructor's schema and FTS setup writes."""
    store = object.__new__(KnowledgeStore)
    store.path = path
    return store


def _fold(value: str) -> str:
    return " ".join(value.split())


@pytest.fixture(scope="module")
def raw_plan() -> dict:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def plans():
    agencies = json.loads(AGENCIES_PATH.read_text(encoding="utf-8"))
    store = _reader(REAL_INDEX) if REAL_INDEX.is_file() else None
    return load_plans(PLAN_PATH, store, agencies)


def test_plan_shape_agencies_hosts_and_source_free_links(raw_plan, plans) -> None:
    assert set(raw_plan) == {"version", "checked_at", "index", "plans"}
    agency_ids = {item["id"] for item in json.loads(AGENCIES_PATH.read_text(encoding="utf-8"))["agencies"]}
    agency_ids.add("district_office")
    serialized = json.dumps(raw_plan, ensure_ascii=False)
    assert "devir" not in serialized.casefold()
    assert re.search(r"\btl\b", serialized, re.IGNORECASE) is None
    assert "teminat" not in serialized.casefold()
    assert "canlı" not in serialized.casefold()
    assert "hak kazan" not in serialized.casefold()
    assert "uygunsunuz" not in serialized.casefold()
    assert "borcunuz" not in serialized.casefold()
    assert "iade alırsınız" not in serialized.casefold()
    assert "\N{EM DASH}" not in serialized and "\N{EN DASH}" not in serialized
    assert re.search(r"\b0?\d{3}[ .]?\d{3}[ .]?\d{2}[ .]?\d{2}\b", serialized) is None
    assert re.search(r"\b\d{1,2}:\d{2}\b", serialized) is None
    urls = []
    for plan in raw_plan["plans"]:
        for step in plan["steps"]:
            assert step["agency"] in agency_ids
            if step["kind"] == "link":
                assert not any(source.get("quotes") or source.get("documents") for source in step["sources"])
            if step["agency"] == "igdas":
                assert not step["sources"]
            urls.extend(source["url"] for source in step["sources"])
    assert PRICE_URL not in urls
    assert all(host_allowed(urlsplit(url).hostname or "") for url in urls)
    assert len(plans) == 1
    assert [step["id"] for step in plans[0]["steps"]] == ["su", "dogalgaz", "istanbulkart", "sosyal-nokta", "ilce", "153"]


def test_three_water_pages_are_individually_active_and_exact(plans) -> None:
    if not REAL_INDEX.is_file():
        pytest.skip("gerçek dizin kopyası yok")
    step = plans[0]["steps"][0]
    assert step["id"] == "su"
    assert [source["url"] for source in step["sources"]] == list(WATER_URLS)
    store = _reader(REAL_INDEX)
    for url, source in zip(WATER_URLS, step["sources"], strict=True):
        page = store.current_document(url)
        assert page is not None and page["active"] == 1, url
        body = _fold(page["body"])
        assert source["indexed"] is True and source["fetched_at"] == page["fetched_at"]
        for quote in source["quotes"] + source["documents"]:
            assert _fold(quote) in body, (url, quote)
    assert step["choices"][0]["source"] == 0 and "abonelik-iptal-islemleri" in step["sources"][0]["url"]
    assert step["choices"][1]["source"] == 1 and "yenileme-abonelik-islemleri" in step["sources"][1]["url"]
    assert step["choices"][2]["source"] == 2 and "yeni-abonelik-islemleri" in step["sources"][2]["url"]
    assert step["choices"][3]["source"] is None


def test_other_indexed_pages_and_points_are_local_source_backed(plans) -> None:
    if not REAL_INDEX.is_file():
        pytest.skip("gerçek dizin kopyası yok")
    steps = {step["id"]: step for step in plans[0]["steps"]}
    assert steps["istanbulkart"]["sources"][0]["indexed"]
    assert steps["istanbulkart"]["sources"][1]["indexed"]
    points = steps["sosyal-nokta"]["points"]
    page = _reader(REAL_INDEX).current_document(steps["sosyal-nokta"]["sources"][0]["url"])
    assert points and len(points) == len(re.findall(r"^\|\s*\d+\s*$", page["body"], re.MULTILINE))
    body = _fold(page["body"])
    assert all(_fold(item["address"]) in body for item in points)
    assert next(item for item in points if item["name"].startswith("Eyüpsultan"))["district"] == "Eyüpsultan"


def test_the_fourth_guide_match_is_the_excluded_tariff_page() -> None:
    if not REAL_INDEX.is_file():
        pytest.skip("gerçek dizin kopyası yok")
    store = _reader(REAL_INDEX)
    page = store.current_document(PRICE_URL)
    assert page is not None and page["active"] == 1
    body = normalize_tr(page["body"])
    assert "su satis tarifeleri" in body and "birim fiyat" in body
    data = PLAN_PATH.read_text(encoding="utf-8")
    assert PRICE_URL not in data
