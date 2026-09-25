"""The single-minute arrival rule: one whole number, or an honest word instead of one.

The owner's decision (product principles §4.4): an arrival is shown as one whole minute,
"7 dk", never a range, and the English abbreviation never reaches the page. The rest is the
Mobiett lesson: a "1 dk" that keeps a rider waiting ten minutes ends trust, so the number is
withdrawn rather than shown when it cannot be backed:

    no estimate at all, or the source failed        -> "doğrulanamadı", no number
    the estimate comes from the timetable           -> "tarifeye göre", no number
    the bus position is older than the threshold,
    or every position was too old to estimate from  -> "tarifeye göre", no number
    under one minute                                -> "1 dk" (never "şimdi")
    otherwise                                       -> "<n> dk", n rounded down

A timetable estimate carries no number because ``ibb_mcp.eta`` counts it to the planned
departure from the terminus, not to the rider's stop: printing it as an arrival would be a
fabrication. Rounding down leans early on purpose: missing the bus costs more than waiting a
minute for it. The threshold (``NABIZ_ARRIVAL_STALE_S``, default 180 s) is the design's
estimate and is still to be measured.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from ibb_mcp.http import RateLimitExceeded, UpstreamUnavailable
from ibb_mcp.models import Provenance, utcnow
from nabiz.agent.minutes import BY_TIMETABLE, UNVERIFIED, shown_minutes
from nabiz.console.cards import Mode, env_seconds, mode_for, provenance_view, unknown_provenance

ARRIVAL_STALE_DEFAULT_S = 180


@dataclass(frozen=True)
class ArrivalDisplay:
    minutes: int | None
    display: str
    mode: Mode


def arrival_stale_after_s() -> int:
    return env_seconds("NABIZ_ARRIVAL_STALE_S", ARRIVAL_STALE_DEFAULT_S)


def single_minute(
    eta_minutes: float | None,
    *,
    method: str | None,
    age_s: float | None,
    stale_after_s: float,
    offline: bool,
) -> ArrivalDisplay:
    """Apply the rule above to one estimate (the rule itself is :func:`nabiz.agent.minutes.shown_minutes`)."""
    minutes, text = shown_minutes(eta_minutes, method, stale=age_s is None or age_s > stale_after_s)
    if text == UNVERIFIED:
        return ArrivalDisplay(None, text, "unknown")
    return ArrivalDisplay(minutes, text, "schedule" if minutes is None else mode_for(offline))


def _as_datetime(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    if isinstance(value, str) and value:
        try:
            parsed = dt.datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
    return None


def position_time(arrival: dict[str, Any], prov: Provenance) -> dt.datetime:
    """When the position behind this estimate was taken: the bus's own report, else the read."""
    return _as_datetime(arrival.get("reported_at")) or prov.reported_at or prov.observed_at


async def arrival_view(nabiz: Any, line: str, stop: str, *, stale_after_s: float, offline: bool) -> dict[str, Any]:
    """``GET /api/arrival``: the soonest estimate for a line at a stop, under the single-minute rule.

    A line or stop that does not exist raises ``ValueError`` (the route answers 400 with the
    tool's own Turkish sentence). An İBB outage is an answer, not an error: "doğrulanamadı".
    """
    try:
        result = await nabiz.iett_next_arrivals(line_code=line, stop=stop, limit=1)
    except (RateLimitExceeded, UpstreamUnavailable):
        return {
            "line": line.upper().strip(),
            "stop": stop,
            "minutes": None,
            "display": UNVERIFIED,
            "provenance": unknown_provenance("iett"),
        }
    data = result.data or {}
    arrivals = data.get("arrivals") or []
    first = arrivals[0] if arrivals else {}
    taken = position_time(first, result.provenance) if first else None
    age_s = max(0.0, (utcnow() - taken).total_seconds()) if taken else None
    if not first and (data.get("diagnostics") or {}).get("dropped_stale"):
        # Buses reported, every position too old to estimate from: the stale case, not the empty one.
        shown = ArrivalDisplay(None, BY_TIMETABLE, "schedule")
    else:
        shown = single_minute(
            first.get("eta_minutes"),
            method=first.get("method"),
            age_s=age_s,
            stale_after_s=stale_after_s,
            offline=offline,
        )
    provenance = provenance_view(result.provenance, offline=offline, mode=shown.mode)
    if taken is not None and age_s is not None:
        provenance["observed_at"], provenance["age_s"] = taken.isoformat(), int(age_s)
    stop_row = data.get("stop") or {}
    return {
        "line": data.get("line_code") or line.upper().strip(),
        "stop": stop_row.get("name") or stop,
        "minutes": shown.minutes,
        "display": shown.display,
        "provenance": provenance,
    }
