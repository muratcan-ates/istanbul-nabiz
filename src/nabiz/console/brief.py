"""``GET /api/brief``: the home page's city cards, each with its source, its age and who wrote it.

What the page asks for comes from the person's own device (saved stations and lines, and
the functional needs of their profile); nothing here stores it. The cards:

- ``metro_status``: Metro İstanbul's disruption notices, for the saved Metro lines when there
  are any, else for every line
- ``metro_equipment``: the lift record at each saved station, from the step-free port. It never
  says a lift "works": the most it says is that İBB's record shows no fault
- ``alternative``: when the profile asks for step-free access and a saved station's lift is
  out of service, the nearest station whose record shows no lift fault
- ``arrival``: for a saved ``LINE:STOP`` pair, the single-minute arrival
- ``traffic``: the city-wide traffic index
- ``air``: the air quality nearest the first saved station, when the gazetteer knows its name

A source that fails gives an "unverified" card, not a missing one and not a number. Every card
is written by a template, so every card's author is "kural".
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ibb_mcp.http import RateLimitExceeded, UpstreamUnavailable
from ibb_mcp.models import utcnow
from nabiz.console import notice_age
from nabiz.console.arrival import BY_TIMETABLE, arrival_view
from nabiz.console.cards import Status, card, freshness_status, how_view, iso_now, number_tr, provenance_view, unknown_provenance
from nexus_core.arena import UNCERTAINTY_TEXT

log = logging.getLogger("nabiz.console.brief")

MAX_ITEMS = 5
_METRO_LINE = re.compile(r"^(M\d{1,2}[AB]?|T\d|F\d|MARMARAY)$", re.IGNORECASE)
_UNREADABLE = (RateLimitExceeded, UpstreamUnavailable)
_LIFT_BODY: dict[str, tuple[str, Status]] = {
    "working": ("İBB kaydında asansör arızası yok.", "ok"),
    "out_of_service": ("İBB kaydına göre asansör kullanılamıyor.", "warning"),
}


@dataclass(frozen=True)
class Freshness:
    """How the cards judge age: recorded or live data, and the two staleness thresholds."""

    offline: bool
    card_stale_after_s: float
    arrival_stale_after_s: float


def split_csv(raw: str | None, limit: int = MAX_ITEMS) -> list[str]:
    """Up to ``limit`` distinct, trimmed, non-empty items, each at most 60 characters."""
    seen: list[str] = []
    for item in (raw or "").split(","):
        item = item.strip()[:60]
        if item and item not in seen:
            seen.append(item)
    return seen[:limit]


def last_known(body: str, status: Status) -> str:
    """A stale card's sentence starts by saying it is the last known state, not the present one."""
    # The sentence keeps its own first letter: it may be a place name ("İstanbul", "Kartal").
    return f"Son bilinen durum: {body}" if status == "stale" and body else body


def codes_for(status: Status, provenance: dict[str, Any]) -> list[str]:
    """Uncertainty codes for a city card, restricted to the Arena's published vocabulary."""
    codes = set()
    if status == "stale":
        codes.add("stale_data")
    if status == "unverified":
        codes.add("no_evidence")
    if provenance.get("mode") == "recorded":
        codes.add("recorded_data")
    if provenance.get("age_s") is None:
        codes.add("unknown_age")
    return [code for code in UNCERTAINTY_TEXT if code in codes]


def _how(tool: str, provenance: dict[str, Any], status: Status, elapsed_s: float) -> dict[str, Any]:
    return how_view(tool, provenance, rule_id=None, signal_id=None,
                    uncertainty=codes_for(status, provenance), latency_ms=round(elapsed_s * 1000, 1))


def _unverified(kind: str, key: str, title: str, source: str, *, tool: str, elapsed_s: float) -> dict[str, Any]:
    body = "Veri alınamadı; doğrulanamadı."
    provenance = unknown_provenance(source)
    return card(kind, key, title=title, body=body, status="unverified", provenance=provenance,
                how=_how(tool, provenance, "unverified", elapsed_s))


