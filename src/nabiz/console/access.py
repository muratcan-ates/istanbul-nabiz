"""Who may use the operator's side, and how often one visitor may ask the chat.

**The operator's side** (``/console`` and ``/api/console/*``) approves cards whose text the
citizen page then shows as "Simüle operatör onayladı", and an approval changes what the
reflexes do next. So it is not open to whoever reaches the port:

* ``NABIZ_CONSOLE_TOKEN`` set: a request carries it in the ``X-Nabiz-Operator`` header (a
  script, a test), or carries the cookie the console's sign-in form sets. The cookie holds an
  HMAC of the token, not the token, and is ``HttpOnly`` and ``SameSite=Strict``. Every
  comparison is constant-time.
* no token: the console answers only while the app is bound to this machine (``NABIZ_HOST``
  loopback, the default) and only to a ``Host`` header naming this machine, so a web page
  that rebinds its own name to 127.0.0.1 (DNS rebinding) cannot drive it. Bound to any other
  address without a token, the console refuses with 503 rather than open itself to a network.

**The chat** answers everyone, but one address gets a bounded number of turns a minute
(:class:`TurnLimiter`), so one visitor cannot spend the day's model ceiling for everyone.
Addresses are kept only as bucket keys in memory, never logged or written anywhere.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field

from fastapi import Request
from fastapi.responses import JSONResponse

HEADER = "x-nabiz-operator"
COOKIE = "nabiz_operator"
COOKIE_MAX_AGE_S = 12 * 3600
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
#: Turns one address may start per minute, and how many addresses the limiter remembers.
#: Design parameters, not measured values.
CHAT_TURNS_PER_MIN = 10
REMEMBERED_CLIENTS = 4096


def host_name(header: str) -> str:
    """The name in a ``Host`` header, without its port (``[::1]:8090`` is ``::1``)."""
    header = header.strip().lower()
    if header.startswith("["):
        return header[1:].split("]", 1)[0]
    return header.rsplit(":", 1)[0] if header.count(":") == 1 else header


@dataclass(frozen=True)
class OperatorAccess:
    """The console's door: a token, or this machine only."""

    token: str | None = None
    bound_host: str = "127.0.0.1"
    extra_hosts: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> OperatorAccess:
        env = os.environ if env is None else env
        token = (env.get("NABIZ_CONSOLE_TOKEN") or "").strip() or None
        extra = frozenset(h.strip().lower() for h in (env.get("NABIZ_ALLOWED_HOSTS") or "").split(",") if h.strip())
        return cls(token=token, bound_host=(env.get("NABIZ_HOST") or "127.0.0.1").strip(), extra_hosts=extra)

    @property
    def local_only(self) -> bool:
        return host_name(self.bound_host) in LOOPBACK_HOSTS

    def cookie_value(self) -> str:
        """What the sign-in cookie holds: an HMAC of the token, so the cookie never is the token."""
        if self.token is None:
            return ""
        return hmac.new(self.token.encode("utf-8"), b"nabiz-console-session", hashlib.sha256).hexdigest()

    def token_matches(self, offered: str) -> bool:
        return self.token is not None and hmac.compare_digest(offered.encode("utf-8"), self.token.encode("utf-8"))

    def refusal(self, request: Request) -> JSONResponse | None:
        """``None`` when the request may reach the console; else the answer it gets instead."""
        if self.token is not None:
            if self.token_matches(request.headers.get(HEADER, "")):
                return None
            cookie = request.cookies.get(COOKIE, "")
            if cookie and hmac.compare_digest(cookie.encode("utf-8"), self.cookie_value().encode("utf-8")):
                return None
            return _problem(401, "unauthorized", "Konsol için operatör girişi gerekli.")
        if not self.local_only:
            return _problem(503, "console_locked", "Konsol anahtarı tanımlanmadan bu adreste açılmaz.")
        if host_name(request.headers.get("host", "")) not in LOOPBACK_HOSTS | self.extra_hosts:
            return _problem(403, "forbidden_host", "Konsol yalnız bu bilgisayarın adresinden açılır.")
        return None


def _problem(status: int, kind: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": kind, "message": message})


class TurnLimiter:
    """A token bucket per client address: ``per_min`` turns a minute, a burst of the same size."""

    def __init__(self, per_min: int = CHAT_TURNS_PER_MIN, *, clients: int = REMEMBERED_CLIENTS) -> None:
        self.capacity = float(max(1, per_min))
        self.rate = self.capacity / 60.0
        self.clients = clients
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def allow(self, client: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        tokens, seen = self._buckets.pop(client, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - seen) * self.rate)
        allowed = tokens >= 1.0
        self._buckets[client] = (tokens - 1.0 if allowed else tokens, now)
        while len(self._buckets) > self.clients:
            self._buckets.popitem(last=False)
        return allowed


def is_operator_path(path: str) -> bool:
    """The operator's page (by its route or its file) and API; the sign-in form stays reachable."""
    return path in ("/console", "/console.html") or path.startswith("/api/console/")


def login_page(*, failed: bool) -> str:
    """The console's sign-in form: one field, no script, the same honesty labels as every page."""
    error = '<p class="field-error" role="alert">Anahtar doğrulanamadı.</p>' if failed else ""
    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Nabız konsol: giriş</title>
<link rel="stylesheet" href="/css/tokens.css"><link rel="stylesheet" href="/css/base.css">
<link rel="stylesheet" href="/css/components.css"></head>
<body><main id="main" class="shell"><h1>Nabız konsol: simüle operatör girişi</h1>
<p>Resmî İBB hizmeti değildir. Bu konsol simüle operatör içindir.</p>{error}
<form method="post" action="/console/login"><div class="field"><label for="token">Operatör anahtarı</label>
<input id="token" name="token" type="password" autocomplete="current-password" required maxlength="200"></div>
<button type="submit" class="btn btn-primary">Giriş</button></form></main></body></html>
"""
