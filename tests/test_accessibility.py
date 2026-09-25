"""Step-free answers: the lift state of a station, the nearest alternative, the tool's payload,
NEXUS signal candidates and the mission file that reads them.

The stations are the recorded ``metro_stations.json``; the lift faults are records built here in
the verified field shape (see ``tests/test_metro_equipment.py``), with test values, not İBB data.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import tomllib
from typing import Any

import pytest
from conftest import REPO_ROOT
from test_metro_equipment import offline_ctx, record, stations, write_recordings

from ibb_mcp.accessibility import (
    EQUIPMENT_DATA_UNAVAILABLE,
    HUB_FAULT_THRESHOLD,
    LIFT_COUNT_UNKNOWN,
    NO_ALTERNATIVE,
    NO_LIFT_RECORDED,
    STALE_DATA,
    accessible_alternative,
    alternative_answer,
    card_status,
    check_needs,
    equipment_status,
    equipment_status_data,
    faults_by_platform,
    lift_state,
    resolve_platforms,
    signal_candidates,
    stale_signal,
    transfer_hubs,
)
from ibb_mcp.metro_graph import MetroGraph
from ibb_mcp.models import Provenance
from ibb_mcp.sources.metro import MetroSource
from ibb_mcp.sources.metro_equipment import (
    EQUIPMENT_STALE_AFTER_S,
    NO_RECORDED_DATA,
    EquipmentRecord,
    EquipmentSnapshot,
    MetroEquipmentSource,
)
from nexus_core.missions import load_mission
from nexus_core.reflex import matches, render, signal_values
from nexus_core.signals import Origin, Signal

MISSION = REPO_ROOT / "missions" / "erisilebilir_yolculuk.toml"
NOW = dt.datetime(2026, 9, 25, 12, 0, tzinfo=dt.UTC)
STATIONS = stations()
GRAPH = MetroGraph.from_stations(STATIONS)


def snapshot(*rows: dict[str, Any], groups: tuple[str, ...] = ("Asansör",)) -> EquipmentSnapshot:
    return EquipmentSnapshot(records=[EquipmentRecord.from_raw(r) for r in rows], groups_read=list(groups))


def texts(value: Any) -> list[str]:
    """Every string inside a payload, for wording checks."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [t for v in value.values() for t in texts(v)]
    if isinstance(value, list | tuple):
        return [t for v in value for t in texts(v)]
    return []


def provenance(age_s: float = 0.0, cached: bool = False) -> Provenance:
    return Provenance(source="metro_equipment", source_url="x", observed_at=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=age_s),
                      cached=cached)


# -- needs ----------------------------------------------------------------------------
def test_only_step_free_is_understood_and_nothing_personal_is_asked() -> None:
    assert check_needs(None) == ("step_free",) == check_needs([]) == check_needs(["step_free", "step_free"])
    with pytest.raises(ValueError, match="Desteklenmeyen"):
        check_needs(["wheelchair_user"])


# -- the station's lifts --------------------------------------------------------------
def test_an_interchange_resolves_to_all_its_platforms() -> None:
    assert sorted(p.line_name for p in resolve_platforms("yenikapi", STATIONS)) == ["M1A", "M1B", "M2"]
    assert resolve_platforms("Yokistasyon", STATIONS) == []


def test_a_listed_lift_makes_the_station_out_of_service() -> None:
    platforms = resolve_platforms("Kartal", STATIONS)
    state = lift_state("Kartal", platforms, faults_by_platform(snapshot(record()).records, STATIONS))
    assert (state.lift_status, state.lift_count, state.unavailable_lift_count) == ("out_of_service", 5, 1)


def test_an_escalator_fault_does_not_take_the_lifts_out() -> None:
    faults = faults_by_platform(snapshot(record(group="Yürüyen Merdiven")).records, STATIONS)
    assert lift_state("Kartal", resolve_platforms("Kartal", STATIONS), faults).lift_status == "working"


def test_no_lift_and_no_lift_data_are_unknown_never_working() -> None:
    no_lift = lift_state("Moda", resolve_platforms("Moda", STATIONS), {})
    assert (no_lift.lift_status, no_lift.codes) == ("unknown", (NO_LIFT_RECORDED,))
    unknown = lift_state("X", [STATIONS[0].model_copy(update={"lifts": None})], {})
    assert (unknown.lift_status, unknown.codes) == ("unknown", (LIFT_COUNT_UNKNOWN,))


