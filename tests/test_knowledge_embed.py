from __future__ import annotations

import asyncio

import httpx
import pytest

from ibb_mcp.knowledge.embed import HashingEmbedder, OpenAIEmbedder


def test_hashing_embedder_is_deterministic_unit_vector() -> None:
    embedder = HashingEmbedder(24)
    first = asyncio.run(embedder.embed_query("su aboneliği"))
    second = asyncio.run(embedder.embed_query("su aboneliği"))
    assert first == second
    assert abs(sum(value * value for value in first) - 1) < 1e-8


def test_openai_embedder_batches_and_caches(monkeypatch) -> None:
    class Store:
        values = {}

        def get_embedding_cache(self, key):
            return self.values.get(key)

        def put_embedding_cache(self, key, vector):
            self.values[key] = vector

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    calls = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, *, headers, json):
            calls.append((len(json["input"]), headers["Authorization"]))
            return Response({"data": [{"index": i, "embedding": [1.0, float(i + 1)]} for i in range(len(json["input"]))]})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: Client())
    store = Store()
    embedder = OpenAIEmbedder("https://model.invalid/v1", "secret", "test-model", store=store)
    texts = [f"text {i}" for i in range(70)]
    first = asyncio.run(embedder.embed_documents(texts))
    second = asyncio.run(embedder.embed_documents(texts))
    assert len(first) == len(second) == 70
    assert [call[0] for call in calls] == [64, 6]
    assert calls[0][1] == "Bearer secret"
    assert embedder.dimension == 2


def test_the_embedder_never_points_at_an_ibb_host(monkeypatch) -> None:
    """The guardrail exempts the embedding call as a model endpoint; this keeps that true at runtime."""
    from ibb_mcp.knowledge.embed import embedder_from_env, is_ibb_host

    gov = "ibb" + ".gov.tr"
    for url in (f"https://api.{gov}/v1", f"https://{gov}/v1", "https://iett.istanbul/v1", "not a url"):
        assert is_ibb_host(url), url
        with pytest.raises(ValueError):
            OpenAIEmbedder(url, "secret", "test-model")
    assert not is_ibb_host("https://model.invalid/v1")
    monkeypatch.setenv("NABIZ_LLM_BASE_URL", f"https://api.{gov}/v1")
    monkeypatch.setenv("NABIZ_LLM_API_KEY", "secret")
    assert embedder_from_env() is None
