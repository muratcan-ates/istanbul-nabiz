"""Source matching, strict fare parsing, and deterministic weekly calculations."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.knowledge.guardrails import host_allowed
from nabiz.console.fare_calc import choose_eticket_package, estimate, parse_pattern
from nabiz.console.fare_sources import (
    CAPTURE_PATH,
    FARES_PATH,
    fare_quotes_in_store,
    load_fare_catalog,
    parse_amount,
    validate_fare_catalog,
)

REAL_INDEX = REPO_ROOT / "data" / "knowledge" / "knowledge.db"


class ReadOnlyStore:
    """Small read-only adapter around documents.current_document."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def current_document(self, url: str) -> dict[str, Any] | None:
        uri = f"file:{self.path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT canonical_url, fetched_at, body FROM documents WHERE canonical_url=? AND active=1 "
                "ORDER BY fetched_at DESC LIMIT 1",
                (url,),
            ).fetchone()
        return dict(row) if row else None


@pytest.fixture(scope="module")
def catalog() -> dict[str, Any]:
    load_fare_catalog.cache_clear()
    return load_fare_catalog(FARES_PATH)


def pattern_data(**updates: Any) -> dict[str, Any]:
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


def option(result: dict[str, Any], key: str) -> dict[str, Any]:
    return next(row for row in result["options"] if row["id"] == key)


def test_catalog_sources_quotes_and_hosts_are_valid(catalog: dict[str, Any]) -> None:
    assert validate_fare_catalog(catalog) == []
    assert all(host_allowed(urlsplit(source["url"]).hostname or "") for source in catalog["sources"].values())
    assert catalog["metro"]["subscription"]["rows"]["ogrenci30"]["passes"] is None
    labels = {row["label"] for row in catalog["ferry"]["routes"]}
    assert "EMİNÖNÜ - KADIKÖY" not in labels
    assert not any("Adalar" in label for label in labels)
    assert catalog["ferry"]["columns"]["other"] == ["İndirimli (TL)"]


@pytest.mark.parametrize(
    ("raw", "style", "expected"),
    [("3.628 ₺", "tr", 362800), ("46,20 ₺", "tr", 4620), ("65 ₺", "tr", 6500),
     ("65.21", "dot", 6521), ("44.3", "dot", 4430)],
)
def test_amounts_are_parsed_without_guessing(raw: str, style: str, expected: int) -> None:
    assert parse_amount(raw, style) == expected


@pytest.mark.parametrize(("raw", "style"), [("3,628 ₺", "tr"), ("65.210", "dot"), ("1,2,3 ₺", "tr"), ("65 TL", "tr")])
def test_amount_rejects_unlisted_spellings(raw: str, style: str) -> None:
    with pytest.raises(ValueError):
        parse_amount(raw, style)


def test_quote_in_store_reads_only_the_existing_index(catalog: dict[str, Any]) -> None:
    if not REAL_INDEX.is_file():
        pytest.skip("gerçek dizin kopyası yok")
    before = REAL_INDEX.stat().st_mtime_ns
    assert fare_quotes_in_store(catalog, ReadOnlyStore(REAL_INDEX)) == []
    assert REAL_INDEX.stat().st_mtime_ns == before


def test_capture_is_consistent_with_unavailable_bus_tariff(catalog: dict[str, Any]) -> None:
    if not CAPTURE_PATH.is_file():
        pytest.skip("capture.json yok")
    capture = json.loads(CAPTURE_PATH.read_text(encoding="utf-8"))
    assert capture["schema"] == 1
    assert capture["requests"] <= 3
    assert catalog["missing"]["bus"]["status"] == capture["entries"][0]["status"]
    assert catalog["missing"]["bus"]["checked_at"] == capture["entries"][0]["requested_at"]
    assert all("/api/" not in (entry.get("url") or "") for entry in capture["entries"])
    assert all("igdas" not in (entry.get("url") or "").casefold() for entry in capture["entries"])
    assert [entry["status"] for entry in capture["entries"]] == ["alinamadi", "sitemap", "aday_yok"]


def test_full_metro_pattern_has_three_complete_options_and_a_real_lowest(catalog: dict[str, Any]) -> None:
    pattern, errors = parse_pattern(pattern_data(), catalog)
    assert not errors and pattern is not None
    result = estimate(pattern, catalog)
    assert [row["complete"] for row in result["options"]] == [True, True, True]
    assert option(result, "card_single")["known_weekly_kurus"] == 46200
    assert option(result, "eticket")["known_weekly_kurus"] == 53000
    assert option(result, "subscription")["known_weekly_kurus"] == 20160
    assert result["lowest"] == "subscription"
    assert result["lowest"] == min(result["options"], key=lambda row: row["known_weekly_kurus"])["id"]


