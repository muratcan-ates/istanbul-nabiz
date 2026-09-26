"""Quota tiers, example accounts and the chat's quota hook (DECISIONS #38).

The model is never reached: ``nabiz.agent.llm.chat`` is a scripted fake, İBB is the recorded
fixtures, the account file and the outbox live in ``tmp_path``. Example addresses use the RFC 2606
domain the ``no-personal-data`` guardrail allows.
"""

from __future__ import annotations

import datetime as dt
import logging
import pathlib
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from conftest import offline_settings, refuse_network
from fastapi.testclient import TestClient
from test_console_chat import CLOUD, FakeModel, events, reply, tool_call

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console.access import TurnLimiter
from nabiz.console.accounts import ACCOUNT_FOLLOW_LIMIT, EXAMPLE_BAND, EXAMPLE_SMS_CODE, AccountStore, ConsentRequired
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.email_sender import OutboxEmailSender
from nabiz.console.emergency_text import CARD_TEXT
from nabiz.console.quota import TIERS, MeteredGuard, QuotaBook, Tier, address_key, tiers_from_env

DOMAIN = "example.com"
DEVICE = "d3v1c3-0123456789abcdef"
EMERGENCY = "Acil ambulans lazım, biri yaralandı"


def address(name: str = "ornek") -> str:
    return f"{name}@{DOMAIN}"


@pytest.fixture(scope="module")
def nabiz() -> Iterator[Nabiz]:
    yield Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)), cache=TTLCache(), settings=offline_settings()
        )
    )


def tiers(questions: int = 3, calls: int = 60) -> dict[str, Tier]:
    return {
        "cihaz": Tier("cihaz", "Hesapsız", questions, calls),
        "eposta": Tier("eposta", "E-posta", questions * 3, calls * 3),
        "ibb": Tier("ibb", "İBB", questions * 7, calls * 7),
    }


def make_client(nabiz: Nabiz, tmp_path: pathlib.Path, *, config: llm.LlmConfig | None = None, book: QuotaBook | None = None):
    app = build_console_app(nabiz=nabiz, llm_config=config or llm.LlmConfig(), guard=SpendGuard(BudgetConfig(state_path=None)))
    app.state.quota = book or QuotaBook(tiers())
    app.state.accounts = AccountStore(tmp_path / "accounts.sqlite")
    app.state.outbox = OutboxEmailSender(tmp_path / "outbox")
    return TestClient(app), app