# -- the alternative ------------------------------------------------------------------
def test_kartal_lift_out_suggests_a_neighbour_with_a_ride_estimate() -> None:
    answer = accessible_alternative("Kartal", stations=STATIONS, snapshot=snapshot(record()), graph=GRAPH)
    assert answer["lift_status"] == "out_of_service"
    alternative = answer["alternative"]
    assert alternative["station"] in {"Soğanlık", "Yakacık-Adnan Kahveci"} and alternative["line"] == "M4"
    assert isinstance(alternative["extra_minutes"], int) and 1 <= alternative["extra_minutes"] <= 10
    assert "tahmin" in alternative["reason"] and "operatör onayı" in alternative["reason"]


def test_the_alternative_is_never_a_station_listed_in_the_same_snapshot() -> None:
    answer = accessible_alternative("Kartal", stations=STATIONS, snapshot=snapshot(record()), graph=GRAPH)
    first = answer["alternative"]["station"]
    blocked = record(station=first, station_id=None, code="TEST-ASN-02")
    second = accessible_alternative("Kartal", stations=STATIONS, snapshot=snapshot(record(), blocked), graph=GRAPH)
    assert second["alternative"]["station"] not in {first, "Kartal"}


def test_a_rider_stuck_on_a_platform_is_not_sent_through_an_in_station_transfer() -> None:
    """Yenikapı M2's lift out: the next step-free stop is on M2, not Aksaray via the M1A platform."""
    answer = accessible_alternative("Yenikapı", stations=STATIONS, snapshot=snapshot(record(station="Yenikapı", line="M2",
                                    station_id=20)), graph=GRAPH)
    assert answer["lift_status"] == "out_of_service" and answer["alternative"]["line"] == "M2"
    faults = signal_candidates(snapshot(record(station="Yenikapı", line="M2", station_id=20)), STATIONS, now=NOW, graph=GRAPH)
    assert faults[0]["payload"]["alternative_line"] == "M2"


def test_no_alternative_is_said_as_a_code() -> None:
    every_lift = [record(station=s.name or "", line=s.line_name or "", station_id=s.station_id, code=f"T{i}")
                  for i, s in enumerate(STATIONS) if s.lifts]
    answer = accessible_alternative("Kartal", stations=STATIONS, snapshot=snapshot(*every_lift), graph=GRAPH)
    assert answer["alternative"] is None and NO_ALTERNATIVE in answer["uncertainty"]


def test_a_station_with_no_listed_fault_needs_no_alternative_and_is_not_called_working() -> None:
    answer = accessible_alternative("Kartal", stations=STATIONS, snapshot=snapshot(), graph=GRAPH)
    assert answer["lift_status"] == "working" and answer["alternative"] is None
    assert answer["text"] == "İBB kaydında Kartal istasyonu için asansör arızası yok."


def test_without_the_lift_list_nothing_is_claimed() -> None:
    for snap in (None, EquipmentSnapshot(), snapshot(groups=("Yürüyen Merdiven",))):
        answer = accessible_alternative("Kartal", stations=STATIONS, snapshot=snap, graph=GRAPH)
        assert answer["lift_status"] == "unknown" and answer["alternative"] is None
        assert answer["uncertainty"] == [EQUIPMENT_DATA_UNAVAILABLE]


def test_an_unknown_station_is_a_clear_refusal() -> None:
    with pytest.raises(ValueError, match="bulamadım"):
        accessible_alternative("Yokistasyon", stations=STATIONS, snapshot=snapshot(), graph=GRAPH)


@pytest.mark.parametrize("rows", [(), (record(),), (record(kind="Revizyon"), record(group="Yürüyen Bant"))])
def test_never_says_working(rows: tuple[dict[str, Any], ...]) -> None:
    """No answer, card text or reason says a lift works: the most is "İBB kaydında arıza yok"."""
    snap = snapshot(*rows, groups=("Asansör", "Yürüyen Bant"))
    payloads = [
        accessible_alternative("Kartal", stations=STATIONS, snapshot=snap, graph=GRAPH),
        equipment_status_data(snap, provenance(), STATIONS, station="Kartal"),
        signal_candidates(snap, STATIONS, now=NOW, graph=GRAPH),
    ]
    for text in texts(payloads):
        assert "çalışıyor" not in text.casefold(), text


