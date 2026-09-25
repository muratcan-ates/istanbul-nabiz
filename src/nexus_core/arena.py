# Adapted from CloudSentinel app/debate.py (github.com/muratcan-ates/cloudsentinel @ 80938ae), MIT License,
# Copyright (c) 2026 CloudSentinel Team (YZTA Bootcamp 2026, Group 60). See NOTICE.md.
"""The Arena: three seats argue an escalated signal from its evidence, a human decides.

The seats are Erişilebilirlik (who loses step-free access, and what replaces it), Operasyon
(is the evidence fresh enough to act on, is this a maintenance matter) and İletişim (can the
citizen text say where it came from and how old it is). Each writes a stance with a rationale
and cites the evidence it rests on. The Arena prepares a card; it never applies anything, and
nothing in this module can approve (``decisions.py``).

Who sits in the seats is a port (:class:`ArenaPort`). :class:`RuleBasedSeats` fills them from
the evidence with fixed rules and says so on the card ("Koltuklar kural tabanlı (model yok)");
a model-backed port can replace it later without touching the engine. Whatever the port
returns is screened before it reaches a card: unknown or repeated seats are dropped, a missing
seat is marked abstained, and a citation that is not one of the evidence items is removed and
flagged ``not_in_source``, so a model cannot invent a source. A port that raises falls back
to the rule-based seats.

Confidence is computed here, deterministically, from uncertainty codes about the evidence and
the seats' stances (:func:`assess_confidence`). Nothing a seat says about its own certainty is
read: an :class:`Opinion` has no field for it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nexus_core.signals import Clock, Origin, Signal, system_clock
from nexus_core.uncertainty import UNCERTAINTY_TEXT

Role = Literal["Erişilebilirlik", "Operasyon", "İletişim"]
Stance = Literal["support", "oppose", "conditional"]
Author = Literal["kural", "model", "yerel model"]
ConfidenceLevel = Literal["high", "medium", "low"]

SEAT_ROLES: tuple[Role, ...] = ("Erişilebilirlik", "Operasyon", "İletişim")
RULE_BASED_LABEL = "Koltuklar kural tabanlı (model yok)"
DEFAULT_STALE_AFTER_S = 900
LONG_OUTAGE_DAYS = 7
STEP_FREE_EQUIPMENT = frozenset({"elevator", "asansör"})

#: A code in NOT_COUNTED is shown, not scored.
BLOCKING_CODES = frozenset({"no_evidence", "stale_data", "unknown_age"})
NOT_COUNTED = frozenset({"model_unavailable", "warning_grade", "rule_based_seats", "no_precedent"})
HIGH_REASONS = ("Kanıt taze", "Birden çok kaynak", "Koltuklar arasında itiraz yok")
PANEL_QUORUM = 2
MAX_ROUNDS = 2


class PanelVotes(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    support: int = Field(ge=0)
    oppose: int = Field(ge=0)
    conditional: int = Field(ge=0)


class PanelVerdict(BaseModel):
    """The panel's label for a card; it cannot approve or change the card's status."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Literal["publish", "hold", "tie", "no_quorum"]
    votes: PanelVotes
    answered: int = Field(ge=0)
    quorum: int = Field(default=PANEL_QUORUM, ge=1)
    rounds: Literal[1, 2] = 1


class EvidenceItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, max_length=600)
    provenance: Origin


