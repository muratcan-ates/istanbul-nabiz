"""İETT source: live bus positions and planned departure times (SOAP).

Three upstream operations live here, all behind the shared cache:

* ``GetHatOtoKonum_json`` — every vehicle currently running one line,
* ``GetFiloAracKonum_json`` — the whole fleet (6911 vehicles on 2026-09-08) in one shot,
* ``GetPlanlananSeferSaati_json`` — the timetable for one line.

Why the caching is not optional: İETT documents a hard limit of 100 requests per hour
for this service (``PoliteClient`` budgets us to 80) and the gateway 503s every İBB
service after a burst, so a user question must map to a cache read, never to an upstream
call — and a stale read is surfaced as stale, not replaced with an invented number.

The fleet payload carries a number plate (``Plaka``); ``BusPosition.from_fleet_raw``
drops it before it reaches this module (see NOTICE.md).
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Callable, Iterable, Sequence
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from ibb_mcp.cache import CacheEntry
from ibb_mcp.config import (
    IETT_ACTION_FLEET_POSITIONS,
    IETT_ACTION_LINE_POSITIONS,
    IETT_ACTION_SCHEDULE,
    IETT_FLEET_ASMX,
    IETT_SCHEDULE_ASMX,
)
from ibb_mcp.models import (
    ISTANBUL_TZ,
    BusPosition,
    PlannedDeparture,
    Provenance,
    day_type_for,
    utcnow,
)
from ibb_mcp.sources.base import SourceContext, make_provenance

log = logging.getLogger("ibb_mcp.sources.iett")

#: Timetables change a few times a year, so one day of caching is generous.
SCHEDULE_TTL_SECONDS = 86_400.0

#: İETT line codes are short and alphanumeric ("500T", "15F", "E-10", "34AS"). We both
#: validate against this and XML-escape, because the code arrives from user input and is
#: interpolated into a SOAP body.
LINE_CODE_RE = re.compile(r"^[A-Z0-9ÇĞİÖŞÜ][A-Z0-9ÇĞİÖŞÜ._-]{0,15}$")

#: İETT day-type codes; see ``models.DAY_TYPE_LABELS``.
DAY_TYPES = frozenset({"I", "C", "P"})

# Turkish dotted/dotless I folding: casefold() alone maps "I" to "i", which is wrong for
# Turkish ("ISTANBUL" should fold to "ıstanbul", "İSTANBUL" to "istanbul").
_TR_FOLD = str.maketrans({"İ": "i", "I": "ı", "Î": "i", "Û": "u", "Â": "a"})

# People type terminus names without diacritics ("sifa" for "ŞİFA") and punctuate them
# differently ("4. Levent" vs the feed's "4.LEVENT METRO"), so we compare on a
# deaccented, punctuation-free variant as well.
_ASCII_FOLD = str.maketrans("ıİşŞğĞüÜöÖçÇâîû", "iissgguuooccaiu")
_PUNCT_RE = re.compile(r"[\s.,\-/()']+")

#: Day-type aliases keyed by :func:`_fold_key`, never by ``.upper()``: Python upper-cases
#: "hafta içi" to "HAFTA IÇI" (ASCII rules), which matches neither the dotted "HAFTA İÇİ"
#: nor the plain "HAFTA ICI" spelling a table would list.
#:
#: The weekday names are spelled out rather than folded to a first letter, because the
#: first letter lies in Turkish: "Pazartesi" is Monday and "Cuma" is Friday — both are
#: ordinary weekdays ("I"), but their initials are the codes for Sunday and Saturday.
_DAY_TYPE_ALIASES = {
    "i": "I", "c": "C", "p": "P",
    "haftaici": "I", "icgunu": "I", "weekday": "I", "weekdays": "I",
    "pazartesi": "I", "monday": "I",
    "sali": "I", "tuesday": "I",
    "carsamba": "I", "wednesday": "I",
    "persembe": "I", "thursday": "I",
    "cuma": "I", "friday": "I",
    "cumartesi": "C", "saturday": "C",
    "pazar": "P", "sunday": "P",
}


def _fold_key(text: str) -> str:
    """Accent-, case- and punctuation-insensitive lookup key for the alias tables."""
    return _PUNCT_RE.sub("", " ".join(str(text).split()).translate(_ASCII_FOLD).casefold())


# --------------------------------------------------------------------------------------
# normalisation helpers
# --------------------------------------------------------------------------------------
def normalise_line_code(line_code: str) -> str:
    """Upper-case and strip a line code, rejecting anything that is not one.

    Rejecting early keeps a malformed code from spending one of the 100 requests/hour.
    """
    code = "".join(str(line_code or "").split()).upper()
    if not code:
        raise ValueError("Hat kodu boş olamaz (örn. '500T').")
    if not LINE_CODE_RE.match(code):
        raise ValueError(f"Geçersiz hat kodu: {line_code!r}")
    return code


def normalise_day_type(day_type: str | None) -> str | None:
    """Map a day-type argument to İETT's single-letter code, or ``None`` for 'any'."""
    if day_type is None:
        return None
    key = _fold_key(day_type)
    if not key:
        return None
    resolved = _DAY_TYPE_ALIASES.get(key)
    if resolved is None:
        # Deliberately no "first letter wins" fallback: it would answer "pazartesi"
        # (Monday) with Sunday's timetable and "cuma" (Friday) with Saturday's — a wrong
        # answer that looks right. An unknown word is refused instead.
        raise ValueError(f"Bilinmeyen gün tipi: {day_type!r} (I=hafta içi, C=cumartesi, P=pazar)")
    return resolved


