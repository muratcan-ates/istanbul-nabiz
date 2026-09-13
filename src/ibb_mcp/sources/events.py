"""İBB events — **no usable feed exists; this source refuses instead of guessing.**

Epic E3 asked whether Nabız can recommend İBB events. It was researched on 2026-09-13
(evidence and method in ``docs/events_research.md``) and the answer is **no**: İBB
publishes no machine-readable, forward-looking events calendar under the Açık Veri
Lisansı. Everything the portal returns for *etkinlik* is either a spreadsheet of past
counts or — in the single API case — a press-release archive.

Why this module exists at all, given the answer is no:

* **A refusal has to be reachable.** A user who asks "bu akşam ne var?" deserves a
  sourced "bunu yayınlamıyorlar, şuraya bak" rather than an LLM improvising a concert
  that does not exist. The tool layer can only say that if something returns it.
* **The evidence has to live next to the code**, so that the next person to ask does not
  repeat the research, and so the answer carries its own citations
  (:data:`EVIDENCE`).
* **The day a feed appears, this should be a small change, not a new epic.** The search,
  district/category filtering and nearest-to-a-place ranking are written here against
  :class:`EventsFeedAdapter`; plugging in a real feed means writing one adapter class and
  passing it to :class:`EventsSource`. Nothing else moves.

**This module contains no event records and must never contain any.** The only honest
sources of event data are a feed we do not have; every field below is a *shape*, not a
value. A future adapter is the one place data may enter.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from ibb_mcp.cache import CacheEntry
from ibb_mcp.models import ISTANBUL_TZ, Provenance, haversine_km
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.sources.places import normalize_tr

log = logging.getLogger("ibb_mcp.sources.events")

#: Short source key used in provenance and cache keys.
SOURCE = "events"

#: What a *hypothetical* feed would be cached for. Event listings change on the scale of
#: a publishing day, not a minute, and a stale event is far less harmful than a stale bus
#: position — but a day is too long to notice a cancellation, so: one hour.
EVENTS_TTL_S = 3600.0

#: Where the refusal points the reader. Not an İBB data endpoint — it is the portal search
#: that produced the negative result, which is the only citable thing we actually have.
EVIDENCE_URL = "https://data.ibb.gov.tr/api/3/action/package_search?q=etkinlik"

#: Date the research below was carried out. Printed in the refusal so a reader can tell
#: how old the "no" is and decide whether to re-check.
VERIFIED_ON = dt.date(2026, 9, 13)


class CandidateEvidence(BaseModel):
    """One source we checked and why it does not qualify.

    Returned verbatim inside the refusal payload: an unsupported "hayır" is an opinion,
    a "hayır" carrying the URLs that were checked is a finding someone can overturn.
    """

    name: str
    url: str
    checked_on: dt.date
    verdict: str
    detail: str


#: The full negative result. Keep this in step with ``docs/events_research.md``; the doc
#: carries the method and the confidence levels, this carries what the agent can say out
#: loud. Ordered most-promising-first, which is also the order they were ruled out.
EVIDENCE: tuple[CandidateEvidence, ...] = (
    CandidateEvidence(
        name="Metro İstanbul Event List (GetActivities)",
        url="https://api.ibb.gov.tr/MetroIstanbul/api/MetroMobile/V2/GetActivities",
        checked_on=VERIFIED_ON,
        verdict="not an events calendar",
        detail=(
            "Portaldaki tek 'etkinlik' API'si. Canlı çağrıldı: 168 kayıt, alanlar "
            "Id/Title/Content/Photo/StartDate/Language/Media — mekân, ilçe, koordinat, "
            "bitiş saati ve kategori yok. Kayıtların tamamı geçmiş tarihli (en yenisi "
            "2026-02-05) ve StartDate yayın tarihi, etkinlik tarihi değil: 2025-11-20 "
            "damgalı bir kayıt '29 Mayıs'ta ... yürüyoruz' diyor. Bu bir basın bülteni "
            "arşivi."
        ),
    ),
    CandidateEvidence(
        name="İBB Açık Veri Portalı — 'etkinlik' araması",
        url=EVIDENCE_URL,
        checked_on=VERIFIED_ON,
        verdict="statistics only",
        detail=(
            "9 veri seti. Sekizi XLSX ve geçmiş sayımlar (kütüphane etkinlik sayısı, "
            "Bulgur Palas katılımcı sayısı, spor organizasyonları). İleriye dönük tek bir "
            "etkinlik kaydı yok."
        ),
    ),
    CandidateEvidence(
        name="İBB Açık Veri Portalı — API formatındaki tüm veri setleri",
        url="https://data.ibb.gov.tr/api/3/action/package_search?fq=res_format:API",
        checked_on=VERIFIED_ON,
        verdict="no events API",
        detail=(
            "41 veri seti; hepsi ulaşım (İSPARK, İETT, Metro, İSBİKE), trafik veya hava "
            "kalitesi. Kültür-sanat takvimi yok."
        ),
    ),
    CandidateEvidence(
        name="kultur.istanbul",
        url="https://kultur.istanbul/etkinlikler/",
        checked_on=VERIFIED_ON,
        verdict="html only, all rights reserved",
        detail=(
            "Gerçek bir etkinlik takvimi, ama yalnızca HTML: RSS, iCal, JSON ya da "
            "geliştirici dokümanı yok. İşleten İstanbul Kültür ve Sanat Ürünleri Tic. "
            "A.Ş.; sayfa altı '© 2026 ... All rights reserved' diyor — açık veri lisansı "
            "kapsamında değil."
        ),
    ),
    CandidateEvidence(
        name="kultursanat.istanbul (İBB Kültür Sanat)",
        url="https://kultursanat.istanbul/etkinliklerimiz",
        checked_on=VERIFIED_ON,
        verdict="html only, all rights reserved",
        detail=(
            "Makine okunur çıktı yok; kontrol anında liste boştu ('Toplam 0 etkinlik'). "
            "'Tüm hakları İstanbul Büyükşehir Belediyesi'nde saklıdır' + üyelik sözleşmesi "
            "ve KVKK aydınlatma metni."
        ),
    ),
    CandidateEvidence(
        name="İstanbul Senin süper uygulaması (İBB Etkinlik mini-uygulaması)",
        url="https://istanbulsenin.istanbul/",
        checked_on=VERIFIED_ON,
        verdict="no public API",
        detail=(
            "Etkinlik kaydı ve ücretsiz bilet burada yaşıyor, ama yayımlanmış bir "
            "geliştirici API'si ya da dokümanı bulunamadı. Uygulama içi trafiği "
            "tersine çevirmek kullanım koşullarına aykırı; denenmedi."
        ),
    ),
)

#: The single Turkish sentence the agent should say. Kept as one string so the refusal is
#: worded identically everywhere and can be reviewed in one place.
REFUSAL_TR = (
    "İBB, etkinliklerini makine okunur ve ileriye dönük bir açık veri akışı olarak "
    "yayınlamıyor; bu yüzden etkinlik önerisi üretmiyoruz. Uydurmamak için boş dönüyoruz. "
    "Güncel program için kultur.istanbul, kultursanat.istanbul veya İstanbul Senin "
    "uygulamasına bakabilirsiniz."
)


# --------------------------------------------------------------------------------------
# The shape a future feed must fill
# --------------------------------------------------------------------------------------
class Event(BaseModel):
    """One event, as Nabız would need it.

    Deliberately stricter than any HTML listing: ``start`` is timezone-aware UTC and
    ``venue``/``lat``/``lon`` are what make "yakınımda ne var" answerable at all. A feed
    that cannot fill ``start`` and at least one of ``district`` / ``lat``+``lon`` is not
    good enough to recommend from, and its adapter should say so rather than pad the gaps.

    Lives here rather than in ``models.py`` because nothing produces one yet; it moves
    into the shared models module on the day a real adapter ships.
    """

    event_id: str
    title: str
    start: dt.datetime
    end: dt.datetime | None = None
    venue: str | None = None
    district: str | None = None
    lat: float | None = None
    lon: float | None = None
    category: str | None = None
    url: str | None = None
    is_free: bool | None = None
    description: str | None = None
    #: Filled by :meth:`EventsSource.near`, never by a feed.
    distance_km: float | None = None

    def starts_on(self) -> dt.date:
        """Local (İstanbul) calendar day. Users filter by the day they live in, not UTC."""
        return self.start.astimezone(ISTANBUL_TZ).date()


@runtime_checkable
class EventsFeedAdapter(Protocol):
    """The one plug point. Implement this when a real feed becomes available.

    Contract:

    * ``fetch()`` returns events **already parsed and normalised** — UTC-aware ``start``,
      coordinates repaired, mojibake fixed. Filtering, ranking and distance are
      :class:`EventsSource`'s job, not the adapter's.
    * It must go through ``ctx.client`` (:class:`~ibb_mcp.http.PoliteClient`) for any
      network access. No adapter may open its own HTTP client: the 6 s/host spacing that
      keeps the İBB gateway alive is global or it is nothing.
    * ``license`` is the *exact* licence string of that feed. It is stamped onto every
      result, so an adapter over a scraped "all rights reserved" page must say exactly
      that — which is the point at which someone should notice we are not allowed to
      ship it.
    * Raise :class:`~ibb_mcp.http.UpstreamUnavailable` on failure. Returning an empty list
      to mean "broken" would read as "bugün etkinlik yok", which is a lie.
    """

    #: Short source key, e.g. ``"kultur_istanbul"``.
    name: str
    #: Citable URL for provenance.
    source_url: str
    #: Exact licence string for the feed.
    license: str

    async def fetch(self) -> Sequence[Event]:
        """All currently-published events. Called at most once per :data:`EVENTS_TTL_S`."""
        ...


# --------------------------------------------------------------------------------------
# The source
# --------------------------------------------------------------------------------------
class EventsSource:
    """Events for İstanbul — unavailable by default, functional with an adapter.

    Constructed exactly like every other source so the tool layer needs no special case::

        source = EventsSource(ctx)                    # today: refuses, with evidence
        source = EventsSource(ctx, adapter=MyFeed())  # the day a feed exists

    Every method returns ``(payload, provenance)`` where ``payload["available"]`` is the
    first thing a caller must read, mirroring :mod:`ibb_mcp.analytics`.
    """

    def __init__(self, ctx: SourceContext, adapter: EventsFeedAdapter | None = None) -> None:
        self.ctx = ctx
        self.adapter = adapter
        if adapter is None:
            log.info("events source constructed without an adapter: every query will refuse (E3, %s)", VERIFIED_ON)

    @property
    def available(self) -> bool:
        return self.adapter is not None

    # -- refusal -----------------------------------------------------------------
    def _unavailable(self) -> tuple[dict[str, Any], Provenance]:
        """The honest empty answer, with its receipts attached."""
        payload: dict[str, Any] = {
            "available": False,
            "reason": REFUSAL_TR,
            "reason_en": (
                "İBB publishes no machine-readable, forward-looking events feed under an open "
                "licence; no event recommendation is produced."
            ),
            "events": [],
            "checked_on": VERIFIED_ON.isoformat(),
            "evidence": [c.model_dump(mode="json") for c in EVIDENCE],
            "what_would_unblock_it": (
                "İBB Kültür A.Ş. ile bir veri paylaşımı ya da kultur.istanbul üzerinde "
                "yayımlanmış bir JSON/iCal akışı. Ayrıntı: docs/events_research.md"
            ),
        }
        # No İBB payload is returned here, so claiming the İBB Açık Veri Lisansı over it
        # would be a false citation — the one thing this module exists to avoid.
        provenance = Provenance(
            source=SOURCE,
            source_url=EVIDENCE_URL,
            license="n/a — veri döndürülmedi",
        )
        return payload, provenance

    # -- adapter path ------------------------------------------------------------
    async def _load(self) -> tuple[list[Event], CacheEntry[Any]]:
        assert self.adapter is not None  # guarded by every caller
        adapter = self.adapter

        async def loader() -> list[Event]:
            return list(await adapter.fetch())

        events, entry = await self.ctx.cached(
            f"{SOURCE}:{adapter.name}:all", loader, source=SOURCE, ttl=EVENTS_TTL_S
        )
        return list(events), entry

    def _provenance(self, entry: CacheEntry[Any]) -> Provenance:
        assert self.adapter is not None
        return Provenance(
            source=f"{SOURCE}:{self.adapter.name}",
            source_url=self.adapter.source_url,
            observed_at=entry.stored_at_utc,
            cached=not entry.fresh,
            license=self.adapter.license,
        )

    # -- queries -----------------------------------------------------------------
    async def search(
        self,
        *,
        date_from: dt.date | None = None,
        date_to: dt.date | None = None,
        district: str | None = None,
        category: str | None = None,
        query: str | None = None,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], Provenance]:
        """Events matching a date range, district, category and/or free-text title.

        Dates are **İstanbul calendar days**, inclusive at both ends, because that is what
        a person means by "yarın". Text matching is Turkish-folded so "kadikoy" finds
        "Kadıköy".
        """
        if self.adapter is None:
            return self._unavailable()

        events, entry = await self._load()
        limit = limit or self.ctx.settings.max_results
        district_key, category_key, query_key = normalize_tr(district), normalize_tr(category), normalize_tr(query)

        matched = [
            event
            for event in events
            if (date_from is None or event.starts_on() >= date_from)
            and (date_to is None or event.starts_on() <= date_to)
            and (not district_key or district_key in normalize_tr(event.district))
            and (not category_key or category_key in normalize_tr(event.category))
            and (not query_key or query_key in normalize_tr(f"{event.title} {event.venue or ''}"))
        ]
        matched.sort(key=lambda event: event.start)
        return self._payload(matched, limit=limit, total=len(matched)), self._provenance(entry)

    async def near(
        self,
        lat: float,
        lon: float,
        *,
        radius_km: float | None = None,
        date_from: dt.date | None = None,
        date_to: dt.date | None = None,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], Provenance]:
        """Events within ``radius_km`` of a coordinate, nearest first.

        Events with no coordinate are dropped rather than assumed to be at the centre of
        their district: "500 m ötende" has to be true or not be said.
        """
        if self.adapter is None:
            return self._unavailable()

        events, entry = await self._load()
        radius = radius_km or self.ctx.settings.default_radius_km
        limit = limit or self.ctx.settings.max_results

        ranked: list[Event] = []
        for event in events:
            if event.lat is None or event.lon is None:
                continue
            if date_from is not None and event.starts_on() < date_from:
                continue
            if date_to is not None and event.starts_on() > date_to:
                continue
            distance = haversine_km(lat, lon, event.lat, event.lon)
            if distance <= radius:
                ranked.append(event.model_copy(update={"distance_km": round(distance, 3)}))
        ranked.sort(key=lambda event: (event.distance_km or 0.0, event.start))

        payload = self._payload(ranked, limit=limit, total=len(ranked))
        payload["radius_km"] = radius
        payload["without_coordinates"] = sum(1 for e in events if e.lat is None or e.lon is None)
        return payload, self._provenance(entry)

    def _payload(self, events: list[Event], *, limit: int, total: int) -> dict[str, Any]:
        return {
            "available": True,
            "events": [event.model_dump(mode="json", exclude_none=True) for event in events[:limit]],
            "returned": min(limit, total),
            "matched": total,
            "note": None if total else "Ölçütlere uyan etkinlik bulunamadı.",
        }

    def availability(self) -> dict[str, Any]:
        """Machine-readable status for ``city_freshness`` and the data-quality report."""
        if self.adapter is None:
            payload, _ = self._unavailable()
            return payload
        return {
            "available": True,
            "adapter": self.adapter.name,
            "source_url": self.adapter.source_url,
            "license": self.adapter.license,
        }
