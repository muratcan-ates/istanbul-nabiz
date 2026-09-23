"""Tests for the tracing shim and for what it is allowed to say about a request.

Two things are proved here, and they pull in opposite directions.

**Tracing is never load-bearing.** The shim must import and every instrumented path must
still answer when OpenTelemetry is absent, when nothing is configured, and when the Azure
exporter is missing or refuses to start. The absent case runs in a subprocess with the
import blocked, so it cannot leave a half-imported module behind for the tests after it.

**A trace never carries personal data.** Application Insights is a server-side store, so
a span attribute is under the same rule as the lake (docs/NABIZ.md §1.3): no number plate,
nothing the user typed, no coordinate derived from one. The tests assert it at every call
site where the temptation is real — an upstream URL, an agent turn, a tool whose argument
*is* the user's words, and the exception path (the MCP server's own tool span is asserted in
tests/test_server_security.py), because this codebase's error messages
quote the input back ("Bilinmeyen yer: …").

No SDK, exporter or key is needed: spans are captured by a small in-memory tracer provider
defined below, the Azure distro is a stand-in module, the HTTP tests run on
``httpx.MockTransport`` and the agent runs its deterministic no-model path over
``tests/fixtures``.
"""

from __future__ import annotations

import inspect
import logging
import os
import pathlib
import re
import subprocess
import sys
import types
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from telemetry_recording import RecordingProvider, RecordingTracer

from ibb_mcp.http import PoliteClient, UpstreamUnavailable
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm, telemetry
from nabiz.agent.agent import NabizAgent

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Stands in for anything a person typed. A place name, because that is the value most
#: likely to reach a span by accident: it arrives as an argument, it can end up in a URL,
#: and it is quoted back in error messages.
TYPED_BY_THE_USER = "Kadıköy"

#: Shaped like an Application Insights connection string, deliberately not like a real key:
#: the no-secrets guardrail flags anything GUID-shaped after InstrumentationKey=.
FAKE_CONNECTION = "InstrumentationKey=not-a-key;IngestionEndpoint=https://ingest.invalid/"


@pytest.fixture(autouse=True)
def isolated_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep each test's configuration to itself: setup_telemetry writes module globals."""
    monkeypatch.setattr(telemetry, "_provider", None)
    monkeypatch.setattr(telemetry, "_tracer", None)
    monkeypatch.setattr(telemetry, "_configured", False)
    for name in ("APPLICATIONINSIGHTS_CONNECTION_STRING", "APPLICATIONINSIGHTS_AUTHENTICATION_STRING", "NABIZ_TRACE_CONSOLE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def spans() -> Iterator[RecordingTracer]:
    provider = RecordingProvider()
    telemetry.install_tracer_provider(provider)
    yield provider.tracer
    telemetry.install_tracer_provider(None)


def json_ok(payload: Any) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json=payload))


def run_python(code: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src"), "NABIZ_OFFLINE": "1"}
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60, check=False)


# ======================================================================================
# 1. tracing is optional
# ======================================================================================

ABSENT_OPENTELEMETRY = r"""
import asyncio, importlib.abc, sys

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise ImportError(f"blocked for the test: {name}")
        return None

sys.meta_path.insert(0, Blocker())

import httpx
from nabiz.agent import telemetry
from ibb_mcp.http import PoliteClient

assert telemetry._otel is None
assert telemetry.setup_telemetry("nabiz-test") is None
with telemetry.span("nabiz.tool", **{"nabiz.tool.name": "places_resolve"}) as handle:
    handle.set(**{"nabiz.tool.ok": True})
    assert handle.recording is False

@telemetry.traced("nabiz.tool")
def add(left, right):
    return left + right

assert add(2, 3) == 5

async def main():
    client = PoliteClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"parks": 249})))
    try:
        assert await client.get_json("https://gateway.test/ispark/Park", source="ispark") == {"parks": 249}
    finally:
        await client.aclose()

asyncio.run(main())
assert not any(name.startswith("opentelemetry") for name in sys.modules)
print("served without opentelemetry")
"""


def test_everything_still_works_with_opentelemetry_absent() -> None:
    result = run_python(ABSENT_OPENTELEMETRY)
    assert result.returncode == 0, result.stderr
    assert "served without opentelemetry" in result.stdout


