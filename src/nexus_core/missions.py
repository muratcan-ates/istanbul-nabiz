# Adapted from CloudSentinel app/actions.py (github.com/muratcan-ates/cloudsentinel @ 80938ae), MIT License,
# Copyright (c) 2026 CloudSentinel Team (YZTA Bootcamp 2026, Group 60). See NOTICE.md.
"""Missions: the if-then rules NEXUS runs, read from TOML with ``tomllib``.

A mission file is a small library of readable rules ("EĞER asansör kullanılamıyor VE
alternatif istasyon varsa O ZAMAN vatandaş kartını güncelle")::

    [mission]
    id = "erisilebilir-yolculuk"
    title = "Erişilebilir yolculuk"
    reviewed_on = 2026-09-25          # expires_days counts from here

    [escalation]
    window_hours = 336                # the same entity seen this often in this window ...
    repeat_threshold = 3              # ... goes to a human
    critical_kinds = ["hub_faults"]

    [[rules]]
    id = "R-01"
    path = "reflex"                   # reflex: closed by the rule; arena: drafted for a human
    expires_days = 30
    [rules.when]
    kind = "equipment_fault"
    conditions = [{ field = "equipment_type", op = "eq", value = "elevator" }]
    [rules.then]
    action = "publish_alternative"
    card_template = "{station} istasyonunda asansör kullanılamıyor ..."

Nothing here evaluates an expression. A condition is a field name, one operator from a
fixed list and a literal; a template is plain ``{name}`` placeholders with no attribute
access, indexing or format spec; an action must be in :data:`ACTION_CATALOG`. A file that
asks for anything else fails to load, loudly, before a single signal is routed.

Rules are time-bound on purpose (the past informs, it does not command): a rule with
``expires_days`` stops matching that many days after the mission's ``reviewed_on`` (or its own
``valid_from``), and an expired rule never silently comes back.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import re
import string
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from nexus_core.signals import as_utc

#: The only things a rule may do. Everything a reflex does is reversible and stays inside
#: Nabız: nothing is sent to İBB, nothing is deleted, no threshold or rule is changed, and
#: nothing approves a decision. A rule naming any other action fails to load.
ACTION_CATALOG: dict[str, str] = {
    "publish_card": "Nabız yüzünde şablonlu bilgi kartı yayımla",
    "publish_alternative": "Adımsız alternatif metnini yayımla",
    "fold_repeat": "Sinyali açık karta katla, tekrar sayacını artır",
    "label_quality": "Veri kalitesi etiketi bas",
    "schedule_mode": "Veri yaşı ya da tarife moduna geç",
    "open_escalation": "Eskalasyon kartı aç (insana git)",
}

Op = Literal["eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "present", "absent", "true", "false"]
VALUELESS_OPS = frozenset({"present", "absent", "true", "false"})
LIST_OPS = frozenset({"in", "not_in"})
NUMERIC_OPS = frozenset({"gt", "gte", "lt", "lte"})
CardKind = Literal["metro_equipment", "metro_status", "arrival", "traffic", "air", "parking", "alternative"]

NAME_PATTERN = r"^[a-z_][a-z0-9_]*$"
_NAME = re.compile(NAME_PATTERN)
Scalar = str | int | float | bool


class MissionError(ValueError):
    """A mission file that cannot be trusted to run: bad TOML, unknown action, unsafe template."""


def template_fields(template: str) -> list[str]:
    """The placeholder names in ``template``, in order; anything but ``{name}`` is refused."""
    names: list[str] = []
    for _, name, spec, conversion in string.Formatter().parse(template):
        if name is None:
            continue
        if not _NAME.match(name) or spec or conversion:
            raise ValueError(f"template placeholder {{{name}}} must be a plain lower-case name")
        names.append(name)
    return names


class Condition(BaseModel):
    """``field op value``: one named comparison against a signal's payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str = Field(pattern=NAME_PATTERN)
    op: Op
    value: Scalar | tuple[Scalar, ...] | None = None

    @model_validator(mode="after")
    def _value_fits_op(self) -> Condition:
        if self.op in VALUELESS_OPS:
            if self.value is not None:
                raise ValueError(f"op {self.op!r} takes no value")
        elif self.op in LIST_OPS:
            if not isinstance(self.value, tuple):
                raise ValueError(f"op {self.op!r} needs a list value")
        elif self.op in NUMERIC_OPS:
            if isinstance(self.value, bool) or not isinstance(self.value, int | float):
                raise ValueError(f"op {self.op!r} needs a number")
        elif self.value is None or isinstance(self.value, tuple):
            raise ValueError(f"op {self.op!r} needs a single value")
        return self


