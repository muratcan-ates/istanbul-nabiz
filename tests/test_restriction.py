"""Session limits never become an IP-wide punishment or a content classifier."""

from __future__ import annotations

import datetime as dt

import pytest

from nabiz.console.restriction import AUTO_HOURS, REQUESTS_PER_WINDOW, RestrictionBook


class Clock:
    now = dt.datetime(2026, 9, 27, 12, tzinfo=dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.now


def test_shared_ip_has_independent_sessions_and_essential_actions_stay_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NABIZ_AUTO_RESTRICTION", "1")  # P00 D2a: the automatic path, switched on for this test
    clock = Clock()
    book = RestrictionBook(clock=clock)
    for _ in range(REQUESTS_PER_WINDOW):
        assert book.check("session-one", "model", address="10.0.0.1").allowed
    assert book.check("session-one", "model", address="10.0.0.1").code == "rate_limited"
    assert book.check("session-one", "upload", address="10.0.0.1").code == "rate_limited"
    blocked = book.check("session-one", "model", address="10.0.0.1")
    assert blocked.code == "restricted"
    assert blocked.restriction.until == clock.now + dt.timedelta(hours=AUTO_HOURS)
    assert book.check("session-two", "model", address="10.0.0.1").allowed
    assert not book.check("session-one", "upload").allowed
    for action in ("emergency", "appeal", "follow", "delete"):
        assert book.check("session-one", action).allowed
        assert book.check("", action).allowed


def test_expiry_and_human_only_long_restriction() -> None:
    clock = Clock()
    book = RestrictionBook(clock=clock)
    with pytest.raises(ValueError, match="insan"):
        book.restrict("session-one", reason="automated_burst", hours=48, human=False)
    long = book.restrict("session-one", reason="reviewed_abuse", hours=48, human=True)
    assert long.source == "human"
    clock.now += dt.timedelta(hours=49)
    assert book.current("session-one") is None
    assert book.check("session-one", "model").allowed


def test_complaint_and_repeated_subject_have_no_content_penalty() -> None:
    book = RestrictionBook(clock=Clock())
    for _ in range(REQUESTS_PER_WINDOW):
        assert book.check("session-one", "model").allowed
    assert book.current("session-one") is None
    with pytest.raises(ValueError, match="oturum"):
        book.check("ip:1", "model")
    with pytest.raises(ValueError, match="kodlanmış"):
        book.restrict("session-one", reason="Serbest metin ve kişi bilgisi", hours=24, human=True)


def test_automatic_restriction_is_off_by_the_owners_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    """P00 D2a: without NABIZ_AUTO_RESTRICTION=1 a burst is only rate limited, never restricted."""
    monkeypatch.delenv("NABIZ_AUTO_RESTRICTION", raising=False)
    clock = Clock()
    book = RestrictionBook(clock=clock)
    for _ in range(REQUESTS_PER_WINDOW):
        assert book.check("session-one", "model").allowed
    codes = {book.check("session-one", "model").code for _ in range(10)}
    assert codes == {"rate_limited"} and book.current("session-one") is None
    clock.now += dt.timedelta(seconds=61)
    assert book.check("session-one", "model").allowed
