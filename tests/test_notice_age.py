from __future__ import annotations

import datetime as dt
import gzip
import json
import pathlib
import re
import subprocess

import httpx
import pytest
from conftest import offline_settings, refuse_network
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient, UpstreamUnavailable
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.console import brief, notice_age
from nabiz.console.brief import Freshness, metro_status_card, station_cards
from nabiz.console.cards import unknown_provenance
from nabiz.console.notice_age import (
    EQUIPMENT_SOURCE,
    METRO_SOURCE,
    archive_sentence,
    ibb_sentence,
    metro_history,
    notice_routes,
)

NOW = dt.datetime(2026, 9, 26, 7, tzinfo=dt.UTC)
READS = (
    "2026-09-08T17:30:30.824282Z",
    "2026-09-13T07:10:52Z",
    "2026-09-26T06:47:28.852062Z",
)
DESCRIPTION = (
    "Onarım çalışması nedeniyle seferler Yıldız-Mecidiyeköy ve Nurtepe istasyonundan aktarmalı olarak "
    "Çağlayan-Mahmutbey istasyonları arasında yapılmaktadır."
)
STATIC = pathlib.Path(__file__).parents[1] / "src" / "nabiz" / "console" / "static"


@pytest.fixture
def nabiz() -> Nabiz:
    client = PoliteClient(transport=httpx.MockTransport(refuse_network))
    return Nabiz(SourceContext.create(client=client, cache=TTLCache(), settings=offline_settings()))


def _stamp(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def write_part(root: pathlib.Path, source: str, snapshot_iso: str, rows: list[dict]) -> pathlib.Path:
    stamp = _stamp(snapshot_iso)
    folder = root / source / f"year={stamp:%Y}" / f"month={stamp:%m}" / f"day={stamp:%d}" / f"hour={stamp:%H}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stamp:%Y%m%dT%H%M%S}.ndjson.gz"
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def metro_row(snapshot_iso: str, *, line: str = "M7", description: str = DESCRIPTION, has_notice: bool = True) -> dict:
    return {
        "line_id": 7,
        "line_name": line,
        "description": description if has_notice else None,
        "is_active": True,
        "has_notice": has_notice,
        "ts_utc": "2026-07-27T06:27:37.103000Z" if has_notice else snapshot_iso,
        "snapshot_ts_utc": snapshot_iso,
        "color": "#F89ABA",
    }


def set_lake(monkeypatch, tmp_path: pathlib.Path) -> None:
    monkeypatch.setenv("NABIZ_LAKE_DIR", str(tmp_path))
    notice_age.clear_cache()
    monkeypatch.setattr(notice_age, "utcnow", lambda: NOW)
    monkeypatch.setattr(brief, "utcnow", lambda: NOW)


class StepFree:
    def __init__(self, lift: str = "out_of_service") -> None:
        self.lift = lift

    async def alternative(self, station: str, needs: list[str]) -> dict:
        return {
            "lift_status": self.lift,
            "stale": False,
            "provenance": unknown_provenance("metro_equipment"),
        }


def test_three_reads_give_the_archive_sentence(tmp_path: pathlib.Path, monkeypatch) -> None:
    set_lake(monkeypatch, tmp_path)
    for stamp in READS:
        write_part(tmp_path, METRO_SOURCE, stamp, [metro_row(stamp)])
    seen = metro_history(notice_age.cached_rows(METRO_SOURCE, now=NOW))[notice_age.notice_key("M7", DESCRIPTION)]

    assert seen.seen_reads == seen.total_reads == 3
    assert archive_sentence(seen) == (
        "Nabız 08.09.2026 ile 26.09.2026 arasında 3 gün okudu; 3 okumanın hepsinde bildirim yayındaydı. "
        "Okumalar her gün yapılmadı."
    )


def test_a_heartbeat_read_counts_as_a_read_without_the_notice(tmp_path: pathlib.Path, monkeypatch) -> None:
    set_lake(monkeypatch, tmp_path)
    for stamp in READS:
        write_part(tmp_path, METRO_SOURCE, stamp, [metro_row(stamp)])
    heartbeat = "2026-09-26T08:47:28Z"
    write_part(tmp_path, METRO_SOURCE, heartbeat, [metro_row(heartbeat, has_notice=False)])  # Sentetik kayıp okuması.
    seen = metro_history(notice_age.cached_rows(METRO_SOURCE, now=NOW))[notice_age.notice_key("M7", DESCRIPTION)]

    assert seen.total_reads == 4 and seen.seen_reads == 3
    assert "4 okumadan 3 tanesinde" in archive_sentence(seen)


def test_the_ibb_sentence_says_at_least_and_no_end(tmp_path: pathlib.Path, monkeypatch) -> None:
    set_lake(monkeypatch, tmp_path)
    sentence = ibb_sentence(_stamp("2026-07-27T06:27:37.103000Z"))

    assert "27.07.2026 tarihinde güncelledi" in sentence
    assert "en az bu tarihten beri yayında" in sentence
    assert "Başlangıç tarihi yayımlanmıyor, bitiş tahmini yok." in sentence
    assert all(word not in sentence for word in ("sürekli", "çalışıyor", "ETA", "—", "–"))


def test_partitions_older_than_the_window_are_not_opened(tmp_path: pathlib.Path, monkeypatch) -> None:
    set_lake(monkeypatch, tmp_path)
    old = tmp_path / METRO_SOURCE / "year=2026" / "month=08" / "day=01" / "hour=00" / "old.ndjson.gz"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"not a gzip file")
    monkeypatch.setattr(notice_age.gzip, "open", lambda *args, **kwargs: pytest.fail("old partition opened"))

    assert notice_age.read_rows(METRO_SOURCE, tmp_path, since=dt.date(2026, 8, 22)) == []