def test_the_http_layer_loads_the_shim_without_loading_the_agent() -> None:
    """``nabiz.agent`` exports lazily; an eager package would be an import cycle with ibb_mcp.http."""
    result = run_python(
        "import sys, ibb_mcp.http, ibb_mcp.server\n"
        "assert 'nabiz.agent.telemetry' in sys.modules\n"
        "assert 'nabiz.agent.agent' not in sys.modules, 'importing the server pulled the agent in'\n"
        "from nabiz.agent import NabizAgent, LlmConfig\n"
        "print(NabizAgent.__name__, LlmConfig.__name__)\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["NabizAgent", "LlmConfig"]


def test_traced_preserves_the_wrapped_signature() -> None:
    """The MCP SDK reads a tool's schema off its signature; a decorator must not hide it."""

    def places_resolve(query: str, limit: int = 5) -> str:
        return query

    wrapped = telemetry.traced("nabiz.tool")(places_resolve)
    assert wrapped.__wrapped__ is places_resolve
    assert inspect.signature(wrapped) == inspect.signature(places_resolve)
    assert wrapped.__name__ == "places_resolve"


def test_without_configuration_spans_go_nowhere_and_cost_nothing_visible() -> None:
    telemetry.setup_telemetry("nabiz-test")
    with telemetry.span("nabiz.tool", **{"nabiz.tool.name": "city_freshness"}) as handle:
        assert handle.recording is False


def test_a_provider_that_fails_to_start_a_span_does_not_break_the_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        def get_tracer(self, scope: str) -> Any:
            return self

        def start_as_current_span(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("exporter on fire")

    telemetry.install_tracer_provider(Broken())
    try:
        with telemetry.span("nabiz.tool") as handle:
            handle.set(**{"nabiz.tool.ok": True})
    finally:
        telemetry.install_tracer_provider(None)


# ======================================================================================
# 2. what a span may carry
# ======================================================================================


def test_span_records_its_name_and_allowed_attributes(spans: RecordingTracer) -> None:
    with telemetry.span("nabiz.tool", **{"nabiz.tool.name": "traffic_index"}) as handle:
        handle.set(**{"nabiz.tool.ok": True, "nabiz.tool.data_age_s": 42.0, "nabiz.tool.error_kind": None})

    recorded = spans.one("nabiz.tool")
    assert recorded.attributes == {"nabiz.tool.name": "traffic_index", "nabiz.tool.ok": True, "nabiz.tool.data_age_s": 42.0}
    # The SDK's default would write the exception message into the span; ours never asks it to.
    assert recorded.options == {"record_exception": False, "set_status_on_exception": False}


def test_attributes_outside_the_allow_list_are_dropped(spans: RecordingTracer) -> None:
    """The three shapes of personal data this project must never trace."""
    with telemetry.span(
        "nabiz.tool",
        **{
            "nabiz.tool.name": "ispark_find_parking",
            "plaka": "34 TEST 01",  # a number plate: dropped at parse (DECISIONS #7)
            "question": f"{TYPED_BY_THE_USER}'de otopark var mı?",  # the user's own words
            "lat": 40.9903,  # a coordinate that came from a user
        },
    ) as handle:
        handle.set(**{"user.place": TYPED_BY_THE_USER})

    assert set(spans.one("nabiz.tool").attributes) == {"nabiz.tool.name"}
    assert TYPED_BY_THE_USER not in spans.every_value()


def test_an_exception_message_never_reaches_the_span(spans: RecordingTracer) -> None:
    with pytest.raises(ValueError), telemetry.span("nabiz.tool", **{"nabiz.tool.name": "places_resolve"}):
        raise ValueError(f"Bilinmeyen yer: {TYPED_BY_THE_USER}")

    status = spans.one("nabiz.tool").status
    assert status.status_code.name == "ERROR"
    assert status.description == "ValueError"


def test_a_long_value_on_an_allowed_name_is_truncated(spans: RecordingTracer) -> None:
    with telemetry.span("nabiz.tool", **{"nabiz.tool.arg_names": "x" * 500}):
        pass
    assert len(spans.one("nabiz.tool").attributes["nabiz.tool.arg_names"]) == telemetry.MAX_VALUE_CHARS


def test_every_attribute_the_code_sets_is_on_the_allow_list() -> None:
    """A name missing from the list is silently dropped; this finds it before a demo does."""
    used: set[str] = set()
    for path in [*(REPO_ROOT / "src").rglob("*.py")]:
        used |= set(re.findall(r'"(nabiz\.(?:tool|http|agent)\.[a-z_]+)":', path.read_text(encoding="utf-8")))
    assert used, "no span attributes found; the pattern is stale"
    assert used <= telemetry.ALLOWED_ATTRIBUTES, sorted(used - telemetry.ALLOWED_ATTRIBUTES)


# ======================================================================================
# 3. call site: upstream HTTP
# ======================================================================================


async def test_upstream_span_records_the_request_without_its_query(spans: RecordingTracer) -> None:
    client = PoliteClient(transport=json_ok({"ok": True}))
    try:
        await client.get_json(
            f"https://gateway.test/ispark/ParkDetay?id=42&q={TYPED_BY_THE_USER}", source="ispark", budget="iett"
        )
    finally:
        await client.aclose()

    assert spans.one("nabiz.http.request").attributes == {
        "nabiz.http.method": "GET",
        "nabiz.http.host": "gateway.test",
        "nabiz.http.path": "/ispark/ParkDetay",
        "nabiz.http.source": "ispark",
        "nabiz.http.budget": "iett",
        "nabiz.http.budget_remaining": 79,
        "nabiz.http.attempts": 1,
        "nabiz.http.status": 200,
    }
    assert TYPED_BY_THE_USER not in spans.every_value()


async def test_upstream_span_records_a_failure_by_kind(spans: RecordingTracer) -> None:
    client = PoliteClient(transport=httpx.MockTransport(lambda request: httpx.Response(503)), max_attempts=1)
    try:
        with pytest.raises(UpstreamUnavailable):
            await client.get_json("https://gateway.test/ispark/Park", source="ispark")
    finally:
        await client.aclose()

    recorded = spans.one("nabiz.http.request")
    assert recorded.attributes["nabiz.http.status"] == 503
    assert recorded.status.description == "UpstreamUnavailable"


async def test_a_soap_call_wraps_its_request_and_the_unwrapping(spans: RecordingTracer) -> None:
    xml = (
        '<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        '<soap:Body><GetHatOtoKonum_jsonResponse xmlns="http://tempuri.org/">'
        "<GetHatOtoKonum_jsonResult>[]</GetHatOtoKonum_jsonResult>"
        "</GetHatOtoKonum_jsonResponse></soap:Body></soap:Envelope>"
    )
    client = PoliteClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=xml)))
    try:
        assert (
            await client.post_soap_json(
                "https://gateway.test/iett/FiloDurum/SeferGerceklesme.asmx",
                source="iett_line",
                action="GetHatOtoKonum_json",
                body_xml="<GetHatOtoKonum_json/>",
            )
            == []
        )
    finally:
        await client.aclose()

    soap = spans.one("nabiz.http.soap")
    assert spans.one("nabiz.http.request").parent is soap


