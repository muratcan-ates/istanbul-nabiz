"""Unit and browser-module contract tests for the PII guard."""

from __future__ import annotations

import ast
import dataclasses
import importlib.util
import json
import re
import sys

import pytest
from conftest import FIXTURES_DIR, REPO_ROOT

from nabiz.console import policy
from nabiz.console.pii_guard import (
    KINDS,
    MaskedTurn,
    PiiHit,
    fold_keep_length,
    iban_valid,
    luhn_valid,
    mask,
    mask_labels,
    mask_turn,
    pii_final_fields,
    scan_pii,
    tckn_valid,
)


def tckn(nine: str) -> str:
    odd = sum(int(nine[index]) for index in (0, 2, 4, 6, 8))
    even = sum(int(nine[index]) for index in (1, 3, 5, 7))
    first_check = (odd * 7 - even) % 10
    first_ten = nine + str(first_check)
    return first_ten + str(sum(map(int, first_ten)) % 10)


def tr_iban(bank5: str, acc16: str) -> str:
    body = bank5 + "0" + acc16
    remainder = 0
    for ch in body + "TR00":
        digits = str(ord(ch) - 55) if ch.isalpha() else ch
        for digit in digits:
            remainder = (remainder * 10 + int(digit)) % 97
    return "TR" + f"{98 - remainder:02d}" + body


def mail(user: str) -> str:
    return user + chr(64) + "example.org"


def spaced(value: str, width: int = 4) -> str:
    return " ".join(value[index : index + width] for index in range(0, len(value), width))


TCKN = tckn("100000001")
IBAN = tr_iban("00061", "0000000000000001")
ARABIC_DIGITS = TCKN.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
POSITIVES = [
    (spaced(IBAN), "[IBAN]"),
    (IBAN.lower(), "[IBAN]"),
    (f"IBAN: {IBAN}", "IBAN: [IBAN]"),
    (IBAN.replace("TR", "tr", 1), "[IBAN]"),
    ("4111 1111 1111 1111", "[KART NO]"),
    ("5555555555554444", "[KART NO]"),
    ("378282246310005", "[KART NO]"),
    ("4111-1111-1111-1111", "[KART NO]"),
    (TCKN, "[TC KİMLİK]"),
    (f"TC:{TCKN}", "TC:[TC KİMLİK]"),
    (f"TC {ARABIC_DIGITS}", "TC [TC KİMLİK]"),
    (f"başvuru {TCKN}", "başvuru [TC KİMLİK]"),
    ("0555 000 00 01", "[TELEFON]"),
    ("+90 555 000 00 01", "[TELEFON]"),
    ("(0555) 000 00 01", "[TELEFON]"),
    ("5550000001", "[TELEFON]"),
    ("05550000001", "[TELEFON]"),
    ("muratcan" + chr(64) + "example.org", "[E-POSTA]"),
    (mail("destek"), "[E-POSTA]"),
    ("34 QX 1234", "[PLAKA]"),
    ("06 XW 123", "[PLAKA]"),
    ("35 X 12345", "[PLAKA]"),
    ("34qx1234", "[PLAKA]"),
    ("34-QX-1234", "[PLAKA]"),
    (f"TC {TCKN} ve 0555 000 00 01", "TC [TC KİMLİK] ve [TELEFON]"),
    (f"🙂 {TCKN}", "🙂 [TC KİMLİK]"),
    ("İSPARK otoparkında kartımı 4111 1111 1111 1111 okuttum", "İSPARK otoparkında kartımı [KART NO] okuttum"),
    (f"İETT hattında TC {TCKN} ile giriş", "İETT hattında TC [TC KİMLİK] ile giriş"),
    ("4111 1111 1111 1111 34 dk", "[KART NO] 34 dk"),
    ("Kart 4111-1111-1111-1111", "Kart [KART NO]"),
    ("0555\u00a0000\u00a000\u00a001", "[TELEFON]"),
    ("0555\u2009000\u300000 01", "[TELEFON]"),
    ("kart 4111\u00a01111\u00a01111\u00a01111", "kart [KART NO]"),
    ("34 ve 06 QX 123", "34 ve [PLAKA]"),
    (f"{mail('yolcu')} 0555 000 00 01", "[E-POSTA] [TELEFON]"),
    ("tr96 0006 1000 0000 0000 0000 01", "[IBAN]"),
]


