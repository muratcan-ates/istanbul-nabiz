"""The server's ChatCard v1 values agree with the v0.1 producer contract."""

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

# Copied from SOZLESME-sohbet-karti-v0.md v0.1, the producer contract's fixed sets.
ACTION_KIND = {
    "use_location": "device", "type_place": "view", "expand_map": "view", "listen": "view",
    "remember_here": "device", "remember_always": "device", "change": "view", "forget": "device",
    "save_calendar": "nabiz", "export_ics": "device", "review_report": "view", "send": "nabiz",
    "open_official": "external", "add_outlook": "external", "confirm_resolved": "nabiz",
    "reopen": "nabiz", "cancel": "nabiz", "appeal": "nabiz", "share": "external",
}
CONSENT = {"use_location", "remember_here", "remember_always", "save_calendar", "send", "add_outlook",
           "confirm_resolved", "reopen", "cancel", "appeal", "share"}
CONSENT_ORDER = ["use_location", "remember_here", "remember_always", "save_calendar", "send",
                 "add_outlook", "confirm_resolved", "reopen", "cancel", "appeal", "share"]
ALIASES = {"add_calendar": "save_calendar", "download_ics": "export_ics",
           "open_map": "expand_map", "remember": "remember_here"}
RESULTS = {None, "saved_nabiz", "ics_downloaded", "outlook_verifying", "outlook_added", "outlook_failed",
           "report_sent", "resolution_confirmed", "reopened", "cancelled", "appeal_sent"}
ACTION_KEYS = {"id", "label", "kind", "requires_consent", "operation_id"}
LINK_EMPTY = {"event_id": None, "report_code": None, "operation_id": None}


def sample(**changes: object) -> dict:
    value = {"v": 1, "type": "info", "status": "ready", "title": "Bilgi", "body": {"text": "Açıklama"}}
    value.update(changes)
    return value


def action_ids(card: dict) -> list[str]:
    return [action["id"] for action in card["actions"]]


def test_card_defaults_and_stable_identity() -> None:
    first = chat_cards.make_card("info", "Bilgi")
    assert first == chat_cards.make_card("info", "Bilgi")
    assert first == {
        "v": 1, "id": first["id"], "conversation_id": None, "message_id": None,
        "type": "info", "status": "ready", "title": "Bilgi", "body": {},
        "sources": [], "source_time": None, "linked": LINK_EMPTY, "linked_id": None,
        "actions": [], "sensitive": False,
    }
    assert first["id"].startswith("card-info-")
    assert chat_cards.make_card("info", "Bilgi", linked_id="op:işlem-2")["id"] != first["id"]
    assert chat_cards.make_card("info", "Bilgi", card_id="card-fixed")["id"] == "card-fixed"
    with pytest.raises(TypeError, match="unknown fields"):
        chat_cards.make_card("info", "Bilgi", cardid="typo")


@pytest.mark.parametrize("raw", [sample(type="unknown"), sample(title="<script>bad()</script>"),
                                 sample(v=2), {"v": 1, "title": "Başlık"}])
def test_invalid_identity_is_dropped(raw: dict) -> None:
    assert chat_cards.validate_card(raw) is None


def test_action_table_and_document_match_v01_source() -> None:
    assert chat_cards.ACTION_KIND == ACTION_KIND
    assert tuple(ACTION_KIND) == chat_cards.CARD_ACTIONS
    assert chat_cards.CONSENT_ACTIONS == CONSENT
    assert chat_cards.ACTION_ALIASES == ALIASES
    assert set(chat_cards.CARD_RESULTS) == RESULTS
    doc = CONTRACT.read_text()
    assert doc.startswith("Tek kaynak: nabiz-plan/2026-09-27/gpt-paketler/SOZLESME-sohbet-karti-v0.md (v0.1)")
    rows = re.findall(r"^\| `([a-z_]+)` \| (view|device|nabiz|external) \| (true|false) \|$", doc, re.M)
    assert {action: kind for action, kind, _ in rows} == ACTION_KIND
    assert {action for action, _, consent in rows if consent == "true"} == CONSENT
    alias_rows = re.findall(r"^\| `([a-z_]+)` \| `([a-z_]+)` \|$", doc, re.M)
    assert dict(alias_rows) == ALIASES
    result_line = re.search(r"`body\.result` kapalı listesi: ([^\n]+)", doc)
    assert result_line and set(re.findall(r"`([^`]+)`", result_line.group(1).split(". Bilinmeyen")[0])) == {
        "null" if value is None else value for value in RESULTS
    }


