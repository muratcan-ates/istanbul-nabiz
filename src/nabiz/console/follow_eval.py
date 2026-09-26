"""What a followed topic looks like now, and what changed since last time.

Every read goes through the one :class:`~ibb_mcp.tools.Nabiz` facade and its shared cache, the
same data every visitor sees (DECISIONS #3): the alert engine (``check_alerts``: a line's notices,
``lift_outage`` for a station's or a line's recorded faults, ``bus_bunching``), the station list
and the service-page index. A topic is evaluated once per run however many people follow it.

A state is ``{alert key: sentence}``. The key is the engine's ``dedupe_key``, which changes when the
news changes (a new notice text, a worse fault), so "new" and "resolved" are set differences. A
source that could not be read gives ``unavailable`` and no diff: "could not look" is never
reported as "resolved".
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ibb_mcp.models import utcnow
from nabiz.console.follow import KINDS, Topic

log = logging.getLogger("nabiz.console.follow")

INDEX_MISSING = "Bilgi arşivi bu sunucuda kurulu değil; yeni kaynak kontrol edilemedi."
NO_STATION = "Bu adla bir metro istasyonu bulunamadı."


@dataclass
class TopicState:
    topic: Topic
    active: dict[str, str] = field(default_factory=dict)
    active_en: dict[str, str] = field(default_factory=dict)
    unavailable: str | None = None
    checked_at: str = ""

    def public(self) -> dict[str, Any]:
        """What the page shows for a topic: sentences only, each already naming its source and age."""
        return {
            "key": self.topic.key,
            "kind": self.topic.kind,
            "value": self.topic.value,
            "label": self.topic.label,
            "note": self.topic.note,
            "email": bool(KINDS.get(self.topic.kind, {}).get("email")),
            "active": list(self.active.values()),
            "fingerprint": sorted(self.active),
            "unavailable": self.unavailable,
            "checked_at": self.checked_at,
        }


@dataclass(frozen=True)
class Change:
    kind: str  # "new" | "resolved"
    topic: str
    text_tr: str
    text_en: str


def rules_for(topic: Topic) -> list[dict[str, Any]]:
    """The alert-engine rules one topic stands for."""
    if topic.kind == "metro_line":
        return [
            {"kind": "metro_disruption", "lines": [topic.value]},
            {"kind": "lift_outage", "lines": [topic.value], "equipment": ["elevator"]},
        ]
    if topic.kind == "station":
        return [{"kind": "lift_outage", "stations": [topic.value], "equipment": ["elevator", "escalator"]}]
    if topic.kind == "bus_line":
        return [{"kind": "bus_bunching", "line": topic.value}]
    return []


async def _alerts(nabiz: Any, topic: Topic, state: TopicState) -> None:
    result = await nabiz.check_alerts({"rules": rules_for(topic)})
    data = result.data
    for alert in data.get("alerts", []):
        state.active[alert["dedupe_key"]] = alert["message_tr"]
        state.active_en[alert["dedupe_key"]] = alert.get("message_en") or alert["message_tr"]
    if data.get("unavailable"):
        state.unavailable = " ".join(data["unavailable"].values())


async def _knowledge(nabiz: Any, topic: Topic, state: TopicState) -> None:
    result = await nabiz.ibb_services_search(query=topic.value, limit=5)
    data = result.data
    if (data.get("evidence") or {}).get("level") == "index_missing":
        state.unavailable = INDEX_MISSING
        return
    for hit in data.get("hits", []):
        url = str(hit.get("url") or "")
        if not url:
            continue
        stamp = hit.get("source_updated_at") or hit.get("fetched_at") or "tarih yok"
        title = str(hit.get("title") or url)
        state.active[f"page:{url}"] = f"{title} ({url}); kaynak tarihi: {stamp}"
        state.active_en[f"page:{url}"] = f"{title} ({url}); source date: {stamp}"


async def evaluate_topic(nabiz: Any, topic: Topic) -> TopicState:
    """One topic's state now. Never raises: a failure is the state's ``unavailable`` sentence."""
    state = TopicState(topic, checked_at=utcnow().isoformat(timespec="seconds"))
    try:
        if topic.kind == "station":
            try:
                await nabiz.metro_station_info(name=topic.value)
            except ValueError:
                state.unavailable = NO_STATION
                return state
        if topic.kind == "knowledge":
            await _knowledge(nabiz, topic, state)
        else:
            await _alerts(nabiz, topic, state)
    except Exception as exc:  # noqa: BLE001 - one unreadable source must not stop the other topics
        log.warning("follow topic %s not evaluated: %s", topic.kind, type(exc).__name__)
        state.unavailable = "Kaynak şu an okunamadı; değişiklik kontrol edilemedi."
    return state


async def evaluate_topics(nabiz: Any, topics: Iterable[Topic]) -> dict[str, TopicState]:
    """Each distinct topic once, in order."""
    states: dict[str, TopicState] = {}
    for topic in topics:
        if topic.supported and topic.key not in states:
            states[topic.key] = await evaluate_topic(nabiz, topic)
    return states


def diff(previous: Mapping[str, str] | None, state: TopicState) -> list[Change]:
    """New and resolved items since ``previous`` (``None``: nothing was known, so all is new)."""
    if state.unavailable:
        return []
    before = dict(previous or {})
    label = state.topic.label
    changes = [
        Change("new", label, text, state.active_en.get(key, text)) for key, text in state.active.items() if key not in before
    ]
    changes += [Change("resolved", label, text, text) for key, text in before.items() if key not in state.active]
    return changes


def essential(topic: Topic, changes: Iterable[Change]) -> list[Change]:
    """The changes worth an e-mail: a new or cleared fault, a line notice, a new service page."""
    if not KINDS.get(topic.kind, {}).get("email"):
        return []
    return list(changes)
