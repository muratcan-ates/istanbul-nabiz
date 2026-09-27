"""Citizen endpoints for the updates list and its optional calendar reminder."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ibb_mcp.models import utcnow
from nabiz.console.accounts import ACCOUNT_FOLLOW_LIMIT
from nabiz.console.citizen_requests import normal_code
from nabiz.console.email_sender import NOT_OFFICIAL
from nabiz.console.follow import topic_from
from nabiz.console.ics import calendar_text
from nabiz.console.notices_center import (
    Notice,
    calendar_event,
    report_notice,
    request_notice,
    sort_notices,
    topic_notices,
)
from nabiz.console.operator import port_problem
from nabiz.console.report_api import report_engine, support_count
from nabiz.console.report_outcome_api import find_outcome, outcome_view
from nabiz.console.requests_api import citizen_view, request_desk
from nexus_core.signals import system_clock

log = logging.getLogger("nabiz.console.notices_center_api")
notices_center_routes = APIRouter()


class NoticeTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["metro_line", "station", "bus_line", "knowledge"]
    value: str = Field(min_length=1, max_length=60)


class NoticesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topics: list[NoticeTopic] = Field(default_factory=list, max_length=ACCOUNT_FOLLOW_LIMIT)
    requests: list[str] = Field(default_factory=list, max_length=10, description="Device-held request codes")
    reports: list[str] = Field(default_factory=list, max_length=10, description="Device-held report codes")


class CalendarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["topic", "request", "report"]
    topic: NoticeTopic | None = None
    code: str | None = Field(default=None, max_length=16)
    item_id: str = Field(pattern=r"^n_[0-9a-f]{16}$")
    lang: Literal["tr", "en"] = "tr"

    @model_validator(mode="after")
    def source_matches_reference(self) -> CalendarIn:
        if (self.source == "topic") != (self.topic is not None):
            raise ValueError("topic is required only for topic items")
        if (self.source != "topic") != (self.code is not None):
            raise ValueError("code is required only for request and report items")
        return self


def _now(request: Request):
    clock = getattr(request.app.state, "notices_clock", None)
    return clock() if callable(clock) else utcnow()


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _problem(response: Response, status: int, kind: str, message: str) -> JSONResponse:
    result = port_problem(status, kind, message)
    result.headers["Cache-Control"] = "no-store"
    response.headers["Cache-Control"] = "no-store"
    return result


def _report_now(request: Request):
    clock = getattr(request.app.state, "report_clock", system_clock)
    return clock()


async def _topic_items(request: Request, topics: list[NoticeTopic]) -> tuple[list[Notice], list[dict[str, Any]]]:
    items: list[Notice] = []
    unavailable: list[dict[str, Any]] = []
    checked: list[tuple[int, Any]] = []
    for index, raw_topic in enumerate(topics):
        try:
            checked.append((index, topic_from(raw_topic.kind, raw_topic.value)))
        except ValueError as exc:
            raise _FollowTopicError(str(exc)) from exc
    nabiz = getattr(request.app.state, "nabiz", None)
    if nabiz is None and topics:
        unavailable.extend({
            "source": "topic", "ref_index": index, "label": topic.label,
            "text_tr": "Kaynak şu an okunamadı; değişiklik kontrol edilemedi.",
        } for index, topic in checked)
        return items, unavailable
    for index, topic in checked:
        found, missing = await topic_notices(nabiz, topic, index)
        items.extend(found)
        if missing is not None:
            unavailable.append(missing)
    return items, unavailable


class _FollowTopicError(ValueError):
    pass


def _request_unavailable(index: int) -> dict[str, Any]:
    return {
        "source": "request",
        "ref_index": index,
        "label": "Operatör talebi",
        "text_tr": "Talep durumu şu an okunamadı; değişiklik kontrol edilemedi.",
    }


def _report_unavailable(index: int) -> dict[str, Any]:
    return {
        "source": "report",
        "ref_index": index,
        "label": "Asansör bildirimi",
        "text_tr": "Bildirim durumu şu an okunamıyor; karar çekirdeği bağlı değil.",
    }


async def _request_items(request: Request, codes: list[str], now: Any) -> tuple[list[Notice], list[dict[str, Any]], int]:
    items: list[Notice] = []
    unavailable: list[dict[str, Any]] = []
    skipped = 0
    for index, raw in enumerate(codes):
        code = normal_code(raw)
        if code is None:
            skipped += 1
            continue
        try:
            row = await asyncio.to_thread(request_desk(request.app).store.get, code)
        except Exception as exc:  # noqa: BLE001 - do not turn a failed read into a missing request
            log.warning("notices request store unavailable: %s", type(exc).__name__)
            unavailable.append(_request_unavailable(index))
            continue
        if row is not None:
            items.append(request_notice(citizen_view(row), index, now))
    return items, unavailable, skipped


async def _report_items(request: Request, codes: list[str]) -> tuple[list[Notice], list[dict[str, Any]], int]:
    items: list[Notice] = []
    unavailable: list[dict[str, Any]] = []
    skipped = 0
    engine = report_engine(request) if codes else None
    for index, raw in enumerate(codes):
        code = normal_code(raw)
        if code is None:
            skipped += 1
            continue
        if engine is None:
            unavailable.append(_report_unavailable(index))
            continue
        try:
            state = await asyncio.to_thread(find_outcome, engine, code)
            if state is None:
                continue
            support = support_count(engine, state.signal.signal_id)
            view = outcome_view(state, support, engine.ttl_hours, _report_now(request))
        except Exception as exc:  # noqa: BLE001 - preserve the difference between unavailable and absent
            log.warning("notices report source unavailable: %s", type(exc).__name__)
            unavailable.append(_report_unavailable(index))
            continue
        items.append(report_notice(view, index))
    return items, unavailable, skipped


async def _collect(request: Request, body: NoticesIn) -> tuple[list[Notice], list[dict[str, Any]], int, Any]:
    now = _now(request)
    topics, topic_unavailable = await _topic_items(request, body.topics)
    requests, request_unavailable, bad_requests = await _request_items(request, body.requests, now)
    reports, report_unavailable, bad_reports = await _report_items(request, body.reports)
    return (
        sort_notices([*topics, *requests, *reports]),
        [*topic_unavailable, *request_unavailable, *report_unavailable],
        bad_requests + bad_reports,
        now,
    )


@notices_center_routes.post("/api/notices")
async def read_notices(request: Request, body: NoticesIn, response: Response) -> Any:
    """Read supplied topics and device codes for this response only; nothing is retained."""
    try:
        items, unavailable, skipped, now = await _collect(request, body)
    except _FollowTopicError as exc:
        return _problem(response, 400, "follow_topic", str(exc))
    _no_store(response)
    log.info(
        "notices topics=%d requests=%d reports=%d items=%d",
        len(body.topics), len(body.requests), len(body.reports), len(items),
    )
    return {
        "items": [item.public() for item in items],
        "unavailable": unavailable,
        "skipped": skipped,
        "checked_at": now.isoformat(timespec="seconds"),
        "disclaimer": NOT_OFFICIAL,
    }


async def _calendar_notice(request: Request, body: CalendarIn, now: Any) -> Notice | None:
    if body.source == "topic":
        assert body.topic is not None
        try:
            topic = topic_from(body.topic.kind, body.topic.value)
        except ValueError as exc:
            raise _FollowTopicError(str(exc)) from exc
        nabiz = getattr(request.app.state, "nabiz", None)
        if nabiz is None:
            return None
        items, _ = await topic_notices(nabiz, topic, 0)
        return next((item for item in items if item.id == body.item_id), None)
    assert body.code is not None
    code = normal_code(body.code)
    if code is None:
        raise _InvalidCodeError
    if body.source == "request":
        row = await asyncio.to_thread(request_desk(request.app).store.get, code)
        if row is None:
            return None
        notice = request_notice(citizen_view(row), 0, now)
        return notice if notice.id == body.item_id else None
    engine = report_engine(request)
    if engine is None:
        raise _NotWiredError
    state = await asyncio.to_thread(find_outcome, engine, code)
    if state is None:
        return None
    view = outcome_view(state, support_count(engine, state.signal.signal_id), engine.ttl_hours, _report_now(request))
    notice = report_notice(view, 0)
    return notice if notice.id == body.item_id else None


class _InvalidCodeError(ValueError):
    pass


class _NotWiredError(RuntimeError):
    pass


@notices_center_routes.post("/api/notices/calendar")
async def download_calendar(request: Request, body: CalendarIn, response: Response) -> Any:
    """Rebuild one current notice and return its reminder as an attachment."""
    now = _now(request)
    try:
        item = await _calendar_notice(request, body, now)
    except _FollowTopicError as exc:
        return _problem(response, 400, "follow_topic", str(exc))
    except _InvalidCodeError:
        return _problem(response, 422, "invalid_code", "Kod tanınmadı.")
    except _NotWiredError:
        return _problem(response, 503, "not_wired", "Bildirim durumu şu an okunamıyor; karar çekirdeği bağlı değil.")
    except Exception as exc:  # noqa: BLE001 - the response must not reveal codes or internal details
        log.warning("notices calendar source unavailable: %s", type(exc).__name__)
        return _problem(response, 404, "notice_gone", "Bu güncelleme artık kayıtta yok; listeyi yenileyin.")
    if item is None:
        return _problem(response, 404, "notice_gone", "Bu güncelleme artık kayıtta yok; listeyi yenileyin.")
    event = calendar_event(item, now=now, lang=body.lang)
    if event is None:
        return _problem(response, 422, "no_calendar", "Bu güncelleme için takvim hatırlatıcısı yok.")
    _no_store(response)
    headers = {
        "Content-Disposition": 'attachment; filename="nabiz-hatirlatici.ics"',
        "Cache-Control": "no-store",
    }
    return Response(calendar_text([event], now=now), media_type="text/calendar; charset=utf-8", headers=headers)
