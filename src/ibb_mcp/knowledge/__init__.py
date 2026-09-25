"""The local knowledge layer for reviewed public-service source pages."""

from __future__ import annotations

import os
import pathlib

from .answer import KnowledgeAnswer, answer
from .embed import Embedder, embedder_from_env
from .retrieve import Hit, search
from .store import KnowledgeStore


def open_from_env() -> tuple[KnowledgeStore | None, Embedder | None]:
    """Open an existing index and optional embedder; never reads a .env file."""
    configured = os.environ.get("NABIZ_KNOWLEDGE_DB", "data/knowledge/knowledge.db")
    path = pathlib.Path(configured).expanduser()
    if not path.is_absolute():
        path = pathlib.Path(__file__).resolve().parents[3] / path
    if not path.is_file():
        return None, None
    store = KnowledgeStore(path)
    return store, embedder_from_env(store=store)


__all__ = ["Hit", "KnowledgeAnswer", "KnowledgeStore", "answer", "open_from_env", "search"]
