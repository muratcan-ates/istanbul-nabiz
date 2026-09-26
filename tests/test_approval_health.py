from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import shutil
import subprocess
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nexus_helpers import Clock, approve, build_engine, elevator, make_signal

from nabiz.console.access import is_operator_path
from nabiz.console.approval_health_api import approval_health_routes
from nabiz.console.nexus_port import NexusConsole
from nabiz.console.ports import OPERATOR, Ports
from nexus_core.approval_health import REASON_LABELS, compute_approval_health
from nexus_core.stats import compute_stats

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"


def outage(n: int, when: dt.datetime):
    return make_signal(entity=f"E-{n:03d}", observed_at=when, **elevator(f"O-{n:03d}").payload)


def rule(
    engine: Any,
    clock: Clock,
    count: int,
    action: str,
    *,
    start: int = 0,
    wait_s: float = 30,
    reason: str | None = None,
) -> None:
    labels = {
        "approve": "Kanıt güncel ve yeterli: test notu",
        "edit": "Kanıt güncel ve yeterli: test notu",
        "reject": "Kanıt yetersiz: test notu",
        "defer": "Ek doğrulama gerekiyor: test notu",
    }
    for n in range(start, start + count):
        signal_id = engine.process(outage(n, clock.now)).signal_id
        clock.advance(seconds=wait_s)
        engine.decide(approve(signal_id, action, reason or labels[action], "Düzenlenmiş metin" if action == "edit" else None))


def approval_client(engine: Any, clock: Clock) -> TestClient:
    app = FastAPI()
    app.state.ports = Ports(console=NexusConsole(engine, nabiz=None, recorded=lambda: None, offline=True, clock=clock))
    app.include_router(approval_health_routes)
    return TestClient(app)