def negatives() -> list[dict[str, str]]:
    path = FIXTURES_DIR / "pii_negatives.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize(("source", "expected"), POSITIVES)
def test_positive_messages_are_masked(source: str, expected: str) -> None:
    masked, count, _ = mask_labels(source)
    assert (masked, count) == (expected, expected.count("["))


def test_negative_fixture_is_never_masked() -> None:
    cases = negatives()
    assert len(cases) >= 40
    for case in cases:
        assert set(case) == {"text", "neden"}
        assert mask(case["text"]) == (case["text"], 0)
        assert scan_pii(case["text"]) == []


def test_no_digit_run_survives_masking() -> None:
    for source, expected in POSITIVES:
        output, _ = mask(source)
        assert not re.search(r"[0-9](?:[ -]?[0-9]){9,}", output)
        assert expected == output


def test_checksums_decide() -> None:
    assert tckn_valid(TCKN)
    assert not tckn_valid(TCKN[:-1] + str((int(TCKN[-1]) + 1) % 10))
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")
    assert iban_valid(IBAN)
    assert not iban_valid(IBAN[:-1] + str((int(IBAN[-1]) + 1) % 10))


def test_fold_keeps_length_and_offsets() -> None:
    samples = ("İSTANBUL", "İETT İSPARK", "ıI", "Straße", "حَرِيق", "🙂", "١٠٠٠", "a\u00a0b\u2009c\u3000d\ne")
    assert all(len(fold_keep_length(value)) == len(value) for value in samples)
    assert fold_keep_length("İETT İSPARK ŞİŞLİ ıI") == "iett ispark sisli ii"
    assert fold_keep_length("١٠٠") == "100"
    assert fold_keep_length("a\u00a0b\u2009c\u3000d\ne") == "a b c d e"
    assert mask("İSPARK otoparkında kartımı 4111 1111 1111 1111 okuttum")[0] == (
        "İSPARK otoparkında kartımı [KART NO] okuttum"
    )


def test_hits_carry_no_value() -> None:
    hits = scan_pii(f"TC {TCKN}")
    assert {field.name for field in dataclasses.fields(PiiHit)} == {"kind", "start", "end"}
    assert TCKN not in repr(hits)


