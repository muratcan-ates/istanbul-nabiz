"""Nabız web app: the 12 MCP tools over plain HTTP, plus the single-page UI.

The web layer deliberately owns no data logic. Every endpoint is a thin wrapper around a
:class:`ibb_mcp.tools.Nabiz` method, so the browser sees exactly what an MCP client sees —
the same ``ToolResult`` envelope, the same provenance, the same Turkish notes. That is
what lets the UI promise a data age on every card without inventing one.
"""

from __future__ import annotations

__all__ = ["create_app"]


def __getattr__(name: str):  # pragma: no cover - convenience re-export
    """Import ``create_app`` lazily so importing the package costs no FastAPI import."""
    if name == "create_app":
        from nabiz.web.main import create_app

        return create_app
    raise AttributeError(name)
