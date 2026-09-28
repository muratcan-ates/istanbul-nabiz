"""E66: the processing path is separate from the publication outcome."""

from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest
from conftest import REPO_ROOT
from nexus_helpers import Clock

from nabiz.console.report_timeline import (
    CITIZEN_MOVES,
    OPERATOR_MOVES,
    STAGES,
    TimelineStore,
    load_agencies,
    next_stage,
    timeline_path,
    timeline_view,
)


def make_store(tmp_path: pathlib.Path, clock: Clock) -> TimelineStore:
    return TimelineStore(tmp_path / "timeline.db", clock=clock)


def start(store: TimelineStore, clock: Clock) -> dict:
    return store.ensure("K7M2QX9P", "signal-hidden", "Kartal", "not_working", clock())


def to_resolution(store: TimelineStore, clock: Clock) -> dict:
    start(store, clock)
    store.apply("K7M2QX9P", "operator", "reviewing")
    return store.apply("K7M2QX9P", "operator", "resolution_reported", text="Bakım tamamlandı.")


def test_next_stage_accepts_only_the_declared_moves() -> None:
    operators = {stage: set(moves) for stage, moves in OPERATOR_MOVES.items()}
    citizens = CITIZEN_MOVES
    stages = (*STAGES, "reopened")
    for current in stages:
        for target in stages:
            expected = target in operators.get(current, set())
            assert (next_stage(current, "operator", target) == target) is expected
        for action in ("fixed", "ongoing", "info", *stages):
            expected = citizens.get(current, {}).get(action)
            assert next_stage(current, "citizen", action) == expected
    assert next_stage("resolution_reported", "operator", "confirmed") is None
    assert next_stage("reviewing", "operator", "reopened") is None
    assert next_stage("confirmed", "operator", "reviewing") is None
    assert next_stage("recorded", "model", "reviewing") is None


def test_ongoing_reopens_once_and_operator_can_resume_review(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    store = make_store(tmp_path, clock)
    to_resolution(store, clock)
    reopened = store.apply("K7M2QX9P", "citizen", "ongoing", text="Asansör hâlâ kapalı.")
    assert reopened["stage"] == "reopened" and reopened["reopen_count"] == 1
    reviewed = store.apply("K7M2QX9P", "operator", "reviewing")
    assert reviewed["stage"] == "reviewing" and reviewed["reopen_count"] == 1


def test_personal_text_is_masked_before_sqlite_storage(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    store = make_store(tmp_path, clock)
    start(store, clock)
    store.apply("K7M2QX9P", "operator", "reviewing")
    private = "TC 10000000146, telefon 0555 123 45 67, e-posta person@example.com"
    store.apply("K7M2QX9P", "operator", "resolution_reported", text=private)
    content = store.path.read_bytes()
    for secret in ("10000000146", "0555 123 45 67", "person@example.com"):
        assert secret.encode() not in content
    row = store.get("K7M2QX9P")
    assert row["data"]["history"][-1]["masked_count"] >= 3
    assert "[TC KİMLİK]" in row["data"]["history"][-1]["note_masked"]


def test_ttl_path_and_purge_use_the_scratch_ledger(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    store = make_store(tmp_path, clock)
    start(store, clock)
    env = {"NEXUS_DB_PATH": str(tmp_path / "scratch" / "nexus.db")}
    assert timeline_path(env) == tmp_path / "scratch" / "report_timeline.db"
    clock.advance(days=29)
    store.apply("K7M2QX9P", "operator", "reviewing")
    assert dt.datetime.fromisoformat(store.get("K7M2QX9P")["expires_at"]) == clock() + dt.timedelta(days=30)
    clock.advance(days=30, seconds=1)
    assert store.purge() == 1
    assert store.get("K7M2QX9P") is None


def test_virtual_view_does_not_create_a_row(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    store = make_store(tmp_path, clock)
    virtual = store.virtual_view("K7M2QX9P", "hidden", "Kartal", "not_working", clock())
    assert virtual["stage"] == "recorded"
    assert virtual["data"]["history"][0]["stage"] == "recorded"
    with store._connect() as conn:
        assert conn.execute("SELECT count(*) FROM report_timeline").fetchone()[0] == 0


def test_confirmation_waits_seven_days_and_never_implies_resolution(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    store = make_store(tmp_path, clock)
    row = to_resolution(store, clock)
    agencies = load_agencies()
    clock.advance(days=6, hours=23)
    assert timeline_view(store.get(row["code"]), "approved", clock(), agencies)["confirmation"] == "awaiting"
    clock.advance(hours=1)
    view = timeline_view(store.get(row["code"]), "approved", clock(), agencies)
    assert view["confirmation"] == "none_7_days"
    assert view["stage"] == "resolution_reported"
    confirmed = store.apply("K7M2QX9P", "citizen", "fixed")
    assert timeline_view(confirmed, "approved", clock(), agencies)["confirmation"] == "confirmed"


def test_referral_uses_only_the_agency_catalogue(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    store = make_store(tmp_path, clock)
    start(store, clock)
    store.apply("K7M2QX9P", "operator", "reviewing")
    with pytest.raises(ValueError, match="agency_required"):
        store.apply("K7M2QX9P", "operator", "referred", agency_id="invented")
    row = store.apply("K7M2QX9P", "operator", "referred", agency_id="metro")
    view = timeline_view(row, "waiting", clock(), load_agencies())
    source = json.loads((REPO_ROOT / "data" / "agencies.json").read_text(encoding="utf-8"))
    agency = next(item for item in source["agencies"] if item["id"] == "metro")
    assert view["agency"]["name"] == agency["name"]
    assert view["agency"]["url"] == agency["url"]


def test_a_photo_step_shows_in_history_without_moving_the_stage(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    store = make_store(tmp_path, clock)
    row = start(store, clock)
    row["data"]["history"].append({"by": "citizen", "step": "photo_added", "photo_ref": "photo:0123456789ab",
                                   "at": clock().isoformat()})
    row["data"]["photo_refs"] = ["photo:0123456789ab"]
    view = timeline_view(row, "waiting", clock(), load_agencies())
    assert view["stage"] == "recorded" and view["has_photo"] is True and view["photo_refs"] == ["photo:0123456789ab"]
    assert [step["stage"] for step in view["steps"] if step["reached"]] == ["recorded"]
    assert view["history"][-1]["step"] == "photo_added"


def test_a_failed_seal_rolls_the_step_back(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    store = make_store(tmp_path, clock)
    start(store, clock)

    def broken(before: str, row: dict) -> int:
        assert before == "recorded" and row["stage"] == "reviewing"
        raise OSError("ledger unavailable")

    with pytest.raises(OSError):
        store.apply("K7M2QX9P", "operator", "reviewing", seal=broken)
    assert store.get("K7M2QX9P")["stage"] == "recorded"
    sealed = store.apply("K7M2QX9P", "operator", "reviewing", seal=lambda before, row: 7)
    assert sealed["stage"] == "reviewing" and sealed["ledger_entry_id"] == 7
