"""Görev 0-a: a model answer that tells the person to call 112 or 153 passes the numeric check.

The check (:mod:`nabiz.agent.faithfulness`) requires every number in an answer to come from a tool
result. An official help line in a call ("112'yi arayın") is a phone number, not a measurement: it is
masked out when it is on the closed list :data:`~nabiz.agent.faithfulness.OFFICIAL_LINES` and next to a
call. Any other number, an invented phone number and a line number used as a bus or a price stay checked.
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
        "Acil bir durumda 112'yi arayın.",
        "Bunun için 153'ü arayabilirsiniz.",
        "Gaz kokusu alırsanız 187'yi hemen arayın.",
        "İBB Çözüm Merkezi'ni (153) arayın.",
        "In an emergency, call 112.",
    ],
)
def test_an_official_line_in_a_call_passes(answer: str) -> None:
    assert check_faithfulness(answer, None).passed


@pytest.mark.parametrize(
    ("answer", "unsupported"),
    [
        ("Bilgi için 0212 555 12 34 numarasını arayın.", "0212"),
        ("İBB'yi 444 99 99'dan arayabilirsiniz.", "444"),
        ("112 numaralı otobüs 5 dakikada gelir.", "112"),
        ("Bilet 112 TL.", "112"),
        ("Kadıköy'e 112 ile gidin ve inince arayın.", "112"),
    ],
)
def test_invented_numbers_and_a_line_number_outside_a_call_are_still_refused(answer: str, unsupported: str) -> None:
    report = check_faithfulness(answer, None)
    assert not report.passed and unsupported in report.unsupported_texts


def test_a_changed_amount_next_to_a_call_is_still_refused() -> None:
    evidence = [{"tariff": "İlk 1 saat 30 TL"}]
    assert check_faithfulness("İlk 1 saat 30 TL. Acil bir durumda 112'yi arayın.", evidence).passed
    report = check_faithfulness("İlk 1 saat 35 TL. Acil bir durumda 112'yi arayın.", evidence)
    assert report.unsupported_texts == ["35"]


def test_the_list_is_closed_and_holds_no_invented_line() -> None:
    assert OFFICIAL_LINES == ("112", "110", "153", "155", "156", "177", "185", "187")
    assert not check_faithfulness("444 1 999'u arayın.", None).passed, "eval/red_team.jsonl rt-38"


@pytest.mark.parametrize("answer", ["Acil bir durumda 112'yi arayın.", "Bunun için 153'ü arayabilirsiniz."])
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