def test_action_objects_keep_metadata_and_cannot_lower_consent() -> None:
    checked = chat_cards.validate_card(sample(actions=[
        {"id": "add_calendar", "label": "<b>Takvime kaydet</b>", "kind": "view",
         "requires_consent": False, "operation_id": "plan-17"},
        {"id": "listen", "requires_consent": True, "operation_id": "must-drop"},
        {"id": "share", "requires_consent": False, "operation_id": "share-1"},
        "rm -rf", "save_calendar",
    ]))
    assert checked is not None
    assert action_ids(checked) == ["save_calendar", "listen", "share"]
    assert checked["actions"] == [
        {"id": "save_calendar", "label": "Takvime kaydet", "kind": "nabiz",
         "requires_consent": True, "operation_id": "plan-17"},
        {"id": "listen", "label": "", "kind": "view", "requires_consent": True, "operation_id": None},
        {"id": "share", "label": "", "kind": "external", "requires_consent": True, "operation_id": "share-1"},
    ]
    assert all(set(action) == ACTION_KEYS for action in checked["actions"])
    assert chat_cards.normalize_action({"id": "remember", "requires_consent": False})["id"] == "remember_here"
    assert chat_cards.validate_card(sample(actions="listen"))["actions"] == []


def test_aliases_and_four_action_cap() -> None:
    checked = chat_cards.validate_card(sample(actions=["open_map", "download_ics", "remember", "appeal", "cancel"]))
    assert checked is not None and action_ids(checked) == ["expand_map", "export_ics", "remember_here", "appeal"]


@pytest.mark.parametrize("unsafe", ["javascript:alert(1)", "http://example.org/",
                                      "https://user@example.org/", "https://example.org/\" onclick=\"x"])
def test_unsafe_source_url_cannot_enable_official_action(unsafe: str) -> None:
    checked = chat_cards.validate_card(sample(
        sources=[{"label": "Kaynak", "url": unsafe, "freshness": "kayitli"}], actions=["open_official"],
    ))
    assert checked is not None and checked["sources"][0]["url"] is None and checked["actions"] == []
    safe = chat_cards.validate_card(sample(
        sources=[{"label": "Kaynak", "url": "https://www.ibb.istanbul/"}], actions=["open_official"],
    ))
    assert safe is not None and action_ids(safe) == ["open_official"]


def test_text_sources_and_results_are_bounded() -> None:
    sources = [{"label": f"Kayıt {i}", "url": None, "source_time": "2026-09-27T09:20:00+03:00",
                "freshness": "kayitli"} for i in range(40)]
    sources[1]["source_time"] = "2026-09-27T09:00:00+03:00"
    checked = chat_cards.validate_card(sample(
        title="A" * 5_000, sources=sources, source_time="2026-09-27T09:40:00+03:00",
        body={"text": "<b>Okunur</b><script>bad()</script> " + "B" * 900,
              "steps": ["<i>adım</i>"] * 40, "result": "invented_success"}, extra="ignore me",
    ))
    assert checked is not None
    assert len(checked["title"]) == 120 and len(checked["sources"]) == 20
    assert checked["source_time"] == "2026-09-27T09:00:00+03:00"
    assert len(checked["body"]["text"]) == 600 and "bad()" not in checked["body"]["text"]
    assert checked["body"]["steps"] == ["adım"] * 20
    assert checked["body"]["result"] is None and "extra" not in checked
    for result in RESULTS:
        assert chat_cards.validate_card(sample(body={"result": result}))["body"]["result"] == result


