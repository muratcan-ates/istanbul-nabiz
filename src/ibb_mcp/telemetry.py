"""OpenTelemetry for İstanbul Nabız, confined to one module and optional everywhere.

The promise this module keeps is that **nothing else in the codebase imports
OpenTelemetry**. Call sites ask for :func:`span` or :func:`traced` and get something that
works whether the packages are installed or not. The API package happens to arrive with
the MCP SDK today, but nothing here depends on that staying true: an optional dependency
that turned into an ``ImportError`` at start-up would take the server down for a feature
nobody asked for.

It lives in the server package because the server's HTTP client and tool wrapper make
spans, and ``ibb_mcp`` imports nothing from ``nabiz`` (DECISIONS #8). Until 2026-09-23 it
was ``nabiz.agent.telemetry``, where the agent's spans were; that name is still the same
module (:mod:`nabiz.agent.telemetry` aliases this one), so the agent, the web app and any
code written before the move share one tracer and one allow-list.

:func:`setup_telemetry` picks an exporter from the environment, once per process:

``APPLICATIONINSIGHTS_CONNECTION_STRING`` set
    Azure Monitor, the deployed shape: ``infra/modules/containerapps.bicep`` sets it on the
    MCP app. Needs ``azure-monitor-opentelemetry`` (the ``telemetry`` extra); without it
    tracing stays off and one log line says so.
``NABIZ_TRACE_CONSOLE=1``
    Spans printed to **stderr**, the local demo path; needs only ``opentelemetry-sdk``.
    stderr because stdout is the MCP channel on the stdio transport, and a span written
    there would corrupt the JSON-RPC stream mid-session.
neither
    Nothing is configured, the API hands back its no-op tracer and an instrumented call
    costs a couple of dictionary lookups.

**Privacy is a hard constraint on span attributes, not a nicety.** A trace is shipped to a
cloud service and kept there, which makes it exactly the kind of server-side store
docs/NABIZ.md §1.3 keeps personal data out of. So a span may never carry:

* a bus number plate: dropped at the parsing boundary (DECISIONS #7), and it does not come
  back here;
* anything the user typed: the question, a place or stop name, any argument *value*.
  Argument *names* are fine, and are what the tool spans record;
* coordinates that came from a user.

That rule is enforced by :data:`ALLOWED_ATTRIBUTES`, an allow-list. A deny-list would be a
guess about what the next attribute happens to be called, and the price of guessing wrong
is a user's address sitting in Application Insights. Anything not on the list is dropped
before it reaches a span. Exceptions get the same treatment: spans are opened with
``record_exception=False`` and ``set_status_on_exception=False``, because both put the
exception *message* into the trace and this project's messages read
"Bilinmeyen yer: <whatever the user typed>". Only the exception's type name is recorded.

The allow-list only governs spans made here. The Azure Monitor distro would also
auto-instrument FastAPI, requests and urllib, and those spans record full URLs — query
strings included, and ``/api/route?from=…&to=…`` is two places a person typed — and it
would forward Python log records. :func:`_setup_azure_monitor` therefore switches every
auto-instrumentation and the log and metric exporters off, so the only spans that leave
the process are ours and the MCP SDK's (which carry the method and tool name, never the
arguments).
"""

from __future__ import annotations

import contextlib
import functools
import inspect
import logging
import os
import sys
import threading
from collections.abc import Callable, Iterator
from typing import Any

log = logging.getLogger("nabiz.telemetry")

try:
    from opentelemetry import trace as _otel
except ImportError:  # pragma: no cover - exercised in a subprocess by tests/test_agent_telemetry.py
    _otel = None

#: Instrumentation scope every span in this project is created under.
SCOPE = "istanbul-nabiz"

#: The complete vocabulary of span attributes. See the module docstring for why this is an
#: allow-list. Adding a name here is the moment to ask whether the value can ever contain
#: something a user typed: if it can, it does not belong in a trace.
ALLOWED_ATTRIBUTES = frozenset(
    {
        # one tool invocation, from the agent or from the MCP server
        "nabiz.tool.name",
        "nabiz.tool.arg_names",  # names only: `place="Taksim"` is the user's own words
        "nabiz.tool.ok",
        "nabiz.tool.cached",
        "nabiz.tool.data_age_s",
        "nabiz.tool.duration_ms",
        "nabiz.tool.error_kind",
        # one upstream request to İBB
        "nabiz.http.method",
        "nabiz.http.host",
        "nabiz.http.path",  # path only: the query string can carry a resolved place
        "nabiz.http.source",
        "nabiz.http.status",
        "nabiz.http.attempts",
        "nabiz.http.budget",
        "nabiz.http.budget_remaining",
        "nabiz.http.error_kind",
        # one agent turn, and the model calls inside it
        "nabiz.agent.turn",
        "nabiz.agent.step",
        "nabiz.agent.mode",
        "nabiz.agent.lang",
        "nabiz.agent.provider",
        "nabiz.agent.model",
        "nabiz.agent.steps",
        "nabiz.agent.tool_calls",
        "nabiz.agent.tools",
        "nabiz.agent.faithful",
        "nabiz.agent.repaired",
        "nabiz.agent.forced",
        "nabiz.agent.repair",
    }
)

