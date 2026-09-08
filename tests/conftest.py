"""Shared fixtures for the whole suite.

Two decisions here shape every other test file:

* ``src/`` is put on ``sys.path`` so the suite runs from a bare checkout, with or
  without an editable install. ``ibb_mcp`` is a namespace package, so no build step
  is required to import it.
* the ``ctx`` fixture hands sources an :class:`~ibb_mcp.http.PoliteClient` bolted to an
  ``httpx.MockTransport`` that *raises*. Reaching İBB from a test is not a slow test,
  it is a real-world side effect: the gateway starts returning 503 to every service
  after roughly fifteen rapid calls and the İETT SOAP service allows 100 requests per
  hour for the whole project. A stray live call must fail loudly, not silently pass.
"""

from __future__ import annotations

import json
import pathlib
import sys
from collections.abc import Callable
from typing import Any

import httpx
import pytest

TESTS_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
SRC_DIR = REPO_ROOT / "src"
FIXTURES_DIR = TESTS_DIR / "fixtures"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ibb_mcp.cache import TTLCache  # noqa: E402  (import must follow the sys.path bootstrap)
from ibb_mcp.config import Settings  # noqa: E402
from ibb_mcp.http import PoliteClient  # noqa: E402
from ibb_mcp.sources.base import SourceContext  # noqa: E402


def read_fixture(name: str) -> Any:
    """Parse a recorded İBB response. ``name`` may omit the ``.json`` suffix."""
    filename = name if name.endswith(".json") else f"{name}.json"
    return json.loads((FIXTURES_DIR / filename).read_text(encoding="utf-8"))


def read_fixture_text(name: str) -> str:
    """Read a recorded response verbatim; used for the SOAP ``.xml`` captures."""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def offline_settings() -> Settings:
    """Settings that never touch the network and read from ``tests/fixtures``."""
    return Settings(offline=True, fixtures_dir=FIXTURES_DIR)


def refuse_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(
        "A test tried to reach the network: "
        f"{request.method} {request.url}. Tests must use tests/fixtures, never İBB."
    )


@pytest.fixture(scope="session")
def fixtures_dir() -> pathlib.Path:
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def load_fixture() -> Callable[[str], Any]:
    return read_fixture


@pytest.fixture(scope="session")
def load_fixture_text() -> Callable[[str], str]:
    return read_fixture_text


@pytest.fixture
def settings() -> Settings:
    return offline_settings()


@pytest.fixture
def no_network_transport() -> httpx.MockTransport:
    """A transport that turns any outbound request into a loud test failure."""
    return httpx.MockTransport(refuse_network)


@pytest.fixture
def cache() -> TTLCache:
    return TTLCache()


@pytest.fixture
def ctx(settings: Settings, cache: TTLCache, no_network_transport: httpx.MockTransport) -> SourceContext:
    """A SourceContext wired for offline tests.

    Deliberately a sync fixture so both sync and async tests can take it. The client is
    not closed: ``MockTransport`` owns no sockets, so there is nothing to release.
    """
    return SourceContext.create(
        client=PoliteClient(transport=no_network_transport),
        cache=cache,
        settings=settings,
    )
