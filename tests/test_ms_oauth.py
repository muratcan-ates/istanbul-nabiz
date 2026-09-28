from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from nabiz.console.ms_oauth import MemoryTokenStore, OAuthConfig, exchange_code, new_authorization


def test_oauth_pkce_and_state_with_mock_transport():
    config = OAuthConfig("public-client", "http://localhost/callback")
    attempt = new_authorization(config)
    query = parse_qs(urlparse(attempt.url).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["offline_access Calendars.ReadWrite"]
    assert attempt.verifier not in attempt.url
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path.endswith("/token")
        assert b"code_verifier=" in request.content
        return httpx.Response(200, json={"access_token": "fake-token"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            exchange_code(config, "code", "wrong", attempt, client)
        assert exchange_code(config, "code", attempt.state, attempt, client) == "fake-token"
    assert len(calls) == 1
    vault = MemoryTokenStore()
    vault.put("owner", "fake-token")
    assert vault.get("owner") == "fake-token"
    assert vault.get("other") is None


def test_oauth_disabled_without_settings(monkeypatch):
    monkeypatch.delenv("NABIZ_MS_CLIENT_ID", raising=False)
    monkeypatch.delenv("NABIZ_MS_REDIRECT_URI", raising=False)
    assert OAuthConfig.from_env() is None
