"""İSPARK — İstanbul's municipal car parks.

Two unauthenticated endpoints back every parking answer:

``GET /ispark/Park``
    Every lot (249 on 2026-09-08) with live ``emptyCapacity``. One call covers the whole
    city, which is why "parking near me" is answered from a single shared cached fetch
    rather than by querying the lots the user happens to be near.

``GET /ispark/ParkDetay?id=<parkID>``
    Adds the tariff text, the address and — crucially — ``updateDate``, the only
    timestamp İSPARK publishes anywhere. The list endpoint carries none, so a lot whose
    detail we never fetched can be shown but not dated.

The trap worth knowing: ParkDetay answers an *unknown* id with a plausible-looking dummy
record (capacity 1) instead of an error. :meth:`IsparkSource.park_detail` therefore
refuses to call it before checking the id against the live list.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ibb_mcp.config import ISPARK_DETAIL, ISPARK_LIST
from ibb_mcp.http import UpstreamUnavailable
from ibb_mcp.models import ParkingLot, Provenance, haversine_km
from ibb_mcp.sources.base import SourceContext, make_provenance

log = logging.getLogger("ibb_mcp.sources.ispark")

#: Cache key for the whole-city list. One key, so N concurrent users cost one request.
KEY_ALL = "ispark:all"

#: How many lots :meth:`IsparkSource.enrich` pulls detail for. Each detail is a separate
#: gateway request held 6 s apart by :class:`~ibb_mcp.http.PoliteClient`, so this is a
#: latency budget rather than a policy: three lots is what an answer can actually show.
ENRICH_LIMIT = 3

#: Radius multipliers tried in order when the requested radius finds nothing. Returning
#: a lot 3 km away beats returning nothing; the tool layer tells the user it widened.
RADIUS_WIDENING = (1.0, 2.0, 3.0)


def describe_availability(lot: ParkingLot) -> str:
    """One short Turkish phrase for how full a lot is.

    The agent says this out loud, so it must never overstate: an unknown occupancy says
    so instead of guessing, and "çok yer var" is reserved for genuinely empty lots.
    """
    empty = lot.empty
    if empty is None:
        return "doluluk bilgisi yok"
    if empty <= 0:
        return "dolu"

    occupancy = lot.occupancy_pct
    if occupancy is None:
        # Capacity missing, so a percentage would be invented. Quote the raw count.
        return f"{empty} boş yer"
    if occupancy >= 90 or empty <= 5:
        return "az yer kaldı"
    if occupancy >= 70:
        return "yer var"
    return "çok yer var"


class IsparkSource:
    """Reads İSPARK through the shared client and cache in :class:`SourceContext`."""

    def __init__(self, ctx: SourceContext) -> None:
        self.ctx = ctx

    # ---------------------------------------------------------------- whole city
    async def _fetch_all(self) -> list[dict[str, Any]]:
        if self.ctx.settings.offline:
            return _as_rows(self.ctx.load_fixture("ispark_park"))
        return _as_rows(await self.ctx.client.get_json(ISPARK_LIST, source="ispark"))

    async def list_parks(self) -> tuple[list[ParkingLot], Provenance]:
        """Every İSPARK lot with its live free-space count.

        The cache holds the *raw* rows and this method parses them on every call. That
        costs microseconds and buys a guarantee that matters: callers get their own
        model instances, so stamping ``distance_km`` on a result can never leak into the
        next user's answer.
        """
        rows, entry = await self.ctx.cached(KEY_ALL, self._fetch_all, source="ispark")
        lots = [lot for row in rows if (lot := _safe_parse(row)) is not None]
        return lots, make_provenance("ispark", entry=entry, url=ISPARK_LIST)

    # -------------------------------------------------------------------- detail
    async def park_detail(self, park_id: int) -> tuple[ParkingLot, Provenance]:
        """Tariff, address and ``updateDate`` for one lot.

        Validates ``park_id`` against the live list first. Skipping that check is how you
        end up quoting the dummy "capacity 1" record back to a user as if it were a real
        car park.
        """
        listed, _ = await self.list_parks()
        base = next((lot for lot in listed if lot.park_id == park_id), None)
        if base is None:
            raise ValueError(
                f"Bilinmeyen otopark id'si: {park_id}. Bu id İSPARK Park listesinde yok. "
                "ParkDetay servisi bilinmeyen id'ler için hata yerine kapasitesi 1 olan "
                "sahte bir kayıt döndürdüğü için sorgu yapılmadı; geçerli id'leri "
                "list_parks() veya find_near() ile alın."
            )

        async def loader() -> list[dict[str, Any]]:
            if self.ctx.settings.offline:
                return _as_rows(self.ctx.load_fixture("ispark_parkdetay"))
            payload = await self.ctx.client.get_json(ISPARK_DETAIL, source="ispark", params={"id": park_id})
            return _as_rows(payload)

        rows, entry = await self.ctx.cached(f"ispark:detail:{park_id}", loader, source="ispark")
        raw = next((row for row in rows if _row_id(row) == park_id), None)

        if raw is None:
            if self.ctx.settings.offline:
                # Recorded fixtures cover a single lot. Degrade to the list record — real
                # data for this lot, just without the detail-only fields — instead of
                # handing back a different lot's tariff.
                log.debug("ispark: offline detay fixture'ı %s için kayıt içermiyor", park_id)
                return base, make_provenance("ispark", entry=entry, url=ISPARK_LIST)
            raise UpstreamUnavailable(
                f"ispark: ParkDetay({park_id}) istenen kaydı döndürmedi; sahte kayıt riski nedeniyle kullanılmadı.",
                source="ispark",
            )

        merged = _merge_detail(base, ParkingLot.from_raw(raw))
        return merged, make_provenance(
            "ispark",
            entry=entry,
            reported_at=merged.updated_at,
            url=f"{ISPARK_DETAIL}?id={park_id}",
        )

    # ------------------------------------------------------------------ geosearch
    async def find_near(
        self,
        lat: float,
        lon: float,
        radius_km: float | None = None,
        min_free: int = 1,
        open_now: bool = True,
        limit: int | None = None,
    ) -> tuple[list[ParkingLot], Provenance]:
        """Open lots with free space near a point, nearest first.

        When the requested radius is empty the search widens to 2x and then 3x rather
        than reporting "no parking in İstanbul" — the caller can compare
        ``distance_km`` against the radius it asked for and say so in the answer.
        """
        lots, provenance = await self.list_parks()
        settings = self.ctx.settings
        base_radius = settings.default_radius_km if radius_km is None else radius_km
        cap = min(limit or settings.max_results, settings.max_results)

        candidates: list[ParkingLot] = []
        for lot in lots:
            if lot.lat is None or lot.lon is None:
                continue  # coordinate failed repair; a pin in the wrong place is worse than none
            if open_now and not lot.is_open:
                continue  # unknown counts as closed: never route someone to a shut barrier
            if min_free > 0 and (lot.empty is None or lot.empty < min_free):
                continue
            distance = haversine_km(lat, lon, lot.lat, lot.lon)
            candidates.append(lot.model_copy(update={"distance_km": round(distance, 3)}))

        candidates.sort(key=lambda lot: lot.distance_km if lot.distance_km is not None else float("inf"))
        for factor in RADIUS_WIDENING:
            reach = base_radius * factor
            hits = [lot for lot in candidates if lot.distance_km is not None and lot.distance_km <= reach]
            if hits:
                return hits[:cap], provenance
        return [], provenance

    # -------------------------------------------------------------------- enrich
    async def enrich(self, lots: list[ParkingLot]) -> list[ParkingLot]:
        """Add tariff and ``updateDate`` to the first :data:`ENRICH_LIMIT` lots.

        Called with a ``find_near`` result, so the first entries are the nearest ones —
        the lots a user is actually choosing between. Failures are swallowed per lot:
        a missing tariff should downgrade one line of the answer, not lose the parking
        spaces we already know about.
        """
        if not lots:
            return []

        targets = lots[:ENRICH_LIMIT]
        results = await asyncio.gather(
            *(self.park_detail(lot.park_id) for lot in targets),
            return_exceptions=True,
        )

        enriched: list[ParkingLot] = []
        for lot, result in zip(targets, results, strict=True):
            if isinstance(result, BaseException):
                log.info("ispark: %s (%s) detayı alınamadı: %r", lot.name, lot.park_id, result)
                enriched.append(lot)
                continue
            detail, _ = result
            # park_detail rebuilt the lot from the cached list, which has no geometry
            # relative to the user; carry the distance we already computed.
            enriched.append(detail.model_copy(update={"distance_km": lot.distance_km}))
        return enriched + list(lots[ENRICH_LIMIT:])


# --------------------------------------------------------------------------------------
# parsing helpers
# --------------------------------------------------------------------------------------
def _as_rows(payload: Any) -> list[dict[str, Any]]:
    """Normalise an İSPARK payload to a list of records.

    Both endpoints answer with a JSON array (ParkDetay with a one-element one). A bare
    object is accepted defensively; anything else is an upstream failure, not data.
    """
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    raise UpstreamUnavailable(
        f"ispark: beklenmeyen yanıt tipi {type(payload).__name__}",
        source="ispark",
    )


def _row_id(row: dict[str, Any]) -> int | None:
    try:
        return int(row["parkID"])
    except (KeyError, TypeError, ValueError):
        return None


def _safe_parse(row: dict[str, Any]) -> ParkingLot | None:
    """Parse one row, dropping it if it is malformed.

    249 lots arrive in one response; one bad record must not cost the user the other 248.
    """
    try:
        return ParkingLot.from_raw(row)
    except Exception as exc:  # noqa: BLE001 - any bad row is skipped, never fatal
        log.warning("ispark: kayıt çözümlenemedi (parkID=%r): %r", row.get("parkID"), exc)
        return None


def _merge_detail(base: ParkingLot, detail: ParkingLot) -> ParkingLot:
    """Overlay a ParkDetay record on its list record.

    The detail response wins for every field it actually carries, so ``emptyCapacity``
    and the ``updateDate`` that describes it stay together — quoting one call's free-space
    count with another call's timestamp would misdate the number. Fields ParkDetay omits
    (``isOpen`` most importantly) survive from the list record.
    """
    data = base.model_dump()
    for field, value in detail.model_dump().items():
        if value is not None:
            data[field] = value
    return ParkingLot(**data)
