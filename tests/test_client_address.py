"""A10: the limiter's address, and a forged ``X-Forwarded-For`` that must not buy a bucket of its own."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from nabiz.console.client_address import TRUSTED_PROXIES_ENV, limiter_address

PROXY = "10.0.0.5"


def _app(env: dict[str, str]) -> FastAPI:
    app = FastAPI()

    @app.get("/who")
    async def who(request: Request) -> dict[str, str]:
        return {"address": limiter_address(request, env)}

    return app


def _ask(env: dict[str, str], peer: str, forwarded: str | None = None) -> str:
    client = TestClient(_app(env), client=(peer, 50000))
    headers = {"X-Forwarded-For": forwarded} if forwarded is not None else {}
    return client.get("/who", headers=headers).json()["address"]


def test_without_trusted_proxies_the_peer_is_the_address_and_the_header_is_ignored() -> None:
    assert _ask({}, "203.0.113.7") == "203.0.113.7"
    assert _ask({}, "203.0.113.7", "198.51.100.1") == "203.0.113.7", "a forged header changes nothing"
    assert _ask({TRUSTED_PROXIES_ENV: ""}, PROXY, "198.51.100.1") == PROXY, "today's behaviour, behind a proxy too"


def test_behind_a_trusted_proxy_each_visitor_gets_their_own_address() -> None:
    env = {TRUSTED_PROXIES_ENV: "10.0.0.0/24"}
    assert _ask(env, PROXY, "198.51.100.1") == "198.51.100.1"
    assert _ask(env, PROXY, "198.51.100.2") == "198.51.100.2"


def test_the_rightmost_untrusted_hop_wins_so_a_forged_left_entry_does_nothing() -> None:
    env = {TRUSTED_PROXIES_ENV: "10.0.0.0/24, 10.1.0.1"}
    # The visitor wrote "192.0.2.4" themselves; the proxies appended the address they really saw.
    assert _ask(env, PROXY, "192.0.2.4, 198.51.100.9, 10.1.0.1") == "198.51.100.9"


def test_a_header_from_an_untrusted_peer_is_ignored() -> None:
    assert _ask({TRUSTED_PROXIES_ENV: "10.0.0.0/24"}, "203.0.113.7", "198.51.100.1") == "203.0.113.7"


def test_a_malformed_hop_or_a_missing_header_falls_back_to_the_proxy() -> None:
    env = {TRUSTED_PROXIES_ENV: "10.0.0.0/24"}
    assert _ask(env, PROXY, "not-an-address") == PROXY
    assert _ask(env, PROXY) == PROXY
    assert _ask(env, PROXY, "10.0.0.9") == PROXY, "only proxies in the chain"


def test_a_malformed_trusted_entry_is_skipped_not_widened() -> None:
    assert _ask({TRUSTED_PROXIES_ENV: "nonsense, 0.0.0.0/0x"}, PROXY, "198.51.100.1") == PROXY


def test_ipv6() -> None:
    env = {TRUSTED_PROXIES_ENV: "fd00::/8"}
    assert _ask(env, "fd00::1", "2001:db8::7") == "2001:db8::7"
