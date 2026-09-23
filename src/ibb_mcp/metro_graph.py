"""The rail network as a graph — and the transfers it refuses to build.

Metro İstanbul publishes 248 stations with a line name, an order along that line and a
coordinate. That is enough to answer "can I get there on rails, and roughly how long does
it take", which is the only rail question this project asks. It is **not** a routing
engine: there is no timetable, no service pattern, no platform geometry and no direction
of travel in the feed, so every number this module produces is an estimate assembled from
distance and the handful of constants in :class:`MetroGraphParams`.

What it refuses to do:

**It will not connect two stations because they share a name.** 25 station names repeat
across lines in this dataset, forming 33 cross-line pairs, and eight of those pairs are
more than 800 m apart — different places wearing the same word. Bahariye is on T3 in
Kadıköy *and* on M9 in Bağcılar, 20.7 km and a strait apart. A graph built on name
equality "connects" Kadıköy to Taksim in 64 minutes by teleporting across the Bosphorus
there and again between the two Yenimahalle stations (M3/M7, 6.8 km apart) — reproduced on
2026-09-23 by letting every same-name pair transfer for free — and it does so silently,
which is the worst failure mode available to us. So a transfer edge is justified by **distance** and
nothing else: the same station hall, or a walk short enough that a person would really
make it. Every same-name pair that fails the test is kept in
:attr:`MetroGraph.rejected_transfers`, so the refusal is visible instead of invisible.

**It will not invent a Bosphorus crossing.** Marmaray, the Metrobüs and the ferries are
not in this feed — it is Metro İstanbul's own network only. Built from the feed alone the
graph has no rail link between the two sides of the city, and Kadıköy → Taksim correctly
comes back as ``reason="disconnected"``. A caller who wants the crossing must bring that
data as rows it vouches for (``added=`` in :meth:`MetroGraph.from_stations`), and those
rows are then named in :meth:`MetroGraph.assumptions`. :func:`marmaray_tube` builds the one
such line this project uses, from four stations the feed already has.

**It will not pretend a station without coordinates exists.** Three of the 248 rows carry
no position (the M5 Sultanbeyli extension); they are dropped and counted in
:attr:`MetroGraph.dropped_stations` rather than joined by guesswork. They sit at the end
of their line, so nothing is bridged over them — a station dropped from the *middle* of a
line would silently make its two neighbours adjacent, which is why the count is published.

Cost model: Dijkstra over **seconds**. A ride between neighbouring stations is the
great-circle distance divided by a per-mode speed, plus a dwell; the straight line
understates real track, and the speeds were chosen so whole journeys land in the right
place rather than each hop. The one check against a published figure this repository can
cite: Metro İstanbul's own description of M7 (the ``LineContent`` of the M7 notice in
``tests/fixtures/metro_status.json``) gives a 36-minute one-way run over 17 stations, and
the graph gives 38.9 minutes Yıldız → Mahmutbey over the same 17 (16 hops). The branch
that wrote this module also quoted Kartal → Kadıköy, Yenikapı → Taksim and Levent →
Yenikapı against "about 40, 9 and 20 real minutes"; no source for those three is in the
repository, so they are not claimed here. The constants are one calibration, not
independent knobs — moving one moves every journey, so retune them together.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from itertools import combinations

from ibb_mcp.models import MetroStation, haversine_km
from ibb_mcp.sources.metro import normalize_tr, rank_match_loose, squash_punctuation


@dataclass(frozen=True)
class MetroGraphParams:
    """Tunable constants. Every one is an assumption, and every one is disclosed.

    The three walking thresholds are the whole phantom defence. ``in_station_transfer_km``
    is "one station hall, change platform". ``max_named_walk_km`` is generous because two
    stops that agree on a name usually are one interchange split by a street — Aksaray M1A
    to Aksaray T1 is a real 557 m walk thousands of people make daily.
    ``max_unnamed_walk_km`` is tight because a differing name is no evidence at all, so
    only near-touching platforms qualify. Beyond the applicable threshold there is no edge,
    however the two stations happen to be spelled.
    """

    metro_speed_kmh: float = 35.0
    tram_speed_kmh: float = 17.0
    funicular_speed_kmh: float = 12.0
    dwell_seconds: float = 25.0
    #: Time lost changing service: walking the passage plus waiting for the next train.
    transfer_seconds: float = 240.0
    walk_speed_kmh: float = 4.5
    in_station_transfer_km: float = 0.25
    max_named_walk_km: float = 0.8
    max_unnamed_walk_km: float = 0.35
    #: Furthest we will walk from a point to a station before calling it unreachable.
    access_walk_km: float = 1.2
    #: Half of an assumed 6-minute headway, charged once for the first boarding.
    mean_wait_seconds: float = 180.0


DEFAULT_METRO_PARAMS = MetroGraphParams()

#: Kilometres in one degree of latitude, near enough anywhere. Used only to widen a search
#: window, never to measure anything — :func:`~ibb_mcp.models.haversine_km` does that.
KM_PER_LATITUDE_DEGREE = 111.0

#: The line name the Marmaray rows carry. Read as a metro by :func:`mode_for_line`.
MARMARAY_LINE = "Marmaray"

#: The Marmaray tube section, west to east, as the four stations it shares with lines that
#: *are* in Metro İstanbul's feed: Yenikapı (M1A, M1B, M2), Sirkeci (T1), Üsküdar (M5) and
#: Ayrılık Çeşmesi (M4). These are the same anchors the route advisor used before this graph
#: existed. Only the tube is modelled: Marmaray's suburban stretches towards Halkalı and
#: Gebze stop at stations the feed does not carry, so a journey that needs them is still
#: refused rather than approximated.
MARMARAY_TUBE: tuple[str, ...] = ("Yenikapı", "Sirkeci", "Üsküdar", "Ayrılık Çeşmesi")

#: Every reason a result can carry no path, so callers can branch on a name rather than
#: on a string they hope is spelled the same way here.
PATH_FAILURE_REASONS = (
    "unknown_origin",
    "unknown_destination",
    "no_station_near_origin",
    "no_station_near_destination",
    "disconnected",
)


@dataclass(frozen=True)
class MetroLeg:
    """One step of a journey. ``stops`` is 1 on a ride and 0 on everything else.

    Rides are emitted one per station hop instead of merged into "M4 ×15", because merging
    throws the intermediate station names away: a caller who wants the summary can count
    legs, a caller who wants the stations cannot get them back.
    """

    kind: str
    line: str | None
    from_station: str
    to_station: str
    stops: int
    seconds: float
    km: float | None = None


@dataclass(frozen=True)
class MetroPath:
    legs: tuple[MetroLeg, ...]
    total_seconds: float
    ride_seconds: float
    wait_seconds: float
    transfer_count: int
    lines: tuple[str, ...]
    stop_count: int


@dataclass(frozen=True)
class RejectedTransfer:
    """A same-name pair that distance disqualified — the phantom log.

    Published rather than swallowed: it is the evidence that the graph declined a
    connection on purpose, and the list is short enough to read out, with Bahariye T3/M9
    at 20.7 km as its headline entry.
    """

    name: str
    line_a: str
    line_b: str
    km: float


@dataclass(frozen=True)
class MetroPathResult:
    """A path, or a named reason there is none — never both, never neither."""

    path: MetroPath | None
    reason: str | None


@dataclass(frozen=True)
class _Edge:
    """A traversable connection. ``line`` is the service you are on *after* taking it."""

    to_node: int
    kind: str
    line: str | None
    seconds: float
    km: float


def mode_for_line(line: str) -> str:
    """Rolling stock implied by the line code: ``F``/``TF`` funicular, ``T`` tram, else metro.

    ``TF`` is named next to ``F`` because TF1 and TF2 are funiculars whose code begins with
    a T; reading them as trams would run a 600 m cable haul at 17 km/h.
    """
    upper = line.upper()
    if upper.startswith(("F", "TF")):
        return "funicular"
    if upper.startswith("T"):
        return "tram"
    return "metro"


def _speed_for(line: str, params: MetroGraphParams) -> float:
    speeds = {
        "funicular": params.funicular_speed_kmh,
        "tram": params.tram_speed_kmh,
        "metro": params.metro_speed_kmh,
    }
    return speeds[mode_for_line(line)]


def _point_label(lat: float, lon: float) -> str:
    """A coordinate as a leg endpoint, so an access leg can say where it actually started."""
    return f"{lat:.5f},{lon:.5f}"


class MetroGraph:
    """Stations, the edges distance justifies between them, and shortest paths over seconds.

    Built once from a list of stations, then read-only — building it per request is
    affordable, and caching it is an optimisation rather than a requirement. Nothing here
    mutates after construction, so one graph can be shared by concurrent callers.
    """

    def __init__(
        self,
        stations: Sequence[MetroStation],
        edges: Sequence[tuple[_Edge, ...]],
        rejected: Sequence[RejectedTransfer],
        dropped: int,
        params: MetroGraphParams,
        added_lines: Sequence[str] = (),
    ) -> None:
        self._stations = tuple(stations)
        self._edges = tuple(edges)
        self._rejected = tuple(rejected)
        self._dropped = dropped
        self._params = params
        self._lines = tuple(sorted({s.line_name for s in self._stations if s.line_name}))
        self._added_lines = tuple(added_lines)

    # -- construction ------------------------------------------------------------------
    @classmethod
    def from_stations(
        cls,
        stations: Sequence[MetroStation],
        *,
        params: MetroGraphParams = DEFAULT_METRO_PARAMS,
        added: Sequence[MetroStation] = (),
    ) -> MetroGraph:
        """Build the graph. Pure: nothing is read from disk and nothing is fetched.

        ``added`` holds rows the caller vouches for that Metro İstanbul does not publish —
        in practice :func:`marmaray_tube`. They go through exactly the same edge rules as
        the feed's own rows, so an added line gains a transfer only where distance
        justifies one, and its line names are disclosed by :meth:`assumptions`.
        """
        usable: list[MetroStation] = []
        dropped = 0
        for station in (*stations, *added):
            if station.lat is None or station.lon is None or not station.line_name or station.order is None:
                dropped += 1
                continue
            usable.append(station)
        usable.sort(key=lambda s: (s.line_name or "", s.order or 0))

        edges: list[list[_Edge]] = [[] for _ in usable]
        cls._add_ride_edges(usable, edges, params)
        rejected = cls._add_transfer_edges(usable, edges, params)
        added_lines = sorted({row.line_name for row in added if row.line_name})
        return cls(usable, [tuple(row) for row in edges], rejected, dropped, params, added_lines)

    @staticmethod
    def _add_ride_edges(stations: Sequence[MetroStation], edges: list[list[_Edge]], params: MetroGraphParams) -> None:
        """Join each station to its neighbour in ``Order`` along the same line, both ways.

        Direction is not modelled. ``Order`` implies one, but a rider travels either way
        along a line, so both directions cost the same and a path may run up the order or
        down it.
        """
        by_line: dict[str, list[int]] = {}
        for index, station in enumerate(stations):
            by_line.setdefault(station.line_name or "", []).append(index)
        for line, indices in by_line.items():
            speed = _speed_for(line, params)
            ordered = sorted(indices, key=lambda i: stations[i].order or 0)
            for left, right in zip(ordered, ordered[1:], strict=False):
                a, b = stations[left], stations[right]
                km = haversine_km(a.lat or 0.0, a.lon or 0.0, b.lat or 0.0, b.lon or 0.0)
                seconds = km / speed * 3600.0 + params.dwell_seconds
                edges[left].append(_Edge(right, "ride", line, seconds, km))
                edges[right].append(_Edge(left, "ride", line, seconds, km))

    @staticmethod
    def _transfer_candidates(
        stations: Sequence[MetroStation],
        keys: Sequence[str],
        params: MetroGraphParams,
    ) -> list[tuple[int, int]]:
        """Pairs worth measuring: geometric neighbours, plus every pair that shares a name.

        Measuring all thirty thousand pairs of a 245-station network is waste — a few dozen
        are ever close enough to walk. Sorting by latitude and stopping once the latitude gap
        alone exceeds the longest walk we allow cannot drop a real neighbour, because the
        north-south part of a distance is never larger than the distance itself.

        Same-name pairs are then added whatever their latitudes, because those are precisely
        the ones that need a recorded verdict and Bahariye T3/M9 sits 20.7 km outside any
        geometric window. Losing one of those to an optimisation is the bug this whole module
        exists to prevent.
        """
        reach = max(params.in_station_transfer_km, params.max_named_walk_km, params.max_unnamed_walk_km)
        reach_degrees = reach / KM_PER_LATITUDE_DEGREE
        pairs: set[tuple[int, int]] = set()

        by_name: dict[str, list[int]] = {}
        for index, key in enumerate(keys):
            if key:
                by_name.setdefault(key, []).append(index)
        for indices in by_name.values():
            pairs.update(combinations(indices, 2))

        by_latitude = sorted(range(len(stations)), key=lambda i: stations[i].lat or 0.0)
        for position, left in enumerate(by_latitude):
            for right in by_latitude[position + 1 :]:
                if (stations[right].lat or 0.0) - (stations[left].lat or 0.0) > reach_degrees:
                    break
                pairs.add((left, right) if left < right else (right, left))
        return sorted(pairs)

    @classmethod
    def _add_transfer_edges(
        cls,
        stations: Sequence[MetroStation],
        edges: list[list[_Edge]],
        params: MetroGraphParams,
    ) -> list[RejectedTransfer]:
        """Measure every candidate cross-line pair and connect only the ones distance allows.

        A shared name buys a *longer* allowance; it never buys an edge by itself. The
        rejected list records same-name pairs only: two differently named stations six
        kilometres apart are not a phantom transfer anyone would claim, they are simply two
        stations, and logging all of those would bury the eight that matter.
        """
        rejected: list[RejectedTransfer] = []
        keys = [squash_punctuation(normalize_tr(s.name)) for s in stations]
        for left, right in cls._transfer_candidates(stations, keys, params):
            a, b = stations[left], stations[right]
            if a.line_name == b.line_name:
                continue
            km = haversine_km(a.lat or 0.0, a.lon or 0.0, b.lat or 0.0, b.lon or 0.0)
            same_name = bool(keys[left]) and keys[left] == keys[right]
            if km <= params.in_station_transfer_km:
                kind, seconds = "transfer", params.transfer_seconds
            elif km <= (params.max_named_walk_km if same_name else params.max_unnamed_walk_km):
                kind = "walk"
                seconds = km / params.walk_speed_kmh * 3600.0 + params.transfer_seconds
            else:
                if same_name:
                    rejected.append(
                        RejectedTransfer(
                            name=a.name or "",
                            line_a=a.line_name or "",
                            line_b=b.line_name or "",
                            km=round(km, 3),
                        )
                    )
                continue
            edges[left].append(_Edge(right, kind, b.line_name, seconds, km))
            edges[right].append(_Edge(left, kind, a.line_name, seconds, km))
        rejected.sort(key=lambda row: -row.km)
        return rejected

    # -- inspection --------------------------------------------------------------------
    @property
    def lines(self) -> tuple[str, ...]:
        return self._lines

    @property
    def station_count(self) -> int:
        """Stations the graph can actually route over, not rows received."""
        return len(self._stations)

    @property
    def dropped_stations(self) -> int:
        """Rows discarded for want of a coordinate, a line name or an order."""
        return self._dropped

    @property
    def params(self) -> MetroGraphParams:
        return self._params

    @property
    def rejected_transfers(self) -> tuple[RejectedTransfer, ...]:
        """Same-name pairs distance disqualified, furthest apart first."""
        return self._rejected

    @property
    def added_lines(self) -> tuple[str, ...]:
        """Lines the caller supplied that are not in Metro İstanbul's feed."""
        return self._added_lines

    def find_stations(self, name: str) -> list[MetroStation]:
        """Turkish- and punctuation-insensitive lookup, best matches first.

        Shares :func:`~ibb_mcp.sources.metro.rank_match_loose` with the station search tool,
        so "4. Levent", "4.Levent" and "4 levent" land on the same platform in both places.
        Every line carrying the name is returned: an interchange is several rows.
        """
        return [self._stations[index] for _, index in self._ranked(name)]

    def stations_near(
        self,
        lat: float,
        lon: float,
        *,
        radius_km: float | None = None,
    ) -> list[tuple[MetroStation, float]]:
        """Stations within ``radius_km`` (default ``access_walk_km``), nearest first.

        Straight-line distance, so it cannot see the hill, the motorway or the shoreline
        between the point and the platform. Read the kilometres as a lower bound.
        """
        return [(self._stations[index], km) for index, km in self._near(lat, lon, radius_km)]

    def assumptions(self) -> dict[str, float | str]:
        """Every constant behind a path, for the disclosure the tool layer has to print."""
        values: dict[str, float | str] = {field.name: getattr(self._params, field.name) for field in fields(MetroGraphParams)}
        values["method"] = "dijkstra over estimated seconds; great-circle distance, no timetable"
        values["mode_by_line_prefix"] = "F/TF funicular, T tram, otherwise metro"
        values["transfer_rule"] = "transfers are justified by distance only; a shared station name is never enough"
        if self._added_lines:
            added = ", ".join(self._added_lines)
            values["network"] = (
                f"Metro İstanbul rail plus {added}, which the caller added from stations already in the feed; "
                "no Metrobüs or ferry"
            )
        else:
            values["network"] = "Metro İstanbul rail only — no Marmaray, Metrobüs or ferry, so no Bosphorus crossing"
        return values

    # -- paths -------------------------------------------------------------------------
    def path_between_stations(self, origin: str, destination: str) -> MetroPathResult:
        """Cheapest ride between two named stations, or the reason there is none.

        Either name may resolve to several platforms — Yenikapı is on M1A, M1B and M2. All
        of them are searched at once and the cheapest pairing wins, because that is what the
        rider meant: they said "Yenikapı", not "the M1B platform at Yenikapı".

        No waiting time is charged. The question was station to station; how long they stand
        on the platform first depends on when they arrive, and the figures this model was
        calibrated against are in-vehicle times.
        """
        sources = self._endpoints(origin)
        if not sources:
            return MetroPathResult(path=None, reason="unknown_origin")
        targets = self._endpoints(destination)
        if not targets:
            return MetroPathResult(path=None, reason="unknown_destination")

        solved = self._solve({node: 0.0 for node in sources}, {node: 0.0 for node in targets})
        if solved is None:
            return MetroPathResult(path=None, reason="disconnected")
        legs, _, _ = solved
        return MetroPathResult(path=_assemble(legs, 0.0), reason=None)

    def path_between_points(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
    ) -> MetroPathResult:
        """Door to door: walk to a station, ride, walk off.

        The access and egress legs are straight-line walks at ``walk_speed_kmh`` — no
        pavement, no crossing, no climb out of the station — and one ``mean_wait_seconds``
        is charged for the first boarding. Every station inside ``access_walk_km`` is a
        candidate at both ends, so the search can spend a longer walk on a much faster line
        instead of being pinned to whatever happens to be closest.
        """
        near_origin = self._near(*origin)
        if not near_origin:
            return MetroPathResult(path=None, reason="no_station_near_origin")
        near_destination = self._near(*destination)
        if not near_destination:
            return MetroPathResult(path=None, reason="no_station_near_destination")

        origin_km = dict(near_origin)
        destination_km = dict(near_destination)
        sources = {node: self._walk_seconds(km) for node, km in near_origin}
        targets = {node: self._walk_seconds(km) for node, km in near_destination}
        solved = self._solve(sources, targets)
        if solved is None:
            return MetroPathResult(path=None, reason="disconnected")

        legs, start, end = solved
        access = MetroLeg(
            kind="access",
            line=None,
            from_station=_point_label(*origin),
            to_station=self._name(start),
            stops=0,
            seconds=round(sources[start], 1),
            km=round(origin_km[start], 3),
        )
        egress = MetroLeg(
            kind="egress",
            line=None,
            from_station=self._name(end),
            to_station=_point_label(*destination),
            stops=0,
            seconds=round(targets[end], 1),
            km=round(destination_km[end], 3),
        )
        wait = self._params.mean_wait_seconds if any(leg.kind == "ride" for leg in legs) else 0.0
        return MetroPathResult(path=_assemble((access, *legs, egress), wait), reason=None)

    # -- internals ---------------------------------------------------------------------
    def _name(self, node: int) -> str:
        return self._stations[node].name or ""

    def _walk_seconds(self, km: float) -> float:
        return km / self._params.walk_speed_kmh * 3600.0

    def _near(self, lat: float, lon: float, radius_km: float | None = None) -> list[tuple[int, float]]:
        limit = self._params.access_walk_km if radius_km is None else radius_km
        found = [
            (index, km)
            for index, station in enumerate(self._stations)
            if (km := haversine_km(lat, lon, station.lat or 0.0, station.lon or 0.0)) <= limit
        ]
        found.sort(key=lambda row: row[1])
        return found

    def _ranked(self, name: str) -> list[tuple[int, int]]:
        """``(rank, station index)`` for every station whose name matches, best first."""
        query = normalize_tr(name)
        if not query:
            return []
        loose = squash_punctuation(query)
        scored: list[tuple[int, str, int, int]] = []
        for index, station in enumerate(self._stations):
            rank = rank_match_loose(query, loose, station.name)
            if rank is None:
                continue
            scored.append((rank, station.line_name or "", station.order or 0, index))
        scored.sort()
        return [(row[0], row[3]) for row in scored]

    def _endpoints(self, name: str) -> list[int]:
        """Only the best-ranked matches are journey endpoints.

        "Levent" also matches "4.Levent" as a substring, which is helpful when someone is
        browsing station names and wrong when they are naming where they stand. Keeping only
        the top rank means an exact name never competes with a station that merely contains
        it, while a genuine interchange still contributes all of its platforms.
        """
        ranked = self._ranked(name)
        if not ranked:
            return []
        best = ranked[0][0]
        return [index for rank, index in ranked if rank == best]

    def _solve(
        self,
        sources: Mapping[int, float],
        targets: Mapping[int, float],
    ) -> tuple[list[MetroLeg], int, int] | None:
        """Legs of the cheapest source-to-target journey, plus the nodes it entered and left.

        The whole graph is relaxed instead of stopping at the first target popped, because a
        target carries an exit cost — the egress walk — so the nearest one is not necessarily
        the cheapest one. At 245 nodes that is not worth being clever about.
        """
        distance, came_from = self._relax(sources)
        reachable = [(distance[node] + exit_cost, node) for node, exit_cost in targets.items() if node in distance]
        if not reachable:
            return None

        _, best = min(reachable)
        chain: list[tuple[int, _Edge]] = []
        cursor = best
        while cursor in came_from:
            previous, edge = came_from[cursor]
            chain.append((previous, edge))
            cursor = previous
        chain.reverse()

        legs = [
            MetroLeg(
                kind=edge.kind,
                line=edge.line,
                from_station=self._name(previous),
                to_station=self._name(edge.to_node),
                stops=1 if edge.kind == "ride" else 0,
                seconds=round(edge.seconds, 1),
                km=round(edge.km, 3),
            )
            for previous, edge in chain
        ]
        # An empty chain means the cheapest target was itself a source: the rider is already
        # there. That is a real answer — zero legs — not a failure.
        return legs, (chain[0][0] if chain else best), best

    def _relax(self, sources: Mapping[int, float]) -> tuple[dict[int, float], dict[int, tuple[int, _Edge]]]:
        distance: dict[int, float] = dict(sources)
        came_from: dict[int, tuple[int, _Edge]] = {}
        queue: list[tuple[float, int]] = [(cost, node) for node, cost in sources.items()]
        heapq.heapify(queue)
        while queue:
            cost, node = heapq.heappop(queue)
            if cost > distance.get(node, float("inf")):
                continue
            for edge in self._edges[node]:
                candidate = cost + edge.seconds
                if candidate < distance.get(edge.to_node, float("inf")):
                    distance[edge.to_node] = candidate
                    came_from[edge.to_node] = (node, edge)
                    heapq.heappush(queue, (candidate, edge.to_node))
        return distance, came_from


