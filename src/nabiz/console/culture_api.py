"""Recorded İBB library and museum hours for a district selected by the visitor."""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.text import fold_tr
from nabiz.console.cards import display_text
from nabiz.console.operator import port_problem
from nexus_core.stats import ISTANBUL

log = logging.getLogger("nabiz.console.culture")

CULTURE_DIR = REPO_ROOT / "data" / "reference" / "ibb_kultur"
SOURCES = {
    "library": ("kutuphaneler", "Kutuphane Adi"),
    "museum": ("muzeler", "Muze Adi"),
}
FIELD_NAMES = ("Ilce Adi", "Acilis Yili", "Adres", "Telefon", "Calisma Saatleri", "Calisma Gunleri")
DAY_NAMES = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
DAY_INDEX = {fold_tr(name): index for index, name in enumerate(DAY_NAMES)}
HOURS_PATTERN = re.compile(r"([0-2]?\d)[:.]([0-5]\d)\s*-\s*([0-2]?\d)[:.]([0-5]\d)")
WEEKDAY_RANGE = re.compile(r"([a-z]+)\s*-\s*([a-z]+)")
#: The library capture spells one district two ways ("K.Çekmece" beside "Küçükçekmece"); the selector
#: shows the district once and both spellings match it. The record itself is not rewritten.
DISTRICT_ALIASES = {fold_tr("K.Çekmece"): "Küçükçekmece"}
#: The selector lists districts in Turkish alphabetical order (Ç after C, Ş after S, Ü after U).
TR_ALPHABET = "abcçdefgğhıijklmnoöprsştuüvwxyz"
TR_LOWER = str.maketrans({"I": "ı", "İ": "i", "â": "a", "Â": "a", "î": "i", "Î": "i", "û": "u", "Û": "u"})

NOTES = (
    "Doluluk bilgisi yok: İBB kütüphane ve müze doluluğunu açık veri olarak yayımlamıyor.",
    "Resmî tatil ve özel kapanışlar kayıtta yok; gitmeden önce arayın.",
    "Bu kayıtlarda konum yok; haritada gösterilemiyor.",
)
DISCLAIMER = "Resmî İBB hizmeti değildir."


@dataclass(frozen=True)
class Venue:
    kind: Literal["library", "museum"]
    name: str
    district: str | None
    address: str | None
    phones: tuple[str, ...]
    hours_text: str | None
    days_text: str | None
    opening_year: str | None


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _phones(value: Any) -> tuple[str, ...]:
    raw = _clean(value)
    if raw is None:
        return ()
    result: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if fold_tr(line).startswith("dahili:"):
            if result:
                result[-1] = f"{result[-1]} {line}"
            continue
        result.append(line)
    return tuple(result)


@lru_cache(maxsize=4)
def load_venues(directory: Path = CULTURE_DIR) -> tuple[list[Venue], dict[str, Any]]:
    """Read the captured files verbatim; a missing or changed source stays unavailable."""
    venues: list[Venue] = []
    metadata: dict[str, Any] = {}
    for kind, (stem, name_field) in SOURCES.items():
        path = Path(directory) / f"{stem}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        fields = payload.get("fields")
        available_fields = {item.get("id") for item in fields if isinstance(item, dict)} if isinstance(fields, list) else set()
        if not {name_field, *FIELD_NAMES} <= available_fields:
            continue
        records = payload.get("records")
        if not isinstance(records, list):
            continue
        metadata[kind] = {
            "captured_at": payload.get("captured_at"),
            "resource_last_modified": payload.get("resource_last_modified"),
            "license_title": payload.get("license_title"),
            "package_id": payload.get("package_id"),
        }
        for record in records:
            if not isinstance(record, dict) or (name := _clean(record.get(name_field))) is None:
                continue
            venues.append(
                Venue(
                    kind=kind,  # type: ignore[arg-type]
                    name=name,
                    district=_clean(record.get("Ilce Adi")),
                    address=_clean(record.get("Adres")),
                    phones=_phones(record.get("Telefon")),
                    hours_text=_clean(record.get("Calisma Saatleri")),
                    days_text=_clean(record.get("Calisma Gunleri")),
                    opening_year=_clean(record.get("Acilis Yili")),
                )
            )
    return venues, metadata


