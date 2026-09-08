"""Tests for the polite HTTP layer and the TTL cache.

Nothing here touches the network: every request goes through an ``httpx.MockTransport``.
That is not only for speed. ``api.ibb.gov.tr`` starts 503-ing every service after about
fifteen rapid calls and the İETT SOAP service allows the whole project 100 requests an
hour, so a test suite that called upstream would be an outage generator.

Backoff and the per-host spacing gate both go through ``asyncio.sleep`` inside
:mod:`ibb_mcp.http`; the ``fast_clock`` fixture replaces that one function so retry
behaviour can be asserted in milliseconds while still recording what the code *would*
have waited.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json

import httpx
import pytest

from ibb_mcp.cache import CacheEntry, TTLCache
from ibb_mcp.http import (
    HourlyBudget,
    PoliteClient,
    RateLimitExceeded,
    UpstreamUnavailable,
    extract_soap_json,
)

LINE_ACTION = "GetHatOtoKonum_json"
FLEET_ACTION = "GetFiloAracKonum_json"
SCHEDULE_ACTION = "GetPlanlananSeferSaati_json"


class _FastAsyncio:
    """Stand-in for the ``asyncio`` module as seen from :mod:`ibb_mcp.http`.

    ``sleep`` returns immediately and records the requested delay; every other
    attribute falls through to the real module.
    """

    def __init__(self) -> None:
        self.slept: list[float] = []

    async def sleep(self, seconds: float, *args: object, **kwargs: object) -> None:
        self.slept.append(seconds)
        await asyncio.sleep(0)

    def __getattr__(self, name: str) -> object:
        return getattr(asyncio, name)


@pytest.fixture
def fast_clock(monkeypatch: pytest.MonkeyPatch) -> _FastAsyncio:
    shim = _FastAsyncio()
    monkeypatch.setattr("ibb_mcp.http.asyncio", shim)
    return shim


def make_client(handler, **kwargs) -> PoliteClient:
    return PoliteClient(transport=httpx.MockTransport(handler), **kwargs)


def close_truncated_capture(xml_text: str, action: str) -> str:
    """Close a recorded ``.soap.xml`` capture that was cut off at ~4 KB.

    The fixtures in ``tests/fixtures`` hold the first few kilobytes of the real
    responses, so they stop mid-record and carry no closing tags. Trimming back to the
    last complete JSON object and closing the elements gives a well formed envelope
    made of genuine recorded bytes - Turkish characters, key order and all.
    """
    head, marker, tail = xml_text.partition(f"<{action}Result>")
    assert marker, f"{action}Result element not found in the capture"
    cut = tail.rfind("},{")
    assert cut > 0, "capture is too short to contain two complete records"
    return f"{head}{marker}{tail[:cut]}}}]</{action}Result></{action}Response></soap:Body></soap:Envelope>"


def soap_envelope(action: str, payload: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<soap:Body><{action}Response xmlns=\"http://tempuri.org/\">"
        f"<{action}Result>{payload}</{action}Result>"
        f"</{action}Response></soap:Body></soap:Envelope>"
    )


# =================================================================================
# extract_soap_json
# =================================================================================
@pytest.mark.parametrize(
    ("xml_name", "json_name", "action"),
    [
        ("iett_hat_500T.soap.xml", "iett_hat_500T", LINE_ACTION),
        ("iett_fleet.soap.xml", "iett_fleet", FLEET_ACTION),
        ("iett_planlanan.soap.xml", "iett_planlanan", SCHEDULE_ACTION),
    ],
)
def test_extract_soap_json_matches_the_recorded_payload(
    load_fixture, load_fixture_text, xml_name: str, json_name: str, action: str
) -> None:
    """Parsing the recorded SOAP body must reproduce the recorded JSON exactly."""
    parsed = extract_soap_json(close_truncated_capture(load_fixture_text(xml_name), action), action)
    reference = load_fixture(json_name)

    assert isinstance(parsed, list) and len(parsed) >= 10
    # The capture holds the first N records of the same response the JSON fixture came from.
    assert parsed == reference[: len(parsed)]


def test_extract_soap_json_on_the_real_500t_response(load_fixture_text) -> None:
    capture = close_truncated_capture(load_fixture_text("iett_hat_500T.soap.xml"), LINE_ACTION)
    records = extract_soap_json(capture, LINE_ACTION)
    assert records[0]["kapino"] == "C-338"
    assert records[0]["hatkodu"] == "500T"
    assert {"boylam", "enlem", "guzergahkodu", "son_konum_zamani", "yakinDurakKodu"} <= set(records[0])
    assert all(record["hatkodu"] == "500T" for record in records)


@pytest.mark.parametrize(
    ("xml_name", "action"),
    [
        ("iett_hat_500T.soap.xml", LINE_ACTION),
        ("iett_fleet.soap.xml", FLEET_ACTION),
        ("iett_planlanan.soap.xml", SCHEDULE_ACTION),
    ],
)
def test_extract_soap_json_rejects_a_truncated_response(load_fixture_text, xml_name: str, action: str) -> None:
    """A response cut off mid-record must fail loudly, never yield half a fleet.

    The recorded captures are themselves truncated, which makes them a free regression
    test for exactly the failure mode a flaky gateway produces.
    """
    with pytest.raises(UpstreamUnavailable):
        extract_soap_json(load_fixture_text(xml_name), action)


def test_extract_soap_json_unescapes_xml_entities() -> None:
    payload = "[{&quot;kapino&quot;:&quot;C-338&quot;,&quot;hatad&quot;:&quot;A &amp; B&quot;}]"
    assert extract_soap_json(soap_envelope(LINE_ACTION, payload), LINE_ACTION) == [
        {"kapino": "C-338", "hatad": "A & B"}
    ]


def test_extract_soap_json_returns_empty_list_for_an_empty_element() -> None:
    assert extract_soap_json(soap_envelope(LINE_ACTION, ""), LINE_ACTION) == []
    assert extract_soap_json(soap_envelope(LINE_ACTION, "   "), LINE_ACTION) == []


def test_extract_soap_json_raises_when_the_result_element_is_missing() -> None:
    xml = (
        '<?xml version="1.0"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Body><SomethingElse>42</SomethingElse></soap:Body></soap:Envelope>"
    )
    with pytest.raises(UpstreamUnavailable) as excinfo:
        extract_soap_json(xml, LINE_ACTION, source="iett")
    assert excinfo.value.source == "iett"
    assert "sonuç elemanı yok" in str(excinfo.value)


def test_extract_soap_json_surfaces_a_soap_fault() -> None:
    xml = (
        '<?xml version="1.0"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Body><soap:Fault><faultcode>soap:Server</faultcode>"
        "<faultstring>Server was unable to process request.</faultstring>"
        "</soap:Fault></soap:Body></soap:Envelope>"
    )
    with pytest.raises(UpstreamUnavailable, match="unable to process request"):
        extract_soap_json(xml, LINE_ACTION)


def test_extract_soap_json_raises_on_a_leaked_oracle_error() -> None:
    """İETT sometimes returns an Oracle error as the result payload, HTTP 200 and all."""
    payload = "ORA-12541: TNS:no listener"
    with pytest.raises(UpstreamUnavailable, match="ORA-"):
        extract_soap_json(soap_envelope(LINE_ACTION, payload), LINE_ACTION)


def test_extract_soap_json_raises_on_an_oracle_error_after_a_prefix() -> None:
    payload = "Hata olustu: ORA-01722: invalid number"
    with pytest.raises(UpstreamUnavailable, match="ORA-"):
        extract_soap_json(soap_envelope(FLEET_ACTION, payload), FLEET_ACTION)


def test_extract_soap_json_raises_on_undecodable_json() -> None:
    with pytest.raises(UpstreamUnavailable, match="JSON"):
        extract_soap_json(soap_envelope(LINE_ACTION, "[{not json"), LINE_ACTION)


# =================================================================================
# PoliteClient — retries
# =================================================================================
async def test_client_retries_a_503_then_succeeds(fast_clock: _FastAsyncio) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(200, json={"ok": True})

    async with make_client(handler) as client:
        payload = await client.get_json("https://api.ibb.gov.tr/ispark/Park", source="ispark")

    assert payload == {"ok": True}
    assert len(calls) == 2
    assert fast_clock.slept, "a retry must back off before trying again"


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_client_gives_up_after_max_attempts(fast_clock: _FastAsyncio, status: int) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, text="nope")

    async with make_client(handler, max_attempts=3) as client:
        with pytest.raises(UpstreamUnavailable) as excinfo:
            await client.get_json("https://api.ibb.gov.tr/ispark/Park", source="ispark")

    assert len(calls) == 3
    assert excinfo.value.status == status
    assert excinfo.value.source == "ispark"


async def test_client_does_not_retry_a_404(fast_clock: _FastAsyncio) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(404, text="not found")

    async with make_client(handler, max_attempts=3) as client:
        with pytest.raises(UpstreamUnavailable) as excinfo:
            await client.get_json("https://api.ibb.gov.tr/nope", source="ispark")

    assert len(calls) == 1, "a 404 is not going to fix itself; retrying only burns budget"
    assert excinfo.value.status == 404


async def test_client_retries_transport_errors_then_gives_up(fast_clock: _FastAsyncio) -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ConnectTimeout("connect timeout", request=request)

    async with make_client(handler, max_attempts=2) as client:
        with pytest.raises(UpstreamUnavailable) as excinfo:
            await client.get_json("https://api.ibb.gov.tr/ispark/Park", source="ispark")

    assert attempts["n"] == 2
    assert excinfo.value.status is None


async def test_client_backoff_grows_and_stays_capped(fast_clock: _FastAsyncio) -> None:
    """Backoff is 4 s, 8 s, 16 s with jitter, capped at 30 s.

    A neutral host is used so the per-host spacing gate (1 s here, 6 s for
    ``api.ibb.gov.tr``) does not blend into the recorded sleeps.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with make_client(handler, max_attempts=4) as client:
        with pytest.raises(UpstreamUnavailable):
            await client.get_json("https://mock.invalid/x", source="ispark")

    backoffs = [s for s in fast_clock.slept if s > 2.0]  # gate waits are 1 s
    assert len(backoffs) == 3  # one wait between each pair of attempts
    assert all(s <= 30.0 for s in backoffs)
    assert backoffs[0] < backoffs[1] < backoffs[2]  # jitter never inverts a whole step


