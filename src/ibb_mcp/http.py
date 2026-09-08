"""A deliberately polite HTTP client for the İBB gateway.

Why this exists as its own layer: ``api.ibb.gov.tr`` starts returning HTTP 503 for
*every* service after roughly 15 rapid requests, and the İETT fleet service documents a
hard limit of 100 requests per hour. A naive "one upstream call per user question"
design would take the whole gateway down for everybody, so:

* one shared client enforces a minimum interval per host,
* a token bucket enforces the İETT hourly budget,
* retries use exponential backoff with jitter and give up quickly,
* everything a tool reads goes through :mod:`ibb_mcp.cache`, so N concurrent users
  produce at most one upstream request.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

log = logging.getLogger("ibb_mcp.http")

USER_AGENT = "istanbul-nabiz/0.1 (+https://github.com/muratcan-ates/istanbul-nabiz) open-data client"
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=45.0, write=15.0, pool=10.0)

#: Minimum seconds between requests to a host. The gateway is shared by every İBB
#: service, so the limit is per host, not per endpoint.
HOST_MIN_INTERVAL = {"api.ibb.gov.tr": 6.0, "data.ibb.gov.tr": 1.0}
DEFAULT_MIN_INTERVAL = 1.0

RETRY_STATUS = {429, 500, 502, 503, 504}


class UpstreamUnavailable(RuntimeError):
    """Raised when an İBB endpoint could not be read after retries.

    Callers are expected to fall back to cached data and tell the user how old it is,
    rather than inventing a value.
    """

    def __init__(self, message: str, *, source: str, status: int | None = None) -> None:
        super().__init__(message)
        self.source = source
        self.status = status


class RateLimitExceeded(UpstreamUnavailable):
    """Raised when our own budget for a source is exhausted (we stop before İBB does)."""


@dataclass
class _HostGate:
    """Serialises requests to one host with a minimum spacing."""

    min_interval: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_call: float = 0.0

    async def wait(self) -> None:
        async with self.lock:
            delay = self.min_interval - (time.monotonic() - self.last_call)
            if delay > 0:
                await asyncio.sleep(delay)
            self.last_call = time.monotonic()


@dataclass
class HourlyBudget:
    """A simple sliding-window budget, used for the İETT 100 requests/hour rule."""

    name: str
    limit: int
    window_seconds: float = 3600.0
    _calls: list[float] = field(default_factory=list)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        self._calls = [t for t in self._calls if t > cutoff]

    @property
    def remaining(self) -> int:
        self._prune(time.monotonic())
        return max(0, self.limit - len(self._calls))

    def consume(self) -> None:
        now = time.monotonic()
        self._prune(now)
        if len(self._calls) >= self.limit:
            raise RateLimitExceeded(
                f"{self.name}: kendi saatlik bütçemiz doldu ({self.limit} istek/saat); önbellekten servis ediliyor.",
                source=self.name,
            )
        self._calls.append(now)


class PoliteClient:
    """Shared HTTP client. Create one per process and reuse it."""

    def __init__(
        self,
        *,
        timeout: httpx.Timeout | None = None,
        max_attempts: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout or DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            transport=transport,
        )
        self._gates: dict[str, _HostGate] = {}
        self._max_attempts = max_attempts
        self.budgets: dict[str, HourlyBudget] = {
            # İETT documents a maximum of 100 requests per hour; we stay under it.
            "iett": HourlyBudget("iett", limit=80),
        }

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> PoliteClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def _gate_for(self, url: str) -> _HostGate:
        host = urlsplit(url).netloc
        if host not in self._gates:
            self._gates[host] = _HostGate(HOST_MIN_INTERVAL.get(host, DEFAULT_MIN_INTERVAL))
        return self._gates[host]

    async def request(
        self,
        method: str,
        url: str,
        *,
        source: str,
        budget: str | None = None,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        if budget and budget in self.budgets:
            self.budgets[budget].consume()

        gate = self._gate_for(url)
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            await gate.wait()
            try:
                response = await self._client.request(method, url, headers=headers, content=content, params=params)
            except httpx.HTTPError as exc:
                last_error = exc
                log.warning("%s: transport error on attempt %d: %r", source, attempt, exc)
            else:
                if response.status_code == 200:
                    return response
                last_error = UpstreamUnavailable(
                    f"{source}: HTTP {response.status_code}", source=source, status=response.status_code
                )
                if response.status_code not in RETRY_STATUS:
                    raise last_error
                log.warning("%s: HTTP %d on attempt %d", source, response.status_code, attempt)
            if attempt < self._max_attempts:
                # The gateway needs roughly a minute and a half to recover from a 503 burst.
                backoff = min(30.0, 4.0 * 2 ** (attempt - 1)) * (0.7 + 0.6 * random.random())
                await asyncio.sleep(backoff)

        if isinstance(last_error, UpstreamUnavailable):
            raise last_error
        raise UpstreamUnavailable(f"{source}: {last_error!r}", source=source)

    async def get_json(
        self,
        url: str,
        *,
        source: str,
        budget: str | None = None,
        params: dict[str, Any] | None = None,
        accept_json: bool = True,
    ) -> Any:
        """GET and parse JSON.

        ``accept_json`` matters: the traffic-index endpoint returns XML unless an
        explicit ``Accept: application/json`` header is sent.
        """
        headers = {"Accept": "application/json"} if accept_json else None
        response = await self.request("GET", url, source=source, budget=budget, headers=headers, params=params)
        return _loads(response, source)

    async def post_soap_json(
        self,
        url: str,
        *,
        source: str,
        action: str,
        body_xml: str,
        budget: str | None = None,
    ) -> Any:
        """Call an İETT ``.asmx`` operation whose result is a JSON string inside SOAP XML."""
        envelope = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            f"<soap:Body>{body_xml}</soap:Body>"
            "</soap:Envelope>"
        ).encode()
        response = await self.request(
            "POST",
            url,
            source=source,
            budget=budget,
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"http://tempuri.org/{action}"'},
            content=envelope,
        )
        return extract_soap_json(response.text, action, source=source)


def extract_soap_json(xml_text: str, action: str, *, source: str = "iett") -> Any:
    """Pull the embedded JSON payload out of a SOAP response body.

    İETT wraps a JSON *string* inside ``<{action}Result>`` with XML entity escaping, and
    Oracle errors sometimes leak through as plain text in the same element.
    """
    match = re.search(rf"<{re.escape(action)}Result>(.*?)</{re.escape(action)}Result>", xml_text, re.S)
    if not match:
        fault = re.search(r"<faultstring>(.*?)</faultstring>", xml_text, re.S)
        detail = html.unescape(fault.group(1)).strip() if fault else "sonuç elemanı yok"
        raise UpstreamUnavailable(f"{source}/{action}: {detail}", source=source)
    payload = html.unescape(match.group(1)).strip()
    if not payload:
        return []
    if payload.startswith("ORA-") or "ORA-" in payload[:200]:
        raise UpstreamUnavailable(f"{source}/{action}: upstream Oracle hatası: {payload[:160]}", source=source)
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise UpstreamUnavailable(f"{source}/{action}: JSON çözülemedi: {exc}", source=source) from exc


def _loads(response: httpx.Response, source: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        snippet = response.text[:160].replace("\n", " ")
        raise UpstreamUnavailable(f"{source}: yanıt JSON değil ({snippet!r})", source=source) from exc
