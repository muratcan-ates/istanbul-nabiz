"""Metro İstanbul: live line notices and station facilities (journey J3).

Two endpoints with very different characters:

* ``GetServiceStatuses`` lists **only the lines that currently have a notice**. An empty
  ``Data`` array means "hiçbir hatta bildirim yok", not "veri gelmedi" — the distinction
  is the whole point of :meth:`MetroSource.line_status`, which returns ``None`` rather
  than inventing an "işliyor" record we did not actually receive.
* ``GetStations`` is effectively static (248 stations) and carries the accessibility
  detail J3 needs, so it is cached for a day and never counted against a live budget.

Both wrap their payload in ``{Success, Error, Data}``. ``Success: false`` is a genuine
upstream failure and must not be read as an empty result, hence :func:`_unwrap`.

Field quirks handled here and in :mod:`ibb_mcp.models`: the escalator count is spelled
``Escolator``; ``Name`` is shouted and de-diacriticised (``YENIKAPI``) while
``Description`` holds the human form (``Yenikapı``). Users type neither reliably, so all
lookups go through :func:`normalize_tr`.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from ibb_mcp.config import METRO_SERVICE_STATUS, METRO_STATIONS
from ibb_mcp.http import UpstreamUnavailable
from ibb_mcp.models import MetroLineStatus, MetroStation, Provenance
from ibb_mcp.sources.base import SourceContext, make_provenance

#: One day. Station facilities change on the scale of construction projects, not minutes.
STATIONS_TTL = 86400.0

# --------------------------------------------------------------------------------------
# Turkish-insensitive matching
# --------------------------------------------------------------------------------------
#: Mapped *before* casefolding, because ``"İ".casefold()`` yields ``i`` plus a combining
#: dot (U+0307) and ``"I".casefold()`` yields ``i`` — so a naive fold makes "ısparta" and
#: "isparta" collide inconsistently across sources. Folding every Turkish letter onto its
#: ASCII skeleton lets a user type "sisli" and hit "Şişli-Mecidiyeköy".
_TR_FOLD = str.maketrans(
    {
        "İ": "i", "I": "i", "ı": "i", "i": "i",
        "Ş": "s", "ş": "s",
        "Ğ": "g", "ğ": "g",
        "Ü": "u", "ü": "u",
        "Ö": "o", "ö": "o",
        "Ç": "c", "ç": "c",
        "Â": "a", "â": "a", "Î": "i", "î": "i", "Û": "u", "û": "u",
    }
)


def normalize_tr(text: str | None) -> str:
    """Fold Turkish text to a searchable ASCII skeleton.

    ``'Şişli-Mecidiyeköy'`` and ``'SISLI-MECIDIYEKOY'`` both become
    ``'sisli-mecidiyekoy'``, so a query typed on any keyboard matches either spelling.
    """
    if not text:
        return ""
    folded = text.translate(_TR_FOLD).casefold()
    # Anything that arrived pre-decomposed (I + U+0307) still carries combining marks.
    decomposed = unicodedata.normalize("NFKD", folded)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.split())


def rank_match(query: str, candidate: str) -> int | None:
    """Match quality: 0 exact, 1 prefix, 2 substring, ``None`` for no match."""
    if not candidate or not query:
        return None
    if candidate == query:
        return 0
    if candidate.startswith(query):
        return 1
    if query in candidate:
        return 2
    return None


def _unwrap(payload: Any, *, source: str) -> list[dict[str, Any]]:
    """Validate the ``{Success, Error, Data}`` envelope Metro İstanbul returns.

    A falsy ``Success`` is raised as an upstream failure so the cache can fall back to a
    previous snapshot and the agent can say how old it is, instead of reporting "no
    disruptions" when we simply failed to read the feed.
    """
    if not isinstance(payload, dict):
        raise UpstreamUnavailable(f"{source}: beklenmeyen yanıt tipi {type(payload).__name__}", source=source)
    if not payload.get("Success"):
        detail = payload.get("Error") or "Success=false"
        raise UpstreamUnavailable(f"{source}: servis hata bildirdi ({detail})", source=source)
    data = payload.get("Data")
    if data is None:
        return []
    if not isinstance(data, list):
        raise UpstreamUnavailable(f"{source}: Data listesi bekleniyordu", source=source)
    return data


class MetroSource:
    """Reads Metro İstanbul's public mobile API through the shared client and cache."""

    def __init__(self, ctx: SourceContext) -> None:
        self.ctx = ctx

    # -- live notices ------------------------------------------------------------------
    async def service_status(self) -> tuple[list[MetroLineStatus], Provenance]:
        """Current line notices. An empty list means no line has a reported problem."""

        async def load() -> list[dict[str, Any]]:
            if self.ctx.settings.offline:
                return _unwrap(self.ctx.load_fixture("metro_status"), source="metro_status")
            payload = await self.ctx.client.get_json(METRO_SERVICE_STATUS, source="metro_status")
            return _unwrap(payload, source="metro_status")

        raw, entry = await self.ctx.cached("metro:status", load, source="metro_status")
        statuses = [MetroLineStatus.from_raw(item) for item in raw]
        # İBB stamps each notice individually; the freshest one dates the whole answer.
        stamps = [s.updated_at for s in statuses if s.updated_at is not None]
        provenance = make_provenance(
            "metro_status",
            entry=entry,
            reported_at=max(stamps) if stamps else None,
            url=METRO_SERVICE_STATUS,
        )
        return statuses, provenance

    async def line_status(self, line_name: str) -> MetroLineStatus | None:
        """Notice for one line, e.g. ``"M4"``.

        ``None`` means **no reported disruption**, not "unknown": the endpoint only ever
        returns lines that currently carry a notice, so a line's absence is itself the
        answer. Callers should phrase that as "bildirilen arıza yok" and still quote the
        provenance age from :meth:`service_status`, because an old snapshot cannot prove
        the line is fine right now.
        """
        wanted = normalize_tr(line_name)
        if not wanted:
            return None
        statuses, _ = await self.service_status()
        for status in statuses:
            if normalize_tr(status.line_name) == wanted:
                return status
        return None

    # -- stations ----------------------------------------------------------------------
    async def stations(self) -> tuple[list[MetroStation], Provenance]:
        """All 248 stations with their accessibility detail. Cached for a day."""

        async def load() -> list[dict[str, Any]]:
            if self.ctx.settings.offline:
                return _unwrap(self.ctx.load_fixture("metro_stations"), source="metro_stations")
            payload = await self.ctx.client.get_json(METRO_STATIONS, source="metro_stations")
            return _unwrap(payload, source="metro_stations")

        raw, entry = await self.ctx.cached("metro:stations", load, source="metro_stations", ttl=STATIONS_TTL)
        stations = [MetroStation.from_raw(item) for item in raw]
        return stations, make_provenance("metro_stations", entry=entry, url=METRO_STATIONS)

    async def find_station(self, name: str) -> list[MetroStation]:
        """Turkish-insensitive station search, best matches first.

        Interchange names repeat across lines (``Yenikapı`` appears on M1A, M1B and M2),
        so every matching line is returned rather than an arbitrary winner; the caller
        decides whether to ask which line the user meant.
        """
        query = normalize_tr(name)
        if not query:
            return []
        stations, _ = await self.stations()
        scored: list[tuple[int, str, int, MetroStation]] = []
        for station in stations:
            rank = rank_match(query, normalize_tr(station.name))
            if rank is None:
                continue
            scored.append((rank, station.line_name or "", station.order or 0, station))
        scored.sort(key=lambda row: (row[0], row[1], row[2]))
        return [row[3] for row in scored]