async def test_client_spaces_out_requests_to_the_shared_gateway(fast_clock: _FastAsyncio) -> None:
    """Every İBB service sits behind one host, so the spacing is per host, not per endpoint."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    async with make_client(handler) as client:
        await client.get_json("https://api.ibb.gov.tr/ispark/Park", source="ispark")
        await client.get_json("https://api.ibb.gov.tr/MetroIstanbul/x", source="metro_status")

    assert fast_clock.slept, "the second call to the gateway must wait"
    assert max(fast_clock.slept) == pytest.approx(6.0, abs=0.5)


# =================================================================================
# PoliteClient — headers and payloads
# =================================================================================
async def test_get_json_sends_accept_json_when_asked(fast_clock: _FastAsyncio) -> None:
    """The traffic index endpoint answers XML unless this header is present."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[{"TrafficIndex": 60}])

    async with make_client(handler) as client:
        await client.get_json(
            "https://api.ibb.gov.tr/tkmservices/api/TrafficData/v1/TrafficIndexHistory/1/H",
            source="traffic",
            accept_json=True,
        )

    assert seen[0].headers["accept"] == "application/json"


async def test_get_json_omits_the_accept_header_when_not_asked(fast_clock: _FastAsyncio) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    async with make_client(handler) as client:
        await client.get_json("https://api.ibb.gov.tr/ispark/Park", source="ispark", accept_json=False)

    assert seen[0].headers.get("accept") != "application/json"