# -- the tool's payload ---------------------------------------------------------------
def test_status_payload_filters_by_station_line_and_counts_stations_by_name() -> None:
    snap = snapshot(record(), record(station="Taksim", line="M2", station_id=24, code="B"),
                    record(station="Yenikapı", line="M2", station_id=20, code="C"),
                    record(station="Yenikapı", line="M1A", station_id=121, code="D"))
    everything = equipment_status_data(snap, provenance(), STATIONS)
    assert everything["count"] == 4 and everything["affected_stations"] == 3  # Yenikapı once, not per line
    assert equipment_status_data(snap, provenance(), STATIONS, line="M2")["count"] == 2  # Taksim, Yenikapı M2
    at_yenikapi = equipment_status_data(snap, provenance(), STATIONS, station="Yenikapı")
    assert at_yenikapi["count"] == 2 and at_yenikapi["station"]["lift_status"] == "out_of_service"
    assert at_yenikapi["records"][0]["ibb_date"] == "2026-09-20T05:00:00+00:00"


def test_card_status_follows_the_contract() -> None:
    assert card_status(EquipmentSnapshot(), [], stale=False) == "unverified"
    assert card_status(snapshot(), [], stale=True) == "stale"
    assert card_status(snapshot(record()), [EquipmentRecord.from_raw(record())], stale=False) == "warning"
    assert card_status(snapshot(), [], stale=False) == "ok"


def test_live_data_past_its_age_is_stale_and_a_recording_never_is() -> None:
    old = provenance(age_s=EQUIPMENT_STALE_AFTER_S + 60)
    assert equipment_status_data(snapshot(), old, STATIONS)["stale"] is True
    assert STALE_DATA in equipment_status_data(snapshot(), old, STATIONS)["uncertainty"]
    assert equipment_status_data(snapshot(), provenance(cached=True), STATIONS)["stale"] is True
    recorded = equipment_status_data(snapshot(), old, STATIONS, offline=True)
    assert recorded["stale"] is False and recorded["mode"] == "recorded"


async def test_the_facade_helpers_read_recordings_end_to_end(tmp_path: pathlib.Path) -> None:
    write_recordings(tmp_path, {"Asansör": [record()], "Yürüyen Merdiven": [record(group="Yürüyen Merdiven", code="E")]},
                     [{"Name": "Asansör", "Inactive": 1}])
    ctx = offline_ctx(tmp_path)
    equipment, metro = MetroEquipmentSource(ctx), MetroSource(ctx)
    status = await equipment_status(equipment, metro, station="kartal", group="asansor")
    assert status.data["count"] == 1 and status.data["filters"]["group"] == "Asansör"
    assert status.data["mode"] == "recorded" and status.provenance.source == "metro_equipment"
    alternative = await alternative_answer(equipment, metro, station="Kartal", needs=["step_free"])
    assert alternative.data["alternative"] is not None and alternative.note


async def test_the_facade_without_recordings_says_unverified(tmp_path: pathlib.Path) -> None:
    write_recordings(tmp_path, {}, None)
    ctx = offline_ctx(tmp_path)
    status = await equipment_status(MetroEquipmentSource(ctx), MetroSource(ctx), station="Kartal")
    assert status.data["card_status"] == "unverified" and status.data["uncertainty"] == [NO_RECORDED_DATA]
    assert status.data["station"]["lift_status"] == "unknown" and "doğrulanamadı" in status.note


# -- signals and the mission file ------------------------------------------------------
def test_interchanges_follow_the_graphs_walking_rule() -> None:
    hubs = transfer_hubs(STATIONS)
    assert hubs[("yenikapi", "M2")] == hubs[("yenikapi", "M1A")]
    assert ("bahariye", "T3") not in hubs or hubs[("bahariye", "T3")] != hubs.get(("bahariye", "M9"))


def test_signal_candidates_cover_fault_long_outage_and_hub() -> None:
    snap = snapshot(record(date="2026-09-20T08:00:00"),
                    record(station="Yenikapı", line="M2", station_id=20, code="C", date=None),
                    record(station="Yenikapı", line="M1A", station_id=121, code="D", date=None))
    found = signal_candidates(snap, STATIONS, now=NOW, graph=GRAPH)
    kinds = [s["kind"] for s in found]
    assert kinds.count("equipment_fault") == 3 and kinds.count("long_outage") == 1 and kinds.count("hub_faults") == 1
    kartal = next(s for s in found if s["kind"] == "equipment_fault" and s["payload"]["station"] == "Kartal")
    # İstanbul 20.09 08:00 is 05:00 UTC; to 25.09 12:00 UTC is 5 days and 7 hours.
    assert kartal["payload"]["alternative_station"] and kartal["payload"]["outage_hours"] == 127.0
    assert kartal["payload"]["date_semantics_unknown"] is True and kartal["payload"]["outage_hours_basis"] == "ibb_date"
    hub = next(s for s in found if s["kind"] == "hub_faults")
    assert hub["payload"]["fault_count"] >= HUB_FAULT_THRESHOLD and hub["payload"]["hub"] == "Yenikapı"


