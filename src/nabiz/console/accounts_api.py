"""The example-account and follow routes (DECISIONS #38).

``X-Nabiz-Account`` carries the sign-in token the page keeps on the device; nothing else opens
an account. Every body is JSON in a POST, never a query string, so an address never reaches an
access log. Routes:

* ``GET  /api/account/providers``: the three example sign-ins, the tier table and the consent text.
* ``POST /api/account/signin``: ``{provider, email, consent, sms_code?}``. Without ``consent: true``
  it answers 400 and writes nothing. The verification e-mail goes to the outbox, never out.
* ``GET  /api/account``: the account, its follows and today's quota. ``DELETE /api/account``: gone,
  with its follows and outbox files.
* ``GET  /api/account/outbox``: the account's own e-mail previews.
* ``POST /api/account/follows``, ``DELETE /api/account/follows/{id}``: at most ten topics.
* ``POST /api/follows/status``: current state of up to ten topics sent in the body, for the page's
  own notices (a visitor without an account keeps three on the device). Stateless.
* ``POST /api/follow/unsubscribe``: the signed token of an e-mail's "takibi bırak" link.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from nabiz.console.accounts import (
    ACCOUNT_FOLLOW_LIMIT,
    CONSENT_TEXT,
    CONSENT_VERSION,
    DEVICE_FOLLOW_LIMIT,
    EXAMPLE_BAND,
    EXAMPLE_SMS_CODE,
    PROVIDERS,
    Account,
    AccountStore,
    ConsentRequired,
    FollowLimit,
)
from nabiz.console.booking import BookingStore, booking_path
from nabiz.console.digest import check_unsubscribe, verification_email
from nabiz.console.email_sender import OutboxEmailSender, outbox_dir_from_env
from nabiz.console.follow import topic_from
from nabiz.console.follow_eval import evaluate_topics
from nabiz.console.journey_watch import JourneyStore, journeys_path
from nabiz.console.operator import port_problem
from nabiz.console.quota import Holder, QuotaBook

ACCOUNT_HEADER = "x-nabiz-account"
DEVICE_HEADER = "x-nabiz-device"

account_routes = APIRouter()


def store_for(request: Request) -> AccountStore:
    """The app's account file, opened on first use (``NABIZ_ACCOUNTS_DB``); a test may set its own."""
    state = request.app.state
    if getattr(state, "accounts", None) is None:
        state.accounts = AccountStore.from_env()
        state.accounts.purge_inactive()
    return state.accounts


def outbox_for(request: Request) -> OutboxEmailSender:
    state = request.app.state
    if getattr(state, "outbox", None) is None:
        state.outbox = OutboxEmailSender(outbox_dir_from_env())
    return state.outbox


def current_account(request: Request) -> Account | None:
    token = request.headers.get(ACCOUNT_HEADER)
    return store_for(request).by_token(token) if token else None


def holder_for(request: Request, account: Account | None = None) -> Holder:
    """Who this request is counted against: the account when a token opens one, else this device."""
    account = account if account is not None else current_account(request)
    book: QuotaBook = request.app.state.quota
    host = request.client.host if request.client else None
    if account is not None:
        return book.holder(device=None, host=host, account_id=account.id, tier=account.tier)
    return book.holder(device=request.headers.get(DEVICE_HEADER), host=host)


def quota_status(request: Request, account: Account | None = None) -> dict[str, Any]:
    account = account if account is not None else current_account(request)
    status = request.app.state.quota.status(holder_for(request, account))
    return {**status, "has_account": account is not None}


def _signed_out() -> Response:
    return port_problem(401, "no_account", "Bu cihazda bağlı bir örnek hesap yok.")


class SignIn(BaseModel):
    provider: Literal["ibb", "istanbulkart", "google"]
    email: str = Field(min_length=3, max_length=254)
    consent: bool = False
    sms_code: str | None = Field(default=None, max_length=12)


class FollowIn(BaseModel):
    kind: Literal["metro_line", "station", "bus_line", "knowledge"]
    value: str = Field(min_length=1, max_length=60)


class FollowCheck(BaseModel):
    topics: list[FollowIn] = Field(default_factory=list, max_length=ACCOUNT_FOLLOW_LIMIT)


class Unsubscribe(BaseModel):
    token: str = Field(min_length=3, max_length=120)


@account_routes.get("/api/account/providers")
async def providers(request: Request) -> dict[str, Any]:
    return {
        "providers": [{"key": key, **value, "example": True, "band": EXAMPLE_BAND} for key, value in PROVIDERS.items()],
        "tiers": request.app.state.quota.table(),
        "consent": {"text": CONSENT_TEXT, "version": CONSENT_VERSION},
        "sms_example_code": EXAMPLE_SMS_CODE,
        "limits": {"device_follows": DEVICE_FOLLOW_LIMIT, "account_follows": ACCOUNT_FOLLOW_LIMIT},
        "band": EXAMPLE_BAND,
    }


