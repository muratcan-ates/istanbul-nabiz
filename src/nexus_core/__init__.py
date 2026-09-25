"""NEXUS core: the decision layer under Nabız, as a library.

A signal comes in (an elevator out of service, a stale source); a readable if-then rule closes
it on the reflex path, or the Arena drafts a card with evidence, three seats' opinions and a
rule-computed confidence, and a person approves, edits, rejects or defers it. Every step is
sealed in a hash-chained SQLite ledger; decisions people keep approving become rule drafts that
a person may adopt for a limited time.

Standard library and pydantic only. Nothing here imports ``ibb_mcp`` or ``nabiz``: the
console is the composition root that feeds signals and evidence in and publishes cards out
(``scripts/check_architecture.py`` holds the fence).
"""

from nexus_core.arena import ArenaPort, Confidence, EvidenceItem, Opinion, RuleBasedSeats
from nexus_core.decisions import Alternative, Approval, Decision, DecisionConflict, Operator, ProposedAction
from nexus_core.engine import DecisionNotFound, DecisionReceipt, NexusEngine, ProcessResult
from nexus_core.escalation import Escalation
from nexus_core.ledger import Ledger
from nexus_core.missions import Mission, MissionError, MissionRule, load_mission, load_missions
from nexus_core.reflex import Action, ReflexEngine
from nexus_core.router import Router
from nexus_core.rule_drafts import RuleDraft, RuleDrafts
from nexus_core.signals import Origin, Signal
from nexus_core.stats import Stats

__all__ = [
    "Action",
    "Alternative",
    "Approval",
    "ArenaPort",
    "Confidence",
    "Decision",
    "DecisionConflict",
    "DecisionNotFound",
    "DecisionReceipt",
    "Escalation",
    "EvidenceItem",
    "Ledger",
    "Mission",
    "MissionError",
    "MissionRule",
    "NexusEngine",
    "Operator",
    "Opinion",
    "Origin",
    "ProcessResult",
    "ProposedAction",
    "ReflexEngine",
    "Router",
    "RuleBasedSeats",
    "RuleDraft",
    "RuleDrafts",
    "Signal",
    "Stats",
    "load_mission",
    "load_missions",
]
