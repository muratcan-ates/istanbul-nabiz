"""Small, dependency-free RFC 5545 writer for calendar reminders."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    """A personal-data-free calendar event with only the fields this product needs."""

    uid: str
    start: dt.datetime
    minutes: int
    summary: str
    description: str
    url: str | None = None
    alarm: bool = True

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.start.utcoffset() is None:
            raise ValueError("CalendarEvent.start must be timezone-aware")
        if type(self.minutes) is not int or not 1 <= self.minutes <= 240:
            raise ValueError("CalendarEvent.minutes must be an integer from 1 to 240")


def escape_text(value: str) -> str:
    """Escape a TEXT value as required by RFC 5545 section 3.3.11."""
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\r" or char == "\n":
            if char == "\r" and index + 1 < len(value) and value[index + 1] == "\n":
                index += 1
            result.append("\\n")
        elif char == "\\":
            result.append("\\\\")
        elif char == ";":
            result.append("\\;")
        elif char == ",":
            result.append("\\,")
        elif ord(char) >= 32 and ord(char) != 127:
            result.append(char)
        index += 1
    return "".join(result)


def fold_line(line: str) -> str:
    """Fold a content line at UTF-8 octet boundaries, with a leading space on continuations."""
    physical: list[str] = []
    current = ""
    octets = 0
    for char in line:
        size = len(char.encode("utf-8"))
        if octets + size > 75:
            physical.append(current)
            current = " "
            octets = 1
        current += char
        octets += size
    physical.append(current)
    return "\r\n".join(physical)


def _utc_stamp(value: dt.datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("calendar timestamps must be timezone-aware")
    return value.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    return value if parsed.scheme.lower() in {"http", "https"} and parsed.netloc else None


def calendar_text(events: list[CalendarEvent] | tuple[CalendarEvent, ...], *, now: dt.datetime) -> str:
    """Serialize events with CRLF endings, UTC dates, and no unsupported personal fields."""
    stamp = _utc_stamp(now)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Istanbul Nabiz//Guncellemeler 1.0//TR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for event in events:
        lines.extend(
            (
                "BEGIN:VEVENT",
                f"UID:{escape_text(event.uid)}",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{_utc_stamp(event.start)}",
                f"DURATION:PT{event.minutes}M",
                f"SUMMARY:{escape_text(event.summary)}",
                f"DESCRIPTION:{escape_text(event.description)}",
            )
        )
        if safe_url := _safe_url(event.url):
            lines.append(f"URL:{escape_text(safe_url)}")
        if event.alarm:
            lines.extend(
                (
                    "BEGIN:VALARM",
                    "ACTION:DISPLAY",
                    "TRIGGER:PT0M",
                    f"DESCRIPTION:{escape_text(event.summary)}",
                    "END:VALARM",
                )
            )
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_line(line) for line in lines) + "\r\n"