class When(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    conditions: tuple[Condition, ...] = ()


class Then(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str
    card_template: str = Field(min_length=1, max_length=600)
    title: str | None = Field(default=None, max_length=120)
    card_kind: CardKind | None = None

    @field_validator("action")
    @classmethod
    def _in_catalog(cls, value: str) -> str:
        if value not in ACTION_CATALOG:
            raise ValueError(f"action {value!r} is not in the reflex catalog ({', '.join(ACTION_CATALOG)})")
        return value

    @field_validator("card_template", "title")
    @classmethod
    def _plain_placeholders(cls, value: str | None) -> str | None:
        if value is not None:
            template_fields(value)
        return value


class MissionRule(BaseModel):
    """One if-then rule. ``path`` says who finishes the job: the rule itself, or a human."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.@-]*$", max_length=64)
    path: Literal["reflex", "arena"]
    when: When
    then: Then
    expires_days: int | None = Field(default=None, gt=0, le=366)
    valid_from: dt.datetime | None = None

    @field_validator("valid_from", mode="before")
    @classmethod
    def _date_is_midnight_utc(cls, value: Any) -> Any:
        if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
            return dt.datetime.combine(value, dt.time(0), tzinfo=dt.UTC)
        return value

    @field_validator("valid_from")
    @classmethod
    def _aware(cls, value: dt.datetime | None) -> dt.datetime | None:
        return None if value is None else as_utc(value)

    @model_validator(mode="after")
    def _expiry_has_a_start(self) -> MissionRule:
        if self.expires_days is not None and self.valid_from is None:
            raise ValueError(f"rule {self.id}: expires_days needs valid_from or the mission's reviewed_on")
        return self

    @property
    def expires_at(self) -> dt.datetime | None:
        if self.expires_days is None or self.valid_from is None:
            return None
        return self.valid_from + dt.timedelta(days=self.expires_days)

    def is_active(self, now: dt.datetime) -> bool:
        """Started, and not yet expired. An expired rule stays expired."""
        now = as_utc(now)
        if self.valid_from is not None and now < self.valid_from:
            return False
        return self.expires_at is None or now < self.expires_at


class EscalationSettings(BaseModel):
    """When a signal a rule could close goes to a human anyway (see ``escalation.py``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_hours: int = Field(default=336, gt=0, le=24 * 90)
    repeat_threshold: int = Field(default=3, ge=2, le=100)
    critical_kinds: tuple[str, ...] = ()
    ttl_hours: int = Field(default=72, ge=0, le=24 * 90)

    @classmethod
    def merged(cls, settings: Iterable[EscalationSettings]) -> EscalationSettings:
        """The strictest combination: the widest window, lowest threshold and shortest card TTL."""
        items = list(settings)
        if not items:
            return cls()
        return cls(
            window_hours=max(s.window_hours for s in items),
            repeat_threshold=min(s.repeat_threshold for s in items),
            critical_kinds=tuple(sorted({k for s in items for k in s.critical_kinds})),
            ttl_hours=min(s.ttl_hours for s in items),
        )


class Mission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    title: str = Field(min_length=1)
    intent: str = ""
    reviewed_on: dt.date | None = None
    escalation: EscalationSettings = EscalationSettings()
    rules: tuple[MissionRule, ...] = ()
    source: str = ""


def _rule_data(raw: Mapping[str, Any], reviewed_on: dt.date | None) -> dict[str, Any]:
    data = dict(raw)
    if reviewed_on is not None and data.get("expires_days") is not None:
        data.setdefault("valid_from", reviewed_on)
    return data


def parse_rules(raw_rules: Sequence[Mapping[str, Any]], *, reviewed_on: dt.date | None = None) -> tuple[MissionRule, ...]:
    """Validate ``[[rules]]`` tables; duplicate ids in one list are an error."""
    rules = tuple(MissionRule.model_validate(_rule_data(raw, reviewed_on)) for raw in raw_rules)
    ids = [rule.id for rule in rules]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"duplicate rule id(s): {', '.join(duplicates)}")
    return rules


def parse_mission(data: Mapping[str, Any], source: str = "<memory>") -> Mission:
    """A :class:`Mission` from parsed TOML; every problem is a :class:`MissionError` naming ``source``."""
    unknown = sorted(set(data) - {"mission", "escalation", "rules"})
    if unknown:
        raise MissionError(f"{source}: unknown top-level table(s): {', '.join(unknown)}")
    try:
        header = dict(data.get("mission") or {})
        reviewed_on = header.get("reviewed_on")
        rules = parse_rules(data.get("rules") or [], reviewed_on=reviewed_on)
        return Mission.model_validate({**header, "escalation": data.get("escalation") or {}, "rules": rules, "source": source})
    except (ValidationError, ValueError, TypeError) as exc:
        raise MissionError(f"{source}: {exc}") from exc


def load_mission(path: str | pathlib.Path) -> Mission:
    path = pathlib.Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise MissionError(f"{path.name}: {exc}") from exc
    return parse_mission(data, source=path.name)


def load_missions(directory: str | pathlib.Path) -> list[Mission]:
    """Every ``*.toml`` in ``directory``, by file name. A rule id used twice across files fails."""
    missions = [load_mission(p) for p in sorted(pathlib.Path(directory).glob("*.toml"))]
    seen: dict[str, str] = {}
    for mission in missions:
        for rule in mission.rules:
            if rule.id in seen:
                raise MissionError(f"{mission.source}: rule id {rule.id} is already defined in {seen[rule.id]}")
            seen[rule.id] = mission.source
    return missions
