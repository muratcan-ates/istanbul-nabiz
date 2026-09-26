from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"


def node_json(tmp_path, modules: dict[str, str], body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    imports = "\n".join(
        f"import * as {name} from {json.dumps((STATIC / path).as_uri())};" for name, path in modules.items()
    )
    harness = tmp_path / "personas_harness.mjs"
    harness.write_text(f"{imports}\n{body}\n", encoding="utf-8")
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_seven_presets_are_filled_in_order(tmp_path) -> None:
    source = (STATIC / "js" / "personas.js").read_text(encoding="utf-8")
    assert "const PERSONA_ORDER" in source and "const PRESETS" in source
    values = node_json(
        tmp_path,
        {"personas": "js/personas.js"},
        "console.log(JSON.stringify({order:personas.PERSONA_ORDER,"
        "presets:personas.PERSONA_ORDER.map((id)=>personas.PRESETS[id])}));",
    )
    assert values["order"] == ["gorme", "isitme", "hareket", "yasli", "ilk_kez", "yabanci", "okuma"]
    for preset in values["presets"]:
        assert {"label", "hint", "prefs", "simple", "needs", "lang", "voice", "call153"} <= preset.keys()
        assert preset["label"] and preset["hint"]


def test_preset_needs_are_profile_need_keys(tmp_path) -> None:
    source = (STATIC / "js" / "personas.js").read_text(encoding="utf-8")
    profile_source = (STATIC / "js" / "profile.js").read_text(encoding="utf-8")
    keys = set(re.findall(r"key: '([^']+)'", profile_source)) | {"answer_en"}
    arrays = re.findall(r"needs: Object\.freeze\(\[([^\]]*)\]\)", source)
    assert len(arrays) == 7
    for array in arrays:
        assert set(re.findall(r"'([^']+)'", array)) <= keys
    values = node_json(
        tmp_path,
        {"personas": "js/personas.js", "profile": "js/profile.js"},
        "console.log(JSON.stringify(personas.PERSONA_ORDER.map((id)=>[...new Set(["
        "...personas.PRESETS[id].needs,...(personas.PRESETS[id].lang==='en'?['answer_en']:[])])]"
        ".every((key)=>profile.NEED_KEYS.has(key)))));",
    )
    assert all(values)


def test_preset_prefs_survive_a11y_parse(tmp_path) -> None:
    source = (STATIC / "js" / "personas.js").read_text(encoding="utf-8")
    assert "parsePrefs(JSON.stringify" in source
    values = node_json(
        tmp_path,
        {"personas": "js/personas.js", "a11y": "js/a11y.js"},
        "console.log(JSON.stringify(personas.PERSONA_ORDER.map((id)=>{"
        "const o=personas.planPreset(id,a11y.DEFAULT_PREFS,{consent:false,needs:[]}).prefs;"
        "return JSON.stringify(a11y.parsePrefs(JSON.stringify(o)))===JSON.stringify(o)"
        "&&Object.keys(o).every((key)=>key in a11y.DEFAULT_PREFS)})));",
    )
    assert all(values)


def test_sight_and_elder_bring_150_simple_and_the_153_bar(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"personas": "js/personas.js", "a11y": "js/a11y.js"},
        "console.log(JSON.stringify(personas.PERSONA_ORDER.map((id)=>{"
        "const plan=personas.planPreset(id,a11y.DEFAULT_PREFS,{consent:true,needs:[]});"
        "return [id,plan.prefs.text,plan.simple,plan.call153]})));",
    )
    by_id = {row[0]: row[1:] for row in values}
    assert by_id["gorme"] == [150, True, True]
    assert by_id["yasli"] == [150, True, True]
    assert all(by_id[key][2] is False for key in ("isitme", "hareket", "ilk_kez", "yabanci", "okuma"))


def test_hearing_turns_voice_off_and_never_opens_tid(tmp_path) -> None:
    source = (STATIC / "js" / "personas.js").read_text(encoding="utf-8")
    assert "data-pending" not in source and "tid-istanbul-senin" not in source and "speechSynthesis" not in source
    values = node_json(
        tmp_path,
        {"personas": "js/personas.js", "a11y": "js/a11y.js"},
        "const plan=personas.planPreset('isitme',a11y.DEFAULT_PREFS,{consent:true,needs:[]});"
        "console.log(JSON.stringify({voice:plan.voice,call153:plan.call153}));",
    )
    assert values == {"voice": "off", "call153": False}


def test_plan_asks_consent_and_never_drops_a_need(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"personas": "js/personas.js", "a11y": "js/a11y.js"},
        "const pending=personas.planPreset('hareket',a11y.DEFAULT_PREFS,{consent:false,needs:['stroller']});"
        "const approved=personas.planPreset('hareket',a11y.DEFAULT_PREFS,{consent:true,needs:['stroller']});"
        "const english=personas.planPreset('yabanci',a11y.DEFAULT_PREFS,{consent:false,needs:[]});"
        "const savedEnglish=personas.planPreset('hareket',a11y.DEFAULT_PREFS,{consent:false,needs:['answer_en']});"
        "console.log(JSON.stringify({pending,approved,english,savedEnglish}));",
    )
    assert values["pending"]["needsConsent"] is True
    assert {"stroller", "step_free", "slow_walk"} <= set(values["pending"]["needs"])
    assert values["approved"]["needsConsent"] is False
    assert values["english"]["needsConsent"] is True
    assert values["savedEnglish"]["needsConsent"] is True


