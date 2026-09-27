"""Evidence, arithmetic and privacy checks for the bill catalogue."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.knowledge.guardrails import host_allowed
from nabiz.console.bill_helper import BILL_ITEMS_PATH, bill_quotes_in_store, load_bill_catalog, validate_bill_catalog

REAL_INDEX = REPO_ROOT / "data" / "knowledge" / "knowledge.db"


class ReadOnlyIndex:
    """Small read-only adapter matching the lookup used by source verification."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def current_document(self, url: str) -> dict[str, Any] | None:
        connection = sqlite3.connect(f"file:{self.path.resolve().as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                "SELECT * FROM documents WHERE url=? AND active=1 ORDER BY fetched_at DESC LIMIT 1", (url,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()


def test_catalog_is_valid_and_uses_only_supported_iskı_tariff_rows() -> None:
    catalog = load_bill_catalog()
    assert validate_bill_catalog(catalog) == []
    assert all(host_allowed(source["url"].split("/")[2]) for source in (
        item["source"] for item in catalog["items"] if item["source"]
    ))
    assert all(item["source"] is None for item in catalog["items"] if item["agency"] == "igdas")
    assert "ksub_rows" not in catalog["tariff"]
    for row in catalog["tariff"]["rows"]:
        assert round((row["water"] + row["wastewater"] - row["total"]) * 100) == 0


def test_catalog_quotes_and_tariff_values_match_the_read_only_index() -> None:
    if not REAL_INDEX.is_file():
        pytest.skip("gerçek dizin kopyası yok")
    catalog = load_bill_catalog()
    index = ReadOnlyIndex(REAL_INDEX)
    assert bill_quotes_in_store(catalog, index) == []
    connection = sqlite3.connect(f"file:{REAL_INDEX.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        source = catalog["tariff"]["source"]
        document = connection.execute("SELECT * FROM documents WHERE url=? AND active=1", (source["url"],)).fetchone()
        assert document
        assert document["fetched_at"] == source["fetched_at"]
        for row in catalog["tariff"]["rows"]:
            for amount in (row["water"], row["wastewater"], row["total"]):
                assert f"{amount:.2f}".replace(".", ",") in document["body"]
        ksub = document["body"].split("İSKİ GENEL MÜDÜRLÜĞÜ 2026 KSUB TARİFELERİ", 1)[1]
        household_values = []
        for marker in ("1.Kademe ( Konut Başına", "Konut 2.Kademe", "Konut 3.Kademe"):
            row_body = ksub.split(marker, 1)[1]
            match = re.search(r"(?m)^\s*(\d+,\d{2})\s*$", row_body)
            assert match, marker
            household_values.append(float(match.group(1).replace(",", ".")))
        assert household_values == [row["wastewater"] for row in catalog["tariff"]["rows"]]
        rural_body = ksub.split("Kırsal Mahalle /Yerleşik Alanlarda Konut", 1)[1]
        rural_value = re.search(r"(?m)^\s*(\d+,\d{2})\s*$", rural_body)
        assert rural_value and rural_value.group(1) == "32,64"
        assert float(rural_value.group(1).replace(",", ".")) == catalog["tariff"]["rows"][1]["wastewater"]
    finally:
        connection.close()


def test_saved_capture_time_matches_current_tariff_source() -> None:
    catalog = json.loads(BILL_ITEMS_PATH.read_text(encoding="utf-8"))
    assert catalog["captured_at"] == catalog["tariff"]["source"]["fetched_at"]
