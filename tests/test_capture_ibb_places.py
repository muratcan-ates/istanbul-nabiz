"""Offline contracts for the one-time IBB place capture script."""

from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import zipfile
from urllib.parse import urlsplit

import pytest

from ibb_mcp.models import LAT_RANGE, LON_RANGE

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "capture_ibb_places.py"
SPEC = importlib.util.spec_from_file_location("capture_ibb_places_under_test", SCRIPT)
assert SPEC and SPEC.loader
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


def test_capture_sources_are_direct_downloads_with_the_shared_box() -> None:
    assert tuple(capture.SOURCES) == ("halk_ekmek", "kent_lokantasi", "sosyal_tesis", "wifi")
    urls = [
        f"https://{capture.HOST}/dataset/{source[2]}/resource/{source[3]}/download/{source[4]}"
        for source in capture.SOURCES.values()
    ]
    assert all(urlsplit(url).hostname == "data.ibb.gov.tr" and "/api/" not in url for url in urls)
    assert capture.DELAY_S == 10
    assert capture.LAT == LAT_RANGE and capture.LON == LON_RANGE


def test_fetch_waits_once_between_two_mocked_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[int] = []

    class Reply:
        status = 200
        headers = {"Last-Modified": "test"}

        def __enter__(self) -> Reply:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return b"recorded"

        def geturl(self) -> str:
            return "https://data.ibb.gov.tr/download/test.csv"

    monkeypatch.setattr(capture.urllib.request, "urlopen", lambda *_args, **_kwargs: Reply())
    monkeypatch.setattr(capture.time, "sleep", waits.append)
    capture._requests = 0
    url = "https://data.ibb.gov.tr/download/test.csv"
    assert capture.fetch(url)[0] == 200
    assert capture.fetch(url)[0] == 200
    assert waits == [10]


def test_columns_never_treat_a_dealer_as_the_place_name() -> None:
    _, columns = capture.columns([["BAYİ ADI", "LATITUDE", "LONGITUDE"]])
    assert "name" not in columns


def test_place_accepts_decimal_swapped_and_wkt_coordinates() -> None:
    assert capture.place(["41,01", "29,02"], {"lat": 0, "lon": 1}) == (41.01, 29.02)
    assert capture.place(["29.02", "41.01"], {"lat": 0, "lon": 1}) == (41.01, 29.02)
    assert capture.place(["POINT (29.02 41.01)"], {"coord": 0}) == (41.01, 29.02)
    assert capture.place(["39.0", "29.0"], {"lat": 0, "lon": 1}) == "outside_istanbul"


def test_slim_blanks_contact_data_and_drops_repeated_rows() -> None:
    cols = {"name": 0, "district": 1, "address": 2, "lat": 3, "lon": 4}
    email = "adres" + chr(64) + "example.test"
    rows, dropped = capture.slim(
        [
            ["BÜFE", "Kadıköy", "0555 123 45 67", "40.99", "29.03"],
            ["BÜFE", "Kadıköy", email, "40.99", "29.03"],
        ],
        cols,
    )
    assert rows == [["BÜFE", "Kadıköy", "", 40.99, 29.03]]
    assert dropped["pii_blanked"] == 2
    assert dropped["duplicate"] == 1


def _xlsx_three_rows() -> bytes:
    shared = """<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <si><t>name</t></si><si><t>İlçe</t></si><si><t>Halk Ekmek</t></si><si><t>Kadıköy</t></si>
      <si><t>Üsküdar</t></si><si><t>Maltepe</t></si></sst>"""
    sheet = """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
      <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
      <row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2" t="s"><v>3</v></c></row>
      <row r="3"><c r="A3" t="s"><v>2</v></c><c r="B3" t="s"><v>4</v></c></row>
      </sheetData></worksheet>"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as book:
        book.writestr("xl/sharedStrings.xml", shared)
        book.writestr("xl/worksheets/sheet1.xml", sheet)
    return output.getvalue()


def test_xlsx_rows_reads_a_small_in_memory_workbook() -> None:
    rows = capture.xlsx_rows(_xlsx_three_rows())
    assert rows == [["name", "İlçe"], ["Halk Ekmek", "Kadıköy"], ["Halk Ekmek", "Üsküdar"]]


def test_csv_rows_supports_semicolons_and_cp1254() -> None:
    rows = capture.csv_rows("ad;ilçe\nHalk Ekmek;Kadıköy\n".encode("cp1254"))
    assert rows == [["ad", "ilçe"], ["Halk Ekmek", "Kadıköy"]]


def test_recorded_files_have_only_slim_in_bounds_rows_when_available() -> None:
    directory = ROOT / "data" / "reference" / "ibb_places"
    files = sorted(directory.glob("*.json")) if directory.is_dir() else []
    if not files:
        pytest.skip("captured reference files are absent")
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") != "alindi":
            continue
        assert payload["count"] > 0
        assert all(len(row) == 5 for row in payload["rows"])
        for row in payload["rows"]:
            assert LAT_RANGE[0] <= row[3] <= LAT_RANGE[1]
            assert LON_RANGE[0] <= row[4] <= LON_RANGE[1]
            assert not capture.PII.search(" ".join(str(value) for value in row[:3]))
