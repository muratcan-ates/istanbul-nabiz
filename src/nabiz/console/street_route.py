"""Turn pedestrian directions into the route card v0.1 data contract."""

from __future__ import annotations

import hashlib
from typing import Any

from nabiz.console.route_provider_azure import Directions, RouteProvider

_MANEUVERS = {
    "Depart": ("Yürümeye başlayın.", "Start walking."),
    "TurnRight": ("Sağa dönün.", "Turn right."),
    "TurnLeft": ("Sola dönün.", "Turn left."),
    "Straight": ("Düz devam edin.", "Continue straight."),
    "Arrive": ("Hedefe vardınız.", "You have arrived."),
}
_UNKNOWN = {
    "tr": ["Kaldırım durumu bilinmiyor.", "Giriş durumu bilinmiyor.", "Asansör durumu bilinmiyor."],
    "en": ["Sidewalk status is unknown.", "Entrance status is unknown.", "Lift status is unknown."],
}


def maneuver_text(code: str, lang: str) -> str:
    """Unknown maneuver codes remain uncertain rather than guessing a turn."""
    texts = _MANEUVERS.get(code)
    if texts is None:
        return "Yön adımı bilinmiyor." if lang == "tr" else "Direction step is unknown."
    return texts[0] if lang == "tr" else texts[1]


def route_card(
    from_name: str,
    to_name: str,
    needs: list[str],
    directions: Directions | None,
    *,
    lang: str,
) -> dict[str, Any]:
    """A stable, plain-data route card; missing provider data cannot become a line."""
    available = directions is not None
    sample = bool(directions and directions.sample)
    title = "Yaya rotası" if lang == "tr" else "Walking route"
    digest = hashlib.sha256(f"route\0{title}\0{from_name}\0{to_name}".encode()).hexdigest()[:10]
    provider = "sahte" if sample else "azure_maps" if available else "nabiz_kayit"
    if available:
        source = {
            "name": "Elle yazılmış örnek" if sample else "Azure Maps",
            "url": None if sample else "https://atlas.microsoft.com",
            "observed_at": None,
            "freshness": "kayitli" if sample else "dogrulanamadi",
        }
    else:
        source = None
    steps = directions.maneuvers if directions else ()
    legs = [
        {"kind": "walk", "title": maneuver_text(code, lang), "detail": "", "minutes": None, "lift_text": None} for code in steps
    ]
    disclaimer = (
        "Sokak rotası bağlantısı kapalı. Çizgi ve adım gösterilmiyor."
        if not available and lang == "tr"
        else "Street routing is off. No line or steps are shown."
        if not available
        else "Elle yazılmış örnek. Gerçek sokak rotası değildir."
        if sample and lang == "tr"
        else "Hand-written sample. This is not a real street route."
        if sample
        else "Kaldırım, giriş ve asansör bilgileri doğrulanmadı."
        if lang == "tr"
        else "Sidewalk, entrance and lift information is unverified."
    )
    return {
        "v": 0,
        "id": f"card-route-{digest}",
        "conversation_id": None,
        "message_id": None,
        "type": "route",
        "status": "ready" if available else "unavailable",
        "title": title,
        "source": source,
        "linked": {"event_id": None, "report_code": None, "operation_id": None},
        "actions": [],
        "data": {
            "from": from_name,
            "to": to_name,
            "needs": needs,
            "legs": legs,
            "unknown_segments": _UNKNOWN[lang].copy() if available else [],
            "street_geometry": available and not sample,
            "provider": provider,
            "sample": sample,
            "disclaimer": disclaimer,
        },
        "sensitive": False,
    }


async def make_street_route(
    provider: RouteProvider,
    origin: tuple[float, float],
    destination: tuple[float, float],
    names: tuple[str, str],
    *,
    needs: list[str],
    lang: str,
    consent: bool,
) -> dict[str, Any]:
    """One explicit lookup, with no retained location and no fallback straight line."""
    directions = await provider.directions(origin, destination, consent=consent)
    card = route_card(*names, needs, directions, lang=lang)
    return {
        "provider_status": (
            "kapalı" if not consent else "doğrulanamadı" if directions is None and provider.status == "hazır" else provider.status
        ),
        "card": card,
        "geometry": [list(point) for point in directions.points] if directions and not directions.sample else [],
    }
