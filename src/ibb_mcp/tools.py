"""The tool layer: one façade that turns sources into answers an agent can cite.

Every method returns a :class:`ToolResult` whose ``data`` is plain JSON-friendly types and
whose ``provenance`` carries the source URL and the age of the reading. That envelope is
what makes the numeric-faithfulness check in the eval harness possible: the agent may only
say a number that appears in a tool result.

Tools are deliberately parametric. There is no free-form query tool and no natural-language
to KQL/SQL path, because a tool the model can shape arbitrarily is a tool whose output
nobody can verify.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import enum
import logging
import os
import pathlib
import time
from collections.abc import Mapping
from typing import Any

from ibb_mcp.config import ATTRIBUTION, ATTRIBUTION_EN, REPO_ROOT, Settings
from ibb_mcp.models import (
    ISTANBUL_TZ,
    LAT_RANGE,
    LON_RANGE,
    Provenance,
    ToolResult,
    aqi_band,
    day_type_for,
    describe_traffic,
    utcnow,
)
from ibb_mcp.sources.base import SourceContext, make_provenance
from ibb_mcp.sources.places import Place, get_place_index
from ibb_mcp.timetables import ScheduleTables

log = logging.getLogger("ibb_mcp.tools")

#: Days of hourly traffic history behind the weekday × hour baseline: four whole weeks, so
#: every cell gets four samples, one above the floor in :mod:`ibb_mcp.traffic_profile`. The
#: charter records the endpoint serving 30 days hourly (docs/NABIZ.md, verified 2026-09-08).
TRAFFIC_BASELINE_DAYS = 28

#: How long a built baseline is reused. Four weeks of history barely move in six hours, and
#: each rebuild is one more request against the gateway the collector shares.
TRAFFIC_BASELINE_TTL_SECONDS = 6 * 3600.0

#: After a failed history read, how long to answer "no baseline" before asking again, so a
#: failing endpoint is not retried on every journey question.
TRAFFIC_BASELINE_RETRY_SECONDS = 15 * 60.0

#: How many name matches ``iett_next_arrivals`` weighs before choosing its target stop.
#: A name is rarely unique: "Şifa" matches stops in Sarıyer and in Tuzla, and only one of
#: them is on the 500T. The search scans every stop whatever the limit, so a generous
#: shortlist costs nothing measurable.
STOP_CANDIDATES = 50


def _dump(model: Any) -> Any:
    """Serialise a tool payload to JSON-friendly types.

    Handles the three shapes this codebase produces: pydantic models (the İBB sources),
    dataclasses (routing, reliability, alerts) and plain containers. Everything a tool
    returns crosses a JSON boundary, so an unserialisable object is a runtime failure in
    the MCP layer rather than a type error at the call site — hence the breadth here.
    """
    if isinstance(model, list | tuple):
        return [_dump(item) for item in model]
    if isinstance(model, dict):
        return {key: _dump(value) for key, value in model.items()}
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", exclude_none=True)
    if dataclasses.is_dataclass(model) and not isinstance(model, type):
        return {key: _dump(value) for key, value in dataclasses.asdict(model).items() if value is not None}
    if isinstance(model, dt.date):  # datetime is a date too, and both isoformat cleanly
        return model.isoformat()
    if isinstance(model, enum.Enum):
        return model.value
    return model


def _local_url(path: pathlib.Path | str) -> str:
    """Cite a local derived file without saying where this checkout lives.

    Provenance goes to every client. An absolute path would put the machine's user name
    into it, so a file inside the repository is cited repo-relative and anything else
    (an ``NABIZ_*`` override pointing at a mounted volume) by its file name alone.
    ``os.path.abspath`` rather than ``Path.resolve`` because this is string work: it must
    not touch the filesystem to describe a file that may not exist.
    """
    absolute = pathlib.Path(os.path.abspath(path))
    try:
        return f"local:{absolute.relative_to(REPO_ROOT).as_posix()}"
    except ValueError:
        return f"local:{absolute.name}"


def _check_weekday_hour(weekday: int | None, hour: int | None) -> None:
    """Refuse an impossible slot instead of quietly wrapping it.

    ``occupancy.lookup_weekday`` reduces the weekday modulo 7, so weekday=7 would come back
    as Monday — a plausible answer to a question nobody asked.
    """
    if weekday is not None and not 0 <= weekday <= 6:
        raise ValueError("weekday 0 (Pazartesi) ile 6 (Pazar) arasında olmalı.")
    if hour is not None and not 0 <= hour <= 23:
        raise ValueError("hour 0 ile 23 arasında, İstanbul saatiyle olmalı.")


def _in_istanbul(lat: float, lon: float) -> bool:
    return LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]


class Nabiz:
    """Holds one context and one instance of each source for the process lifetime."""

    def __init__(self, ctx: SourceContext | None = None) -> None:
        self.ctx = ctx or SourceContext.create()
        self.settings: Settings = self.ctx.settings
        self.places = get_place_index(self.settings)
        self._sources: dict[str, Any] = {}
        self._gtfs = None
        self._gtfs_lock = asyncio.Lock()
        # A separate lock: loading sequences may need the GTFS index, and asyncio.Lock is
        # not re-entrant, so sharing ``_gtfs_lock`` would deadlock the first caller.
        self._sequences: dict[str, Any] | None = None
        self._stop_routes: Any = None  # ibb_mcp.lines.StopRouteIndex, built on first use
        self._sequences_lock = asyncio.Lock()
        self._schedule_tables = ScheduleTables()  # GTFS departures + service days, for the arrival fallback
        # (monotonic expiry, baseline or None, the history read's provenance or None): see
        # traffic_baseline_with_provenance().
        self._traffic_baseline: tuple[float, Any, Provenance | None] | None = None
        self._traffic_baseline_lock = asyncio.Lock()

    # -- lazy source construction -------------------------------------------------
    def _source(self, name: str):
        """Import sources lazily so a broken optional module cannot break the server."""
        if name not in self._sources:
            if name == "ispark":
                from ibb_mcp.sources.ispark import IsparkSource

                self._sources[name] = IsparkSource(self.ctx)
            elif name == "iett":
                from ibb_mcp.sources.iett import IettSource

                self._sources[name] = IettSource(self.ctx)
            elif name == "metro":
                from ibb_mcp.sources.metro import MetroSource

                self._sources[name] = MetroSource(self.ctx)
            elif name == "metro_equipment":
                from ibb_mcp.sources.metro_equipment import MetroEquipmentSource

                self._sources[name] = MetroEquipmentSource(self.ctx)
            elif name == "traffic":
                from ibb_mcp.sources.traffic import TrafficSource

                self._sources[name] = TrafficSource(self.ctx)
            elif name == "aq":
                from ibb_mcp.sources.airquality import AirQualitySource

                self._sources[name] = AirQualitySource(self.ctx)
            else:  # pragma: no cover - programming error
                raise KeyError(name)
        return self._sources[name]

    async def gtfs(self):
        """Load the GTFS index once, off the event loop (it parses a 1.5 MB CSV)."""
        if self._gtfs is None:
            async with self._gtfs_lock:
                if self._gtfs is None:
                    from ibb_mcp.gtfs import get_index

                    self._gtfs = await asyncio.to_thread(get_index, self.settings)
        return self._gtfs

    async def stop_sequences(self) -> dict[str, Any]:
        """Route stop orders, read once per process and off the event loop.

        Reading the cached ``route_sequences.json.gz`` on every request was cheap only while
        the cache existed: without it ``load_stop_sequences`` rebuilds from a 150 MB
        ``stop_times.txt``, per request. An empty result (no GTFS on this machine) is cached
        too — like :func:`ibb_mcp.gtfs.get_index`, a fresh download needs a restart.
        """
        if self._sequences is None:
            async with self._sequences_lock:
                if self._sequences is None:
                    from ibb_mcp.gtfs import load_stop_sequences

                    self._sequences = await asyncio.to_thread(load_stop_sequences, self.settings)
        return self._sequences

    async def stop_routes(self):
        """The stop -> route-variant index (:class:`ibb_mcp.lines.StopRouteIndex`), built once.

        One inversion of the sequences serves both the route advisor's direct-line scan and
        the "which lines do stop here" hint of ``iett_next_arrivals``. ``stop_code in index``
        answers whether any nameable variant calls there.
        """
        if self._stop_routes is None:
            from ibb_mcp.lines import StopRouteIndex

            sequences = await self.stop_sequences()
            self._stop_routes = await asyncio.to_thread(StopRouteIndex.build, sequences)
        return self._stop_routes

    async def traffic_baseline(self):
        """The weekday × hour median of the traffic index, from İBB's own history, or ``None``."""
        baseline, _ = await self.traffic_baseline_with_provenance()
        return baseline

    async def traffic_baseline_with_provenance(self) -> tuple[Any, Provenance | None]:
        """The traffic baseline and the provenance of the history read it was built from.

        Built from one ``TrafficIndexHistory/28/H`` read and reused for
        :data:`TRAFFIC_BASELINE_TTL_SECONDS`. The last 24 hours are left out of it, because
        the newest point is the reading about to be judged and must not vote in its own
        yardstick. A failed read returns ``(None, None)`` — the callers then say the
        comparison is unavailable — and is not retried for :data:`TRAFFIC_BASELINE_RETRY_SECONDS`.

        The provenance is kept with the memo because the "usually at this hour" figure is a
        number the user hears, and every such number carries its source and age. Its age is
        computed when it is read, so a baseline reused for hours says so.
        """
        memo = self._traffic_baseline
        if memo is not None and time.monotonic() < memo[0]:
            return memo[1], memo[2]
        async with self._traffic_baseline_lock:
            memo = self._traffic_baseline
            if memo is not None and time.monotonic() < memo[0]:
                return memo[1], memo[2]
            from ibb_mcp.traffic_profile import build_baseline

            try:
                points, prov = await self._source("traffic").index_history(days=TRAFFIC_BASELINE_DAYS, period="H")
            except Exception as exc:  # noqa: BLE001 - a missing baseline is reported, never fatal
                log.info("traffic history unavailable for the baseline: %r", exc)
                self._traffic_baseline = (time.monotonic() + TRAFFIC_BASELINE_RETRY_SECONDS, None, None)
                return None, None
            newest = max((point.at for point in points if point.at is not None), default=None)
            cutoff = newest - dt.timedelta(hours=24) if newest is not None else None
            baseline = build_baseline(points, before=cutoff)
            self._traffic_baseline = (time.monotonic() + TRAFFIC_BASELINE_TTL_SECONDS, baseline, prov)
            return baseline, prov

    async def aclose(self) -> None:
        await self.ctx.aclose()

    # -- helpers ------------------------------------------------------------------
    def _resolve_place(self, query: str) -> Place:
        place = self.places.resolve_one(query)
        if place is None:
            raise ValueError(
                f"'{query}' için bir yer bulamadım. Semt, ilçe veya metro istasyonu adı deneyin "
                "(örnek: Taksim, Kadıköy, Levent)."
            )
        return place

    def _endpoint(self, name: str | None, lat: float | None, lon: float | None, *, role: str) -> Any:
        """One end of a journey, from a place name or from coordinates, never half of each.

        Coordinates win when both are given, because they are what ``places_resolve``
        hands onward; the name then only labels them. One coordinate without the other is
        refused rather than paired with a guess.
        """
        from ibb_mcp.routing import Waypoint

        if (lat is None) != (lon is None):
            raise ValueError(f"{role}_lat ve {role}_lon birlikte verilmeli.")
        if lat is not None and lon is not None:
            if not _in_istanbul(lat, lon):
                raise ValueError(f"{role} koordinatı İstanbul sınırları dışında; bu servis yalnızca İstanbul verisi sunar.")
            return Waypoint(name.strip() if name and name.strip() else f"{lat:.4f}, {lon:.4f}", float(lat), float(lon))
        if not name or not name.strip():
            raise ValueError(f"{role} için bir yer adı ya da {role}_lat/{role}_lon vermelisiniz.")
        place = self._resolve_place(name)
        return Waypoint(place.label, place.lat, place.lon)

    @staticmethod
    def _attribution() -> dict[str, str]:
        return {"tr": ATTRIBUTION, "en": ATTRIBUTION_EN}

    @staticmethod
    def _route_codes_for(line_code: str, buses: list[Any], index: Any) -> list[str]:
        """Route variants a line runs, from live vehicles first and GTFS as backup."""
        codes = {bus.route_code for bus in buses if bus.route_code}
        if not codes:
            codes = {r.route_code for r in index.routes_for_short_name(line_code) if r.route_code}
        return sorted(codes)

    async def _lines_serving(self, stop_code: str, limit: int = 8) -> list[str]:
        """Which lines do call at this stop, so a refusal can still be useful.

        Read from the prebuilt stop index rather than by scanning every route variant, which
        also means every serving line is seen before the list is cut: the old scan stopped at
        the first ``limit`` names it met in dictionary order. Alphabetical order is kept
        because the refusal wording is pinned by ``tests/test_web.py``.
        """
        index = await self.stop_routes()
        return sorted(index.lines_serving(stop_code))[:limit]

    # -- 1. places ----------------------------------------------------------------
    async def places_resolve(self, query: str, limit: int = 5) -> ToolResult:
        """Turn a place name into coordinates."""
        matches = self.places.resolve(query, limit=limit)
        return ToolResult(
            data={
                "query": query,
                "matches": [
                    {"name": p.name, "label": p.label, "lat": p.lat, "lon": p.lon, "kind": p.kind, "district": p.district}
                    for p in matches
                ],
            },
            provenance=make_provenance("gazetteer", url="local:data/reference/places.csv"),
            note=None if matches else "Eşleşme yok.",
        )

    # -- 2. parking ---------------------------------------------------------------
    async def ispark_find_parking(
        self,
        place: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_km: float | None = None,
        min_free: int = 1,
        open_now: bool = True,
        with_tariff: bool = True,
    ) -> ToolResult:
        """Car parks near a place, with live free-space counts."""
        if lat is None or lon is None:
            if not place:
                raise ValueError("place ya da lat/lon vermelisiniz.")
            resolved = self._resolve_place(place)
            lat, lon, label = resolved.lat, resolved.lon, resolved.label
        else:
            label = f"{lat:.4f}, {lon:.4f}"

        source = self._source("ispark")
        radius = radius_km or self.settings.default_radius_km
        lots, prov = await source.find_near(lat, lon, radius_km=radius, min_free=min_free, open_now=open_now)

        notes: list[str] = []
        if with_tariff and lots:
            enriched = await source.enrich(lots)
            # The per-lot detail endpoint is fresher than the bulk list, so a lot that had
            # space a moment ago can come back full. Re-applying the filter here keeps the
            # promise the caller made ("at least min_free spaces") instead of quietly
            # returning a full car park with a tariff attached.
            if min_free > 0:
                kept = [lot for lot in enriched if lot.empty is None or lot.empty >= min_free]
                filled = [lot for lot in enriched if lot not in kept]
                if filled:
                    notes.append(
                        f"{len(filled)} otopark ({', '.join(lot.name for lot in filled[:3])}) "
                        "güncel detay verisinde dolu göründüğü için listeden çıkarıldı; "
                        "detay ölçümü toplu listeden daha tazedir."
                    )
                lots = kept
            else:
                lots = enriched

        if not lots:
            notes.append(f"{label} çevresinde {radius:.1f} km içinde boş yeri olan açık otopark bulunamadı.")
        elif any(lot.distance_km is not None and lot.distance_km > radius for lot in lots):
            notes.append(f"En yakın uygun otopark istenen {radius:.1f} km yarıçapın dışında kaldı.")

        return ToolResult(
            data={"near": label, "lat": lat, "lon": lon, "radius_km": radius, "count": len(lots), "parks": _dump(lots)},
            provenance=prov,
            note=" ".join(notes) or None,
        )

    async def ispark_typical_occupancy(self, park_id: int, weekday: int | None = None, hour: int | None = None) -> ToolResult:
        """Historical occupancy for a car park at a given weekday and hour.

        The profile is built from snapshots this project collects itself, because İBB
        publishes only the current occupancy and keeps no history. A cell with too few
        observations, or whose observations all fall inside one short window, reports
        ``available: false`` with the reason rather than presenting one afternoon as a
        pattern.

        The provenance is the profile's, not the request's: ``reported_at`` is the newest
        snapshot the profile was built from, so the age an agent quotes is the age of the
        history, not "0 seconds ago" for a table that may be a week old.
        """
        from ibb_mcp.occupancy import load_profile, lookup, lookup_weekday, profile_path

        _check_weekday_hour(weekday, hour)
        now = utcnow().astimezone(ISTANBUL_TZ)

        def answer() -> tuple[dict[str, Any], Any]:
            # One thread hop for the load and the lookup: ``lookup`` falls back to reading
            # the file itself when handed ``profile=None``, which would be a second, blocking
            # read on the event loop whenever the profile has not been built.
            profile = load_profile(self.settings)
            if weekday is None and hour is None:
                return lookup(park_id, now, settings=self.settings, profile=profile), profile
            slot = (now.weekday() if weekday is None else weekday, now.hour if hour is None else hour)
            return lookup_weekday(park_id, *slot, settings=self.settings, profile=profile), profile

        result, profile = await asyncio.to_thread(answer)
        return ToolResult(
            data=result,
            provenance=Provenance(
                source="nabiz_history",
                source_url=_local_url(profile_path(self.settings)),
                observed_at=(profile.built_at_utc if profile and profile.built_at_utc else utcnow()),
                reported_at=profile.last_sample_utc if profile else None,
            ),
            note=result.get("note"),
        )

    # -- 2b. travel-mode comparison -----------------------------------------------
    async def plan_journey(
        self,
        origin: str | None = None,
        destination: str | None = None,
        origin_lat: float | None = None,
        origin_lon: float | None = None,
        destination_lat: float | None = None,
        destination_lon: float | None = None,
        slow_walk: bool = False,
    ) -> ToolResult:
        """Compare driving, metro, a single bus line and walking between two places.

        A comparison, never turn-by-turn navigation: the result carries every assumption
        it used (the speed implied by the current traffic index, the parking search
        penalty, metro speed, walk speed) so the agent can state them instead of
        presenting an estimate as a routing engine's answer.

        A missing GTFS export costs the bus option only. The other three modes read live
        İBB sources through the shared cache, so a checkout without ``data/reference/gtfs``
        still answers, and the withdrawn bus option says why. The traffic baseline is
        optional in the same way: without it the ``traffic_typical`` reading is simply absent.
        """
        from ibb_mcp.routing import DEFAULT_PARAMS, compare_options, slow_walk_params

        start = self._endpoint(origin, origin_lat, origin_lon, role="origin")
        end = self._endpoint(destination, destination_lat, destination_lon, role="destination")

        index = sequences = line_index = None
        try:
            index = await self.gtfs()
            sequences = await self.stop_sequences()
            line_index = await self.stop_routes() if sequences else None
        except Exception as exc:  # noqa: BLE001 - the bus option is withdrawn, the rest stands
            log.info("GTFS unavailable for journey comparison: %r", exc)

        baseline, baseline_prov = await self.traffic_baseline_with_provenance()
        advice = await compare_options(
            start,
            end,
            self.ctx,
            index=index,
            sequences=sequences,
            line_index=line_index,
            traffic_baseline=baseline,
            traffic_baseline_provenance=baseline_prov,
            params=slow_walk_params() if slow_walk else DEFAULT_PARAMS,
        )
        payload = advice.to_dict()

        # An option the router could not cost is not an option. Leaving it in ``options``
        # with a null duration invites the agent to offer "walk" when the router meant
        # "too far to walk", so it moves to its own list — with its reason, because
        # "Boğaz'ın iki yakası arasında yürünemez" is itself an answer worth relaying.
        costed = [option for option in payload["options"] if option.get("available") and option.get("total_minutes") is not None]
        withdrawn = [
            {"mode": option["mode"], "label": option["label"], "reason": option.get("reason")}
            for option in payload["options"]
            if option not in costed
        ]
        payload["options"] = costed
        payload["unavailable_options"] = withdrawn
        note = (
            "Hesaplanamayan seçenekler: " + " ".join(f"{item['label']}: {item['reason']}" for item in withdrawn)
            if withdrawn
            else None
        )
        # The baseline is cited in data.provenance but does not age the envelope: it never
        # moves the minutes, and a 28-day history reused for hours would make every fresh
        # comparison sound hours old.
        live_inputs = [p for p in advice.provenance if p is not baseline_prov]
        return ToolResult(data=payload, provenance=self._routing_provenance(live_inputs), note=note)

    @staticmethod
    def _routing_provenance(inputs: list[Provenance]) -> Provenance:
        """One envelope stamp for a comparison built from several live readings.

        The age a user hears should be that of the *oldest* reading the answer leans on, so
        ``observed_at`` is the earliest fetch among the inputs and ``cached`` is set if any
        of them came from a stale cache. İBB's own ``reported_at`` is deliberately not
        folded in: a Metro notice can be weeks old by design, which says nothing about how
        fresh the traffic index behind the drive estimate is. Each input keeps its own full
        stamp in ``data.provenance``.
        """
        observed = min((p.observed_at for p in inputs if p.observed_at), default=None) or utcnow()
        return Provenance(
            source="nabiz_routing",
            source_url="local:src/ibb_mcp/routing.py",
            observed_at=observed,
            cached=any(p.cached for p in inputs),
        )

    # -- 2c. line reliability -----------------------------------------------------
    async def line_reliability(self, line_code: str, hour: int | None = None) -> ToolResult:
        """How regular a bus line actually is, measured from our own vehicle snapshots.

        İBB publishes no headway or bunching figure anywhere, so this exists only because
        the collector has been watching vehicles arrive. A line-hour with too few
        observations refuses rather than reporting a headway from two sightings — and that
        refusal is ``available: false``, which is why the flag comes from the cell itself
        and not from whether a cell was found: the table stores its refusals too.
        """
        from ibb_mcp.reliability import describe_cell, load_table, table_path

        line = (line_code or "").strip().upper()
        if not line:
            raise ValueError("Bir hat kodu vermelisiniz (örnek: 500T).")
        _check_weekday_hour(None, hour)
        at_hour = utcnow().astimezone(ISTANBUL_TZ).hour if hour is None else hour

        path = table_path()
        table = await asyncio.to_thread(load_table, path)
        payload = describe_cell(table, line, at_hour)
        note = payload.pop("note", None)
        payload["available"] = bool(payload.get("available"))
        if table is not None:
            payload["observed_lines"] = table.lines()
        payload["kind"] = "measured_history"
        return ToolResult(
            data=payload,
            provenance=Provenance(
                source="nabiz_reliability",
                source_url=_local_url(path),
                observed_at=table.generated_at if table is not None else utcnow(),
                reported_at=table.observed_to if table is not None else None,
            ),
            note=note,
        )

    # -- 2d. alerts ---------------------------------------------------------------
    async def check_alerts(self, subscription: Mapping[str, Any] | Any) -> ToolResult:
        """Evaluate a client-held alert subscription against current conditions.

        Stateless by design and by law: the subscription (places with coordinates, rules,
        the keys the client is already sitting on) lives with the caller and arrives with
        the request. Nothing is stored, nothing is logged, and there is no user identifier
        — see ``docs/privacy.md``. The engine's :func:`~ibb_mcp.alerts.engine.check_alerts`
        is the single implementation the web route and this tool share, so the cooldown
        policy, privacy summary and disclaimer travel with every answer.
        """
        from ibb_mcp.alerts.engine import check_alerts as evaluate

        raw = subscription.model_dump(mode="json", exclude_none=True) if hasattr(subscription, "model_dump") else subscription
        payload = await evaluate(self.ctx, raw)
        payload["stateless"] = True

        notes: list[str] = []
        if not payload["alerts"]:
            notes.append("Şu an bildirilecek bir durum yok.")
        if payload["unavailable"]:
            # "Nothing to report" and "could not look" are different answers; a dead source
            # must not be relayed as all-clear.
            notes.append("Kontrol edilemeyenler: " + " ".join(payload["unavailable"].values()))
        if payload["skipped_rule_kinds"]:
            notes.append("Bu sunucunun tanımadığı kural türleri atlandı: " + ", ".join(payload["skipped_rule_kinds"]) + ".")
        return ToolResult(
            data=payload,
            provenance=make_provenance("nabiz_alerts", url="local:src/ibb_mcp/alerts"),
            note=" ".join(notes) or None,
        )

    # -- 3. buses -----------------------------------------------------------------
    async def iett_stops_search(self, query: str, limit: int = 8) -> ToolResult:
        """Find bus stops by name."""
        index = await self.gtfs()
        stops = index.search_stops(query, limit=limit)
        return ToolResult(
            data={"query": query, "count": len(stops), "stops": _dump(stops)},
            provenance=make_provenance("gtfs", url="https://data.ibb.gov.tr/dataset/iett-gtfs-verisi"),
            note=None if stops else f"'{query}' için durak bulunamadı.",
        )

    async def iett_line_buses(self, line_code: str, direction: str | None = None) -> ToolResult:
        """Where the buses on a line are right now."""
        from ibb_mcp.sources.iett import buses_towards

        await self._refuse_unknown_line(line_code)
        buses, prov = await self._source("iett").line_positions(line_code)
        if direction:
            buses = buses_towards(buses, direction)
        return ToolResult(
            data={
                "line_code": line_code.upper().strip(),
                "count": len(buses),
                "directions": sorted({b.direction for b in buses if b.direction}),
                "buses": _dump(buses),
            },
            provenance=prov,
            note=None if buses else f"{line_code} hattında şu anda konum bildiren araç yok.",
        )

    async def _refuse_unknown_line(self, line_code: str) -> None:
        """Refuse a line code İETT's own route list does not know, before it costs a request.

        Every line-position read spends one call from İETT's documented 100 an hour, which
        this server shares with the collector and with every other user of the gateway. A
        well-formed but invented code ("999X") would otherwise spend one to learn nothing.
        Without a GTFS export there is no list to check against, so the call goes ahead as
        before rather than refusing every line.
        """
        try:
            index = await self.gtfs()
        except Exception as exc:  # noqa: BLE001 - no route list means no check, not no answer
            log.info("GTFS unavailable, line code %r not checked: %r", line_code, exc)
            return
        if index.is_loaded and not index.routes_for_short_name(line_code):
            raise ValueError(
                f"'{line_code.strip()}' İETT'nin GTFS hat listesinde yok; hat kodunu kontrol edin (örn. '500T'). "
                "Liste, yeni açılmış bir hattı henüz içermiyor olabilir."
            )

    async def iett_next_arrivals(
        self, line_code: str, stop: str, limit: int = 3, planned: bool = False, stale_after_s: float | None = None
    ) -> ToolResult:
        """Estimated arrivals of a line at a stop.

        These are estimates, not a published timetable guarantee; the method used for each
        estimate is returned so the agent can say how it was derived.

        A stop *name* is resolved with the line in mind: of the stops that match the name,
        the first one the line actually calls at wins, and the best name match is used only
        when none does. Taking the best name match alone sent "500T to Şifa" to a Şifa stop
        in Sarıyer and refused it, although the 500T's own terminus is ŞİFA SONDURAK.

        ``stale_after_s`` is the caller's limit on a live position's age (the arrival card's
        ``NABIZ_ARRIVAL_STALE_S``); past it the estimate falls back to the GTFS timetable, then
        to İETT's planned departures, and ``diagnostics["mode"]`` says which one answered.
        """
        from ibb_mcp.eta import EtaParams, estimate_arrivals, planned_summary, speed_profile_from_fleet
        from ibb_mcp.eta_profile import served_rate

        index = await self.gtfs()
        candidates: list[Any] = []
        target = index.lookup_stop(stop) if stop.isdigit() else None
        resolution = "stop_code" if target is not None else "best_name_match"
        if target is None:
            candidates = index.search_stops(stop, limit=STOP_CANDIDATES)
            if not candidates:
                raise ValueError(f"'{stop}' için durak bulunamadı. Durak adını veya durak kodunu deneyin.")
            target = candidates[0]

        # Before any İETT read: an invented code would otherwise spend three of them (positions,
        # then the schedule because no bus came back, then the fleet) and answer "no bus
        # approaching" for a line that does not exist.
        await self._refuse_unknown_line(line_code)
        source = self._source("iett")
        buses, prov = await source.line_positions(line_code)
        planned_day_type = day_type_for() if planned else None
        if not buses or planned:
            planned_departures, _ = await source.schedule(line_code, day_type=planned_day_type or day_type_for())
        else:
            planned_departures = []
        scheduled = planned_departures if not buses else None

        params = EtaParams(max_results=limit, **({} if stale_after_s is None else {"stale_after_s": float(stale_after_s)}))
        try:
            fleet, _ = await source.fleet_positions()
            params = dataclasses.replace(params, speed_kmh=speed_profile_from_fleet(fleet))
        except Exception as exc:  # noqa: BLE001 - the fleet call is optional
            log.info("fleet speed profile unavailable, using default: %r", exc)

        # The per-stop rate: the untuned 120 s/stop unless NABIZ_ETA_PROFILE_MODE=calibrated.
        # The profile fitted by scripts/calibrate_eta.py (data/reference/eta_profile.json)
        # scored 35.82 min MAE against 10.18 for 120 s/stop on 523 held-out predictions at
        # stops it never saw (eval/results/eta.md), so the estimator with the better
        # held-out score is the one served (DECISIONS #18). served_rate reads no file then, and
        # off the event loop because the calibrated mode does.
        rate = await asyncio.to_thread(served_rate, line_code, utcnow(), self.settings)

        sequences = await self.stop_sequences()
        timetable, service_days = await self._schedule_tables.get(self.settings)

        # Refuse to estimate for a stop the line does not serve. Without this guard the
        # distance method happily returns a three-hour "arrival" for a bus that will never
        # come, because straight-line distance knows nothing about routes.
        served_by = self._route_codes_for(line_code, buses, index)
        if sequences and served_by:
            known = [sequences[code] for code in served_by if code in sequences]
            if known and len(candidates) > 1:
                on_line = next(
                    (
                        stop_row
                        for stop_row in candidates
                        if stop_row.stop_code and any(seq.position_of(stop_row.stop_code) is not None for seq in known)
                    ),
                    None,
                )
                if on_line is not None:
                    resolution, target = "name_match_on_line", on_line
            if known and not any(seq.position_of(target.stop_code) is not None for seq in known):
                serving = await self._lines_serving(target.stop_code)
                hint = f" Bu durağa uğrayan hatlar: {', '.join(serving[:6])}." if serving else ""
                raise ValueError(
                    f"{line_code.upper().strip()} hattı '{target.name or target.stop_code}' durağına uğramıyor.{hint}"
                )

        arrivals, diagnostics = estimate_arrivals(
            buses=buses, target=target, index=index, sequences=sequences, scheduled=scheduled,
            speed_profile=rate.as_speed_profile(), line_code=line_code.upper().strip(),
            timetable=timetable, service_days=service_days, params=params,
        )
        # Which rate, from where, and why: "120 s/stop because nothing was measured" and
        # "120 s/stop because the measurement did not transfer" are different answers.
        diagnostics["rate_source"] = rate.source
        diagnostics["rate_mode"] = rate.mode
        diagnostics["rate_reason"] = rate.reason
        diagnostics["seconds_per_stop"] = rate.seconds_per_stop
        # How the target stop was chosen, so an answer about "Şifa" can say which Şifa.
        diagnostics["stop_resolution"] = resolution
        data = {
            "line_code": line_code.upper().strip(),
            "stop": _dump(target),
            "arrivals": _dump(arrivals),
            "diagnostics": diagnostics,
            "disclaimer": "Varış saatleri tahminidir; resmi İETT bilgisi değildir. " + rate.sentence_tr(),
        }
        if planned:
            data["planned"] = planned_summary(planned_departures or [], planned_day_type or day_type_for())
        return ToolResult(
            data=data,
            provenance=prov,
            note=None if arrivals else "Yaklaşan araç bulunamadı.",
        )

    # -- 4. metro -----------------------------------------------------------------
    async def metro_status(self, line: str | None = None) -> ToolResult:
        """Live disruption notices. An absent line means no reported disruption."""
        statuses, prov = await self._source("metro").service_status()
        if line:
            wanted = line.strip().casefold()
            statuses = [s for s in statuses if (s.line_name or "").casefold() == wanted]
            note = f"{line.upper()} için bildirilmiş bir arıza/çalışma duyurusu yok." if not statuses else None
        else:
            note = "Bildirilmiş arıza/çalışma duyurusu yok." if not statuses else None
        return ToolResult(
            data={"count": len(statuses), "lines": _dump(statuses)},
            provenance=prov,
            note=note,
        )

    async def metro_station_info(self, name: str) -> ToolResult:
        """Station details including step-free access."""
        source = self._source("metro")
        matches = await source.find_station(name)
        if not matches:
            raise ValueError(f"'{name}' adlı bir metro istasyonu bulamadım.")
        _, prov = await source.stations()
        return ToolResult(data={"query": name, "count": len(matches), "stations": _dump(matches)}, provenance=prov)

    async def metro_equipment_status(
        self, station: str | None = None, line: str | None = None, group: str | None = None
    ) -> ToolResult:
        """Lifts, escalators and moving walkways İBB lists as unusable (``ibb_mcp.accessibility``)."""
        from ibb_mcp.accessibility import equipment_status

        sources = self._source("metro_equipment"), self._source("metro")
        return await equipment_status(*sources, station=station, line=line, group=group)

    async def accessible_alternative(self, station: str, needs: list[str] | None = None) -> ToolResult:
        """A station's lifts and, if one is listed unusable, the nearest step-free station (not an MCP tool)."""
        from ibb_mcp.accessibility import alternative_answer

        sources = self._source("metro_equipment"), self._source("metro")
        return await alternative_answer(*sources, station=station, needs=needs)

    async def accessible_journey(
        self, origin: str | tuple[float, float], destination: str | tuple[float, float], needs: list[str] | None = None
    ) -> Any:
        """A step-free rail journey with per-station lifts (``ibb_mcp.journey_accessible``; not an MCP tool)."""
        from ibb_mcp.journey_accessible import plan_accessible_journey

        return await plan_accessible_journey(self, origin, destination, needs)

    async def ibb_services_search(self, query: str, limit: int = 5) -> ToolResult:
        """Reviewed İBB service pages from the local knowledge index (``ibb_mcp.knowledge``)."""
        from ibb_mcp.knowledge.tool import search_local_index

        return await search_local_index(query, limit, offline=self.settings.offline)

    async def ibb_datasets_search(self, query: str, category: str | None = None, limit: int = 5) -> ToolResult:
        """Datasets on the İBB Open Data portal, from the local catalogue file (``ibb_mcp.catalog``; no İBB call)."""
        from ibb_mcp.catalog import search_catalog

        return await asyncio.to_thread(search_catalog, query, category, limit)

    async def metro_equipment_signals(self) -> ToolResult:
        """The equipment snapshot as NEXUS signal candidates, for the console (not an MCP tool)."""
        from ibb_mcp.equipment_signals import equipment_signals

        return await equipment_signals(self._source("metro_equipment"), self._source("metro"))

    # -- 5. traffic ---------------------------------------------------------------
    async def traffic_index(self, window: str = "now") -> ToolResult:
        """City-wide traffic index, 1 (free flowing) to 99 (gridlocked)."""
        source = self._source("traffic")
        note = None
        if window == "now":
            point, prov = await source.current()
            # A null index arrives as None (models.TrafficIndexPoint); it used to arrive as 0,
            # and describe_traffic(0) is "akıcı": missing data read out as free-flowing
            # traffic. İBB's scale is 1–99, so a 0 or anything else off it is no reading either.
            valid = point is not None and isinstance(point.index, int) and 1 <= point.index <= 99
            data: dict[str, Any] = {
                "index": point.index if valid else None,
                "at": _dump(point.at) if point else None,
                "description": describe_traffic(point.index) if valid else None,
            }
            if point is not None and not valid:
                note = "İBB bu ölçümde geçerli bir trafik indeksi döndürmedi; değer bilinmiyor."
            if valid:
                data["typical"] = await self._typical_traffic(point)
        else:
            points, prov = await source.index_history(days=1, period="H")
            comparison = source.compare_with_yesterday(points)
            data = {"history": _dump(points[:24]), **comparison}
        return ToolResult(data=data, provenance=prov, note=note)

    async def _typical_traffic(self, point: Any) -> dict[str, Any]:
        """The live index held against this weekday and hour's measured median.

        Always a dict with ``available``: "no baseline yet" (too few weeks behind the cell)
        and "history unreadable" are both answers the agent should relay, and neither may be
        read as "about as usual".
        """
        from ibb_mcp.traffic_profile import compare_to_typical

        baseline, history_prov = await self.traffic_baseline_with_provenance()
        if baseline is None:
            return {
                "available": False,
                "description": "İBB trafik geçmişi okunamadı; bu saatin olağan seviyesiyle karşılaştırma yapılamadı.",
            }
        comparison = compare_to_typical(point.index, point.at or utcnow(), baseline)
        typical: dict[str, Any] = {
            "available": comparison.available,
            "typical_index": comparison.typical,
            "delta": comparison.delta,
            "band": comparison.band,
            "samples": comparison.samples,
            "history_days": TRAFFIC_BASELINE_DAYS,
            "description": comparison.description_tr,
        }
        if history_prov is not None:
            # typical_index and delta come from a separate TrafficIndexHistory read, not from
            # the live 1/H read the envelope cites, so they carry that read's own stamp.
            typical["provenance"] = {**_dump(history_prov), "age_seconds": round(history_prov.age_seconds, 1)}
        return typical

    # -- 6. air quality -----------------------------------------------------------
    async def air_quality_now(self, place: str) -> ToolResult:
        """Latest air-quality reading at the station nearest a place."""
        source = self._source("aq")
        resolved = self._resolve_place(place)
        station = await source.nearest_station(resolved.lat, resolved.lon)
        if station is None:
            raise ValueError(f"{resolved.label} yakınında hava kalitesi istasyonu bulunamadı.")
        reading, prov = await source.latest(station.station_id)
        band = aqi_band(reading.aqi_index) if reading else None
        return ToolResult(
            data={
                "place": resolved.label,
                "station": _dump(station),
                "reading": _dump(reading),
                "band": {"label": band[0], "key": band[1]} if band else None,
                "disclaimer": "Sağlık tavsiyesi değildir.",
            },
            provenance=prov,
            note=None if reading else "İstasyondan güncel ölçüm gelmiyor.",
        )

    async def air_quality_forecast(self, place: str, horizon_hours: int = 6) -> ToolResult:
        """Short-horizon forecast and the cleanest upcoming window."""
        from ibb_mcp.analytics import air_quality_forecast as forecast_impl

        resolved = self._resolve_place(place)
        source = self._source("aq")
        station = await source.nearest_station(resolved.lat, resolved.lon)
        if station is None:
            raise ValueError(f"{resolved.label} yakınında hava kalitesi istasyonu bulunamadı.")
        result = await forecast_impl(self.ctx, station=station, horizon_hours=horizon_hours)
        return ToolResult(
            data={"place": resolved.label, "station": _dump(station), **result},
            provenance=make_provenance("nabiz_forecast", url="local:gold/aq_forecast"),
            note=result.get("note"),
        )

    # -- 7. freshness -------------------------------------------------------------
    async def city_freshness(self) -> ToolResult:
        """How old the data behind each source is. The agent quotes this when hedging."""
        freshness = self.ctx.cache.freshness()
        budgets = {name: budget.remaining for name, budget in self.ctx.client.budgets.items()}
        return ToolResult(
            data={
                "sources": freshness,
                "request_budget_remaining": budgets,
                "attribution": self._attribution(),
                "checked_at": _dump(utcnow()),
            },
            provenance=make_provenance("nabiz_runtime", url="local:cache"),
            note=None if freshness else "Henüz hiçbir kaynak sorgulanmadı.",
        )