@account_routes.post("/api/account/signin")
async def signin(request: Request, body: SignIn) -> Any:
    if body.consent is not True:
        return port_problem(
            400, "consent_required", "Hesap bağlamak için açık rıza kutusunu işaretleyin. Hiçbir şey kaydedilmedi."
        )
    if PROVIDERS[body.provider]["flow"] == "sms" and (body.sms_code or "").strip() != EXAMPLE_SMS_CODE:
        return port_problem(
            400, "sms_code", f"Örnek kod yanlış. Bu gösterimde kod her zaman {EXAMPLE_SMS_CODE}; SMS gönderilmez."
        )
    try:
        account, token = store_for(request).create(email=body.email, provider=body.provider, consent=body.consent)
    except ConsentRequired:
        return port_problem(400, "consent_required", "Hesap bağlamak için açık rıza kutusunu işaretleyin.")
    except ValueError as exc:
        return port_problem(400, "invalid_email", str(exc))
    preview = outbox_for(request).send(verification_email(account))
    return {
        "token": token,
        "account": account.public(),
        "band": EXAMPLE_BAND,
        "verification": {"sent": False, "id": preview.reference},
    }


@account_routes.get("/api/account")
async def account_view(request: Request) -> Any:
    account = current_account(request)
    if account is None:
        return _signed_out()
    return {
        "account": account.public(),
        "follows": _follows(request, account),
        "quota": quota_status(request, account),
        "band": EXAMPLE_BAND,
    }


def _follows(request: Request, account: Account) -> list[dict[str, Any]]:
    return [
        {key: follow[key] for key in ("id", "kind", "value", "label", "added_at")}
        for follow in store_for(request).follows(account.id)
    ]


@account_routes.delete("/api/account")
async def account_delete(request: Request) -> Any:
    account = current_account(request)
    if account is None:
        return _signed_out()
    removed = store_for(request).delete(account.id)
    emails = outbox_for(request).purge(account.id)
    journeys = _delete_saved_journeys(request, account.id)
    bookings = _delete_bookings(request, account.id)
    return {
        "deleted": removed, "outbox_deleted": emails, "journeys_deleted": journeys, "bookings_deleted": bookings,
        "message": "Hesabın, takip konuların ve e-posta önizlemelerin silindi.",
    }


def _delete_saved_journeys(request: Request, account_id: str) -> int:
    """E65: an account's saved journeys go with it (kvkk). No store file yet means nothing was saved."""
    store = getattr(request.app.state, "journey_watch_store", None)
    if store is None and not journeys_path().is_file():
        return 0
    return (store or JourneyStore()).delete_account(account_id)


def _delete_bookings(request: Request, account_id: str) -> int:
    """E53: the account's example library bookings go with it. No store file yet means nothing was booked.

    Read from the store module, not ``booking_api``: that one imports this module (an import cycle).
    """
    store = getattr(request.app.state, "booking_store", None)
    if store is None and not booking_path().is_file():
        return 0
    store = store or BookingStore()
    return store.delete_holder(store.holder_of("account", account_id))


@account_routes.get("/api/account/outbox")
async def account_outbox(request: Request) -> Any:
    account = current_account(request)
    if account is None:
        return _signed_out()
    return {"sent": False, "previews": outbox_for(request).previews(account.id)}


@account_routes.post("/api/account/follows")
async def follow_add(request: Request, body: FollowIn) -> Any:
    account = current_account(request)
    if account is None:
        return _signed_out()
    try:
        topic = topic_from(body.kind, body.value)
        follow = store_for(request).add_follow(account.id, kind=topic.kind, value=topic.value, label=topic.label)
    except FollowLimit as exc:
        return port_problem(409, "follow_limit", str(exc))
    except ValueError as exc:
        return port_problem(400, "follow_topic", str(exc))
    return {"follow": follow, "follows": _follows(request, account)}


@account_routes.delete("/api/account/follows/{follow_id}")
async def follow_remove(request: Request, follow_id: str) -> Any:
    account = current_account(request)
    if account is None:
        return _signed_out()
    removed = store_for(request).remove_follow(account.id, follow_id[:32])
    return {"removed": removed, "follows": _follows(request, account)}


@account_routes.post("/api/follows/status")
async def follows_status(request: Request, body: FollowCheck) -> Any:
    try:
        topics = [topic_from(item.kind, item.value) for item in body.topics]
    except ValueError as exc:
        return port_problem(400, "follow_topic", str(exc))
    states = await evaluate_topics(request.app.state.nabiz, topics)
    return {"topics": [state.public() for state in states.values()]}


@account_routes.post("/api/follow/unsubscribe")
async def follow_unsubscribe(request: Request, body: Unsubscribe) -> Any:
    store = store_for(request)
    follow_id = check_unsubscribe(store.secret(), body.token)
    owner = store.follow_owner(follow_id) if follow_id else None
    if follow_id is None or owner is None:
        return port_problem(404, "not_found", "Bu bağlantının takibi bulunamadı; zaten bırakılmış olabilir.")
    store.remove_follow(owner, follow_id)
    return {"removed": True, "message": "Takip bırakıldı. Bu konu için artık e-posta hazırlanmaz."}
