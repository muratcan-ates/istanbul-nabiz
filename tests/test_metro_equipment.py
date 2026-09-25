"""Metro İstanbul's faulty-equipment source: parsing, the summary check, and the request rules.

Two kinds of input. Recorded İBB answers (``tests/fixtures/metro_faulty_equipment*_<date>.json``,
written by ``scripts/capture_metro_equipment.py``) are checked by the tests at the end, which skip
until a recording exists. Everything else uses records built here in the field shape verified on
2026-09-24 (``Code``, ``Group``, ``LineId``, ``LineName``, ``StationId``, ``StationName``,
``Location``, ``Type``, ``Date``, ``Description``); their values are test values, not İBB data,
and their stations are real rows of the recorded ``metro_stations.json`` so matching is exercised.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import shutil
from typing import Any

import httpx
import pytest
from conftest import FIXTURES_DIR, offline_settings

from ibb_mcp import http
from ibb_mcp.cache import TTLCache
from ibb_mcp.config import METRO_FAULTY_EQUIPMENT_DETAILS, METRO_FAULTY_EQUIPMENTS, Settings
from ibb_mcp.http import PoliteClient, UpstreamUnavailable
from ibb_mcp.models import MetroStation
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.sources.metro_equipment import (
    DATE_SEMANTICS_UNKNOWN,
    DETAILS_FIXTURE_PREFIX,
    EQUIPMENT_GROUPS,
    GROUP_UNAVAILABLE,
    LOCATION_EMPTY,
    NO_RECORDED_DATA,
    SUMMARY_DETAIL_MISMATCH,
    SUMMARY_FIXTURE_PREFIX,
    SUMMARY_UNREADABLE,
    UNKNOWN_STATUS_TYPE,
    EquipmentRecord,
    MetroEquipmentSource,
    details_body,
    details_fixture_name,
    group_slug,
    latest_fixture,
    line_key,
    match_station,
    parse_summary,
    resolve_group,
    summary_fixture_name,
    unwrap,
)


def record(station: str = "Kartal", line: str = "M4", *, station_id: int | None = 16, line_id: int | None = 3,
           group: str = "Asansör", kind: str = "Arıza", code: str = "TEST-ASN-01", date: str | None = "2026-09-20T08:00:00",
           location: str | None = None) -> dict[str, Any]:
    """One detail record in the verified field shape. Values are test values."""
    return {"Code": code, "Group": group, "LineId": line_id, "LineName": line, "StationId": station_id,
            "StationName": station, "Location": location, "Type": kind, "Date": date, "Description": None}


def envelope(rows: list[Any]) -> dict[str, Any]:
    return {"Success": True, "Error": None, "Data": rows}


def stations() -> list[MetroStation]:
    return [MetroStation.from_raw(row) for row in json.loads((FIXTURES_DIR / "metro_stations.json").read_text("utf-8"))["Data"]]


def write_recordings(
    directory: pathlib.Path, details: dict[str, list[Any]], summary: list[Any] | None, stamp: str = "20260101"
) -> None:
    """A private fixtures folder: the recorded station list plus equipment answers made here."""
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES_DIR / "metro_stations.json", directory / "metro_stations.json")
    for group, rows in details.items():
        (directory / f"{details_fixture_name(group, stamp)}.json").write_text(json.dumps(envelope(rows)), encoding="utf-8")
    if summary is not None:
        (directory / f"{summary_fixture_name(stamp)}.json").write_text(json.dumps(envelope(summary)), encoding="utf-8")


def offline_ctx(directory: pathlib.Path) -> SourceContext:
    settings = Settings(offline=True, fixtures_dir=directory)
    return SourceContext.create(client=PoliteClient(transport=httpx.MockTransport(_refuse)), cache=TTLCache(), settings=settings)


def _refuse(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"offline test reached the network: {request.url}")


# -- request rules --------------------------------------------------------------------
@pytest.mark.parametrize("group", EQUIPMENT_GROUPS)
def test_details_body_is_the_one_verified_shape(group: str) -> None:
    assert details_body(group) == {"EquipmentGroupName": group}


@pytest.mark.parametrize("bad", ["", "Hat", "asansor", "Asansör ", "Giriş / Çıkış"])
def test_details_body_refuses_anything_else(bad: str) -> None:
    with pytest.raises(ValueError, match="Bilinmeyen ekipman grubu"):
        details_body(bad)


def test_resolve_group_accepts_how_people_type_it() -> None:
    assert resolve_group("asansor") == "Asansör"
    assert resolve_group("YÜRÜYEN MERDİVEN") == "Yürüyen Merdiven"
    assert resolve_group(" ") is None and resolve_group(None) is None
    with pytest.raises(ValueError):
        resolve_group("merdiven")


def test_fixture_names_carry_group_and_date() -> None:
    assert group_slug("Yürüyen Merdiven") == "yuruyen_merdiven"
    assert details_fixture_name("Asansör", "20260925") == "metro_faulty_equipment_details_asansor_20260925"
    assert summary_fixture_name("20260925") == "metro_faulty_equipments_20260925"
    # The two prefixes must not swallow each other's files.
    assert not DETAILS_FIXTURE_PREFIX.startswith(SUMMARY_FIXTURE_PREFIX)


def test_latest_fixture_picks_the_newest_dated_file(tmp_path: pathlib.Path) -> None:
    for stamp in ("20260101", "20260925", "20260301"):
        (tmp_path / f"{summary_fixture_name(stamp)}.json").write_text("[]")
    (tmp_path / "metro_faulty_equipments_latest.json").write_text("[]")  # not a date: ignored
    assert latest_fixture(tmp_path, SUMMARY_FIXTURE_PREFIX) == "metro_faulty_equipments_20260925"
    assert latest_fixture(tmp_path, "metro_faulty_equipment_details_asansor_") is None


# -- parsing --------------------------------------------------------------------------
def test_unwrap_reads_the_envelope_and_a_bare_list() -> None:
    assert unwrap(envelope([1, 2]), source="t") == [1, 2]
    assert unwrap([3], source="t") == [3]
    assert unwrap({"Success": True, "Data": None}, source="t") == []


def test_unwrap_never_repeats_the_services_error_text() -> None:
    """An error there can carry server internals; the message names the failure, not the text."""
    leaked = "System.NullReferenceException at C:\\build\\Metro\\Controllers\\Equipment.cs:line 42"
    with pytest.raises(UpstreamUnavailable) as caught:
        unwrap({"Success": False, "Error": leaked, "Data": None}, source="metro_equipment")
    assert "Exception" not in str(caught.value) and "C:\\" not in str(caught.value)


def test_a_record_keeps_every_verified_field() -> None:
    parsed = EquipmentRecord.from_raw(record(location="Kuzey girişi"))
    assert (parsed.code, parsed.group, parsed.equipment_type) == ("TEST-ASN-01", "Asansör", "elevator")
    assert (parsed.line_id, parsed.line_name, parsed.station_id, parsed.station_name) == (3, "M4", 16, "Kartal")
    assert (parsed.status_type, parsed.status_class, parsed.location) == ("Arıza", "fault", "Kuzey girişi")
    assert parsed.ibb_date == dt.datetime(2026, 9, 20, 5, 0, tzinfo=dt.UTC)  # İstanbul 08:00


@pytest.mark.parametrize(("kind", "cls"), [("Arıza", "fault"), ("Revizyon", "revision"), ("Çalıştırılmıyor", "not_operated"),
                                           ("ARIZA", "fault")])
def test_each_type_seen_is_its_own_class(kind: str, cls: str) -> None:
    assert EquipmentRecord.from_raw(record(kind=kind)).status_class == cls


def test_an_unknown_type_is_kept_as_unknown_not_dropped() -> None:
    parsed = EquipmentRecord.from_raw(record(kind="Tasarruf-Güvenlik"))
    assert parsed.status_class == "unknown" and parsed.status_label == "Tasarruf-Güvenlik"
    assert UNKNOWN_STATUS_TYPE in parsed.uncertainty()
    assert EquipmentRecord.from_raw(record(kind=None)).status_label == "bilinmiyor"


def test_the_date_is_labelled_undocumented_and_an_empty_location_is_flagged() -> None:
    codes = EquipmentRecord.from_raw(record(location="  ")).uncertainty()
    assert DATE_SEMANTICS_UNKNOWN in codes and LOCATION_EMPTY in codes
    assert DATE_SEMANTICS_UNKNOWN not in EquipmentRecord.from_raw(record(date=None)).uncertainty()


@pytest.mark.parametrize("raw", ["2011-01-01", "14.04.2026", "14.04.2026 00:00:00", "2026-04-14T00:00:00"])
def test_date_shapes_parse(raw: str) -> None:
    assert EquipmentRecord.from_raw(record(date=raw)).ibb_date is not None


def test_describe_says_what_ibb_recorded_and_never_that_anything_works() -> None:
    text = EquipmentRecord.from_raw(record(kind="Revizyon")).describe()
    assert "Kartal (M4)" in text and "Revizyon" in text and "İBB kaydındaki tarih: 20.09.2026" in text
    assert "çalışıyor" not in text.casefold()


def test_outage_id_is_stable_across_snapshots_and_differs_per_date() -> None:
    a, b = EquipmentRecord.from_raw(record()), EquipmentRecord.from_raw(record())
    assert a.outage_id == b.outage_id
    assert a.outage_id != EquipmentRecord.from_raw(record(date="2026-09-21T08:00:00")).outage_id


def test_line_key_takes_the_leading_code() -> None:
    assert line_key("M2 Yenikapı-Hacıosman") == line_key("m2") == "M2"
    assert line_key("M1A") == "M1A" and line_key(None) == ""


# -- matching a record to a station ----------------------------------------------------
def test_match_by_id_when_the_name_agrees() -> None:
    found = match_station(EquipmentRecord.from_raw(record()), stations())
    assert found is not None and (found.name, found.line_name) == ("Kartal", "M4")


def test_an_id_whose_name_disagrees_is_not_trusted() -> None:
    parsed = EquipmentRecord.from_raw(record(station="Taksim", line="M2", station_id=16))
    found = match_station(parsed, stations())
    assert found is not None and (found.name, found.line_name) == ("Taksim", "M2")


def test_match_by_name_and_line_picks_the_right_platform_of_an_interchange() -> None:
    parsed = EquipmentRecord.from_raw(record(station="YENİKAPI", line="M1A", station_id=None, line_id=None))
    found = match_station(parsed, stations())
    assert found is not None and found.line_name == "M1A"


def test_an_unknown_station_matches_nothing() -> None:
    assert match_station(EquipmentRecord.from_raw(record(station="Yokistasyon", station_id=None)), stations()) is None


# -- the summary ----------------------------------------------------------------------
def test_summary_rows_are_found_by_value_and_count_words() -> None:
    rows = [{"Name": "Asansör", "Active": 668, "Inactive": 10}, {"Name": "Hat", "Active": 18, "Inactive": 1}, "junk"]
    (row,) = parse_summary(rows)
    assert (row.group, row.active, row.inactive) == ("Asansör", 668, 10)


def test_a_summary_row_without_a_recognisable_count_is_skipped_not_guessed() -> None:
    assert parse_summary([{"Name": "Asansör", "Count": 10}]) == []


async def test_summary_detail_mismatch_is_an_uncertainty_code(tmp_path: pathlib.Path) -> None:
    """24.09.2026's shape: the summary counted 10 "Arıza", the detail listed 14 unusable lifts."""
    lifts = [record(code=f"A{i}") for i in range(10)] + [record(code=f"R{i}", kind="Revizyon") for i in range(4)]
    write_recordings(tmp_path, {"Asansör": lifts}, [{"Name": "Asansör", "Active": 668, "Inactive": 10}])
    snap, _ = await MetroEquipmentSource(offline_ctx(tmp_path)).snapshot(("Asansör",))
    assert SUMMARY_DETAIL_MISMATCH in snap.uncertainty
    (row,) = snap.summary
    assert (row.inactive, row.detail_count, row.consistent) == (10, 14, False)
    assert row.detail_by_type == {"Arıza": 10, "Revizyon": 4}


