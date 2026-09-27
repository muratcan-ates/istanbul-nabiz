"""Unit checks for scenario validation, temporary closure rows and privacy suppression."""

from __future__ import annotations

from ibb_mcp.models import MetroStation
from ibb_mcp.sources.metro_equipment import EquipmentSnapshot, match_station
from nabiz.console.scenario import (
    EFFECTS,
    classify,
    closure_info,
    closure_records,
    route_from,
    summarize,
    suppress,
)


def test_route_input_rejects_coordinates_personal_data_duplicates_and_unknown_needs() -> None:
    email = "murat" + chr(64) + "example.test"
    for value in ("41.01,29.02 > Kadıköy", f"Kadıköy > {email}", "Kadıköy > Kadıköy"):
        try:
            route_from(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected invalid route: {value}")
    try:
        route_from({"from": "Kadıköy", "to": "Levent", "needs": ["person" + chr(64) + "example.test"]})
    except ValueError as exc:
        assert "step_free" in str(exc) and "slow_walk" in str(exc)
        assert ("person" + chr(64) + "example.test") not in str(exc)
    else:
        raise AssertionError("unknown need was accepted")
    assert route_from("  Kadıköy   >   Levent ") == {"from": "Kadıköy", "to": "Levent", "needs": ["step_free"]}


def test_closure_rows_follow_selected_platforms_and_match_the_station_list() -> None:
    stations = [
        MetroStation(station_id=100, name="Zeytinburnu", line_name="M1A", lifts=5),
        MetroStation(station_id=101, name="Zeytinburnu", line_name="T1", lifts=0),
    ]
    all_lines = closure_records(stations, "Zeytinburnu", None)
    selected = closure_records(stations, "Zeytinburnu", "M1A")
    assert len(all_lines) == 2 and len(selected) == 1
    assert selected[0].station_id == 100 and selected[0].line_name == "M1A"
    assert selected[0].code == "nabiz-scenario" and selected[0].status_class == "fault"
    assert match_station(selected[0], stations) == stations[0]
    snapshot = EquipmentSnapshot.model_construct(records=[selected[0]], groups_read=["Asansör"])
    info = closure_info(stations, "Zeytinburnu", "M1A", snapshot)
    assert info["already_faulty"] is True
    assert info["no_lift_record"] is False
    assert info["lift_count"] == 5


def test_classify_keeps_all_five_states_separate() -> None:
    # _finish_route sets available, alternatives_used and extra_minutes from the real planner path.
    assert classify({"available": True}, {"available": False, "reason": "no path"}, "Sirkeci")["effect"] == "blocked"
    # accessible_alternative and _route_via_alternative only report a checked station that was avoided.
    detour = classify(
        {"available": True, "extra_minutes": 2},
        {
            "available": True,
            "extra_minutes": 6,
            "alternatives_used": [{"station": "Yenikapı", "line": "M1", "avoided_station": "Sirkeci", "reason": "checked"}],
        },
        "Sirkeci",
    )
    assert detour["effect"] == "detour" and detour["added_minutes"] == 4
    # _finish_route's unchanged route contains no alternative for the closed station.
    assert classify({"available": True}, {"available": True, "alternatives_used": []}, "Sirkeci")["effect"] == "not_affected"
    # A verifiable route that already has no accessible path is not counted as a scenario effect.
    unavailable = classify({"available": False, "reason": "no step-free route"}, {"available": False}, "Sirkeci")
    assert unavailable["effect"] == "already_unavailable"
    # _PATH_REASONS_TR and _read_sources failures mean unknown, never not_affected.
    unverified = classify(
        {"available": False, "reason": "Başlangıç yeri metro istasyonlarıyla eşleşmedi."},
        {"available": False},
        "Sirkeci",
    )
    assert unverified["effect"] == "unverified"


def test_saved_counts_suppress_small_cells_and_subtotals() -> None:
    assert [suppress(n) for n in (0, 2, 3)] == [0, "lt3", 3]
    rows = [{"effect": "blocked"}, {"effect": "not_affected"}]
    summary = summarize(rows, {"status": "ok", "considered": 2, "effects": {"blocked": 1}})
    assert summary["counts"]["affected"] == 1
    assert summary["saved"]["considered"] == "lt3"
    assert set(summary["saved"]["effects"].values()) == {"lt3"}
    visible = summarize([], {"status": "ok", "considered": 3, "effects": {"blocked": 3}})["saved"]
    assert visible["considered"] == 3 and visible["effects"]["blocked"] == 3
    assert tuple(name for name in EFFECTS if name not in summary["counts"]) == ()
