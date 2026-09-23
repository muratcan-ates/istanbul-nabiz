"""Tests for the public edge of the MCP server: what one HTTP caller may do and spend.

Most of this file drives the real application ``ibb-mcp --transport http`` serves: the
SDK's streamable-HTTP app wrapped by :func:`ibb_mcp.server.build_http_app`, started through
the ASGI lifespan as uvicorn starts it, and spoken to with ``httpx.ASGITransport``. No
socket is opened, no İBB host is reachable (the façade's client refuses the network, as
everywhere in this suite), and nothing sleeps: the limiter's clock is injected where time
has to pass, and elsewhere the refill rate is set so low that none passes.

The rest pins the deployment contract the edge depends on: the path the Dockerfile's
HEALTHCHECK probes, the console script it runs, and the pyproject extras it installs.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import inspect
import json
import pathlib
import time
import tomllib
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from ibb_mcp import config as config_module
from ibb_mcp import server as server_module
from ibb_mcp.alerts.schema import AlertSubscription
from ibb_mcp.config import HardeningConfig, Settings, reference_path
from ibb_mcp.server import (
    DEFAULT_TOOL_COST,
    HEALTH_PATH,
    MAX_REQUEST_BYTES,
    REJECTED_MESSAGE,
    TOOL_COSTS,
    ApiKeyGate,
    ClientLimiter,
    TokenBucket,
    ToolBudget,
    build_http_app,
    build_server,
    client_address,
    client_identity,
    cost_for,
    extract_api_key,
)
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROTOCOL_VERSION = "2025-06-18"
MCP_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


class FakeClock:
    """A monotonic clock the test moves by hand."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeRequest:
    """Just the two things :func:`client_identity` reads off a Starlette request."""

    def __init__(self, host: str | None, headers: dict[str, str] | None = None) -> None:
        self.client = type("Client", (), {"host": host})() if host else None
        self.headers = headers or {}


# ======================================================================================
# 1. configuration
# ======================================================================================


def test_defaults_are_open_but_budgeted() -> None:
    config = HardeningConfig.from_env({})
    assert config.api_keys == ()
    assert config.cors_origins == ()
    assert config.trusted_proxy_hops == 0
    assert (config.burst, config.refill_per_minute, config.max_clients) == (30, 12.0, 1024)


def test_every_knob_is_read_from_the_environment() -> None:
    config = HardeningConfig.from_env(
        {
            "NABIZ_API_KEYS": " alpha , beta,,",
            "NABIZ_MCP_RATE_BURST": "40",
            "NABIZ_MCP_RATE_PER_MINUTE": "6.5",
            "NABIZ_MCP_MAX_CLIENTS": "64",
            "NABIZ_MCP_CORS_ORIGINS": "https://nabiz.example, https://ops.example",
            "NABIZ_MCP_TRUSTED_PROXY_HOPS": "1",
        }
    )
    assert config.api_keys == ("alpha", "beta")
    assert (config.burst, config.refill_per_minute, config.max_clients) == (40, 6.5, 64)
    assert config.cors_origins == ("https://nabiz.example", "https://ops.example")
    assert config.trusted_proxy_hops == 1


@pytest.mark.parametrize("raw", ["abc", "-3", "0", "nan", "inf", "2.5"])
def test_a_malformed_number_falls_back_to_its_default_instead_of_stopping_the_boot(
    raw: str, caplog: pytest.LogCaptureFixture
) -> None:
    config = HardeningConfig.from_env({"NABIZ_MCP_RATE_BURST": raw, "NABIZ_MCP_RATE_PER_MINUTE": raw})
    assert config.burst == HardeningConfig.burst
    if raw != "2.5":  # a fractional refill rate is legitimate
        assert config.refill_per_minute == HardeningConfig.refill_per_minute
    assert "NABIZ_MCP_RATE_BURST" in caplog.text


def test_zero_proxy_hops_is_a_valid_setting_not_a_typo() -> None:
    assert HardeningConfig.from_env({"NABIZ_MCP_TRUSTED_PROXY_HOPS": "0"}).trusted_proxy_hops == 0
    assert HardeningConfig.from_env({"NABIZ_MCP_TRUSTED_PROXY_HOPS": "-1"}).trusted_proxy_hops == 0


# ======================================================================================
# 2. the token bucket and the per-client table
# ======================================================================================


def test_bucket_refills_at_the_configured_rate_on_an_injected_clock() -> None:
    clock = FakeClock()
    bucket = TokenBucket(capacity=10, refill_per_second=0.2, clock=clock)

    assert bucket.consume(10) is True
    assert bucket.consume(1) is False
    clock.advance(5.0)  # 5 s x 0.2 tokens/s = 1 token
    assert bucket.consume(1) is True
    assert bucket.consume(1) is False
    clock.advance(1000.0)  # 200 tokens' worth of idling into a bucket that holds 10
    assert bucket.consume(10) is True
    assert bucket.consume(1) is False, "the bucket must not refill past its capacity"