async def test_an_agreeing_summary_raises_no_mismatch(tmp_path: pathlib.Path) -> None:
    write_recordings(tmp_path, {"Asansör": [record()]}, [{"Name": "Asansör", "Active": 5, "Inactive": 1}])
    snap, _ = await MetroEquipmentSource(offline_ctx(tmp_path)).snapshot(("Asansör",))
    assert SUMMARY_DETAIL_MISMATCH not in snap.uncertainty and snap.summary[0].consistent is True


async def test_an_unreadable_summary_is_said_not_hidden(tmp_path: pathlib.Path) -> None:
    write_recordings(tmp_path, {"Asansör": [record()]}, None)
    snap, _ = await MetroEquipmentSource(offline_ctx(tmp_path)).snapshot(("Asansör",))
    assert SUMMARY_UNREADABLE in snap.uncertainty and snap.available


# -- the source, offline ---------------------------------------------------------------
async def test_offline_without_a_recording_is_no_data_and_costs_nothing_twice(tmp_path: pathlib.Path) -> None:
    write_recordings(tmp_path, {}, None)
    source = MetroEquipmentSource(offline_ctx(tmp_path))
    snap, provenance = await source.snapshot()
    assert not snap.available and snap.uncertainty == [NO_RECORDED_DATA]
    assert snap.groups_missing == list(EQUIPMENT_GROUPS) and provenance.source == "metro_equipment"
    again, _ = await source.snapshot()
    assert again.uncertainty == [NO_RECORDED_DATA]


