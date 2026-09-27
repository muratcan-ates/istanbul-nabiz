"""JSON routes for example-family membership; every path carries the account identity header."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, StrictBool

from nabiz.console.accounts import Account
from nabiz.console.accounts_api import current_account, store_for
from nabiz.console.family import FamilyError, FamilyStore
from nabiz.console.operator import port_problem

family_routes = APIRouter()
_NO_ACCOUNT = "Bu cihazda bağlı bir örnek hesap yok."


class FamilyCodeIn(BaseModel):
    display_name: str = Field(default="", max_length=100)
    consent: StrictBool = False


class FamilyJoinIn(BaseModel):
    code: str = Field(default="", max_length=32)
    display_name: str = Field(default="", max_length=100)
    consent: StrictBool = False


class FamilySharesIn(BaseModel):
    follow_ids: list[str] = Field(default_factory=list, max_length=10)
    stops: list[dict[str, str]] = Field(default_factory=list, max_length=6)


def family_store_for(request: Request) -> FamilyStore:
    """Open a family store on the same test or configured SQLite file as the account store."""
    state = request.app.state
    if getattr(state, "family", None) is None:
        state.family = FamilyStore(store_for(request))
    return state.family


def _perform(
    request: Request,
    account: Account | None,
    operation: Callable[[FamilyStore, str], dict[str, Any]],
    message: str,
) -> Any:
    if account is None:
        return port_problem(401, "no_account", _NO_ACCOUNT)
    try:
        result = operation(family_store_for(request), account.id)
    except FamilyError as exc:
        return port_problem(exc.status, exc.code, exc.message)
    extras = {key: value for key, value in result.items() if key == "dissolved"}
    view = result.get("view", result)
    return {**view, **extras, "message": message}


@family_routes.get("/api/account/family")
async def get_family(request: Request) -> Any:
    account = current_account(request)
    return _perform(request, account, lambda store, account_id: store.view(account_id), "Aile durumunuz güncellendi.")


@family_routes.post("/api/account/family/code")
async def create_family_code(request: Request, body: FamilyCodeIn) -> Any:
    account = current_account(request)
    return _perform(
        request,
        account,
        lambda store, account_id: store.create_code(account_id, body.display_name, body.consent),
        "Aile kodunuz hazır.",
    )


@family_routes.post("/api/account/family/code/renew")
async def renew_family_code(request: Request) -> Any:
    account = current_account(request)
    return _perform(request, account, lambda store, account_id: store.renew_code(account_id), "Kodunuz yenilendi.")


@family_routes.post("/api/account/family/join")
async def request_family_join(request: Request, body: FamilyJoinIn) -> Any:
    account = current_account(request)

    def join(store: FamilyStore, account_id: str) -> dict[str, Any]:
        store.request_join(account_id, body.code, body.display_name, body.consent)
        return store.view(account_id)

    return _perform(request, account, join, "Katılma isteğiniz gönderildi.")


@family_routes.delete("/api/account/family/join")
async def cancel_family_join(request: Request) -> Any:
    account = current_account(request)
    return _perform(request, account, lambda store, account_id: store.cancel_request(account_id), "İstek geri alındı.")


@family_routes.post("/api/account/family/requests/{request_id}/approve")
async def approve_family_request(request: Request, request_id: str) -> Any:
    account = current_account(request)
    return _perform(
        request,
        account,
        lambda store, account_id: store.decide(account_id, request_id[:32], True),
        "Katılma isteği onaylandı.",
    )


@family_routes.post("/api/account/family/requests/{request_id}/reject")
async def reject_family_request(request: Request, request_id: str) -> Any:
    account = current_account(request)
    return _perform(
        request,
        account,
        lambda store, account_id: store.decide(account_id, request_id[:32], False),
        "Katılma isteği reddedildi.",
    )


@family_routes.delete("/api/account/family/members/{member_id}")
async def remove_family_member(request: Request, member_id: str) -> Any:
    account = current_account(request)
    return _perform(
        request,
        account,
        lambda store, account_id: store.remove_member(account_id, member_id[:32]),
        "Üye aileden çıkarıldı.",
    )


@family_routes.post("/api/account/family/leave")
async def leave_family(request: Request) -> Any:
    account = current_account(request)
    return _perform(request, account, lambda store, account_id: store.leave(account_id), "Aile üyeliği sona erdi.")


@family_routes.post("/api/account/family/shares")
async def save_family_shares(request: Request, body: FamilySharesIn) -> Any:
    account = current_account(request)
    return _perform(
        request,
        account,
        lambda store, account_id: store.set_shares(account_id, body.follow_ids, body.stops),
        "Paylaşım seçiminiz kaydedildi.",
    )