def test_bucket_uses_a_monotonic_clock_by_default() -> None:
    """A wall clock would hand out free tokens whenever NTP stepped the host forward."""
    assert TokenBucket(capacity=1, refill_per_second=1.0).clock is time.monotonic


def test_a_clock_that_appears_to_run_backwards_never_removes_tokens() -> None:
    clock = FakeClock()
    bucket = TokenBucket(capacity=5, refill_per_second=1.0, clock=clock)
    bucket.consume(5)
    clock.advance(-60.0)
    assert bucket.tokens == 0.0
    assert bucket.consume(1) is False


def test_a_price_above_the_bucket_size_is_never_affordable_and_says_so() -> None:
    bucket = TokenBucket(capacity=4, refill_per_second=2.0, clock=FakeClock())
    assert bucket.retry_after(5) == float("inf")


def _limiter(clock: FakeClock, **overrides: Any) -> ClientLimiter:
    return ClientLimiter(HardeningConfig(**{"burst": 26, "refill_per_minute": 12.0, **overrides}), clock=clock)


def test_an_expensive_tool_drains_the_bucket_faster_than_a_cheap_one() -> None:
    clock = FakeClock()
    cheap, expensive = _limiter(clock), _limiter(clock)
    cheap_calls = expensive_calls = 0
    while cheap.check("addr:198.51.100.1", cost_for("city_freshness")).allowed:
        cheap_calls += 1
    while expensive.check("addr:198.51.100.1", cost_for("iett_next_arrivals")).allowed:
        expensive_calls += 1
    assert (cheap_calls, expensive_calls) == (26, 2)


def test_a_refused_call_says_how_long_to_wait() -> None:
    clock = FakeClock()
    limiter = _limiter(clock, burst=8)
    assert limiter.check("addr:198.51.100.1", 8).allowed is True

    decision = limiter.check("addr:198.51.100.1", 8)
    assert decision.allowed is False
    assert decision.retry_after_s == pytest.approx(40.0)  # 8 tokens at 12 a minute
    clock.advance(40.0)
    assert limiter.check("addr:198.51.100.1", 8).allowed is True


def test_clients_do_not_share_a_bucket() -> None:
    limiter = _limiter(FakeClock(), burst=4)
    assert limiter.check("addr:198.51.100.1", 4).allowed is True
    assert limiter.check("addr:198.51.100.1", 1).allowed is False
    assert limiter.check("addr:198.51.100.2", 4).allowed is True


def test_the_client_table_cannot_grow_without_bound() -> None:
    """An unbounded dict keyed by address is a memory-exhaustion bug in itself."""
    limiter = _limiter(FakeClock(), max_clients=8)
    for index in range(5000):
        limiter.check(f"addr:client-{index}", 1)
    assert limiter.tracked_clients == 8


def test_eviction_keeps_the_most_recently_seen_clients() -> None:
    limiter = _limiter(FakeClock(), burst=2, max_clients=3)
    for name in ("a", "b", "c"):
        limiter.check(f"addr:{name}", 2)
    limiter.check("addr:a", 0)  # touch 'a' so 'b' becomes the least recently used
    limiter.check("addr:d", 2)

    assert limiter.tracked_clients == 3
    assert limiter.check("addr:a", 1).allowed is False, "'a' was touched, so its drained bucket survived"
    assert limiter.check("addr:b", 2).allowed is True, "'b' was evicted and starts fresh"


# ======================================================================================
# 3. tool prices
# ======================================================================================


async def test_every_tool_the_server_exposes_has_a_declared_price(ctx: SourceContext) -> None:
    """Catches the drift where a new tool ships and is priced by accident, not by choice."""
    exposed = {tool.name for tool in await build_server(app=Nabiz(ctx), hardening=HardeningConfig()).list_tools()}
    assert exposed == set(TOOL_COSTS), (
        f"unpriced: {sorted(exposed - set(TOOL_COSTS))}; stale: {sorted(set(TOOL_COSTS) - exposed)}"
    )


def test_local_answers_are_cheaper_than_gateway_reads_which_are_cheaper_than_iett() -> None:
    """The ordering is the point of the table; the exact numbers can be retuned."""
    local = max(TOOL_COSTS[n] for n in ("places_resolve", "iett_stops_search", "line_reliability", "city_freshness"))
    gateway = min(TOOL_COSTS[n] for n in ("metro_status", "traffic_index", "air_quality_now", "ispark_find_parking"))
    iett = min(TOOL_COSTS[n] for n in ("iett_line_buses", "iett_next_arrivals", "plan_journey"))
    assert local < gateway < iett


def test_an_unknown_tool_pays_the_highest_price() -> None:
    assert cost_for("a_tool_added_next_week") == DEFAULT_TOOL_COST == max(TOOL_COSTS.values())
    assert cost_for(None) == DEFAULT_TOOL_COST


