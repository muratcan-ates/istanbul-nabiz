"""One chat turn's knowledge answer: the E78 model path when allowed, the E63 citation map always."""

from __future__ import annotations

from typing import Any

from ibb_mcp.knowledge.answer import KnowledgeAnswer
from ibb_mcp.knowledge.citation_map import citation_map
from nabiz.console.knowledge_generate import answer_with_model, build_generator


async def knowledge_turn(
    chat: Any, question: str, *, store: Any, embedder: Any, sensitive: bool, lang: str
) -> tuple[KnowledgeAnswer, str, dict[str, Any]]:
    """The answer, its author ("kural", "model", "yerel model") and the ``how`` additions.

    Offline or sensitive, no generator is built: the rule path answers exactly as before (E78 G3).
    """
    generator = None if chat.offline or sensitive else build_generator(chat.config, chat.guard, lang=lang)
    wrapped = await answer_with_model(question, store=store, embedder=embedder, sensitive=sensitive, generator=generator)
    cmap = citation_map(wrapped.answer, store=store)
    generation = wrapped.generation
    extra: dict[str, Any] = {
        "citation_map": cmap,
        "generation": {key: generation[key] for key in ("status", "reason", "label", "dropped")},
        "uncertainty": [f"kaynak çelişkisi: cümle {item['sentence']}" for item in cmap["conflicts"]],
    }
    return wrapped.answer, wrapped.author, extra