def parse_days(text: str | None) -> frozenset[int] | None:
    """Return recognized weekdays only; unknown wording never becomes an assumed schedule."""
    folded = fold_tr(text).casefold()
    if folded in {"hergun", "her gun"}:
        return frozenset(range(7))
    if "hafta ici" in folded and "hafta sonu" in folded and "kapali" in folded:
        return frozenset(range(5))
    match = WEEKDAY_RANGE.fullmatch(folded)
    if match is None or match.group(1) not in DAY_INDEX or match.group(2) not in DAY_INDEX:
        return None
    start, end = DAY_INDEX[match.group(1)], DAY_INDEX[match.group(2)]
    if end < start:
        return None
    return frozenset(range(start, end + 1))


def parse_hours(text: str | None) -> tuple[dt.time, dt.time] | Literal["always"] | None:
    """Parse the source's clock interval or its explicit round-the-clock value."""
    value = (text or "").strip()
    if fold_tr(value) == "7/24":
        return "always"
    match = HOURS_PATTERN.search(value)
    if match is None:
        return None
    start_hour, start_minute, end_hour, end_minute = (int(part) for part in match.groups())
    if start_hour > 23 or end_hour > 23:
        return None
    start = dt.time(start_hour, start_minute)
    end = dt.time(end_hour, end_minute)
    return (start, end) if end > start else None


def district_name(raw: str | None) -> str | None:
    """The district as the selector shows it: the record's spelling unless it is a known abbreviation."""
    if raw is None:
        return None
    return DISTRICT_ALIASES.get(fold_tr(raw), raw)


def turkish_order(name: str) -> tuple[int, ...]:
    """Sort key for Turkish alphabetical order; a character outside the alphabet sorts after it."""
    return tuple(TR_ALPHABET.find(char) if char in TR_ALPHABET else 100 + ord(char) for char in name.translate(TR_LOWER).lower())


def _schedule(venue: Venue) -> tuple[frozenset[int] | None, tuple[dt.time, dt.time] | Literal["always"] | None]:
    days = parse_days(venue.days_text)
    hours = parse_hours(venue.hours_text) or parse_hours(venue.days_text)
    return days, hours


def _local(now_local: dt.datetime) -> dt.datetime:
    return now_local.replace(tzinfo=ISTANBUL) if now_local.tzinfo is None else now_local.astimezone(ISTANBUL)


def _next_opening(days: frozenset[int], opening: dt.time, now_local: dt.datetime) -> dt.datetime | None:
    now = _local(now_local)
    for offset in range(8):
        day = now.date() + dt.timedelta(days=offset)
        if day.weekday() not in days:
            continue
        candidate = dt.datetime.combine(day, opening, tzinfo=ISTANBUL)
        if candidate > now:
            return candidate
    return None


def venue_state(venue: Venue, now_local: dt.datetime) -> dict[str, Any]:
    """Describe the recorded schedule at an İstanbul-local instant."""
    days, hours = _schedule(venue)
    if hours == "always":
        return {"state": "open", "text": "Kayda göre 7/24 açık", "closes_at": None, "opens_next": None, "opens_on": None}
    if days is None or hours is None:
        return {"state": "unknown", "text": "Çalışma saati kayıtta yok", "closes_at": None, "opens_next": None, "opens_on": None}
    now = _local(now_local)
    opening, closing = hours
    if now.weekday() in days and opening <= now.time() < closing:
        closes = closing.strftime("%H.%M")
        return {
            "state": "open",
            "text": f"Kayda göre şu an açık · kapanış {closes}",
            "closes_at": closes,
            "opens_next": None,
            "opens_on": None,
        }
    next_open = _next_opening(days, opening, now)
    if next_open is None:
        return {"state": "unknown", "text": "Çalışma saati kayıtta yok", "closes_at": None, "opens_next": None, "opens_on": None}
    today = next_open.date() == now.date()
    day_text = "bugün" if today else DAY_NAMES[next_open.weekday()]
    opens = next_open.strftime("%H.%M")
    return {
        "state": "closed",
        "text": f"Kayda göre şu an kapalı · açılış {day_text} {opens}",
        "closes_at": None,
        "opens_next": f"{day_text} {opens}",
        # The same moment without Turkish words, so the page can say it in its own language.
        "opens_on": {"weekday": next_open.weekday(), "today": today, "time": opens},
    }


def _utc_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=dt.UTC) if parsed.tzinfo is None else parsed.astimezone(dt.UTC)


def _now_local() -> dt.datetime:
    return dt.datetime.now(ISTANBUL)