def node_json(expression: str, payload: object | None = None) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = (
        "import fs from 'node:fs';\n"
        "globalThis.window = { location: { search: '' } };\n"
        "const input = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
        "const health = await import('./js/console_health.js');\n"
        f"const output = {expression};\n"
        "console.log(JSON.stringify(output));\n"
    )
    result = subprocess.run(
        [node, "--experimental-default-type=module", "--input-type=module", "-e", script],
        input=json.dumps(payload or {}, ensure_ascii=False),
        capture_output=True,
        text=True,
        cwd=STATIC,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_nine_rulings_keep_the_stats_rate_but_are_insufficient(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    rule(engine, clock, 9, "approve")
    stats = compute_stats(engine.states().values(), clock.now)
    health = compute_approval_health(engine.states().values(), stats)
    assert health.approval_rate == stats.approval_rate == 1.0
    assert health.sufficient is False
    assert health.median_decision_s == stats.median_decision_s
    assert sum(bucket.count for bucket in health.durations) == 9


def test_fifty_approvals_share_stats_window_without_returning_a_second_alarm(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    rule(engine, clock, 50, "approve")
    stats = engine.stats()
    health = compute_approval_health(engine.states().values(), stats)
    payload = approval_client(engine, clock).get("/api/console/approval-health").json()
    assert health.approval_rate == stats.approval_rate == 1.0
    assert health.rulings_counted == 50 and stats.rubber_stamp_warning is True
    assert "warnings" not in payload and "band" not in payload


def test_thirty_mixed_rulings_count_actions_and_reasons(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    rule(engine, clock, 24, "approve")
    rule(engine, clock, 6, "reject", start=24)
    health = compute_approval_health(engine.states().values(), engine.stats())
    assert health.approval_rate == 0.8
    assert health.sufficient is True
    assert health.by_action == {"approve": 24, "edit": 0, "reject": 6}
    assert {item.code: item.count for item in health.reasons}["evidence_current"] == 24
    assert {item.code: item.count for item in health.reasons}["evidence_insufficient"] == 6


def test_rate_median_and_ruling_count_match_stats_with_deferrals(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    rule(engine, clock, 4, "approve", wait_s=10)
    rule(engine, clock, 2, "defer", start=4, wait_s=60)
    rule(engine, clock, 5, "reject", start=6, wait_s=300)
    stats = compute_stats(engine.states().values(), clock.now)
    health = compute_approval_health(engine.states().values(), stats)
    assert (health.approval_rate, health.median_decision_s, health.rulings_counted) == (
        stats.approval_rate,
        stats.median_decision_s,
        stats.rulings_counted,
    )


def test_window_keeps_only_the_last_fifty_verdicts(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    rule(engine, clock, 10, "reject")
    rule(engine, clock, 50, "approve", start=10)
    health = compute_approval_health(engine.states().values(), engine.stats())
    assert health.rulings_counted == 50
    assert health.approval_rate == 1.0
    assert health.by_action["reject"] == 0


def test_deferrals_are_excluded_from_reason_window_but_still_timed(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    rule(engine, clock, 10, "approve")
    rule(engine, clock, 3, "defer", start=10)
    health = compute_approval_health(engine.states().values(), engine.stats())
    assert health.rulings_counted == 10
    assert health.decisions_timed == 13
    assert sum(bucket.count for bucket in health.durations) == 13
    assert health.by_action["approve"] == 10
    assert health.without_code == 0


def test_duration_buckets_have_fixed_edges(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    for n, wait in enumerate((5, 10, 59, 60, 299, 300)):
        signal_id = engine.process(outage(n, clock.now)).signal_id
        clock.advance(seconds=wait)
        engine.decide(approve(signal_id))
    health = compute_approval_health(engine.states().values(), engine.stats())
    assert [bucket.count for bucket in health.durations] == [1, 2, 2, 1]


def test_reason_codes_count_known_prefixes_and_never_return_free_text(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    rule(engine, clock, 1, "reject", reason="Kanıt yetersiz: SENSITIVE-TEST")
    rule(engine, clock, 1, "reject", start=1, reason="serbest yazı")
    response = approval_client(engine, clock).get("/api/console/approval-health")
    body = response.json()
    assert {item["code"]: item["count"] for item in body["reasons"]["codes"]}["evidence_insufficient"] == 1
    assert body["reasons"]["without_code"] == 1
    assert "SENSITIVE-TEST" not in json.dumps(body)


def test_reason_table_matches_console_cards() -> None:
    source = (STATIC / "js" / "console-cards.js").read_text(encoding="utf-8")
    found = []
    for group, block in re.findall(r"(approve|reject|defer): \[(.*?)\]", source, flags=re.S):
        found.extend((code, group, label) for code, label in re.findall(r"\{ code: '(\w+)', label: '([^']+)' \}", block))
    expected = [(code, group, label) for code, (group, label) in REASON_LABELS.items()]
    assert found == expected
    assert len(found) == 10


def test_approval_health_endpoint_answers_with_the_role_and_reduced_contract(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    rule(engine, clock, 2, "approve")
    body = approval_client(engine, clock).get("/api/console/approval-health").json()
    assert body["actor"] == OPERATOR
    assert set(body) == {
        "actor",
        "window",
        "sufficient",
        "approval_rate",
        "median_decision_s",
        "decisions_timed",
        "durations",
        "reasons",
        "generated_at",
    }
    assert body["window"] == {"size": 50, "rulings_counted": 2, "min_rulings": 10}
    assert body["sufficient"] is False


def test_endpoint_contains_no_person_identifier_or_free_text(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    rule(engine, clock, 1, "reject", reason="Kanıt yetersiz: PRIVATE-SUFFIX")
    body = approval_client(engine, clock).get("/api/console/approval-health").json()
    forbidden = {"score", "operator_name", "handle", "operator_id"}

    def walk(value: Any) -> list[str]:
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            return [text for child in value.values() for text in walk(child)]
        if isinstance(value, list):
            return [text for child in value for text in walk(child)]
        return [value] if isinstance(value, str) else []

    strings = walk(body)
    assert "simule-operator" not in strings
    assert "PRIVATE-SUFFIX" not in strings


def test_unwired_console_answers_503_not_500() -> None:
    app = FastAPI()
    app.state.ports = Ports()
    app.include_router(approval_health_routes)
    response = TestClient(app).get("/api/console/approval-health")
    assert response.status_code == 503
    assert response.json() == {"error": "not_wired", "message": "Karar çekirdeği bu süreçte bağlı değil."}


def test_endpoint_strings_have_no_typographic_dash(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    body = approval_client(engine, clock).get("/api/console/approval-health").json()

    def strings(value: Any):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)

    assert all("—" not in value and "–" not in value for value in strings(body))


def test_operator_gate_covers_the_new_endpoint() -> None:
    assert is_operator_path("/api/console/approval-health")


def test_duration_list_renders_zero_buckets_and_matching_median() -> None:
    payload = {
        "durations": [
            {"key": "lt_10s", "label": "10 sn altı", "count": 0},
            {"key": "s10_60", "label": "10 sn ile 1 dk", "count": 0},
            {"key": "m1_5", "label": "1 ile 5 dk", "count": 0},
            {"key": "gt_5m", "label": "5 dk ve üstü", "count": 0},
        ],
        "median": 30,
    }
    result = node_json("health.durationList(input.durations, input.median)", payload)
    assert result.count("<li>") == 4
    assert result.count("--w: 0%") == 4
    assert "Medyan karar süresi: 30 sn" in result


def test_reason_list_shows_action_and_coded_reason_counts() -> None:
    payload = {
        "reasons": {
            "by_action": {"approve": 1, "edit": 1, "reject": 1},
            "codes": [{"code": "evidence_current", "label": "Kanıt güncel ve yeterli", "group": "approve", "count": 1}],
            "without_code": 0,
        }
    }
    result = node_json("health.reasonList(input.reasons)", payload)
    assert "Onay 1 · Düzenleyerek onay 1 · Ret 1" in result
    assert "Kanıt güncel ve yeterli" in result and "Kodsuz gerekçe" in result


def test_reduced_section_shows_insufficient_sample_without_band_or_alert() -> None:
    payload = {
        "actor": OPERATOR,
        "window": {"size": 50, "rulings_counted": 2, "min_rulings": 10},
        "sufficient": False,
        "approval_rate": 1.0,
        "median_decision_s": 30.0,
        "durations": [{"key": "lt_10s", "label": "10 sn altı", "count": 2}],
        "reasons": {"by_action": {"approve": 2, "edit": 0, "reject": 0}, "codes": [], "without_code": 2},
    }
    result = node_json("health.healthSection(input)", payload)
    assert 'id="approval-health"' in result and 'aria-labelledby="health-title"' in result
    assert "Onay oranı %100 · yetersiz örnek" in result
    assert "Yetersiz örnek: 2 karar var" in result
    assert "health-dot" not in result and "role=\"alert\"" not in result


def test_reduced_module_exports_no_band_or_warning_renderer() -> None:
    source = (STATIC / "js" / "console_health.js").read_text(encoding="utf-8")
    assert "bandSvg" not in source and "alertCard" not in source and "alertRole" not in source
    assert "health-dot" not in source and "role=\"alert\"" not in source
    assert "getElementById('day')" in source
    assert "/api/console/approval-health" in source


def test_health_css_uses_tokens_and_has_no_literal_colour_or_motion() -> None:
    css = (STATIC / "css" / "console_health.css").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}|\b(?:rgb|hsl|oklch)\s*\(|\b(?:animation|transition)\s*:", css)
    assert "var(--primary)" in css and "var(--text-muted)" in css and "var(--surface-sunken)" in css


def _token_values(source: str) -> dict[str, str]:
    return dict(re.findall(r"--([\w-]+):\s*([^;]+);", source))


def _resolve_token(name: str, values: dict[str, str], seen: frozenset[str] = frozenset()) -> str:
    assert name not in seen
    value = values[name].strip()
    match = re.fullmatch(r"var\(--([\w-]+)\)", value)
    return _resolve_token(match.group(1), values, seen | {name}) if match else value


def _luminance(color: str) -> float:
    assert re.fullmatch(r"#[0-9a-fA-F]{6}", color)
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))


def _contrast(first: str, second: str, values: dict[str, str]) -> float:
    luminances = sorted((_luminance(_resolve_token(first, values)), _luminance(_resolve_token(second, values))))
    return (luminances[1] + 0.05) / (luminances[0] + 0.05)


def test_health_text_and_bars_meet_contrast_in_both_themes() -> None:
    source = (STATIC / "css" / "tokens.css").read_text(encoding="utf-8")
    dark_start = source.index("@media (prefers-color-scheme: dark)")
    light_values = _token_values(source[:dark_start])
    dark_values = light_values | _token_values(source[dark_start:])
    themes = (light_values, dark_values)
    text_pairs = (("text", "surface-raised"), ("text-muted", "surface-raised"))
    graphic_pairs = (("primary", "surface-sunken"),)
    for values in themes:
        assert all(_contrast(first, second, values) >= 4.5 for first, second in text_pairs)
        assert all(_contrast(first, second, values) >= 3 for first, second in graphic_pairs)


def test_health_module_passes_node_syntax_check() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [node, "--check", "--experimental-default-type=module", str(STATIC / "js" / "console_health.js")],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
