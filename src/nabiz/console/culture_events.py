"""Source bounded event planning for the citizen page."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.text import fold_tr
from nabiz.console.culture_api import (
    CULTURE_DIR,
    DISCLAIMER,
    Venue,
    district_name,
    load_venues,
    parse_days,
    parse_hours,
    turkish_order,
)

PATH_ENV = "NABIZ_EVENTS_PATH"
EVENTS_PATH = REPO_ROOT / "data" / "reference" / "etkinlik" / "etkinlikler.json"
DATE_PATTERN = re.compile(r"^(\d{2}-\d{2}-\d{4})(?: (\d{2}:\d{2}))?(?: - (\d{2}-\d{2}-\d{4}))?$")
TR_DAY_NAMES = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
TYPE_LABELS_EN = {
    "konser": "Concert", "sergi": "Exhibition", "tiyatro": "Theatre", "performans": "Performance",
    "deneyim": "Experience", "imza-gunu": "Book signing", "okur-yazar-bulusmasi": "Reader meet-up",
    "soylesi": "Talk", "atolye": "Workshop", "festival": "Festival", "film-gosterimi": "Film screening",
    "gezi": "Tour", "masal": "Storytelling", "muzikal": "Musical", "bale": "Ballet", "dinleti": "Recital",
    "drama": "Drama", "fuar": "Fair", "seminer": "Seminar", "stand-up": "Stand-up",
    "cocuklar-icin-2": "For children", "yetiskinler-icin": "For adults", "ucretsiz": "Free",
    "satista": "Tickets on sale", "tukendi": "Sold out",
}


@dataclass(frozen=True)
class CultureEvent:
    """One dated event card as captured from the source homepage."""

    id: str
    title: str
    link: str
    date_text: str
    venue: str
    types: tuple[str, ...]
    type_slugs: tuple[str, ...]
    start: dt.date | None
    end: dt.date | None
    start_time: dt.time | None
    district: str | None


def culture_event_id(link: str) -> str:
    """Stable, opaque identifier derived only from the source link."""
    return "ev_" + hashlib.sha256(link.encode("utf-8")).hexdigest()[:12]


def parse_event_dates(text: str) -> tuple[dt.date, dt.date, dt.time | None] | None:
    """Parse only the date and time formats present in the captured event cards."""
    match = DATE_PATTERN.fullmatch((text or "").strip())
    if match is None:
        return None
    try:
        start = dt.datetime.strptime(match.group(1), "%d-%m-%Y").date()
        end = dt.datetime.strptime(match.group(3), "%d-%m-%Y").date() if match.group(3) else start
        parsed_time = dt.datetime.strptime(match.group(2), "%H:%M").time() if match.group(2) else None
    except ValueError:
        return None
    return (start, end, parsed_time) if end >= start else None


def _name_key(value: str | None) -> str:
    return " ".join(fold_tr(value or "").split())


def _district_index() -> dict[str, str | None]:
    candidates: dict[str, set[str]] = defaultdict(set)
    venues, _ = load_venues(CULTURE_DIR)
    for venue in venues:
        district = district_name(venue.district)
        if district and _name_key(venue.name):
            candidates[_name_key(venue.name)].add(district)
    path = REPO_ROOT / "data" / "reference" / "places.csv"
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                name, district = row.get("name", "").strip(), row.get("district", "").strip()
                if name and district:
                    candidates[_name_key(name)].add(district_name(district) or district)
    except OSError:
        pass
    return {key: next(iter(values)) if len(values) == 1 else None for key, values in candidates.items()}


def venue_district(name: str) -> str | None:
    """Return a district only when a captured venue name matches exactly after Turkish folding."""
    return _district_index().get(_name_key(name))


def load_culture_events(path: str | Path | None = None) -> tuple[list[CultureEvent], dict[str, Any]]:
    """Read the owner's capture without caching or filling fields that were absent."""
    source_path = Path(path) if path is not None else Path(os.environ.get(PATH_ENV, "") or EVENTS_PATH)
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return [], {"status": "no_data"}
    if not isinstance(payload, dict) or not isinstance(payload.get("home_events"), list):
        return [], {"status": "no_data"}
    home = payload["home_events"]
    listed = payload.get("listings") if isinstance(payload.get("listings"), list) else []
    home_links = {str(item.get("link")) for item in home if isinstance(item, dict) and item.get("link")}
    undated = sum(1 for item in listed if isinstance(item, dict) and item.get("link") and str(item["link"]) not in home_links)
    events: list[CultureEvent] = []
    unparsed = 0
    districts = _district_index()
    for item in home:
        if not isinstance(item, dict):
            continue
        link = str(item.get("link") or "").strip()
        title = str(item.get("title") or "").strip()
        date_text = str(item.get("date_text") or "").strip()
        parsed_link = urlsplit(link)
        if (parsed_link.scheme != "https" or parsed_link.hostname not in {"kultur.istanbul", "www.kultur.istanbul"}
                or not title or not date_text):
            unparsed += 1
            continue
        dates = parse_event_dates(date_text)
        if dates is None:
            unparsed += 1
        types = item.get("types") if isinstance(item.get("types"), list) else []
        slugs = item.get("type_slugs") if isinstance(item.get("type_slugs"), list) else []
        events.append(CultureEvent(
            id=culture_event_id(link), title=title, link=link, date_text=date_text,
            venue=str(item.get("venue") or "").strip(),
            types=tuple(str(value) for value in types if isinstance(value, str) and value.strip()),
            type_slugs=tuple(str(value) for value in slugs if isinstance(value, str) and value.strip()),
            start=dates[0] if dates else None, end=dates[1] if dates else None,
            start_time=dates[2] if dates else None, district=districts.get(_name_key(str(item.get("venue") or ""))),
        ))
    metadata = {
        "captured_at": payload.get("captured_at"), "source": payload.get("source"),
        "source_url": payload.get("source_url"), "license_note": payload.get("license_note"),
        "not_captured": payload.get("not_captured", []), "undated": undated, "unparsed": unparsed,
    }
    return events, metadata


