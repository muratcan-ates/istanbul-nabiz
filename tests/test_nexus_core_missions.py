"""nexus_core.missions: readable if-then rules from TOML, and a loud refusal of anything unsafe."""

from __future__ import annotations

import datetime as dt
import pathlib
import textwrap
import tomllib

import pytest
from nexus_helpers import MISSIONS_DIR, T0, missions

from nexus_core.missions import (
    ACTION_CATALOG,
    Condition,
    EscalationSettings,
    MissionError,
    MissionRule,
    load_mission,
    load_missions,
    parse_mission,
    template_fields,
)

RULE = """
[mission]
id = "deneme"
title = "Deneme"
reviewed_on = 2026-09-25

[[rules]]
id = "{rule_id}"
path = "reflex"
expires_days = 30
[rules.when]
kind = "equipment_fault"
conditions = [{{ field = "equipment_type", op = "eq", value = "escalator" }}]
[rules.then]
action = "{action}"
card_template = "{template}"
"""


def mission_text(rule_id: str = "R-90", action: str = "publish_card", template: str = "{station} kapalı") -> str:
    return RULE.format(rule_id=rule_id, action=action, template=template)


def write(tmp_path: pathlib.Path, name: str, text: str) -> pathlib.Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_the_repository_mission_loads_and_every_rule_is_time_bound() -> None:
    (mission,) = missions()
    assert mission.id == "erisilebilir-yolculuk" and mission.source == "erisilebilir_yolculuk.toml"
    assert [r.id for r in mission.rules] == ["R-01", "R-02", "R-03", "R-04", "R-05", "R-06"]
    for rule in mission.rules:
        assert rule.then.action in ACTION_CATALOG
        assert rule.expires_at == dt.datetime(2026, 10, 25, tzinfo=dt.UTC)
    assert mission.escalation.repeat_threshold == 3 and "hub_faults" in mission.escalation.critical_kinds


def test_no_repository_card_text_says_an_elevator_works() -> None:
    """The data never supports "çalışıyor"; the most it supports is "no fault in the İBB record"."""
    for rule in missions()[0].rules:
        assert "çalışıyor" not in rule.then.card_template.lower()
        assert "ETA" not in rule.then.card_template


def test_a_minimal_mission_loads(tmp_path: pathlib.Path) -> None:
    mission = load_mission(write(tmp_path, "a.toml", mission_text()))
    (rule,) = mission.rules
    assert rule.when.conditions == (Condition(field="equipment_type", op="eq", value="escalator"),)
    assert rule.valid_from == dt.datetime(2026, 9, 25, tzinfo=dt.UTC)


@pytest.mark.parametrize("action", ["approve", "send_email", "delete_record", "adopt_rule", "change_threshold"])
def test_an_action_outside_the_catalog_fails_to_load(tmp_path: pathlib.Path, action: str) -> None:
    """Approving, sending, deleting or changing a rule is never something a rule may do."""
    with pytest.raises(MissionError, match=r"(?s)b\.toml.*not in the reflex catalog"):
        load_mission(write(tmp_path, "b.toml", mission_text(action=action)))


@pytest.mark.parametrize(
    "template",
    ["{station.__class__}", "{station[0]}", "{station!r}", "{station:>9999}", "{Station}", "{0}"],
)
def test_a_template_is_plain_placeholders_only(tmp_path: pathlib.Path, template: str) -> None:
    with pytest.raises(MissionError, match="plain lower-case name"):
        load_mission(write(tmp_path, "c.toml", mission_text(template=template)))


def test_template_fields_lists_names_in_order() -> None:
    assert template_fields("{station}: {alternative_station} (+{extra_minutes} dk) {{literal}}") == [
        "station",
        "alternative_station",
        "extra_minutes",
    ]


