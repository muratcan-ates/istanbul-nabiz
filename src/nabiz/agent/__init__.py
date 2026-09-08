"""The Nabız city agent: tool loop, model switch and numeric-faithfulness check.

``NabizAgent`` answers a citizen's question over the same twelve tools the ``ibb-mcp``
server exposes, and refuses to return a number that no tool produced. It runs with Azure
OpenAI, with a Foundry Local model on a laptop, or — when there is no model quota at all —
in a deterministic keyword-routed mode. See :mod:`nabiz.agent.agent`.
"""

from __future__ import annotations

from nabiz.agent.agent import (
    AgentAnswer,
    NabizAgent,
    ToolCallRecord,
    build_tool_schemas,
    detect_language,
)
from nabiz.agent.faithfulness import (
    CheckedNumber,
    FaithfulnessReport,
    check_faithfulness,
    extract_numbers,
)
from nabiz.agent.llm import LlmConfig, LlmError, LlmUnavailable, available, chat

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