#: Attribute values are short by construction: a tool name, a status code, a duration.
#: The cap is a second line of defence: a long string that reaches an allowed name is
#: truncated rather than shipped whole.
MAX_VALUE_CHARS = 120

#: Auto-instrumentations the Azure Monitor distro would otherwise switch on. Each one
#: records URLs (with their query strings) or SQL for spans that bypass the allow-list.
#: Names as the distro's README lists them; not exercised here, because the distro is not
#: installed in the development environment (see :func:`_setup_azure_monitor`).
AZURE_AUTO_INSTRUMENTATIONS = ("azure_sdk", "django", "fastapi", "flask", "psycopg2", "requests", "urllib", "urllib3")

_lock = threading.Lock()
_configured = False
_provider: Any = None
_tracer: Any = None


def _clean(attributes: dict[str, Any]) -> dict[str, Any]:
    """Drop everything that is not an allow-listed, scalar, short attribute."""
    cleaned: dict[str, Any] = {}
    for key, value in attributes.items():
        if value is None:
            continue
        if key not in ALLOWED_ATTRIBUTES:
            log.debug("telemetry: dropped attribute %r (not in the allow-list)", key)
            continue
        cleaned[key] = value if isinstance(value, bool | int | float) else str(value)[:MAX_VALUE_CHARS]
    return cleaned


class Span:
    """A handle on one span, or on nothing at all, with the same methods either way.

    Call sites hold one of these and never a raw OpenTelemetry span, which is what makes
    the privacy filter unavoidable: every attribute that reaches a real span goes through
    :meth:`set`.
    """

    __slots__ = ("_span",)

    def __init__(self, span: Any = None) -> None:
        self._span = span

    @property
    def recording(self) -> bool:
        """True when this span will actually be exported somewhere."""
        return self._span is not None and bool(getattr(self._span, "is_recording", lambda: False)())

    def set(self, **attributes: Any) -> None:
        """Attach attributes, filtered. Never raises: telemetry must not break a request."""
        if self._span is None:
            return
        for key, value in _clean(attributes).items():
            try:
                self._span.set_attribute(key, value)
            except Exception:  # noqa: BLE001 - a broken exporter is not worth an outage
                log.debug("telemetry: could not set attribute %r", key, exc_info=True)

    def fail(self, exc: BaseException) -> None:
        """Mark the span failed, recording the exception's *type* and nothing else.

        The message is deliberately left out. Tool errors in this codebase quote the
        user's own input back ("Bilinmeyen yer: …"), so a status description would carry
        free text straight into a cloud log.
        """
        if self._span is None or _otel is None:
            return
        try:
            self._span.set_status(_otel.Status(_otel.StatusCode.ERROR, type(exc).__name__))
        except Exception:  # noqa: BLE001 - same reason as above
            log.debug("telemetry: could not set span status", exc_info=True)


_NULL_SPAN = Span(None)


def _get_tracer() -> Any:
    """The tracer to use, or None when OpenTelemetry is not importable."""
    global _tracer
    if _otel is None:
        return None
    if _tracer is None:
        provider = _provider
        _tracer = provider.get_tracer(SCOPE) if provider is not None else _otel.get_tracer(SCOPE)
    return _tracer


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[Span]:
    """Open one span. Yields a :class:`Span` handle, which may wrap nothing.

    ``record_exception`` and ``set_status_on_exception`` are both off: the SDK's default
    behaviour writes the exception message into the span, and this project's messages
    contain user input. :meth:`Span.fail` records the type name instead.
    """
    tracer = _get_tracer()
    if tracer is None:
        yield _NULL_SPAN
        return
    try:
        started = tracer.start_as_current_span(name, record_exception=False, set_status_on_exception=False)
    except Exception:  # noqa: BLE001 - a misconfigured provider must not break the caller
        log.debug("telemetry: could not start span %r", name, exc_info=True)
        yield _NULL_SPAN
        return
    with started as raw:
        handle = Span(raw)
        handle.set(**attributes)
        try:
            yield handle
        except BaseException as exc:
            handle.fail(exc)
            raise


def traced[F: Callable[..., Any]](name: str | F | None = None, /, **attributes: Any) -> Any:
    """Wrap a function in a span. Usable bare (``@traced``) or named (``@traced("x")``).

    ``functools.wraps`` is not cosmetic here. The MCP SDK derives every tool's JSON schema
    from the wrapped function's signature, so a decorator that loses ``__wrapped__`` makes
    each tool advertise ``(*args, **kwargs)`` and every call is rejected.
    """

    def decorate(fn: F) -> F:
        span_name = name if isinstance(name, str) else f"nabiz.{fn.__qualname__}"

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with span(span_name, **attributes):
                    return await fn(*args, **kwargs)

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with span(span_name, **attributes):
                return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorate(name) if callable(name) else decorate


