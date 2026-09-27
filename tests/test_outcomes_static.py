from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest

STATIC = pathlib.Path(__file__).parents[1] / "src/nabiz/console/static"
MODULE = STATIC / "js/console_outcomes.js"
CSS = STATIC / "css/console_outcomes.css"


def node_json(expression: str, payload: object | None = None) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    url = json.dumps(MODULE.as_uri())
    script = (
        "import fs from 'node:fs';\n"
        "const input = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
        f"const board = await import({url});\n"
        f"const output = {expression};\n"
        "console.log(JSON.stringify(output));\n"
    )
    result = subprocess.run(
        [node, "--experimental-default-type=module", "--input-type=module", "-e", script],
        input=json.dumps(payload or {}, ensure_ascii=False), capture_output=True, text=True,
        cwd=STATIC, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_metric_markup_shows_denominator_hides_small_sample_percent_and_escapes_labels() -> None:
    measured = {"key": "o1_requests", "label": "<script>etiket</script>", "kind": "ratio", "status": "measured",
                "numerator": 9, "denominator": 12, "value": 75, "source": "test", "note": None}
    insufficient = {**measured, "key": "o1_cards", "label": "Kart", "status": "insufficient",
                    "numerator": 1, "denominator": 3, "value": None, "reason": "En az 10 örnek gerekir, şu an 3."}
    unmeasured = {**measured, "key": "o3_confirmed", "label": "Teyit", "status": "unmeasured",
                  "numerator": None, "denominator": None, "value": None, "reason": "Kaynak yok."}
    result = node_json(
        "[board.metricMarkup(input.measured), board.metricMarkup(input.insufficient), board.metricMarkup(input.unmeasured), "
        "board.boardMarkup(input.data, null, false, input.next, input.saved)]",
        {"measured": measured, "insufficient": insufficient, "unmeasured": unmeasured,
         "data": {"window_days": 30, "min_n": 10, "groups": []},
         "saved": {"taken_at": "2026-09-27T12:00:00+00:00", "window_days": 30, "metrics": []},
         "next": "2026-09-27T12:05:00+00:00"},
    )
    assert "%" in result[0] and "Penceredeki talep: 12" in result[0]
    assert "<script>" not in result[0] and "&lt;script&gt;" in result[0]
    assert "Henüz ölçülmedi" in result[1] and "1 / 3" in result[1] and "%" not in result[1]
    assert "Kaynak yok." in result[2] and "Henüz ölçülmedi" in result[2]
    assert "Son kayıt:" in result[3] and "Henüz kayıt yok." not in result[3]


def test_duration_and_denominator_helpers_cover_expected_turkish_forms() -> None:
    values = node_json(
        "[board.formatDuration(59), board.formatDuration(38 * 60), board.formatDuration(2 * 3600 + 14 * 60), "
        "board.formatDuration(3 * 86400), ...Array.from({length: 100}, (_, i) => "
        "board.denominatorText({key: 'o1_requests', numerator: i + 1, denominator: i + 1}))]"
    )
    assert values[:4] == ["59 sn", "38 dk", "2 sa 14 dk", "3 gün"]
    assert all(value and "undefined" not in value for value in values[4:])


def test_window_preference_falls_back_to_thirty_for_broken_storage() -> None:
    values = node_json(
        "[board.readWindow({getItem: () => '{'}), board.readWindow({getItem: () => {throw new Error('blocked')}}), "
        "board.readWindow({getItem: () => JSON.stringify({version: 1, days: 7})}), "
        "board.readWindow({getItem: () => JSON.stringify({version: 2, days: 7})})]"
    )
    assert values == [30, 30, 7, 30]


def test_static_module_respects_console_motion_privacy_and_mock_rules() -> None:
    js = MODULE.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert "setInterval" not in js and "scroll" not in js
    assert "canlı" not in js.lower() and "\u2014" not in js and "\u2013" not in js
    assert not re.search(r"#[0-9a-fA-F]{3,8}|\brgb\s*\(", css)
    assert "--danger" not in css and not re.search(r"\bred\b", css.lower())
    assert "opacity:" not in css
    assert "if (typeof document !== 'undefined') mount();" in js
    assert "let currentHost = host;" in js and "const currentHost =" not in js
    assert js.index("if (api.MOCK) return;") < js.index("const host = placeBoard();")
    assert "setTimeout" in js and "addEventListener('scroll'" not in js
    assert "aria-disabled=\"true\"" in js and "role=\"status\"" in js
    assert "transition:" not in css and "animation:" not in css
