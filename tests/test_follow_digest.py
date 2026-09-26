"""Followed topics, the daily digest and the e-mail senders (DECISIONS #36).

İBB is the recorded fixtures (M7 carries a works notice, Etiler a recorded lift fault); the account
file and the outbox live in ``tmp_path``; no e-mail leaves the test.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib.util
import json
import pathlib
import sys
from collections.abc import Iterator

import httpx
import pytest
from conftest import offline_settings, refuse_network
from test_console_chat import events
from test_quota_accounts import DEVICE, address, make_client, sign_in

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.console.accounts import AccountStore
from nabiz.console.digest import check_unsubscribe, run_digest, unsubscribe_token
from nabiz.console.email_sender import AcsEmailSender, Email, OutboxEmailSender, sender_from_env
from nabiz.console.follow import NO_SOURCE, suggest_follow, topic_from
from nabiz.console.follow_eval import INDEX_MISSING, NO_STATION, evaluate_topic

MORNING = dt.datetime(2026, 9, 26, 6, 0, tzinfo=dt.UTC)


@pytest.fixture(scope="module")
def nabiz() -> Iterator[Nabiz]:
    yield Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)), cache=TTLCache(), settings=offline_settings()
        )
    )


# -- what a follow request becomes -----------------------------------------------------------------
@pytest.mark.parametrize(
    ("message", "kind", "value"),
    [
        ("M2 hattını takip et", "metro_line", "M2"),
        ("M1A'yı takip etmek istiyorum", "metro_line", "M1A"),
        ("Etiler asansörünü takip et", "station", "Etiler"),
        ("Kadıköy metro istasyonunu takip etmek istiyorum", "station", "Kadıköy"),
        ("500T hattını takip et", "bus_line", "500T"),
        ("Kreş başvurularını takip et", "knowledge", "Kreş başvurularını"),
        ("Please follow M4 for me", "metro_line", "M4"),
    ],
)
def test_a_follow_request_becomes_one_topic(message: str, kind: str, value: str) -> None:
    topic = suggest_follow(message)
    assert topic is not None and (topic.kind, topic.value) == (kind, value) and topic.supported
    assert topic.as_suggestion()["prompt"].startswith("Takip edilecek konu: ")


@pytest.mark.parametrize("message", ["Kadıköy su kesintilerini takip et", "İGDAŞ doğalgaz kesintisini takip etmek istiyorum"])
def test_a_topic_with_no_source_is_said_honestly(message: str) -> None:
    topic = suggest_follow(message)
    assert topic is not None and topic.supported is False
    suggestion = topic.as_suggestion()
    assert NO_SOURCE in suggestion["prompt"] and suggestion["email"] is False


@pytest.mark.parametrize(
    "message", ["M2 çalışıyor mu?", "Etiler asansörü çalışıyor mu?", "takip et", "41.0082, 28.9784 takip et"]
)
def test_no_cue_no_topic_and_never_a_coordinate(message: str) -> None:
    assert suggest_follow(message) is None
    with pytest.raises(ValueError):
        topic_from("knowledge", "41.0082, 28.9784")


def test_the_chat_offers_a_follow_after_its_answer_and_not_on_an_emergency(nabiz: Nabiz, tmp_path: pathlib.Path) -> None:
    client, _ = make_client(nabiz, tmp_path)
    with client:
        response = client.post(
            "/api/chat", json={"message": "M2 hattını takip etmek istiyorum"}, headers={"X-Nabiz-Device": DEVICE}
        )
        final = events(response.text)[-1][1]
        water = events(client.post("/api/chat", json={"message": "Kadıköy su kesintilerini takip et"}).text)[-1][1]
    suggestion = final["follow_suggestion"]
    assert suggestion["kind"] == "metro_line" and suggestion["value"] == "M2" and suggestion["supported"] is True
    assert suggestion["prompt"] == "Takip edilecek konu: M2 hattı: duyurular ve asansör arızaları"
    assert water["follow_suggestion"]["supported"] is False


# -- evaluation ------------------------------------------------------------------------------------
async def test_topics_read_todays_data_and_name_what_they_cannot(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", "data/knowledge/not-built-here.db")
    m7 = await evaluate_topic(nabiz, topic_from("metro_line", "M7"))
    etiler = await evaluate_topic(nabiz, topic_from("station", "Etiler"))
    nowhere = await evaluate_topic(nabiz, topic_from("station", "Hiçyokköy"))
    archive = await evaluate_topic(nabiz, topic_from("knowledge", "kreş"))
    assert any("M7" in text and "Metro İstanbul duyurusu" in text for text in m7.active.values())
    assert any("Etiler" in text and "Arıza" in text for text in etiler.active.values())
    assert nowhere.unavailable == NO_STATION and archive.unavailable == INDEX_MISSING


def test_the_status_route_is_stateless_and_bounded(nabiz: Nabiz, tmp_path: pathlib.Path) -> None:
    client, app = make_client(nabiz, tmp_path)
    with client:
        ok = client.post("/api/follows/status", json={"topics": [{"kind": "metro_line", "value": "M7"}]}).json()
        many = client.post("/api/follows/status", json={"topics": [{"kind": "metro_line", "value": "M1"}] * 11})
    assert ok["topics"][0]["active"] and ok["topics"][0]["fingerprint"]
    assert many.status_code == 422
    assert not (tmp_path / "accounts.sqlite").exists() or app.state.accounts is not None


# -- the digest ------------------------------------------------------------------------------------
def follow_all(store: AccountStore, account_id: str) -> dict[str, str]:
    ids = {}
    for kind, value in (("metro_line", "M7"), ("station", "Etiler"), ("bus_line", "500T")):
        topic = topic_from(kind, value)
        ids[kind] = store.add_follow(account_id, kind=topic.kind, value=topic.value, label=topic.label)["id"]
    return ids


async def test_the_digest_mails_only_essential_changes_once_a_day(nabiz: Nabiz, tmp_path: pathlib.Path) -> None:
    store = AccountStore(tmp_path / "a.sqlite")
    account, _ = store.create(email=address(), provider="ibb", consent=True)
    ids = follow_all(store, account.id)
    outbox = OutboxEmailSender(tmp_path / "outbox")

    first = await run_digest(store, nabiz, outbox, now=MORNING, outbox=outbox)
    again = await run_digest(store, nabiz, outbox, now=MORNING + dt.timedelta(hours=2), outbox=outbox)
    tomorrow = await run_digest(store, nabiz, outbox, now=MORNING + dt.timedelta(days=1), outbox=outbox)
    assert (first.emails, again.emails, again.skipped_today, tomorrow.emails) == (1, 0, 1, 0), "no change, no e-mail"

    [mail] = outbox.previews(account.id)
    text = mail["text"]
    assert mail["kind"] == "digest" and mail["sent"] is False
    assert "Resmî İBB hizmeti değildir" in text and "English" in text
    assert "Metro İstanbul duyurusu" in text and "Etiler" in text, "each line names its source and age"
    assert "500T" not in text, "a bus line's bunching is not worth an e-mail"
    assert text.count("Takibi bırak: ") == 2 and "#takibi-birak=" in text and "#hesap" in text

    store.set_follow_state(ids["station"], {"lift:old": "Etiler (M6): eski arıza kaydı"})
    later = await run_digest(store, nabiz, outbox, now=MORNING + dt.timedelta(days=2), outbox=outbox)
    newest = outbox.previews(account.id)[0]["text"]
    assert later.emails == 1 and "Giderildi: Etiler (M6): eski arıza kaydı" in newest and "Yeni: " in newest


async def test_the_digest_purges_a_year_idle_account_and_its_outbox(nabiz: Nabiz, tmp_path: pathlib.Path) -> None:
    now = [MORNING]
    store = AccountStore(tmp_path / "a.sqlite", clock=lambda: now[0])
    account, _ = store.create(email=address(), provider="google", consent=True)
    outbox = OutboxEmailSender(tmp_path / "outbox")
    outbox.send(Email(address(), "s", "t", "verify", account.id))
    now[0] += dt.timedelta(days=400)
    report = await run_digest(store, nabiz, outbox, now=now[0], outbox=outbox)
    assert report.purged == 1 and outbox.previews(account.id) == []


def test_the_unsubscribe_link_stops_one_follow_only(nabiz: Nabiz, tmp_path: pathlib.Path) -> None:
    client, app = make_client(nabiz, tmp_path)
    with client:
        headers = {"X-Nabiz-Account": sign_in(client)["token"]}
        first = client.post("/api/account/follows", json={"kind": "metro_line", "value": "M7"}, headers=headers).json()["follow"]
        client.post("/api/account/follows", json={"kind": "station", "value": "Etiler"}, headers=headers)
        secret = app.state.accounts.secret()
        link = unsubscribe_token(secret, first["id"])
        forged = client.post("/api/follow/unsubscribe", json={"token": first["id"] + ".0000"})
        done = client.post("/api/follow/unsubscribe", json={"token": link})
        left = client.get("/api/account", headers=headers).json()["follows"]
    assert check_unsubscribe(secret, link) == first["id"] and check_unsubscribe(secret, "x.y") is None
    assert forged.status_code == 404 and done.status_code == 200
    assert [follow["value"] for follow in left] == ["Etiler"]


# -- the senders -----------------------------------------------------------------------------------
def test_the_outbox_writes_json_and_says_it_sent_nothing(tmp_path: pathlib.Path) -> None:
    outbox = OutboxEmailSender(tmp_path / "outbox")
    result = outbox.send(Email(address(), "Konu", "Metin", "digest", "acc1"))
    [path] = list((tmp_path / "outbox").glob("*.json"))
    record = json.loads(path.read_text(encoding="utf-8"))
    assert result.delivered is False and result.sender == "outbox"
    assert record["to"] == address() and record["sent"] is False and "gönderilmedi" in record["note"]
    assert outbox.purge_older_than(now=dt.datetime.now(dt.UTC) + dt.timedelta(days=31)) == 1


def test_acs_is_off_without_both_variables_and_never_imported_early() -> None:
    assert AcsEmailSender.from_env({}) is None
    assert AcsEmailSender.from_env({"NABIZ_ACS_CONNECTION_STRING": "set"}) is None
    assert AcsEmailSender.from_env({"NABIZ_ACS_SENDER": "set"}) is None
    both = {"NABIZ_ACS_CONNECTION_STRING": "set", "NABIZ_ACS_SENDER": "set"}
    assert isinstance(sender_from_env(deliver=False, env=both), OutboxEmailSender), "the outbox unless delivery is asked"
    assert isinstance(sender_from_env(deliver=True, env={}), OutboxEmailSender)
    assert isinstance(sender_from_env(deliver=True, env=both), AcsEmailSender)
    assert "azure.communication.email" not in sys.modules


def test_the_digest_script_runs_offline_into_the_outbox(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("NABIZ_ACCOUNTS_DB", str(tmp_path / "a.sqlite"))
    monkeypatch.setenv("NABIZ_OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.delenv("NABIZ_ACS_CONNECTION_STRING", raising=False)
    store = AccountStore(tmp_path / "a.sqlite")
    account, _ = store.create(email=address(), provider="ibb", consent=True)
    topic = topic_from("metro_line", "M7")
    store.add_follow(account.id, kind=topic.kind, value=topic.value, label=topic.label)
    store.close()
    spec = importlib.util.spec_from_file_location(
        "notify_digest", pathlib.Path(__file__).parents[1] / "scripts" / "notify_digest.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module,
        "Nabiz",
        lambda ctx: Nabiz(
            SourceContext.create(
                client=PoliteClient(transport=httpx.MockTransport(refuse_network)), cache=TTLCache(), settings=offline_settings()
            )
        ),
    )
    assert asyncio.run(module.main([])) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["emails"] == 1 and summary["sender"] == "outbox"
    assert asyncio.run(module.main(["--deliver"])) == 2, "no ACS configured: nothing is sent"
    assert len(list((tmp_path / "outbox").glob("*.json"))) == 1
