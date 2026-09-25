"""The reflex path: an if-then rule closes a routine signal, with no model and no human.

:func:`matches` decides whether a rule's ``when`` holds for a signal; :class:`ReflexEngine`
runs the rule's ``then`` and returns an :class:`Action`: which catalog action to take and the
card text it publishes. The engine performs no I/O; applying the action (publishing the card)
is the console's job, after the ledger has recorded it.

Two rules from ``ibb_mcp.alerts`` carry over. Absent data never fires a rule: every operator
but ``absent`` is false on a missing or ``None`` field, and a comparison between a number and a
string is false rather than an error. And a rule that cannot fill its template does not
publish a half-empty card: the run fails with the missing field named, and the signal escalates
to a human (``escalation.REFLEX_FAILED``).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from nexus_core.missions import CardKind, Condition, MissionRule, When, template_fields
from nexus_core.signals import Signal

#: Signal attributes a condition or template may name besides the payload's own keys.
SIGNAL_FIELDS = ("entity_id", "kind", "severity")


class MissingField(LookupError):
    """A template placeholder with no value in the signal."""


class CardDraft(BaseModel):
    """What the citizen face shows. Source and data age come from the signal's provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: CardKind | None = None
    title: str
    body: str


class Action(BaseModel):
    """A reflex's output: one catalog action and the card it publishes. Written by a rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    rule_id: str
    signal_id: str
    card: CardDraft
    author: Literal["kural"] = "kural"


class ReflexResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    action: Action | None = None
    failure: str | None = None
    elapsed_ms: float


def signal_values(signal: Signal) -> dict[str, Any]:
    """The names a condition or a template can use: the payload plus a few signal attributes."""
    values = {name: getattr(signal, name) for name in SIGNAL_FIELDS}
    values.update(signal.payload)
    return values


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _equal(actual: Any, expected: Any) -> bool:
    """Numbers compare by value (3 == 3.0); anything else only within its own type ("1" != 1, True != 1)."""
    if _is_number(actual) and _is_number(expected):
        return actual == expected
    return type(actual) is type(expected) and actual == expected


def _compare(check: Callable[[float, float], bool]) -> Callable[[Any, Any], bool]:
    return lambda actual, expected: _is_number(actual) and _is_number(expected) and check(actual, expected)


_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": _equal,
    "ne": lambda actual, expected: not _equal(actual, expected),
    "in": lambda actual, expected: any(_equal(actual, item) for item in expected),
    "not_in": lambda actual, expected: not any(_equal(actual, item) for item in expected),
    "gt": _compare(lambda a, b: a > b),
    "gte": _compare(lambda a, b: a >= b),
    "lt": _compare(lambda a, b: a < b),
    "lte": _compare(lambda a, b: a <= b),
    "present": lambda actual, _: True,
    "true": lambda actual, _: actual is True,
    "false": lambda actual, _: actual is False,
}


def check(condition: Condition, values: Mapping[str, Any]) -> bool:
    """One condition against the signal's values. Missing data is false, except for ``absent``."""
    actual = values.get(condition.field)
    if condition.op == "absent":
        return actual is None
    if actual is None:
        return False
    return _OPS[condition.op](actual, condition.value)


def matches(when: When, signal: Signal) -> bool:
    """Same kind, and every condition holds."""
    if when.kind != signal.kind:
        return False
    values = signal_values(signal)
    return all(check(condition, values) for condition in when.conditions)


def _text(value: Any) -> str:
    """A value as a Turkish card writes it: 119.6 is "119,6", 24.0 is "24"."""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.1f}".replace(".", ",")
    return str(value)


def render(template: str, values: Mapping[str, Any]) -> str:
    """Fill ``{name}`` placeholders; a missing or empty value raises :class:`MissingField`."""
    filled: dict[str, str] = {}
    for name in template_fields(template):
        value = values.get(name)
        if value is None or value == "":
            raise MissingField(name)
        filled[name] = _text(value)
    return template.format_map(filled)


class ReflexEngine:
    """Runs a matched reflex rule. Stateless; the timing is the "refleks · N ms" badge."""

    def run(self, rule: MissionRule, signal: Signal) -> ReflexResult:
        started = time.perf_counter()
        values = signal_values(signal)
        try:
            body = render(rule.then.card_template, values)
            title = render(rule.then.title, values) if rule.then.title else signal.title
        except MissingField as exc:
            return ReflexResult(ok=False, failure=f"missing_field:{exc.args[0]}", elapsed_ms=_ms(started))
        card = CardDraft(kind=rule.then.card_kind, title=title, body=body)
        action = Action(kind=rule.then.action, rule_id=rule.id, signal_id=signal.signal_id, card=card)
        return ReflexResult(ok=True, action=action, elapsed_ms=_ms(started))


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
