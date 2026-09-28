"""Shared vocabulary of the ETA estimate: constants, tunables, the GTFS hook and the per-call context.

This is the lowest of the ETA modules (ENGINEERING §13, split plan). :mod:`ibb_mcp.eta_live` and
:mod:`ibb_mcp.eta_schedule` import from here; :mod:`ibb_mcp.eta` orchestrates them and keeps the
public import path. Nothing here reads a clock or touches a data file.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from ibb_mcp.models import ISTANBUL_TZ, Stop

#: A scheduled row describes a departure, not a vehicle, so it carries no door number.
NO_VEHICLE = ""
MODE_LIVE = "live"
MODE_SCHEDULE = "schedule"
MODE_UNKNOWN = "unknown"
SCHEDULE_GTFS = "gtfs_stop_times"
SCHEDULE_IETT = "iett_planned"
#: Fallback city speed when the fleet tells us nothing (see :func:`ibb_mcp.eta.speed_profile_from_fleet`).
DEFAULT_SPEED_KMH = 16.0
_CONFIDENCE_ORDER = ("high", "medium", "low")


def as_aware(moment: dt.datetime) -> dt.datetime:
    """A naive moment is Istanbul local time, the convention ``parse_ibb_datetime`` uses.

    Without this a naive ``now`` either raises against the aware upstream timestamps or,
    when there is no live bus to compare it with, silently reads as the *server's* local
    time and picks the wrong day type — an Azure box runs UTC, which is a three-hour error
    in the timetable fallback.
    """
    return moment if moment.tzinfo else moment.replace(tzinfo=ISTANBUL_TZ)


def downgrade_confidence(confidence: str) -> str:
    """One notch less certain, floored at 'low'."""
    position = _CONFIDENCE_ORDER.index(confidence) if confidence in _CONFIDENCE_ORDER else 1
    return _CONFIDENCE_ORDER[min(position + 1, len(_CONFIDENCE_ORDER) - 1)]


def cap_confidence(confidence: str, ceiling: str) -> str:
    """Keep a method's confidence at or below its measured ceiling."""
    confidence_rank = _CONFIDENCE_ORDER.index(confidence) if confidence in _CONFIDENCE_ORDER else 1
    ceiling_rank = _CONFIDENCE_ORDER.index(ceiling) if ceiling in _CONFIDENCE_ORDER else 2
    return _CONFIDENCE_ORDER[max(confidence_rank, ceiling_rank)]


@dataclass(frozen=True)
class EtaParams:
    """Tunable constants. Every one is a guess until ``eta_log`` says otherwise.

    ``seconds_per_stop`` is the day-one placeholder from PLAN.md section 7 (2 min/stop);
    once the collector has line×hour history, pass a per-route override through
    ``speed_profile`` rather than editing this default.
    """

    seconds_per_stop: float = 120.0
    speed_kmh: float = DEFAULT_SPEED_KMH
    winding_factor: float = 1.35
    max_bus_age_s: float = 600.0
    #: Match the arrival card's NABIZ_ARRIVAL_STALE_S default; callers own env resolution.
    stale_after_s: float = 180.0
    max_results: int = 3
    #: Heuristic confidence before the method's measured ceiling is applied.
    high_confidence_stops: int = 8
    #: Beyond this road distance the straight-line method is little better than a guess.
    low_confidence_km: float = 6.0
    #: How far a bus may sit from the stop it calls ``yakinDurakKodu`` before we stop
    #: believing that claim locates it. See ``ibb_mcp.eta_live._claim_is_credible``.
    max_stop_claim_km: float = 1.5
    #: An average speed no İstanbul bus sustains. If a stop-sequence estimate implies more,
    #: ``seconds_per_stop`` is miscalibrated for that route; say so instead of hiding it.
    implausible_speed_kmh: float = 60.0
    #: How many planned departures to offer when falling back to the timetable.
    max_scheduled: int = 3


DEFAULT_PARAMS = EtaParams()


class GtfsLookup(Protocol):
    """The one hook the ETA modules need from ``ibb_mcp.gtfs.GtfsIndex``.

    A protocol rather than an import, so the ETA maths can be unit-tested without loading
    15 000 stops and a change to the index's constructor cannot break it. Route stop
    orders are *not* fetched through here — ``gtfs.load_stop_sequences()`` returns them as
    a plain dict that the caller passes in as ``sequences``, which keeps this module
    working on the day those sequences are still empty for want of ``stop_times.csv``.
    """

    def lookup_stop(self, stop_code: str) -> Stop | None: ...


def resolve_stop(index: GtfsLookup | None, stop_code: str | None) -> Stop | None:
    """Resolve a stop code through the index, tolerating either accessor it exposes."""
    if index is None or not stop_code:
        return None
    getter = getattr(index, "lookup_stop", None) or getattr(index, "stop_by_code", None)
    if callable(getter):
        return getter(stop_code)
    mapping = getattr(index, "by_stop_code", None)
    return mapping.get(stop_code) if isinstance(mapping, Mapping) else None


def stop_positions(sequence: Any) -> dict[str, int]:
    """Map ``stop_code`` -> position along the route.

    On a loop route a stop appears twice; first occurrence wins, which keeps "stops away"
    positive for a bus approaching the first time and under-counts one on its second pass.
    Under-counting is the safer error: being wrong by a whole loop shows up loudly in
    ``eta_log`` instead of hiding as a plausible number.
    """
    if sequence is None:
        return {}
    codes: Sequence[Any] | None = getattr(sequence, "stop_codes", None)
    if codes is None:
        codes = [getattr(stop, "stop_code", None) for stop in (getattr(sequence, "stops", None) or [])]
    positions: dict[str, int] = {}
    for position, code in enumerate(codes):
        if code is not None:
            positions.setdefault(str(code), position)
    return positions


@dataclass(frozen=True)
class EtaContext:
    """Everything the per-bus and timetable helpers need, so their signatures stay readable."""

    target: Stop
    index: GtfsLookup | None
    sequences: Mapping[str, Any] | None
    speed_profile: Mapping[str, float] | None
    params: EtaParams
    moment: dt.datetime
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def note(self, text: str) -> None:
        if text not in self.diagnostics["notes"]:
            self.diagnostics["notes"].append(text)

    def sequence_for(self, route_code: str | None) -> Any:
        """Ordered stop list for a route, or None while ``stop_times.csv`` is absent."""
        if not route_code or not self.sequences:
            return None
        return self.sequences.get(route_code) or self.sequences.get(route_code.upper())

    def seconds_per_stop(self, route_code: str | None) -> float:
        profile = self.speed_profile
        if profile and route_code and (value := float(profile.get(route_code) or 0)) > 0:
            return value
        return self.params.seconds_per_stop