async def test_get_json_forwards_query_params_and_the_user_agent(fast_clock: _FastAsyncio) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[{"parkID": 3068}])

    async with make_client(handler) as client:
        await client.get_json("https://api.ibb.gov.tr/ispark/ParkDetay", source="ispark", params={"id": 3068})

    assert seen[0].url.params["id"] == "3068"
    assert "istanbul-nabiz" in seen[0].headers["user-agent"]


async def test_get_json_raises_when_the_body_is_not_json(fast_clock: _FastAsyncio) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<TrafficIndexHistory><TrafficIndex>60</TrafficIndex></TrafficIndexHistory>")

    async with make_client(handler) as client:
        with pytest.raises(UpstreamUnavailable, match="JSON değil"):
            await client.get_json("https://api.ibb.gov.tr/tkm", source="traffic")


async def test_post_soap_json_sends_the_envelope_and_parses_the_result(
    fast_clock: _FastAsyncio, load_fixture_text, load_fixture
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        capture = close_truncated_capture(load_fixture_text("iett_hat_500T.soap.xml"), LINE_ACTION)
        return httpx.Response(200, text=capture)

    async with make_client(handler) as client:
        records = await client.post_soap_json(
            "https://api.ibb.gov.tr/iett/FiloDurum/SeferGerceklesme.asmx",
            source="iett_line",
            action=LINE_ACTION,
            body_xml=f"<{LINE_ACTION} xmlns='http://tempuri.org/'><HatKodu>500T</HatKodu></{LINE_ACTION}>",
        )

    assert records == load_fixture("iett_hat_500T")[: len(records)]
    assert len(records) >= 10
    request = seen[0]
    assert request.method == "POST"
    assert request.headers["soapaction"] == f'"http://tempuri.org/{LINE_ACTION}"'
    assert request.headers["content-type"].startswith("text/xml")
    body = request.content.decode()
    assert "<soap:Envelope" in body and "<HatKodu>500T</HatKodu>" in body


# =================================================================================
# HourlyBudget
# =================================================================================
def test_hourly_budget_consumes_and_reports_remaining() -> None:
    budget = HourlyBudget("iett", limit=3)
    assert budget.remaining == 3
    budget.consume()
    assert budget.remaining == 2
    budget.consume()
    budget.consume()
    assert budget.remaining == 0


def test_hourly_budget_raises_at_the_limit() -> None:
    budget = HourlyBudget("iett", limit=2)
    budget.consume()
    budget.consume()
    with pytest.raises(RateLimitExceeded) as excinfo:
        budget.consume()
    assert excinfo.value.source == "iett"
    assert isinstance(excinfo.value, UpstreamUnavailable)  # callers can catch one type
    assert budget.remaining == 0


def test_hourly_budget_forgets_calls_outside_the_window() -> None:
    budget = HourlyBudget("iett", limit=1, window_seconds=0.0)
    budget.consume()
    assert budget.remaining == 1  # the window has already slid past
    budget.consume()


def test_client_defaults_to_the_documented_iett_budget() -> None:
    client = PoliteClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    assert client.budgets["iett"].limit == 80  # under İETT's documented 100/hour


async def test_client_stops_before_spending_an_exhausted_budget(fast_clock: _FastAsyncio) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text="<x/>")

    async with make_client(handler) as client:
        client.budgets["iett"] = HourlyBudget("iett", limit=1)
        await client.request("GET", "https://api.ibb.gov.tr/iett/x", source="iett_line", budget="iett")
        with pytest.raises(RateLimitExceeded):
            await client.request("GET", "https://api.ibb.gov.tr/iett/x", source="iett_line", budget="iett")

    assert len(calls) == 1, "the second call must never leave the process"


