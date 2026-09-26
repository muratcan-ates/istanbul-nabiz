"""Read Metro notice and equipment history from the local lake."""

from __future__ import annotations

import datetime as dt
import gzip
import json
import logging
import os
import pathlib
import time
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request

from ibb_mcp.http import RateLimitExceeded, UpstreamUnavailable
from ibb_mcp.models import utcnow
from ibb_mcp.text import fold_tr, squash_punctuation
from nabiz.console.cards import display_text
from nexus_core.stats import ISTANBUL

METRO_SOURCE = "metro_status"
EQUIPMENT_SOURCE = "metro_equipment_snapshot"
READ_WINDOW_DAYS = 35
CACHE_TTL_S = 300.0
GONE_WINDOW = dt.timedelta(days=7)
FAULT_CLASSES = frozenset({"fault", "revision", "not_operated"})

log = logging.getLogger("nabiz.console.notice_age")
notice_routes = APIRouter(prefix="/api/console")
_UNREADABLE = (RateLimitExceeded, UpstreamUnavailable)
_ROWS_CACHE: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}


@dataclass(frozen=True)
class Seen:
    """A notice or equipment record observed in distinct local snapshots."""

    key: str
    line: str | None
    description: str | None
    first_seen: dt.datetime
    last_seen: dt.datetime
    seen_reads: int
    total_reads: int
    read_days: tuple[dt.date, ...]
    ibb_dates: tuple[dt.datetime, ...]


def _utc(value: dt.datetime) -> dt.datetime:
    return (value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value).astimezone(dt.UTC)