def test_masking_never_logs_and_imports_stay_small(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG")
    mask(f"TC {TCKN}")
    assert caplog.records == []
    source = (REPO_ROOT / "src/nabiz/console/pii_guard.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(name=node.module or "")])
    }
    assert imports <= {"__future__", "re", "functools", "dataclasses", "collections.abc", "typing", "ibb_mcp.text"}
    assert not imports.intersection({"logging", "httpx", "openai", "nabiz.agent"})


def test_mask_is_idempotent() -> None:
    for source, _ in POSITIVES:
        masked, _ = mask(source)
        assert mask(masked) == (masked, 0)
    assert all(not re.search(r"[0-9]", label) for _, label in KINDS)


def test_masking_keeps_policy_decisions() -> None:
    safe_positive = [
        source for source, _ in POSITIVES if not re.search(r"\b(?:kart|bilet|ne kadar)\b", source, re.I)
    ]
    for source in [case["text"] for case in negatives()] + safe_positive:
        masked = mask(source)[0]
        assert policy.refuses(source) == policy.refuses(masked)
        assert policy.emergency_intent(source) == policy.emergency_intent(masked)
    numeric = "4111111111111111 ne kadar?"
    assert policy.refuses(numeric) is False
    assert policy.refuses("[KART NO] ne kadar?") is True


def test_mask_turn_masks_history_but_counts_the_message() -> None:
    history = [f"{'x' * (8000 - len(' kart ') - 16)} kart 4111111111111111" for _ in range(40)]
    assert all(len(item) == 8000 for item in history)
    turn = mask_turn(f"TC {TCKN}", history)
    assert isinstance(turn, MaskedTurn)
    assert turn.message == "TC [TC KİMLİK]"
    assert len(turn.history) == 40 and all(item.endswith("kart [KART NO]") for item in turn.history)
    assert turn.count == 1 and turn.kinds == ("TC KİMLİK",)
    assert pii_final_fields(turn) == {"masked_count": 1, "masked_kinds": ["TC KİMLİK"]}
    assert set(pii_final_fields(turn)) == {"masked_count", "masked_kinds"}


def test_js_mask_matches_python(tmp_path) -> None:
    from test_static_a11y import node_json

    texts = [source for source, _ in POSITIVES] + [case["text"] for case in negatives()]
    chars = [chr(code) for code in range(0x10000) if chr(code).isspace()] + ["\ufeff"]
    values = node_json(
        tmp_path,
        {"pii": "js/pii_badge.js"},
        f"const texts=JSON.parse({json.dumps(json.dumps(texts, ensure_ascii=False))});"
        f"const chars=JSON.parse({json.dumps(json.dumps(chars, ensure_ascii=False))});"
        "console.log(JSON.stringify({masks:texts.map(x=>pii.maskPii(x)),folds:chars.map(x=>pii.foldKeepLength(x))}));",
    )
    assert [(item["masked"], item["count"]) for item in values["masks"]] == [mask(text) for text in texts]
    assert values["folds"] == [fold_keep_length(char) for char in chars]


def test_badge_and_warning_markup(tmp_path) -> None:
    from test_static_a11y import node_json

    values = node_json(
        tmp_path,
        {"pii": "js/pii_badge.js"},
        "console.log(JSON.stringify({zero:pii.badgeMarkup(0,[]),"
        "device:pii.badgeMarkup(1,['TC KİMLİK'],'device'),"
        "server:pii.badgeMarkup(2,['TC KİMLİK','IBAN','<b>x</b>'],'server'),"
        "warning:pii.warningMarkup(),deviceNote:pii.PII_NOTE_DEVICE,serverNote:pii.PII_NOTE_SERVER}));",
    )
    assert values["zero"] == ""
    assert "TC KİMLİK" in values["device"]
    assert values["deviceNote"].replace("'", "&#39;") in values["device"]
    assert "cihazınızdan" not in values["device"].lower()
    assert values["serverNote"] in values["server"] and "<b>x</b>" not in values["server"]
    assert values["server"].count('class="tag"') == 2
    assert values["warning"].startswith('<p class="chat-hint pii-warning" id="pii-warning">')
    assert "Soruya TC kimlik" in values["warning"]


def test_pii_badge_js_static_rules() -> None:
    path = REPO_ROOT / "src/nabiz/console/static/js/pii_badge.js"
    source = path.read_text(encoding="utf-8")
    forbidden_items = (
        "fetch", "XMLHttpRequest", "sendBeacon", "WebSocket", "localStorage", "sessionStorage",
        "indexedDB", "console.", "./api.js", "./config.js",
    )
    for forbidden in forbidden_items:
        assert forbidden not in source
    assert "cihazınızdan" not in source.lower()
    assert "addEventListener('submit'" in source and ", true)" in source
    submit_body = source.split("function onSubmit", 1)[1].split("\n  }", 1)[0]
    assert submit_body.index("pending = null") < submit_body.index("maskPii(")
    assert "insertAdjacentHTML('beforebegin'" in source
    assert "new win.MutationObserver" in source
    imports = re.findall(r"from '([^']+)'", source)
    assert imports == ["./format.js", "./icons.js", "./disclosure.js"]
    assert "\u2014" not in source and "\u2013" not in source
    assert not re.search(r"\bETA\b", source)
    assert len(source.splitlines()) <= 300


def test_owned_files_pass_plate_and_email_guardrails() -> None:
    spec = importlib.util.spec_from_file_location("guardrails", REPO_ROOT / "scripts/guardrails.py")
    guardrails = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = guardrails
    spec.loader.exec_module(guardrails)
    paths = [
        REPO_ROOT / "src/nabiz/console/pii_guard.py",
        REPO_ROOT / "src/nabiz/console/static/js/pii_badge.js",
        REPO_ROOT / "tests/test_pii_guard.py",
        FIXTURES_DIR / "pii_negatives.jsonl",
    ]
    for path in paths:
        source = path.read_text(encoding="utf-8")
        for line in source.splitlines():
            assert not any(guardrails._could_be_a_real_plate(match) for match in guardrails.PLATE_SHAPED_VALUE.finditer(line))
        assert not guardrails.EMAIL.search(source)
    python_source = paths[0].read_text(encoding="utf-8")
    assert guardrails._python_plate_findings(python_source, str(paths[0])) == []
    for line in paths[1].read_text(encoding="utf-8").splitlines():
        assert guardrails._PLATE_KEY_IN_TEXT.search(line) is None


def test_chat_turn_masks_before_the_model(monkeypatch, caplog) -> None:
    chat_path = REPO_ROOT / "src/nabiz/console/chat.py"
    if "pii_guard" not in chat_path.read_text(encoding="utf-8"):
        pytest.skip("B01 chat.py'ye pii_guard'ı bağlamadı")
    from test_console_chat import CLOUD, FakeModel, client_for, events, nabiz, reply, tool_call, unlimited

    from nabiz.agent import llm

    fake = FakeModel(
        reply(tool_calls=[tool_call("metro_status")]),
        reply("Metro hattında bir çalışma duyurusu var."),
    )
    monkeypatch.setattr(llm, "chat", fake)
    caplog.set_level("DEBUG")
    message = f"TC {TCKN} metro arızası var mı?"
    fixture = nabiz.__wrapped__()
    test_nabiz = next(fixture)
    try:
        with client_for(test_nabiz, CLOUD, unlimited()) as client:
            response = client.post(
                "/api/chat",
                json={"message": message, "needs": [], "history": [{"role": "user", "content": "kartım 4111111111111111"}]},
            )
    finally:
        fixture.close()
    stream = events(response.text)
    final = stream[-1][1]
    contents = [item["content"] for call in fake.calls for item in call["messages"] if item.get("content")]
    assert all(TCKN not in content and "4111111111111111" not in content for content in contents)
    # B01 hands the earlier questions over as their own user message, before the question.
    assert any("[TC KİMLİK]" in content for content in contents) and any("[KART NO]" in content for content in contents)
    assert final["masked_count"] == 1 and final["masked_kinds"] == ["TC KİMLİK"]
    assert TCKN not in caplog.text and "4111111111111111" not in caplog.text


def test_mount_without_chat_log_still_masks(tmp_path) -> None:
    from test_static_a11y import node_json

    message = f"TC {TCKN}"
    values = node_json(
        tmp_path,
        {"pii": "js/pii_badge.js"},
        "const makeDoc=(ids)=>({getElementById:(id)=>ids[id]||null});"
        "const form={id:'chat-form',html:'',insertAdjacentHTML(where,value){this.html+=where+value;}};"
        "const attrs={'aria-describedby':'chat-hint chat-count-live'};"
        "const input={id:'chat-input',value:'',getAttribute(key){return attrs[key]||null;},"
        "setAttribute(key,value){attrs[key]=value;}};"
        "const listeners=[];const win={addEventListener(type,fn,capture){listeners.push({type,fn,capture});}};"
        "const doc=makeDoc({'chat-form':form,'chat-input':input});pii.mountPiiBadge(doc,win);"
        f"input.value={json.dumps(message)};listeners[0].fn({{target:{{id:'chat-form'}}}});"
        "const emptyListeners=[];pii.mountPiiBadge(makeDoc({}),{addEventListener(...args){emptyListeners.push(args);}});"
        "console.log(JSON.stringify({value:input.value,html:form.html,described:attrs['aria-describedby'],listeners:listeners.length,capture:listeners[0].capture,empty:emptyListeners.length}));",
    )
    assert values["value"] == "TC [TC KİMLİK]"
    assert "pii-warning" in values["html"] and "beforeend" in values["html"]
    assert values["described"] == "chat-hint chat-count-live pii-warning"
    assert values["listeners"] == 1 and values["capture"] is True and values["empty"] == 0
