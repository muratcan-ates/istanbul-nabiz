"""Durable, revocable sessions and one-use login flow records."""

from fastapi import Response

from nabiz.console.sessions import COOKIE, SessionStore, clear_session_cookie, set_session_cookie


def test_session_persists_and_logout_revokes(tmp_path) -> None:
    path = tmp_path / "sessions.sqlite"
    first = SessionStore(path)
    token = first.create("account-a", "google", "provider-sub", now=100)
    assert token not in path.read_bytes().decode("latin1")
    second = SessionStore(path)
    assert second.get(token, now=101).account_id == "account-a"
    assert second.get(token, now=100 + 12 * 3600) is None
    assert second.revoke(token) is True
    assert first.get(token, now=101) is None


def test_account_revocation_is_scoped_and_cookie_is_protected(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions.sqlite")
    a = store.create("a", "google", "a-sub", now=100)
    b = store.create("b", "google", "b-sub", now=100)
    assert store.revoke_account("a") == 1
    assert store.get(a, now=101) is None and store.get(b, now=101) is not None
    response = Response()
    set_session_cookie(response, b)
    header = response.headers["set-cookie"]
    assert COOKIE in header and "httponly" in header.lower()
    assert "secure" in header.lower() and "samesite=lax" in header.lower()
    clear_session_cookie(response)
    assert any("Max-Age=0" in value for value in response.headers.getlist("set-cookie"))


def test_flow_is_one_use_and_provider_bound(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions.sqlite")
    store.put_flow("state", "google", "nonce", "verifier", now=100)
    assert store.take_flow("state", "microsoft", now=101) is None
    assert store.take_flow("state", "google", now=101) is None
    store.put_flow("other", "google", "nonce", "verifier", now=100)
    assert store.take_flow("other", "google", now=700) is None