def test_map_points_allow_sixty_while_other_arrays_stay_at_twenty() -> None:
    points = [{"lat": i, "lon": i, "label": f"Nokta {i}", "details": list(range(30))} for i in range(70)]
    checked = chat_cards.validate_card(sample(type="map", body={"points": points, "other": list(range(70))}))
    assert checked is not None
    assert len(checked["body"]["points"]) == 60
    assert checked["body"]["points"][-1]["lat"] == 59
    assert len(checked["body"]["points"][0]["details"]) == 20
    assert len(checked["body"]["other"]) == 20
    assert len(chat_cards.validate_card(sample(body={"points": points}))["body"]["points"]) == 20


@pytest.mark.parametrize(("linked", "derived"), [
    ({"event_id": "42"}, "event:42"), ({"report_code": "R-7"}, "report:R-7"),
    ({"operation_id": "op-9"}, "op:op-9"),
])
def test_linked_triple_and_legacy_id(linked: dict, derived: str) -> None:
    built = chat_cards.make_card("status", "Durum", linked=linked)
    key = next(iter(linked))
    assert built["linked"] == {**LINK_EMPTY, key: linked[key]}
    assert built["linked_id"] == derived
    assert chat_cards.validate_card(sample(linked_id=derived))["linked"] == built["linked"]
    other_key = "event_id" if key == "report_code" else "report_code"
    assert chat_cards.validate_card(sample(linked={**linked, other_key: "other"}))["linked_id"] is None


def test_sensitive_health_and_restored_filters_use_action_ids() -> None:
    raw = sample(actions=["use_location", "share", "save_calendar", "forget", "listen", "expand_map"])
    assert action_ids(chat_cards.validate_card({**raw, "sensitive": True})) == ["listen", "expand_map"]
    raised = sample(actions=[{"id": "listen", "requires_consent": True}, "expand_map"], sensitive=True)
    assert action_ids(chat_cards.validate_card(raised)) == ["expand_map"]
    health = chat_cards.validate_card(sample(type="memory", body={"kind": "health"},
                                             actions=["listen", "remember_here", "change", "share"]))
    assert health is not None and health["sensitive"] is True and action_ids(health) == ["change"]
    restored = chat_cards.validate_card(sample(
        actions=["share", "save_calendar", "listen", "expand_map", "open_official"],
        sources=[{"label": "Resmî", "url": "https://example.org/"}],
    ), restored=True)
    assert restored is not None and action_ids(restored) == ["listen", "expand_map", "open_official"]
    invalid = chat_cards.validate_card(sample(status="sent", actions=["send"]))
    assert invalid is not None and invalid["status"] == "unavailable" and invalid["actions"] == []


def test_v0_conversion_preserves_data_sources_links_and_action_objects() -> None:
    raw = {"v": 0, "id": "card-event-abc", "type": "event", "status": "done", "title": "Etkinlik",
           "source": {"name": "Birincil", "url": "https://example.org/", "observed_at": "2026-09-27T11:00:00+03:00",
                      "freshness": "kayitli"},
           "linked": {"event_id": "e-17", "report_code": None, "operation_id": None},
           "actions": [{"id": "add_calendar", "label": "Takvime ekle", "kind": "view",
                        "requires_consent": False, "operation_id": "save-17"},
                       {"id": "add_outlook", "label": "Outlook'a ekle", "kind": "external",
                        "requires_consent": True, "operation_id": "outlook-17"}],
           "data": {"result": "outlook_verifying", "sources": [{"name": "İkinci", "url": "https://other.org/",
                    "observed_at": "2026-09-27T09:00:00+03:00", "freshness": "tarife"}]}}
    checked = chat_cards.from_v0(raw)
    assert checked == chat_cards.validate_card(raw)
    assert checked["v"] == 1 and checked["id"] == raw["id"]
    assert checked["body"] == raw["data"]
    assert [source["label"] for source in checked["sources"]] == ["Birincil", "İkinci"]
    assert checked["source_time"] == "2026-09-27T09:00:00+03:00"
    assert checked["linked_id"] == "event:e-17" and checked["linked"] == raw["linked"]
    assert action_ids(checked) == ["save_calendar", "add_outlook"]
    assert [action["operation_id"] for action in checked["actions"]] == ["save-17", "outlook-17"]
    assert all(action["requires_consent"] for action in checked["actions"])
    assert chat_cards.validate_card({**raw, "data": {"sources": 7}}) is not None
    with pytest.raises(ValueError, match="v0"):
        chat_cards.from_v0({"v": 2})


