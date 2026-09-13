"""Per-line service reliability, derived from the vehicle positions we archived ourselves.

İETT publishes where every bus on a line *is right now*. It publishes no headway, no
bunching indicator and no history, and neither does anybody else for İstanbul. A position
feed sampled every few minutes and kept for a while is enough to reconstruct the two
numbers a rider actually feels:

* **headway** — how long after one bus of a line the next one reaches the same stop;
* **headway regularity** — whether those gaps are even or whether buses travel in convoys
  while riders wait. The standard measure is the coefficient of variation, ``std/mean``,
  and it has a natural scale: an evenly dispatched service tends to 0, while a service
  whose buses arrive independently of one another (a Poisson process) sits at 1. So the cv
  doubles as a 0..1 "how random does this line feel" score — :func:`bunching_score`.

That is the feature: the archive that exists to measure our own ETA error also says which
lines are worth trusting a timetable for.

**How an arrival is reconstructed.** Each snapshot row carries ``nearest_stop_code``. A
vehicle has *arrived* at a stop on the first tick it reports that stop, having previously
reported an **earlier** stop of the same route variant — the rule
``scripts/eta_report.observed_arrivals`` uses, and for the same reason: without the
forward-movement test a bus resting at a terminus and a bus running the opposite direction
both register as arrivals. Unlike that function this one keeps the direction, because a
headway that mixes the two directions of a line is not a headway. The clock is
``snapshot_ts_utc``, not İETT's ``ts_utc``: measured over the current archive the two
differ by a median of 37 s, but ``ts_utc`` has a stale tail (p90 61 s, worst case 15 min)
and all vehicles in a tick report within ~11 s of each other, so İETT's clock buys no
resolution and costs robustness.

**What two partial days of collection can and cannot support:**

* *Resolution.* Arrivals are located to one collector tick (~3.2 min), so every headway is
  a multiple of the tick and the medians are quantised — a true 10-minute headway reads as
  9.6 or 12.9. See :data:`HEADWAY_RESOLUTION_MINUTES`.
* *Missed passages inflate irregularity.* A bus passing a stop between two ticks is never
  seen there and its two neighbouring headways merge into one double gap. Every cv here is
  an **upper bound**: bunching can be overstated by this, never hidden by it.
* *Samples are not independent.* One pair of buses running nose-to-tail produces a short
  headway at every stop it passes. ``samples`` counts gap observations; ``vehicles_seen``
  and ``stops_measured`` bound the real information content. Hence the cv is computed per
  stop first and then taken as a median across stops, never pooled.
* *Coverage.* A cell is "this line at this hour, on the one or two days we were watching" —
  not a typical week. ``days`` and the table's observation span say exactly which.

A (line, hour) cell that fails any guard below is emitted with ``available=False`` and a
Turkish reason. Nothing is interpolated to fill a hole.
"""

from __future__ import annotations

import bisect
import collections
import dataclasses
import datetime as dt
import json
import logging
import pathlib
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.models import ISTANBUL_TZ, haversine_km, utcnow

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# guards
# --------------------------------------------------------------------------------------
#: Pooled headway observations required before a (line, hour) cell reports any number.
#: Twelve is roughly one hour of a 5-minute line at a single stop, or a handful of stops
#: on a slower one — enough that a median is not a coin flip, low enough that a two-day
#: archive still produces cells.
MIN_SAMPLES = 12

#: Headways needed *at one stop in one hour* before that stop contributes a cv.
#: ``statistics.stdev`` needs two; three is the smallest count where the spread means
#: anything at all.
MIN_HEADWAYS_PER_STOP = 3

#: Stops that must clear :data:`MIN_HEADWAYS_PER_STOP` before the cell reports a cv.
#: The cv is a median across stops, and a median of fewer than five is a mood.
MIN_STOPS_FOR_CV = 5

#: A headway needs two different vehicles; a cell needs enough of them to have a service.
MIN_VEHICLES = 2