async def test_nothing_recorded_leaves_the_stamp_unread_with_no_age(tmp_path: pathlib.Path) -> None:
    """No record read means no time: the stamp is not "now", so no answer says "0 sn önce"."""
    from nabiz.agent.templates import render_answer

    write_recordings(tmp_path, {}, None)
    _, provenance = await MetroEquipmentSource(offline_ctx(tmp_path)).snapshot()
    assert provenance.observed_at is None and provenance.reported_at is None and provenance.unread
    assert provenance.describe_age() == "kayıt yok" and provenance.shown_age_seconds is None
    payload = {"data": {"available": False}, "provenance": {"age": None}}
    assert "Verinin yaşı" not in render_answer("metro_equipment_status", payload, "tr")


async def test_a_missing_group_is_named(tmp_path: pathlib.Path) -> None:
    write_recordings(tmp_path, {"Asansör": [record()]}, None)
    snap, _ = await MetroEquipmentSource(offline_ctx(tmp_path)).snapshot()
    assert snap.groups_read == ["Asansör"] and GROUP_UNAVAILABLE in snap.uncertainty
    assert snap.groups_missing == ["Yürüyen Merdiven", "Yürüyen Bant"]


async def test_offline_answers_are_dated_by_their_recording(tmp_path: pathlib.Path) -> None:
    write_recordings(tmp_path, {"Asansör": [record()]}, None)
    report = [{"name": details_fixture_name("Asansör", "20260101"), "captured_at_utc": "2026-01-01T06:00:00+00:00"}]
    (tmp_path / "_capture_report.json").write_text(json.dumps(report), encoding="utf-8")
    _, provenance = await MetroEquipmentSource(offline_ctx(tmp_path)).snapshot(("Asansör",))
    assert provenance.observed_at == dt.datetime(2026, 1, 1, 6, 0, tzinfo=dt.UTC)


