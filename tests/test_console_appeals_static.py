"""The isolated console panel has safe text rendering and an explicit integration seam."""

from __future__ import annotations

from pathlib import Path

from ibb_mcp.config import REPO_ROOT


def test_panel_uses_text_nodes_and_authenticated_relative_routes() -> None:
    base = Path(REPO_ROOT) / "src/nabiz/console/static"
    script = (base / "js/console_appeals.js").read_text(encoding="utf-8")
    style = (base / "css/console_appeals.css").read_text(encoding="utf-8")
    assert "export async function mountConsoleAppeals" in script
    assert "credentials: 'same-origin'" in script
    assert "textContent" in script and "innerHTML" not in script
    assert "Operatör belirteci" not in script
    assert "/api/console/appeals" in script
    assert ":focus-visible" in style and "44px" in style
    assert "var(--focus-ring)" in style and "var(--focus)" not in style
    assert "getElementById('appeals')" in script
    assert "\u2013" not in script + style and "\u2014" not in script + style
