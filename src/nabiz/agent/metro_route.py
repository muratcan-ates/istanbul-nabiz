"""Which metro questions the live announcements answer, and which belong to the service pages.

``metro_status`` returns Metro İstanbul's live disruption and works announcements, nothing else. A
question about how the service runs ("Gece metrosu hangi günler çalışıyor?", "M4 24 saat açık mı?",
"Metroya evcil hayvanla binilir mi?") is not answered by an announcement: sent there, the rule path
showed whatever notice was live (an unrelated M7 one, 26 Sep). Those questions leave the tool path as
out of scope, so the chat looks them up in the service-page index instead (``ibb_services_search``).
"""

from __future__ import annotations

import re
from typing import Any

#: Folded phrases (``ibb_mcp.text.normalize_tr``) that ask about the service, matched as substrings.
SERVICE_PHRASES = (
    "gece metro", "gece sefer", "gece otobus", "24 saat", "hangi gun", "hafta sonu", "hafta ici",
    "calisma saat", "sefer saat", "kacta basl", "kacta bit", "kacta acil", "kacta kapan", "ilk sefer",
    "son sefer", "yolcu hak", "sikayet", "oneri", "kayip esya", "erisilebilirlik hizmet", "evcil hayvan",
    "bisiklet",
)  # fmt: skip


def asks_about_service(folded: str) -> bool:
    """Is this metro question about how the service runs rather than about a disruption now?"""
    return any(phrase in folded for phrase in SERVICE_PHRASES)


def metro_route(folded: str, line: re.Match[str] | None) -> tuple[str, dict[str, Any]]:
    """``metro_status`` for a disruption question; out of scope (the service pages) for a service one."""
    if asks_about_service(folded):
        return "", {"reason": "scope"}
    return "metro_status", {"line": line.group(1).upper() if line else None}


#: Words that ask about a station's lifts or escalators: İBB's fault record answers those, not
#: the station list (whose lift count says nothing about whether one is out of service).
EQUIPMENT_WORDS = ("asansor", "yuruyen merdiven", "yuruyen bant", "lift", "elevator", "escalator")


def station_route(folded: str, place: str) -> tuple[str, dict[str, Any]]:
    """A station question: its fault record when it names a lift or an escalator, else its facilities."""
    if any(word in folded for word in EQUIPMENT_WORDS):
        return "metro_equipment_status", {"station": place}
    return "metro_station_info", {"name": place}
