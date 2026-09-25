"""The citizen publication port reads only cards already sealed in a NEXUS ledger."""

from __future__ import annotations

import asyncio
import datetime as dt
import pathlib
from collections.abc import Sequence
from typing import Any

from nabiz.console.published import PublishedCards
from nabiz.console.wiring import MISSIONS_DIR
from nexus_core import Approval, Ledger, NexusEngine, Operator, Origin, Signal, load_missions

NOW = dt.datetime(2026, 9, 25, 9, 0, tzinfo=dt.UTC)


def engine(tmp_path: pathlib.Path, now: dt.datetime = NOW) -> NexusEngine:
    def clock() -> dt.datetime:
        return now

    return NexusEngine(Ledger(tmp_path / "nexus.db", clock=clock), load_missions(MISSIONS_DIR), clock=clock)


def signal(kind: str, payload: dict[str, Any], *, entity: str = "sample", at: dt.datetime = NOW) -> Signal:
    return Signal.create(
        kind=kind,
        entity_id=entity,
        severity="warning",
        observed_at=at,
        provenance=Origin(source="metro_equipment", url="https://example.test/source", observed_at=at, mode="recorded"),
        payload=payload,
    )


def cards(core: NexusEngine, stations: Sequence[str], *, now: dt.datetime = NOW) -> list[dict[str, Any]]:
    port = PublishedCards(core, offline=True, stale_after_s=900, clock=lambda: now)
    return asyncio.run(port.published(stations=stations))


def test_r03_reflex_card_is_limited_to_its_station(tmp_path: pathlib.Path) -> None:
    core = engine(tmp_path)
    one = signal("equipment_fault", {"station": "Kartal", "equipment_type": "escalator"}, entity="metro-equipment:KRT-YM")
    core.process(one)

    (kartal,) = cards(core, ["Kartal"])
    assert kartal["how"]["rule_id"] == "R-03" and kartal["kind"] == "metro_equipment"
    assert kartal["how"]["signal_id"] == one.signal_id and kartal["provenance"]["mode"] == "recorded"
    assert cards(core, ["Kadıköy"]) == []


def test_r04_source_stale_is_unverified_for_any_station(tmp_path: pathlib.Path) -> None:
    core = engine(tmp_path)
    core.process(signal("source_stale", {
        "source": "metro_equipment", "age_text": "18 saat", "last_known_text": "kayıtlı bilgi",
    }, entity="source:metro_equipment"))

    (item,) = cards(core, ["Kadıköy"])
    assert item["status"] == "unverified" and item["how"]["rule_id"] == "R-04"
    assert item["how"]["tool"] == "check_alerts"


def test_r06_approved_text_is_the_published_card(tmp_path: pathlib.Path) -> None:
    core = engine(tmp_path)
    one = signal("long_outage", {"station": "Kartal", "outage_hours": 30, "text": "Kayıt uzun süredir açık."})
    core.process(one)
    core.decide(Approval(signal_id=one.signal_id, action="approve", reason="kanıt yeterli", actor=Operator()))

    (item,) = cards(core, ["Kartal"])
    assert item["how"]["rule_id"] == "R-06"
    assert item["body"].endswith("(Simüle operatör onayladı.)")


def test_rejected_arena_card_is_not_published(tmp_path: pathlib.Path) -> None:
    core = engine(tmp_path)
    one = signal("long_outage", {"station": "Kartal", "outage_hours": 30, "text": "Kayıt uzun süredir açık."})
    core.process(one)
    core.decide(Approval(signal_id=one.signal_id, action="reject", reason="yayımlanmasın", actor=Operator()))

    assert cards(core, ["Kartal"]) == []


def test_r07_parking_card_uses_the_parking_kind(tmp_path: pathlib.Path) -> None:
    core = engine(tmp_path)
    one = signal("parking_full", {"text": "Örnek otopark doluluk uyarısı."}, entity="parking:12")
    core.process(one)
    core.decide(Approval(signal_id=one.signal_id, action="approve", reason="kanıt yeterli", actor=Operator()))

    (item,) = cards(core, [])
    assert item["kind"] == "parking" and item["how"]["rule_id"] == "R-07"


def test_reflex_card_is_removed_after_its_24_hour_window(tmp_path: pathlib.Path) -> None:
    core = engine(tmp_path)
    core.process(signal("equipment_fault", {"station": "Kartal", "equipment_type": "escalator"}, entity="metro-equipment:KRT-YM"))
    later = NOW + dt.timedelta(days=2)

    assert cards(core, ["Kartal"], now=later) == []


def test_approved_card_is_removed_after_its_rule_expiry(tmp_path: pathlib.Path) -> None:
    core = engine(tmp_path)
    one = signal("parking_full", {"text": "Örnek otopark doluluk uyarısı."}, entity="parking:12")
    core.process(one)
    core.decide(Approval(signal_id=one.signal_id, action="approve", reason="kanıt yeterli", actor=Operator()))
    later = NOW + dt.timedelta(days=31)

    assert cards(core, [], now=later) == []
