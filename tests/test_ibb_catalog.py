"""The İBB Open Data catalogue: its capture script against a mock transport, and its local search.

The CKAN answer is ``tests/fixtures/ckan_package_search_synthetic.json``: the shape of
``data.ibb.gov.tr``'s ``package_search``, with made-up content. Nothing here reaches the network.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import pathlib
import sys

import httpx
import pytest
from conftest import REPO_ROOT, read_fixture

from ibb_mcp import catalog as cat
from ibb_mcp import http
from ibb_mcp.http import PoliteClient

_spec = importlib.util.spec_from_file_location("capture_ibb_catalog", REPO_ROOT / "scripts" / "capture_ibb_catalog.py")
capture = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = capture
assert _spec.loader is not None
_spec.loader.exec_module(capture)
GAP_AS_SHIPPED = capture.MIN_GAP_S
CAPTURED = dt.datetime(2026, 9, 26, 9, 0, tzinfo=dt.UTC)


def ckan() -> dict:
    return read_fixture("ckan_package_search_synthetic.json")


def write_catalog(tmp_path: pathlib.Path, *, synthetic: bool = True) -> pathlib.Path:
    body = cat.build_catalog(ckan()["result"]["results"], captured_at=CAPTURED, count_reported=8, calls=1)
    body["meta"]["synthetic"] = synthetic
    path = tmp_path / "ibb_catalog.json"
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _no_spacing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(http.HOST_MIN_INTERVAL, "data.ibb.gov.tr", 0.0)


# -- the capture script -----------------------------------------------------------------
def test_a_dry_run_sends_nothing_and_names_the_limits(capsys: pytest.CaptureFixture[str]) -> None:
    assert capture.main([]) == 0
    out = capsys.readouterr().out
    assert "none sent" in out and "package_search?rows=1000&start=0" in out
    assert capture.MAX_CALLS == 3 and GAP_AS_SHIPPED >= 6.0


def test_live_refuses_under_the_offline_flag(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("NABIZ_OFFLINE", "1")
    assert capture.main(["--live"]) == 2
    assert "refusing" in capsys.readouterr().out


async def test_one_page_holds_the_whole_catalogue() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=ckan())

    async with PoliteClient(max_attempts=1, transport=httpx.MockTransport(handler)) as client:
        got = await capture.capture(client, gap_s=0.0)
    assert len(sent) == 1
    assert sent[0].url.host == "data.ibb.gov.tr" and sent[0].url.params["rows"] == "1000" and sent[0].url.params["start"] == "0"
    assert got.complete and not got.failed and len(got.packages) == 8


async def test_a_low_page_cap_stops_at_three_calls_and_says_partial() -> None:
    packages = ckan()["result"]["results"]
    starts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params["start"])
        starts.append(start)
        page = packages[start : start + 2]  # a portal that serves two per page, whatever is asked
        return httpx.Response(200, json={"success": True, "result": {"count": 8, "results": page}})

    async with PoliteClient(max_attempts=1, transport=httpx.MockTransport(handler)) as client:
        got = await capture.capture(client, gap_s=0.0)
    assert starts == [0, 2, 4]
    assert not got.complete and len(got.packages) == 6


async def test_a_failed_page_is_reported_by_status_and_nothing_is_kept() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="<html>stack trace</html>")

    async with PoliteClient(max_attempts=1, transport=httpx.MockTransport(handler)) as client:
        got = await capture.capture(client, gap_s=0.0)
    assert got.failed and got.rows[0]["status"] == 403 and "stack" not in json.dumps(got.rows)
    assert capture.page_results({"success": False}) is None


def test_written_files_are_slim_and_summarised(tmp_path: pathlib.Path) -> None:
    got = capture.Capture(packages=ckan()["result"]["results"], count=8, rows=[{"ok": True}])
    catalog, summary = capture.write_files(got, tmp_path, CAPTURED)
    record = next(item for item in catalog["datasets"] if item["name"] == "ispark-otopark-bilgileri")
    assert set(record) == {
        "name", "title", "notes", "organization", "groups", "tags", "license_title", "metadata_modified", "num_resources",
        "resources",
    }  # fmt: skip
    assert record["metadata_modified"] == "2026-09-20T08:15:00+00:00"
    assert record["resources"][0] == {
        "name": "İSPARK Lokasyonları",
        "format": "CSV",
        "url": "https://data.ibb.gov.tr/dataset/ispark-otopark-bilgileri/resource/a/download/ispark.csv",
        "last_modified": "2026-09-20T08:15:00+00:00",
        "datastore_active": True,
    }
    assert catalog["meta"]["complete"] is True and catalog["meta"]["count_captured"] == 8
    assert summary["datasets"] == 8 and summary["by_category"]["Mobilite"] == 3
    assert summary["recently_updated"][0]["name"] == "istanbul-barajlari-gunluk-doluluk-oranlari"
    assert (tmp_path / cat.CATALOG_FILE).is_file() and (tmp_path / cat.SUMMARY_FILE).is_file()


def test_notes_are_cut_to_six_hundred_characters() -> None:
    record = cat.slim_package({"name": "x", "notes": "a " * 700})
    assert len(record["notes"]) <= cat.NOTES_KEPT


def test_the_catalogue_file_is_gitignored() -> None:
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "data/reference/ibb_catalog.json" in ignored


# -- the search -------------------------------------------------------------------------
def test_no_catalogue_is_a_named_gap_not_an_empty_answer(tmp_path: pathlib.Path) -> None:
    result = cat.search_catalog("otopark", path=tmp_path / "missing.json")
    assert result.data["catalog"] == {"available": False} and result.data["datasets"] == []
    assert "make capture-catalog" in result.note and result.provenance.unread


def test_turkish_suffixes_and_generic_words_find_the_car_parks(tmp_path: pathlib.Path) -> None:
    result = cat.search_catalog("İBB'nin otopark verisi var mı?", path=write_catalog(tmp_path))
    names = [hit["name"] for hit in result.data["datasets"]]
    assert names[:2] == ["ispark-otopark-bilgileri", "mevcut-otopark-sayilari-ve-kapasiteleri"]
    hit = result.data["datasets"][0]
    assert hit["url"] == "https://data.ibb.gov.tr/dataset/ispark-otopark-bilgileri"
    assert hit["formats"] == ["CSV", "JSON"] and hit["datastore"] is True and hit["organization"] == "İSPARK A.Ş."
    assert result.data["mode"] == "search" and result.data["catalog"]["datasets"] == 8
    assert cat.SYNTHETIC_NOTE in result.note
    assert result.provenance.observed_at == CAPTURED


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("barajların doluluk oranları", "istanbul-barajlari-gunluk-doluluk-oranlari"),
        ("wifi noktaları", "ibb-wi-fi-lokasyon"),
        ("halk ekmek büfeleri", "istanbul-halk-ekmek-bufe-konumlari-veri-seti"),
        ("isbike bisiklet istasyonu", "tum-isbike-istasyonlari-web-servisi"),
    ],
)
def test_a_subject_finds_its_dataset_first(tmp_path: pathlib.Path, query: str, expected: str) -> None:
    result = cat.search_catalog(query, path=write_catalog(tmp_path))
    assert result.data["datasets"][0]["name"] == expected


def test_a_category_alone_lists_it_newest_first(tmp_path: pathlib.Path) -> None:
    result = cat.search_catalog("", category="cevre", limit=5, path=write_catalog(tmp_path))
    assert result.data["category"] == "Çevre" and result.data["mode"] == "category"
    assert [hit["name"] for hit in result.data["datasets"]] == [
        "istanbul-barajlari-gunluk-doluluk-oranlari", "parklar-ve-yesil-alanlar",
    ]  # fmt: skip
    counts = {item["name"]: item["count"] for item in result.data["categories"]}
    assert list(counts) == list(cat.CATEGORIES) and counts["Mobilite"] == 3


def test_an_unknown_category_and_a_bad_limit_are_refused(tmp_path: pathlib.Path) -> None:
    with pytest.raises(ValueError, match="Mobilite"):
        cat.search_catalog("otopark", category="Spor", path=write_catalog(tmp_path))
    with pytest.raises(ValueError):
        cat.search_catalog("otopark", limit=0, path=write_catalog(tmp_path))


def test_no_match_says_so(tmp_path: pathlib.Path) -> None:
    result = cat.search_catalog("uzay mekiği", path=write_catalog(tmp_path, synthetic=False))
    assert result.data["datasets"] == [] and "bulunamadı" in result.note


def test_a_description_that_talks_to_a_model_is_not_passed_on(tmp_path: pathlib.Path) -> None:
    result = cat.search_catalog("elektrik tüketimi", path=write_catalog(tmp_path))
    assert result.data["datasets"][0]["name"] == "elektrik-tuketim-verisi"
    assert result.data["datasets"][0]["summary"] is None


def test_an_unreadable_file_reads_as_missing(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    assert cat.load_catalog(path) is None
