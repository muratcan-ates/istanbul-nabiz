"""Stateless journey impact checks and the separately consented account routes."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from nabiz.console.accounts_api import current_account
from nabiz.console.cards import provenance_view, unknown_provenance
from nabiz.console.journey_watch import (
    ACCOUNT_LIMIT,
    DEVICE_LIMIT,
    JourneyStore,
    impact,
    journey_from,
)
from nabiz.console.operator import port_problem
from nabiz.console.ports import PortNotWired

JOURNEY_CONSENT_VERSION = "2026-09-27"
JOURNEY_CONSENT_TEXT = (
    "Açık rızamla kayıtlı yolculuklarımın (başlangıç, varış, saat, kısıt) bu projenin sunucusunda, "
    "hesabıma bağlı olarak saklanmasını kabul ediyorum. İstediğim an silebilirim; 90 gün kullanılmazsa silinir. "
    "Kaydettiğiniz yolculuklar, adınız ve cihazınız olmadan yalnız toplam sayı olarak İBB operatörünün etki "
    "senaryolarında kullanılabilir."
)

journey_watch_routes = APIRouter()


class JourneyBatch(BaseModel):
    journeys: list[dict[str, Any]] = Field(min_length=1, max_length=DEVICE_LIMIT)


class JourneySave(BaseModel):
    journey: dict[str, Any]
    consent: bool = False


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _provenance(result: Any, request: Request, source: str) -> dict[str, Any]:
    provenance = getattr(result, "provenance", None)
    return (
        provenance_view(provenance, offline=request.app.state.fresh.offline)
        if provenance is not None
        else unknown_provenance(source)
    )


def _source_time(result: Any) -> str | None:
    provenance = getattr(result, "provenance", None)
    value = getattr(provenance, "reported_at", None) or getattr(provenance, "observed_at", None)
    return value.isoformat() if isinstance(value, dt.datetime) else None


def _invalid(raw: Mapping[str, Any], index: int, message: str, checked_at: str) -> dict[str, Any]:
    raw_id = raw.get("id")
    safe_id = (
        raw_id
        if isinstance(raw_id, str)
        and 1 <= len(raw_id) <= 24
        and all(ch.isascii() and (ch.islower() or ch.isdigit() or ch == "-") for ch in raw_id)
        else f"invalid-{index + 1}"
    )
    return {
        "id": safe_id,
        "level": "invalid",
        "from": "",
        "to": "",
        "time": None,
        "needs": [],
        "headline": "Yolculuk kaydı kontrol edilemedi.",
        "affected_needs": [],
        "reasons": [],
        "alternative": None,
        "lines": [],
        "fingerprint": [],
        "comparable": False,
        "time_note": None,
        "uncertainty": [],
        "disclaimer": "",
        "provenance": unknown_provenance("metro_equipment"),
        "notices_observed_at": None,
        "checked_at": checked_at,
        "error": message,
    }


async def _read_notices(nabiz: Any) -> tuple[Any, list[Mapping[str, Any]] | None]:
    try:
        result = await nabiz.metro_status()
        return result, result.data.get("lines") or []
    except Exception:  # noqa: BLE001 - one unreadable source must not be reported as clear
        return None, None


async def _alternative(request: Request, journey: Any, plan: Mapping[str, Any]) -> Mapping[str, Any] | None:
    used = plan.get("alternatives_used") or []
    if not used or "step_free" not in journey.needs:
        return None
    first = used[0]
    station = first.get("avoided_station") if isinstance(first, Mapping) else None
    port = getattr(request.app.state.ports, "step_free", None)
    if not station or port is None:
        return None
    try:
        return await port.alternative(station, list(journey.needs))
    except (PortNotWired, NotImplementedError):
        return None
    except Exception:  # noqa: BLE001 - approvals are optional; the route remains unapproved
        return None


async def _check_one(
    request: Request,
    raw: Mapping[str, Any],
    index: int,
    journey: Any,
    notices: list[Mapping[str, Any]] | None,
    notice_result: Any,
    checked_at: str,
) -> dict[str, Any]:
    nabiz = request.app.state.nabiz
    try:
        plan_result = await nabiz.accessible_journey(journey.origin, journey.destination, list(journey.needs))
        plan = dict(plan_result.data)
        plan["observed_at"] = _source_time(plan_result)
    except PortNotWired:
        raise
    except LookupError:
        return _invalid(raw, index, "Başlangıç ya da varış yeri bulunamadı.", checked_at)
    except ValueError as exc:
        return _invalid(raw, index, str(exc), checked_at)
    except Exception:  # noqa: BLE001 - source failures are uncertain, never a clear result
        plan_result = None
        plan = {
            "available": False,
            "reason": "Yolculuk kaynağı şu an okunamadı; doğrulanamadı.",
            "uncertainty": ["journey_source_unavailable"],
        }
    result = impact(journey, plan, notices, alternative=await _alternative(request, journey, plan), checked_at=checked_at)
    if plan_result is not None:
        result["provenance"] = _provenance(plan_result, request, "metro_equipment")
    if notice_result is not None:
        result["notices_observed_at"] = _source_time(notice_result)
    return result


async def _check(request: Request, raw_journeys: list[Mapping[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Read shared notices once, then isolate every journey's source failure."""
    checked_at = _now()
    notice_result, notices = await _read_notices(request.app.state.nabiz)
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_journeys):
        try:
            journey = journey_from(raw)
        except ValueError as exc:
            results.append(_invalid(raw, index, str(exc), checked_at))
            continue
        if journey.id in seen_ids:
            results.append(_invalid(raw, index, "Yolculuk kimliği bu istekte zaten kullanılmış.", checked_at))
            continue
        seen_ids.add(journey.id)
        results.append(await _check_one(request, raw, index, journey, notices, notice_result, checked_at))
    return checked_at, results


