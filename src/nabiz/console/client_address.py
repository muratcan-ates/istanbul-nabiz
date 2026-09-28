"""The address a limiter keys on, behind a reverse proxy only when the proxy is named (A10, KARAR 3).

Every limiter in the console (the chat's turn limiter, the request desk, the report and account routes)
read ``request.client.host``. Behind a reverse proxy that is the proxy's address, so every visitor shares
one bucket and one visitor's burst closes the chat for all of them. Reading ``X-Forwarded-For`` instead
is no fix on its own: any caller can send the header, and a forged value would give each request a
bucket of its own.

:func:`limiter_address` trusts the header only from a proxy listed in ``NABIZ_TRUSTED_PROXIES`` (a comma
list of addresses or CIDR ranges). Empty, which is the default, keeps today's behaviour exactly: the
socket's address, header ignored. When the direct peer is a trusted proxy, the header is read from the
right, the proxies' own entries are skipped, and the first address that is not a trusted proxy is the
client; a malformed entry there ends the walk at the proxy itself. Nothing here logs an address.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

TRUSTED_PROXIES_ENV = "NABIZ_TRUSTED_PROXIES"
FORWARDED_HEADER = "x-forwarded-for"
UNKNOWN = "unknown"

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


@lru_cache(maxsize=16)
def trusted_networks(raw: str) -> tuple[Network, ...]:
    """The networks in ``raw``; an entry that is not an address or a range is skipped, never widened."""
    networks = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _trusted(address: str, networks: tuple[Network, ...]) -> bool:
    try:
        ip = ipaddress.ip_address(address.strip())
    except ValueError:
        return False
    return any(ip in network for network in networks)


def _valid(address: str) -> bool:
    try:
        ipaddress.ip_address(address)
    except ValueError:
        return False
    return True


def limiter_address(request: Any, env: Mapping[str, str] | None = None) -> str:
    """The client's address for rate limiting: the peer, or behind a trusted proxy the forwarded client."""
    env = os.environ if env is None else env
    peer = request.client.host if getattr(request, "client", None) else UNKNOWN
    networks = trusted_networks(env.get(TRUSTED_PROXIES_ENV) or "")
    if not networks or not _trusted(peer, networks):
        return peer
    header = ",".join(request.headers.getlist(FORWARDED_HEADER)) if hasattr(request.headers, "getlist") else ""
    header = header or request.headers.get(FORWARDED_HEADER, "")
    for hop in reversed([part.strip() for part in header.split(",") if part.strip()]):
        if not _valid(hop):
            return peer
        if not _trusted(hop, networks):
            return hop
    return peer
