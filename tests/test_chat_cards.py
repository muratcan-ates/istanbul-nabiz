"""The server's ChatCard v1 values stay bounded and match the browser vocabulary."""

from __future__ import annotations

import inspect
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import REPO_ROOT

from nabiz.console import chat_cards

STATIC_JS = REPO_ROOT / "src" / "nabiz" / "console" / "static" / "js" / "chat_cards.js"
CONTRACT = REPO_ROOT / "docs" / "contracts" / "chat-card.md"


def sample(**changes: object) -> dict:
    value = {"v": 1, "type": "info", "status": "ready", "title": "Bilgi", "body": {"text": "Açıklama"}}
    value.update(changes)
    return value


def test_card_defaults_and_stable_identity() -> None:
    first = chat_cards.card("info", "Bilgi")
    second = chat_cards.card("info", "Bilgi")
    assert first == second
    assert first == {
        "v": 1, "id": first["id"], "conversation_id": None, "message_id": None,
        "type": "info", "status": "ready", "title": "Bilgi", "body": {},
        "sources": [], "source_time": None, "linked_id": None, "actions": [], "sensitive": False,
    }
    assert first["id"].startswith("card-info-")
    assert chat_cards.card("info", "Bilgi", linked_id="işlem-2")["id"] != first["id"]
    assert chat_cards.card("info", "Bilgi", card_id="card-fixed")["id"] == "card-fixed"


@pytest.mark.parametrize("raw", [
    sample(type="unknown"),
    sample(title="<script>bad()</script>"),
    sample(v=2),
    {"v": 1, "title": "Başlık"},
])
def test_invalid_identity_is_dropped(raw: dict) -> None:
    assert chat_cards.validate_card(raw) is None


def test_unknown_action_is_removed_and_actions_must_be_an_array() -> None:
    checked = chat_cards.validate_card(sample(actions=["listen", "rm -rf", "listen"]))
    assert checked is not None and checked["actions"] == ["listen"]
    assert chat_cards.validate_card(sample(actions="listen"))["actions"] == []
    assert chat_cards.validate_card(sample(actions={"listen": True}))["actions"] == []


@pytest.mark.parametrize("unsafe", ["javascript:alert(1)", "http://example.org/", "https://user@example.org/"])
def test_unsafe_source_url_cannot_become_an_official_action(unsafe: str) -> None:
    checked = chat_cards.validate_card(sample(
        sources=[{"label": "Kaynak", "url": unsafe, "freshness": "kayitli"}],
        actions=["open_official"],
    ))
    assert checked is not None
    assert checked["sources"][0]["url"] is None
    assert checked["actions"] == []


def test_https_source_allows_the_official_action() -> None:
    checked = chat_cards.validate_card(sample(
        sources=[{"label": "Kaynak", "url": "https://www.ibb.istanbul/", "freshness": "guncel"}],
        actions=["open_official"],
    ))
    assert checked is not None and checked["actions"] == ["open_official"]


def test_long_text_and_nested_markup_are_plain_and_bounded() -> None:
    checked = chat_cards.validate_card(sample(
        title="A" * 5_000,
        body={"text": "<b>Okunur</b><script>bad()</script> " + "B" * 900,
              "steps": ["<i>adım</i>"] * 40, "nested": {"text": "<img src=x onerror=bad()>Güvenli"}},
        extra="ignore me",
    ))
    assert checked is not None
    assert len(checked["title"]) == 120
    assert len(checked["body"]["text"]) == 600
    assert "bad()" not in checked["body"]["text"]
    assert checked["body"]["nested"]["text"] == "Güvenli"
    assert checked["body"]["steps"] == ["adım"] * 20
    assert "extra" not in checked


def test_sources_are_bounded_and_oldest_valid_time_sets_age() -> None:
    sources = [
        {"label": f"Kayıt {number}", "url": None, "source_time": "2026-09-27T09:20:00+03:00", "freshness": "kayitli"}
        for number in range(40)
    ]
    sources[1]["source_time"] = "2026-09-27T09:00:00+03:00"
    checked = chat_cards.validate_card(sample(sources=sources, source_time="2026-09-27T09:40:00+03:00"))
    assert checked is not None
    assert len(checked["sources"]) == 20
    assert checked["source_time"] == "2026-09-27T09:00:00+03:00"


def test_sensitive_and_unrecognized_status_are_inert() -> None:
    assert chat_cards.validate_card(sample(actions=["send"], sensitive=True))["actions"] == []
    invalid = chat_cards.validate_card(sample(status="sent", actions=["send"]))
    assert invalid is not None and invalid["status"] == "unavailable" and invalid["actions"] == []


def test_cards_field_limits_to_six_and_deduplicates() -> None:
    raw = [sample(title="A"), sample(title="A")]
    raw.extend(sample(title=f"Kart {index}") for index in range(12))
    checked = chat_cards.cards_field(raw)
    assert len(checked) == chat_cards.MAX_CARDS == 6
    assert len({item["id"] for item in checked}) == 6
    assert chat_cards.cards_field("not a list") == []


def test_documented_example_is_valid_data() -> None:
    content = CONTRACT.read_text()
    match = re.search(r"```json\n(.*?)\n```", content, re.DOTALL)
    assert match is not None
    example = json.loads(match.group(1))
    assert chat_cards.validate_card(example) == example


def test_python_and_browser_share_the_closed_vocabularies() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    assert STATIC_JS.is_file()
    assert "CARD_TYPES" in STATIC_JS.read_text()
    script = (
        f"import {{ CARD_TYPES, CARD_STATUSES, CARD_ACTIONS, FRESHNESS, validateCard }} from {json.dumps(STATIC_JS.as_uri())};"
        "const id = validateCard({v: 1, type: 'info', title: 'İstanbul', status: 'ready'}).card.id;"
        "console.log(JSON.stringify({CARD_TYPES, CARD_STATUSES, CARD_ACTIONS, FRESHNESS, id}));"
    )
    result = subprocess.run([node, "--input-type=module", "-e", script], cwd=REPO_ROOT,
                            capture_output=True, text=True, timeout=20, check=True)
    browser = json.loads(result.stdout)
    assert browser == {
        "CARD_TYPES": list(chat_cards.CARD_TYPES),
        "CARD_STATUSES": list(chat_cards.CARD_STATUSES),
        "CARD_ACTIONS": list(chat_cards.CARD_ACTIONS),
        "FRESHNESS": list(chat_cards.FRESHNESS),
        "id": chat_cards.card("info", "İstanbul")["id"],
    }


def test_validator_has_no_io_or_environment_dependency() -> None:
    source = inspect.getsource(chat_cards)
    assert all(fragment not in source for fragment in ("open(", "requests", "environ"))
    assert Path(chat_cards.__file__).stat().st_size > 0