async def metro_status_card(nabiz: Any, lines: Sequence[str], fresh: Freshness) -> dict[str, Any]:
    wanted = {line.upper() for line in lines}
    title = "Metro: " + ", ".join(sorted(wanted)) if wanted else "Metro duyuruları"
    started = time.perf_counter()
    try:
        result = await nabiz.metro_status()
    except _UNREADABLE:
        return _unverified("metro_status", "metro", title, "metro", tool="metro_status",
                           elapsed_s=time.perf_counter() - started)
    notices = [n for n in result.data.get("lines") or [] if not wanted or (n.get("line_name") or "").upper() in wanted]
    if notices:
        history = {}
        try:
            history = notice_age.metro_history(notice_age.cached_rows(notice_age.METRO_SOURCE, now=utcnow()))
        except Exception as exc:  # noqa: BLE001 - arşiv okunamazsa kart yalnız İBB cümlesiyle çıkar
            log.warning("notice archive unreadable: %s", type(exc).__name__)
        parts = []
        for item in notices[:3]:
            line = item.get("line_name") or ""
            description = item.get("description") or ""
            raw_updated = item.get("updated_at")
            try:
                updated_at = (
                    dt.datetime.fromisoformat(raw_updated.replace("Z", "+00:00"))
                    if isinstance(raw_updated, str) else None
                )
            except ValueError:
                updated_at = None
            extra = notice_age.since_text(updated_at, history.get(notice_age.notice_key(line, description)))
            parts.append(f"{line}: {description}".strip() + (f" {extra}" if extra else ""))
        body = " ".join(parts)
        content: Status = "warning"
    else:
        body, content = "Bildirilmiş arıza ya da çalışma duyurusu yok.", "ok"
    status = freshness_status(result.provenance, stale_after_s=fresh.card_stale_after_s, content=content)
    provenance = provenance_view(result.provenance, offline=fresh.offline)
    return card("metro_status", "metro", title=title, body=last_known(body, status), status=status,
                provenance=provenance, how=_how("metro_status", provenance, status, time.perf_counter() - started))


async def station_cards(step_free: Any, station: str, needs: Sequence[str], *, nabiz: Any = None) -> list[dict[str, Any]]:
    """The lift card for one saved station, and the alternative card when it is needed and known."""
    started = time.perf_counter()
    try:
        view = await step_free.alternative(station, list(needs))
    except Exception as exc:  # noqa: BLE001 - one station's failure must not blank the page
        log.warning("step-free port failed for a saved station: %s", type(exc).__name__)
        view = {}
    lift = view.get("lift_status")
    body, status = _LIFT_BODY.get(lift, ("Asansör durumu doğrulanamadı.", "unverified"))
    if view.get("stale") and lift in _LIFT_BODY:
        # Served from cache after an error, or older than the threshold: the last known record,
        # said as such, never a current "no fault".
        status = "stale"
        body = last_known(body, status)
    if lift == "out_of_service" and nabiz is not None:
        try:
            equipment = await nabiz.metro_equipment_status(station=station, group="Asansör")
        except (*_UNREADABLE, ValueError) as exc:
            log.warning("lift date source unreadable: %s", type(exc).__name__)
        else:
            sentences = notice_age.equipment_sentences(equipment.data or {}, station, now=utcnow())
            if sentences:
                body += " " + " ".join(sentences)
    provenance = view.get("provenance") or unknown_provenance("metro_equipment")
    elapsed = time.perf_counter() - started
    cards = [card("metro_equipment", station, title=f"{station} asansör", body=body, status=status,
                  provenance=provenance, how=_how("accessible_alternative", provenance, status, elapsed))]
    alternative = view.get("alternative")
    if "step_free" in needs and lift == "out_of_service" and alternative:
        extra = alternative.get("extra_minutes")
        detail = ""
        if isinstance(extra, int):
            detail = f" {station} ile arası tahminen {extra} dk (mesafeye dayalı; dönüş yolu dahil değil)."
        where = f"{alternative.get('station')} ({alternative.get('line')})"
        body = f"İBB kaydında asansör arızası olmayan en yakın istasyon: {where}.{detail} Operatör onayı yok."
        if view.get("operator_approved") and view.get("approved_text"):
            # The text the simulated operator approved for this outage replaces the suggestion.
            body = f"{view['approved_text']} (Simüle operatör onayladı.)"
        title = f"{station} için adımsız seçenek"
        shown: Status = "stale" if view.get("stale") else "warning"
        cards.append(card("alternative", station, title=title, body=body, status=shown, provenance=provenance,
                          how=_how("accessible_alternative", provenance, shown, elapsed)))
    return cards