def _provenance(metadata: dict[str, Any], now_utc: dt.datetime) -> dict[str, Any]:
    observed = _utc_timestamp(metadata.get("resource_last_modified"))
    package_id = metadata.get("package_id")
    return {
        "source": "ibb_open_data",
        "url": f"https://data.ibb.gov.tr/dataset/{package_id}" if package_id else None,
        "observed_at": metadata.get("resource_last_modified") if observed else None,
        "age_s": max(0, int((now_utc - observed).total_seconds())) if observed else None,
        "mode": "recorded",
        "captured_at": metadata.get("captured_at"),
        "license_title": metadata.get("license_title"),
    }


def _sort_key(item: tuple[Venue, dict[str, Any]], now_local: dt.datetime) -> tuple[Any, ...]:
    venue, state = item
    if state["state"] == "open":
        return (0, state["closes_at"] or "99.99", fold_tr(venue.name))
    if state["state"] == "closed":
        days, hours = _schedule(venue)
        opening = hours[0] if isinstance(hours, tuple) else dt.time.max
        candidate = _next_opening(days or frozenset(), opening, now_local)
        return (1, candidate or dt.datetime.max.replace(tzinfo=ISTANBUL), fold_tr(venue.name))
    return (2, fold_tr(venue.name))


def _display(value: str | None) -> str | None:
    return display_text(value) if value is not None else None


culture_routes = APIRouter()


@culture_routes.get("/api/culture")
async def culture(
    district: str = Query("", max_length=40),
    kinds: str = Query("library,museum", max_length=20),
) -> Any:
    selected = [part.strip().lower() for part in kinds.split(",") if part.strip()]
    if not selected or any(kind not in SOURCES for kind in selected):
        return port_problem(422, "bad_kinds", display_text("Kütüphane ya da müze türünü seçin."))
    selected = list(dict.fromkeys(selected))
    all_venues, metadata = load_venues(Path(CULTURE_DIR))
    districts_by_key: dict[str, str] = {}
    for item in all_venues:
        if (name := district_name(item.district)) is not None:
            districts_by_key.setdefault(fold_tr(name), name)
    districts = sorted(districts_by_key.values(), key=turkish_order)
    canonical = districts_by_key.get(fold_tr(district_name(district))) if district else None
    if district and districts and canonical is None:
        return port_problem(422, "unknown_district", display_text("Bu ilçe adı kayıtlarda yok."))

    now_local = _now_local()
    now_utc = now_local.astimezone(dt.UTC)
    venues: list[dict[str, Any]] = []
    ranked: list[tuple[Venue, dict[str, Any]]] = []
    if canonical:
        ranked = [
            (venue, venue_state(venue, now_local))
            for venue in all_venues
            if venue.kind in selected and fold_tr(district_name(venue.district)) == fold_tr(canonical)
        ]
        ranked.sort(key=lambda entry: _sort_key(entry, now_local))
        for venue, state in ranked[:40]:
            venues.append(
                {
                    "kind": venue.kind,
                    "kind_tr": _display("Kütüphane" if venue.kind == "library" else "Müze"),
                    "name": _display(venue.name),
                    "district": _display(district_name(venue.district)),
                    "address": _display(venue.address),
                    "phones": [_display(phone) for phone in venue.phones],
                    "hours_text": _display(venue.hours_text),
                    "days_text": _display(venue.days_text),
                    "opening_year": _display(venue.opening_year),
                    "state": state["state"],
                    "state_text": _display(state["text"]),
                    "closes_at": state["closes_at"],
                    "opens_next": state["opens_next"],
                    "opens_on": state["opens_on"],
                }
            )

    counts = {
        "total": len(ranked),
        "open": sum(state["state"] == "open" for _, state in ranked),
        "closed": sum(state["state"] == "closed" for _, state in ranked),
        "unknown": sum(state["state"] == "unknown" for _, state in ranked),
    }
    provenance = {kind: _provenance(metadata[kind], now_utc) for kind in selected if kind in metadata}
    log.info("culture request kinds=%s matched=%s", ",".join(selected), len(venues))
    result: dict[str, Any] = {
        "district": _display(canonical),
        "now_local": now_local.isoformat(),
        "kinds": selected,
        "districts": [_display(name) for name in districts],
        "venues": venues,
        "counts": counts,
        "notes": [_display(note) for note in NOTES],
        "provenance_by_kind": provenance,
        "license": _display("İBB Açık Veri Lisansı") if metadata else None,
        "captured_at": {kind: item.get("captured_at") for kind, item in metadata.items()},
        "disclaimer": _display(DISCLAIMER),
    }
    if not metadata:
        result["note"] = _display("Kütüphane ve müze kaydı bu sunucuda yok.")
    return result