def test_stale_signal_only_for_old_live_data() -> None:
    assert stale_signal(snapshot(), provenance(), offline=False) is None
    assert stale_signal(snapshot(), provenance(age_s=EQUIPMENT_STALE_AFTER_S + 1), offline=True) is None
    signal = stale_signal(snapshot(record()), provenance(age_s=EQUIPMENT_STALE_AFTER_S + 60), offline=False)
    assert signal["kind"] == "source_stale" and signal["payload"]["last_known_text"] == "İBB kaydında 1 asansör kullanılamıyor."


def _mission() -> dict[str, Any]:
    return tomllib.loads(MISSION.read_text(encoding="utf-8"))


def test_the_mission_has_the_six_rules_in_the_nexus_shape() -> None:
    mission = _mission()
    assert set(mission) == {"mission", "escalation", "rules"}
    assert [(r["id"], r["path"], r["when"]["kind"]) for r in mission["rules"]] == [
        ("R-01", "arena", "equipment_fault"),
        ("R-02", "arena", "equipment_fault"),
        ("R-03", "reflex", "equipment_fault"),
        ("R-04", "reflex", "source_stale"),
        ("R-05", "arena", "hub_faults"),
        ("R-06", "arena", "long_outage"),
    ]
    for rule in mission["rules"]:
        assert set(rule) <= {"id", "path", "when", "then", "expires_days", "valid_from"}
        assert set(rule["then"]) <= {"action", "card_template", "title", "card_kind"}


def _nexus_signals() -> list[Any]:
    """Every kind of signal accessibility builds, wrapped the way the console wraps them."""
    snap = snapshot(record(date="2026-09-20T08:00:00"),
                    record(station="Yenikapı", line="M2", station_id=20, code="C"),
                    record(station="Yenikapı", line="M1A", station_id=121, code="D"),
                    record(station="Kadıköy", line="M4", station_id=1, code="E", group="Yürüyen Merdiven"),
                    record(station="Kayıtsız Durak", line="M99", station_id=None, line_id=None, code="F"))
    found = signal_candidates(snap, STATIONS, now=NOW, graph=GRAPH)
    found.append(stale_signal(snap, provenance(age_s=EQUIPMENT_STALE_AFTER_S + 60), offline=False))
    origin = Origin(source="Metro İstanbul", url="x", observed_at=NOW, mode="recorded")
    return [Signal.create(kind=f["kind"], entity_id=f["entity_id"], severity=f["severity"], observed_at=NOW,
                          provenance=origin, payload=f["payload"]) for f in found]


def test_every_rule_fires_on_and_fills_from_the_signals_accessibility_builds() -> None:
    """A rule naming a field no signal carries would never fire, or would fail at run time."""
    signals = _nexus_signals()
    for rule in load_mission(MISSION).rules:
        fired = [s for s in signals if matches(rule.when, s)]
        assert fired, f"{rule.id}: no signal accessibility builds matches it"
        for signal in fired:
            values = signal_values(signal)
            body = render(rule.then.card_template, values)
            title = render(rule.then.title, values) if rule.then.title else ""
            assert "çalışıyor" not in (body + title).casefold()


def test_the_alternative_carries_what_the_approved_binding_checks() -> None:
    """nexus_core re-checks an approved alternative against the next snapshot: the field is explicit."""
    kartal = next(s for s in _nexus_signals() if s.kind == "equipment_fault" and s.payload["station"] == "Kartal")
    assert kartal.payload["alternative_faulty"] is False and kartal.payload["down_days"] == 5


def test_the_mission_loads_with_nexus_core() -> None:
    loaded = load_mission(MISSION)
    assert [rule.id for rule in loaded.rules] == ["R-01", "R-02", "R-03", "R-04", "R-05", "R-06"]