def _hidden_reason(event: CultureEvent, day: dt.date, today: dt.date, now_time: dt.time) -> str | None:
    if event.start is None or event.end is None:
        return "unparsed"
    if event.end < day:
        return "past"
    if not event.start <= day <= event.end:
        return "outside"
    slugs = set(event.type_slugs)
    if slugs.intersection({"iptal", "ertelendi"}):
        return "cancelled"
    if day == today and event.start == event.end and event.start_time and event.start_time <= now_time:
        return "started"
    return None


def _matches_event(event: CultureEvent, district: str | None, audience: str, free_only: bool) -> bool:
    slugs = set(event.type_slugs)
    if audience == "child" and not any(slug.startswith("cocuklar-icin") for slug in slugs):
        return False
    if audience == "adult" and "yetiskinler-icin" not in slugs:
        return False
    if free_only and "ucretsiz" not in slugs:
        return False
    return not district or event.district == district


def events_on(
    events: list[CultureEvent], day: dt.date, today: dt.date, now_time: dt.time, *,
    district: str | None = None, audience: str = "all", free_only: bool = False,
) -> tuple[list[CultureEvent], dict[str, int]]:
    """Select dated source events for a plan day and count the reasons other events were hidden."""
    hidden = {"past": 0, "cancelled": 0, "started": 0, "undated": 0, "unparsed": 0}
    selected: list[CultureEvent] = []
    if day < today:
        return selected, hidden
    for event in events:
        reason = _hidden_reason(event, day, today, now_time)
        if reason in hidden:
            hidden[reason] += 1
        if reason is not None:
            continue
        if _matches_event(event, district, audience, free_only):
            selected.append(event)
    selected.sort(key=lambda event: (event.start_time is None, event.start_time or dt.time.max, turkish_order(event.title)))
    return selected, hidden


def _event_venue(event: CultureEvent) -> Venue | None:
    matches = [venue for venue in load_venues(CULTURE_DIR)[0] if _name_key(venue.name) == _name_key(event.venue)]
    return matches[0] if len(matches) == 1 else None


