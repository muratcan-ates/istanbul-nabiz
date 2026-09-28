"""E67's stable station grouping and explainable priority rules."""

from __future__ import annotations

import datetime as dt

from nabiz.console.incident import (
    WAIT_HOURS,
    apply_actions,
    auto_incidents,
    build_incidents,
    effective_priority,
    equipment_members,
    photo_members,
    report_members,
    suggest_priority,
)
from nabiz.console.report_triage import SUPPORT_MANY, report_priority
from nexus_core.state import SignalState

NOW = dt.datetime(2026, 9, 25, 9, 0, tzinfo=dt.UTC)


def report(
    signal_id: str,
    station: str = "Sanayi Mahallesi",
    *,
    received: dt.datetime = NOW,
    support: int = 1,
    status: str = "awaiting_approval",
    kind: str = "not_working",
    lift_status: str | None = None,
    reasons: tuple[str, ...] = (),
) -> dict:
    return {
        "signal": {
            "signal_id": signal_id,
            "kind": "citizen_report",
            "entity_id": signal_id,
            "payload": {"station": station, "report_kind": kind, "lift_status": lift_status, "lift_text": "Arıza", "line": "M2"},
        },
        "received_at": received.isoformat(),
        "status": status,
        "reasons": reasons,
        "repeats": 1,
        "support": support,
    }


def report_member(
    signal_id: str,
    station: str = "Sanayi Mahallesi",
    *,
    support: int = 1,
    status: str = "awaiting_approval",
    level: str = "normal",
    received: str | None = None,
) -> dict:
    return {
        "ref": f"report:{signal_id}",
        "signal_id": signal_id,
        "station": station,
        "report_kind": "not_working",
        "kind_text": "asansör kapalıydı",
        "status": status,
        "received_at": received or NOW.isoformat(),
        "support": support,
        "lift_status": None,
        "lift_text": None,
        "codes": [],
        "priority": {"level": "medium" if support >= SUPPORT_MANY and level == "normal" else level},
        "window_hours": 168,
    }


def equipment_member(signal_id: str = "eq-1", station: str = "Sanayi Mahallesi", *, kind: str = "elevator") -> dict:
    return {
        "ref": f"equipment:{signal_id}",
        "signal_id": signal_id,
        "station": station,
        "equipment_type": kind,
        "status_class": "fault",
        "status_type": "Arıza",
        "observed_at": NOW.isoformat(),
        "line": "M2",
    }


def test_station_key_uses_the_report_map_turkish_fold() -> None:
    members = report_members(
        [report("s1", "İTÜ-Ayazağa"), report("s2", "itu ayazaga")],
        {"s1": 1, "s2": 1},
        NOW,
        168,
    )
    assert members[0]["station_key"] == members[1]["station_key"]


def test_member_collectors_and_auto_incident_gates() -> None:
    states = [
        report("s1"),
        report("s2", support=2),
        {
            "signal": {
                "signal_id": "eq-1",
                "kind": "equipment_fault",
                "entity_id": "e1",
                "payload": {
                    "station": "Sanayi Mahallesi",
                    "equipment_type": "elevator",
                    "status_class": "fault",
                    "status_type": "Arıza",
                    "line": "M2",
                },
                "provenance": {"observed_at": NOW.isoformat(), "source": "Metro İstanbul"},
            }
        },
    ]
    reports = report_members(states, {"s1": 1, "s2": 2}, NOW, 168)
    equipment = equipment_members(states)
    photos = photo_members(
        [
            {"code": "SYNTHETIC1", "place": {"kind": "station", "name": "Sanayi Mahallesi"}, "category": "lift"},
            {"code": "SYNTHETIC2", "place": {"kind": "district", "name": "Şişli"}, "category": "lift"},
        ]
    )
    grouped = auto_incidents(reports, photos, equipment)
    assert len(grouped) == 1
    assert len(grouped[0]["members"]["report"]) == 2
    assert len(grouped[0]["members"]["equipment"]) == 1
    assert len(grouped[0]["members"]["photo"]) == 1
    assert "SYNTHETIC1" not in photos[0]["ref"] and photos[0]["ref"].startswith("photo:")
    assert auto_incidents([], [], equipment) == []
    assert (
        len(
            auto_incidents(
                [],
                photo_members(
                    [
                        {"code": "DISTRICT1", "place": {"kind": "district", "name": "Şişli"}},
                    ]
                ),
                equipment,
            )
        )
        == 0
    )


