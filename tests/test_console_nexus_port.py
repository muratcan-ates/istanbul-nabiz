"""nabiz.console.nexus_port: which snapshots reach the core again, and what a queue read waits for.

Every test runs on a fixed clock and a ledger in ``tmp_path``; no source is read (the port's
``_process_all`` is fed signals made here, test values).
"""

from __future__ import annotations

import asyncio
import pathlib
from typing import Any

from nexus_helpers import Clock, approve, build_engine, elevator, make_signal, origin

from nabiz.console.nexus_port import APPROVED_QUIET_S, QUIET_S, NexusConsole, board_key, describe_step
from nabiz.console.signals import Incoming
from nexus_core.engine import default_evidence
from nexus_core.signals import Signal


def incoming(signal: Signal) -> Incoming:
    return Incoming(signal, default_evidence(signal))


def console(engine: Any, clock: Clock) -> NexusConsole:
    return NexusConsole(engine, nabiz=None, recorded=lambda: None, offline=False, clock=clock)  # type: ignore[arg-type]


def long_outage(clock: Clock) -> Signal:
    return make_signal(
        "long_outage",
        entity="metro-equipment:ASN-9",
        observed_at=clock.now,
        station="Kartal",
        outage_id="ASN-9@2026-09-20",
        outage_hours=120.0,
        text="Kartal (M4): asansör kullanılamıyor.",
    )


def parking(clock: Clock) -> Signal:
    key = "parking:3068:ge90:warning"
    source = origin(clock.now, source="ispark")
    return make_signal("parking_full", entity=f"alert:{key}", observed_at=clock.now, provenance=source,
                       text="İzlenen otopark yüzde 92 dolu.", dedupe_key=key)  # fmt: skip


def statuses(engine: Any, ids: list[str]) -> list[str]:
    return [engine.states()[i].status for i in ids]


def test_an_approved_one_off_card_is_not_queued_again_at_the_next_read(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    port = console(engine, clock)
    for make in (long_outage, parking):
        (first,) = port._process_all([incoming(make(clock))])
        engine.decide(approve(first))
        clock.advance(minutes=5)
        assert port._process_all([incoming(make(clock))]) == [], f"{make.__name__}: an approval is not asked again"
    clock.advance(seconds=APPROVED_QUIET_S)
    again = port._process_all([incoming(long_outage(clock)), incoming(parking(clock))])
    assert statuses(engine, again) == ["awaiting_approval", "awaiting_approval"], "a day later it is asked again"


def test_an_approved_alternative_still_reaches_its_binding_check(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    port = console(engine, clock)
    (first,) = port._process_all([incoming(elevator(observed_at=clock.now))])
    engine.decide(approve(first))
    clock.advance(minutes=5)
    (second,) = port._process_all([incoming(elevator(observed_at=clock.now))])
    state = engine.states()[second]
    assert state.status == "closed_by_reflex" and state.rule_id.startswith("OA-")


def test_a_deferred_card_stays_in_the_queue_and_holds_its_outage(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    port = console(engine, clock)
    (first,) = port._process_all([incoming(long_outage(clock))])
    engine.decide(approve(first, action="defer", reason="Yarın doğrulanacak"))
    clock.advance(days=3)
    assert port._process_all([incoming(long_outage(clock))]) == []
    engine.decide(approve(first))  # a deferred card can still be decided
    assert engine.states()[first].status == "approved"


def test_a_rejection_is_quiet_for_an_hour(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    port = console(engine, clock)
    (first,) = port._process_all([incoming(parking(clock))])
    engine.decide(approve(first, action="reject", reason="Yanlış alarm"))
    clock.advance(minutes=30)
    assert port._process_all([incoming(parking(clock))]) == []
    clock.advance(seconds=QUIET_S)
    assert len(port._process_all([incoming(parking(clock))])) == 1


def test_a_hub_without_an_outage_id_is_keyed_by_its_fault_list() -> None:
    one = make_signal("hub_faults", entity="metro-hub:yenikapi", hub="Yenikapı", fault_count=2, equipment_list="A; B")
    same = make_signal("hub_faults", entity="metro-hub:yenikapi", hub="Yenikapı", fault_count=2, equipment_list="A; B",
                       observed_at=one.observed_at.replace(minute=5))  # fmt: skip
    other = make_signal("hub_faults", entity="metro-hub:yenikapi", hub="Yenikapı", fault_count=3, equipment_list="A; B; C")
    assert board_key(incoming(one)) == board_key(incoming(same)) != board_key(incoming(other))
    assert board_key(incoming(one))[2] is not None


def test_one_failing_signal_does_not_stop_the_batch(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    port = console(engine, clock)
    real = engine.process

    def flaky(signal: Signal, evidence: Any = None) -> Any:
        if signal.kind == "parking_full":
            raise RuntimeError("boom")
        return real(signal, evidence=evidence)

    engine.process = flaky  # type: ignore[method-assign]
    taken = port._process_all([incoming(parking(clock)), incoming(long_outage(clock))])
    assert statuses(engine, taken) == ["awaiting_approval"]


def test_a_queue_read_does_not_wait_for_a_slow_source(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    port = console(engine, clock)
    port.queue_wait_s = 0.05

    async def slow(*, force: bool = False) -> list[str]:
        await asyncio.sleep(5)
        return []

    port.ingest = slow  # type: ignore[method-assign]

    async def read() -> dict[str, Any]:
        return await port.queue()

    payload = asyncio.run(read())
    assert payload["reading_sources"] is True and payload["items"] == []


def test_the_trace_speaks_turkish() -> None:
    received = describe_step(
        "signal_received",
        {"signal": {"kind": "long_outage", "entity_id": "x", "payload": {"station": "Kartal"},
                    "provenance": {"source": "metro_equipment", "mode": "recorded"}}},  # fmt: skip
    )
    assert received == "Sinyal alındı: uzun süren arıza · Kartal (kaynak: Metro İstanbul arıza kaydı, kayıtlı veri)."
    drafted = describe_step("arena_drafted", {"decision": {"confidence": {"level": "medium"}, "arena_label": "x"}})
    assert "güven: orta" in drafted and "medium" not in drafted
