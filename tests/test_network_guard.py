"""The suite-wide network guard in ``tests/conftest.py`` must be seen refusing.

A guard nobody has watched fail is a guard nobody knows works (docs/ENGINEERING.md CI-6).
Every address used here is either a documentation range that routes nowhere (RFC 5737)
or a lookup the guard refuses before any resolver is asked, so nothing leaves the machine
even if the guard were broken.
"""

from __future__ import annotations

import socket

import httpx
import pytest


def test_a_dns_lookup_for_an_ibb_host_is_refused_and_recorded(_no_outbound_network: list[str]) -> None:
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("api.ibb.gov.tr", 443)
    assert _no_outbound_network == ["DNS lookup 'api.ibb.gov.tr'"]
    _no_outbound_network.clear()  # the refusal was the point; do not fail the teardown


def test_a_raw_connection_off_the_machine_is_refused(_no_outbound_network: list[str]) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock, pytest.raises(ConnectionRefusedError):
        sock.connect(("192.0.2.1", 443))  # TEST-NET-1: documentation only, routes nowhere
    assert len(_no_outbound_network) == 1
    _no_outbound_network.clear()


def test_a_client_built_outside_ctx_is_refused_too(_no_outbound_network: list[str]) -> None:
    # The gap the guard closes: this client never went through the ctx fixture.
    with httpx.Client() as client, pytest.raises(httpx.ConnectError):
        client.get("https://api.ibb.gov.tr/")
    assert _no_outbound_network and all("api.ibb.gov.tr" in a for a in _no_outbound_network)
    _no_outbound_network.clear()


def test_loopback_stays_allowed(_no_outbound_network: list[str]) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(server.getsockname(), timeout=5):
            pass
    assert _no_outbound_network == []