def _lines_used(legs: Iterable[MetroLeg]) -> tuple[str, ...]:
    """Services touched, in order and deduplicated; a transfer leg names the line it delivers to."""
    seen: list[str] = []
    for leg in legs:
        if leg.line and leg.line not in seen:
            seen.append(leg.line)
    return tuple(seen)


def _assemble(legs: Sequence[MetroLeg], wait_seconds: float) -> MetroPath:
    return MetroPath(
        legs=tuple(legs),
        total_seconds=round(sum(leg.seconds for leg in legs) + wait_seconds, 1),
        ride_seconds=round(sum(leg.seconds for leg in legs if leg.kind == "ride"), 1),
        wait_seconds=wait_seconds,
        transfer_count=sum(1 for leg in legs if leg.kind in ("transfer", "walk")),
        lines=_lines_used(legs),
        stop_count=sum(leg.stops for leg in legs),
    )


def marmaray_tube(stations: Sequence[MetroStation]) -> list[MetroStation]:
    """Rows for the Marmaray tube, placed on the coordinates of stations the feed already has.

    Each :data:`MARMARAY_TUBE` name is looked up with the same Turkish- and punctuation-
    insensitive folding as :meth:`MetroGraph.find_stations`, and its first platform with a
    coordinate lends the Marmaray row its position. Sharing the coordinate is what turns
    Yenikapı M2 → Marmaray into an in-station transfer under the ordinary distance rule,
    without a special case. The rows carry no ``station_id``: they are not Metro İstanbul's
    records and must not be mistaken for them.

    Returns an empty list when fewer than two anchors resolve, because one station is not a
    line. With a partial list the tube simply ends early, and a crossing that needed the
    missing anchor comes back ``disconnected`` — the honest reading of a thinner feed.
    """
    by_key: dict[str, MetroStation] = {}
    for station in stations:
        if station.lat is None or station.lon is None:
            continue
        by_key.setdefault(squash_punctuation(normalize_tr(station.name)), station)
    rows: list[MetroStation] = []
    for name in MARMARAY_TUBE:
        found = by_key.get(squash_punctuation(normalize_tr(name)))
        if found is None:
            continue
        rows.append(MetroStation(name=found.name, line_name=MARMARAY_LINE, order=len(rows) + 1, lat=found.lat, lon=found.lon))
    return rows if len(rows) >= 2 else []
