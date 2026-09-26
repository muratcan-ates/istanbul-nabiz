"""Shared fixtures for the whole suite.

Three decisions here shape every other test file:

* ``src/`` is put on ``sys.path`` so the suite runs from a bare checkout, with or
  without an editable install. ``ibb_mcp`` is a namespace package, so no build step
  is required to import it.
* the ``ctx`` fixture hands sources an :class:`~ibb_mcp.http.PoliteClient` bolted to an
  ``httpx.MockTransport`` that *raises*. Reaching İBB from a test is not a slow test,
  it is a real-world side effect: the gateway starts returning 503 to every service
  after roughly fifteen rapid calls and the İETT SOAP service allows 100 requests per
  hour for the whole project. A stray live call must fail loudly, not silently pass.
  Behind that, ``_no_outbound_network`` guards *every* test, including the ones that
  never take ``ctx``: a socket connection or a DNS lookup for anything but loopback
  fails the test.
* GTFS comes from ``tests/fixtures/gtfs_mini``, never from ``data/reference/gtfs``. The
  full export is gitignored, so a test reading it passes on a laptop and fails in CI:
  three ``test_web.py`` tests did exactly that and failed 10 of CI's first 13 runs.
"""

from __future__ import annotations

import atexit
import json
import os
import pathlib
import shutil
import socket
import sys
import tempfile
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

# The console answers only a Host header naming this machine (nabiz.console.access); the
# test client's own name is "testserver". A test of the door itself builds its own access.
os.environ.setdefault("NABIZ_ALLOWED_HOSTS", "testserver")

TESTS_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
SRC_DIR = REPO_ROOT / "src"
FIXTURES_DIR = TESTS_DIR / "fixtures"
GTFS_MINI_DIR = FIXTURES_DIR / "gtfs_mini"

# The chat answers service questions from the local index once one is built (data/knowledge,
# gitignored). The suite sees no index unless a test seeds its own, so an owner's ingest run
# cannot change what the chat tests expect. The file named here never exists.
os.environ["NABIZ_KNOWLEDGE_DB"] = str(TESTS_DIR / "no-knowledge-index.db")
# The same for the İBB Open Data catalogue (data/reference/ibb_catalog.json, gitignored, written by
# the owner's `make capture-catalog`): a test that needs one writes its own and points here.
os.environ["NABIZ_IBB_CATALOG"] = str(TESTS_DIR / "no-ibb-catalog.json")

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


_gtfs_copy: pathlib.Path | None = None


def gtfs_fixture_dir() -> pathlib.Path:
    """A private, per-session copy of ``tests/fixtures/gtfs_mini``.

    A copy, not the committed folder: ``load_stop_sequences`` caches the sequences it
    builds as ``route_sequences.json.gz`` beside the tables, and a test run must not leave
    a new file in the repository. The copy keeps that write in a temporary directory while
    still exercising the real build from ``trips.csv`` and ``stop_times.txt``. A plain
    function rather than a fixture because ``offline_settings()`` is also called outside
    fixtures, for example inside ``test_collector.py``.
    """
    global _gtfs_copy
    if _gtfs_copy is None:
        scratch = pathlib.Path(tempfile.mkdtemp(prefix="nabiz-gtfs-"))
        atexit.register(shutil.rmtree, scratch, ignore_errors=True)
        _gtfs_copy = scratch / "gtfs"
        shutil.copytree(GTFS_MINI_DIR, _gtfs_copy, ignore=shutil.ignore_patterns("*.py", "*.md", "__pycache__"))
    return _gtfs_copy


def offline_settings() -> Settings:
    """Settings that never touch the network and read only committed test data."""
    return Settings(offline=True, fixtures_dir=FIXTURES_DIR, gtfs_dir=gtfs_fixture_dir())


def refuse_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(
        "A test tried to reach the network: "
        f"{request.method} {request.url}. Tests must use tests/fixtures, never İBB."
    )


#: Loopback is allowed: an ASGI app under test, or a local server a test starts itself,
#: is not İBB. Everything else is outbound.
_LOOPBACK_HOSTS = {"localhost", "::1", "0.0.0.0"}


def _is_loopback(host: object) -> bool:
    if isinstance(host, bytes):
        host = host.decode(errors="replace")
    return host is None or (isinstance(host, str) and (host in _LOOPBACK_HOSTS or host.startswith("127.")))


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Refuse any connection or DNS lookup that would leave this machine, in every test.

    ``refuse_network`` only covers clients built by the ``ctx`` fixture; a test that makes
    its own ``httpx`` client, or a code path that builds one internally, would reach İBB
    unnoticed. So the guard sits below every HTTP library, at the socket. Attempts are
    recorded and the test fails at teardown even if the code under test caught the error:
    the stale-on-error cache swallows upstream failures by design, and a guard that can be
    swallowed is not a guard. Subprocesses (git, node, the stdio MCP server) are not
    covered; the stdio server test starts its server with ``NABIZ_OFFLINE=1`` itself, and
    ``make test`` and CI set it for the whole run.

    The fixture's value is the attempt log, so ``tests/test_network_guard.py`` can watch it
    fire and then clear it.
    """
    attempts: list[str] = []
    real_connect, real_connect_ex, real_getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def outbound(sock: socket.socket, address: object) -> bool:
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            return False  # AF_UNIX: asyncio's self-pipe and the like
        return not _is_loopback(address[0] if isinstance(address, tuple) else address)

    def connect(sock: socket.socket, address: object) -> None:
        if outbound(sock, address):
            attempts.append(f"connect {address!r}")
            raise ConnectionRefusedError(f"tests may not reach the network: {address!r}")
        return real_connect(sock, address)

    def connect_ex(sock: socket.socket, address: object) -> int:
        if outbound(sock, address):
            attempts.append(f"connect {address!r}")
            raise ConnectionRefusedError(f"tests may not reach the network: {address!r}")
        return real_connect_ex(sock, address)

    def getaddrinfo(host: object, *args: Any, **kwargs: Any) -> Any:
        if not _is_loopback(host):
            attempts.append(f"DNS lookup {host!r}")
            raise socket.gaierror(socket.EAI_NONAME, f"tests may not resolve {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield attempts
    if attempts:
        pytest.fail("A test tried to reach the network (tests must use tests/fixtures, never İBB): " + "; ".join(attempts))


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
