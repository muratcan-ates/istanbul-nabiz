"""Görev 0-a: a model answer that tells the person to call 153 passes the numeric check.

The check (:mod:`nabiz.agent.faithfulness`) requires every number in an answer to come from a tool
result. An official help line in a call ("153'ü arayın") is a phone number, not a measurement: it is
masked out when it is on the closed list :data:`~nabiz.agent.faithfulness.OFFICIAL_LINES` and next to a
call. Any other number, an invented phone number and a line number used as a bus or a price stay checked.
Owner's decision, 30 Sep 2026: Nabız sends no one to an emergency line, so an emergency number in a call
is no longer on the list and is refused like any other unsourced number.
"""

from __future__ import annotations

import pytest
from test_console_chat import CLOUD, FakeModel, ask, client_for, nabiz, reply  # noqa: F401  (nabiz is a fixture)

from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.agent.faithfulness import OFFICIAL_LINES, check_faithfulness


@pytest.mark.parametrize(
    "answer",
    [
        "Bunun için 153'ü arayabilirsiniz.",
        "İBB Çözüm Merkezi'ni (153) arayın.",
        "You can call 153.",
    ],
)
def test_an_official_line_in_a_call_passes(answer: str) -> None:
    assert check_faithfulness(answer, None).passed


@pytest.mark.parametrize(
    ("answer", "unsupported"),
    [
        ("Acil bir durumda 112'yi arayın.", "112"),
        ("Gaz kokusu alırsanız 187'yi hemen arayın.", "187"),
        ("In an emergency, call 112.", "112"),
        ("İtfaiye için 110'u arayın.", "110"),
    ],
)
def test_an_emergency_line_in_a_call_is_an_unsourced_number(answer: str, unsupported: str) -> None:
    report = check_faithfulness(answer, None)
    assert not report.passed and unsupported in report.unsupported_texts


@pytest.mark.parametrize(
    ("answer", "unsupported"),
    [
        ("Bilgi için 0212 555 12 34 numarasını arayın.", "0212"),
        ("İBB'yi 444 99 99'dan arayabilirsiniz.", "444"),
        ("153 numaralı otobüs 5 dakikada gelir.", "153"),
        ("Bilet 153 TL.", "153"),
        ("Kadıköy'e 153 ile gidin ve inince arayın.", "153"),
    ],
)
def test_invented_numbers_and_a_line_number_outside_a_call_are_still_refused(answer: str, unsupported: str) -> None:
    report = check_faithfulness(answer, None)
    assert not report.passed and unsupported in report.unsupported_texts


def test_a_changed_amount_next_to_a_call_is_still_refused() -> None:
    evidence = [{"tariff": "İlk 1 saat 30 TL"}]
    assert check_faithfulness("İlk 1 saat 30 TL. Sorunuz için 153'ü arayın.", evidence).passed
    report = check_faithfulness("İlk 1 saat 35 TL. Sorunuz için 153'ü arayın.", evidence)
    assert report.unsupported_texts == ["35"]


def test_the_list_is_closed_and_holds_no_invented_line() -> None:
    assert OFFICIAL_LINES == ("153", "185")
    assert not check_faithfulness("444 1 999'u arayın.", None).passed, "eval/red_team.jsonl rt-38"


@pytest.mark.parametrize("answer", ["Sorunuz için 153'ü arayın.", "Bunun için 153'ü arayabilirsiniz."])
def test_the_chat_keeps_the_model_answer_and_its_label(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch, answer: str) -> None:  # noqa: F811
    fake = FakeModel(reply(answer))
    monkeypatch.setattr(llm, "chat", fake)
    with client_for(nabiz, CLOUD) as client:
        _, final = ask(client, "Kadıköy'de gece açık kütüphane var mı?")
    assert len(fake.calls) == 1, "no repair call"
    assert final["author"] == "model" and final["answer"].startswith(answer)


def test_the_chat_still_drops_an_invented_number(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    invented = "Bilgi için 0212 555 12 34 numarasını arayın."
    monkeypatch.setattr(llm, "chat", FakeModel(reply(invented), reply(invented)))
    with client_for(nabiz, CLOUD) as client:
        _, final = ask(client, "Kadıköy'de gece açık kütüphane var mı?")
    assert "555" not in final["answer"] and final["author"] != "model"