def test_a_broken_partition_is_skipped_and_logged_by_type_only(tmp_path: pathlib.Path, monkeypatch, caplog) -> None:
    set_lake(monkeypatch, tmp_path)
    path = tmp_path / METRO_SOURCE / "year=2026" / "month=09" / "day=26" / "hour=06" / "secret-row.ndjson.gz"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"private row text is not a gzip stream")

    assert notice_age.read_rows(METRO_SOURCE, tmp_path, since=dt.date(2026, 8, 22)) == []
    assert "notice lake partition unreadable: BadGzipFile" in caplog.text
    assert "secret-row.ndjson.gz" not in caplog.text
    assert "private row text" not in caplog.text


def test_rows_are_cached_for_five_minutes(tmp_path: pathlib.Path, monkeypatch) -> None:
    set_lake(monkeypatch, tmp_path)
    calls = 0
    real_read_rows = notice_age.read_rows

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_read_rows(*args, **kwargs)

    tick = [10.0]
    monkeypatch.setattr(notice_age, "read_rows", counted)
    monkeypatch.setattr(notice_age.time, "monotonic", lambda: tick[0])
    first = notice_age.cached_rows(METRO_SOURCE, now=NOW)
    tick[0] = 309.0
    second = notice_age.cached_rows(METRO_SOURCE, now=NOW)
    assert first is second and calls == 1
    tick[0] = 311.0
    notice_age.cached_rows(METRO_SOURCE, now=NOW)
    assert calls == 2


@pytest.mark.asyncio
async def test_the_metro_card_carries_both_sentences(nabiz: Nabiz, tmp_path: pathlib.Path, monkeypatch) -> None:
    set_lake(monkeypatch, tmp_path)
    for stamp in READS:
        write_part(tmp_path, METRO_SOURCE, stamp, [metro_row(stamp)])

    card = await metro_status_card(nabiz, ["M7"], Freshness(True, 900, 180))

    assert card["body"].removeprefix("Son bilinen durum: ").startswith("M7: Onarım çalışması")
    assert "27.07.2026 tarihinde güncelledi" in card["body"]
    assert "Nabız 08.09.2026 ile 26.09.2026 arasında 3 gün okudu" in card["body"]
    assert set(card) == {"id", "kind", "title", "body", "status", "provenance", "author", "how"}
    assert all(word not in card["body"] for word in ("sürekli", "ETA", "—", "–"))


