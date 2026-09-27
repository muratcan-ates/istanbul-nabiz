"""P00 D2a (K): each closed console panel of E67, E74, E75 and E77 offers one primary action, never two at once."""

from __future__ import annotations

import re

from conftest import REPO_ROOT

JS = REPO_ROOT / "src" / "nabiz" / "console" / "static" / "js"
PRIMARY = 'class="btn btn-primary"'


def test_incidents_outcomes_and_scenario_each_have_exactly_one_primary() -> None:
    for name, action in (("console_incidents.js", "type=\"submit\""), ("console_outcomes.js", "data-ob-save"),
                         ("console_scenario.js", "")):
        source = (JS / name).read_text(encoding="utf-8")
        assert source.count(PRIMARY) == 1, name
        line = next(text for text in source.splitlines() if PRIMARY in text)
        assert action in line, name


def test_the_knowledge_editor_shows_its_primaries_only_in_exclusive_states() -> None:
    source = (JS / "console_knowledge_editor.js").read_text(encoding="utf-8")
    candidate = source[source.index("export function candidateMarkup("):source.index("function proposalForm(")]
    # try-today and approve are two arms of one ternary; the action row hides while a reason form is open.
    approve = r"candidate\.status === 'tried'\s*\?\s*`<button class=\"btn btn-primary\"[^`]*data-ked=\"approve\""
    assert re.search(approve, candidate)
    assert "const actions = active && !form ?" in candidate
    listing = source[source.index("function candidateList("):]
    # while the proposal form is open no candidate is active, so its primary never joins the form's.
    assert "const active = selected && !state.candidateForm;" in listing