def chat(client: TestClient, message: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    response = client.post("/api/chat", json={"message": message}, headers={"X-Nabiz-Device": DEVICE, **(headers or {})})
    assert response.status_code == 200, response.text
    return events(response.text)[-1][1]


def sign_in(client: TestClient, provider: str = "ibb", **extra: Any) -> dict[str, Any]:
    body = {"provider": provider, "email": address(), "consent": True, **extra}
    response = client.post("/api/account/signin", json=body)
    assert response.status_code == 200, response.text
    return response.json()


# -- the quota book --------------------------------------------------------------------------------
def test_the_three_tiers_rise_and_live_in_one_table() -> None:
    assert TIERS["cihaz"].questions < TIERS["eposta"].questions < TIERS["ibb"].questions
    assert TIERS["cihaz"].model_calls < TIERS["eposta"].model_calls < TIERS["ibb"].model_calls
    env = {"NABIZ_QUOTA_ANON_QUESTIONS": "5", "NABIZ_QUOTA_IBB_MODEL_CALLS": "9", "NABIZ_QUOTA_EMAIL_QUESTIONS": "lots"}
    read = tiers_from_env(env)
    assert read["cihaz"].questions == 5 and read["ibb"].model_calls == 9
    assert read["eposta"].questions == TIERS["eposta"].questions, "a value that is not a whole number is ignored"


def test_a_device_is_counted_by_pseudonym_and_its_address_caps_a_cleared_device() -> None:
    book = QuotaBook(tiers(questions=2), salt=b"s" * 16)
    holder = book.holder(device=DEVICE, host="203.0.113.9")
    assert DEVICE not in holder.key and "203.0.113.9" not in str(holder.address)
    assert book.admit(holder) and book.admit(holder) and not book.admit(holder)
    assert book.status(holder)["questions_left"] == 0 and book.status(holder)["model_open"] is False
    # A new device id on the same address gets its own count, up to the address's shared cap.
    fresh = [book.holder(device=f"{DEVICE}{i:02d}", host="203.0.113.9") for i in range(10)]
    admitted = sum(book.admit(h) for h in fresh for _ in range(2))
    assert admitted == 2 * 5 - 2, "the address holds five devices' worth, and the first device used two"
    assert address_key("2001:db8::1") == address_key("2001:db8::2"), "IPv6 is counted by its /64"


def test_the_day_turns_over_in_istanbul_time() -> None:
    now = [dt.datetime(2026, 9, 26, 20, 59, tzinfo=dt.UTC)]
    book = QuotaBook(tiers(questions=1), clock=lambda: now[0])
    holder = book.holder(device=DEVICE, host="198.51.100.1")
    assert book.admit(holder) and not book.admit(holder)
    now[0] = dt.datetime(2026, 9, 26, 21, 1, tzinfo=dt.UTC)  # 00:01 in İstanbul
    assert book.admit(holder)


def test_the_metered_guard_only_delegates_without_a_meter() -> None:
    inner = SpendGuard(BudgetConfig(state_path=None))
    guard = MeteredGuard(inner)
    assert guard.allows("openai_compatible") and guard.reserve("openai_compatible", 6)
    guard.release("openai_compatible", 6)
    guard.record("openai_compatible", {}, 2)
    assert inner.today()["calls"] == 2 and guard.config is inner.config


# -- the chat hook ---------------------------------------------------------------------------------
def test_past_the_question_quota_the_rules_answer_and_the_model_is_closed(
    nabiz: Nabiz, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeModel(
        *[step for _ in range(3) for step in (reply(tool_calls=[tool_call("metro_status")]), reply("M7 aktarmalı."))]
    )
    monkeypatch.setattr(llm, "chat", fake)
    client, _ = make_client(nabiz, tmp_path, config=CLOUD, book=QuotaBook(tiers(questions=1)))
    with client:
        first = chat(client, "Metro hattında arıza var mı?")
        second = chat(client, "Metro hattında arıza var mı?")
    assert first["author"] == "model" and first["quota"]["model_open_this_turn"] is True
    assert first["quota"]["questions_left"] == 0 and first["quota"]["questions_limit"] == 1
    assert second["author"] == "kural" and second["quota"]["model_open_this_turn"] is False
    assert second["answer"], "the rules still answer"
    assert len(fake.calls) == 2, "the second turn never reached the model"


def test_model_calls_are_counted_per_person(nabiz: Nabiz, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeModel(
        *[step for _ in range(3) for step in (reply(tool_calls=[tool_call("metro_status")]), reply("M7 aktarmalı."))]
    )
    monkeypatch.setattr(llm, "chat", fake)
    client, _ = make_client(nabiz, tmp_path, config=CLOUD, book=QuotaBook(tiers(questions=5, calls=7)))
    with client:
        first = chat(client, "Metro hattında arıza var mı?")
        second = chat(client, "Metro hattında arıza var mı?")
    assert first["author"] == "model" and first["quota"]["model_calls_left"] == 5, "two calls made, seven allowed"
    assert second["author"] == "kural", "five left cannot hold a whole turn's six"
    assert len(fake.calls) == 2


def test_an_emergency_is_never_counted_never_limited_and_always_answered(nabiz: Nabiz, tmp_path: pathlib.Path) -> None:
    client, app = make_client(nabiz, tmp_path, book=QuotaBook(tiers(questions=1)))
    with client:
        app.state.chat_limiter = TurnLimiter(1)
        chat(client, "M2 çalışıyor mu?")
        limited = client.post("/api/chat", json={"message": "M2 çalışıyor mu?"}, headers={"X-Nabiz-Device": DEVICE})
        assert limited.status_code == 429
        final = chat(client, EMERGENCY)
        again = chat(client, EMERGENCY)
        status = client.get("/api/quota", headers={"X-Nabiz-Device": DEVICE}).json()
    assert final["emergency"] is True and final["mode"] == "redirect" and again["emergency"] is True
    assert final["quota"]["counted"] is False and "follow_suggestion" not in final
    assert status["questions_left"] == 0 and status["questions_limit"] == 1, "the emergencies took nothing"


def test_the_quota_strip_route_names_the_tier_and_what_is_left(nabiz: Nabiz, tmp_path: pathlib.Path) -> None:
    client, _ = make_client(nabiz, tmp_path, book=QuotaBook(tiers(questions=20)))
    with client:
        chat(client, "M2 çalışıyor mu?")
        anonymous = client.get("/api/quota", headers={"X-Nabiz-Device": DEVICE}).json()
        token = sign_in(client, "ibb")["token"]
        linked = client.get("/api/quota", headers={"X-Nabiz-Account": token}).json()
    assert anonymous["tier"] == "cihaz" and anonymous["questions_left"] == 19 and anonymous["has_account"] is False
    assert linked["tier"] == "ibb" and linked["questions_limit"] == 140 and linked["has_account"] is True


# -- accounts --------------------------------------------------------------------------------------
def test_without_consent_nothing_reaches_the_server(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, nabiz: Nabiz
) -> None:
    db = tmp_path / "fresh" / "accounts.sqlite"
    outbox = tmp_path / "fresh-outbox"
    monkeypatch.setenv("NABIZ_ACCOUNTS_DB", str(db))
    monkeypatch.setenv("NABIZ_OUTBOX_DIR", str(outbox))
    app = build_console_app(nabiz=nabiz, llm_config=llm.LlmConfig())
    with TestClient(app) as client:
        for body in ({"provider": "google", "email": address()}, {"provider": "google", "email": address(), "consent": False}):
            refused = client.post("/api/account/signin", json=body)
            assert refused.status_code == 400 and refused.json()["error"] == "consent_required"
    assert not db.exists() and not outbox.exists(), "no file was even opened"
    with pytest.raises(ConsentRequired):
        AccountStore(tmp_path / "direct.sqlite").create(email=address(), provider="ibb", consent=False)


def test_sign_in_is_an_example_the_sms_code_is_shown_and_nothing_is_sent(
    nabiz: Nabiz, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    client, app = make_client(nabiz, tmp_path)
    with client:
        providers = client.get("/api/account/providers").json()
        wrong = client.post("/api/account/signin", json={"provider": "istanbulkart", "email": address(), "consent": True})
        signed = sign_in(client, "istanbulkart", sms_code=EXAMPLE_SMS_CODE)
        view = client.get("/api/account", headers={"X-Nabiz-Account": signed["token"]}).json()
        outbox = client.get("/api/account/outbox", headers={"X-Nabiz-Account": signed["token"]}).json()
    labels = [p["label"] for p in providers["providers"]]
    assert labels == ["İBB hesabı ile giriş (örnek)", "İstanbulkart hesabı ile SMS girişi (örnek)", "Google ile giriş (örnek)"]
    assert all(p["band"] == EXAMPLE_BAND and p["example"] is True for p in providers["providers"])
    assert [row["tier"] for row in providers["tiers"]] == ["cihaz", "eposta", "ibb"]
    assert wrong.status_code == 400 and EXAMPLE_SMS_CODE in wrong.json()["message"]
    assert signed["verification"]["sent"] is False and signed["account"]["example"] is True
    assert view["account"]["tier"] == "ibb" and view["band"] == EXAMPLE_BAND
    assert outbox["sent"] is False and outbox["previews"][0]["kind"] == "verify" and outbox["previews"][0]["sent"] is False
    stored = app.state.accounts.by_token(signed["token"])
    assert stored is not None and stored.email == address()
    assert address() not in caplog.text and signed["token"] not in caplog.text, "no address or token in any log"


def test_one_tap_delete_removes_the_account_its_follows_and_its_outbox(nabiz: Nabiz, tmp_path: pathlib.Path) -> None:
    client, app = make_client(nabiz, tmp_path)
    with client:
        token = sign_in(client, "google")["token"]
        headers = {"X-Nabiz-Account": token}
        added = client.post("/api/account/follows", json={"kind": "metro_line", "value": "m2"}, headers=headers).json()
        assert added["follow"]["value"] == "M2" and len(added["follows"]) == 1
        assert list((tmp_path / "outbox").glob("*.json"))
        gone = client.delete("/api/account", headers=headers).json()
        after = client.get("/api/account", headers=headers)
    assert gone["deleted"] is True and gone["outbox_deleted"] == 1
    assert after.status_code == 401
    assert not list((tmp_path / "outbox").glob("*.json"))
    rows = app.state.accounts._db.execute("SELECT (SELECT COUNT(*) FROM accounts), (SELECT COUNT(*) FROM follows)").fetchone()
    assert rows == (0, 0)


def test_an_account_follows_at_most_ten_topics_and_never_a_coordinate(nabiz: Nabiz, tmp_path: pathlib.Path) -> None:
    client, _ = make_client(nabiz, tmp_path)
    with client:
        headers = {"X-Nabiz-Account": sign_in(client)["token"]}
        codes = [
            client.post("/api/account/follows", json={"kind": "bus_line", "value": f"{100 + i}T"}, headers=headers).status_code
            for i in range(ACCOUNT_FOLLOW_LIMIT + 1)
        ]
        place = client.post("/api/account/follows", json={"kind": "knowledge", "value": "41.0082, 28.9784"}, headers=headers)
        unknown = client.post("/api/account/follows", json={"kind": "metro_line", "value": "Kadıköy"}, headers=headers)
    assert codes == [200] * ACCOUNT_FOLLOW_LIMIT + [409]
    assert place.status_code in (400, 409) and unknown.status_code in (400, 409)


def test_an_unused_account_is_purged_after_a_year(tmp_path: pathlib.Path) -> None:
    now = [dt.datetime(2026, 9, 26, 9, 0, tzinfo=dt.UTC)]
    store = AccountStore(tmp_path / "a.sqlite", clock=lambda: now[0])
    account, _ = store.create(email=address(), provider="google", consent=True)
    now[0] += dt.timedelta(days=364)
    assert store.purge_inactive() == []
    now[0] += dt.timedelta(days=2)
    assert store.purge_inactive() == [account.id]


@pytest.mark.parametrize(
    ("message", "lang"),
    [
        (EMERGENCY, "tr"),
        ("Evde gaz kaçağı var, gaz kokusu geliyor", "tr"),
        ("النجدة حريق", "ar"),
        ("Вызовите скорую, человек без сознания", "ru"),
        ("Hilfe, mein Vater hat einen Herzinfarkt", "de"),
    ],
)
def test_an_emergency_in_any_card_language_passes_a_spent_quota_and_limiter(
    nabiz: Nabiz, tmp_path: pathlib.Path, message: str, lang: str
) -> None:
    """Integration of hesap-kota-takip and acil-çok-dil: with the daily quota spent and the per-minute limiter
    answering 429, an emergency in Turkish (rules) or a visitor language (the multilingual rules) still gets 200,
    the 112 card in its own language, and is not counted. The redirect's final has no text: the page draws the
    card from ``final.lang`` (``emergency_text``)."""
    client, app = make_client(nabiz, tmp_path, book=QuotaBook(tiers(questions=1)))
    with client:
        app.state.chat_limiter = TurnLimiter(1)
        chat(client, "M2 çalışıyor mu?")
        limited = client.post("/api/chat", json={"message": "M2 çalışıyor mu?"}, headers={"X-Nabiz-Device": DEVICE})
        assert limited.status_code == 429
        final = chat(client, message)
        status = client.get("/api/quota", headers={"X-Nabiz-Device": DEVICE}).json()
    assert final["emergency"] is True and final["mode"] == "redirect", final
    assert final["lang"] == lang and "112" in CARD_TEXT[lang]["call"], "the page opens the 112 card in this language"
    assert final["quota"]["counted"] is False
    assert status["questions_left"] == 0 and status["questions_limit"] == 1, "the emergency took nothing"