def test_the_default_burst_affords_every_tool() -> None:
    """A tool priced above the bucket could never be called; the server warns, this forbids it."""
    assert max(TOOL_COSTS.values()) <= HardeningConfig().burst


def test_an_unaffordable_price_is_warned_about_at_start(caplog: pytest.LogCaptureFixture) -> None:
    ToolBudget(HardeningConfig(burst=5))
    assert "iett_next_arrivals" in caplog.text and "can never be called" in caplog.text


# ======================================================================================
# 4. API keys and caller identity
# ======================================================================================


def test_the_server_is_open_when_no_key_is_configured() -> None:
    gate = ApiKeyGate(HardeningConfig.from_env({}).api_keys)
    assert gate.required is False
    assert gate.accepts(None) is True


def test_right_key_passes_and_near_misses_are_refused() -> None:
    gate = ApiKeyGate(["alpha-key", "beta-key"])
    assert gate.accepts("alpha-key") and gate.accepts("beta-key")
    for wrong in (None, "", "alpha-ke", "alpha-key ", "ALPHA-KEY"):
        assert gate.accepts(wrong) is False, wrong


def test_key_comparison_is_constant_time_and_never_stops_at_a_match() -> None:
    """A timing channel cannot be observed reliably from a test runner, so it is pinned structurally."""
    source = inspect.getsource(ApiKeyGate.accepts)
    assert "hmac.compare_digest" in source, "keys must never be compared with =="
    loop_body = source.split("for key in self._keys:", 1)[1]
    assert "break" not in loop_body and "return" not in loop_body.split("matched |=")[0]