#: Vehicle-hours needed before the progression rate (stops/h, km/h) is reported.
MIN_PROGRESS_SAMPLES = 5

#: Collector cadence for watched lines, and therefore the granularity of every arrival
#: time here. Headways are quantised to multiples of this.
HEADWAY_RESOLUTION_MINUTES = 3.2

#: Beyond this a "gap" is far more likely to be a service break, a garage run or an
#: unobserved passage than a headway a rider experienced.
MAX_HEADWAY_MINUTES = 120.0

#: If consecutive collector ticks are further apart than this, the collector was not
#: running; any headway spanning the hole is discarded rather than counted as a long wait.
MAX_TICK_GAP = dt.timedelta(minutes=10)

#: Ceiling on a single progression step. A larger jump between two ticks means the stop
#: match wandered (a route variant switch, a GPS excursion), not a fast bus.
MAX_STOPS_PER_STEP = 6

#: Share of stop passages the sampling actually witnesses, below which a cell reports
#: nothing. A bus that advances three stops between two ticks was seen at one of those
#: three stops and missed at the other two, so the capture rate is measurable — see
#: :func:`_progress_rates` — and it is the single biggest threat to these statistics.
#: Under a Bernoulli(c) model of witnessing, gaps between *witnessed* arrivals average
#: ``1/c`` true headways, and a perfectly regular line already shows a cv of
#: ``sqrt(1 - c)`` from the sampling alone (:func:`sampling_cv_floor`). At c = 0.25 that
#: floor is 0.87 and the measurement has nothing left to say.
MIN_CAPTURE_RATE = 0.25

#: Bunching bands. Below :data:`CV_REGULAR` the gaps are even enough that a headway is a
#: promise; above :data:`CV_BUNCHED` the arrival process is closer to random than to
#: scheduled and riders see convoys. The bands follow the usual transit-practice reading
#: of the headway cv (even service near 0.2, visibly irregular past ~0.5, indistinguishable
#: from random at 1.0); they are this project's thresholds, published so a reader can
#: disagree with them rather than having to reverse-engineer them.
CV_REGULAR = 0.30
CV_BUNCHED = 0.60

LABEL_REGULAR = "düzenli"
LABEL_SOMEWHAT = "biraz düzensiz"
LABEL_BUNCHED = "kümelenme var"

#: Where the built table is kept. Small, derived and reproducible from the lake.
DEFAULT_TABLE_PATH = REPO_ROOT / "data" / "reference" / "line_reliability.json"

SCHEMA_VERSION = 1


# --------------------------------------------------------------------------------------
# bunching
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class BunchingVerdict:
    """A headway cv turned into something an answer can say out loud."""

    cv: float
    score: float
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {"cv": self.cv, "score": self.score, "label": self.label}


def bunching_score(cv: float) -> BunchingVerdict:
    """Map a headway coefficient of variation onto 0..1 and a Turkish label.

    The score is the cv itself, clamped to ``[0, 1]``, because the cv already carries the
    scale we want: 0 is a perfectly even service, and 1 is the cv of a Poisson process —
    buses arriving with no memory of each other, which is the practical worst case a rider
    can distinguish. Anything above 1 is worse still but not *more* informative, so it
    saturates instead of running away.

    Thresholds are :data:`CV_REGULAR` and :data:`CV_BUNCHED`; a negative cv is impossible
    and is rejected rather than silently clamped, since it can only mean a caller computed
    it wrong.
    """
    if cv < 0:
        raise ValueError(f"headway cv cannot be negative, got {cv!r}")
    score = min(cv, 1.0)
    if cv < CV_REGULAR:
        label = LABEL_REGULAR
    elif cv < CV_BUNCHED:
        label = LABEL_SOMEWHAT
    else:
        label = LABEL_BUNCHED
    return BunchingVerdict(cv=round(cv, 3), score=round(score, 3), label=label)


