"""nexus_core.reflex: named operators only, missing data never fires, a card is never half empty."""

from __future__ import annotations

import pytest
from nexus_helpers import escalator, make_signal, missions

from nexus_core.missions import Condition, MissionRule, When
from nexus_core.reflex import MissingField, ReflexEngine, check, matches, render


def cond(op: str, value: object = None, field: str = "x") -> Condition:
    return Condition(field=field, op=op, value=value)


@pytest.mark.parametrize(
    ("condition", "values", "expected"),
    [
        (cond("eq", "elevator"), {"x": "elevator"}, True),
        (cond("eq", 3), {"x": 3.0}, True),
        (cond("eq", 1), {"x": True}, False),  # a bool is not the number 1
        (cond("eq", "1"), {"x": 1}, False),  # a string is not a number
        (cond("ne", "elevator"), {"x": "escalator"}, True),
        (cond("in", ("M1A", "M2")), {"x": "M2"}, True),
        (cond("not_in", ("M1A", "M2")), {"x": "M2"}, False),
        (cond("gte", 7), {"x": 7}, True),
        (cond("gt", 7), {"x": 7}, False),
        (cond("lt", 7), {"x": "3"}, False),  # a number compared with text is false, not an error
        (cond("lte", 7.5), {"x": 7}, True),
        (cond("present"), {"x": 0}, True),
        (cond("absent"), {}, True),
        (cond("absent"), {"x": None}, True),
        (cond("absent"), {"x": "Şişhane"}, False),
        (cond("true"), {"x": True}, True),
        (cond("true"), {"x": 1}, False),
        (cond("false"), {"x": False}, True),
    ],
)
def test_operators(condition: Condition, values: dict, expected: bool) -> None:
    assert check(condition, values) is expected


@pytest.mark.parametrize("op", ["eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "present", "true", "false"])
def test_missing_data_never_fires_a_condition(op: str) -> None:
    value = {"in": ("a",), "not_in": ("a",)}.get(op, None if op in {"present", "true", "false"} else 1)
    assert check(cond(op, value), {}) is False
    assert check(cond(op, value), {"x": None}) is False


def test_a_rule_matches_its_kind_and_every_condition() -> None:
    when = When(kind="equipment_fault", conditions=(cond("eq", "escalator", "equipment_type"),))
    assert matches(when, escalator())
    assert not matches(when, escalator(equipment_type="elevator"))
    assert not matches(when, make_signal("source_stale", equipment_type="escalator"))


def test_conditions_can_read_the_signal_severity() -> None:
    when = When(kind="equipment_fault", conditions=(cond("eq", "critical", "severity"),))
    assert matches(when, make_signal(severity="critical")) and not matches(when, make_signal())


def test_render_fills_names_and_never_re_expands_a_value() -> None:
    assert render("{station} ({line})", {"station": "Taksim", "line": "M2"}) == "Taksim (M2)"
    assert render("{station}", {"station": "{secret}"}) == "{secret}"
    with pytest.raises(MissingField, match="line"):
        render("{station} ({line})", {"station": "Taksim"})
    with pytest.raises(MissingField):
        render("{station}", {"station": ""})


def rule(rule_id: str) -> MissionRule:
    return next(r for mission in missions() for r in mission.rules if r.id == rule_id)


def test_a_reflex_run_returns_the_action_and_the_card() -> None:
    result = ReflexEngine().run(rule("R-03"), escalator())
    assert result.ok and result.failure is None and result.elapsed_ms >= 0
    action = result.action
    assert action.kind == "publish_card" and action.rule_id == "R-03" and action.author == "kural"
    assert action.card.body == "Kadıköy istasyonunda yürüyen merdiven kullanılamıyor (İBB kaydı)."
    assert action.card.title == escalator().title and action.card.kind == "metro_equipment"


def test_a_rule_title_template_is_rendered_too() -> None:
    from nexus_helpers import elevator

    result = ReflexEngine().run(rule("R-01"), elevator())
    assert result.ok and result.action.card.title == "Adımsız erişim: Taksim"
    assert "Şişhane" in result.action.card.body and "+4 dk" in result.action.card.body


def test_a_rule_that_cannot_fill_its_card_fails_and_names_the_field() -> None:
    result = ReflexEngine().run(rule("R-03"), escalator(station=None))
    assert not result.ok and result.action is None and result.failure == "missing_field:station"
