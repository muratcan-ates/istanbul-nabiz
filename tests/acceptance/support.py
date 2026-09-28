"""What the acceptance tests share: one offline app, the chat stream, and whether a P00 group is wired yet.

A test for an endpoint the base does not have yet is skipped with the group that brings it
(``after("G2", "/api/photo-reports", "POST")``) and runs by itself once that group merges: nothing
here needs editing when the route appears. G1 lands on ``/api/chat``, which exists already, so its
switch is whether any product module imports the correction slots (:func:`imported_by_product`).

Everything is offline: the İBB tools read ``tests/fixtures`` through a client that refuses the network,
and a test that wants a model scripts one with :class:`test_console_chat.FakeModel`.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import offline_settings, refuse_network
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Mount

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console.access import OperatorAccess
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard

ROOT = Path(__file__).resolve().parents[2]
PRODUCT_SRC = ROOT / "src" / "nabiz"
OPERATOR_TOKEN = "<acceptance-operator-token>"
OPERATOR = {"X-Nabiz-Operator": OPERATOR_TOKEN}
BASE_URL = "http://127.0.0.1:8090"
CLOUD = llm.LlmConfig(base_url="http://model.invalid/v1", model="fake-model", provider="openai_compatible")
#: What an offline citation may call itself: a recorded fixture, a timetable, never "live".
OFFLINE_MODES = frozenset({"recorded", "schedule", "unknown"})
G1_MODULE = "nabiz.agent.context_slots"


# ---- is a route (or a P00 group) there yet ----------------------------------------------------------


def _param_free(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path)


def _routes(routes: Sequence[Any]) -> Iterator[Any]:
    """Every endpoint route; FastAPI 0.14x keeps an included router whole, so open it. The static
    mount matches every path and is not an endpoint."""
    for route in routes:
        nested = getattr(route, "effective_route_contexts", None)
        if nested is not None:
            yield from nested()
        elif isinstance(route, Mount):
            continue
        elif getattr(route, "routes", None) is not None:
            yield from _routes(route.routes)
        else:
            yield route


def route_exists(app: FastAPI, path: str, method: str | None = None) -> bool:
    """Does ``app`` serve ``path`` (parameter names ignored), for ``method`` when given?"""
    wanted = _param_free(path)
    for route in _routes(app.routes):
        if _param_free(str(getattr(route, "path", ""))) != wanted:
            continue
        if method is None or method.upper() in (getattr(route, "methods", None) or set()):
            return True
    return False


def _names_module(node: ast.AST, module: str) -> bool:
    parent, _, leaf = module.rpartition(".")
    if isinstance(node, ast.Import):
        return any(alias.name == module for alias in node.names)
    if not isinstance(node, ast.ImportFrom):
        return False
    if node.level == 0:
        return node.module == module or (node.module == parent and any(alias.name == leaf for alias in node.names))
    return node.module == leaf or (node.module is None and any(alias.name == leaf for alias in node.names))


def imported_by_product(module: str) -> bool:
    """Does any module under ``src/nabiz`` other than ``module`` itself import it?"""
    own = PRODUCT_SRC.parent / (module.replace(".", "/") + ".py")
    for path in sorted(PRODUCT_SRC.rglob("*.py")):
        if path == own:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(_names_module(node, module) for node in ast.walk(tree)):
            return True
    return False


def offline_nabiz() -> Nabiz:
    return Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)), cache=TTLCache(), settings=offline_settings()
        )
    )


def build_app(nabiz: Nabiz | None = None, *, config: llm.LlmConfig | None = None, guard: SpendGuard | None = None) -> FastAPI:
    """The product app as production builds it, with a known operator token and no model unless one is given."""
    return build_console_app(
        settings=offline_settings(),
        nabiz=nabiz,
        llm_config=config or llm.LlmConfig(),
        guard=guard or SpendGuard(BudgetConfig(state_path=None)),
        access=OperatorAccess(token=OPERATOR_TOKEN),
    )


#: Built once, never started: only its route table is read.
PROBE_APP = build_app()


def wired(path: str, method: str = "GET") -> bool:
    return route_exists(PROBE_APP, path, method)


def after(group: str, path: str, method: str = "GET") -> pytest.MarkDecorator:
    """Skip until the P00 group that brings ``method path`` is merged; then the test runs by itself."""
    return pytest.mark.skipif(not wired(path, method), reason=f"P00 {group} bağlanınca açılır ({method} {path} tabanda yok)")


AFTER_G1 = pytest.mark.skipif(
    not imported_by_product(G1_MODULE),
    reason=f"P00 G1 bağlanınca açılır ({G1_MODULE} sohbete bağlı değil)",
)


# ---- the chat stream ---------------------------------------------------------------------------------


def stream_events(text: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in text.strip().split("\n\n"):
        head, body = block.split("\n", 1)
        assert head.startswith("event: ") and body.startswith("data: "), block
        out.append((head.removeprefix("event: "), json.loads(body.removeprefix("data: "))))
    return out


def chat(
    client: TestClient,
    message: str,
    *,
    history: Sequence[str] = (),
    needs: Sequence[str] = (),
    headers: dict[str, str] | None = None,
) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, Any]]:
    """One turn; ``history`` is the person's own earlier questions, oldest first."""
    body = {"message": message, "needs": list(needs), "history": [{"role": "user", "content": text} for text in history]}
    response = client.post("/api/chat", json=body, headers=headers or {})
    assert response.status_code == 200, response.text
    stream = stream_events(response.text)
    assert stream[-1][0] == "final" and [kind for kind, _ in stream].count("final") == 1
    return stream, stream[-1][1]


def tools_started(stream: Sequence[tuple[str, dict[str, Any]]]) -> list[str]:
    return [data["name"] for kind, data in stream if kind == "tool" and data.get("status") == "start"]


def assert_offline_citations(final: dict[str, Any]) -> None:
    """Every citation names its source and age, and none calls a recorded fixture live (criterion 4)."""
    assert final["citations"], "an answer from a tool cites it"
    for cited in final["citations"]:
        assert cited["mode"] in OFFLINE_MODES, cited
        assert cited["source"] and "age_s" in cited


def sign_in(client: TestClient, email: str) -> dict[str, str]:
    """An example account (no real İBB link); returns the header that carries its token."""
    response = client.post("/api/account/signin", json={"provider": "google", "email": email, "consent": True})
    assert response.status_code == 200, response.text
    return {"X-Nabiz-Account": response.json()["token"]}