def _venue_hours(venue: Venue, day: dt.date) -> dict[str, Any]:
    days = parse_days(venue.days_text)
    hours = parse_hours(venue.hours_text) or parse_hours(venue.days_text)
    opens: str | None = None
    closes: str | None = None
    if hours == "always":
        opens, closes, open_on_day = "7/24", "7/24", True
    elif days is not None and day.weekday() not in days:
        open_on_day = False
    elif days is not None and isinstance(hours, tuple):
        opens, closes, open_on_day = hours[0].strftime("%H:%M"), hours[1].strftime("%H:%M"), True
    else:
        open_on_day = None
    return {"name": venue.name, "kind": venue.kind, "hours_text": venue.hours_text, "days_text": venue.days_text,
            "open_on_day": open_on_day, "opens": opens, "closes": closes}


def venue_hours_for(event: CultureEvent, day: dt.date) -> dict[str, Any] | None:
    """Read a plan-day schedule only for an exact E30 venue name."""
    venue = _event_venue(event)
    if venue is None:
        return None
    return _venue_hours(venue, day)


def nearby_venues_for(district: str | None, day: dt.date) -> list[dict[str, Any]]:
    """List up to three E30 venues in the same known district that are recorded open that day."""
    if not district:
        return []
    matches = []
    for venue in load_venues(CULTURE_DIR)[0]:
        venue_district_name = district_name(venue.district)
        if not venue_district_name or fold_tr(venue_district_name) != fold_tr(district):
            continue
        hours = _venue_hours(venue, day)
        if hours["open_on_day"] is True:
            matches.append({"name": venue.name, "kind": venue.kind, "opens": hours["opens"],
                            "closes": hours["closes"], "address": venue.address})
    return sorted(matches, key=lambda row: (row["opens"] or "", turkish_order(row["name"])))[:3]


def _ical_escape(value: str) -> str:
    return (value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n")
            .replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,"))


def _fold_ical_line(line: str) -> list[str]:
    result: list[str] = []
    current = ""
    limit = 75
    for char in line:
        size = len(char.encode("utf-8"))
        if current and len(current.encode("utf-8")) + size > limit:
            result.append(current)
            current, limit = " " + char, 75
        else:
            current += char
    result.append(current)
    return result


def plan_calendar_text(
    event: CultureEvent, day: dt.date, lang: str, now_utc: dt.datetime, captured_at: str = "",
) -> str:
    """Build one personal-data-free iCalendar entry with RFC line folding."""
    stamp = now_utc.replace(tzinfo=dt.UTC) if now_utc.tzinfo is None else now_utc.astimezone(dt.UTC)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//istanbul-nabiz//dayplan//{'EN' if lang == 'en' else 'TR'}",
             "CALSCALE:GREGORIAN", "BEGIN:VEVENT", f"UID:{event.id}-{day.isoformat()}@istanbul-nabiz",
             f"DTSTAMP:{stamp:%Y%m%dT%H%M%SZ}"]
    if event.start_time:
        local = dt.datetime.combine(day, event.start_time, tzinfo=ZoneInfo("Europe/Istanbul"))
        lines.append(f"DTSTART:{local.astimezone(dt.UTC):%Y%m%dT%H%M%SZ}")
    else:
        lines.append(f"DTSTART;VALUE=DATE:{day:%Y%m%d}")
    lines.extend([f"SUMMARY:{_ical_escape(event.title)}", f"URL:{_ical_escape(event.link)}"])
    if lang == "en":
        description = (f"Venue: {event.venue}\nEvent information was captured from kultur.istanbul on {captured_at}; "
                       "check the event page before going.\nThis is not an official Istanbul Metropolitan Municipality service.")
    else:
        description = (f"Mekân: {event.venue}\nEtkinlik bilgisi kultur.istanbul'dan {captured_at} tarihinde alındı; "
                       "gitmeden önce etkinlik sayfasını kontrol edin.\n" + DISCLAIMER)
    lines.extend([f"DESCRIPTION:{_ical_escape(description)}", "END:VEVENT", "END:VCALENDAR"])
    return "\r\n".join(part for line in lines for part in _fold_ical_line(line)) + "\r\n"
