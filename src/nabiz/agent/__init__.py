"""The Nabız city agent: tool loop, model switch and numeric-faithfulness check.

``NabizAgent`` answers a citizen's question over the tools the ``ibb-mcp`` server exposes
(all but ``check_alerts``, which needs a subscription the web agent does not hold) and
refuses to return a number that no tool produced. It runs with Azure OpenAI, with a
Foundry Local model on a laptop, or — when there is no model quota at all — in a
deterministic keyword-routed mode. See :mod:`nabiz.agent.agent`.

The names below are resolved on first use (PEP 562) rather than imported here. The agent
imports :mod:`ibb_mcp.http`, and :mod:`ibb_mcp.http` imports
:mod:`nabiz.agent.telemetry`; an eager package would turn that into an import cycle
whenever ``ibb_mcp`` is imported first, which is every MCP server start.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - for type checkers and readers only
    from nabiz.agent.agent import AgentAnswer, NabizAgent, ToolCallRecord, build_tool_schemas, detect_language
    from nabiz.agent.faithfulness import CheckedNumber, FaithfulnessReport, check_faithfulness, extract_numbers
    from nabiz.agent.llm import LlmConfig, LlmError, LlmUnavailable, available, chat

#: Public name -> the submodule that defines it.
_EXPORTS: dict[str, str] = {
    "AgentAnswer": "nabiz.agent.agent",
    "NabizAgent": "nabiz.agent.agent",
    "ToolCallRecord": "nabiz.agent.agent",
    "build_tool_schemas": "nabiz.agent.agent",
    "detect_language": "nabiz.agent.agent",
    "CheckedNumber": "nabiz.agent.faithfulness",
    "FaithfulnessReport": "nabiz.agent.faithfulness",
    "check_faithfulness": "nabiz.agent.faithfulness",
    "extract_numbers": "nabiz.agent.faithfulness",
    "LlmConfig": "nabiz.agent.llm",
    "LlmError": "nabiz.agent.llm",
    "LlmUnavailable": "nabiz.agent.llm",
    "available": "nabiz.agent.llm",
    "chat": "nabiz.agent.llm",
}

__all__ = [
    "AgentAnswer",
    "CheckedNumber",
    "FaithfulnessReport",
    "LlmConfig",
    "LlmError",
    "LlmUnavailable",
    "NabizAgent",
    "ToolCallRecord",
    "available",
    "build_tool_schemas",
    "chat",
    "check_faithfulness",
    "detect_language",
    "extract_numbers",
]


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        # AttributeError, not ImportError: `from nabiz.agent import llm` asks for the
        # attribute first and falls back to importing the submodule only on this error.
        raise AttributeError(f"module 'nabiz.agent' has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value  # resolve once; later lookups are plain attribute reads
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORTS})