def test_a_linked_photo_joins_its_report_even_at_another_place() -> None:
    reports = report_members([report("s1"), report("s2", "Üsküdar")], {}, NOW, 168)
    photos = photo_members([
        {"code": "SYNTHETIC3", "place": {"kind": "district", "name": "Şişli"}, "linked_signal_id": "s1",
         "linked_report_code": "ABCDEFGH"},
        {"code": "SYNTHETIC4", "place": {"kind": "station", "name": "Kartal"}, "linked_signal_id": "s2",
         "linked_report_code": "BCDEFGHJ"},
        {"code": "SYNTHETIC5", "place": {"kind": "station", "name": "Kartal"}},
        {"code": "SYNTHETIC6", "place": {"kind": "district", "name": "Şişli"}},
    ])
    by_code = {member["photo_code"]: member for member in photos}
    assert set(by_code) == {"SYNTHETIC3", "SYNTHETIC4", "SYNTHETIC5"}
    assert [by_code[code]["linked_ref"] for code in ("SYNTHETIC3", "SYNTHETIC4", "SYNTHETIC5")] == [
        "report:s1", "report:s2", None]
    grouped = {item["station_key"]: item for item in auto_incidents(reports, photos, [])}
    assert [m["report_code"] for m in grouped["sanayimahallesi"]["members"]["photo"]] == ["ABCDEFGH"]
    uskudar = next(item for key, item in grouped.items() if key != "sanayimahallesi" and item["members"]["report"])
    assert [m["linked_ref"] for m in uskudar["members"]["photo"]] == ["report:s2"]
    assert uskudar["stations"] == ["Kartal", "Üsküdar"] and len(grouped) == 3
    lone = auto_incidents([], [by_code["SYNTHETIC5"]], [])
    assert len(lone) == 1 and lone[0]["members"]["photo"][0]["linked_ref"] is None
    # A linked photo whose report left the window falls back to its own station, never a new identity.
    assert len(auto_incidents([], [by_code["SYNTHETIC3"]], [])) == 0


def test_report_priority_base_stays_consistent_with_its_decision_card() -> None:
    state = SignalState.model_validate(
        {
            "signal": {
                "signal_id": "s1",
                "kind": "citizen_report",
                "entity_id": "s1",
                "severity": "warning",
                "observed_at": NOW,
                "payload": {"report_kind": "not_working", "station": "A"},
                "provenance": {"source": "Vatandaş bildirimi", "observed_at": NOW},
            },
            "received_at": NOW,
            "status": "awaiting_approval",
            "reasons": [],
            "repeats": 1,
        }
    )
    direct = report_priority(state, 1, 168)
    member = report_members([report("s1")], {"s1": 1}, NOW, 168)[0]
    assert member["priority"] == direct


def test_verified_access_and_repeat_raise_only_by_the_single_rule() -> None:
    reports = [report_member("s1", support=2), report_member("s2", support=1)]
    incident = auto_incidents(reports, [], [equipment_member()])[0]
    suggestion = suggest_priority(incident, NOW)
    assert SUPPORT_MANY == 3
    assert suggestion["level"] == "high"
    assert suggestion["base_level"] == "normal"
    assert suggestion["raised_by"] == ["access", "repeat"]
    access = next(item for item in suggestion["factors"] if item["key"] == "access")
    assert access["verified"] is True and access["source"] == "ibb_record"
    assert next(item for item in suggestion["factors"] if item["key"] == "repeat")["values"]["people"] == 3


def test_citizen_reports_alone_never_verify_access_or_raise_the_level() -> None:
    reports = [report_member("s1", support=3)]
    incident = auto_incidents(reports, [], [])[0]
    suggestion = suggest_priority(incident, NOW)
    access = next(item for item in suggestion["factors"] if item["key"] == "access")
    assert suggestion["level"] == suggestion["base_level"] == "medium"
    assert access["verified"] is False and access["source"] == "citizen"