def describe_accessibility(station: MetroStation) -> str:
    """One Turkish sentence about lifts, escalators, WC, baby room and prayer room.

    Unknown fields are omitted rather than rendered as zero: "asansör yok" and "asansör
    bilgisi paylaşılmamış" are very different answers for someone planning a step-free
    journey.
    """
    head = station.name or "İstasyon"
    if station.line_name:
        head = f"{head} ({station.line_name})"

    parts: list[str] = []
    if station.lifts is not None:
        parts.append(f"{station.lifts} asansör" if station.lifts else "asansör yok")
    if station.escalators is not None:
        parts.append(f"{station.escalators} yürüyen merdiven" if station.escalators else "yürüyen merdiven yok")
    for value, label in ((station.wc, "WC"), (station.baby_room, "bebek bakım odası"), (station.masjid, "mescit")):
        if value is None:
            continue
        parts.append(f"{label} var" if value else f"{label} yok")

    if not parts:
        return f"{head}: erişilebilirlik bilgisi İBB tarafından paylaşılmamış."

    sentence = f"{head}: " + ", ".join(parts) + "."
    if station.step_free is False:
        sentence += " Asansör bulunmadığı için tekerlekli sandalye erişimi kısıtlı olabilir."
    return sentence


def summarise_disruptions(statuses: list[MetroLineStatus]) -> str:
    """Short Turkish headline for the whole network, used when no line is named."""
    active = [s for s in statuses if s.is_active is not False]
    if not active:
        return "Metro hatlarında bildirilen bir arıza yok."
    names = ", ".join(sorted({s.line_name or "?" for s in active}))
    return f"{len(active)} hatta bildirim var: {names}."
