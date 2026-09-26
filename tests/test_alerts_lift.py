"""Pure and offline coverage for the Metro İstanbul lift-outage alert rule."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
from conftest import FIXTURES_DIR
from test_metro_equipment import offline_ctx, record, stations, write_recordings

from ibb_mcp.alerts.engine import _lift_observation, build_context, check_alerts, parse_subscription
from ibb_mcp.alerts.lift import LiftOutageRule
from ibb_mcp.alerts.rules import AlertContext, LiftObservation
from ibb_mcp.cache import TTLCache
from ibb_mcp.config import METRO_FAULTY_EQUIPMENT_DETAILS, Settings
from ibb_mcp.http import PoliteClient
from ibb_mcp.models import Provenance, utcnow
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.sources.metro_equipment import DATE_SEMANTICS_UNKNOWN, LOCATION_EMPTY, EquipmentRecord, EquipmentSnapshot


def _equipment_record(**overrides: object) -> EquipmentRecord:
    return EquipmentRecord.from_raw(record(**overrides))


def _observation(
    records: tuple[EquipmentRecord, ...],
    *,
    station_rows=None,
    groups_read: tuple[str, ...] = ("Asansör",),
    stale: bool = False,
    uncertainty: tuple[str, ...] = (),
    provenance: Provenance | None = None,
) -> LiftObservation:
    return LiftObservation(
        records=records,
        stations=tuple(station_rows if station_rows is not None else stations()),
        provenance=provenance
        or Provenance(source="metro_equipment", source_url=METRO_FAULTY_EQUIPMENT_DETAILS),
        groups_read=groups_read,
        stale=stale,
        uncertainty=uncertainty,
    )


def test_lift_rule_is_silent_without_an_observation() -> None:
    assert LiftOutageRule(stations=("Kartal",)).evaluate(AlertContext()) is None


def test_lift_rule_is_silent_for_an_unwatched_station() -> None:
    rule = LiftOutageRule(stations=("Kadıköy",))
    alert = rule.evaluate(AlertContext(lift=_observation((_equipment_record(),))))
    assert alert is None


def test_lift_rule_warns_when_another_recorded_lift_remains() -> None:
    alert = LiftOutageRule(stations=("Kartal",)).evaluate(
        AlertContext(lift=_observation((_equipment_record(),)))
    )
    assert alert is not None
    assert alert.severity == "warning"
    assert "adımsız erişim yok" not in alert.message_tr


def test_lift_rule_is_critical_when_every_recorded_lift_is_listed() -> None:
    records = tuple(_equipment_record(code=f"TEST-ASN-{index}") for index in range(1, 6))
    alert = LiftOutageRule(stations=("Kartal",)).evaluate(AlertContext(lift=_observation(records)))
    assert alert is not None
    assert alert.severity == "critical"
    assert "İstasyonda kayıtlı 5 asansörün 5'i kullanılamıyor" in alert.message_tr


def test_unknown_lift_count_is_a_warning_with_the_code() -> None:
    station_rows = [
        station.model_copy(update={"lifts": None}) if station.name == "Kartal" else station for station in stations()
    ]
    alert = LiftOutageRule(stations=("Kartal",)).evaluate(
        AlertContext(lift=_observation((_equipment_record(),), station_rows=station_rows))
    )
    assert alert is not None
    assert alert.severity == "warning"
    assert "lift_count_unknown" in alert.uncertainty


def test_escalator_only_is_info() -> None:
    record_row = _equipment_record(group="Yürüyen Merdiven")
    observation = _observation((record_row,), groups_read=("Yürüyen Merdiven",))
    alert = LiftOutageRule(stations=("Kartal",), equipment=("escalator",)).evaluate(
        AlertContext(lift=observation)
    )
    assert alert is not None
    assert alert.severity == "info"


def test_line_filter_matches_every_station_on_the_line() -> None:
    records = (
        _equipment_record(code="KARTAL-ASN", station="Kartal"),
        _equipment_record(code="KOZYATAGI-ASN", station="Kozyatağı", station_id=None),
    )
    alert = LiftOutageRule(lines=("m4",)).evaluate(AlertContext(lift=_observation(records)))
    assert alert is not None
    assert "Kartal" in alert.message_tr
    assert "Kozyatağı" in alert.message_tr


def test_uncertainty_codes_pass_through_to_the_alert() -> None:
    alert = LiftOutageRule(stations=("Kartal",)).evaluate(
        AlertContext(lift=_observation((_equipment_record(),), uncertainty=("group_unavailable",)))
    )
    assert alert is not None
    assert alert.uncertainty == sorted({"group_unavailable", DATE_SEMANTICS_UNKNOWN, LOCATION_EMPTY})


def test_message_never_says_a_lift_works() -> None:
    alert = LiftOutageRule(stations=("Kartal",)).evaluate(
        AlertContext(lift=_observation((_equipment_record(),)))
    )
    assert alert is not None
    assert "çalışıyor" not in alert.message_tr.casefold()
    assert "works" not in alert.message_en.casefold()
    for text in (alert.message_tr, alert.message_en):
        assert "eta" not in text.casefold()
        assert "kanca" not in text.casefold()
        assert "—" not in text


def test_dedupe_key_follows_outage_ids_and_severity() -> None:
    records = tuple(_equipment_record(code=f"TEST-ASN-{index}") for index in range(1, 6))
    critical = _observation(records)
    warning_stations = [
        station.model_copy(update={"lifts": 6}) if station.name == "Kartal" else station for station in stations()
    ]
    warning = _observation(records, station_rows=warning_stations)
    rule = LiftOutageRule(stations=("Kartal",))
    critical_alert = rule.evaluate(AlertContext(lift=critical))
    repeated_alert = rule.evaluate(AlertContext(lift=critical))
    warning_alert = rule.evaluate(AlertContext(lift=warning))
    changed_alert = rule.evaluate(AlertContext(lift=_observation(records[:-1] + (_equipment_record(code="OTHER"),))))
    assert critical_alert is not None and repeated_alert is not None and warning_alert is not None
    assert changed_alert is not None
    assert critical_alert.dedupe_key == repeated_alert.dedupe_key
    assert warning_alert.severity == "warning"
    assert critical_alert.dedupe_key != warning_alert.dedupe_key
    assert critical_alert.dedupe_key != changed_alert.dedupe_key


def test_parse_rejects_a_rule_without_station_or_line() -> None:
    with pytest.raises(ValueError, match="en az bir istasyon ya da hat"):
        parse_subscription({"rules": [{"kind": "lift_outage"}]})


def test_parse_rejects_an_overlong_station_label() -> None:
    with pytest.raises(ValueError, match="en fazla 120 karakter"):
        parse_subscription({"rules": [{"kind": "lift_outage", "stations": ["K" * 121]}]})


async def test_build_context_reads_only_the_asked_groups(tmp_path) -> None:
    write_recordings(tmp_path, {"Asansör": [record()]}, summary=[])
    context = await build_context(offline_ctx(tmp_path), {"rules": [{"kind": "lift_outage", "stations": ["Kartal"]}]})
    assert context.lift is not None
    assert context.lift.groups_read == ("Asansör",)


async def test_no_recording_is_reported_as_unavailable_not_all_clear(tmp_path) -> None:
    write_recordings(tmp_path, {}, summary=None)  # the station list only, no equipment answer
    result = await check_alerts(offline_ctx(tmp_path), {"rules": [{"kind": "lift_outage", "stations": ["Kartal"]}]})
    assert result["alerts"] == []
    assert result["unavailable"]["metro_equipment"] == "Metro ekipman kaydı yok; asansör durumu doğrulanamadı."


async def test_the_recording_of_26_september_clears_kartal_and_warns_for_etiler() -> None:
    """The committed 2026-09-26 recording: no lift record at Kartal, one lift fault at Etiler (M6)."""
    kartal = await check_alerts(offline_ctx(FIXTURES_DIR), {"rules": [{"kind": "lift_outage", "stations": ["Kartal"]}]})
    assert kartal["alerts"] == [] and "metro_equipment" not in kartal["unavailable"]
    etiler = await check_alerts(offline_ctx(FIXTURES_DIR), {"rules": [{"kind": "lift_outage", "stations": ["Etiler"]}]})
    [alert] = etiler["alerts"]
    assert alert["severity"] == "warning"
    assert alert["message_tr"].startswith("Etiler (M6): asansör kullanılamıyor, İBB kaydındaki durum: Arıza.")
    assert "çalışıyor" not in alert["message_tr"]
    assert "summary_detail_mismatch" in alert["uncertainty"]


async def test_stale_live_data_is_said_out_loud(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_ctx = SourceContext.create(
        client=PoliteClient(transport=httpx.MockTransport(lambda request: pytest.fail("unexpected network request"))),
        cache=TTLCache(),
        settings=Settings(offline=False, fixtures_dir=tmp_path),
    )
    old_provenance = Provenance(
        source="metro_equipment",
        source_url=METRO_FAULTY_EQUIPMENT_DETAILS,
        reported_at=utcnow() - dt.timedelta(days=30),
    )
    snapshot = EquipmentSnapshot(records=[_equipment_record()], groups_read=["Asansör"])

    async def snapshot_rows(self, groups):
        assert tuple(groups) == ("Asansör",)
        return snapshot, old_provenance

    async def station_rows(self):
        return stations(), old_provenance

    monkeypatch.setattr("ibb_mcp.sources.metro_equipment.MetroEquipmentSource.snapshot", snapshot_rows)
    monkeypatch.setattr("ibb_mcp.sources.metro.MetroSource.stations", station_rows)
    observation = await _lift_observation(source_ctx, ("elevator",))
    alert = LiftOutageRule(stations=("Kartal",)).evaluate(AlertContext(lift=observation))
    assert observation.stale
    assert "stale_data" in observation.uncertainty
    assert alert is not None
    assert alert.message_tr.startswith("Son bilinen durum, doğrulanamadı: ")


def test_identical_record_lines_are_said_once_with_their_count() -> None:
    from ibb_mcp.alerts.lift import _collapse_repeats

    same = "Taksim (M2): asansör kullanılamıyor."
    lines = [same, same, "Şişli: yürüyen merdiven kullanılamıyor."]
    assert _collapse_repeats(lines, "İBB kaydında {n} ayrı kayıt") == [
        "Taksim (M2): asansör kullanılamıyor. (İBB kaydında 2 ayrı kayıt.)",
        "Şişli: yürüyen merdiven kullanılamıyor.",
    ]