def departure_minutes(value: str | None) -> int | None:
    """Minutes-from-midnight for a ``DT`` value, keeping after-midnight runs ordered.

    İETT counts services past midnight into the previous service day: ``24:30`` means
    00:30 tomorrow. Returning 1470 rather than 30 keeps the timetable sorted and lets a
    23:50 query still see that run.
    """
    if not value:
        return None
    parts = str(value).strip().split(":")
    if len(parts) < 2:
        return None
    try:
        hours, minutes = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if hours < 0 or not 0 <= minutes < 60 or hours > 47:
        return None
    return hours * 60 + minutes


def _fold_variants(text: str) -> set[str]:
    """Comparable forms of a string: plain, Turkish dotted-I aware, and deaccented."""
    base = " ".join(str(text).split())
    turkish = base.translate(_TR_FOLD).casefold()
    ascii_only = _PUNCT_RE.sub("", base.translate(_ASCII_FOLD).casefold())
    return {base.casefold(), turkish, ascii_only} - {""}


def buses_towards(buses: Sequence[BusPosition], direction_hint: str | None) -> list[BusPosition]:
    """Keep the buses heading towards ``direction_hint`` ("Kadıköy", "4. Levent", "G"/"D").

    The live feed's ``yon`` is a free-text terminus name, so this is a contains match on
    both Turkish and ASCII foldings. A bare ``G``/``D`` is matched against the route code
    segment instead (``500T_G_D0``), which is how the GTFS join identifies a direction.

    Returns an empty list when nothing matches — callers must say "eşleşen sefer yok"
    rather than falling back to the other direction.
    """
    if direction_hint is None:
        return list(buses)
    hint = " ".join(str(direction_hint).split())
    if not hint:
        return list(buses)

    if len(hint) == 1 and hint.upper() in {"G", "D"}:
        letter = hint.upper()
        return [b for b in buses if letter in (b.route_code or "").upper().split("_")[1:]]

    wanted = _fold_variants(hint)
    matched: list[BusPosition] = []
    for bus in buses:
        haystack = _fold_variants(bus.direction or "")
        if any(w and w in h for w in wanted for h in haystack):
            matched.append(bus)
    return matched


# --------------------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------------------
def _parse_records(
    raw: Any,
    parser: Callable[[dict[str, Any]], Any],
    *,
    what: str,
) -> list[Any]:
    """Parse a list payload, skipping records we cannot read instead of failing the call."""
    if not isinstance(raw, list):
        log.warning("iett/%s: beklenen liste yerine %s geldi", what, type(raw).__name__)
        return []
    parsed: list[Any] = []
    for record in raw:
        if not isinstance(record, dict):
            continue
        try:
            parsed.append(parser(record))
        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the whole payload
            log.warning("iett/%s: kayıt çözümlenemedi (%s)", what, exc)
    return parsed


def _latest_report(buses: Iterable[BusPosition], *, now: dt.datetime | None = None) -> dt.datetime | None:
    """The newest *plausible* vehicle timestamp — what the agent quotes as 'son konum'.

    The fleet feed sends a bare clock ("23:03:07"), which ``parse_ibb_datetime`` can only
    date as today, so a bus parked since last night lands hours in the future. Taking a
    plain maximum would then clamp the age to zero and make hours-old data look live, so
    stamps ahead of now are dropped instead of trusted.
    """
    horizon = (now or utcnow()) + dt.timedelta(minutes=2)
    stamps = [b.reported_at for b in buses if b.reported_at is not None and b.reported_at <= horizon]
    return max(stamps) if stamps else None


