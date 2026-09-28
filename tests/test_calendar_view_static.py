"""The Takvim tab's calendar view: overlap lanes, plan parsing and the calendar file, run in node (no browser)."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from test_static_a11y import STATIC

MODULE = STATIC / "js" / "calendar_view.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run(tmp_path, body: str) -> dict:
    """Load the module as ESM with stub imports and no DOM, then run ``body``."""
    source = MODULE.read_text(encoding="utf-8")
    source = source.replace("import { API_BASE } from './config.js';", "const API_BASE = '';")
    source = source.replace("import { currentLang, t } from './i18n_text.js';",
                            "const currentLang = () => 'tr'; const t = (key, fallback) => fallback;")
    script = tmp_path / "cal.mjs"
    script.write_text(source + "\n" + body, encoding="utf-8")
    return json.loads(subprocess.run(["node", str(script)], capture_output=True, text=True, check=True).stdout)


def test_overlapping_events_share_the_hour_side_by_side(tmp_path) -> None:
    out = run(tmp_path, """
const d = (h, m = 0) => new Date(2026, 8, 28, h, m);
const placed = lanes([
  { id: 'a', start: d(14), end: d(15) }, { id: 'b', start: d(14, 30), end: d(16) }, { id: 'c', start: d(20), end: d(21) },
]);
process.stdout.write(JSON.stringify(Object.fromEntries(placed.map((p) => [p.id, [p.lane, p.lanes]]))));
""")
    assert out == {"a": [0, 2], "b": [1, 2], "c": [0, 1]}


def test_plans_without_a_time_are_all_day_and_a_missing_end_is_one_hour(tmp_path) -> None:
    out = run(tmp_path, """
const day = normalize({ id: 'x', title: 'Gösterim', starts_at: '2026-09-29' }, 'device');
const timed = normalize({ id: 'y', title: 'Konser', starts_at: '2026-09-28T20:30' }, 'device');
const bad = normalize({ id: 'z', title: 'Bozuk', starts_at: 'yarın' }, 'device');
const hours = (timed.end - timed.start) / 3600000;
process.stdout.write(JSON.stringify({ allDay: day.allDay, hours, startH: timed.start.getHours(), bad }));
""")
    assert out == {"allDay": True, "hours": 1, "startH": 20, "bad": None}


def test_the_calendar_file_is_a_single_event_with_escaped_text(tmp_path) -> None:
    out = run(tmp_path, """
const item = normalize({ id: 'k', title: 'Konser; Harbiye, açık hava', starts_at: '2026-09-28T20:30', ends_at: '2026-09-28T22:30',
  place: 'Harbiye' }, 'device');
process.stdout.write(JSON.stringify(icsText(item, new Date(Date.UTC(2026, 8, 28, 12)))));
""")
    assert out.count("BEGIN:VEVENT") == 1 and out.endswith("END:VCALENDAR\r\n")
    assert "SUMMARY:Konser\\; Harbiye\\, açık hava" in out
    assert "LOCATION:Harbiye" in out and "DTSTAMP:20260928T120000Z" in out


def test_the_page_loads_the_view_and_the_offline_shell_keeps_it() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert '<script type="module" src="/js/calendar_view.js"></script>' in html
    assert "'/js/calendar_view.js'" in sw and "'/css/calendar_view.css'" in sw
    source = MODULE.read_text(encoding="utf-8")
    assert "api.ibb.gov.tr" not in source and "canlı" not in source.lower()