def test_cards_field_limits_to_six_and_deduplicates() -> None:
    raw = [sample(title="A"), sample(title="A")]
    raw.extend(sample(title=f"Kart {index}") for index in range(12))
    checked = chat_cards.cards_field(raw)
    assert len(checked) == chat_cards.MAX_CARDS == 6
    assert len({item["id"] for item in checked}) == 6
    assert chat_cards.cards_field("not a list") == []


def test_documented_example_is_valid_data() -> None:
    match = re.search(r"```json\n(.*?)\n```", CONTRACT.read_text(), re.DOTALL)
    assert match is not None
    example = json.loads(match.group(1))
    assert chat_cards.validate_card(example) == example


def test_python_and_browser_share_contract_and_v0_example() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = (
        f"import {{ CARD_TYPES, CARD_STATUSES, CARD_ACTIONS, ACTION_KIND, CONSENT_ACTIONS, ACTION_ALIASES,"
        f" CARD_RESULTS, FRESHNESS, validateCard }} from {json.dumps(STATIC_JS.as_uri())};"
        "const raw={v:0,id:'card-status-9',type:'status',status:'ready',title:'İstanbul',"
        "linked:{event_id:null,report_code:'R-9',operation_id:null},"
        "source:{name:'Kaynak',url:'https://example.org/',observed_at:'2026-09-27T09:20:00+03:00',freshness:'kayitli'},"
        "actions:[{id:'add_calendar',label:'Takvime ekle',kind:'view',requires_consent:false,operation_id:'op-1'},"
        "{id:'open_official',label:'Kaynağı aç',kind:'external',requires_consent:false,operation_id:'op-2'}],"
        "data:{result:'saved_nabiz'}};"
        "console.log(JSON.stringify({CARD_TYPES,CARD_STATUSES,CARD_ACTIONS,ACTION_KIND,CONSENT_ACTIONS,"
        "ACTION_ALIASES,CARD_RESULTS,FRESHNESS,card:validateCard(raw).card}));"
    )
    result = subprocess.run([node, "--input-type=module", "-e", script], cwd=REPO_ROOT,
                            capture_output=True, text=True, timeout=20, check=True)
    browser = json.loads(result.stdout)
    raw = {"v": 0, "id": "card-status-9", "type": "status", "status": "ready", "title": "İstanbul",
           "linked": {"event_id": None, "report_code": "R-9", "operation_id": None},
           "source": {"name": "Kaynak", "url": "https://example.org/",
                      "observed_at": "2026-09-27T09:20:00+03:00", "freshness": "kayitli"},
           "actions": [{"id": "add_calendar", "label": "Takvime ekle", "kind": "view",
                        "requires_consent": False, "operation_id": "op-1"},
                       {"id": "open_official", "label": "Kaynağı aç", "kind": "external",
                        "requires_consent": False, "operation_id": "op-2"}],
           "data": {"result": "saved_nabiz"}}
    assert browser == {
        "CARD_TYPES": list(chat_cards.CARD_TYPES), "CARD_STATUSES": list(chat_cards.CARD_STATUSES),
        "CARD_ACTIONS": list(chat_cards.CARD_ACTIONS), "ACTION_KIND": ACTION_KIND,
        "CONSENT_ACTIONS": CONSENT_ORDER, "ACTION_ALIASES": ALIASES,
        "CARD_RESULTS": list(chat_cards.CARD_RESULTS), "FRESHNESS": list(chat_cards.FRESHNESS),
        "card": chat_cards.validate_card(raw),
    }


def test_validator_has_no_io_or_environment_dependency_and_stays_bounded() -> None:
    source = inspect.getsource(chat_cards)
    assert all(fragment not in source for fragment in ("open(", "requests", "environ"))
    assert sum(bool(line.strip()) and not line.lstrip().startswith("#") for line in source.splitlines()) <= 250
    assert Path(chat_cards.__file__).stat().st_size > 0
