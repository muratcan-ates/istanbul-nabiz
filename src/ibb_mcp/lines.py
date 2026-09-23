"""Direct İETT lines between two stops: "can one bus just take me there?"

The travel advisor asks the bus network a question the ETA engine never asks. ``eta.py``
answers *when* the next vehicle reaches a stop; this module answers whether **any single
line** joins two stops at all, which is what decides whether "bus" is even on the list of
options worth comparing against driving. The data for it already exists: ``gtfs.py``
builds the ordered stop list of every route variant (:func:`ibb_mcp.gtfs.load_stop_sequences`),
and a direct line is simply a variant whose order puts the origin before the destination.

What this module refuses to do:

* **It is not a journey planner.** One line, one ride, or nothing — no transfers, no
  walking legs, no stitching a bus onto the metro. PLAN.md section 17 keeps route planning
  out of this project, and a two-leg itinerary assembled from a static stop order would be
  a promise nobody has verified against a timetable.
* **It never matches on a stop name.** Stops are identified by GTFS ``stop_code``, the key
  live telemetry reports as ``yakinDurakKodu`` — *not* ``stop_id``, which is a different
  number space (see the module docstring of ``gtfs.py``). Turning "Kadıköy" into a set of
  codes is the caller's job, so the caller can also say which codes it picked.
* **It never calls a line direct because the route touches both stops.** Direction is the
  whole point. A line is published as one route variant per direction — ``500T_G_D0`` runs
  Şifa Sondurak to 4. Levent Metro over 64 stops, ``500T_D_D0`` runs the other way over the
  same stops. Membership alone would answer "take the 500T" to a rider standing at 4. Levent
  who wants Şifa on the *G* run, sending them 63 stops the wrong way. So positions are
  compared, never sets.
* **It never invents a line name.** A route variant whose code cannot be parsed is counted
  and dropped, never surfaced (see :func:`parse_route_code`).
* **No network, no file I/O, no clock.** Pure functions over the mapping the caller already
  loaded. A direct line here is a fact about the published route, not a claim that a bus is
  running right now — that still needs the live ETA tool, and the advisor must say so.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from ibb_mcp.gtfs import RouteStopSequence

#: A route variant code is ``LINE_DIRECTION_VARIANT``: ``"500T_G_D0"`` is line 500T in the
#: "G" (gidiş) direction, deviation 0. 9,256 of the 9,279 rows in ``routes.csv`` have
#: exactly this shape; the rest are a shifted column, which is what the parser guards against.
_MIN_ROUTE_CODE_PARTS = 3

#: Origin and destination must be at least this many stops apart before a line counts as a
#: ride. Zero means both codes land on the same position in the route — the rider is already
#: standing where they want to be, and offering them a bus for it is noise, not an answer.
MIN_STOPS_BETWEEN = 1

_LEADING_DIGITS = re.compile(r"^(\d+)(.*)$")


@dataclass(frozen=True)
class DirectLine:
    """One line that carries a rider from origin to destination without changing vehicle.

    ``stops_between`` is a ride *length*, not a duration: converting stops to minutes needs
    the fleet's speed and belongs to ``ibb_mcp.eta``. Keeping the raw count here means the
    advisor can quote something it actually measured ("14 stops") instead of a modelled
    minute figure dressed up as a fact.

    ``route_code`` is kept beside ``line`` on purpose. It is the key the live feed uses
    (``guzergahkodu``), so whoever receives this can go straight on to ask for arrivals on
    that exact variant, and it records *which* of a line's variants the claim rests on.
    """

    line: str
    route_code: str
    origin_stop_code: str
    destination_stop_code: str
    stops_between: int
    direction: str | None


def parse_route_code(route_code: str) -> tuple[str, str] | None:
    """``"500T_G_D0"`` -> ``("500T", "G")``; ``None`` when the code is not a route code.

    23 rows of ``routes.csv`` carry a shifted column — a sentence of Turkish service prose,
    or a bare ``"3"`` — where ``route_code`` belongs, and 7 of those reach the sequence
    cache with a genuine stop order attached. Their trips are real but their line is
    unknowable, and a tool that answered "take the SEFERLER MARMARA ÜNİV..." would be
    inventing a line name out of a parsing accident. Refusing to name them costs 7 variants
    out of 2,876 and keeps every line this module does name checkable against the sign on
    the bus.

    A code with *more* than three parts is accepted and read the same way, because the line
    and the direction still sit in the first two; a code with fewer carries no direction at
    all, which this module cannot work without.

    Reading the line from the code costs nothing against ``routes.csv``: for all 2,869
    sequence variants whose code parses, the prefix equals that row's ``route_short_name``
    (checked against the local export on 2026-09-23, zero differences).
    """
    parts = route_code.split("_")
    if len(parts) < _MIN_ROUTE_CODE_PARTS:
        return None
    line, direction = parts[0].strip(), parts[1].strip()
    if not line or not direction or any(char.isspace() for char in line):
        return None
    return line, direction


def _clean_code(stop_code: str) -> str:
    """Stop codes arrive from user input and from fuzzy name matches; both bring whitespace."""
    return str(stop_code).strip() if stop_code else ""


def _clean_codes(stop_codes: Iterable[str]) -> tuple[str, ...]:
    """Strip, drop blanks, keep first-seen order so results stay deterministic."""
    cleaned: dict[str, None] = {}
    for stop_code in stop_codes:
        code = _clean_code(stop_code)
        if code:
            cleaned.setdefault(code, None)
    return tuple(cleaned)


def _positions(sequence: RouteStopSequence) -> dict[str, int]:
    """Map ``stop_code`` -> position along one route variant, first visit winning.

    Same rule as :meth:`ibb_mcp.gtfs.RouteStopSequence.stops_between`, computed once per
    candidate route instead of once per pair of stops. On a loop route a stop appears twice
    and only the first visit is indexed, so a ride that would board after the loop's turning
    point is reported as "no direct line". That under-reports; the opposite error would send
    someone to a bus stop the route reaches only on its way out of the neighbourhood.
    """
    positions: dict[str, int] = {}
    for position, stop_code in enumerate(sequence.stop_codes):
        code = _clean_code(stop_code)
        if code:
            positions.setdefault(code, position)
    return positions


def _line_sort_key(line: str) -> tuple[int, int, str]:
    """Sort line codes the way they are read, so "5" comes before "11ÇB" and "500T".

    Plain string order puts "10" before "5", which makes a list of lines at one stop look
    shuffled to anyone who has stood under the sign.
    """
    match = _LEADING_DIGITS.match(line)
    if match:
        return 0, int(match.group(1)), match.group(2)
    return 1, 0, line


#: How a caller prices one candidate ride: ``(origin stop code, destination stop code,
#: stops between) -> cost``. Lower wins. The route advisor passes walk-in + ride + walk-out
#: minutes, because counting stops alone boards the rider at a stop 700 m away to save one.
RideCost = Callable[[str, str, int], float]


def _ride_order(ride: DirectLine, cost: RideCost | None = None) -> tuple[float, int, tuple[int, int, str], str]:
    """Cheapest first (fewest stops when no cost is given); ties broken by stops, line, route code.

    The tie-breakers are there so the order never wobbles between two calls with the same
    input, which an agent quoting "the first line" would otherwise turn into two answers.
    """
    primary = cost(ride.origin_stop_code, ride.destination_stop_code, ride.stops_between) if cost else ride.stops_between
    return primary, ride.stops_between, _line_sort_key(ride.line), ride.route_code


@dataclass(frozen=True)
class StopRouteIndex:
    """``stop_code`` -> the route variants calling there, inverted once and reused.

    ``load_stop_sequences`` is keyed the other way round, by route, so answering "which
    lines serve this stop?" straight from it means walking all 2,876 variants and the
    129,057 stop entries underneath them (counted in the local export on 2026-09-23). The
    route advisor asks that question for every candidate stop at both ends of a journey,
    which is why the inversion is paid once — by the tool layer, or by :func:`index_for` —
    rather than per call.

    The index is built from the sequences alone — no ``GtfsIndex``, no ``routes.csv`` — so
    it works in a process that only ever loaded the cached sequence file. Measured on the
    local export on 2026-09-23: 24.5 ms to build (median of 7), covering 2,869 named variants
    and 14,017 stop codes; one Kartal → 4.Levent scan through it then takes a median 0.49 ms
    (20 runs) inside the route advisor.
    """

    sequences: Mapping[str, RouteStopSequence]
    routes_by_stop: Mapping[str, tuple[str, ...]]
    line_by_route: Mapping[str, str]
    direction_by_route: Mapping[str, str]
    #: Route variants whose code could not be parsed into a line; dropped, never guessed.
    unnamed_routes: int = 0

    @classmethod
    def build(cls, sequences: Mapping[str, RouteStopSequence]) -> StopRouteIndex:
        routes_by_stop: dict[str, list[str]] = {}
        line_by_route: dict[str, str] = {}
        direction_by_route: dict[str, str] = {}
        unnamed = 0
        for route_code, sequence in sequences.items():
            parsed = parse_route_code(route_code)
            if parsed is None:
                unnamed += 1
                continue
            line, direction = parsed
            line_by_route[route_code] = line
            direction_by_route[route_code] = direction
            for stop_code in _positions(sequence):  # a repeated stop is indexed once
                routes_by_stop.setdefault(stop_code, []).append(route_code)
        return cls(
            sequences=sequences,
            routes_by_stop={code: tuple(routes) for code, routes in routes_by_stop.items()},
            line_by_route=line_by_route,
            direction_by_route=direction_by_route,
            unnamed_routes=unnamed,
        )

    @property
    def stop_count(self) -> int:
        return len(self.routes_by_stop)

    def __contains__(self, stop_code: object) -> bool:
        """Whether some nameable route variant calls at this stop."""
        return isinstance(stop_code, str) and bool(self.routes_serving(stop_code))

    @property
    def route_count(self) -> int:
        """Route variants this index can name; the unnamed ones are in ``unnamed_routes``."""
        return len(self.line_by_route)

    def routes_serving(self, stop_code: str) -> tuple[str, ...]:
        """Route variant codes calling at a stop, in the order the sequences were walked."""
        code = _clean_code(stop_code)
        return self.routes_by_stop.get(code, ()) if code else ()

    def lines_serving(self, stop_code: str) -> tuple[str, ...]:
        """Line codes calling at a stop, one entry per line however many variants it runs."""
        lines = {self.line_by_route[route_code] for route_code in self.routes_serving(stop_code)}
        return tuple(sorted(lines, key=_line_sort_key))

    def direct_lines(
        self,
        origin_stop_codes: Iterable[str],
        destination_stop_codes: Iterable[str],
        *,
        max_results: int = 5,
        cost: RideCost | None = None,
    ) -> list[DirectLine]:
        """Lines riding from any origin stop to any destination stop without a change.

        Ranked by ``cost`` when one is given, otherwise by stop count. The same ranking picks
        the stop pair within a variant, the variant within a line and the order of lines, so
        the first row is always the one the caller's own yardstick prefers.
        """
        origins = _clean_codes(origin_stop_codes)
        destinations = _clean_codes(destination_stop_codes)
        if not origins or not destinations or max_results <= 0:
            return []

        best_per_line: dict[str, DirectLine] = {}
        for route_code in self._routes_serving_both(origins, destinations):
            ride = self._best_ride(route_code, origins, destinations, cost)
            if ride is None:
                continue
            # One line, one row: a rider does not care that the 34 runs eleven variants,
            # only that the 34 gets them there, and in how few stops at best.
            incumbent = best_per_line.get(ride.line)
            if incumbent is None or _ride_order(ride, cost) < _ride_order(incumbent, cost):
                best_per_line[ride.line] = ride
        return sorted(best_per_line.values(), key=lambda ride: _ride_order(ride, cost))[:max_results]

    def _routes_serving_both(self, origins: tuple[str, ...], destinations: tuple[str, ...]) -> list[str]:
        """Variants touching both ends. Cheap set work first; ordering costs a scan per hit."""
        from_origin = {route for code in origins for route in self.routes_by_stop.get(code, ())}
        if not from_origin:
            return []
        to_destination = {route for code in destinations for route in self.routes_by_stop.get(code, ())}
        return sorted(from_origin & to_destination)

    def _best_ride(
        self,
        route_code: str,
        origins: tuple[str, ...],
        destinations: tuple[str, ...],
        cost: RideCost | None = None,
    ) -> DirectLine | None:
        """Cheapest forward ride this variant offers between the two sets of stops.

        Both sets are small — the stops within walking distance of a point — so every pair
        is tried rather than guessed at.
        """
        sequence = self.sequences.get(route_code)
        if sequence is None:
            return None
        positions = _positions(sequence)
        best: DirectLine | None = None
        for origin in origins:
            start = positions.get(origin)
            if start is None:
                continue
            for destination in destinations:
                end = positions.get(destination)
                if end is None:
                    continue
                # end <= start means this variant passes the destination *before* the rider
                # boards: it is not coming back on this run, whatever the map suggests.
                # This comparison is the entire reason the module exists.
                stops_between = end - start
                if stops_between < MIN_STOPS_BETWEEN:
                    continue
                candidate = DirectLine(
                    line=self.line_by_route[route_code],
                    route_code=route_code,
                    origin_stop_code=origin,
                    destination_stop_code=destination,
                    stops_between=stops_between,
                    direction=self.direction_by_route.get(route_code),
                )
                if best is None or _ride_order(candidate, cost) < _ride_order(best, cost):
                    best = candidate
        return best


#: One-slot memo: the sequences mapping last inverted, and the index built from it.
_LAST_INDEX: tuple[Mapping[str, RouteStopSequence], StopRouteIndex] | None = None


def index_for(sequences: Mapping[str, RouteStopSequence]) -> StopRouteIndex:
    """The inverted index for this mapping, built at most once per mapping object.

    One slot, matched by object identity. Identity is safe here precisely because the slot
    keeps a strong reference: a mapping that is still referenced cannot have its id reused
    by a different object. Rebuilt sequences arrive as a fresh dict and miss the memo; a
    mapping *mutated in place* would not, which is fine because ``gtfs.py`` hands out a
    newly built dict and never edits one it has handed out.

    Two threads racing here build the index twice and the later assignment wins. Both
    indexes are equal, so a lock would buy nothing but contention.
    """
    global _LAST_INDEX
    memo = _LAST_INDEX
    if memo is not None and memo[0] is sequences:
        return memo[1]
    index = StopRouteIndex.build(sequences)
    _LAST_INDEX = (sequences, index)
    return index


def lines_serving_stop(sequences: Mapping[str, RouteStopSequence], stop_code: str) -> tuple[str, ...]:
    """Line codes calling at one stop, each line once however many variants it runs.

    An unknown or blank stop code returns an empty tuple rather than raising: the caller
    usually got the code from a fuzzy name match over 15,000 stops, and "no lines" is the
    honest answer to give a rider, not an error to hand an agent mid-sentence.
    """
    return index_for(sequences).lines_serving(stop_code)


def direct_lines_between(
    sequences: Mapping[str, RouteStopSequence],
    origin_stop_codes: Iterable[str],
    destination_stop_codes: Iterable[str],
    *,
    max_results: int = 5,
    cost: RideCost | None = None,
) -> list[DirectLine]:
    """Lines that ride from any origin stop to any destination stop without a change.

    Both ends take a *set* of stop codes because a rider stands near several stops at once
    and an address resolves to whatever is within walking distance; the returned
    :class:`DirectLine` names the pair that gave the shortest ride, so the advisor can say
    which stop it means.

    Shortest ride first, one row per line, at most ``max_results`` rows. An empty list means
    exactly one thing — no single published line joins these stops in this direction — and
    it is a real answer, not a failure to find one.
    """
    return index_for(sequences).direct_lines(
        origin_stop_codes,
        destination_stop_codes,
        max_results=max_results,
        cost=cost,
    )
