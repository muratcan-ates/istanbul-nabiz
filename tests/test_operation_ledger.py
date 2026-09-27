import sqlite3

import pytest

from nabiz.console.operation_ledger import OperationConflict, OperationLedger


def test_ledger_replay_and_conflict():
    db = sqlite3.connect(":memory:")
    OperationLedger.create_schema(db)
    ledger = OperationLedger(db)
    ledger.record("owner", "op-1", "save", "hash", "plan", "saved", {"plan_id": "plan"})
    assert ledger.require_same("owner", "op-1", "save", "hash").target_id == "plan"
    assert ledger.get("other", "op-1") is None
    with pytest.raises(OperationConflict):
        ledger.require_same("owner", "op-1", "outlook", "hash")
    ledger.set_result("owner", "op-1", "added", {"result": "outlook_added"})
    assert ledger.get("owner", "op-1").result["result"] == "outlook_added"
    db.close()
