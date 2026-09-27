"""Deletion chain never claims success when any required module is missing."""

import pytest

from nabiz.console.erasure import REQUIRED_HOOKS, ErasureChain, ErasureIncomplete


def test_all_scoped_hooks_run_and_account_deletion_is_last() -> None:
    calls = []
    chain = ErasureChain({name: lambda account_id, name=name: calls.append((name, account_id)) for name in REQUIRED_HOOKS})
    result = chain.erase("account-a")
    assert result.completed == REQUIRED_HOOKS
    assert calls == [(name, "account-a") for name in REQUIRED_HOOKS]
    assert calls[-1][0] == "account"


def test_missing_hook_refuses_before_any_deletion() -> None:
    calls = []
    chain = ErasureChain({name: lambda account_id: calls.append(account_id) for name in REQUIRED_HOOKS[:-1]})
    with pytest.raises(ErasureIncomplete) as caught:
        chain.erase("account-a")
    assert caught.value.completed == () and calls == []


def test_failed_hook_reports_partial_progress_and_preserves_account() -> None:
    calls = []

    def fail(account_id):
        raise RuntimeError("storage unavailable")

    hooks = {name: lambda account_id, name=name: calls.append(name) for name in REQUIRED_HOOKS}
    hooks["quota"] = fail
    with pytest.raises(ErasureIncomplete) as caught:
        ErasureChain(hooks).erase("account-a")
    assert caught.value.failed == "quota"
    assert "account" not in calls