async def arrival_card(nabiz: Any, pair: str, fresh: Freshness) -> dict[str, Any] | None:
    line, _, stop = pair.partition(":")
    if not line.strip() or not stop.strip():
        return None
    started = time.perf_counter()
    try:
        view = await arrival_view(
            nabiz, line.strip(), stop.strip(), stale_after_s=fresh.arrival_stale_after_s, offline=fresh.offline
        )
    except ValueError:
        return None
    status: Status = "ok" if view["minutes"] is not None else ("stale" if view["display"] == BY_TIMETABLE else "unverified")
    title, body = f"{view['line']} · {view['stop']}", f"Tahmini varış: {view['display']}"
    return card("arrival", pair, title=title, body=body, status=status, provenance=view["provenance"],
                how=_how("iett_next_arrivals", view["provenance"], status, time.perf_counter() - started))


async def traffic_card(nabiz: Any, fresh: Freshness) -> dict[str, Any]:
    title = "Trafik"
    started = time.perf_counter()
    try:
        result = await nabiz.traffic_index(window="now")
    except _UNREADABLE:
        return _unverified("traffic", "city", title, "traffic", tool="traffic_index",
                           elapsed_s=time.perf_counter() - started)
    data = result.data or {}
    provenance = provenance_view(result.provenance, offline=fresh.offline)
    if data.get("index") is None:
        body = "Trafik indeksi bu ölçümde okunamadı; doğrulanamadı."
        return card("traffic", "city", title=title, body=body, status="unverified", provenance=provenance,
                    how=_how("traffic_index", provenance, "unverified", time.perf_counter() - started))
    body = f"İstanbul trafik yoğunluk indeksi {number_tr(data['index'])} ({data.get('description') or ''})."
    status = freshness_status(result.provenance, stale_after_s=fresh.card_stale_after_s)
    return card("traffic", "city", title=title, body=last_known(body, status), status=status, provenance=provenance,
                how=_how("traffic_index", provenance, status, time.perf_counter() - started))


async def air_card(nabiz: Any, place: str, fresh: Freshness) -> dict[str, Any] | None:
    started = time.perf_counter()
    try:
        result = await nabiz.air_quality_now(place=place)
    except ValueError:
        return None  # not a place the gazetteer knows: no card rather than a guessed district
    except _UNREADABLE:
        return _unverified("air", place, f"Hava kalitesi: {place}", "airquality", tool="air_quality_now",
                           elapsed_s=time.perf_counter() - started)
    data = result.data or {}
    reading, band = data.get("reading") or {}, data.get("band") or {}
    content: Status = "ok"
    if reading.get("aqi_index") is None:
        body, content = "İstasyondan güncel ölçüm gelmiyor; doğrulanamadı.", "unverified"
    else:
        station = (data.get("station") or {}).get("name") or ""
        body = f"{station} istasyonu: hava kalitesi indeksi {number_tr(reading['aqi_index'])}"
        body += f" ({band['label']})." if band.get("label") else "."
        body += " Sağlık tavsiyesi değildir."
    status = freshness_status(result.provenance, stale_after_s=fresh.card_stale_after_s, content=content)
    title = f"Hava kalitesi: {data.get('place') or place}"
    provenance = provenance_view(result.provenance, offline=fresh.offline)
    return card("air", place, title=title, body=last_known(body, status), status=status, provenance=provenance,
                how=_how("air_quality_now", provenance, status, time.perf_counter() - started))


async def build_brief(
    nabiz: Any,
    step_free: Any,
    *,
    stations: Sequence[str],
    lines: Sequence[str],
    needs: Sequence[str],
    fresh: Freshness,
    published: Any | None = None,
) -> dict[str, Any]:
    """Build cards without ingesting signals; queue reads are the sole source of new ledger signals."""
    metro_lines = [line for line in lines if _METRO_LINE.match(line)]
    pairs = [line for line in lines if ":" in line]
    cards = [await metro_status_card(nabiz, metro_lines, fresh)]
    for station in stations:
        cards += await station_cards(step_free, station, needs, nabiz=nabiz)
    if published is not None:
        cards.extend(await published.published(stations=stations))
    for pair in pairs:
        if (one := await arrival_card(nabiz, pair, fresh)) is not None:
            cards.append(one)
    cards.append(await traffic_card(nabiz, fresh))
    if stations and (air := await air_card(nabiz, stations[0], fresh)) is not None:
        cards.append(air)
    return {"cards": cards, "generated_at": iso_now()}
