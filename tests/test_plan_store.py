from concurrent.futures import ThreadPoolExecutor

import pytest

from nabiz.console.operation_ledger import OperationConflict
from nabiz.console.plan_store import PlanNotFound, PlanStore


def fields(**changes):
    return {
        "title": "Sergi", "starts_at": "2026-10-03", "ends_at": "2026-10-04", "all_day": True,
        "time_zone": "Europe/Istanbul", "place": "Kadıköy", "source_url": "https://example.org/event",
        "source_date": "2026-09-27", "conversation_id": "chat-1", **changes,
    }


def test_save_replay_persists_and_updates_same_plan(tmp_path):
    path = tmp_path / "plans.sqlite3"
    store = PlanStore(path)
    first = store.save("person-1", "op-save", fields())
    assert store.save("person-1", "op-save", fields())["id"] == first["id"]
    assert PlanStore(path).list("person-1") == [first]
    assert first["all_day"] is True
    assert first["time_zone"] == "Europe/Istanbul"
    moved = store.update("person-1", first["id"], "op-saturday", fields(starts_at="2026-10-10", ends_at="2026-10-11"))
    assert moved["id"] == first["id"]
    assert moved["starts_at"] == "2026-10-10"
    assert len(store.list("person-1")) == 1
    assert store.save("person-1", "op-save", fields()) == first
    assert store.update(
        "person-1", first["id"], "op-saturday", fields(starts_at="2026-10-10", ends_at="2026-10-11")
    ) == moved
    with pytest.raises(PlanNotFound):
        store.get("person-2", first["id"])
    with pytest.raises(OperationConflict):
        store.save("person-1", "op-save", fields(title="Başka"))


def test_concurrent_same_operation_creates_one_row(tmp_path):
    store = PlanStore(tmp_path / "plans.sqlite3")
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: store.save("person", "op-once", fields())["id"], range(2)))
    assert ids[0] == ids[1]
    assert len(store.list("person")) == 1


def test_rejects_invalid_time_and_source(tmp_path):
    store = PlanStore(tmp_path / "plans.sqlite3")
    with pytest.raises(ValueError):
        store.save("person", "op", fields(ends_at="2026-10-03"))
    with pytest.raises(ValueError):
        store.save("person", "op", fields(source_url="http://example.org"))
    with pytest.raises(ValueError):
        store.save("person", "op", fields(time_zone="UTC"))


def test_outlook_confirmation_cannot_be_overwritten(tmp_path):
    store = PlanStore(tmp_path / "plans.sqlite3")
    plan = store.save("person", "save-op", fields())
    store.outlook_operation("person", plan["id"], "graph-op")
    store.set_outlook_result("person", "graph-op", "added", {"result": "outlook_added", "event_id": "event"})
    store.set_outlook_result("person", "graph-op", "failed", {"result": "outlook_failed"})
    assert store.outlook_operation("person", plan["id"], "graph-op").result["result"] == "outlook_added"