def sampling_cv_floor(capture_rate: float) -> float:
    """The headway cv a **perfectly regular** line would still show at this capture rate.

    Model each passage of a stop as witnessed with probability ``c`` and missed otherwise,
    independently. The gap between two witnessed arrivals is then the sum of ``G ~
    Geometric(c)`` true headways, and working through the mean and variance gives
    ``cv_observed² = c·cv_true² + (1 - c)``. Set ``cv_true = 0`` and the floor is
    ``sqrt(1 - c)``: irregularity we invented by not looking often enough.

    It is printed next to every measured cv so the two can be compared. An observed cv
    below its floor is not a contradiction — the stops that clear
    :data:`MIN_HEADWAYS_PER_STOP` are selected for being easy to witness, so their local
    capture is far better than the line average this floor is computed from.
    """
    return round((max(0.0, 1.0 - capture_rate)) ** 0.5, 3)


# --------------------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class LineHourStats:
    """One (line, local hour) cell. Metric fields are ``None`` unless ``available``."""

    line_code: str
    hour: int
    available: bool
    samples: int = 0
    vehicles_seen: int = 0
    stops_measured: int = 0
    stops_with_cv: int = 0
    days: int = 0
    median_headway_min: float | None = None
    headway_cv: float | None = None
    bunching_score: float | None = None
    bunching_label: str | None = None
    stops_per_hour_median: float | None = None
    median_speed_kmh: float | None = None
    stop_capture_rate: float | None = None
    cv_sampling_floor: float | None = None
    #: True when the measured cv exceeds what this capture rate alone would produce on a
    #: perfectly regular line. Only then is the irregularity evidence rather than artefact.
    cv_exceeds_floor: bool | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> LineHourStats:
        fields = {k: payload.get(k) for k in cls.__dataclass_fields__ if k in payload}
        return cls(**fields)  # type: ignore[arg-type]


