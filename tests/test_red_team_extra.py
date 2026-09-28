"""The extra red-team set (P09a-1): ``eval/red_team_extra.jsonl``, run by the harness of ``test_red_team.py``.

Every case goes through :func:`test_red_team.test_red_team_case` itself, imported under another name so
pytest does not collect it twice: the same fake model seat, the same offline İBB fixtures, the same
assertions. This file adds cases, not a second runner. A case the harness cannot express names its own
test in ``own_test`` (today one: two devices behind one address need a device header the harness does
not send).

What the set covers beyond ``red_team.jsonl``: an instruction override in eight languages, instructions
inside a source or a tool result, false operator authority, somebody else's record, personal and health
details, legitimate questions that look like attacks, exact fares or approvals without a source, spam and
appeal abuse, and the E49 gaps as new strict xfails. A case that fails today is a strict xfail with its
reason, never written as if it passed; when a fix lands, the XPASS turns the run red until the marker goes.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import offline_settings, refuse_network
from test_console_chat import FakeModel, client_for
from test_red_team import test_red_team_case as run_shared_case

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console.budget import BudgetConfig, SpendGuard

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "eval" / "red_team_extra.jsonl"
BASE_PATH = ROOT / "eval" / "red_team.jsonl"
CASES = [json.loads(line) for line in DATA_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
BASE_CASES = [json.loads(line) for line in BASE_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]

LANGUAGES = ("tr", "en", "de", "ru", "ar", "fa", "fr", "es")
CATEGORIES = (
    "multilingual_injection", "indirect_injection", "false_authority", "other_person_record", "personal_health_data",
    "legit_lookalike", "unsourced_certainty", "spam_appeal", "e49_gap",
)
#: Keys the shared harness reads. An unknown key would be ignored silently, so the inventory pins them.
CASE_KEYS = frozenset({
    "id", "category", "lang", "seat", "question", "history", "expect", "covered_by", "notes", "model_script", "setup",
    "xfail", "must_not_contain", "messages_must_not_contain", "messages_must_contain", "tool_event", "masked_count_min",
    "citations_min", "citation_masks_min", "check_logs", "history_bounded", "request_lang", "method", "path",
    "instruction_detector", "own_test",
})
#: Setups the shared harness builds for any case id ("index_pii" seeds its page by rt-15's id, so it is left out).
SETUPS = frozenset({"index_injected", "tool_payload_injected", "paused", "quota_spent", "burst_xff", "operator_token"})
DEVICE_A = "device-a-" + "a" * 16
DEVICE_B = "device-b-" + "b" * 16


@pytest.fixture
def nabiz() -> Any:
    return Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)),
            cache=TTLCache(),
            settings=offline_settings(),
        )
    )


def _params() -> list[Any]:
    params = []
    for item in CASES:
        if item.get("own_test"):
            continue
        marks = pytest.mark.xfail(strict=True, reason=item["xfail"]) if item.get("xfail") else ()
        params.append(pytest.param(item, id=item["id"], marks=marks))
    return params


def _case(case_id: str) -> dict[str, Any]:
    return next(item for item in CASES if item["id"] == case_id)


@pytest.mark.parametrize("case", _params())
def test_red_team_extra_case(
    case: dict[str, Any], nabiz: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    run_shared_case(case, nabiz, monkeypatch, tmp_path, caplog)


@pytest.mark.xfail(strict=True, reason=_case("rtx-65")["xfail"])
def test_shared_network_second_device_keeps_its_turn(nabiz: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """rtx-65: one device spends its ten turns a minute; the next device behind the same address still asks."""
    case = _case("rtx-65")
    monkeypatch.setenv("NABIZ_CHAT_TURNS_PER_MIN", "10")
    monkeypatch.setenv("NABIZ_QUOTA_ANON_QUESTIONS", "1000")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(ROOT / "tests" / "no-knowledge-index.db"))
    fake = FakeModel()
    monkeypatch.setattr(llm, "chat", fake)
    body = {"message": case["question"], "needs": [], "history": []}
    with client_for(nabiz, llm.LlmConfig(), SpendGuard(BudgetConfig(state_path=None))) as client:
        first = [client.post("/api/chat", json=body, headers={"X-Nabiz-Device": DEVICE_A}) for _ in range(11)]
        second = client.post("/api/chat", json=body, headers={"X-Nabiz-Device": DEVICE_B})
    assert [response.status_code for response in first[:10]] == [200] * 10
    assert first[10].status_code == 429, "one device is still limited (criterion 10: the session is bounded)"
    assert fake.calls == []
    assert str(second.status_code) == case["expect"]["outcome"], "a second device on the same network keeps its turn"


# ---- the inventory --------------------------------------------------------------------------------


def test_extra_inventory_covers_the_classes_and_the_eight_languages() -> None:
    ids = [case["id"] for case in CASES]
    assert len(CASES) >= 40 and len(ids) == len(set(ids))
    assert not set(ids) & {case["id"] for case in BASE_CASES}, "an extra case never reuses a red_team.jsonl id"
    counts = Counter(case["category"] for case in CASES)
    assert set(counts) == set(CATEGORIES) and all(count >= 3 for count in counts.values()), counts
    injected = {case["lang"] for case in CASES if case["category"] == "multilingual_injection"}
    assert injected >= set(LANGUAGES), set(LANGUAGES) - injected
    assert {case["lang"] for case in CASES} <= set(LANGUAGES)


def test_every_case_speaks_the_shared_harness_schema() -> None:
    for case in CASES:
        assert set(case) <= CASE_KEYS, (case["id"], set(case) - CASE_KEYS)
        assert {"id", "category", "lang", "seat", "question", "history", "expect", "covered_by", "notes"} <= set(case)
        assert case["seat"] in {"rule", "model", "http"}, case["id"]
        assert {"model_calls", "emergency"} <= set(case["expect"]), case["id"]
        assert case.get("setup") is None or case["setup"] in SETUPS, case["id"]
        if case["seat"] == "model" and case.get("method") is None:
            assert case.get("model_script"), f"{case['id']}: a model seat case scripts what the model would say"
        if case.get("covered_by"):
            filename, test_name = case["covered_by"].split("::", 1)
            source = (ROOT / filename).read_text(encoding="utf-8")
            assert re.search(rf"^def {re.escape(test_name)}\(", source, re.M), case["id"]


def test_every_xfail_has_a_reason_and_no_e49_case_repeats_an_existing_one() -> None:
    known = {case["question"].casefold() for case in BASE_CASES if case.get("xfail")}
    for case in CASES:
        if "xfail" in case:
            assert len(case["xfail"]) >= 40, f"{case['id']}: an xfail says why it fails today"
    gaps = [case for case in CASES if case["category"] == "e49_gap"]
    assert not {case["question"].casefold() for case in gaps} & known, "rt-33 and rt-46 stay the only copies"
    assert sum(1 for case in gaps if case.get("xfail")) >= 4


def test_an_own_test_exists_and_carries_the_cases_strict_xfail() -> None:
    module = sys.modules[__name__]
    for case in CASES:
        if not case.get("own_test"):
            continue
        test = getattr(module, case["own_test"], None)
        assert callable(test), case["id"]
        marks = [mark for mark in getattr(test, "pytestmark", []) if mark.name == "xfail"]
        if case.get("xfail"):
            assert marks and marks[0].kwargs.get("strict") is True and marks[0].kwargs.get("reason") == case["xfail"]
        else:
            assert not marks


def test_the_extra_set_stays_out_of_the_default_eval() -> None:
    """``make eval`` reads ``eval/journeys*.jsonl``; the red-team file is not one of them."""
    assert not DATA_PATH.name.startswith("journeys")
    assert "red_team_extra" not in (ROOT / "eval" / "run_eval.py").read_text(encoding="utf-8")
