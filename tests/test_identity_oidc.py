"""No-network OIDC code flow, PKCE and signed ID token checks."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import random
from functools import lru_cache
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import Response

from nabiz.console.identity import LoginClosed, OidcClient, OidcError, google, microsoft, set_login_cookie
from nabiz.console.sessions import SessionStore


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


@lru_cache(maxsize=1)
def _test_key() -> tuple[int, int]:
    """Generate a synthetic RSA test key with the standard library, without an extra dependency."""
    rng = random.Random(13)

    def prime() -> int:
        while True:
            candidate = rng.getrandbits(1024) | (1 << 1023) | 1
            if any(candidate % small == 0 for small in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31)):
                continue
            odd = candidate - 1
            shifts = 0
            while odd % 2 == 0:
                odd //= 2
                shifts += 1
            if all(pow(base, candidate - 1, candidate) == 1 and
                   (pow(base, odd, candidate) == 1 or any(
                       pow(base, odd * (2 ** step), candidate) == candidate - 1 for step in range(shifts)
                   )) for base in (2, 3, 5, 7, 11, 13, 17, 19)):
                return candidate

    while True:
        p, q = prime(), prime()
        modulus = p * q
        phi = (p - 1) * (q - 1)
        if modulus.bit_length() == 2048 and math.gcd(65537, phi) == 1:
            return modulus, pow(65537, -1, phi)


def signed_token(private: tuple[int, int], claims: dict, *, kid: str = "test") -> str:

    head = b64(json.dumps({"alg": "RS256", "typ": "JWT", "kid": kid}).encode())
    body = b64(json.dumps(claims).encode())
    message = f"{head}.{body}".encode()
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(message).digest()
    envelope = b"\x00\x01" + b"\xff" * (256 - len(digest_info) - 3) + b"\x00" + digest_info
    signature = pow(int.from_bytes(envelope, "big"), private[1], private[0]).to_bytes(256, "big")
    return f"{head}.{body}.{b64(signature)}"


def test_unconfigured_login_is_closed_without_network(tmp_path) -> None:
    calls = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: calls.append(request))) as http:
        client = OidcClient(google(), SessionStore(tmp_path / "sessions.sqlite"), http)
        with pytest.raises(LoginClosed, match="Giriş kapalı"):
            client.begin()
        with pytest.raises(LoginClosed):
            client.finish(state="wrong", code="wrong", browser_state="wrong")
    assert calls == []


@pytest.mark.parametrize("factory", [google, microsoft])
def test_auth_code_pkce_and_signed_identity(factory, tmp_path) -> None:
    provider = factory(client_id="test-client", client_secret="server-only", redirect_uri="https://nabiz.example/callback")
    private = _test_key()
    jwks = {"keys": [{"kid": "test", "kty": "RSA", "use": "sig", "n": b64(private[0].to_bytes(256, "big")),
                      "e": b64((65537).to_bytes(3, "big"))}]}
    flow = {}
    claims = {}
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/token"):
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["authorization_code"]
            assert form["client_secret"] == ["server-only"]
            assert form["code_verifier"] == [flow["verifier"]]
            return httpx.Response(200, json={"id_token": signed_token(private, claims)})
        return httpx.Response(200, json=jwks)

    sessions = SessionStore(tmp_path / "sessions.sqlite")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = OidcClient(provider, sessions, http, clock=lambda: 1_000)
        attempt = client.begin()
        query = parse_qs(urlsplit(attempt.url).query)
        assert query["scope"] == ["openid email profile"]
        assert query["code_challenge_method"] == ["S256"]
        assert "Gmail" not in attempt.url and "Calendars" not in attempt.url
        state = query["state"][0]
        response = Response()
        set_login_cookie(response, attempt.browser_state)
        assert "HttpOnly" in response.headers["set-cookie"] and "Secure" in response.headers["set-cookie"]
        assert attempt.browser_state == state
        saved = sessions.take_flow(state, provider.name, now=1_000)
        assert saved is not None
        flow["verifier"] = saved.verifier
        assert query["code_challenge"] == [b64(hashlib.sha256(saved.verifier.encode()).digest())]
        sessions.put_flow(state, provider.name, saved.nonce, saved.verifier, now=1_000)
        claims.update({"iss": provider.issuer, "aud": "test-client", "sub": "user-1", "nonce": saved.nonce,
                       "exp": 2_000, "iat": 900, "email": "test@example.org", "email_verified": True})
        identity = client.finish(state=state, code="server-code", browser_state=attempt.browser_state)
        assert identity.provider == provider.name and identity.subject == "user-1"
        assert identity.email == "test@example.org" and identity.email_verified
        with pytest.raises(OidcError):
            client.finish(state=state, code="server-code", browser_state=attempt.browser_state)
    assert len(calls) == 2


@pytest.mark.parametrize("change", ["nonce", "issuer", "audience", "expired", "signature"])
def test_bad_id_token_is_refused(change, tmp_path) -> None:
    provider = google(client_id="id", client_secret="secret", redirect_uri="http://localhost:8090/callback")
    private = _test_key()
    jwks = {"keys": [{"kid": "test", "kty": "RSA", "n": b64(private[0].to_bytes(256, "big")),
                      "e": b64((65537).to_bytes(3, "big"))}]}
    claims = {"iss": provider.issuer, "aud": "id", "sub": "u", "exp": 2_000, "iat": 900,
              "email": "test@example.org", "email_verified": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            token = signed_token(private, claims)
            if change == "signature":
                token = token[:-1] + ("A" if token[-1] != "A" else "B")
            return httpx.Response(200, json={"id_token": token})
        return httpx.Response(200, json=jwks)

    sessions = SessionStore(tmp_path / "s.sqlite")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = OidcClient(provider, sessions, http, clock=lambda: 1_000)
        state = client.begin().browser_state
        saved = sessions.take_flow(state, "google", now=1_000)
        assert saved is not None
        sessions.put_flow(state, "google", saved.nonce, saved.verifier, now=1_000)
        claims["nonce"] = saved.nonce
        if change == "nonce":
            claims["nonce"] = "different"
        if change == "issuer":
            claims["iss"] = "https://wrong.invalid"
        if change == "audience":
            claims["aud"] = "wrong"
        if change == "expired":
            claims["exp"] = 999
        with pytest.raises(OidcError):
            client.finish(state=state, code="code", browser_state=state)


def test_wrong_state_and_expired_flow_are_refused_before_exchange(tmp_path) -> None:
    sent = []
    provider = google(client_id="id", client_secret="secret", redirect_uri="http://localhost:8090/callback")
    with httpx.Client(transport=httpx.MockTransport(lambda request: sent.append(request))) as http:
        client = OidcClient(provider, SessionStore(tmp_path / "s.sqlite"), http, clock=lambda: 1_000)
        state = client.begin().browser_state
        with pytest.raises(OidcError):
            client.finish(state=state, code="code", browser_state="other-browser")
        with pytest.raises(OidcError):
            client.finish(state=state, code="code", browser_state=None)
        with pytest.raises(OidcError):
            client.finish(state="wrong", code="code", browser_state="wrong")
        client.clock = lambda: 1_601
        with pytest.raises(OidcError):
            client.finish(state=state, code="code", browser_state=state)
    assert sent == []


def test_provider_rejects_wrong_pkce_verifier(tmp_path) -> None:
    provider = google(client_id="id", client_secret="secret", redirect_uri="http://localhost:8090/callback")
    challenge = ""

    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        actual = b64(hashlib.sha256(form["code_verifier"][0].encode()).digest())
        return httpx.Response(400 if actual != challenge else 200, json={"error": "invalid_grant"})

    sessions = SessionStore(tmp_path / "s.sqlite")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = OidcClient(provider, sessions, http, clock=lambda: 1_000)
        attempt = client.begin()
        challenge = parse_qs(urlsplit(attempt.url).query)["code_challenge"][0]
        flow = sessions.take_flow(attempt.browser_state, "google", now=1_000)
        assert flow is not None
        sessions.put_flow(attempt.browser_state, "google", flow.nonce, "wrong-verifier", now=1_000)
        with pytest.raises(OidcError):
            client.finish(state=attempt.browser_state, code="code", browser_state=attempt.browser_state)
