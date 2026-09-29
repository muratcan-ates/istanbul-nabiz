"""Storage and safe text rules for the personal, consented work file."""

from __future__ import annotations

import copy
import datetime as dt
import json
import sqlite3

import pytest

import nabiz.console.case_file as case_file
from nabiz.console.accounts import AccountStore, token_hash
from nabiz.console.case_file import (
    PLAN_PATH,
    CaseConsentRequired,
    CaseFileError,
    CaseFileStore,
    clean_note,
    clean_ref,
    clean_remind,
    due_reminders,
    progress,
    water_route,
)


class Clock:
    def __init__(self) -> None:
        self.value = dt.datetime(2026, 9, 27, 9, tzinfo=dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.value


# a week ahead: the store accepts reminders from today on, so a fixed date ages out
REMIND_ON = (dt.date.today() + dt.timedelta(days=7)).isoformat()

def _count(path, table: str) -> int:
    with sqlite3.connect(path) as db:
        return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


@pytest.mark.parametrize(("choice", "index"), [("iptal", 0), ("yenileme", 1), ("yeni", 2), ("bilmiyorum", None)])
def test_water_route_selection_table(choice: str, index: int | None) -> None:
    result = water_route(choice)
    assert result["choice"] == choice
    assert result["source_index"] == index
    assert ("kaynakta açıkça anlatılmıyor" in result["message"]) is (index is None)


def test_water_route_rejects_unknown_choice() -> None:
    with pytest.raises(ValueError, match="Bilinmeyen"):
        water_route("devir")


@pytest.mark.parametrize("value", ["4111 1111 1111 1111", "10000000146", "0555 000 00 01", "destek@example.org"])
def test_notes_and_references_reject_pii(value: str) -> None:
    with pytest.raises(CaseFileError):
        clean_note(value)
    with pytest.raises(CaseFileError):
        clean_ref(value)


def test_note_reference_trimming_length_and_reference_alphabet() -> None:
    assert clean_note("  kısa\n  not ") == "kısa not"
    assert clean_ref("  AB-12 / C.  ") == "AB-12 / C."
    with pytest.raises(CaseFileError, match="280"):
        clean_note("n" * 281)
    with pytest.raises(CaseFileError):
        clean_ref("ref_code")
    with pytest.raises(CaseFileError):
        clean_ref("r" * 41)


def test_reminder_date_bounds_and_empty_clear() -> None:
    today = dt.date(2026, 9, 27)
    assert clean_remind("", today) is None
    assert clean_remind(today.isoformat(), today) == today.isoformat()
    assert clean_remind((today + dt.timedelta(days=365)).isoformat(), today) == "2027-09-27"
    for value in ((today - dt.timedelta(days=1)).isoformat(), "2027-09-28", "2026-02-30", "tomorrow"):
        with pytest.raises(CaseFileError):
            clean_remind(value, today)


def test_consent_refusal_leaves_both_tables_empty(tmp_path) -> None:
    path = tmp_path / "case.sqlite"
    store = CaseFileStore(path)
    try:
        with pytest.raises(CaseConsentRequired) as caught:
            store.create(("device", ""), "tasinma", False)
        assert caught.value.code == "consent_required"
        assert _count(path, "case_files") == _count(path, "case_steps") == 0
    finally:
        store.close()


def test_device_flow_persists_without_storing_the_key(tmp_path) -> None:
    path = tmp_path / "case.sqlite"
    store = CaseFileStore(path)
    file, key = store.create(("device", ""), "tasinma", True)
    assert key and len(key) >= 30
    owner = ("device", token_hash(key))
    store.set_answer(owner, file["id"], "su", "yenileme")
    store.set_step(owner, file["id"], "su", done=True, note="Abonelik adımı", ref_code="ISK-AB-321", remind_on=REMIND_ON)
    raw = path.read_bytes()
    assert key.encode() not in raw
    store.close()

    restarted = CaseFileStore(path)
    try:
        saved = restarted.files(owner)[0]
        assert saved["answers"] == {"su": "yenileme"}
        step = next(item for item in saved["steps"] if item["step_id"] == "su")
        assert step["done_at"] and step["note"] == "Abonelik adımı"
        assert step["ref_code"] == "ISK-AB-321" and step["remind_on"] == REMIND_ON
    finally:
        restarted.close()


def test_other_owner_cannot_read_or_mutate_a_file(tmp_path) -> None:
    store = CaseFileStore(tmp_path / "case.sqlite")
    file, key = store.create(("device", ""), "tasinma", True)
    owner_a = ("device", token_hash(key))
    owner_b = ("device", token_hash("different device key"))
    for operation in (
        lambda: store.set_answer(owner_b, file["id"], "su", "iptal"),
        lambda: store.set_step(owner_b, file["id"], "su", done=True),
        lambda: store.delete(owner_b, file["id"]),
    ):
        with pytest.raises(CaseFileError) as caught:
            operation()
        assert caught.value.status == 404 and caught.value.code == "file_not_found"
    assert store.files(owner_a)[0]["id"] == file["id"]
    store.close()


def test_owner_limits_unknown_ids_and_duplicate_plan(tmp_path, monkeypatch) -> None:
    path = tmp_path / "case.sqlite"
    original = json.loads(PLAN_PATH.read_text(encoding="utf-8"))["plans"][0]
    plans = []
    for plan_id in ("tasinma", "extra-1", "extra-2", "extra-3"):
        plan = copy.deepcopy(original)
        plan["id"] = plan_id
        plans.append(plan)
    definitions = tmp_path / "plans.json"
    definitions.write_text(json.dumps({"version": 1, "checked_at": "2026-09-27", "index": "local", "plans": plans}))
    monkeypatch.setattr(case_file, "PLAN_PATH", definitions)
    store = CaseFileStore(path)
    owner = ("account", "account-id")
    first, _ = store.create(owner, "tasinma", True)
    with pytest.raises(CaseFileError) as duplicate:
        store.create(owner, "tasinma", True)
    assert duplicate.value.code == "plan_exists"
    store.create(owner, "extra-1", True)
    store.create(owner, "extra-2", True)
    with pytest.raises(CaseFileError) as capped:
        store.create(owner, "extra-3", True)
    assert capped.value.code == "too_many_files"
    with pytest.raises(CaseFileError) as plan_unknown:
        store.create(owner, "unknown", True)
    assert plan_unknown.value.code == "plan_unknown"
    with pytest.raises(CaseFileError) as step_unknown:
        store.set_step(owner, first["id"], "unknown", done=True)
    assert step_unknown.value.code == "step_unknown"
    with pytest.raises(CaseFileError) as choice_unknown:
        store.set_answer(owner, first["id"], "su", "unknown")
    assert choice_unknown.value.code == "choice_unknown"
    store.close()


def test_expiry_is_extended_by_writes_and_cascades_steps(tmp_path) -> None:
    clock = Clock()
    path = tmp_path / "case.sqlite"
    store = CaseFileStore(path, clock=clock)
    file, key = store.create(("device", ""), "tasinma", True)
    owner = ("device", token_hash(key))
    original_expiry = file["expires_at"]
    clock.value += dt.timedelta(days=89)
    updated = store.set_step(owner, file["id"], "su", note="uzat")
    assert updated["expires_at"] > original_expiry
    clock.value += dt.timedelta(days=2)
    assert len(store.files(owner)) == 1
    clock.value += dt.timedelta(days=90)
    assert store.files(owner) == []
    assert _count(path, "case_files") == _count(path, "case_steps") == 0
    store.close()


def test_account_deletion_is_purged_on_the_next_case_file_read(tmp_path) -> None:
    accounts_path = tmp_path / "accounts.sqlite"
    accounts = AccountStore(accounts_path)
    account, _ = accounts.create(email="reader@example.org", provider="ibb", consent=True)
    store = CaseFileStore(tmp_path / "case.sqlite", accounts_path=accounts_path)
    store.create(("account", account.id), "tasinma", True)
    assert _count(store.path, "case_files") == 1
    accounts.delete(account.id)
    assert store.files(("account", account.id)) == []
    assert _count(store.path, "case_files") == _count(store.path, "case_steps") == 0
    store.close()
    accounts.close()


def test_progress_and_due_reminders_skip_completed_steps(tmp_path) -> None:
    store = CaseFileStore(tmp_path / "case.sqlite")
    file, key = store.create(("device", ""), "tasinma", True)
    owner = ("device", token_hash(key))
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))["plans"][0]
    today = dt.date.today().isoformat()  # the store accepts reminders from today on, so a fixed date ages out
    store.set_step(owner, file["id"], "dogalgaz", remind_on=today)
    store.set_step(owner, file["id"], "su", done=True, remind_on=today)
    saved = store.files(owner)[0]
    assert progress(saved, plan) == {"done": 1, "total": 6}
    assert due_reminders(saved, plan, dt.date.today()) == [
        {"step_id": "dogalgaz", "title": "Doğal gaz", "remind_on": today}
    ]
    store.close()