# -- the source, live (a mock transport; nothing leaves the machine) ----------------------
def live_ctx(handler) -> SourceContext:
    settings = Settings(offline=False, fixtures_dir=FIXTURES_DIR)
    return SourceContext.create(client=PoliteClient(transport=httpx.MockTransport(handler), max_attempts=1), cache=TTLCache(),
                                settings=settings)


async def test_live_calls_send_one_valid_body_per_group_and_a_get_for_the_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(http.HOST_MIN_INTERVAL, "api.ibb.gov.tr", 0.0)
    seen: list[tuple[str, str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, str(request.url), body))
        if request.method == "GET":
            return httpx.Response(200, json=envelope([{"Name": "Asansör", "Inactive": 1}]))
        assert body and body["EquipmentGroupName"] in EQUIPMENT_GROUPS, "an invalid body was sent"
        return httpx.Response(200, json=envelope([record(group=body["EquipmentGroupName"])]))

    snap, _ = await MetroEquipmentSource(live_ctx(handler)).snapshot()
    posts = [s for s in seen if s[0] == "POST"]
    assert [b["EquipmentGroupName"] for _, _, b in posts] == list(EQUIPMENT_GROUPS)
    assert all(url == METRO_FAULTY_EQUIPMENT_DETAILS for _, url, _ in posts)
    assert [url for method, url, _ in seen if method == "GET"] == [METRO_FAULTY_EQUIPMENTS]
    assert len(seen) == 4 and len(snap.records) == 3


