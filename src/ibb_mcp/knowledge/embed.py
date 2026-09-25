# Ported from DOU-Synapse apps/api/app/modules/ingestion/embedding.py (github.com/muratcan-ates/DOU-Synapse @ 2cbe1ea, MIT, Copyright (c) 2026 Muratcan Ates)  # noqa: E501
"""Small async embedding protocol with deterministic and OpenAI-compatible providers."""

from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Sequence
from typing import Protocol


class Embedder(Protocol):
    """A provider that embeds documents and one query in the same vector space."""

    @property
    def name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


def unit_vector(vector: Sequence[float]) -> list[float]:
    """Return a finite unit vector; a zero vector stays zero."""
    norm = math.sqrt(sum(float(value) ** 2 for value in vector))
    return [float(value) / norm for value in vector] if norm else [0.0 for _ in vector]


class HashingEmbedder:
    """Dependency-free deterministic embedder for tests and fully offline demos."""

    def __init__(self, dimension: int = 96) -> None:
        self._dimension = dimension

    @property
    def name(self) -> str:
        return "hashing-test"

    @property
    def dimension(self) -> int:
        return self._dimension

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for word in text.casefold().split():
            digest = hashlib.sha256(word.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        return unit_vector(vector)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class OpenAIEmbedder:
    """OpenAI-compatible embedding REST client; Foundry Local support is unverified."""

    def __init__(self, base_url: str, api_key: str, model: str, *, store=None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.store = store
        self._dimension = 0

    @property
    def name(self) -> str:
        return self.model

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        import httpx

        missing: list[tuple[int, str, str]] = []
        result: list[list[float] | None] = [None] * len(texts)
        for index, text in enumerate(texts):
            key = hashlib.sha256(f"{self.model}|{text}".encode()).hexdigest()
            vector = self.store.get_embedding_cache(key) if self.store else None
            if vector is None:
                missing.append((index, text, key))
            else:
                result[index] = vector
                self._dimension = len(vector)
        async with httpx.AsyncClient(timeout=30.0) as client:
            for offset in range(0, len(missing), 64):
                batch = missing[offset : offset + 64]
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "input": [text for _, text, _ in batch]},
                )
                response.raise_for_status()
                payload = response.json()
                rows = sorted(payload["data"], key=lambda row: row["index"])
                for (index, _text, key), row in zip(batch, rows, strict=True):
                    vector = unit_vector(row["embedding"])
                    self._dimension = len(vector)
                    result[index] = vector
                    if self.store:
                        self.store.put_embedding_cache(key, vector)
        return [vector for vector in result if vector is not None]

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]


def embedder_from_env(*, store=None) -> Embedder | None:
    """Build an optional remote embedder from environment values without reading .env."""
    base_url = os.environ.get("NABIZ_LLM_BASE_URL", "").strip()
    api_key = os.environ.get("NABIZ_LLM_API_KEY", "").strip()
    if not base_url or not api_key:
        return None
    model = os.environ.get("NABIZ_EMBED_MODEL", "text-embedding-3-small").strip()
    return OpenAIEmbedder(base_url, api_key, model, store=store)
