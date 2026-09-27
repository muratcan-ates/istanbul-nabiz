"""Authorization-code + PKCE OIDC with signed ID-token verification."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import Response

from nabiz.console.identity.providers import Provider
from nabiz.console.sessions import SessionStore

_SHA256_DER = bytes.fromhex("3031300d060960864801650304020105000420")
LOGIN_COOKIE = "nabiz_login"


class OidcError(ValueError):
    """A provider response or callback failed verification; detail is deliberately generic."""


class LoginClosed(OidcError):
    """No configured client credentials and redirect address."""


@dataclass(frozen=True)
class Identity:
    provider: str
    subject: str
    email: str | None
    email_verified: bool


@dataclass(frozen=True)
class AuthorizationRequest:
    url: str
    browser_state: str


def set_login_cookie(response: Response, browser_state: str) -> None:
    """Bind the authorization request to the same browser that receives the callback."""
    response.set_cookie(LOGIN_COOKIE, browser_state, max_age=600, httponly=True, secure=True, samesite="lax", path="/")


def clear_login_cookie(response: Response) -> None:
    response.delete_cookie(LOGIN_COOKIE, secure=True, httponly=True, samesite="lax", path="/")


def _decode(value: str) -> bytes:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise OidcError("Giriş doğrulanamadı.") from exc
    if _encode(decoded) != value:
        raise OidcError("Giriş doğrulanamadı.")
    return decoded


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _json_part(value: str) -> dict[str, Any]:
    try:
        result = json.loads(_decode(value))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OidcError("Giriş doğrulanamadı.") from exc
    if not isinstance(result, dict):
        raise OidcError("Giriş doğrulanamadı.")
    return result


def _verify_rs256(token: str, jwks: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    parts = token.split(".")
    if len(parts) != 3 or any(len(part) > 16_384 for part in parts):
        raise OidcError("Giriş doğrulanamadı.")
    header, claims = _json_part(parts[0]), _json_part(parts[1])
    if header.get("alg") != "RS256" or header.get("typ", "JWT") != "JWT" or not isinstance(header.get("kid"), str):
        raise OidcError("Giriş doğrulanamadı.")
    keys = jwks.get("keys")
    if not isinstance(keys, list):
        raise OidcError("Giriş doğrulanamadı.")
    key = next((item for item in keys if isinstance(item, dict) and item.get("kid") == header["kid"]
                and item.get("kty") == "RSA" and item.get("use", "sig") == "sig"), None)
    if key is None:
        raise OidcError("Giriş doğrulanamadı.")
    try:
        modulus = int.from_bytes(_decode(key["n"]), "big")
        exponent = int.from_bytes(_decode(key["e"]), "big")
        signature = int.from_bytes(_decode(parts[2]), "big")
        length = (modulus.bit_length() + 7) // 8
        digest = _SHA256_DER + hashlib.sha256(f"{parts[0]}.{parts[1]}".encode("ascii")).digest()
        expected = b"\x00\x01" + b"\xff" * (length - len(digest) - 3) + b"\x00" + digest
        valid = length >= 256 and exponent >= 3 and exponent % 2 == 1 and signature < modulus
        valid = valid and secrets.compare_digest(pow(signature, exponent, modulus).to_bytes(length, "big"), expected)
    except (KeyError, ValueError, TypeError, OverflowError) as exc:
        raise OidcError("Giriş doğrulanamadı.") from exc
    if not valid:
        raise OidcError("Giriş doğrulanamadı.")
    return header, claims


class OidcClient:
    """A provider adapter. The caller owns the httpx client and the durable flow store."""

    def __init__(self, provider: Provider, sessions: SessionStore, client: httpx.Client, *, clock: Any = time.time) -> None:
        self.provider = provider
        self.sessions = sessions
        self.client = client
        self.clock = clock

    def begin(self) -> AuthorizationRequest:
        if not self.provider.enabled:
            raise LoginClosed("Giriş kapalı.")
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = _encode(hashlib.sha256(verifier.encode("ascii")).digest())
        self.sessions.put_flow(state, self.provider.name, nonce, verifier, now=int(self.clock()))
        query = urlencode({
            "response_type": "code", "client_id": self.provider.client_id,
            "redirect_uri": self.provider.redirect_uri, "scope": self.provider.scope,
            "state": state, "nonce": nonce, "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        return AuthorizationRequest(f"{self.provider.authorization_endpoint}?{query}", state)

    def finish(self, *, state: str, code: str, browser_state: str | None) -> Identity:
        if not self.provider.enabled:
            raise LoginClosed("Giriş kapalı.")
        if not browser_state or not secrets.compare_digest(state, browser_state):
            raise OidcError("Giriş doğrulanamadı.")
        flow = self.sessions.take_flow(state, self.provider.name, now=int(self.clock()))
        if flow is None or not code or len(code) > 4096:
            raise OidcError("Giriş doğrulanamadı.")
        try:
            response = self.client.post(self.provider.token_endpoint, data={
                "grant_type": "authorization_code", "code": code, "client_id": self.provider.client_id,
                "client_secret": self.provider.client_secret, "redirect_uri": self.provider.redirect_uri,
                "code_verifier": flow.verifier,
            }, timeout=10)
            response.raise_for_status()
            token = response.json().get("id_token")
            if not isinstance(token, str):
                raise OidcError("Giriş doğrulanamadı.")
            keys_response = self.client.get(self.provider.jwks_uri, timeout=10)
            keys_response.raise_for_status()
            _, claims = _verify_rs256(token, keys_response.json())
        except (httpx.HTTPError, ValueError, KeyError, AttributeError) as exc:
            raise OidcError("Giriş doğrulanamadı.") from exc
        self._check_claims(claims, flow.nonce)
        email = claims.get("email")
        if email is not None and (not isinstance(email, str) or "@" not in email or len(email) > 254):
            raise OidcError("Giriş doğrulanamadı.")
        verified = claims.get("email_verified") is True
        if self.provider.name == "google" and (not email or not verified):
            raise OidcError("Giriş doğrulanamadı.")
        return Identity(self.provider.name, claims["sub"], email, verified)

    def _check_claims(self, claims: dict[str, Any], nonce: str) -> None:
        now = int(self.clock())
        audience = claims.get("aud")
        valid_audience = audience == self.provider.client_id or (
            isinstance(audience, list) and self.provider.client_id in audience and claims.get("azp") == self.provider.client_id
        )
        if (claims.get("iss") != self.provider.issuer or not valid_audience or claims.get("nonce") != nonce
                or not isinstance(claims.get("sub"), str) or not claims["sub"] or len(claims["sub"]) > 255
                or type(claims.get("exp")) is not int or claims["exp"] <= now
                or type(claims.get("iat")) is not int or claims["iat"] > now + 60):
            raise OidcError("Giriş doğrulanamadı.")