def test_personalized_ferry_transfer_uses_its_own_source_column(catalog: dict[str, Any]) -> None:
    pattern, errors = parse_pattern(pattern_data(
        days_per_week=1,
        round_trip=False,
        legs=[{"mode": "metro"}, {"mode": "ferry", "route": "karakoy-kadikoy"}],
        within_window=True,
        personalized=True,
    ), catalog)
    assert not errors and pattern is not None
    line = option(estimate(pattern, catalog), "card_single")["lines"][1]
    assert line["label"] == "1. AKTARMA"
    assert line["column"] == "Tam (TL)"
    assert line["raw"] == "41.43"
    assert line["kurus"] == 4143
    assert line["quote"] == catalog["ferry"]["transfers"][0]["quote"]


def test_incomplete_vapur_then_metro_suppresses_any_lowest(catalog: dict[str, Any]) -> None:
    pattern, errors = parse_pattern(pattern_data(
        days_per_week=1,
        round_trip=False,
        legs=[{"mode": "ferry", "route": "karakoy-kadikoy"}, {"mode": "metro"}],
    ), catalog)
    assert not errors and pattern is not None
    result = estimate(pattern, catalog)
    assert option(result, "card_single")["lines"][1]["reason"] == "metro_transfer_rule_missing"
    assert not option(result, "card_single")["complete"]
    assert result["lowest"] is None


def test_unavailable_bus_price_stays_unknown_and_adds_nothing(catalog: dict[str, Any]) -> None:
    pattern, errors = parse_pattern(pattern_data(
        days_per_week=1, round_trip=False, legs=[{"mode": "bus"}],
    ), catalog)
    assert not errors and pattern is not None
    row = option(estimate(pattern, catalog), "card_single")
    assert row["known_weekly_kurus"] == 0
    assert row["unknown"] == [{"leg": 1, "mode": "bus", "reason": "bus_tariff_unavailable"}]
    assert row["lines"][0]["kurus"] is None


def test_student30_subscription_does_not_assume_a_pass_count(catalog: dict[str, Any]) -> None:
    pattern, errors = parse_pattern(pattern_data(tariff="ogrenci30"), catalog)
    assert not errors and pattern is not None
    result = estimate(pattern, catalog)
    assert option(result, "subscription")["computed"] is False
    assert option(result, "subscription")["reason"] == "passes_missing"
    assert result["lowest"] is None


def test_other_card_shows_quotes_without_a_calculated_amount(catalog: dict[str, Any]) -> None:
    pattern, errors = parse_pattern(pattern_data(
        tariff="other", legs=[{"mode": "ferry", "route": "karakoy-kadikoy"}],
    ), catalog)
    assert not errors and pattern is not None
    result = estimate(pattern, catalog)
    assert result["computed"] is False
    assert result["reason"] == "other_card"
    assert len(result["quotes"]) == 3
    assert all("kurus" not in row and row["quote"] for row in result["quotes"])
    assert next(row for row in result["quotes"] if row["source_id"] == "ferry")["column"] == "İndirimli (TL)"


def test_e_ticket_package_selection_reports_excess_passes(catalog: dict[str, Any]) -> None:
    packs = catalog["metro"]["eticket"]["packs"]
    ten = choose_eticket_package(10, packs)
    eleven = choose_eticket_package(11, packs)
    assert (ten["pack"]["label"], ten["count"], ten["unused_passes"], ten["amount_kurus"]) == (
        "On Geçişlik Kart", 1, 0, 53000,
    )
    assert (eleven["pack"]["label"], eleven["count"], eleven["unused_passes"], eleven["amount_kurus"]) == (
        "Dört Geçişlik Kart", 3, 1, 69000,
    )


@pytest.mark.parametrize(
    "data",
    [pattern_data(days_per_week=0), pattern_data(legs=[{"mode": "metro"}] * 6),
     pattern_data(legs=[{"mode": "ferry", "route": "unknown-route"}])],
)
def test_invalid_days_legs_and_routes_are_rejected(data: dict[str, Any]) -> None:
    pattern, errors = parse_pattern(data)
    assert pattern is None
    assert errors
