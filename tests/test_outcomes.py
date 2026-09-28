from __future__ import annotations

import datetime as dt
import json
import pathlib
import sqlite3

import pytest
from nexus_helpers import Clock, approve, build_engine, elevator

from nabiz.console.citizen_requests import ledger_reply, ledger_request
from nabiz.console.outcomes import (
    PATH_ENV,
    TTL_DAYS,
    OutcomeMetricSpec,
    SnapshotStore,
    TooSoon,
    board,
    card_metrics,
    fidelity_metrics,
    metric,
    percentile,
    read_fidelity,
    read_timeline,
    request_metrics,
    timeline_metrics,
)
from nexus_core.ledger import Ledger
from nexus_core.lifecycle import expire_cards


def request_row(code: str) -> dict[str, object]:
    return {
        "code": code, "signal_id": f"signal-{code}", "original_masked": "masked fixture",
        "masked_count": 0, "lang": "tr", "category": "test", "translation_status": "not_needed",
    }


def test_metric_threshold_and_zero_denominator() -> None:
    spec = OutcomeMetricSpec("X", "ratio", "test")
    low = metric("x", spec, 2, 9)
    enough = metric("x", spec, 5, 10)
    zero = metric("x", spec, 0, 0)
    assert (low["status"], low["value"], low["numerator"], low["denominator"]) == ("insufficient", None, 2, 9)
    assert (enough["status"], enough["value"]) == ("measured", 50)
    assert (zero["status"], zero["value"], zero["reason"]) == ("insufficient", None, "En az 10 örnek gerekir, şu an 0.")


def test_percentile_uses_nearest_rank_and_empty_is_unknown() -> None:
    assert percentile(range(1, 11), 50) == 5
    assert percentile(range(1, 11), 90) == 9
    assert percentile([], 50) is None