@journey_watch_routes.post("/api/journey-watch/check")
async def check_journeys(request: Request, body: JourneyBatch) -> Any:
    try:
        checked_at, results = await _check(request, body.journeys)
    except PortNotWired as exc:
        return port_problem(503, "not_wired", str(exc))
    return {"checked_at": checked_at, "stored": False, "results": results}


def _store(request: Request) -> JourneyStore:
    state = request.app.state
    if getattr(state, "journey_watch_store", None) is None:
        state.journey_watch_store = JourneyStore()
    return state.journey_watch_store


def _account(request: Request) -> Any:
    account = current_account(request)
    if account is None:
        return None
    return account


@journey_watch_routes.get("/api/account/journeys")
async def list_account_journeys(request: Request) -> Any:
    account = _account(request)
    if account is None:
        return port_problem(401, "no_account", "Bu cihazda bağlı bir örnek hesap yok.")
    rows = _store(request).items(account.id)
    return {
        "consent_text": JOURNEY_CONSENT_TEXT,
        "consent_version": JOURNEY_CONSENT_VERSION,
        "limit": ACCOUNT_LIMIT,
        "journeys": rows,
    }


@journey_watch_routes.post("/api/account/journeys")
async def save_account_journey(request: Request, body: JourneySave) -> Any:
    account = _account(request)
    if account is None:
        return port_problem(401, "no_account", "Bu cihazda bağlı bir örnek hesap yok.")
    if body.consent is not True:
        return port_problem(400, "consent_required", "Yolculukları saklamak için ayrı açık rıza kutusunu işaretleyin.")
    try:
        journey = journey_from(body.journey)
        row = _store(request).save(account.id, journey, consent_version=JOURNEY_CONSENT_VERSION)
    except ValueError as exc:
        return port_problem(400, "bad_request", str(exc))
    return {"journey": row}


@journey_watch_routes.delete("/api/account/journeys/{journey_id}")
async def delete_account_journey(request: Request, journey_id: str) -> Any:
    account = _account(request)
    if account is None:
        return port_problem(401, "no_account", "Bu cihazda bağlı bir örnek hesap yok.")
    if not _store(request).delete(account.id, journey_id):
        return port_problem(404, "not_found", "Bu yolculuk kaydı bulunamadı.")
    return {"deleted": True}


@journey_watch_routes.post("/api/account/journeys/check")
async def check_account_journeys(request: Request) -> Any:
    account = _account(request)
    if account is None:
        return port_problem(401, "no_account", "Bu cihazda bağlı bir örnek hesap yok.")
    store = _store(request)
    rows = store.items(account.id)
    try:
        checked_at, results = await _check(request, rows)
    except PortNotWired as exc:
        return port_problem(503, "not_wired", str(exc))
    changes: dict[str, dict[str, list[str]]] = {}
    for result in results:
        journey_id = result["id"]
        changes[journey_id] = store.update_check(account.id, journey_id, result)
    return {"checked_at": checked_at, "stored": True, "results": results, "changed": changes}
