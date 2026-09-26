"""The page half of DECISIONS #36: the example band on every sign-in, the quota strip's sentence,
the identity headers, and the wiring in index.html, kvkk.html and the service worker."""

from __future__ import annotations

import json
import re

from test_static_a11y import STATIC, node_json

from nabiz.console.accounts import EXAMPLE_BAND, EXAMPLE_SMS_CODE, PROVIDERS

VIEW = {"view": "js/account_view.js"}


def providers() -> list[dict]:
    return [{"key": key, **value, "example": True, "band": EXAMPLE_BAND} for key, value in PROVIDERS.items()]


def test_every_example_sign_in_carries_the_band_and_says_it_is_an_example(tmp_path) -> None:
    cards = node_json(
        tmp_path,
        VIEW,
        f"console.log(JSON.stringify({json.dumps(providers())}.map((p) => view.providerCard(p, '{EXAMPLE_SMS_CODE}'))));",
    )
    assert len(cards) == 3
    for card, provider in zip(cards, PROVIDERS.values(), strict=True):
        assert EXAMPLE_BAND in card and "(örnek)" in provider["label"] and provider["label"] in card
        assert "Doğrulama e-postası gönderilmez" in card
    sms = cards[1]
    assert f"Örnek kod: <b>{EXAMPLE_SMS_CODE}</b>" in sms and "SMS gönderilmez" in sms and "Telefon numarası sorulmaz" in sms
    assert "sms_code" not in cards[0] and "sms_code" not in cards[2]
    assert re.search(r'placeholder="[^"@]+@example\.com"', cards[0]), "a placeholder address uses the RFC 2606 domain"
    # One source of the band text: the page's copy equals the server's.
    assert node_json(tmp_path, VIEW, "console.log(JSON.stringify(view.EXAMPLE_BAND));") == EXAMPLE_BAND


def test_the_signed_in_view_repeats_the_band_and_offers_one_tap_delete(tmp_path) -> None:
    view = {"account": {"provider_label": "İBB hesabı ile giriş (örnek)", "email": "x", "tier": "ibb"}, "band": EXAMPLE_BAND}
    html = node_json(tmp_path, VIEW, f"console.log(JSON.stringify(view.signedInView({json.dumps(view)})));")
    assert EXAMPLE_BAND in html and 'id="acct-delete"' in html and "Hesabımı ve verilerimi sil" in html


def test_the_quota_strip_says_what_is_left_and_that_emergencies_stay_open(tmp_path) -> None:
    statuses = [
        {"questions_left": 14, "questions_limit": 20, "model_open": True, "has_account": False, "tier_label": "Hesapsız"},
        {"questions_left": 0, "questions_limit": 20, "model_open": False, "has_account": False, "tier_label": "Hesapsız"},
        {"questions_left": 99, "questions_limit": 150, "model_open": True, "has_account": True, "tier_label": "Örnek İBB"},
    ]
    texts = node_json(tmp_path, VIEW, f"console.log(JSON.stringify({json.dumps(statuses)}.map(view.quotaText)));")
    assert texts[0] == "Bugün kalan: 14/20 soru · daha fazlası için hesap bağla"
    assert "kural yoluyla" in texts[1] and "112" in texts[1] and "153" in texts[1]
    assert texts[2] == "Bugün kalan: 99/150 soru · Örnek İBB"


def test_identity_headers_go_only_to_the_routes_that_need_them(tmp_path) -> None:
    body = (
        "const store = new Map(); globalThis.window = {localStorage: {getItem: (k) => store.get(k) ?? null,"
        " setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k),"
        " get length() { return store.size; }, key: (i) => [...store.keys()][i]}};"
        "id.writeAccount({token: 'tok'}); store.set('nabiz-theme', 'dark'); store.set('other', '1');"
        "const out = {chat: id.identityHeaders('/api/chat?lang=tr'), brief: id.identityHeaders('/api/brief'),"
        " again: id.identityHeaders('/api/quota')};"
        "out.cleared = id.clearDeviceData(); out.left = [...store.keys()];"
        "console.log(JSON.stringify(out));"
    )
    out = node_json(tmp_path, {"id": "js/identity.js"}, body)
    assert set(out["chat"]) == {"X-Nabiz-Device", "X-Nabiz-Account"} and out["chat"]["X-Nabiz-Account"] == "tok"
    assert (
        re.fullmatch(r"[0-9a-f]{32}", out["chat"]["X-Nabiz-Device"])
        and out["again"]["X-Nabiz-Device"] == out["chat"]["X-Nabiz-Device"]
    )
    assert out["brief"] == {}, "the city cards never carry the device id"
    assert out["cleared"] == 3 and out["left"] == ["other"], "every nabiz key goes, nothing else"


def test_the_page_kvkk_and_worker_know_the_new_parts() -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    for needle in ('id="quota-strip"', 'id="hesap"', 'id="takip"', 'id="acct-body"', 'id="follow-list"', "/js/account.js",
                   "/js/follow.js", "/js/quota_strip.js", "/css/account.css", 'href="#takip"'):  # fmt: skip
        assert needle in index, needle
    kvkk = (STATIC / "kvkk.html").read_text(encoding="utf-8")
    for needle in ('id="kvkk-hesap"', "nabiz.device.v1", "nabiz.account.v1", "nabiz.follows.v1", "12 ay", "açık rıza",
                   "Hesabımı ve verilerimi sil", EXAMPLE_BAND, "Azure Communication Services"):  # fmt: skip
        assert needle in kvkk, needle
    chat = (STATIC / "js" / "chat.js").read_text(encoding="utf-8")
    assert "nabiz:follow-suggestion" in chat and "nabiz:follow-suggestion" in (STATIC / "js" / "follow.js").read_text(
        encoding="utf-8"
    )
    follow = (STATIC / "js" / "follow.js").read_text(encoding="utf-8")
    assert "const DEVICE_LIMIT = 3;" in follow and "#takibi-birak=" in follow, "the unsubscribe token rides in the fragment"