# =================================================================================
# TTLCache
# =================================================================================
async def test_cache_miss_then_hit() -> None:
    cache = TTLCache()
    calls = {"n": 0}

    async def loader() -> str:
        calls["n"] += 1
        return "value"

    first, first_entry = await cache.get_or_fetch("k", loader, source="ispark", ttl=60.0)
    second, second_entry = await cache.get_or_fetch("k", loader, source="ispark", ttl=60.0)

    assert (first, second) == ("value", "value")
    assert calls["n"] == 1
    assert first_entry is second_entry
    assert second_entry.fresh is True
    assert isinstance(second_entry, CacheEntry)
    assert second_entry.stored_at_utc.tzinfo is not None
    stats = cache.stats["ispark"]
    assert (stats.hits, stats.misses, stats.errors) == (1, 1, 0)


async def test_cache_refetches_once_the_entry_expires() -> None:
    cache = TTLCache()
    calls = {"n": 0}

    async def loader() -> int:
        calls["n"] += 1
        return calls["n"]

    first, _ = await cache.get_or_fetch("k", loader, source="traffic", ttl=0.0)
    second, entry = await cache.get_or_fetch("k", loader, source="traffic", ttl=0.0)

    assert (first, second) == (1, 2)
    assert calls["n"] == 2
    assert entry.fresh is False  # a zero TTL is stale the moment it is written
    assert cache.stats["traffic"].misses == 2


async def test_cache_uses_the_per_source_default_ttl() -> None:
    cache = TTLCache()
    assert cache.ttl_for("ispark") == 300.0
    assert cache.ttl_for("iett_line") == 60.0
    assert cache.ttl_for("unknown_source") == 300.0

    async def loader() -> str:
        return "v"

    _, entry = await cache.get_or_fetch("k", loader, source="iett_line")
    assert entry.ttl == 60.0


async def test_cache_is_single_flight_under_concurrency() -> None:
    """Fifty citizens asking the same question must produce one upstream request."""
    cache = TTLCache()
    calls = {"n": 0}

    async def loader() -> str:
        calls["n"] += 1
        await asyncio.sleep(0.02)  # long enough for every waiter to pile up on the lock
        return f"payload-{calls['n']}"

    results = await asyncio.gather(
        *[cache.get_or_fetch("ispark:list", loader, source="ispark", ttl=60.0) for _ in range(10)]
    )

    assert calls["n"] == 1, "single-flight broken: the İBB gateway would see 10 requests"
    assert {value for value, _ in results} == {"payload-1"}
    stats = cache.stats["ispark"]
    assert stats.misses == 1
    assert stats.hits == 9