def _parse_utc(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return _utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _utc(dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def _iso(value: dt.datetime | None) -> str | None:
    return _utc(value).isoformat() if value is not None else None


def _row_stamp(row: dict[str, Any]) -> dt.datetime | None:
    return _parse_utc(row.get("snapshot_ts_utc"))


def _snapshot_stamps(rows: list[dict[str, Any]]) -> list[dt.datetime]:
    return sorted({stamp for row in rows if (stamp := _row_stamp(row)) is not None})


def lake_root() -> pathlib.Path:
    """Return the configured local lake directory."""
    return pathlib.Path(os.getenv("NABIZ_LAKE_DIR", "data/lake")).expanduser()


def _partition_day(path: pathlib.Path) -> dt.date | None:
    parts: dict[str, str] = {}
    for part in path.parts:
        name, separator, value = part.partition("=")
        if separator and name in {"year", "month", "day"}:
            parts[name] = value
    try:
        return dt.date(int(parts["year"]), int(parts["month"]), int(parts["day"]))
    except (KeyError, ValueError):
        return None


def _read_rows(source: str, root: pathlib.Path, *, since: dt.date) -> list[dict[str, Any]]:
    """Read recent source rows, skipping old or malformed partitions before opening them."""
    source_root = root / source
    if not source_root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(source_root.rglob("*.ndjson.gz")):
        partition_day = _partition_day(path)
        if partition_day is None or partition_day < since:
            continue
        try:
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if isinstance(value, dict):
                        rows.append(value)
        except (OSError, EOFError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            log.warning("notice lake partition unreadable: %s", type(exc).__name__)
    return rows


# Keep the requested reader API while avoiding a second public ``read_rows`` definition.
read_rows = _read_rows


def cached_rows(source: str, *, now: dt.datetime) -> list[dict[str, Any]]:
    """Return a source's rows from a five-minute, lake-root-aware cache."""
    root = lake_root()
    key = (str(root), source)
    cached = _ROWS_CACHE.get(key)
    tick = time.monotonic()
    if cached is not None and tick - cached[0] < CACHE_TTL_S:
        return cached[1]
    rows = read_rows(source, root, since=(_utc(now) - dt.timedelta(days=READ_WINDOW_DAYS)).date())
    _ROWS_CACHE[key] = (tick, rows)
    return rows


def clear_cache() -> None:
    """Clear cached rows between requests in tests."""
    _ROWS_CACHE.clear()


def notice_key(line: str | None, description: str | None) -> str:
    return f"{(line or '').upper()}|{squash_punctuation(fold_tr(description))}"


def _read_days(stamps: list[dt.datetime]) -> tuple[dt.date, ...]:
    return tuple(sorted({stamp.astimezone(ISTANBUL).date() for stamp in stamps}))


def metro_history(rows: list[dict[str, Any]]) -> dict[str, Seen]:
    """Group each notice by line and text, counting a snapshot only once."""
    reads = _snapshot_stamps(rows)
    found: dict[str, dict[dt.datetime, dict[str, Any]]] = {}
    dates: dict[str, set[dt.datetime]] = {}
    for row in rows:
        if row.get("has_notice") is not True or (stamp := _row_stamp(row)) is None:
            continue
        line = row.get("line_name") if isinstance(row.get("line_name"), str) else None
        description = row.get("description") if isinstance(row.get("description"), str) else None
        key = notice_key(line, description)
        found.setdefault(key, {})[stamp] = {"line": line, "description": description}
        if ibb_date := _parse_utc(row.get("ts_utc")):
            dates.setdefault(key, set()).add(ibb_date)
    history: dict[str, Seen] = {}
    for key, by_read in found.items():
        stamps = sorted(by_read)
        first = stamps[0]
        total = sum(stamp >= first for stamp in reads)
        history[key] = Seen(
            key=key,
            line=by_read[first]["line"],
            description=by_read[first]["description"],
            first_seen=first,
            last_seen=stamps[-1],
            seen_reads=len(stamps),
            total_reads=total,
            read_days=_read_days([stamp for stamp in reads if stamp >= first]),
            ibb_dates=tuple(sorted(dates.get(key, set()))),
        )
    return history


def ibb_sentence(updated_at: dt.datetime | None) -> str:
    if updated_at is None:
        return ""
    day = _utc(updated_at).astimezone(ISTANBUL)
    return display_text(
        f"İBB bu bildirimi en son {day:%d.%m.%Y} tarihinde güncelledi; bildirim en az bu tarihten beri yayında. "
        "Başlangıç tarihi yayımlanmıyor, bitiş tahmini yok."
    )


def archive_sentence(seen: Seen | None) -> str:
    if seen is None or not seen.read_days:
        return ""
    first, last = seen.read_days[0], seen.read_days[-1]
    count = len(seen.read_days)
    span = (last - first).days + 1
    if count == 1:
        opening = f"Nabız {first:%d.%m.%Y} tarihinde {seen.total_reads} kez okudu; "
    else:
        opening = f"Nabız {first:%d.%m.%Y} ile {last:%d.%m.%Y} arasında {count} gün okudu; "
    if seen.seen_reads == seen.total_reads:
        body = f"{seen.total_reads} okumanın hepsinde bildirim yayındaydı."
    else:
        body = f"{seen.total_reads} okumadan {seen.seen_reads} tanesinde bildirim yayındaydı."
    gap = " Okumalar her gün yapılmadı." if count < span else ""
    return display_text(opening + body + gap)


def since_text(updated_at: dt.datetime | None, seen: Seen | None) -> str:
    return display_text(" ".join(part for part in (ibb_sentence(updated_at), archive_sentence(seen)) if part))


def _station_key(value: str) -> str:
    return squash_punctuation(fold_tr(value))


def _equipment_fault(row: dict[str, Any]) -> bool:
    return (
        row.get("has_record") is True
        and bool(row.get("station_name"))
        and row.get("status_class") in FAULT_CLASSES
        and row.get("equipment_type") == "elevator"
    )


def equipment_seen(rows: list[dict[str, Any]], station: str, ibb_date_raw: str) -> Seen | None:
    """Match an archived lift by station and exact İBB date, never by the non-unique code."""
    wanted = _station_key(station)
    dated = [(stamp, row) for row in rows if (stamp := _row_stamp(row)) is not None]
    station_stamps = [stamp for stamp, row in dated if isinstance(row.get("station_name"), str)
                      and _station_key(row["station_name"]) == wanted and row.get("equipment_type") == "elevator"]
    matching = [
        (stamp, row) for stamp, row in dated
        if _equipment_fault(row)
        and _station_key(str(row["station_name"])) == wanted
        and row.get("ibb_date_raw") == ibb_date_raw
    ]
    if not matching or not station_stamps:
        return None
    matching_stamps = sorted({stamp for stamp, _ in matching})
    first_station = min(station_stamps)
    latest_read = max(stamp for stamp, _ in dated)
    total = sum(first_station <= stamp <= latest_read for stamp in {stamp for stamp, _ in dated})
    days = _read_days(matching_stamps)
    key = f"{wanted}|{ibb_date_raw}"
    return Seen(
        key=key,
        line=None,
        description=None,
        first_seen=matching_stamps[0],
        last_seen=matching_stamps[-1],
        seen_reads=len(matching_stamps),
        total_reads=total,
        read_days=days,
        ibb_dates=tuple(sorted({parsed for _, row in matching if (parsed := _parse_utc(row.get("ibb_date"))) is not None})),
    )


def _ibb_day(value: Any) -> dt.date | None:
    if not isinstance(value, str) or not value:
        return None
    if len(value) == 10:
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    stamp = _parse_utc(value)
    return stamp.astimezone(ISTANBUL).date() if stamp is not None else None


def equipment_date_sentence(date_label: str | None, records: list[dict[str, Any]]) -> str:
    """Format distinct İBB elevator record dates using the label returned by the facade."""
    if not date_label:
        return ""
    days = sorted({day for item in records if (day := _ibb_day(item.get("ibb_date"))) is not None})[:3]
    if not days:
        return ""
    dates = ", ".join(day.strftime("%d.%m.%Y") for day in days)
    return display_text(f"{date_label}: {dates}.")


def equipment_archive_sentence(rows: list[dict[str, Any]], station: str, ibb_date_raw: str) -> str:
    """Format a matched lift's first and last archive observations."""
    seen = equipment_seen(rows, station, ibb_date_raw)
    if seen is None:
        return ""
    first = seen.first_seen.astimezone(ISTANBUL)
    if seen.seen_reads == seen.total_reads:
        return display_text(
            f"Nabız'ın ekipman arşivinde bu kayıt en az {first:%d.%m.%Y %H.%M} tarihinden beri var "
            f"({seen.total_reads} okumadan {seen.seen_reads} tanesinde)."
        )
    # Some reads missed the record, so "en az ... beri var" would claim a presence the archive does not show.
    return display_text(
        f"Nabız'ın ekipman arşivi bu kaydı ilk kez {first:%d.%m.%Y %H.%M} tarihinde gördü; "
        f"o tarihten beri {seen.total_reads} okumadan {seen.seen_reads} tanesinde var."
    )


def equipment_sentences(data: dict[str, Any], station: str, *, now: dt.datetime) -> list[str]:
    """Return the İBB record date and any matching local archive observations."""
    records = [item for item in data.get("records") or [] if item.get("equipment_type") == "elevator"]
    sentences = []
    if sentence := equipment_date_sentence(data.get("date_label"), records):
        sentences.append(sentence)
    raw_dates = {
        item["ibb_date_raw"] for item in records
        if isinstance(item.get("ibb_date_raw"), str) and item["ibb_date_raw"]
    }
    if not raw_dates:
        return sentences
    try:
        rows = cached_rows(EQUIPMENT_SOURCE, now=now)
    except Exception as exc:  # noqa: BLE001 - okunamayan arşivde yalnız İBB tarihi kalır
        log.warning("equipment archive unreadable: %s", type(exc).__name__)
        return sentences
    for raw_date in sorted(raw_dates):
        if sentence := equipment_archive_sentence(rows, station, raw_date):
            sentences.append(sentence)
    return sentences


def _notice_data(line: str | None, description: str | None, updated_at: dt.datetime | None, seen: Seen | None) -> dict[str, Any]:
    return {
        "line": line,
        "description": description,
        "ibb_updated_at": _iso(updated_at),
        "first_seen": _iso(seen.first_seen) if seen else None,
        "last_seen": _iso(seen.last_seen) if seen else None,
        "seen_reads": seen.seen_reads if seen else 0,
        "total_reads": seen.total_reads if seen else 0,
        "read_days": [day.isoformat() for day in seen.read_days] if seen else [],
        "since_text": since_text(updated_at, seen),
    }


def _current_notices(lines: list[dict[str, Any]], history: dict[str, Seen]) -> tuple[list[dict[str, Any]], set[str]]:
    notices: list[dict[str, Any]] = []
    keys: set[str] = set()
    for item in lines:
        line = item.get("line_name") if isinstance(item.get("line_name"), str) else None
        description = item.get("description") if isinstance(item.get("description"), str) else None
        key = notice_key(line, description)
        keys.add(key)
        updated = _parse_utc(item.get("updated_at"))
        notices.append(_notice_data(line, description, updated, history.get(key)))
    return notices, keys


def _archive_notices(history: dict[str, Seen]) -> list[dict[str, Any]]:
    return [
        _notice_data(seen.line, seen.description, seen.ibb_dates[-1] if seen.ibb_dates else None, seen)
        for seen in sorted(history.values(), key=lambda one: (one.line or "", one.description or ""))
    ]


def _gone_notices(
    history: dict[str, Seen], current_keys: set[str], latest_read: dt.datetime | None, now: dt.datetime
) -> list[dict[str, Any]]:
    if latest_read is None:
        return []
    cutoff = _utc(now) - GONE_WINDOW
    gone = [
        _notice_data(seen.line, seen.description, seen.ibb_dates[-1] if seen.ibb_dates else None, seen)
        for key, seen in history.items()
        if key not in current_keys and cutoff <= seen.last_seen < latest_read
    ]
    return sorted(gone, key=lambda item: (item["line"] or "", item["description"] or ""))


def _archive_summary(metro_rows: list[dict[str, Any]], equipment_rows: list[dict[str, Any]]) -> dict[str, Any]:
    metro_reads = _snapshot_stamps(metro_rows)
    # "Readable" is what the note promises: a row that names its station. Fault rows are a subset.
    readable = sum(isinstance(row.get("station_name"), str) and bool(row["station_name"].strip()) for row in equipment_rows)
    return {
        "metro_reads": len(metro_reads),
        "metro_days": len(_read_days(metro_reads)),
        "first_read": _iso(metro_reads[0]) if metro_reads else None,
        "last_read": _iso(metro_reads[-1]) if metro_reads else None,
        "equipment_rows": len(equipment_rows),
        "equipment_readable_rows": readable,
    }


def _archive_lifts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs = sorted({
        (str(row["station_name"]), str(row["ibb_date_raw"]))
        for row in rows
        if _equipment_fault(row) and isinstance(row.get("ibb_date_raw"), str) and row["ibb_date_raw"]
    })
    lifts = []
    for station, ibb_date_raw in pairs:
        seen = equipment_seen(rows, station, ibb_date_raw)
        if seen is not None:
            lifts.append({
                "station": station,
                "ibb_date_raw": ibb_date_raw,
                "first_seen": _iso(seen.first_seen),
                "last_seen": _iso(seen.last_seen),
                "seen_reads": seen.seen_reads,
                "total_reads": seen.total_reads,
            })
    return lifts


@notice_routes.get("/metro-notices")
async def metro_notices(request: Request) -> dict[str, Any]:
    """Summarize current Metro notices and the local, discontinuous observation archive."""
    now = utcnow()
    metro_rows = cached_rows(METRO_SOURCE, now=now)
    equipment_rows = cached_rows(EQUIPMENT_SOURCE, now=now)
    history = metro_history(metro_rows)
    try:
        result = await request.app.state.nabiz.metro_status()
        lines = result.data.get("lines") or []
        current_readable = True
    except _UNREADABLE as exc:
        log.warning("metro notice source unreadable: %s", type(exc).__name__)
        lines, current_readable = [], False
    current, current_keys = _current_notices(lines, history) if current_readable else ([], set())
    notices = current if current_readable else _archive_notices(history)
    stamps = _snapshot_stamps(metro_rows)
    archive = _archive_summary(metro_rows, equipment_rows)
    root = lake_root()
    archive_exists = any((root / source).exists() for source in (METRO_SOURCE, EQUIPMENT_SOURCE))
    note = "" if archive_exists else "Nabız'ın arşivi bu sunucuda yok; yalnız İBB'nin son güncelleme tarihi gösteriliyor."
    if archive["equipment_readable_rows"] == 0:
        equipment_note = "Ekipman arşivinde istasyon adı taşıyan kayıt yok; asansör için süre hesaplanmadı."
        note = f"{note} {equipment_note}".strip()
    return {
        "current_readable": current_readable,
        "notices": notices,
        "gone": _gone_notices(history, current_keys, stamps[-1] if stamps else None, now) if current_readable else [],
        "lifts": _archive_lifts(equipment_rows),
        "archive": archive,
        "note": display_text(note),
    }