class Opinion(BaseModel):
    """One seat's view. There is deliberately no confidence field."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Role
    stance: Stance
    rationale: str = Field(min_length=1, max_length=600)
    citations: tuple[Origin, ...] = ()


class Confidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    level: ConfidenceLevel
    reasons: tuple[str, ...]
    codes: tuple[str, ...] = ()


@runtime_checkable
class ArenaPort(Protocol):
    """Fills the three seats. It sees the signal and the evidence, and nothing that can act."""

    author: Author
    label: str

    def opinions(self, signal: Signal, evidence: Sequence[EvidenceItem]) -> list[Opinion]: ...


class ArenaOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    opinions: tuple[Opinion, ...]
    dissent_summary: str
    confidence: Confidence
    author: Author
    label: str
    panel: PanelVerdict


def _stale(evidence: Sequence[EvidenceItem], now: dt.datetime, stale_after_s: int) -> int | None:
    """The oldest known age over the threshold, in seconds; ``None`` when all are fresh or unknown."""
    ages = [age for item in evidence if (age := item.provenance.age_s(now)) is not None and age > stale_after_s]
    return max(ages) if ages else None


def _minutes(seconds: int) -> int:
    return max(1, round(seconds / 60))


class RuleBasedSeats:
    """Three seats filled by fixed rules over the signal and its evidence. No model involved."""

    author: Author = "kural"
    label = RULE_BASED_LABEL

    def __init__(self, *, stale_after_s: int = DEFAULT_STALE_AFTER_S, clock: Clock = system_clock) -> None:
        self.stale_after_s = stale_after_s
        self._clock = clock

    def opinions(self, signal: Signal, evidence: Sequence[EvidenceItem]) -> list[Opinion]:
        now = self._clock()
        cited = tuple(dict.fromkeys(item.provenance for item in evidence))
        return [
            Opinion(role="Erişilebilirlik", citations=cited, **self._accessibility(signal)),
            Opinion(role="Operasyon", citations=cited, **self._operations(signal, evidence, now)),
            Opinion(role="İletişim", citations=cited, **self._communication(evidence)),
        ]

    @staticmethod
    def _accessibility(signal: Signal) -> dict[str, str]:
        payload = signal.payload
        step_free = payload.get("equipment_type") in STEP_FREE_EQUIPMENT or payload.get("step_free_affected") is True
        where = payload.get("station") or signal.entity_id
        alternative = payload.get("alternative_station")
        if not step_free:
            return {"stance": "support", "rationale": "Adımsız erişimi doğrudan etkilemiyor; bilgi kartı yeterli."}
        if not alternative:
            text = (
                f"{where}: adımsız erişim kesildi ve kayıtta alternatif istasyon yok. "
                "Alternatif uydurulmamalı; vatandaşa 'doğrulanamadı' denmeli."
            )
            return {"stance": "conditional", "rationale": text}
        extra = payload.get("extra_minutes")
        detail = f" (+{extra} dk)" if isinstance(extra, int) else ""
        text = f"{where}: adımsız erişim kesildi. {alternative}{detail} adımsız yolculuğu sürdürür; yayımlanmalı."
        return {"stance": "support", "rationale": text}

    def _operations(self, signal: Signal, evidence: Sequence[EvidenceItem], now: dt.datetime) -> dict[str, str]:
        if not evidence:
            return {"stance": "oppose", "rationale": "Kanıt yok; kanıtsız karar yayımlanmaz."}
        stale = _stale(evidence, now, self.stale_after_s)
        if stale is not None:
            limit = _minutes(self.stale_after_s)
            text = f"En eski kanıt {_minutes(stale)} dk önce gözlendi (eşik {limit} dk); yayımlamadan önce doğrulanmalı."
            return {"stance": "oppose", "rationale": text}
        days = signal.payload.get("down_days")
        if isinstance(days, int) and days >= LONG_OUTAGE_DAYS:
            text = f"Arıza {days} gündür sürüyor; bakım talebi taslağı (simüle) önerilir."
            return {"stance": "conditional", "rationale": text}
        return {"stance": "support", "rationale": "Kanıt eşik içinde taze; işletme açısından engel yok."}

    @staticmethod
    def _communication(evidence: Sequence[EvidenceItem]) -> dict[str, str]:
        if not evidence:
            return {"stance": "oppose", "rationale": "Kaynak gösterilemiyor; vatandaş metni yazılamaz."}
        if any(item.provenance.mode == "recorded" for item in evidence):
            text = "Veri kayıtlı, canlı değil; metin 'son bilinen durum' ve veri yaşıyla yayımlanmalı."
            return {"stance": "conditional", "rationale": text}
        if len({item.provenance.source for item in evidence}) < 2:
            return {"stance": "conditional", "rationale": "Tek kaynak; metin kaynağı ve veri yaşını açıkça yazmalı."}
        return {"stance": "support", "rationale": "Metin kaynak ve veri yaşıyla yayımlanabilir."}


def _as_opinion(raw: object) -> Opinion | None:
    """An :class:`Opinion`, or ``None`` for anything a port returned that is not one."""
    if isinstance(raw, Opinion):
        return raw
    try:
        return Opinion.model_validate(raw)
    except ValidationError:
        return None


def screen(opinions: Sequence[object], evidence: Sequence[EvidenceItem]) -> tuple[tuple[Opinion, ...], set[str]]:
    """Keep one opinion per known seat, in seat order, citing only the evidence. Returns the codes raised."""
    known = {item.provenance for item in evidence}
    by_role: dict[str, Opinion] = {}
    codes: set[str] = set()
    for raw in opinions:
        opinion = _as_opinion(raw)
        if opinion is None or opinion.role in by_role:
            continue
        kept = tuple(c for c in opinion.citations if c in known)
        if len(kept) < len(opinion.citations):
            codes.add("not_in_source")
        by_role[opinion.role] = opinion.model_copy(update={"citations": kept})
    if len(by_role) < len(SEAT_ROLES):
        codes.add("abstained_seat")
    return tuple(by_role[role] for role in SEAT_ROLES if role in by_role), codes


def dissent_summary(opinions: Sequence[Opinion]) -> str:
    """The minority view first: who objects, who agrees only on a condition, who did not answer."""
    against = [f"{o.role} karşı: {o.rationale}" for o in opinions if o.stance == "oppose"]
    conditional = [f"{o.role} şartlı: {o.rationale}" for o in opinions if o.stance == "conditional"]
    silent = [role for role in SEAT_ROLES if role not in {o.role for o in opinions}]
    parts = against + conditional
    if silent:
        parts.append(f"Yanıt vermeyen koltuk: {', '.join(silent)}.")
    return " ".join(parts) if parts else "İtiraz yok: üç koltuk da destekliyor."


def uncertainty_codes(
    evidence: Sequence[EvidenceItem], opinions: Sequence[Opinion], now: dt.datetime, stale_after_s: int
) -> set[str]:
    """What is uncertain about this card, from the evidence and the stances alone."""
    codes: set[str] = set()
    if not evidence:
        codes.add("no_evidence")
    if _stale(evidence, now, stale_after_s) is not None:
        codes.add("stale_data")
    if any(item.provenance.observed_at is None for item in evidence):
        codes.add("unknown_age")
    if len({item.provenance.source for item in evidence}) == 1:
        codes.add("single_source")
    if any(item.provenance.mode == "recorded" for item in evidence):
        codes.add("recorded_data")
    if any(o.stance == "oppose" for o in opinions):
        codes.add("dissent")
    return codes


def assess_confidence(codes: set[str]) -> Confidence:
    """Low on any blocking code or on two counted codes, medium on one, high on none."""
    counted = codes - NOT_COUNTED
    if counted & BLOCKING_CODES or len(counted) >= 2:
        level: ConfidenceLevel = "low"
    elif counted:
        level = "medium"
    else:
        level = "high"
    ordered = tuple(code for code in UNCERTAINTY_TEXT if code in codes)
    reasons = tuple(UNCERTAINTY_TEXT[code] for code in ordered) if counted else HIGH_REASONS
    return Confidence(level=level, reasons=reasons, codes=ordered)


def vote(opinions: Sequence[Opinion], quorum: int = PANEL_QUORUM) -> PanelVerdict:
    """Count answered seats; conditional is visible but does not vote either way."""
    votes = PanelVotes(
        support=sum(o.stance == "support" for o in opinions),
        oppose=sum(o.stance == "oppose" for o in opinions),
        conditional=sum(o.stance == "conditional" for o in opinions),
    )
    if len(opinions) < quorum:
        verdict: Literal["publish", "hold", "tie", "no_quorum"] = "no_quorum"
    elif votes.support == votes.oppose:
        verdict = "tie"
    else:
        verdict = "publish" if votes.support > votes.oppose else "hold"
    return PanelVerdict(verdict=verdict, votes=votes, answered=len(opinions), quorum=quorum)


def convene(
    port: ArenaPort | None,
    signal: Signal,
    evidence: Sequence[EvidenceItem],
    now: dt.datetime,
    stale_after_s: int = DEFAULT_STALE_AFTER_S,
) -> ArenaOutcome:
    """Ask the port for opinions, optionally give it one revision, and label the panel vote."""
    fallback = RuleBasedSeats(stale_after_s=stale_after_s, clock=lambda: now)
    seats: ArenaPort = port or fallback
    extra: set[str] = set()
    try:
        raw = seats.opinions(signal, evidence)
    except Exception:  # noqa: BLE001 - a failing model is a degraded card, never a lost signal
        seats, raw = fallback, fallback.opinions(signal, evidence)
        extra.add("model_unavailable")
    opinions, screened = screen(raw, evidence)
    panel = vote(opinions)
    revise = getattr(seats, "revise", None)
    if (any(o.stance == "oppose" for o in opinions) or panel.verdict == "no_quorum") and callable(revise):
        try:
            revised_raw = revise(signal, evidence, opinions)
        except Exception:  # noqa: BLE001 - a failed optional round leaves the first panel intact
            extra.add("model_unavailable")
        else:
            opinions, screened = screen(revised_raw, evidence)
            panel = vote(opinions).model_copy(update={"rounds": MAX_ROUNDS})
    codes = uncertainty_codes(evidence, opinions, now, stale_after_s) | screened | extra
    return ArenaOutcome(
        opinions=opinions,
        dissent_summary=dissent_summary(opinions),
        confidence=assess_confidence(codes),
        author=seats.author,
        label=seats.label,
        panel=panel,
    )