def test_requests_count_the_first_reply_and_ignore_out_of_window_requests(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    ledger = Ledger(tmp_path / "requests.db", clock=clock)
    for number in range(12):
        row = request_row(f"REQ{number:05d}")
        ledger_request(ledger, row)
        if number < 9:
            clock.advance(seconds=10)
            reply = {"lang": "tr", "translation": "not_needed", "text_tr": "masked fixture"}
            ledger_reply(ledger, row, reply, "fixture-operator")
            if number == 0:
                clock.advance(seconds=10)
                ledger_reply(ledger, row, reply, "fixture-operator")
        clock.advance(seconds=10)
    now = clock.now
    old = request_row("OLD00001")
    clock.now = now - dt.timedelta(days=31)
    ledger_request(ledger, old)
    clock.now = now
    ledger_reply(ledger, old, {"lang": "tr", "translation": "not_needed", "text_tr": "masked"}, "fixture-operator")
    metrics, counts = request_metrics(ledger.entries(kinds=["citizen_request", "operator_reply"]), now, 30)
    assert [metrics[0]["numerator"], metrics[0]["denominator"]] == [9, 12]
    assert (metrics[0]["status"], metrics[0]["value"]) == ("measured", 75)
    assert metrics[1]["status"] == "insufficient"
    assert metrics[1]["numerator"] == metrics[2]["numerator"] == 10
    assert counts["waiting_count"] == 3
    assert counts["oldest_waiting_s"] == 30


def test_card_metrics_use_first_human_ruling_and_separate_expiry(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    approved_id = engine.process(elevator("APPROVED", observed_at=clock.now)).signal_id
    assert engine.states()[approved_id].path == "arena"
    clock.advance(seconds=30)
    engine.decide(approve(approved_id, "approve"))
    deferred_id = engine.process(elevator("DEFERRED", observed_at=clock.now)).signal_id
    clock.advance(seconds=30)
    engine.decide(approve(deferred_id, "defer", "need more evidence"))
    expired_id = engine.process(elevator("EXPIRED", observed_at=clock.now)).signal_id
    clock.advance(days=29)
    expire_cards(engine.ledger, engine.states().values(), engine.ttl_hours, clock.now)
    metrics, counts = card_metrics(engine.states().values(), clock.now, 30)
    assert metrics[0]["denominator"] == 3
    assert metrics[0]["numerator"] == 1
    assert counts["expired"] == 1
    assert counts["deferred_or_waiting"] == 1
    assert engine.states()[expired_id].status == "expired"


def test_timeline_metrics_distinguish_confirmation_reopen_and_no_reply() -> None:
    now = dt.datetime(2026, 9, 27, 12, tzinfo=dt.UTC)
    rows = [
        {"stage": "confirmed", "reopen_count": 0, "created_at": now.isoformat(),
         "history": [{"stage": "resolution_reported", "at": now.isoformat()}, {"stage": "confirmed", "at": now.isoformat()}]},
        {"stage": "reviewing", "reopen_count": 1, "created_at": now.isoformat(),
         "history": [{"stage": "resolution_reported", "at": now.isoformat()}, {"stage": "reopened", "at": now.isoformat()}]},
        {"stage": "resolution_reported", "reopen_count": 0, "created_at": now.isoformat(),
         "updated_at": (now - dt.timedelta(days=8)).isoformat(),
         "history": [{"stage": "resolution_reported", "at": (now - dt.timedelta(days=8)).isoformat()}]},
        {"stage": "recorded", "reopen_count": 0, "created_at": now.isoformat(), "history": []},
    ]
    metrics, counts = timeline_metrics(rows, now, 30)
    assert [(item["numerator"], item["denominator"], item["status"]) for item in metrics] == [
        (1, 3, "insufficient"), (1, 3, "insufficient")
    ]
    assert counts["no_reply_7_days"] == 1


def test_fidelity_metrics_read_named_rows_from_the_real_file() -> None:
    text = read_fidelity()
    assert text is not None
    metrics = {item["key"]: item for item in fidelity_metrics(text)}
    measure_rows = {}
    summary_rows = {}
    for line in text.splitlines():
        if "| Cevaplanan (answer/quote_only) ve altını olan |" in line:
            measure_rows["denominator"] = int(line.strip().strip("|").split("|")[-1])
        if "| … ilk kaynağı altın URL |" in line:
            measure_rows["numerator"] = int(line.strip().strip("|").split("|")[-1])
        if "| negatif |" in line:
            summary_rows["negative"] = int(line.strip().strip("|").split("|")[1])
    assert (metrics["o5_first_source"]["numerator"], metrics["o5_first_source"]["denominator"]) == (
        measure_rows["numerator"], measure_rows["denominator"]
    )
    assert metrics["o5_negative_answers"]["denominator"] == summary_rows["negative"]
    assert metrics["o5_first_source"]["note"].startswith("Altın dışı kaynak her zaman yanlış değildir.")


def test_fidelity_metrics_mark_missing_rows_without_guessing() -> None:
    metrics = fidelity_metrics("## Özet\n| Küme | n |\n|---|---:|\n| negatif | 4 |\n")
    assert all(item["status"] == "unmeasured" and item["value"] is None for item in metrics)
    assert all("satır yok" in item["reason"] for item in metrics)
    assert all(item["status"] == "unmeasured" for item in fidelity_metrics(None))


def test_board_without_core_keeps_offline_fidelity_source() -> None:
    data = board(entries=None, states=None, timeline_rows=None, fidelity_md=read_fidelity(),
                 now=dt.datetime(2026, 9, 27, tzinfo=dt.UTC), days=30)
    groups = {group["key"]: group for group in data["groups"]}
    assert all(item["status"] == "unmeasured" for group in groups["O1"]["metrics"] + groups["O2"]["metrics"] for item in [group])
    assert all(item["status"] == "unmeasured" for group in (groups["O3"], groups["O4"]) for item in group["metrics"])
    assert all(item["status"] == "measured" for item in groups["O5"]["metrics"])


def test_board_output_has_no_request_or_operator_identifiers(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    ledger = Ledger(tmp_path / "privacy.db", clock=clock)
    row = request_row("PRIVATE-CODE")
    ledger_request(ledger, row)
    data = board(entries=ledger.entries(), states=[], timeline_rows=[], fidelity_md=read_fidelity(), now=clock.now, days=30)
    serialized = json.dumps(data, ensure_ascii=False)
    for secret in ("PRIVATE-CODE", "signal-PRIVATE-CODE", "fixture-operator", "masked fixture", "code", "signal_id", "text"):
        assert secret not in serialized


def test_read_timeline_is_read_only_and_discards_identifiers_and_notes(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "report_timeline.db"
    expiry = "2030-01-01T00:00:00+00:00"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE report_timeline (code TEXT, signal_id TEXT, station TEXT, kind TEXT, stage TEXT, "
                     "reopen_count INTEGER, created_at TEXT, updated_at TEXT, expires_at TEXT, data TEXT)")
        conn.execute("INSERT INTO report_timeline VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     ("PRIVATE-CODE", "PRIVATE-SIGNAL", "station", "kind", "confirmed", 0, expiry, expiry, expiry,
                      json.dumps({"history": [{"stage": "confirmed", "at": expiry, "note": "PRIVATE NOTE"}]})))
        conn.execute("INSERT INTO report_timeline VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     ("bad", "bad", "station", "kind", "recorded", 0, expiry, expiry, expiry, "{"))
        conn.execute("INSERT INTO report_timeline VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     ("expired", "expired", "station", "kind", "recorded", 0, expiry, expiry,
                      "2020-01-01T00:00:00+00:00", "{"))
    before = (path.stat().st_mtime_ns, path.stat().st_size)
    rows = read_timeline(path)
    after = (path.stat().st_mtime_ns, path.stat().st_size)
    assert rows is not None and rows.skipped == 1 and len(rows) == 1
    assert rows[0]["history"] == [{"stage": "confirmed", "at": expiry}]
    assert not any(value in json.dumps(rows) for value in ("PRIVATE-CODE", "PRIVATE-SIGNAL", "PRIVATE NOTE"))
    assert before == after


def test_a_timeline_with_a_linked_photo_counts_as_one_report(tmp_path: pathlib.Path) -> None:
    from nabiz.console.photo_reports import NewPhotoReport, PhotoReportStore
    from nabiz.console.report_link import link_photo
    from nabiz.console.report_timeline import TimelineStore

    clock = Clock()
    timeline = TimelineStore(tmp_path / "report_timeline.db", clock=clock)
    timeline.ensure("ABCDEFGH", "sig-1", "Kartal", "not_working", clock())
    photos = PhotoReportStore(tmp_path / "photos.db")
    photo = photos.create(NewPhotoReport("lift", {"kind": "station", "name": "Kartal"}, "", 0, (), "tr", {}, b"x", "jpeg"))
    link_photo(photo["code"], "ABCDEFGH", "sig-1", photos_db=photos.path, timeline_db=timeline.path, now=clock())
    for step in ("reviewing", "resolution_reported"):
        timeline.apply("ABCDEFGH", "operator", step, to=step, text="Bakım tamamlandı.")
    timeline.apply("ABCDEFGH", "citizen", "fixed")
    rows = read_timeline(timeline.path, now=clock())
    assert rows is not None and len(rows) == 1 and rows[0]["has_photo"] is True
    assert all("stage" in item for item in rows[0]["history"])
    metrics, counts = timeline_metrics(rows, clock(), 30)
    assert (metrics[0]["numerator"], metrics[0]["denominator"]) == (1, 1)
    assert counts["reports"] == 1 and counts["with_photo"] == 1


def test_read_timeline_does_not_create_a_missing_file(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "missing.db"
    assert read_timeline(path) is None
    assert not path.exists()


def test_snapshot_store_cooldown_expiry_and_numeric_only_storage(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    store = SnapshotStore(tmp_path / "outcomes.db", clock=clock)
    data = board(entries=[], states=[], timeline_rows=None, fidelity_md=read_fidelity(), now=clock.now, days=30)
    saved = store.save(data)
    assert store.latest(30)["taken_at"] == saved["taken_at"]
    with pytest.raises(TooSoon):
        store.save(data)
    with sqlite3.connect(store.path) as conn:
        raw = conn.execute("SELECT data FROM outcome_snapshots").fetchone()[0]
    assert "PRIVATE" not in raw and "\"note\"" not in raw
    assert all(set(row) == {"key", "status", "numerator", "denominator", "value"} for row in json.loads(raw))
    clock.advance(minutes=5)
    store.save(data)
    clock.advance(days=TTL_DAYS, seconds=1)
    assert store.latest(30) is None


def test_snapshot_store_keeps_only_the_newest_500_rows(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    store = SnapshotStore(tmp_path / "bounded.db", clock=clock)
    data = board(entries=[], states=[], timeline_rows=None, fidelity_md=read_fidelity(), now=clock.now, days=30)
    old = (clock.now - dt.timedelta(minutes=5010)).isoformat()
    expires = (clock.now + dt.timedelta(days=TTL_DAYS)).isoformat()
    with sqlite3.connect(store.path) as conn:
        conn.executemany("INSERT INTO outcome_snapshots (taken_at, window_days, expires_at, data) VALUES (?, 30, ?, '[]')",
                         [(old, expires)] * 500)
    store.save(data)
    with sqlite3.connect(store.path) as conn:
        count, first_id = conn.execute("SELECT COUNT(*), MIN(id) FROM outcome_snapshots").fetchone()
    assert count == 500 and first_id == 2


def test_snapshot_path_uses_env_or_ledger_sibling(tmp_path: pathlib.Path) -> None:
    from nabiz.console.outcomes import snapshots_path

    assert snapshots_path({PATH_ENV: str(tmp_path / "custom.db")}) == tmp_path / "custom.db"
    assert snapshots_path({"NEXUS_DB_PATH": str(tmp_path / "nexus.db")}) == tmp_path / "outcomes.db"


def test_the_board_takes_its_stage_names_from_the_timeline() -> None:
    """P00 G2 (E75 note): the board reads E66's rows, so its stage names come from report_timeline, never a copy."""
    from nabiz.console import outcomes, report_timeline

    assert outcomes.STAGES is report_timeline.STAGES
    assert {"resolution_reported", "confirmed", "reopened"} == outcomes.RESOLUTION_REACHED
    assert set(report_timeline.WAITING_ON) >= outcomes.RESOLUTION_REACHED
