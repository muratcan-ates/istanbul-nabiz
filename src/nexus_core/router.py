"""The decision router: reflex or Arena, and why.

The order is fixed and every step leaves a reason code in the :class:`RouteDecision`:

1. Find the first active rule whose ``when`` holds. Learned rules (adopted from drafts, see
   ``rule_drafts.py``) are tried before the mission files: a human adopted them for exactly
   this pattern.
2. No rule: ``no_rule``, or ``rule_expired`` when only an expired rule would have matched.
   A signal nobody wrote a rule for goes to a human, never to a guess.
3. An escalation trigger fires (``critical``, ``repeat``): Arena, whatever the rule says.
4. Otherwise the rule's own ``path`` decides (``rule_path`` when it says Arena).

The router only routes. Running the reflex, and escalating when it fails, is the engine's job.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from nexus_core.escalation import Escalation
from nexus_core.missions import EscalationSettings, Mission, MissionRule
from nexus_core.reflex import matches
from nexus_core.signals import Clock, Signal, system_clock

Path = Literal["reflex", "arena"]

NO_RULE = "no_rule"
RULE_EXPIRED = "rule_expired"
RULE_PATH = "rule_path"

#: Turkish text for every reason code a route, an escalation or a failed reflex can carry.
REASON_TEXT: dict[str, str] = {
    NO_RULE: "Bu sinyal için kural yok; insan karar verir",
    RULE_EXPIRED: "Eşleşen kuralın süresi dolmuş; insan karar verir",
    RULE_PATH: "Kural bu durumu insana yönlendiriyor",
    "critical": "Kritik sinyal",
    "repeat": "Aynı varlıkta pencere içinde tekrar eden olay",
    "reflex_failed": "Refleks kural uygulanamadı (eksik veri)",
    "approved_binding": "Onaylı alternatif (OA) çalışma anı denetiminden geçti",
    "binding_check_failed": "Onaylı alternatif çalışma anı denetiminden geçemedi; insan karar verir",
    "alternative_changed": "Bu kayıtta önerilen alternatif istasyon değişmiş",
    "alternative_unverified": "Alternatif istasyonun asansörü bu kayıtta doğrulanamadı",
    "stale_data": "Veri eşikten eski",
}


class RouteDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Path
    rule: MissionRule | None = None
    reasons: tuple[str, ...] = ()
    repeats: int = 1


class Router:
    """Routes a signal using the missions' rules, the learned rules and the escalation triggers."""

    def __init__(
        self,
        missions: Sequence[Mission],
        escalation: Escalation | None = None,
        *,
        learned: Callable[[], Sequence[MissionRule]] | None = None,
        clock: Clock = system_clock,
    ) -> None:
        self.missions = tuple(missions)
        self.escalation = escalation or Escalation(EscalationSettings.merged(m.escalation for m in self.missions))
        self._learned = learned
        self._clock = clock

    def rules(self) -> list[MissionRule]:
        """Every rule, learned ones first, active or not."""
        learned = list(self._learned()) if self._learned else []
        return learned + [rule for mission in self.missions for rule in mission.rules]

    def match(self, signal: Signal) -> tuple[MissionRule | None, bool]:
        """The first active matching rule, and whether an expired rule also matched."""
        now = self._clock()
        expired = False
        for rule in self.rules():
            if not matches(rule.when, signal):
                continue
            if rule.is_active(now):
                return rule, expired
            expired = True
        return None, expired

    def explain(self, signal: Signal) -> RouteDecision:
        rule, expired = self.match(signal)
        repeats = self.escalation.repeats(signal)
        triggers = self.escalation.reasons(signal, repeats)
        if rule is None:
            missing = RULE_EXPIRED if expired else NO_RULE
            return RouteDecision(path="arena", reasons=(missing, *triggers), repeats=repeats)
        if triggers:
            return RouteDecision(path="arena", rule=rule, reasons=triggers, repeats=repeats)
        if rule.path == "arena":
            return RouteDecision(path="arena", rule=rule, reasons=(RULE_PATH,), repeats=repeats)
        return RouteDecision(path="reflex", rule=rule, repeats=repeats)

    def route(self, signal: Signal) -> Path:
        return self.explain(signal).path