@pytest.mark.asyncio
async def test_without_an_archive_the_metro_card_has_only_the_ibb_sentence(
    nabiz: Nabiz, tmp_path: pathlib.Path, monkeypatch
) -> None:
    set_lake(monkeypatch, tmp_path)

    card = await metro_status_card(nabiz, ["M7"], Freshness(True, 900, 180))

    assert "27.07.2026 tarihinde güncelledi" in card["body"]
    assert "Nabız " not in card["body"]


@pytest.mark.asyncio
async def test_the_lift_card_shows_the_record_date_with_its_caveat(
    nabiz: Nabiz, tmp_path: pathlib.Path, monkeypatch
) -> None:
    set_lake(monkeypatch, tmp_path)

    cards = await station_cards(StepFree(), "Taksim", [], nabiz=nabiz)

    assert "İBB kaydındaki tarih (anlamı belgelenmemiş; dönüş tarihi değildir):" in cards[0]["body"]
    assert "14.04.2026" in cards[0]["body"]


@pytest.mark.asyncio
async def test_null_equipment_rows_give_no_lift_archive_sentence(
    nabiz: Nabiz, tmp_path: pathlib.Path, monkeypatch
) -> None:
    set_lake(monkeypatch, tmp_path)
    for index, stamp in enumerate(READS):
        write_part(tmp_path, EQUIPMENT_SOURCE, stamp, [{
            "snapshot_ts_utc": stamp, "has_record": False, "station_name": None, "line_name": None,
            "equipment_type": None, "status_class": "unknown", "ibb_date_raw": None,
            "outage_id": f"||elevator@tarihsiz-{index}",
        }])

    cards = await station_cards(StepFree(), "Taksim", [], nabiz=nabiz)

    assert "Nabız'ın ekipman arşivinde" not in cards[0]["body"]


@pytest.mark.asyncio
async def test_equipment_rows_with_a_station_give_the_at_least_sentence(
    nabiz: Nabiz, tmp_path: pathlib.Path, monkeypatch
) -> None:
    set_lake(monkeypatch, tmp_path)
    result = await nabiz.metro_equipment_status(station="Taksim", group="Asansör")
    record = next(item for item in result.data["records"] if item.get("equipment_type") == "elevator")
    assert record["ibb_date_raw"]
    for stamp in READS:
        write_part(tmp_path, EQUIPMENT_SOURCE, stamp, [{
            "snapshot_ts_utc": stamp, "has_record": True, "station_name": "Taksim", "line_name": "M2",
            "equipment_type": "elevator", "status_class": "fault", "ibb_date_raw": record["ibb_date_raw"],
            "ibb_date": record["ibb_date"], "outage_id": "not-used-for-matching",
        }])

    cards = await station_cards(StepFree(), "Taksim", [], nabiz=nabiz)

    assert "Nabız'ın ekipman arşivinde bu kayıt en az" in cards[0]["body"]
    assert "3 okumadan 3 tanesinde" in cards[0]["body"]