def test_persona_name_never_reaches_a_request(tmp_path) -> None:
    source = (STATIC / "js" / "personas.js").read_text(encoding="utf-8")
    for forbidden in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource", "api.js"):
        assert forbidden not in source
    for path in (STATIC / "js").glob("*.js"):
        if path.name != "personas.js":
            text = path.read_text(encoding="utf-8")
            assert "nabiz.persona.v1" not in text and "data-persona" not in text
    values = node_json(
        tmp_path,
        {"personas": "js/personas.js", "a11y": "js/a11y.js"},
        "console.log(JSON.stringify(personas.PERSONA_ORDER.map((id)=>{"
        "const plan=personas.planPreset(id,a11y.DEFAULT_PREFS,{consent:true,needs:[]});"
        "const payload=JSON.stringify(plan.needs);"
        "return !personas.PERSONA_ORDER.some((name)=>payload.includes(name))"
        "&&!personas.PERSONA_ORDER.some((name)=>payload.includes(personas.PRESETS[name].label))})));",
    )
    assert all(values)


def test_state_parse_rejects_bad_json_and_unknown_ids(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"personas": "js/personas.js"},
        "const bad=[null,'','{','[]','{\"version\":2}','{\"version\":1,\"active\":\"hacker\"}'];"
        "console.log(JSON.stringify(bad.map(personas.parseState)));",
    )
    default = {"version": 1, "active": None, "dismissed": False, "previous": None}
    assert values == [default] * 6


def test_snapshot_restores_what_was_there(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"personas": "js/personas.js"},
        "console.log(JSON.stringify(personas.snapshotOf("
        "{version:1,text:125,contrast:'more',motion:'reduce'},"
        "{consent:true,needs:['stroller','answer_en']},true,true)));",
    )
    assert values == {
        "prefs": {"version": 1, "text": 125, "contrast": "more", "motion": "reduce"},
        "needs": ["stroller"], "consent": True, "lang": "en", "simple": True, "hadProfile": True,
    }


def test_picker_badge_and_bar_markup(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"personas": "js/personas.js"},
        "console.log(JSON.stringify({picker:personas.pickerMarkup(),badge:personas.badgeMarkup('gorme'),"
        "bar:personas.callBarMarkup()}));",
    )
    assert "Size nasıl kolaylık sağlayalım?" in values["picker"]
    assert values["picker"].count('data-persona="') == 7
    assert 'role="group"' in values["picker"] and 'id="persona-later"' in values["picker"]
    assert "Şimdi değil" in values["picker"] and values["picker"].count('tabindex="0"') == 1
    assert "Açık: Görme" in values["badge"] and 'id="persona-undo"' in values["badge"]
    assert 'href="tel:153"' in values["bar"] and "ETA" not in values["bar"]


def test_arrow_keys_move_inside_the_group(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"personas": "js/personas.js"},
        "console.log(JSON.stringify([personas.nextIndex(0,'ArrowRight',7),"
        "personas.nextIndex(6,'ArrowDown',7),personas.nextIndex(0,'ArrowLeft',7),"
        "personas.nextIndex(3,'Home',7),personas.nextIndex(3,'End',7),"
        "personas.nextIndex(3,'KeyA',7)]));",
    )
    assert values == [1, 0, 6, 0, 6, 3]


def test_personas_uses_the_exported_a11y_and_profile_functions() -> None:
    source = (STATIC / "js" / "personas.js").read_text(encoding="utf-8")
    assert "from './a11y.js'" in source
    assert all(name in source.split("from './a11y.js'")[0].splitlines()[-1]
               for name in ("applyPrefs", "savePrefs", "readPrefs", "PREFS_KEY"))
    assert "from './profile.js'" in source
    assert all(name in source.split("from './profile.js'")[0].splitlines()[-1]
               for name in ("readProfile", "NEEDS", "NEED_KEYS", "answerLanguage"))
    assert "new StorageEvent('storage'" in source
    assert len(source.splitlines()) <= 300
    assert "behavior: 'smooth'" not in source


def test_personas_css_has_48px_buttons_64px_bar_and_320px_rule() -> None:
    css = (STATIC / "css" / "personas.css").read_text(encoding="utf-8")
    assert "min-height: 48px" in css and "min-height: 64px" in css
    assert ':root[data-persona-call="on"] body' in css
    assert "padding-bottom" in css and "env(safe-area-inset-bottom" in css
    assert "320px" in css or "20rem" in css
    colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(")
    assert not colour.search(css)
    if "transition" in css or "animation" in css:
        assert "@media (prefers-reduced-motion: no-preference)" in css
    assert len(css.splitlines()) <= 350