async def test_a_failed_group_is_missing_and_the_error_page_never_reaches_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(http.HOST_MIN_INTERVAL, "api.ibb.gov.tr", 0.0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=envelope([]))
        if json.loads(request.content)["EquipmentGroupName"] == "Yürüyen Bant":
            return httpx.Response(404, text="Server Error in '/' Application. at C:\\build\\Metro.cs line 1")
        return httpx.Response(200, json=envelope([]))

    snap, _ = await MetroEquipmentSource(live_ctx(handler)).snapshot()
    assert snap.groups_missing == ["Yürüyen Bant"] and GROUP_UNAVAILABLE in snap.uncertainty
    assert "C:\\" not in json.dumps(snap.model_dump(mode="json"))


async def test_live_with_every_group_down_is_an_upstream_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(http.HOST_MIN_INTERVAL, "api.ibb.gov.tr", 0.0)
    with pytest.raises(UpstreamUnavailable):
        await MetroEquipmentSource(live_ctx(lambda request: httpx.Response(404))).snapshot()


async def test_post_json_reports_a_non_json_answer_by_status_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(http.HOST_MIN_INTERVAL, "api.ibb.gov.tr", 0.0)
    client = PoliteClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>stack trace C:\\x</html>")))
    with pytest.raises(UpstreamUnavailable) as caught:
        await client.post_json(METRO_FAULTY_EQUIPMENT_DETAILS, source="metro_equipment", body=details_body("Asansör"))
    assert "stack" not in str(caught.value) and caught.value.status == 200


# -- recorded İBB answers (skip until scripts/capture_metro_equipment.py --live has run) ----------
RECORDED_DETAILS = sorted(FIXTURES_DIR.glob(f"{DETAILS_FIXTURE_PREFIX}*.json"))
RECORDED_SUMMARY = sorted(FIXTURES_DIR.glob(f"{SUMMARY_FIXTURE_PREFIX}*.json"))
NOT_RECORDED = "no recording yet: the owner runs scripts/capture_metro_equipment.py --live (NETWORK)"


@pytest.mark.skipif(not RECORDED_DETAILS, reason=NOT_RECORDED)
@pytest.mark.parametrize("path", RECORDED_DETAILS, ids=lambda p: p.stem)
def test_every_recorded_detail_row_parses_and_names_a_known_station(path: pathlib.Path) -> None:
    rows = unwrap(json.loads(path.read_text("utf-8")), source=path.stem)
    parsed = [EquipmentRecord.from_raw(row) for row in rows]
    assert all(r.station_name for r in parsed), "a record without a station"
    matched = sum(match_station(r, stations()) is not None for r in parsed)
    assert matched == len(parsed), f"{len(parsed) - matched} of {len(parsed)} records match no GetStations row"


@pytest.mark.skipif(not RECORDED_SUMMARY, reason=NOT_RECORDED)
def test_the_recorded_summary_is_readable() -> None:
    rows = unwrap(json.loads(RECORDED_SUMMARY[-1].read_text("utf-8")), source="summary")
    assert {row.group for row in parse_summary(rows)} == set(EQUIPMENT_GROUPS)


@pytest.mark.skipif(not RECORDED_DETAILS, reason=NOT_RECORDED)
async def test_the_recorded_snapshot_reads_offline() -> None:
    ctx = SourceContext.create(client=PoliteClient(transport=httpx.MockTransport(_refuse)), settings=offline_settings())
    snap, provenance = await MetroEquipmentSource(ctx).snapshot()
    assert snap.available and provenance.observed_at < dt.datetime.now(dt.UTC)