async def test_cache_serves_stale_data_when_the_loader_fails() -> None:
    """A gateway wobble must degrade the answer, never fabricate one."""
    cache = TTLCache()

    async def good() -> str:
        return "last known good"

    async def bad() -> str:
        raise UpstreamUnavailable("İBB 503", source="ispark", status=503)

    await cache.get_or_fetch("k", good, source="ispark", ttl=0.0)
    value, entry = await cache.get_or_fetch("k", bad, source="ispark", ttl=0.0)

    assert value == "last known good"
    assert entry.fresh is False
    assert entry.age >= 0.0
    stats = cache.stats["ispark"]
    assert stats.stale_served == 1
    assert stats.errors == 1
    assert stats.last_error is not None and "UpstreamUnavailable" in stats.last_error


async def test_cache_raises_when_it_fails_with_nothing_cached() -> None:
    cache = TTLCache()

    async def bad() -> str:
        raise UpstreamUnavailable("İBB 503", source="ispark", status=503)

    with pytest.raises(UpstreamUnavailable):
        await cache.get_or_fetch("cold", bad, source="ispark")

    assert cache.stats["ispark"].errors == 1
    assert cache.stats["ispark"].stale_served == 0


async def test_cache_recovers_after_a_failure() -> None:
    cache = TTLCache()
    state = {"fail": False}

    async def loader() -> str:
        if state["fail"]:
            raise UpstreamUnavailable("İBB 503", source="ispark", status=503)
        return "fresh"

    await cache.get_or_fetch("k", loader, source="ispark", ttl=0.0)
    state["fail"] = True
    await cache.get_or_fetch("k", loader, source="ispark", ttl=0.0)
    assert cache.stats["ispark"].last_error is not None

    state["fail"] = False
    value, _ = await cache.get_or_fetch("k", loader, source="ispark", ttl=0.0)
    assert value == "fresh"
    assert cache.stats["ispark"].last_error is None
    assert cache.freshness()["ispark"]["healthy"] is True


async def test_cache_peek_and_invalidate() -> None:
    cache = TTLCache()

    async def loader() -> str:
        return "v"

    assert cache.peek("k") is None
    await cache.get_or_fetch("k", loader, source="ispark", ttl=60.0)
    assert cache.peek("k") is not None

    cache.invalidate("k")
    assert cache.peek("k") is None

    await cache.get_or_fetch("a", loader, source="ispark", ttl=60.0)
    await cache.get_or_fetch("b", loader, source="ispark", ttl=60.0)
    cache.invalidate()
    assert cache.peek("a") is None and cache.peek("b") is None


async def test_freshness_reports_one_row_per_source() -> None:
    cache = TTLCache()

    async def good() -> str:
        return "v"

    async def bad() -> str:
        raise UpstreamUnavailable("İBB 503", source="metro_status", status=503)

    await cache.get_or_fetch("ispark:list", good, source="ispark", ttl=60.0)
    await cache.get_or_fetch("metro:status", good, source="metro_status", ttl=0.0)
    await cache.get_or_fetch("metro:status", bad, source="metro_status", ttl=0.0)

    freshness = cache.freshness()
    assert set(freshness) == {"ispark", "metro_status"}

    ispark = freshness["ispark"]
    assert set(ispark) == {
        "last_success_utc", "age_seconds", "healthy", "hits", "misses", "stale_served", "errors", "last_error",
    }
    assert ispark["healthy"] is True
    assert ispark["last_error"] is None
    assert ispark["age_seconds"] is not None and ispark["age_seconds"] >= 0
    # The timestamp must be an ISO string the MCP tool can hand straight to the agent.
    assert dt.datetime.fromisoformat(ispark["last_success_utc"]).tzinfo is not None

    metro = freshness["metro_status"]
    assert metro["healthy"] is False
    assert metro["stale_served"] == 1 and metro["errors"] == 1
    assert json.dumps(freshness)  # the freshness tool serialises this as-is


def test_freshness_is_empty_before_anything_is_fetched() -> None:
    assert TTLCache().freshness() == {}


# =================================================================================
# The suite must never reach the network
# =================================================================================
async def test_the_no_network_transport_fails_loudly(ctx) -> None:
    with pytest.raises(AssertionError, match="tried to reach the network"):
        await ctx.client.get_json("https://api.ibb.gov.tr/ispark/Park", source="ispark")


def test_ctx_fixture_is_offline_and_points_at_the_fixtures(ctx, fixtures_dir) -> None:
    assert ctx.settings.offline is True
    assert ctx.settings.fixtures_dir == fixtures_dir
    assert ctx.load_fixture("ispark_park")[0]["parkID"] == 3068
    assert isinstance(ctx.cache, TTLCache)
