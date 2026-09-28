"""Appeals stay in a human queue until a reasoned decision."""

from __future__ import annotations

import pytest

from nabiz.console.appeals import AppealBook
from nabiz.console.restriction import RestrictionBook


def prepared() -> tuple[RestrictionBook, AppealBook]:
    restrictions = RestrictionBook()
    restrictions.restrict("session-one", reason="automated_burst", hours=24, human=False)
    return restrictions, AppealBook(restrictions)


def test_appeal_is_queued_once_and_reopen_requires_specific_reason() -> None:
    restrictions, appeals = prepared()
    first = appeals.submit("session-one", "mistake")
    assert appeals.submit("session-one", "other").id == first.id
    assert [item.id for item in appeals.queue()] == [first.id]
    with pytest.raises(ValueError, match="Gerekçeli"):
        appeals.decide(first.id, action="reopen", reason="")
    with pytest.raises(ValueError, match="uygun"):
        appeals.decide(first.id, action="reopen", reason="restriction_upheld")
    result = appeals.decide(first.id, action="reopen", reason="mistaken_restriction")
    assert result.status == "reopened" and result.decision_reason == "mistaken_restriction"
    assert restrictions.current("session-one") is None
    assert appeals.queue() == []
    with pytest.raises(RuntimeError, match="zaten"):
        appeals.decide(first.id, action="reopen", reason="mistaken_restriction")


def test_upheld_restriction_does_not_create_an_unbounded_new_queue() -> None:
    _, appeals = prepared()
    first = appeals.submit("session-one", "other")
    appeals.decide(first.id, action="uphold", reason="restriction_upheld")
    assert appeals.submit("session-one", "mistake").id == first.id
    assert appeals.queue() == []


def test_another_session_cannot_read_the_appeal() -> None:
    _, appeals = prepared()
    appeal = appeals.submit("session-one", "shared_device")
    with pytest.raises(LookupError):
        appeals.for_subject(appeal.id, "session-two")
    assert "subject" not in appeals.for_subject(appeal.id, "session-one").citizen_view()


def test_account_deletion_purges_appeal_and_restriction() -> None:
    restrictions, appeals = prepared()
    appeal = appeals.submit("session-one", "mistake")
    assert appeals.purge_subject("session-one") == 1
    assert restrictions.current("session-one") is None
    with pytest.raises(LookupError):
        appeals.for_subject(appeal.id, "session-one")
