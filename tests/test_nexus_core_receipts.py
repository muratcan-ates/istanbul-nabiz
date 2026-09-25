from __future__ import annotations

from collections.abc import Sequence

from nexus_helpers import Clock, build_engine, elevator, escalator

from nexus_core.arena import EvidenceItem, Opinion
from nexus_core.receipts import receipt_of
from nexus_core.signals import Signal
from nexus_core.views import decision_payload


class MeteredSeats:
    author = "model"
    label = "Sayaçlı model koltukları"

    def __init__(self) -> None:
        self.calls_made = 0

    def opinions(self, signal: Signal, evidence: Sequence[EvidenceItem]) -> list[Opinion]:
        self.calls_made += 1
        return [
            Opinion(role="Erişilebilirlik", stance="support", rationale="Kanıt yeterli."),
            Opinion(role="Operasyon", stance="support", rationale="Kanıt taze."),
            Opinion(role="İletişim", stance="conditional", rationale="Tek kaynak."),
        ]


def test_a_reflex_receipt_has_no_arena_time_and_no_calls(tmp_path) -> None:
    engine = build_engine(tmp_path, Clock())
    result = engine.process(escalator())
    assert result.receipt.path == "reflex" and result.receipt.reflex_ms is not None
    assert result.receipt.arena_ms is None and result.receipt.llm_calls == 0
    assert receipt_of(engine.states()[result.signal_id]) == result.receipt


def test_an_arena_receipt_counts_the_seats_when_the_port_has_no_counter(tmp_path) -> None:
    class UnmeteredSeats:
        author = "model"
        label = "Ölçersiz model koltukları"

        def opinions(self, signal: Signal, evidence: Sequence[EvidenceItem]) -> list[Opinion]:
            return [
                Opinion(role="Erişilebilirlik", stance="support", rationale="Kanıt yeterli."),
                Opinion(role="Operasyon", stance="support", rationale="Kanıt taze."),
                Opinion(role="İletişim", stance="conditional", rationale="Tek kaynak."),
            ]

    engine = build_engine(tmp_path, Clock(), arena=UnmeteredSeats())
    result = engine.process(elevator())
    assert result.receipt.path == "arena" and result.receipt.arena_ms is not None
    assert result.receipt.llm_calls == 3


def test_money_appears_only_when_a_call_is_priced(tmp_path) -> None:
    unpriced = build_engine(tmp_path / "unpriced", Clock(), arena=MeteredSeats()).process(elevator())
    priced = build_engine(tmp_path / "priced", Clock(), arena=MeteredSeats(), usd_per_call=0.02).process(elevator())
    assert unpriced.receipt.usd is None
    assert priced.receipt.usd == 0.02


def test_reading_the_receipt_costs_no_model_call(tmp_path) -> None:
    seats = MeteredSeats()
    engine = build_engine(tmp_path, Clock(), arena=seats)
    signal_id = engine.process(elevator()).signal_id
    before = seats.calls_made
    receipt = receipt_of(engine.states()[signal_id])
    payload = decision_payload(engine.states()[signal_id], engine._clock())
    assert seats.calls_made == before
    assert payload["receipt"]["llm_calls"] == receipt.llm_calls == 1