@dataclass
class ReliabilityTable:
    """Every computed cell plus the observation window that produced it.

    The window is not decoration. A reliability figure without the span it was measured
    over invites the reader to assume "always", and two partial days are not always.
    """

    cells: list[LineHourStats] = field(default_factory=list)
    observed_from: dt.datetime | None = None
    observed_to: dt.datetime | None = None
    days_covered: list[str] = field(default_factory=list)
    snapshots_read: int = 0
    generated_at: dt.datetime = field(default_factory=utcnow)
    resolution_minutes: float = HEADWAY_RESOLUTION_MINUTES
    schema_version: int = SCHEMA_VERSION

    def get(self, line_code: str, hour: int) -> LineHourStats | None:
        for cell in self.cells:
            if cell.line_code == line_code and cell.hour == hour:
                return cell
        return None

    def lines(self) -> list[str]:
        return sorted({cell.line_code for cell in self.cells})

    @property
    def span_hours(self) -> float | None:
        if self.observed_from is None or self.observed_to is None:
            return None
        return round((self.observed_to - self.observed_from).total_seconds() / 3600.0, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.isoformat(),
            "observation_span": {
                "from": self.observed_from.isoformat() if self.observed_from else None,
                "to": self.observed_to.isoformat() if self.observed_to else None,
                "hours": self.span_hours,
                "days_covered": self.days_covered,
                "snapshots_read": self.snapshots_read,
            },
            "resolution_minutes": self.resolution_minutes,
            "thresholds": {
                "cv_regular": CV_REGULAR,
                "cv_bunched": CV_BUNCHED,
                "min_samples": MIN_SAMPLES,
                "min_headways_per_stop": MIN_HEADWAYS_PER_STOP,
                "min_stops_for_cv": MIN_STOPS_FOR_CV,
                "min_vehicles": MIN_VEHICLES,
                "min_capture_rate": MIN_CAPTURE_RATE,
            },
            "cells": [cell.to_dict() for cell in self.cells],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ReliabilityTable:
        span = payload.get("observation_span") or {}
        return cls(
            cells=[LineHourStats.from_dict(c) for c in payload.get("cells", [])],
            observed_from=_parse_ts(span.get("from")),
            observed_to=_parse_ts(span.get("to")),
            days_covered=list(span.get("days_covered") or []),
            snapshots_read=int(span.get("snapshots_read") or 0),
            generated_at=_parse_ts(payload.get("generated_at")) or utcnow(),
            resolution_minutes=float(payload.get("resolution_minutes") or HEADWAY_RESOLUTION_MINUTES),
            schema_version=int(payload.get("schema_version") or SCHEMA_VERSION),
        )


def save_table(table: ReliabilityTable, path: pathlib.Path | str = DEFAULT_TABLE_PATH) -> pathlib.Path:
    """Write the table as JSON, creating the directory if needed."""
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(table.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def load_table(path: pathlib.Path | str = DEFAULT_TABLE_PATH) -> ReliabilityTable | None:
    """Read a saved table, or ``None`` when it is missing or unreadable.

    Unreadable is not fatal on purpose: a missing reliability table costs one optional
    answer, and a tool that raises on a stale file would take the whole server down with it.
    """
    target = pathlib.Path(path)
    if not target.exists():
        return None
    try:
        return ReliabilityTable.from_dict(json.loads(target.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        log.warning("reliability table at %s unreadable (%r)", target, exc)
        return None


# --------------------------------------------------------------------------------------
# reconstruction
# --------------------------------------------------------------------------------------
#: ``(line_code, direction, stop_code)``. Direction is the İETT route-code token (``G``
#: outbound / ``D`` inbound), falling back to the human direction label.
ArrivalKey = tuple[str, str, str]


def _parse_ts(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _direction_of(row: Mapping[str, Any]) -> str:
    route = str(row.get("route_code") or "")
    parts = route.split("_")
    if len(parts) >= 3 and parts[1]:
        return parts[1]
    return str(row.get("direction") or "?")


def _moved_forward(sequences: Mapping[str, Any], route: str | None, from_stop: str, to_stop: str) -> bool:
    """Did the vehicle advance along its route, or is this a layover / opposite run?

    Unknown routes and unknown stops answer ``True``: without a sequence the test cannot be
    applied, and dropping the sighting would silently shrink the sample instead of loosening
    the filter. That is the same degradation ``eta_report`` chose.
    """
    sequence = sequences.get(route or "")
    if sequence is None:
        return True
    here, before = sequence.position_of(to_stop), sequence.position_of(from_stop)
    return here is None or before is None or before < here


def arrival_events(
    snapshots: Iterable[Mapping[str, Any]],
    sequences: Mapping[str, Any] | None = None,
) -> dict[ArrivalKey, list[tuple[dt.datetime, str]]]:
    """Reconstruct ``(time, door)`` arrivals per ``(line, direction, stop)``, time-sorted.

    Consecutive ticks at the same stop collapse into the one arrival that began them; a
    later return to the same stop is a separate arrival.
    """
    sequences = sequences or {}
    by_vehicle: dict[tuple[str, str], list[tuple[dt.datetime, str, str | None, str]]] = collections.defaultdict(list)
    for row in snapshots:
        stamp = _parse_ts(row.get("snapshot_ts_utc"))
        stop = row.get("nearest_stop_code")
        line, door = row.get("line_code"), row.get("door_no")
        if stamp is None or not stop or not line or not door:
            continue
        by_vehicle[(str(line), str(door))].append((stamp, str(stop), row.get("route_code"), _direction_of(row)))

    arrivals: dict[ArrivalKey, list[tuple[dt.datetime, str]]] = collections.defaultdict(list)
    for (line, door), entries in by_vehicle.items():
        entries.sort(key=lambda item: item[0])
        previous: tuple[str, str | None] | None = None
        for stamp, stop, route, direction in entries:
            first_sighting = previous is None
            if (first_sighting or previous[0] != stop) and (
                first_sighting or _moved_forward(sequences, route, previous[0], stop)
            ):
                arrivals[(line, direction, stop)].append((stamp, door))
            previous = (stop, route)
    for events in arrivals.values():
        events.sort()
    return dict(arrivals)


def _tick_index(snapshots: Iterable[Mapping[str, Any]]) -> dict[str, list[dt.datetime]]:
    """When the collector actually observed each line. Used to reject headways over a hole."""
    ticks: dict[str, set[dt.datetime]] = collections.defaultdict(set)
    for row in snapshots:
        stamp = _parse_ts(row.get("snapshot_ts_utc"))
        line = row.get("line_code")
        if stamp is not None and line:
            ticks[str(line)].add(stamp)
    return {line: sorted(values) for line, values in ticks.items()}


def _observed_throughout(ticks: Sequence[dt.datetime], start: dt.datetime, end: dt.datetime) -> bool:
    """Was the collector awake for the whole interval?

    Both bounds are themselves tick times — arrivals are stamped with the tick that saw
    them — so the closed interval is exactly the evidence available. Ticks outside it are
    deliberately not consulted: a hole *after* the second arrival says nothing about the
    wait before it, and consulting one would throw away the last headway of every session.
    """
    window = ticks[bisect.bisect_left(ticks, start) : bisect.bisect_right(ticks, end)]
    return all(later - earlier <= MAX_TICK_GAP for earlier, later in zip(window, window[1:], strict=False))


@dataclass
class _Progress:
    """Per (line, hour) movement evidence: how fast, and how much of it we witnessed."""

    #: One ``(stops_per_hour, km_per_hour)`` pair per vehicle-hour.
    rates: list[tuple[float, float]] = field(default_factory=list)
    #: Ticks at which a vehicle had advanced at least one stop — passages witnessed.
    steps_with_advance: int = 0
    #: Stop positions actually traversed — passages that happened.
    stops_advanced: int = 0

    @property
    def capture_rate(self) -> float | None:
        """Share of stop passages the sampling saw. ``None`` when nothing moved."""
        if self.stops_advanced <= 0:
            return None
        return round(self.steps_with_advance / self.stops_advanced, 3)


def _progress_rates(
    snapshots: Iterable[Mapping[str, Any]],
    sequences: Mapping[str, Any],
) -> dict[tuple[str, int], _Progress]:
    """Per ``(line, hour)``: speed per vehicle-hour, plus the measured capture rate.

    Speeds are accumulated over *every* consecutive pair of sightings, including the ones
    where the bus did not move: dwell time is part of how fast a line actually gets you
    somewhere, and counting only the ticks that advanced would turn a crawling line into a
    fast one.

    The capture rate falls out of the same walk for free. A vehicle that advanced three
    stop positions between two ticks passed three stops and was witnessed at one of them,
    so ``steps_with_advance / stops_advanced`` estimates the share of all stop passages
    this sampling rate can see — the number that bounds how much the headway statistics
    can be trusted. It needs stop sequences; without them it is simply unavailable.
    """
    totals: dict[tuple[str, int, str], list[float]] = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
    capture: dict[tuple[str, int], list[int]] = collections.defaultdict(lambda: [0, 0])
    by_vehicle: dict[tuple[str, str], list[tuple[dt.datetime, str, str | None, float | None, float | None]]]
    by_vehicle = collections.defaultdict(list)
    for row in snapshots:
        stamp = _parse_ts(row.get("snapshot_ts_utc"))
        line, door, stop = row.get("line_code"), row.get("door_no"), row.get("nearest_stop_code")
        if stamp is None or not line or not door or not stop:
            continue
        by_vehicle[(str(line), str(door))].append(
            (stamp, str(stop), row.get("route_code"), row.get("lat"), row.get("lon"))
        )

    for (line, door), entries in by_vehicle.items():
        entries.sort(key=lambda item: item[0])
        for (t0, stop0, route0, lat0, lon0), (t1, stop1, route1, lat1, lon1) in zip(entries, entries[1:], strict=False):
            hours = (t1 - t0).total_seconds() / 3600.0
            if hours <= 0 or t1 - t0 > MAX_TICK_GAP or route0 != route1:
                continue
            hour = t1.astimezone(ISTANBUL_TZ).hour
            key = (line, hour, door)  # the door keeps one vehicle's hour apart from another's
            sequence = sequences.get(route1 or "")
            if sequence is not None:
                before, here = sequence.position_of(stop0), sequence.position_of(stop1)
                if before is not None and here is not None and 0 <= here - before <= MAX_STOPS_PER_STEP:
                    totals[key][0] += here - before
                    totals[key][2] += hours
                    if here > before:
                        capture[(line, hour)][0] += 1
                        capture[(line, hour)][1] += here - before
            if None not in (lat0, lon0, lat1, lon1):
                totals[key][1] += haversine_km(float(lat0), float(lon0), float(lat1), float(lon1))

    progress: dict[tuple[str, int], _Progress] = collections.defaultdict(_Progress)
    for (line, hour, _door), (stops, km, tracked) in totals.items():
        if tracked < 0.15:  # under ~9 minutes of tracking a rate is noise
            continue
        progress[(line, hour)].rates.append((stops / tracked, km / tracked))
    for (line, hour), (witnessed, passed) in capture.items():
        cell = progress[(line, hour)]
        cell.steps_with_advance = witnessed
        cell.stops_advanced = passed
    return dict(progress)


# --------------------------------------------------------------------------------------
# the statistics
# --------------------------------------------------------------------------------------
def compute_line_stats(
    snapshots: Iterable[Mapping[str, Any]],
    sequences: Mapping[str, Any] | None = None,
) -> dict[tuple[str, int], LineHourStats]:
    """Per ``(line_code, İstanbul hour)`` reliability, guards included.

    ``sequences`` is ``{route_code: RouteStopSequence}`` from :func:`ibb_mcp.gtfs.load_stop_sequences`.
    It is optional: without it the forward-movement filter and the stops/hour rate are skipped,
    the speed and headway numbers still come out, and the loss is recorded rather than hidden.

    A cell is returned for every (line, hour) the archive touched, including the ones that
    fail a guard — those carry ``available=False`` and a Turkish ``reason``, because "we
    watched this line at this hour and cannot say" is itself an answer worth publishing.
    """
    rows = list(snapshots)
    sequences = sequences or {}
    if not rows:
        return {}

    arrivals = arrival_events(rows, sequences)
    ticks = _tick_index(rows)
    rates = _progress_rates(rows, sequences)

    # (line, hour) -> (direction, stop) -> [headway minutes]
    headways: dict[tuple[str, int], dict[tuple[str, str], list[float]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    days: dict[tuple[str, int], set[str]] = collections.defaultdict(set)

    # Fleet in service: every distinct door seen on the line during that local hour. Taken
    # from the raw rows rather than from the headway pairs, so it stays a count of buses
    # running and not a count of buses that happened to produce a measurable gap.
    fleet: dict[tuple[str, int], set[str]] = collections.defaultdict(set)
    for row in rows:
        stamp = _parse_ts(row.get("snapshot_ts_utc"))
        line, door = row.get("line_code"), row.get("door_no")
        if stamp is not None and line and door:
            fleet[(str(line), stamp.astimezone(ISTANBUL_TZ).hour)].add(str(door))

    for (line, direction, stop), events in arrivals.items():
        for (earlier, first_door), (later, second_door) in zip(events, events[1:], strict=False):
            local = later.astimezone(ISTANBUL_TZ)
            cell = (line, local.hour)
            if first_door == second_door:
                continue  # the same bus coming round again is a cycle time, not a headway
            gap = (later - earlier).total_seconds() / 60.0
            if gap < 0 or gap > MAX_HEADWAY_MINUTES:
                continue
            if not _observed_throughout(ticks.get(line, []), earlier, later):
                continue  # the collector was down in between; this is our hole, not a wait
            headways[cell][(direction, stop)].append(gap)
            days[cell].add(local.date().isoformat())

    cells: dict[tuple[str, int], LineHourStats] = {}
    for cell in sorted(set(headways) | set(rates) | set(fleet)):
        cells[cell] = _summarise(
            cell,
            headways.get(cell, {}),
            fleet.get(cell, set()),
            days.get(cell, set()),
            rates.get(cell) or _Progress(),
        )
    return cells


def _summarise(
    cell: tuple[str, int],
    per_stop: Mapping[tuple[str, str], list[float]],
    fleet: set[str],
    days: set[str],
    progress: _Progress,
) -> LineHourStats:
    """Turn one cell's raw gaps into a verdict, or into a refusal with a reason."""
    line, hour = cell
    pooled = [gap for gaps in per_stop.values() for gap in gaps]
    cvs = [
        statistics.stdev(gaps) / statistics.fmean(gaps)
        for gaps in per_stop.values()
        if len(gaps) >= MIN_HEADWAYS_PER_STOP and statistics.fmean(gaps) > 0
    ]
    capture = progress.capture_rate
    base = {
        "line_code": line,
        "hour": hour,
        "samples": len(pooled),
        "vehicles_seen": len(fleet),
        "stops_measured": len(per_stop),
        "stops_with_cv": len(cvs),
        "days": len(days),
        "stop_capture_rate": capture,
        "cv_sampling_floor": None if capture is None else sampling_cv_floor(capture),
    }

    reason = _refusal(len(pooled), len(fleet), len(cvs), capture)
    if reason is not None:
        return LineHourStats(available=False, reason=reason, **base)

    verdict = bunching_score(statistics.median(cvs))
    floor = base["cv_sampling_floor"]
    stops_per_hour = median_speed = None
    if len(progress.rates) >= MIN_PROGRESS_SAMPLES:
        stops = [pair[0] for pair in progress.rates if pair[0] > 0]
        speeds = [pair[1] for pair in progress.rates if pair[1] > 0]
        stops_per_hour = round(statistics.median(stops), 1) if len(stops) >= MIN_PROGRESS_SAMPLES else None
        median_speed = round(statistics.median(speeds), 1) if len(speeds) >= MIN_PROGRESS_SAMPLES else None

    return LineHourStats(
        available=True,
        median_headway_min=round(statistics.median(pooled), 1),
        headway_cv=verdict.cv,
        bunching_score=verdict.score,
        bunching_label=verdict.label,
        cv_exceeds_floor=None if floor is None else verdict.cv > floor,
        stops_per_hour_median=stops_per_hour,
        median_speed_kmh=median_speed,
        reason=None,
        **base,
    )


def _refusal(samples: int, vehicles: int, stops_with_cv: int, capture: float | None) -> str | None:
    """The Turkish sentence explaining why a cell stays silent, or ``None`` to publish."""
    if vehicles < MIN_VEHICLES:
        return (
            f"Bu saatte yalnızca {vehicles} araç gözlendi; iki ardışık aracın aynı durağa varışı "
            "olmadan sefer aralığı hesaplanamaz."
        )
    if samples < MIN_SAMPLES:
        return (
            f"Yeterli gözlem yok: {samples} sefer aralığı ölçülebildi, en az {MIN_SAMPLES} gerekiyor. "
            "Toplayıcı bu hattı bu saatte daha uzun süre izlediğinde dolacak."
        )
    if stops_with_cv < MIN_STOPS_FOR_CV:
        return (
            f"Düzenlilik ölçülemedi: yalnızca {stops_with_cv} durakta en az {MIN_HEADWAYS_PER_STOP} ardışık "
            f"varış görüldü, en az {MIN_STOPS_FOR_CV} durak gerekiyor."
        )
    if capture is not None and capture < MIN_CAPTURE_RATE:
        return (
            f"Örnekleme çok seyrek: durak geçişlerinin yalnızca %{capture * 100:.0f}'i yakalanabildi "
            f"(en az %{MIN_CAPTURE_RATE * 100:.0f} gerekiyor). Bu oranda tamamen düzenli bir hat bile "
            f"cv≈{sampling_cv_floor(capture)} gösterir, dolayısıyla ölçüm düzenlilik hakkında bir şey söylemez."
        )
    return None


def build_table(
    snapshots: Iterable[Mapping[str, Any]],
    sequences: Mapping[str, Any] | None = None,
) -> ReliabilityTable:
    """Compute every cell and stamp it with the window it was measured over."""
    rows = list(snapshots)
    stamps = [ts for ts in (_parse_ts(row.get("snapshot_ts_utc")) for row in rows) if ts is not None]
    cells = compute_line_stats(rows, sequences)
    return ReliabilityTable(
        cells=[cells[key] for key in sorted(cells)],
        observed_from=min(stamps) if stamps else None,
        observed_to=max(stamps) if stamps else None,
        days_covered=sorted({ts.astimezone(ISTANBUL_TZ).date().isoformat() for ts in stamps}),
        snapshots_read=len(rows),
    )


def describe_cell(table: ReliabilityTable | None, line_code: str, hour: int) -> dict[str, Any]:
    """Tool-shaped lookup: always a dict, always with ``available`` and a Turkish note.

    This is the function an MCP tool wraps, which is why it tolerates a missing table and a
    missing cell instead of raising: every failure mode has to come back as a sentence the
    agent can repeat verbatim.
    """
    window = None
    if table is not None and table.observed_from and table.observed_to:
        window = {
            "from": table.observed_from.isoformat(),
            "to": table.observed_to.isoformat(),
            "days_covered": table.days_covered,
            "hours": table.span_hours,
        }
    if table is None:
        return {
            "available": False,
            "line_code": line_code,
            "hour": hour,
            "note": "Hat düzenlilik tablosu henüz üretilmedi; scripts/reliability_report.py çalıştırılmalı.",
        }
    cell = table.get(line_code, hour)
    if cell is None:
        return {
            "available": False,
            "line_code": line_code,
            "hour": hour,
            "observation_window": window,
            "note": (
                f"{line_code} hattı saat {hour:02d} için hiç gözlem yok. Toplayıcı yalnızca "
                f"{', '.join(table.lines()) or 'hiçbir hattı'} izliyor."
            ),
        }
    payload = cell.to_dict()
    payload["observation_window"] = window
    payload["resolution_minutes"] = table.resolution_minutes
    payload["note"] = cell.reason if not cell.available else (
        f"{cell.median_headway_min} dk ortanca sefer aralığı, düzenlilik: {cell.bunching_label} "
        f"(cv {cell.headway_cv}). {cell.samples} aralık gözlemi, {cell.vehicles_seen} araç, "
        f"{cell.days} gün. Varışlar ~{table.resolution_minutes:.1f} dakikalık toplama adımıyla "
        f"ölçüldü ve durak geçişlerinin %{(cell.stop_capture_rate or 0) * 100:.0f}'i yakalandı; "
        f"kaçırılan geçişler hem aralığı hem düzensizliği olduğundan büyük gösterir, yani bu "
        f"değerler üst sınırdır. Bu yakalama oranında tamamen düzenli bir hat bile "
        f"cv≈{cell.cv_sampling_floor} gösterebilirdi"
        + (
            ", ölçülen cv bu tabanın üzerinde olduğu için düzensizlik yalnızca örneklemeyle açıklanamaz."
            if cell.cv_exceeds_floor
            else "; ölçülen cv bu tabanın altında, yani veri gerçek bir kümelenmeyi kanıtlamıyor."
        )
    )
    return payload