def test_report_time_ibb_snapshot_is_a_verified_access_source() -> None:
    # lift_status in a report payload is the IBB reading captured when the card arrived.
    reports = report_members(
        [report("s1", support=3, lift_status="out_of_service")],
        {"s1": 3},
        NOW,
        168,
    )
    incident = auto_incidents(reports, [], [])[0]
    suggestion = suggest_priority(incident, NOW)
    access = next(item for item in suggestion["factors"] if item["key"] == "access")
    assert access["verified"] is True and access["source"] == "ibb_record"
    assert access["observed_at"] == NOW.isoformat()
    assert access["values"]["status_type"] == "Arıza"
    assert suggestion["level"] == "high"


def test_conflict_is_a_check_request_and_does_not_lower_priority() -> None:
    member = report_member("s1", level="medium")
    member.update(report_kind="data_wrong", lift_status="out_of_service")
    suggestion = suggest_priority(auto_incidents([member], [], [])[0], NOW)
    conflict = next(item for item in suggestion["factors"] if item["key"] == "conflict")
    assert suggestion["level"] == suggestion["base_level"] == "medium"
    assert conflict["needs_check"] is True
    assert conflict["values"]["text"] == "İBB kaydında arıza var"


def test_waiting_at_the_design_threshold_is_reported_and_is_the_only_wait_upgrade() -> None:
    old = NOW - dt.timedelta(hours=WAIT_HOURS)
    reports = report_members([report("s1", received=old)], {"s1": 1}, NOW, 168)
    suggestion = suggest_priority(auto_incidents(reports, [], [equipment_member()])[0], NOW)
    waiting = next(item for item in suggestion["factors"] if item["key"] == "waiting")
    assert waiting["values"]["hours"] == WAIT_HOURS
    assert waiting["values"]["over"] is True
    assert suggestion["raised_by"] == ["access", "waiting"]


def test_split_merge_replay_and_stale_member_diagnostics() -> None:
    base = auto_incidents([report_member("s1"), report_member("s2"), report_member("s3", "Şişli")], [], [])
    first, second = base
    split = {
        "id": 5,
        "kind": "split",
        "incident_id": first["id"],
        "at": "2026-09-25T10:00:00+00:00",
        "data": {"ref": "report:s1", "station_key": first["station_key"]},
    }
    separated = apply_actions(base, [split])
    assert len(separated) == 3 and len(separated.skipped_actions) == 0
    restored = apply_actions(base, [{**split, "undone_at": "2026-09-25T10:01:00+00:00"}])
    assert restored == base
    merge = {
        "id": 6,
        "kind": "merge",
        "incident_id": first["id"],
        "at": "2026-09-25T10:00:00+00:00",
        "data": {"source": first["id"], "target": second["id"]},
    }
    joined = apply_actions(base, [merge])
    assert len(joined) == 1 and len(joined[0]["stations"]) == 2
    assert apply_actions(base, [{**merge, "undone_at": "2026-09-25T10:01:00+00:00"}]) == base
    skipped = apply_actions(base, [{**split, "data": {"ref": "report:expired"}}])
    assert skipped.skipped_actions == [5]


def test_override_keeps_the_suggestion_as_a_separate_value() -> None:
    suggestion = {"level": "high"}
    override = {"level": "medium", "reason": "Kayıtla yeniden karşılaştırıldı", "at": NOW.isoformat(), "actor": "simüle operatör"}
    assert effective_priority(suggestion, override) == {
        "level": "medium",
        "by": "operator",
        "suggested_level": "high",
        "reason": override["reason"],
        "at": NOW.isoformat(),
        "actor": override["actor"],
    }


def test_builder_sorts_effective_priority_then_oldest_open_report() -> None:
    reports = [report_member("s1", station="Kartal", level="normal"), report_member("s2", station="Üsküdar", level="high")]
    values = build_incidents(reports, [], [], [], {}, NOW)
    assert values[0]["title_station"] == "Üsküdar"