@pytest.mark.asyncio
async def test_a_lift_record_missing_from_some_reads_does_not_claim_it_stayed(
    nabiz: Nabiz, tmp_path: pathlib.Path, monkeypatch
) -> None:
    set_lake(monkeypatch, tmp_path)
    result = await nabiz.metro_equipment_status(station="Taksim", group="Asansör")
    record = next(item for item in result.data["records"] if item.get("equipment_type") == "elevator")
    for index, stamp in enumerate(READS):
        # Synthetic gap: the middle read saw Taksim's lift group without this record (the real 26 Sep lake has such reads).
        date_raw = record["ibb_date_raw"] if index != 1 else "2026-09-26T00:00:00.000"
        write_part(tmp_path, EQUIPMENT_SOURCE, stamp, [{
            "snapshot_ts_utc": stamp, "has_record": True, "station_name": "Taksim", "line_name": "M2",
            "equipment_type": "elevator", "status_class": "fault", "ibb_date_raw": date_raw,
            "ibb_date": record["ibb_date"], "outage_id": "not-used-for-matching",
        }])

    body = (await station_cards(StepFree(), "Taksim", [], nabiz=nabiz))[0]["body"]

    assert "bu kaydı ilk kez 08.09.2026 20.30 tarihinde gördü; o tarihten beri 3 okumadan 2 tanesinde var." in body
    assert "en az" not in body.split("Nabız'ın ekipman arşivi")[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("lift", ["working", "unknown"])
async def test_a_working_or_unknown_lift_gets_no_date_sentence(
    nabiz: Nabiz, lift: str, tmp_path: pathlib.Path, monkeypatch
) -> None:
    set_lake(monkeypatch, tmp_path)

    cards = await station_cards(StepFree(lift), "Taksim", [], nabiz=nabiz)

    assert "tarih" not in cards[0]["body"].lower()


def _client(nabiz: Nabiz) -> TestClient:
    app = FastAPI()
    app.include_router(notice_routes)
    app.state.nabiz = nabiz
    return TestClient(app)


def test_console_endpoint_lists_current_and_gone_notices(
    nabiz: Nabiz, tmp_path: pathlib.Path, monkeypatch
) -> None:
    set_lake(monkeypatch, tmp_path)
    removed = "Test için arşivde olup güncel yanıtta bulunmayan duyuru."  # Sentetik kaybolma senaryosu.
    endpoint_reads = ("2026-09-22T03:40:00Z", "2026-09-23T03:40:00Z", READS[2])
    for index, stamp in enumerate(endpoint_reads):
        rows = [metro_row(stamp)]
        if index == 1:
            rows.append(metro_row(stamp, line="T1", description=removed))
        write_part(tmp_path, METRO_SOURCE, stamp, rows)

    with _client(nabiz) as client:
        response = client.get("/api/console/metro-notices")

    payload = response.json()
    assert response.status_code == 200
    assert payload["notices"][0]["line"] == "M7"
    assert payload["notices"][0]["seen_reads"] == payload["notices"][0]["total_reads"] == 3
    assert payload["gone"][0]["line"] == "T1"
    assert payload["archive"]["metro_reads"] == 3
    assert payload["archive"]["equipment_rows"] == payload["archive"]["equipment_readable_rows"] == 0
    assert "Ekipman arşivinde istasyon adı taşıyan kayıt yok" in payload["note"]


def test_console_endpoint_survives_an_unreadable_source(
    nabiz: Nabiz, tmp_path: pathlib.Path, monkeypatch
) -> None:
    set_lake(monkeypatch, tmp_path)
    for stamp in READS:
        write_part(tmp_path, METRO_SOURCE, stamp, [metro_row(stamp)])

    async def unreadable():
        raise UpstreamUnavailable("offline fixture failure", source="metro_status")

    nabiz.metro_status = unreadable
    with _client(nabiz) as client:
        response = client.get("/api/console/metro-notices")

    assert response.status_code == 200
    assert response.json()["current_readable"] is False
    assert response.json()["notices"][0]["line"] == "M7"


def test_notice_files_follow_the_page_rules(tmp_path: pathlib.Path, monkeypatch) -> None:
    set_lake(monkeypatch, tmp_path)
    script = (STATIC / "js" / "console_notices.js").read_text(encoding="utf-8")
    styles = (STATIC / "css" / "console_notices.css").read_text(encoding="utf-8")
    assert "/api/console/metro-notices" in script
    assert 'role="status"' in script and "esc(" in script
    # "N okumadan M tanesinde": the total comes first, as in the card sentence.
    assert "${num(item.total_reads, 0)} okumadan ${num(item.seen_reads, 0)} tanesinde" in script
    assert all(word not in script for word in ("çalışıyor", "sürekli", "ETA", "—", "–"))
    assert re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\s*\(", styles) is None
    subprocess.run(["node", "--check", str(STATIC / "js" / "console_notices.js")], check=True, capture_output=True)
