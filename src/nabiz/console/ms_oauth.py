"""Microsoft authorization-code PKCE adapter; token persistence belongs to the session layer."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

import httpx

AUTHORITY = "https://login.microsoftonline.com/common/oauth2/v2.0"
SCOPE = "offline_access Calendars.ReadWrite"


@dataclass(frozen=True)
class OAuthConfig:
    client_id: str
    redirect_uri: str

    @classmethod
    def from_env(cls) -> OAuthConfig | None:
        client_id = os.environ.get("NABIZ_MS_CLIENT_ID", "")
        redirect_uri = os.environ.get("NABIZ_MS_REDIRECT_URI", "")
        if not client_id or not redirect_uri:
            return None
        return cls(client_id, redirect_uri)


@dataclass(frozen=True)
class OAuthAttempt:
    url: str
    state: str
    verifier: str


class TokenStore(Protocol):
    def get(self, owner_id: str) -> str | None: ...

    def put(self, owner_id: str, access_token: str) -> None: ...


class MemoryTokenStore:
    """Test adapter only: values vanish with the process."""

    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}

    def get(self, owner_id: str) -> str | None:
        return self._tokens.get(owner_id)

    def put(self, owner_id: str, access_token: str) -> None:
        self._tokens[owner_id] = access_token


def new_authorization(config: OAuthConfig) -> OAuthAttempt:
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    query = urlencode({
        "client_id": config.client_id,
        "response_type": "code",
        "redirect_uri": config.redirect_uri,
        "response_mode": "query",
        "scope": SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return OAuthAttempt(f"{AUTHORITY}/authorize?{query}", state, verifier)


def exchange_code(
    config: OAuthConfig, code: str, returned_state: str, attempt: OAuthAttempt, client: httpx.Client,
) -> str:
    if not secrets.compare_digest(returned_state, attempt.state) or not code:
        raise ValueError("Microsoft bağlantı doğrulaması başarısız.")
    response = client.post(
        f"{AUTHORITY}/token",
        data={
            "client_id": config.client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.redirect_uri,
            "code_verifier": attempt.verifier,
            "scope": SCOPE,
        },
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError("Microsoft erişim jetonu alınamadı.")
    return token
