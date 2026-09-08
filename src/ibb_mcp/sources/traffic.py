"""İBB traffic index: a single 1–99 number for the whole city.

The index is what İBB's own traffic map shows; it updates every five minutes and is
returned as a *history* array, newest first, by
``/tkmservices/api/TrafficData/v1/TrafficIndexHistory/{days}/{period}``.

**The trap in this endpoint:** it content-negotiates and *defaults to XML*. Without an
explicit ``Accept: application/json`` header the body is an ``<ArrayOfTrafficIndex>``
document and JSON parsing fails with a confusing error — so every call here passes
``accept_json=True`` deliberately. Verified 2026-09-08: ``/1/H`` returns 25 points,
covering the last 24 hours plus the current one.

That 25-point shape is exactly what a "şu an vs. dün aynı saat" answer needs, which is
why :func:`compare_with_yesterday` is built on the default ``days=1, period='H'`` call
and needs no second request.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Sequence

from ibb_mcp.config import TRAFFIC_INDEX_HISTORY
from ibb_mcp.models import ISTANBUL_TZ, Provenance, TrafficIndexPoint, describe_traffic
from ibb_mcp.sources.base import SourceContext, make_provenance

#: Aggregation buckets the endpoint accepts. Anything else 404s at the gateway.
VALID_PERIODS: dict[str, str] = {
    "5M": "5 dakikalık",
    "H": "saatlik",
    "D": "günlük",
    "M": "aylık",
    "Y": "yıllık",
}

MAX_DAYS = 365

#: How far a candidate point may sit from "exactly 24 hours ago" and still count as the
#: same hour. An hourly series lands within minutes; anything looser would silently
#: compare 09:00 with 06:00.
SAME_HOUR_TOLERANCE_SECONDS = 5400.0

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def _sort_key(point: TrafficIndexPoint) -> tuple[bool, dt.datetime]:
    """Order oldest → newest, pushing unparseable timestamps to the end."""
    return (point.at is None, point.at or _EPOCH)


class TrafficSource:
    """Reads the city-wide traffic index through the shared client and cache."""

    def __init__(self, ctx: SourceContext) -> None:
        self.ctx = ctx

    async def index_history(
        self,
        days: int = 1,
        period: str = "H",
    ) -> tuple[list[TrafficIndexPoint], Provenance]:
        """Traffic index history, returned oldest → newest.

        ``days`` is the look-back window and ``period`` the bucket size (``5M``, ``H``,
        ``D``, ``M``, ``Y``). Upstream sends newest-first; we reverse it so callers can
        treat the list as a time series and take ``[-1]`` for "now".
        """
        bucket = str(period).strip().upper()
        if bucket not in VALID_PERIODS:
            raise ValueError(f"period '{period}' geçersiz; beklenen: {', '.join(VALID_PERIODS)}")
        if not isinstance(days, int) or isinstance(days, bool):
            raise ValueError("days tam sayı olmalı")
        if not 1 <= days <= MAX_DAYS:
            raise ValueError(f"days 1 ile {MAX_DAYS} arasında olmalı, {days} verildi")

        url = f"{TRAFFIC_INDEX_HISTORY}/{days}/{bucket}"

        async def load() -> list[dict[str, Any]]:
            if self.ctx.settings.offline:
                return self.ctx.load_fixture("traffic_index_1h")
            # accept_json=True is load-bearing: the endpoint returns XML by default.
            payload = await self.ctx.client.get_json(url, source="traffic", accept_json=True)
            return payload if isinstance(payload, list) else []

        raw, entry = await self.ctx.cached(f"traffic:{days}:{bucket}", load, source="traffic")
        points = sorted((TrafficIndexPoint.from_raw(item) for item in raw), key=_sort_key)
        newest = next((p.at for p in reversed(points) if p.at is not None), None)
        return points, make_provenance("traffic", entry=entry, reported_at=newest, url=url)

    async def current(self) -> tuple[TrafficIndexPoint | None, Provenance]:
        """The newest point of the hourly series, or ``None`` when nothing parsed.

        Deliberately reuses the ``1/H`` history rather than issuing its own request: the
        answer to "şu an trafik nasıl?" and to "düne göre nasıl?" then come from one
        cached payload.
        """
        points, provenance = await self.index_history(days=1, period="H")
        newest = next((p for p in reversed(points) if p.at is not None), None)
        return newest, provenance


def compare_with_yesterday(points: Sequence[TrafficIndexPoint]) -> dict[str, Any]:
    """Compare the newest index with the same hour a day earlier.

    Returns ``now``, ``same_hour_yesterday``, ``delta`` and a ready Turkish
    ``description``. Every field is ``None`` when the series cannot support the claim —
    a missing yesterday is reported as missing, never as "değişiklik yok".
    """
    ordered = sorted((p for p in points if p.at is not None), key=lambda p: p.at)
    if not ordered:
        return {
            "now": None,
            "same_hour_yesterday": None,
            "delta": None,
            "description": "Trafik indeksi verisi okunamadı.",
        }

    now_point = ordered[-1]
    target = now_point.at - dt.timedelta(hours=24)
    earlier = ordered[:-1]
    yesterday: TrafficIndexPoint | None = None
    if earlier:
        closest = min(earlier, key=lambda p: abs((p.at - target).total_seconds()))
        if abs((closest.at - target).total_seconds()) <= SAME_HOUR_TOLERANCE_SECONDS:
            yesterday = closest

    local_now = now_point.at.astimezone(ISTANBUL_TZ)
    now_label = describe_traffic(now_point.index)
    text = f"Trafik yoğunluğu {local_now:%H:%M} itibarıyla {now_point.index} ({now_label})."

    delta: int | None = None
    if yesterday is not None:
        delta = now_point.index - yesterday.index
        y_label = describe_traffic(yesterday.index)
        if delta > 0:
            change = f"dünkü aynı saate göre {delta} puan daha yoğun"
        elif delta < 0:
            change = f"dünkü aynı saate göre {abs(delta)} puan daha akıcı"
        else:
            change = "dünkü aynı saatle aynı seviyede"
        text += f" Dün aynı saatte {yesterday.index} ({y_label}) idi; {change}."
    else:
        text += " Dünkü aynı saate ait karşılaştırma verisi yok."

    return {
        "now": _point_dict(now_point),
        "same_hour_yesterday": _point_dict(yesterday) if yesterday else None,
        "delta": delta,
        "description": text,
    }


def _point_dict(point: TrafficIndexPoint) -> dict[str, Any]:
    local = point.at.astimezone(ISTANBUL_TZ) if point.at else None
    return {
        "index": point.index,
        "label": describe_traffic(point.index),
        "at_utc": point.at.isoformat() if point.at else None,
        "at_local": local.isoformat() if local else None,
    }
