"""Every server store an account reaches, and the erasure chain over them (P00 D2a, H).

Deleting an account runs one hook per store in :data:`~nabiz.console.erasure.REQUIRED_HOOKS` order, the
account row last. A hook that fails stops the chain: the route answers 503 and keeps the account, so the
person can try again and is never told everything went when it did not. Photo reports and citizen requests
are keyed by a code kept on the person's device, and memory lives only in the browser, so the account holds
nothing there; their hooks say so with 0 rather than pretend to delete.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nabiz.console.accounts import AccountStore
from nabiz.console.booking import BookingStore, booking_path
from nabiz.console.email_sender import OutboxEmailSender
from nabiz.console.erasure import ErasureChain
from nabiz.console.family import FamilyError, FamilyStore
from nabiz.console.journey_watch import JourneyStore, journeys_path
from nabiz.console.plan_store import PlanStore, plans_path


def _nothing_under_the_account(account_id: str) -> int:
    del account_id
    return 0


def _plans(state: Any, account_id: str) -> int:
    """P06: the server calendar's plans and their operations. No store and no file: nothing was saved."""
    store = getattr(state, "plan_store", None)
    if store is None and not plans_path().is_file():
        return 0
    return (store or PlanStore.from_env()).erase_owner(account_id)


def _outlook_tokens(state: Any, account_id: str) -> int:
    """Outlook is closed today (no token store). A store that cannot delete fails the chain: better a 503
    than an account deleted with its Microsoft token kept."""
    tokens = getattr(state, "plan_tokens", None)
    return 0 if tokens is None else int(tokens.delete(account_id))


def _appeals(state: Any, account_id: str) -> int:
    """P08: the account's appeals and restriction, kept under its quota pseudonym."""
    book = getattr(state, "appeal_book", None)
    return 0 if book is None else book.purge_subject(state.quota.pseudonym("hesap", account_id))


def _bookings(state: Any, account_id: str) -> int:
    """E53: the account's example library bookings. No store file yet means nothing was booked."""
    store = getattr(state, "booking_store", None)
    if store is None and not booking_path().is_file():
        return 0
    store = store or BookingStore()
    return store.delete_holder(store.holder_of("account", account_id))


def _journeys(state: Any, account_id: str) -> int:
    """E65: the account's saved journeys. No store file yet means nothing was saved."""
    store = getattr(state, "journey_watch_store", None)
    if store is None and not journeys_path().is_file():
        return 0
    return (store or JourneyStore()).delete_account(account_id)


def _family(state: Any, accounts: AccountStore, account_id: str) -> int:
    """E52: the account leaves its family (an owner's leaving dissolves the group) and its join request goes.
    Its attempt counter is keyed to the account row and goes with it (ON DELETE CASCADE)."""
    store = getattr(state, "family", None) or FamilyStore(accounts)
    removed = 0
    for step in (store.leave, store.cancel_request):
        try:
            step(account_id)
            removed += 1
        except FamilyError as exc:
            if exc.status != 404:  # nothing to leave or cancel is fine; anything else stops the chain
                raise
    return removed


def _quota(state: Any, account_id: str) -> int:
    """P13: every day's counts of the account. An app with no quota book (a bare router in a test) has none."""
    book = getattr(state, "quota", None)
    return 0 if book is None else book.erase_account(account_id)


def _sessions(state: Any, account_id: str) -> int:
    """P13: every sign-in session of the account."""
    sessions = getattr(state, "sessions", None)
    return 0 if sessions is None else sessions.revoke_account(account_id)


def erasure_chain(state: Any, accounts: AccountStore, outbox: OutboxEmailSender) -> ErasureChain:
    """The chain for this app: one hook per store, bound to the app's state."""
    hooks: dict[str, Callable[[str], object]] = {
        "calendar_plans": lambda account_id: _plans(state, account_id),
        "outlook_tokens": lambda account_id: _outlook_tokens(state, account_id),
        "appeals": lambda account_id: _appeals(state, account_id),
        "bookings": lambda account_id: _bookings(state, account_id),
        "journeys": lambda account_id: _journeys(state, account_id),
        "photo_reports": _nothing_under_the_account,
        "account_memory": _nothing_under_the_account,
        "citizen_requests": _nothing_under_the_account,
        "email_outbox": outbox.purge,
        "family_links": lambda account_id: _family(state, accounts, account_id),
        "quota": lambda account_id: _quota(state, account_id),
        "sessions": lambda account_id: _sessions(state, account_id),
        "account": lambda account_id: int(accounts.delete(account_id)),
    }
    return ErasureChain(hooks)
