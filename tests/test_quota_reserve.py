"""P00 D2a (P13): a turn claims its model calls atomically, keeps what it used and gives back the rest."""

from __future__ import annotations

import asyncio
import pathlib

import pytest
from conftest import offline_settings

from nabiz.agent import llm
from nabiz.console.access import OperatorAccess
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.quota import CURRENT_METER, Meter, MeteredGuard, QuotaBook, Tier
from nabiz.console.quota_api import TurnPlan
from nabiz.console.quota_store import PersistentQuotaBook
from nabiz.console.sessions import SessionStore

TIERS = {"cihaz": Tier("cihaz", "Cihaz", 20, 10)}


class Inner:
    def __init__(self, room: bool = True) -> None:
        self.room, self.recorded = room, 0

    def allows(self, provider: str) -> bool:
        return self.room

    def reserve(self, provider: str, calls: int) -> bool:
        return self.room

    def release(self, provider: str, calls: int) -> None:
        pass

    def record(self, provider: str, usage: object, calls: int) -> None:
        self.recorded += calls


@pytest.fixture(params=["memory", "sqlite"])
def book(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> QuotaBook:
    return QuotaBook(TIERS) if request.param == "memory" else PersistentQuotaBook(tmp_path / "quota.sqlite", TIERS)


def metered(book: QuotaBook, inner: Inner) -> tuple[MeteredGuard, Meter]:
    holder = book.holder(device="d" * 20, host="192.0.2.7")
    meter = Meter(book, holder, model_open=True)
    CURRENT_METER.set(meter)
    return MeteredGuard(inner), meter


def test_a_chat_turn_keeps_the_calls_it_made_and_refunds_the_rest(book: QuotaBook) -> None:
    guard, meter = metered(book, Inner())
    try:
        assert guard.reserve("openai", 3) and book.calls_left(meter.holder) == 7
        guard.record("openai", {}, 2)
        guard.release("openai", 3)
        assert book.calls_left(meter.holder) == 8 and meter.held == 0
    finally:
        CURRENT_METER.set(None)


def test_a_release_before_the_record_still_counts_the_call(book: QuotaBook) -> None:
    guard, meter = metered(book, Inner())
    try:
        assert guard.reserve("openai", 1)
        guard.release("openai", 1)  # the emergency model's order
        guard.record("openai", {}, 1)
        assert book.calls_left(meter.holder) == 9
    finally:
        CURRENT_METER.set(None)


def test_a_refused_reservation_claims_nothing(book: QuotaBook) -> None:
    guard, meter = metered(book, Inner(room=False))
    try:
        assert not guard.reserve("openai", 3)
        assert book.calls_left(meter.holder) == 10 and meter.held == 0
    finally:
        CURRENT_METER.set(None)


def test_more_than_is_left_is_refused_whole(book: QuotaBook) -> None:
    guard, meter = metered(book, Inner())
    try:
        assert not guard.reserve("openai", 11)
        assert book.calls_left(meter.holder) == 10 and meter.held == 0
    finally:
        CURRENT_METER.set(None)


def test_a_turn_cut_off_mid_way_gives_its_claim_back(tmp_path: pathlib.Path) -> None:
    store = PersistentQuotaBook(tmp_path / "quota.sqlite", TIERS)
    holder = store.holder(device="d" * 20, host="192.0.2.7")
    guard = MeteredGuard(Inner())

    class Service:
        async def events(self, body: object):
            assert guard.reserve("openai", 3)
            yield "event: tool\ndata: {}\n\n"
            yield "event: final\ndata: {}\n\n"

    async def run() -> None:
        stream = TurnPlan(False, store, holder, "soru").events(Service(), None)
        await stream.__anext__()
        assert store.calls_left(holder) == 7
        await stream.aclose()

    asyncio.run(run())
    assert store.calls_left(holder) == 10 and store.status(holder)["questions_left"] == 19


def test_the_product_app_keeps_quota_and_sessions_in_their_files(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "nexus.db"))
    monkeypatch.setenv("NABIZ_QUOTA_DB", str(tmp_path / "q" / "quota.sqlite"))
    monkeypatch.setenv("NABIZ_SESSIONS_DB", str(tmp_path / "s" / "sessions.sqlite"))
    app = build_console_app(
        settings=offline_settings(), llm_config=llm.LlmConfig(), guard=SpendGuard(BudgetConfig(state_path=None)),
        access=OperatorAccess(token="test-operator-token", bound_host="0.0.0.0"),
    )
    assert isinstance(app.state.quota, PersistentQuotaBook) and app.state.quota.path == tmp_path / "q" / "quota.sqlite"
    assert isinstance(app.state.sessions, SessionStore) and app.state.sessions.path == tmp_path / "s" / "sessions.sqlite"