def _redate_future_clocks(buses: Sequence[BusPosition], *, now: dt.datetime | None = None) -> list[BusPosition]:
    """Move a fleet timestamp that lands in the future back one day.

    ``GetFiloAracKonum_json`` sends a bare clock (``Saat``: "23:03:07") with no date, so
    ``parse_ibb_datetime`` can only read it as *today* — and a vehicle whose last report
    was before midnight then carries a timestamp hours ahead of now. Downstream that reads
    as an age of zero, i.e. a bus parked since last night looks live. A clock ahead of us
    can only belong to yesterday, so it is dated as such; the two-minute tolerance leaves
    ordinary clock skew between İETT and us alone.
    """
    horizon = (now or utcnow()) + dt.timedelta(minutes=2)
    return [
        bus.model_copy(update={"reported_at": bus.reported_at - dt.timedelta(days=1)})
        if bus.reported_at is not None and bus.reported_at > horizon
        else bus
        for bus in buses
    ]


def _line_of(record: dict[str, Any]) -> str:
    return str(record.get("hatkodu") or record.get("SHATKODU") or "").strip().upper()


# --------------------------------------------------------------------------------------
# source
# --------------------------------------------------------------------------------------
class IettSource:
    """Live and planned İETT bus data. One instance per process, sharing the context."""

    def __init__(self, ctx: SourceContext) -> None:
        self.ctx = ctx

    # -- live positions ----------------------------------------------------------------
    async def line_positions(self, line_code: str) -> tuple[list[BusPosition], Provenance]:
        """Every vehicle currently reporting on one line."""
        code = normalise_line_code(line_code)
        buses, entry = await self.ctx.cached(
            f"iett:line:{code}",
            lambda: self._fetch_line_positions(code),
            source="iett_line",
        )
        return list(buses), make_provenance(
            "iett_line", entry=entry, reported_at=_latest_report(buses), url=IETT_FLEET_ASMX
        )

    async def _fetch_line_positions(self, code: str) -> list[BusPosition]:
        if self.ctx.settings.offline:
            raw = [r for r in self.ctx.load_fixture("iett_hat_500T") if _line_of(r) == code]
            if not raw:
                log.info("offline: 'iett_hat_500T' fixture'ında %s hattı yok", code)
        else:
            body = (
                f"<{IETT_ACTION_LINE_POSITIONS} xmlns='http://tempuri.org/'>"
                f"<HatKodu>{xml_escape(code)}</HatKodu>"
                f"</{IETT_ACTION_LINE_POSITIONS}>"
            )
            raw = await self.ctx.client.post_soap_json(
                IETT_FLEET_ASMX,
                source="iett_line",
                action=IETT_ACTION_LINE_POSITIONS,
                body_xml=body,
                budget="iett",
            )
        buses = _parse_records(raw, BusPosition.from_line_raw, what=IETT_ACTION_LINE_POSITIONS)
        return [b for b in buses if b.door_no]

    async def fleet_positions(self) -> tuple[list[BusPosition], Provenance]:
        """The whole fleet in one call.

        One request feeds every caller, where per-line queries spend the hourly budget a
        line at a time. These records carry no line code: join on door number or position.
        """
        buses, entry = await self.ctx.cached(
            "iett:fleet",
            self._fetch_fleet_positions,
            source="iett_fleet",
        )
        return list(buses), make_provenance(
            "iett_fleet", entry=entry, reported_at=_latest_report(buses), url=IETT_FLEET_ASMX
        )

    async def _fetch_fleet_positions(self) -> list[BusPosition]:
        if self.ctx.settings.offline:
            raw = self.ctx.load_fixture("iett_fleet")
        else:
            raw = await self.ctx.client.post_soap_json(
                IETT_FLEET_ASMX,
                source="iett_fleet",
                action=IETT_ACTION_FLEET_POSITIONS,
                body_xml=f"<{IETT_ACTION_FLEET_POSITIONS} xmlns='http://tempuri.org/' />",
                budget="iett",
            )
        buses = _parse_records(raw, BusPosition.from_fleet_raw, what=IETT_ACTION_FLEET_POSITIONS)
        return _redate_future_clocks([b for b in buses if b.door_no])

    # -- timetable ---------------------------------------------------------------------
    async def schedule(
        self, line_code: str, day_type: str | None = None
    ) -> tuple[list[PlannedDeparture], Provenance]:
        """Planned departures for a line, optionally for one day type only.

        The whole timetable is cached under one key and filtered afterwards, so asking
        for Saturday after asking for a weekday costs no extra upstream request.
        """
        code = normalise_line_code(line_code)
        wanted = normalise_day_type(day_type)
        departures, entry = await self._schedule_all(code)
        if wanted is not None:
            departures = [d for d in departures if (d.day_type or "").upper() == wanted]
        return list(departures), make_provenance("iett_schedule", entry=entry, url=IETT_SCHEDULE_ASMX)

    async def _schedule_all(self, code: str) -> tuple[list[PlannedDeparture], CacheEntry[Any]]:
        return await self.ctx.cached(
            f"iett:sched:{code}",
            lambda: self._fetch_schedule(code),
            source="iett_schedule",
            ttl=SCHEDULE_TTL_SECONDS,
        )

    async def _fetch_schedule(self, code: str) -> list[PlannedDeparture]:
        if self.ctx.settings.offline:
            raw = [r for r in self.ctx.load_fixture("iett_planlanan") if _line_of(r) == code]
            if not raw:
                log.info("offline: 'iett_planlanan' fixture'ında %s hattı yok", code)
        else:
            body = (
                f"<{IETT_ACTION_SCHEDULE} xmlns='http://tempuri.org/'>"
                f"<HatKodu>{xml_escape(code)}</HatKodu>"
                f"</{IETT_ACTION_SCHEDULE}>"
            )
            raw = await self.ctx.client.post_soap_json(
                IETT_SCHEDULE_ASMX,
                source="iett_schedule",
                action=IETT_ACTION_SCHEDULE,
                body_xml=body,
                budget="iett",
            )
        return _parse_records(raw, PlannedDeparture.from_raw, what=IETT_ACTION_SCHEDULE)

    async def next_scheduled_departures(
        self,
        line_code: str,
        route_code: str | None = None,
        after: dt.datetime | None = None,
        limit: int = 3,
    ) -> list[PlannedDeparture]:
        """The next planned departures for the day type that ``after`` falls in.

        ``after`` defaults to now; a naive datetime is read as Istanbul local time, which
        is what the timetable itself is expressed in. When the day's remaining departures
        run out, the list continues with the next day's first ones, so a late-evening
        question still gets an answer instead of an empty list.

        Three service days are considered, in departure order: yesterday's after-midnight
        tail (İETT files a 00:30 run as the previous day's ``24:30``, so just past midnight
        those are still the next buses), then today, then tomorrow.
        """
        if limit <= 0:
            return []
        code = normalise_line_code(line_code)
        moment = after or utcnow()
        local = moment.replace(tzinfo=ISTANBUL_TZ) if moment.tzinfo is None else moment.astimezone(ISTANBUL_TZ)

        departures, _ = await self._schedule_all(code)
        pool = departures
        if route_code:
            wanted_route = str(route_code).strip().upper()
            pool = [d for d in pool if (d.route_code or "").upper() == wanted_route]

        now_minutes = local.hour * 60 + local.minute
        picked: list[PlannedDeparture] = []

        def take(day: dt.datetime, *, at_or_after: int) -> None:
            for departure, minutes in _sorted_for_day(pool, day_type_for(day)):
                if len(picked) >= limit:
                    return
                if minutes >= at_or_after and departure not in picked:
                    picked.append(departure)

        # Yesterday's 24:xx/25:xx runs depart *today*, after midnight. Skipping them makes
        # a 00:05 question answer with the morning's first bus while the 00:30 one is still
        # to come; ``+ 24 * 60`` puts yesterday's clock on the same axis as ours.
        take(local - dt.timedelta(days=1), at_or_after=24 * 60 + now_minutes)
        take(local, at_or_after=now_minutes)
        take(local + dt.timedelta(days=1), at_or_after=0)
        return picked


def _sorted_for_day(
    departures: Iterable[PlannedDeparture], day_type: str
) -> list[tuple[PlannedDeparture, int]]:
    """Departures of one day type as ``(departure, minutes)`` pairs, in time order."""
    pairs = []
    for departure in departures:
        if (departure.day_type or "").upper() != day_type:
            continue
        minutes = departure_minutes(departure.departure_time)
        if minutes is not None:
            pairs.append((departure, minutes))
    pairs.sort(key=lambda pair: pair[1])
    return pairs