# ======================================================================================
# 4. call site: a tool called by the agent (the MCP server's is in test_server_security.py)
# ======================================================================================


async def test_an_agent_turn_traces_itself_without_quoting_the_user(spans: RecordingTracer, ctx: SourceContext) -> None:
    """The trace a demo screenshot shows: a turn, the tool it chose, and the verdict."""
    agent = NabizAgent(Nabiz(ctx), config=llm.LlmConfig())  # provider "none": the deterministic path
    answer = await agent.ask(f"{TYPED_BY_THE_USER} hava kalitesi nasıl?")
    assert answer.mode == "deterministic"

    turn = spans.one("nabiz.agent.turn")
    assert turn.attributes["nabiz.agent.mode"] == "deterministic"
    assert turn.attributes["nabiz.agent.lang"] == "tr"
    assert turn.attributes["nabiz.agent.tool_calls"] == 1
    assert turn.attributes["nabiz.agent.tools"] == "air_quality_now"
    assert turn.attributes["nabiz.agent.faithful"] is True
    assert turn.attributes["nabiz.agent.turn"] >= 1

    tool = spans.one("nabiz.tool")
    assert tool.attributes["nabiz.tool.name"] == "air_quality_now"
    assert tool.attributes["nabiz.tool.arg_names"] == "place"  # the name, never the value
    assert tool.attributes["nabiz.tool.ok"] is True
    assert tool.attributes["nabiz.tool.cached"] is False
    assert "nabiz.tool.data_age_s" in tool.attributes
    assert tool.parent is spans.one("nabiz.agent.deterministic")

    assert TYPED_BY_THE_USER not in spans.every_value()
    assert answer.text not in spans.every_value()