def install_tracer_provider(provider: Any) -> None:
    """Route this module's spans through ``provider``; ``None`` goes back to the global one.

    :func:`setup_telemetry` uses it for the console exporter, the tests use it to capture
    spans in memory, and a host that already owns the global tracer provider can hand us
    its own rather than have us fight it for the global.
    """
    global _provider, _tracer
    _provider = provider
    _tracer = None


def setup_telemetry(service_name: str) -> None:
    """Configure tracing once, from the environment. Safe to call when OTel is absent.

    Idempotent by design: the MCP server, the web app and the collector may each call it,
    and only the first call does anything. A failed configuration also counts as done:
    retrying on every call would repeat the same warning for the life of the process.
    """
    global _configured
    with _lock:
        if _configured:
            return
        _configured = True
        if _otel is None:
            log.debug("opentelemetry is not installed; tracing is off")
            return

        connection = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
        if connection and _setup_azure_monitor(service_name, connection):
            return
        if os.getenv("NABIZ_TRACE_CONSOLE", "").strip().lower() in {"1", "true", "yes"}:
            _setup_console(service_name)
            return
        log.debug("no trace exporter configured; spans go nowhere")


def _entra_client_id(authentication: str) -> str | None:
    """The managed identity's client id from ``APPLICATIONINSIGHTS_AUTHENTICATION_STRING``.

    The Container App sets ``ClientId=<id>;Authorization=AAD``. Anything else (unset, or
    a string that does not ask for Entra) returns None and the connection string alone is
    used, which works because the component keeps local auth enabled
    (infra/modules/monitoring.bicep).
    """
    parts = dict(item.split("=", 1) for item in authentication.split(";") if "=" in item)
    if parts.get("Authorization", "").strip().upper() != "AAD":
        return None
    return parts.get("ClientId", "").strip() or None


def _setup_azure_monitor(service_name: str, connection_string: str) -> bool:
    """Send spans, and only spans, to Application Insights. False if that was not possible.

    Not exercised against the real package here: ``azure-monitor-opentelemetry`` is not
    installed in the development environment, and the tests stand a fake in for it. The
    keyword names follow the distro's documented configuration; in case one is not
    recognised, the auto-instrumentations are also named in
    ``OTEL_PYTHON_DISABLED_INSTRUMENTATIONS``, OpenTelemetry Python's own switch for the
    same thing. Confirming that only ``nabiz.*`` and MCP spans arrive is the first thing
    to check in Application Insights after a deploy.
    """
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError:
        log.warning(
            "APPLICATIONINSIGHTS_CONNECTION_STRING is set but azure-monitor-opentelemetry is not installed "
            "(pip install '.[telemetry]'); tracing stays off"
        )
        return False
    # The service name travels as an environment variable rather than a `resource=`
    # keyword so that this call depends on as little of the package's surface as
    # possible; OTEL_SERVICE_NAME is read by the SDK's default resource detector.
    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
    os.environ.setdefault("OTEL_PYTHON_DISABLED_INSTRUMENTATIONS", ",".join(AZURE_AUTO_INSTRUMENTATIONS))
    options: dict[str, Any] = {
        "connection_string": connection_string,
        "disable_logging": True,
        "disable_metrics": True,
        "enable_live_metrics": False,
        "instrumentation_options": {name: {"enabled": False} for name in AZURE_AUTO_INSTRUMENTATIONS},
    }
    client_id = _entra_client_id(os.getenv("APPLICATIONINSIGHTS_AUTHENTICATION_STRING", ""))
    if client_id:
        try:
            from azure.identity import ManagedIdentityCredential
        except ImportError:
            log.warning("Entra authentication was asked for but azure-identity is not installed; using the connection string")
        else:
            options["credential"] = ManagedIdentityCredential(client_id=client_id)
    try:
        configure_azure_monitor(**options)
    except Exception:  # noqa: BLE001 - an exporter that will not start must not stop the server
        log.warning("Application Insights exporter could not be configured; tracing stays off", exc_info=True)
        return False
    # configure_azure_monitor installs its own global provider, so this module keeps none
    # of its own and resolves the tracer from the global on first use.
    install_tracer_provider(None)
    log.info("tracing: exporting spans to Application Insights as %r", service_name)
    return True


def _setup_console(service_name: str) -> None:
    """Print spans to stderr. The local demo path, and the one used to eyeball a trace."""
    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
    except ImportError:
        log.warning("NABIZ_TRACE_CONSOLE is set but opentelemetry-sdk is not installed; tracing stays off")
        return
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    # Simple, not batched: a demo that ends before the batch interval elapses would print
    # nothing at all. stderr because stdout carries MCP's JSON-RPC frames.
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))
    # The global provider is deliberately left alone: a host process may own it, and
    # losing that argument is worse than having our spans in a provider of our own.
    install_tracer_provider(provider)
    log.info("tracing: printing spans to stderr as %r", service_name)
