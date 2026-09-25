# Adapted from CloudSentinel app/llm.py (github.com/muratcan-ates/cloudsentinel @ 80938ae), MIT License,
# Copyright (c) 2026 CloudSentinel Team (YZTA Bootcamp 2026, Group 60). See NOTICE.md.
"""Named, readable reasons a NEXUS decision card may be uncertain."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict


class Uncertainty(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    label: str
    detail: str


UNCERTAINTY_TEXT: dict[str, str] = {
    "no_evidence": "Kanıt yok",
    "stale_data": "Veri eşikten eski",
    "unknown_age": "Veri yaşı bilinmiyor",
    "single_source": "Tek kaynak",
    "recorded_data": "Kayıtlı veri, canlı değil",
    "dissent": "Panelde itiraz var",
    "abstained_seat": "Yanıt vermeyen panel koltuğu var",
    "not_in_source": "Kanıtta olmayan atıf ayıklandı",
    "model_unavailable": "Model yanıt vermedi",
    "single_snapshot": "Tek gözlem anı",
    "warning_grade": "Uyarı düzeyinde sinyal",
    "no_precedent": "İnsan kararı örneği yok",
    "contested_precedent": "İnsan kararları bölünmüş",
    "no_quorum": "Panel yeter sayıya ulaşmadı",
    "rule_based_seats": "Kural tabanlı panel",
    "unverified_figures": "Öneride doğrulanmamış sayı",
}

_DETAILS: dict[str, str] = {
    "no_evidence": "Karar önerisini destekleyen kanıt bulunmuyor.",
    "stale_data": "En az bir kanıt, güncellik eşiğini aşmış.",
    "unknown_age": "En az bir kanıtın gözlem zamanı bilinmiyor.",
    "single_source": "Kanıtlar tek bir kaynaktan geliyor.",
    "recorded_data": "Kanıtlardan en az biri kayıtlı veri; canlı değil.",
    "dissent": "Panel koltuklarından en az biri karşı oy verdi.",
    "abstained_seat": "Panel koltuklarından en az biri yanıt vermedi.",
    "not_in_source": "Kanıtta bulunmayan kaynak atfı panel yanıtından çıkarıldı.",
    "model_unavailable": "Model yanıt vermedi; kural tabanlı koltuklar kullanıldı.",
    "single_snapshot": "Kanıtların tümü aynı gözlem zamanına dayanıyor.",
    "warning_grade": "Sinyal kritik değil, uyarı seviyesinde.",
    "no_precedent": "Son karar penceresinde aynı örüntü için insan hükmü yok.",
    "contested_precedent": "Son karar penceresinde aynı örüntü hem onaylandı hem reddedildi.",
    "no_quorum": "Yanıt veren koltuk sayısı panel yeter sayısının altında.",
    "rule_based_seats": "Panel yanıtları canlı model yerine sabit kurallardan üretildi.",
    "unverified_figures": "Önerideki en az bir sayı kanıt metinlerinde bulunmuyor.",
}


def uncertainty(code: str, detail: str | None = None) -> Uncertainty:
    """Return a labelled uncertainty; an unknown code is a programming error, not a finding."""
    return Uncertainty(code=code, label=UNCERTAINTY_TEXT[code], detail=detail or _DETAILS[code])


def _pattern_key(state: Any) -> tuple[str, str | None, str] | None:
    if state.decision is None:
        return None
    equipment = state.signal.payload.get("equipment_type")
    return (
        state.signal.kind,
        equipment if isinstance(equipment, str) else None,
        state.decision.proposed_action.kind,
    )


def _figures(text: str) -> set[str]:
    values = re.findall(r"(?<![A-Za-z0-9])\+?\d+(?:[.,]\d+)?%?(?![A-Za-z0-9])", text)
    return {match.lstrip("+").replace(",", ".") for match in values}


@dataclass(frozen=True)
class CardUncertaintyContext:
    signal: Any
    evidence: Sequence[Any]
    panel: Any
    author: str
    proposed_action: str
    proposed_text: str
    confidence_codes: Sequence[str]
    states: Iterable[Any]
    now: dt.datetime
    precedent_window: dt.timedelta


def card_uncertainties(context: CardUncertaintyContext) -> tuple[Uncertainty, ...]:
    """Name evidence, panel and precedent limits for a decision card without changing status."""
    codes = set(context.confidence_codes)
    snapshots = {item.provenance.observed_at for item in context.evidence}
    if context.evidence and len(snapshots) == 1:
        codes.add("single_snapshot")
    if context.signal.severity == "warning":
        codes.add("warning_grade")
    if context.panel.verdict == "no_quorum":
        codes.add("no_quorum")
    if context.author == "kural":
        codes.add("rule_based_seats")

    quoted_figures = _figures(context.proposed_text)
    evidence_figures = set().union(*(_figures(item.text) for item in context.evidence)) if context.evidence else set()
    if quoted_figures - evidence_figures:
        codes.add("unverified_figures")

    equipment = context.signal.payload.get("equipment_type")
    key = (context.signal.kind, equipment if isinstance(equipment, str) else None, context.proposed_action)
    matches = [
        state
        for state in context.states
        if state.signal.signal_id != context.signal.signal_id and _pattern_key(state) == key
    ]
    recent = [
        ruling.status
        for state in matches
        for ruling in state.rulings
        if context.now - context.precedent_window <= ruling.at <= context.now and ruling.status in {"approved", "rejected"}
    ]
    if not recent:
        codes.add("no_precedent")
    elif "approved" in recent and "rejected" in recent:
        codes.add("contested_precedent")
    return tuple(uncertainty(code) for code in UNCERTAINTY_TEXT if code in codes)