async def test_an_agent_tool_failure_records_its_kind_not_its_message(spans: RecordingTracer, ctx: SourceContext) -> None:
    agent = NabizAgent(Nabiz(ctx), config=llm.LlmConfig(), system_prompt="test prompt")
    record = await agent._call_tool("metro_station_info", {"name": TYPED_BY_THE_USER + "-yok"})
    assert record.ok is False

    tool = spans.one("nabiz.tool")
    assert tool.attributes["nabiz.tool.ok"] is False
    assert tool.attributes["nabiz.tool.error_kind"] == "ValueError"
    assert TYPED_BY_THE_USER not in spans.every_value()


# ======================================================================================
# 5. choosing an exporter
# ======================================================================================


@pytest.fixture
def fake_azure(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stand-ins for ``azure.monitor.opentelemetry`` and ``azure.identity``, recording their calls."""
    calls: dict[str, Any] = {"configure": [], "credential": []}

    monitor = types.ModuleType("azure.monitor.opentelemetry")
    monitor.configure_azure_monitor = lambda **kwargs: calls["configure"].append(kwargs)  # type: ignore[attr-defined]
    identity = types.ModuleType("azure.identity")

    class ManagedIdentityCredential:
        def __init__(self, *, client_id: str) -> None:
            calls["credential"].append(client_id)

    identity.ManagedIdentityCredential = ManagedIdentityCredential  # type: ignore[attr-defined]
    for name, module in (
        ("azure", types.ModuleType("azure")),
        ("azure.monitor", types.ModuleType("azure.monitor")),
        ("azure.monitor.opentelemetry", monitor),
        ("azure.identity", identity),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    for name in ("OTEL_SERVICE_NAME", "OTEL_PYTHON_DISABLED_INSTRUMENTATIONS"):
        monkeypatch.delenv(name, raising=False)
    return calls


def test_azure_monitor_exports_our_spans_and_nothing_else(fake_azure: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto-instrumented FastAPI spans would carry /api/route?from=…&to=…; log export would carry messages."""
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", FAKE_CONNECTION)

    telemetry.setup_telemetry("ibb-mcp")

    (options,) = fake_azure["configure"]
    assert options["connection_string"].startswith("InstrumentationKey=")
    assert options["disable_logging"] is True and options["disable_metrics"] is True
    assert options["enable_live_metrics"] is False
    assert {"fastapi", "requests", "urllib", "urllib3"} <= set(options["instrumentation_options"])
    assert all(setting == {"enabled": False} for setting in options["instrumentation_options"].values())
    assert "fastapi" in os.environ["OTEL_PYTHON_DISABLED_INSTRUMENTATIONS"].split(",")
    assert os.environ["OTEL_SERVICE_NAME"] == "ibb-mcp"
    assert "credential" not in options, "no Entra credential was asked for"


def test_azure_monitor_uses_the_managed_identity_when_the_app_asks_for_entra(
    fake_azure: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", FAKE_CONNECTION)
    monkeypatch.setenv(
        "APPLICATIONINSIGHTS_AUTHENTICATION_STRING", "ClientId=11111111-2222-3333-4444-555555555555;Authorization=AAD"
    )

    telemetry.setup_telemetry("ibb-mcp")

    assert fake_azure["credential"] == ["11111111-2222-3333-4444-555555555555"]
    assert "credential" in fake_azure["configure"][0]


@pytest.mark.parametrize(
    ("authentication", "expected"),
    [
        ("ClientId=abc;Authorization=AAD", "abc"),
        ("Authorization=aad;ClientId= abc ", "abc"),
        ("ClientId=abc", None),
        ("", None),
        ("Authorization=AAD", None),
    ],
)
def test_the_entra_client_id_is_read_only_when_entra_is_asked_for(authentication: str, expected: str | None) -> None:
    assert telemetry._entra_client_id(authentication) == expected


def test_setup_runs_once(fake_azure: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", FAKE_CONNECTION)
    telemetry.setup_telemetry("ibb-mcp")
    telemetry.setup_telemetry("ibb-mcp")
    assert len(fake_azure["configure"]) == 1


def test_an_exporter_that_refuses_to_start_leaves_tracing_off(
    fake_azure: dict[str, Any], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def refuse(**kwargs: Any) -> None:
        raise ValueError("bad connection string")

    monkeypatch.setattr(sys.modules["azure.monitor.opentelemetry"], "configure_azure_monitor", refuse)
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=broken")

    with caplog.at_level(logging.WARNING, logger="nabiz.telemetry"):
        telemetry.setup_telemetry("ibb-mcp")

    assert "tracing stays off" in caplog.text
    assert telemetry._provider is None


def test_a_missing_azure_exporter_warns_and_leaves_tracing_off(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """``azure-monitor-opentelemetry`` is the optional ``telemetry`` extra and is not installed here."""
    monkeypatch.setitem(sys.modules, "azure.monitor.opentelemetry", None)
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", FAKE_CONNECTION)

    with caplog.at_level(logging.WARNING, logger="nabiz.telemetry"):
        telemetry.setup_telemetry("ibb-mcp")

    assert "azure-monitor-opentelemetry is not installed" in caplog.text
    assert telemetry._provider is None


def test_console_tracing_without_the_sdk_warns_and_stays_off(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    for name in ("opentelemetry.sdk", "opentelemetry.sdk.resources", "opentelemetry.sdk.trace", "opentelemetry.sdk.trace.export"):
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setenv("NABIZ_TRACE_CONSOLE", "1")

    with caplog.at_level(logging.WARNING, logger="nabiz.telemetry"):
        telemetry.setup_telemetry("nabiz-test")

    assert "opentelemetry-sdk is not installed" in caplog.text
    assert telemetry._provider is None


def test_console_exporter_is_wired_to_stderr_even_without_the_sdk(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The stdio guarantee, checked everywhere: spans go to stderr, because stdout is MCP's channel.

    opentelemetry-sdk is optional and neither the dev extra nor CI installs it, so the test
    below with the real SDK is skipped on every runner. Here the three SDK classes
    ``_setup_console`` imports are stood in for, each doing the one thing the real one does
    that matters: the exporter writes a finished span to the stream it was given.
    """
    built: dict[str, Any] = {}

    class Resource:
        @staticmethod
        def create(attributes: dict[str, Any]) -> dict[str, Any]:
            return attributes

    class ConsoleSpanExporter:
        def __init__(self, out: Any) -> None:
            built["out"] = out

        def export(self, name: str) -> None:
            built["out"].write(f"span {name}\n")

    class SimpleSpanProcessor:
        def __init__(self, exporter: ConsoleSpanExporter) -> None:
            self.exporter = exporter

    class TracerProvider(RecordingProvider):
        def __init__(self, resource: dict[str, Any]) -> None:
            super().__init__()
            built["resource"] = resource
            self.processors: list[SimpleSpanProcessor] = []

        def add_span_processor(self, processor: SimpleSpanProcessor) -> None:
            self.processors.append(processor)

    stand_ins = {
        "opentelemetry.sdk": types.ModuleType("opentelemetry.sdk"),
        "opentelemetry.sdk.resources": types.SimpleNamespace(Resource=Resource),
        "opentelemetry.sdk.trace": types.SimpleNamespace(TracerProvider=TracerProvider),
        "opentelemetry.sdk.trace.export": types.SimpleNamespace(
            ConsoleSpanExporter=ConsoleSpanExporter, SimpleSpanProcessor=SimpleSpanProcessor
        ),
    }
    for name, module in stand_ins.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv("NABIZ_TRACE_CONSOLE", "1")

    telemetry.setup_telemetry("nabiz-test")
    provider = telemetry._provider
    assert isinstance(provider, TracerProvider), "the console path did not install its provider"
    assert built["out"] is sys.stderr, "the console exporter must write to stderr, never stdout"
    assert built["resource"] == {"service.name": "nabiz-test"}
    with telemetry.span("nabiz.tool", **{"nabiz.tool.name": "city_freshness"}):
        pass
    for finished in provider.tracer.finished:
        for processor in provider.processors:
            processor.exporter.export(finished.name)

    captured = capsys.readouterr()
    assert "nabiz.tool" in captured.err
    assert captured.out == ""


def test_console_exporter_prints_spans_to_stderr_never_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The local demo path, with the real SDK where it is installed (the telemetry extra)."""
    pytest.importorskip("opentelemetry.sdk.trace", reason="opentelemetry-sdk is optional and not installed here")
    monkeypatch.setenv("NABIZ_TRACE_CONSOLE", "1")

    telemetry.setup_telemetry("nabiz-test")
    with telemetry.span("nabiz.tool", **{"nabiz.tool.name": "city_freshness"}):
        pass

    captured = capsys.readouterr()
    assert "city_freshness" in captured.err
    assert captured.out == ""