def test_every_configured_key_is_compared_whichever_one_matched(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returning early on a match would leak how many keys the deployment holds."""
    calls: list[int] = []
    real = hmac.compare_digest

    def counting(a: Any, b: Any) -> bool:
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(server_module.hmac, "compare_digest", counting)
    gate = ApiKeyGate(["one", "two", "three", "four"])
    counts = []
    for presented in ("one", "four", "none-of-them"):
        calls.clear()
        gate.accepts(presented)
        counts.append(len(calls))
    assert counts == [4, 4, 4]


def test_a_non_ascii_key_is_refused_rather_than_crashing() -> None:
    """``compare_digest`` raises TypeError on non-ASCII str; the gate compares bytes."""
    assert ApiKeyGate(["secret"]).accepts("şifre") is False
    assert ApiKeyGate(["şifre"]).accepts("şifre") is True


def test_the_key_is_read_from_either_header_whatever_their_case() -> None:
    assert extract_api_key({"X-API-Key": "abc"}) == "abc"
    assert extract_api_key({"authorization": "Bearer abc"}) == "abc"
    assert extract_api_key({"Authorization": "bearer abc"}) == "abc"
    assert extract_api_key({"authorization": "Basic abc"}) is None
    assert extract_api_key({}) is None and extract_api_key(None) is None


def test_the_proxy_appended_address_is_used_and_the_forgeable_part_is_ignored() -> None:
    # One trusted hop (Container Apps ingress) appends the address it saw, last.
    assert client_address("10.0.0.9", "203.0.113.7", 1) == "203.0.113.7"
    assert client_address("10.0.0.9", "198.51.100.66, 203.0.113.7", 1) == "203.0.113.7"
    # With no trusted hop, a header anyone can send is not believed at all.
    assert client_address("10.0.0.9", "198.51.100.66", 0) == "10.0.0.9"
    # Fewer entries than trusted hops: the request did not come through our proxies.
    assert client_address("10.0.0.9", "203.0.113.7", 2) == "10.0.0.9"


def test_rotating_a_forged_forwarded_for_does_not_mint_new_buckets() -> None:
    config, gate = HardeningConfig(trusted_proxy_hops=1), ApiKeyGate()
    identities = {
        client_identity(FakeRequest("10.0.0.9", {"x-forwarded-for": f"192.0.2.{n}, 203.0.113.7"}), config, gate)
        for n in range(50)
    }
    assert identities == {"addr:203.0.113.7"}


def test_ipv6_callers_share_a_bucket_per_64_block() -> None:
    """One subscriber is handed a whole /64; keying by address would give them 2**64 buckets."""
    config, gate = HardeningConfig(), ApiKeyGate()
    first = client_identity(FakeRequest("2001:db8:1:2::1"), config, gate)
    second = client_identity(FakeRequest("2001:db8:1:2:ffff::9"), config, gate)
    other = client_identity(FakeRequest("2001:db8:1:3::1"), config, gate)
    assert first == second == "addr:2001:db8:1:2::/64"
    assert other != first
    assert client_identity(FakeRequest("::ffff:203.0.113.7"), config, gate) == "addr:203.0.113.7"


def test_ports_are_stripped_and_junk_shares_one_bucket() -> None:
    config, gate = HardeningConfig(trusted_proxy_hops=1), ApiKeyGate()
    assert client_identity(FakeRequest("10.0.0.9", {"x-forwarded-for": "203.0.113.7:51234"}), config, gate) == "addr:203.0.113.7"
    assert client_identity(FakeRequest("10.0.0.9", {"x-forwarded-for": "[2001:db8::1]:443"}), config, gate) == (
        "addr:2001:db8::/64"
    )
    junk = {client_identity(FakeRequest("10.0.0.9", {"x-forwarded-for": f"not-an-ip-{n}"}), config, gate) for n in range(9)}
    assert junk == {"addr:unparsed"}
    assert client_identity(FakeRequest(None), HardeningConfig(), gate) == "addr:unknown"


def test_a_key_is_an_identity_only_when_the_server_accepts_it() -> None:
    """Otherwise a caller could send a new made-up key with every request and never run dry."""
    open_server, locked_server = ApiKeyGate(), ApiKeyGate(["real-key"])
    config = HardeningConfig()
    made_up = {client_identity(FakeRequest("203.0.113.7", {"x-api-key": f"k{n}"}), config, open_server) for n in range(9)}
    assert made_up == {"addr:203.0.113.7"}

    keyed = client_identity(FakeRequest("203.0.113.7", {"x-api-key": "real-key"}), config, locked_server)
    assert keyed.startswith("key:") and "real-key" not in keyed
    # The key, not the address: one NAT can hide a whole campus.
    assert client_identity(FakeRequest("198.51.100.1", {"x-api-key": "real-key"}), config, locked_server) == keyed


async def test_the_limiter_remembers_callers_by_pseudonym_not_by_address(caplog: pytest.LogCaptureFixture) -> None:
    """docs/THREAT_MODEL.md §4: the bucket is keyed by a hash; an address is personal data."""
    budget = ToolBudget(HardeningConfig(burst=1, refill_per_minute=0.001))

    async def call_next(ctx: Any) -> dict[str, Any]:
        return {}

    ctx = type("Ctx", (), {"method": "tools/call", "params": {"name": "places_resolve"}, "request": FakeRequest("203.0.113.7")})()
    with caplog.at_level("INFO", logger="ibb_mcp.server"):
        await budget(ctx, call_next)
        refused = await budget(ctx, call_next)

    assert refused["isError"] is True
    remembered = list(budget.limiter._buckets)
    assert len(remembered) == 1 and "203.0.113" not in remembered[0]
    assert "rate limited" in caplog.text and "203.0.113" not in caplog.text


async def test_the_budget_ignores_stdio_and_everything_but_tool_calls() -> None:
    budget = ToolBudget(HardeningConfig(burst=1, refill_per_minute=0.001))
    passed: list[str] = []

    async def call_next(ctx: Any) -> dict[str, Any]:
        passed.append(ctx.method)
        return {}

    stdio = type("Ctx", (), {"method": "tools/call", "params": {"name": "iett_next_arrivals"}, "request": None})()
    listing = type("Ctx", (), {"method": "tools/list", "params": {}, "request": FakeRequest("203.0.113.7")})()
    for _ in range(3):
        await budget(stdio, call_next)
        await budget(listing, call_next)
    assert passed == ["tools/call", "tools/list"] * 3


# ======================================================================================
# 5. the HTTP application, end to end
# ======================================================================================


@contextlib.asynccontextmanager
async def running(app: Any) -> AsyncIterator[None]:
    """Drive the ASGI lifespan the way uvicorn does, so the SDK's session manager starts."""
    inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    outbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    await inbox.put({"type": "lifespan.startup"})
    task = asyncio.create_task(app({"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}, inbox.get, outbox.put))
    started = await asyncio.wait_for(outbox.get(), timeout=10)
    assert started["type"] == "lifespan.startup.complete", started
    try:
        yield
    finally:
        await inbox.put({"type": "lifespan.shutdown"})
        await asyncio.wait_for(outbox.get(), timeout=10)
        await asyncio.wait_for(task, timeout=10)


def http_client(app: Any, address: str = "203.0.113.7", headers: dict[str, str] | None = None) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=(address, 50000))
    return httpx.AsyncClient(transport=transport, base_url="http://nabiz.test", headers=headers or {})


def sse_result(response: httpx.Response) -> dict[str, Any]:
    """The JSON-RPC message inside a one-event SSE response (or a plain JSON one)."""
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    data = [line[len("data: ") :] for line in response.text.splitlines() if line.startswith("data: ")]
    assert data, response.text
    return json.loads(data[-1])


class McpSession:
    """The two messages a real client sends before its first tool call, then tool calls.

    The server runs stateless, so ``initialize`` returns no session id and every later
    request stands on its own; a client that got one would send it back, and this does too.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.headers: dict[str, str] = dict(MCP_HEADERS)
        self._ids = iter(range(1, 10_000))

    async def open(self) -> McpSession:
        response = await self.client.post(
            "/mcp",
            headers=self.headers,
            json={
                "jsonrpc": "2.0",
                "id": next(self._ids),
                "method": "initialize",
                "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
            },
        )
        assert response.status_code == 200, response.text
        self.headers["mcp-protocol-version"] = PROTOCOL_VERSION
        if "mcp-session-id" in response.headers:
            self.headers["mcp-session-id"] = response.headers["mcp-session-id"]
        notified = await self.client.post(
            "/mcp", headers=self.headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        assert notified.status_code == 202, notified.text
        return self

    async def call(self, name: str, arguments: dict[str, Any], *, via: httpx.AsyncClient | None = None) -> dict[str, Any]:
        response = await (via or self.client).post(
            "/mcp",
            headers=self.headers,
            json={
                "jsonrpc": "2.0",
                "id": next(self._ids),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
        )
        assert response.status_code == 200, response.text
        return sse_result(response)["result"]


def text_of(result: dict[str, Any]) -> str:
    return result["content"][0]["text"]


@pytest.fixture
def make_app(ctx: SourceContext):
    """The deployed application over the offline façade, with a given edge configuration."""

    def build(**overrides: Any) -> Any:
        hardening = HardeningConfig(**overrides)
        server = build_server(app=Nabiz(ctx), hardening=hardening)
        return build_http_app(server, hardening, host="0.0.0.0")

    return build


async def test_health_answers_without_a_key_and_without_reaching_ibb(make_app) -> None:
    app = make_app(api_keys=("real-key",))
    async with running(app), http_client(app) as client:
        response = await client.get(HEALTH_PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == server_module.VERSION
    assert body["tools"] == len(TOOL_COSTS)
    # The offline fixture set carries stops.csv and routes.csv (tests/fixtures/gtfs_mini),
    # and the committed tables are in data/reference/. Stop sequences are built lazily, on
    # the first arrival question, so either answer is honest here.
    reference = dict(body["reference"])
    assert isinstance(reference.pop("stop_sequences"), bool)
    assert reference == {"places": True, "gtfs": True, "occupancy_profile": True, "eta_profile": True, "line_reliability": True}
    assert body["request_budget_remaining"] == {"iett": 80}
    # The façade's client refuses the network, so a probe that called İBB would have failed.
    assert "last_error" not in json.dumps(body)


async def test_health_reports_missing_gtfs_instead_of_failing(ctx: SourceContext, tmp_path: pathlib.Path) -> None:
    settings = Settings(offline=True, fixtures_dir=ctx.settings.fixtures_dir, gtfs_dir=tmp_path / "absent")
    nabiz = Nabiz(SourceContext.create(client=ctx.client, cache=ctx.cache, settings=settings))
    body = await server_module.health_snapshot(build_server(app=nabiz, hardening=HardeningConfig()), nabiz)
    assert body["status"] == "ok"
    assert body["reference"]["gtfs"] is False and body["reference"]["stop_sequences"] is False


async def test_the_mcp_endpoint_refuses_a_missing_or_wrong_key_with_one_message(make_app) -> None:
    app = make_app(api_keys=("real-key",))
    async with running(app):
        async with http_client(app) as client:
            missing = await client.post("/mcp", headers=MCP_HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        async with http_client(app, headers={"x-api-key": "wrong"}) as client:
            wrong = await client.post("/mcp", headers=MCP_HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})

    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == wrong.json() == {"error": "unauthorized", "message": REJECTED_MESSAGE}
    assert missing.headers["www-authenticate"].startswith("Bearer")


@pytest.mark.parametrize("header", [{"x-api-key": "real-key"}, {"authorization": "Bearer real-key"}])
async def test_a_configured_key_opens_the_endpoint(make_app, header: dict[str, str]) -> None:
    app = make_app(api_keys=("real-key",))
    async with running(app), http_client(app, headers=header) as client:
        session = await McpSession(client).open()
        result = await session.call("places_resolve", {"query": "Taksim", "limit": 1})
    assert json.loads(text_of(result))["data"]["matches"][0]["name"].startswith("Taksim")


async def test_a_caller_that_spends_its_bucket_is_told_to_wait_and_others_are_not(make_app) -> None:
    # Three one-token calls, and a refill so slow that none arrives during the test.
    app = make_app(burst=3, refill_per_minute=0.001)
    async with running(app), http_client(app, "203.0.113.7") as first, http_client(app, "198.51.100.2") as second:
        session = await McpSession(first).open()
        answers = [await session.call("places_resolve", {"query": "Taksim"}) for _ in range(4)]
        # Another address: the bucket belongs to the caller, not to the server as a whole.
        other = await session.call("places_resolve", {"query": "Taksim"}, via=second)

    assert [answer.get("isError", False) for answer in answers] == [False, False, False, True]
    refusal = json.loads(text_of(answers[-1]))
    assert refusal["error"] == "rate_limited"
    assert refusal["retry_after_seconds"] >= 1
    assert "İstek sınırı aşıldı" in refusal["message"]
    assert other.get("isError", False) is False


async def test_a_flood_of_handshakes_leaves_nothing_behind_on_the_server(make_app) -> None:
    """``initialize`` is not a tool call and costs no tokens, so it must not cost server memory either.

    In the SDK's default stateful mode each one opens a session held for up to 30 idle
    minutes, and 10 000 of them lock every new client out. Stateless, none is opened.
    """
    app = make_app(burst=1, refill_per_minute=0.001)
    async with running(app), http_client(app) as client:
        handshakes = [await McpSession(client).open() for _ in range(50)]
        answer = await handshakes[-1].call("places_resolve", {"query": "Taksim"})
    assert all("mcp-session-id" not in session.headers for session in handshakes)
    assert answer.get("isError", False) is False, "fifty handshakes spent none of the one-token budget"


async def test_the_price_depends_on_the_tool(make_app) -> None:
    """A 13-token arrival estimate does not fit in a 10-token bucket; a 1-token lookup does."""
    app = make_app(burst=10, refill_per_minute=0.001)
    async with running(app), http_client(app) as client:
        session = await McpSession(client).open()
        arrival = await session.call("iett_next_arrivals", {"line_code": "500T", "stop": "Kartal"})
        lookup = await session.call("places_resolve", {"query": "Taksim"})

    assert arrival["isError"] is True and json.loads(text_of(arrival))["retry_after_seconds"] is None
    assert lookup.get("isError", False) is False


async def test_oversized_arguments_are_refused_by_the_advertised_schema(make_app) -> None:
    app = make_app()
    async with running(app), http_client(app) as client:
        session = await McpSession(client).open()
        tools = sse_result(
            await client.post("/mcp", headers=session.headers, json={"jsonrpc": "2.0", "id": 99, "method": "tools/list"})
        )["result"]["tools"]
        long_query = await session.call("iett_stops_search", {"query": "Kadıköy " * 40})
        many = await session.call("iett_stops_search", {"query": "Kadıköy", "limit": 5000})
        far = await session.call("air_quality_forecast", {"place": "Beşiktaş", "horizon_hours": 10**9})

    schemas = {tool["name"]: tool["inputSchema"]["properties"] for tool in tools}
    assert schemas["iett_stops_search"]["query"]["maxLength"] == server_module.MAX_NAME_CHARS
    assert schemas["iett_stops_search"]["limit"]["maximum"] == server_module.MAX_RESULTS
    assert schemas["iett_next_arrivals"]["line_code"]["maxLength"] == server_module.MAX_CODE_CHARS
    assert schemas["air_quality_forecast"]["horizon_hours"]["maximum"] == server_module.MAX_HORIZON_HOURS
    for refused in (long_query, many, far):
        assert refused["isError"] is True


async def test_a_loopback_bind_keeps_the_sdks_dns_rebinding_protection(ctx: SourceContext) -> None:
    """docs/THREAT_MODEL.md MCP-8, now that the app is built here rather than by ``server.run``."""
    hardening = HardeningConfig()
    app = build_http_app(build_server(app=Nabiz(ctx), hardening=hardening), hardening, host="127.0.0.1")
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
    async with running(app), http_client(app) as client:  # Host: nabiz.test, as a rebinding page would send
        rebound = await client.post("/mcp", headers=MCP_HEADERS, json=ping)
        local = await client.post("http://127.0.0.1:8000/mcp", headers=MCP_HEADERS, json=ping)
    assert rebound.status_code == 421, rebound.text
    assert local.status_code != 421


async def test_an_oversized_body_is_refused_before_it_is_parsed(make_app) -> None:
    app = make_app()
    async with running(app), http_client(app) as client:
        session = await McpSession(client).open()
        body = json.dumps({"jsonrpc": "2.0", "id": 5, "method": "ping", "params": {"pad": "x" * MAX_REQUEST_BYTES}})
        response = await client.post("/mcp", headers=session.headers, content=body)
    assert response.status_code == 413


def test_the_largest_legitimate_request_fits_well_inside_the_body_cap() -> None:
    """``check_alerts`` at its schema limits: 5 places, 20 rules, 10 park ids, muted keys for all."""
    from ibb_mcp.alerts.engine import MAX_PARK_IDS, MAX_PLACES, MAX_RULES

    label = "Kadıköy, Moda Caddesi ve çevresi, ev " + "x" * 40
    places = [{"key": f"yer-{n:02d}", "label": label, "lat": 40.99, "lon": 29.03} for n in range(MAX_PLACES)]
    rules = [
        {
            "kind": "parking_filling",
            "park_ids": list(range(1000, 1000 + MAX_PARK_IDS)),
            "threshold_pct": 90,
            "cooldown_seconds": 1800,
        }
    ] * (MAX_RULES // 2) + [{"kind": "metro_disruption", "lines": ["M1A", "M2", "M4", "M5", "Marmaray"]}] * (MAX_RULES // 2)
    muted = [f"parking:{','.join(str(i) for i in range(1000, 1010))}:ge90:high"] * MAX_RULES
    subscription = {"places": places, "rules": rules, "muted_keys": muted}
    AlertSubscription.model_validate(subscription)  # legitimate: the advertised schema accepts it
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "check_alerts", "arguments": {"subscription": subscription}},
    }
    size = len(json.dumps(request, ensure_ascii=False).encode("utf-8"))
    assert size < MAX_REQUEST_BYTES / 4, size  # 4 559 bytes when this was written


def test_the_schema_bounds_every_string_so_even_its_worst_case_fits_the_body_cap() -> None:
    """Every length limit in the alert schema at once, with multi-byte Turkish text.

    The schema's lengths exist so the body cap is the second fence, not the only one: a
    request the schema accepts must never be one the transport then refuses as too large.
    """
    import pydantic

    from ibb_mcp.alerts import schema
    from ibb_mcp.alerts.engine import MAX_PARK_IDS, MAX_PLACES, MAX_RULES

    places = [
        {"key": "ş" * schema.MAX_KEY_CHARS, "label": "İ" * schema.MAX_LABEL_CHARS, "lat": 40.99, "lon": 29.03}
    ] * MAX_PLACES
    rules = [
        {"kind": "metro_disruption", "lines": ["Ğ" * schema.MAX_LINE_CHARS] * schema.MAX_LINES_PER_RULE, "cooldown_seconds": 1800}
    ] * (MAX_RULES // 2) + [
        {"kind": "parking_filling", "park_ids": list(range(10**8, 10**8 + MAX_PARK_IDS)), "threshold_pct": 90.5}
    ] * (MAX_RULES // 2)
    muted = ["ç" * schema.MAX_DEDUPE_KEY_CHARS] * schema.MAX_MUTED_KEYS
    subscription = {"places": places, "rules": rules, "muted_keys": muted}
    AlertSubscription.model_validate(subscription)
    params = {"name": "check_alerts", "arguments": {"subscription": subscription}}
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}
    assert len(json.dumps(request, ensure_ascii=False).encode("utf-8")) < MAX_REQUEST_BYTES

    too_long = {"places": [{**places[0], "key": "k" * (schema.MAX_KEY_CHARS + 1)}], "rules": rules[:1]}
    with pytest.raises(pydantic.ValidationError):
        AlertSubscription.model_validate(too_long)


async def test_cors_is_closed_and_silent_by_default(make_app) -> None:
    app = make_app()
    async with running(app), http_client(app) as client:
        preflight = await client.options(
            "/mcp", headers={"origin": "https://nabiz.example", "access-control-request-method": "POST"}
        )
        health = await client.get(HEALTH_PATH, headers={"origin": "https://nabiz.example"})
    assert "access-control-allow-origin" not in preflight.headers
    assert "access-control-allow-origin" not in health.headers


async def test_a_configured_origin_may_call_and_read_the_session_id(make_app) -> None:
    app = make_app(cors_origins=("https://nabiz.example",), api_keys=("real-key",))
    async with running(app), http_client(app) as client:
        preflight = await client.options(
            "/mcp",
            headers={
                "origin": "https://nabiz.example",
                "access-control-request-method": "POST",
                "access-control-request-headers": "content-type, x-api-key, mcp-session-id",
            },
        )
        foreign = await client.options(
            "/mcp", headers={"origin": "https://evil.example", "access-control-request-method": "POST"}
        )
        # Even a refusal must be readable by the allowed page, or it cannot tell the user why.
        refused = await client.post("/mcp", headers={**MCP_HEADERS, "origin": "https://nabiz.example"}, json={})

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://nabiz.example"
    assert "x-api-key" in preflight.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in preflight.headers
    assert "access-control-allow-origin" not in foreign.headers
    assert refused.status_code == 401
    assert refused.headers["access-control-allow-origin"] == "https://nabiz.example"
    assert "mcp-session-id" in refused.headers["access-control-expose-headers"]


# ======================================================================================
# 6. errors that name a gap, not a stack trace
# ======================================================================================


async def test_missing_gtfs_is_a_named_gap_that_does_not_leak_the_path(ctx: SourceContext, tmp_path: pathlib.Path) -> None:
    absent = tmp_path / "private-home-dir" / "gtfs"
    settings = Settings(offline=True, fixtures_dir=ctx.settings.fixtures_dir, gtfs_dir=absent)
    nabiz = Nabiz(SourceContext.create(client=ctx.client, cache=ctx.cache, settings=settings))
    result = await build_server(app=nabiz, hardening=HardeningConfig()).call_tool("iett_stops_search", {"query": "Kadıköy"})

    payload = json.loads(result.content[0].text)
    assert payload["error"] == "reference_data_missing"
    assert "GTFS" in payload["message"]
    assert "private-home-dir" not in result.content[0].text


async def test_a_tool_call_is_traced_by_name_and_outcome_never_by_argument(ctx: SourceContext) -> None:
    """The span the wrapper adds: what the SDK's own ``tools/call`` span cannot know."""
    from telemetry_recording import RecordingProvider

    from ibb_mcp import telemetry

    provider = RecordingProvider()
    telemetry.install_tracer_provider(provider)
    try:
        server = build_server(app=Nabiz(ctx), hardening=HardeningConfig())
        await server.call_tool("places_resolve", {"query": "Kadıköy"})
        failed = await server.call_tool("air_quality_now", {"place": "zzz-boyle-bir-yer-yok"})
    finally:
        telemetry.install_tracer_provider(None)

    ok, refused = provider.tracer.named("nabiz.tool")
    assert set(ok.attributes) == {"nabiz.tool.name", "nabiz.tool.ok", "nabiz.tool.cached", "nabiz.tool.data_age_s"}
    assert ok.attributes["nabiz.tool.name"] == "places_resolve" and ok.attributes["nabiz.tool.ok"] is True
    assert refused.attributes == {
        "nabiz.tool.name": "air_quality_now",
        "nabiz.tool.ok": False,
        "nabiz.tool.error_kind": "ValueError",
    }
    assert json.loads(failed.content[0].text)["error"] == "bad_request"
    assert "Kadıköy" not in provider.tracer.every_value()


# ======================================================================================
# 7. the deployment contract
# ======================================================================================


def pyproject() -> dict[str, Any]:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_dockerfile_probes_the_path_the_server_serves() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert f"http://127.0.0.1:8000{HEALTH_PATH}" in dockerfile
    assert '"--port", "8000"' in dockerfile


def test_the_console_scripts_the_container_and_the_editor_run_exist() -> None:
    scripts = pyproject()["project"]["scripts"]
    assert scripts["ibb-mcp"] == "ibb_mcp.server:main"
    assert 'CMD ["ibb-mcp"' in (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    editor = json.loads((REPO_ROOT / ".vscode" / "mcp.json").read_text(encoding="utf-8"))["servers"]["istanbul-nabiz"]
    assert editor["command"].endswith("/.venv/bin/ibb-mcp")


def test_the_mcp_sdk_is_pinned_to_the_major_version_the_code_is_written_for() -> None:
    """``mcp.server.mcpserver`` exists only in 2.x; a 1.x install would fail at import."""
    dependencies = pyproject()["project"]["dependencies"]
    assert any(dep.replace(" ", "").startswith("mcp>=2") and "<3" in dep for dep in dependencies), dependencies


def test_the_job_extra_carries_every_sdk_the_image_imports_at_build_time() -> None:
    extras = pyproject()["project"]["optional-dependencies"]
    job = " ".join(extras["job"])
    for distribution in ("azure-identity", "azure-storage-blob", "azure-kusto-data", "azure-kusto-ingest"):
        assert distribution in job
    assert any(dep.startswith("azure-monitor-opentelemetry") for dep in extras["telemetry"])


def test_the_wheel_carries_the_reference_files_the_tools_read() -> None:
    project = pyproject()
    assert "Private :: Do Not Upload" in project["project"]["classifiers"], "nothing is released yet; see pyproject.toml"
    included = project["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    for source, target in included.items():
        assert (REPO_ROOT / source).is_file(), source
        assert target == f"ibb_mcp/data/{pathlib.PurePosixPath(source).name}"


def test_every_packaged_table_is_read_through_reference_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ETA profile and the reliability table resolve like places.csv does, so an installed
    wheel (the container image) reads its packaged copies instead of a checkout path that does
    not exist there. They used to hard-code the checkout, and /healthz reported both missing."""
    from ibb_mcp import eta_profile, reliability

    monkeypatch.delenv("NABIZ_ETA_PROFILE", raising=False)
    monkeypatch.delenv("NABIZ_RELIABILITY_TABLE", raising=False)
    assert eta_profile.profile_path() == reference_path(eta_profile.PROFILE_FILENAME)
    assert reliability.table_path() == reference_path("line_reliability.json")


def test_reference_files_come_from_the_checkout_first_and_the_wheel_otherwise(tmp_path: pathlib.Path) -> None:
    checkout, package = tmp_path / "checkout", tmp_path / "site-packages" / "ibb_mcp" / "data"
    package.mkdir(parents=True)
    (package / "places.csv").write_text("name,lat,lon\n", encoding="utf-8")

    assert reference_path("places.csv", checkout_root=checkout, package_dir=package) == package / "places.csv"
    (checkout / "data" / "reference").mkdir(parents=True)
    (checkout / "data" / "reference" / "places.csv").write_text("name,lat,lon\n", encoding="utf-8")
    assert reference_path("places.csv", checkout_root=checkout, package_dir=package) == (
        checkout / "data" / "reference" / "places.csv"
    )
    # Neither exists: the checkout path, so the "not found" log names where it was expected.
    assert reference_path("absent.csv", checkout_root=checkout, package_dir=package) == (
        checkout / "data" / "reference" / "absent.csv"
    )
    assert config_module.Settings().places_csv == REPO_ROOT / "data" / "reference" / "places.csv"