@pytest.mark.parametrize(
    "condition",
    [
        {"field": "down_days", "op": "gte", "value": "7"},
        {"field": "down_days", "op": "gt", "value": True},
        {"field": "line", "op": "in", "value": "M2"},
        {"field": "line", "op": "present", "value": "M2"},
        {"field": "line", "op": "eq"},
        {"field": "line", "op": "eq", "value": ["M2"]},
        {"field": "Line", "op": "eq", "value": "M2"},
        {"field": "line", "op": "matches", "value": ".*"},
    ],
)
def test_a_condition_must_fit_its_operator(condition: dict) -> None:
    with pytest.raises(ValueError):
        Condition.model_validate(condition)


def test_expiry_needs_a_start(tmp_path: pathlib.Path) -> None:
    text = mission_text().replace("reviewed_on = 2026-09-25\n", "")
    with pytest.raises(MissionError, match="expires_days needs valid_from"):
        load_mission(write(tmp_path, "d.toml", text))


def test_a_rule_is_active_from_its_start_until_it_expires(tmp_path: pathlib.Path) -> None:
    (rule,) = load_mission(write(tmp_path, "e.toml", mission_text())).rules
    start = dt.datetime(2026, 9, 25, tzinfo=dt.UTC)
    assert not rule.is_active(start - dt.timedelta(seconds=1))
    assert rule.is_active(start) and rule.is_active(start + dt.timedelta(days=29, hours=23))
    assert not rule.is_active(start + dt.timedelta(days=30))


def test_a_rule_without_expiry_never_expires() -> None:
    rule = MissionRule.model_validate(
        {"id": "R-X", "path": "reflex", "when": {"kind": "a"}, "then": {"action": "publish_card", "card_template": "x"}}
    )
    assert rule.expires_at is None and rule.is_active(T0 + dt.timedelta(days=3650))


def test_duplicate_rule_ids_fail_in_one_file_and_across_files(tmp_path: pathlib.Path) -> None:
    text = mission_text()
    doubled = text + "\n" + text[text.index("[[rules]]") :]
    with pytest.raises(MissionError, match="duplicate rule id"):
        load_mission(write(tmp_path, "f.toml", doubled))
    folder = tmp_path / "two"
    folder.mkdir()
    write(folder, "a.toml", mission_text())
    write(folder, "b.toml", mission_text().replace('id = "deneme"', 'id = "diger"'))
    with pytest.raises(MissionError, match="already defined in a.toml"):
        load_missions(folder)


def test_bad_toml_and_unknown_tables_fail_with_the_file_name(tmp_path: pathlib.Path) -> None:
    with pytest.raises(MissionError, match="g.toml"):
        load_mission(write(tmp_path, "g.toml", "[mission\n"))
    with pytest.raises(MissionError, match="unknown top-level"):
        parse_mission({"mission": {"id": "x", "title": "x"}, "reflexes": []}, source="h.toml")


def test_unknown_keys_in_a_rule_fail(tmp_path: pathlib.Path) -> None:
    text = mission_text().replace('path = "reflex"', 'path = "reflex"\nauto_approve = true')
    with pytest.raises(MissionError, match="auto_approve"):
        load_mission(write(tmp_path, "i.toml", text))


def test_escalation_settings_merge_to_the_strictest() -> None:
    merged = EscalationSettings.merged(
        [
            EscalationSettings(window_hours=24, repeat_threshold=5, critical_kinds=("a",)),
            EscalationSettings(window_hours=336, repeat_threshold=3, critical_kinds=("b",)),
        ]
    )
    assert merged == EscalationSettings(window_hours=336, repeat_threshold=3, critical_kinds=("a", "b"))
    assert EscalationSettings.merged([]) == EscalationSettings()


def test_the_mission_directory_holds_only_toml_the_loader_reads() -> None:
    """Besides the README that documents the format, nothing sits there that the loader would skip."""
    for path in MISSIONS_DIR.iterdir():
        if path.name == "README.md":
            continue
        assert path.suffix == ".toml", path
        tomllib.loads(path.read_text(encoding="utf-8"))
