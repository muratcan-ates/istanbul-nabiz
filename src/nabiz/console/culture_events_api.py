"""HTTP contracts for source bounded citizen event planning."""
from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any, Literal

from fastapi import APIRouter, Query, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from nabiz.console.cards import display_text
from nabiz.console.culture_api import DISCLAIMER, load_venues, turkish_order
from nabiz.console.culture_events import (
    TYPE_LABELS_EN,
    CultureEvent,
    events_on,
    load_culture_events,
    nearby_venues_for,
    plan_calendar_text,
    venue_hours_for,
)
from nabiz.console.operator import port_problem
from nexus_core.stats import ISTANBUL

culture_events_routes = APIRouter()
log = logging.getLogger("nabiz.console.events")
_EVENT_ID = re.compile(r"^ev_[0-9a-f]{12}$")
class EventCalendarIn(BaseModel):
    """Validated input for a calendar download."""
    id: str = Field(pattern=r"^ev_[0-9a-f]{12}$")
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    lang: Literal["tr", "en"] = "tr"
def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
def _problem(status: int, kind: str, message: str) -> JSONResponse:
    result = port_problem(status, kind, display_text(message))
    result.headers["Cache-Control"] = "no-store"
    return result
def _now() -> dt.datetime:
    return dt.datetime.now(ISTANBUL)
def _parse_day(raw: str | None, today: dt.date) -> dt.date | None:
    if not raw:
        return today
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        return None
def _stale(captured_at: Any, now: dt.datetime) -> bool:
    if not isinstance(captured_at, str):
        return True
    try:
        captured = dt.datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=dt.UTC)
    return now.astimezone(dt.UTC) - captured.astimezone(dt.UTC) > dt.timedelta(days=7)
def _districts(events: list[CultureEvent]) -> list[str]:
    return sorted({event.district for event in events if event.district}, key=turkish_order)
def _event_view(event: CultureEvent) -> dict[str, Any]:
    types = []
    for index, slug in enumerate(event.type_slugs):
        name = event.types[index] if index < len(event.types) else slug
        types.append({"slug": slug, "name_tr": display_text(name), "name_en": TYPE_LABELS_EN.get(slug)})
    return {
        "id": event.id,
        "title": display_text(event.title),
        "link": event.link,
        "date_text": display_text(event.date_text),
        "time": event.start_time.strftime("%H:%M") if event.start_time else None,
        "venue": display_text(event.venue),
        "district": display_text(event.district) if event.district else None,
        "types": types,
        "free": "ucretsiz" in event.type_slugs,
        "sold_out": "tukendi" in event.type_slugs,
    }
def _source(meta: dict[str, Any], now: dt.datetime) -> dict[str, Any]:
    return {
        "name": display_text(str(meta.get("source") or "Kültür AŞ · kultur.istanbul")),
        "url": str(meta.get("source_url") or "https://kultur.istanbul/"),
        "captured_at": meta.get("captured_at"),
        "stale": _stale(meta.get("captured_at"), now),
        "license_note": display_text(str(meta.get("license_note") or "")),
        "not_captured": meta.get("not_captured") if isinstance(meta.get("not_captured"), list) else [],
    }
def _selection(
    raw_date: str | None, raw_district: str | None, audience: str, free: str, response: Response,
) -> tuple[dt.date, dt.datetime, list[CultureEvent], dict[str, Any], list[str], dict[str, int]] | JSONResponse:
    now = _now()
    today = now.date()
    day = _parse_day(raw_date, today)
    if day is None or day < today or day > today + dt.timedelta(days=30):
        return _problem(422, "bad_date", "Bugünden 30 gün sonrasına kadar bir tarih seçin.")
    if audience not in {"all", "child", "adult"}:
        return _problem(422, "bad_audience", "Kimle seçimini denetleyin.")
    if free not in {"0", "1"}:
        return _problem(422, "bad_free", "Ücretsiz filtresini denetleyin.")
    events, meta = load_culture_events()
    if meta.get("status") == "no_data" or not events:
        return (day, now, events, meta, [], {"past": 0, "cancelled": 0, "started": 0,
                                              "undated": 0, "unparsed": 0})
    districts = _districts(events)
    if raw_district and raw_district not in districts:
        return _problem(422, "unknown_district", "İlçe kaynakta bulunamadı.")
    selected, hidden = events_on(
        events, day, today, now.time().replace(tzinfo=None), district=raw_district or None,
        audience=audience, free_only=free == "1",
    )
    hidden["undated"] = int(meta.get("undated", 0) or 0)
    hidden["unparsed"] = int(meta.get("unparsed", 0) or 0)
    _no_store(response)
    return day, now, selected, meta, districts, hidden
