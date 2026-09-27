"""Object boundary and explicit guest migration selection."""

import pytest

from nabiz.console.ownership import OwnershipDenied, owned_record, require_owner, select_guest_records


def test_cross_account_read_write_delete_guard() -> None:
    records = {"record-1": {"owner_id": "account-a", "value": "private"}}
    assert owned_record(records, "record-1", "account-a")["value"] == "private"
    for account_id in ("account-b", None):
        with pytest.raises(OwnershipDenied, match="Kayıt bulunamadı"):
            owned_record(records, "record-1", account_id)
        with pytest.raises(OwnershipDenied):
            require_owner(account_id, records["record-1"]["owner_id"])
    with pytest.raises(OwnershipDenied):
        owned_record(records, "missing", "account-a")


def test_guest_migration_requires_marked_records_and_separate_health_consent() -> None:
    records = [{"id": "a", "kind": "preference", "forgotten": True},
               {"id": "b", "kind": "health", "value": "private"},
               {"id": "c", "kind": "preference"}]
    with pytest.raises(PermissionError):
        select_guest_records(records, selected_ids=["a"], consent=False)
    with pytest.raises(PermissionError):
        select_guest_records(records, selected_ids=["b"], consent=True)
    selected = select_guest_records(records, selected_ids=["a", "b"], consent=True, health_consent=True)
    assert selected.browser_delete_ids == ("a", "b") and selected.remaining_ids == ("c",)
    assert selected.selected[0]["forgotten"] is True
    assert len(records) == 3
    assert select_guest_records(records, selected_ids=[], consent=False).selected == ()