@culture_events_routes.get("/api/events")
async def _list_events(
    response: Response,
    date: str | None = Query(default=None),
    district: str | None = Query(default=None),
    audience: str = Query(default="all", alias="with"),
    free: str = Query(default="0"),
) -> Any:
    """Return the captured event cards available for one plan day."""
    selection = _selection(date, district, audience, free, response)
    if isinstance(selection, JSONResponse):
        return selection
    day, now, selected, meta, districts, hidden = selection
    if meta.get("status") == "no_data" or not selected and not meta.get("captured_at"):
        _no_store(response)
        return {"status": "no_data", "message": "Etkinlik verisi henüz yok."}
    log.info("events date=%s matched=%d hidden=%d", day.isoformat(), len(selected), sum(hidden.values()))
    return {
        "status": "ok", "date": day.isoformat(), "today": now.date().isoformat(),
        "events": [_event_view(event) for event in selected], "hidden": hidden,
        "districts": districts, "source": _source(meta, now), "disclaimer": DISCLAIMER,
    }
def _find_selected(event_id: str, day: dt.date, now: dt.datetime, events: list[CultureEvent]) -> CultureEvent | None:
    selected, _ = events_on(events, day, now.date(), now.time().replace(tzinfo=None))
    return next((event for event in selected if event.id == event_id), None)
@culture_events_routes.get("/api/events/day")
async def _event_day(
    response: Response,
    id: str = Query(...),
    date: str = Query(...),
) -> Any:
    """Return plan details for a source event on a valid day."""
    now = _now()
    today = now.date()
    day = _parse_day(date, today)
    if day is None or day < today or day > today + dt.timedelta(days=30):
        return _problem(422, "bad_date", "Bugünden 30 gün sonrasına kadar bir tarih seçin.")
    if not _EVENT_ID.fullmatch(id):
        return _problem(422, "bad_event_id", "Etkinlik bağlantısını denetleyin.")
    events, meta = load_culture_events()
    event = _find_selected(id, day, now, events)
    if event is None:
        return _problem(404, "event_gone", "Bu etkinlik artık kaynakta yok ya da bu tarihte sürmüyor.")
    _no_store(response)
    venue_hours = venue_hours_for(event, day)
    nearby = nearby_venues_for(event.district, day)
    notes = ["Mekân erişim bilgisi kaynakta yok.", "Yaş aralığı kaynakta yok; kurumun etiketi kullanılır."]
    venue_sources = []
    if venue_hours or nearby:
        notes.append("Resmî tatil ve özel kapanışlar kayıtta yok; gitmeden önce arayın.")
    if venue_hours or nearby:
        _, venue_data = load_venues()
        kinds = {row["kind"] for row in nearby}
        if venue_hours:
            kinds.add(venue_hours["kind"])
        venue_sources = [{"kind": kind, "resource_last_modified": venue_data[kind].get("resource_last_modified")}
                         for kind in sorted(kinds) if kind in venue_data and venue_data[kind].get("resource_last_modified")]
    return {"event": _event_view(event), "venue_hours": venue_hours, "nearby": nearby, "notes": notes,
            "venue_sources": venue_sources}
@culture_events_routes.post("/api/events/calendar")
async def _event_calendar(body: EventCalendarIn, response: Response) -> Any:
    """Download a personal-data-free calendar file for one captured event."""
    if not _EVENT_ID.fullmatch(body.id):
        return _problem(422, "bad_event_id", "Etkinlik bağlantısını denetleyin.")
    try:
        day = dt.date.fromisoformat(body.date)
    except ValueError:
        return _problem(422, "bad_date", "Takvim için etkinlik tarihini denetleyin.")
    now = _now()
    if day < now.date() or day > now.date() + dt.timedelta(days=30):
        return _problem(422, "bad_date", "Bugünden 30 gün sonrasına kadar bir tarih seçin.")
    events, meta = load_culture_events()
    event = _find_selected(body.id, day, now, events)
    if event is None:
        return _problem(404, "event_gone", "Bu etkinlik artık kaynakta yok ya da bu tarihte sürmüyor.")
    _no_store(response)
    content = plan_calendar_text(event, day, body.lang, now.astimezone(dt.UTC), str(meta.get("captured_at") or ""))
    return PlainTextResponse(content, media_type="text/calendar; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="nabiz-gun-plani.ics"',
                                       "Cache-Control": "no-store"})
