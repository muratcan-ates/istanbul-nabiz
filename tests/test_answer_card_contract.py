from __future__ import annotations

import datetime as dt
import html as html_lib
import json
import re
import shutil
import subprocess
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from conftest import REPO_ROOT
from test_console_chat import (
    FEE_QUESTION,
    FEE_QUOTE,
    METRO_QUESTION,
    SERVICE_QUESTION,
    SERVICE_QUOTE,
    ask,
    client_for,
    nabiz,  # noqa: F401
    with_index,
)

from ibb_mcp.knowledge.answer import UNKNOWN_TEXT
from nabiz.agent import llm
from nabiz.console.policy import REFUSAL_TEXT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
CARD_JS = STATIC / "js" / "answer_card.js"
CARD_CSS = STATIC / "css" / "answer_card.css"


def _render(tmp_path: Path, final: dict, options: dict | None = None) -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    payload = json.dumps(json.dumps(final), ensure_ascii=True)
    opts = json.dumps(json.dumps(options or {}), ensure_ascii=True)
    harness = tmp_path / "answer_card_harness.mjs"
    harness.write_text(
        f"import {{ renderAnswerCard }} from {json.dumps(CARD_JS.as_uri())};\n"
        f"const final = JSON.parse({payload});\n"
        f"const options = JSON.parse({opts});\n"
        "console.log(JSON.stringify(renderAnswerCard(final, options)));\n",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _final_for(context, question: str) -> dict:
    with client_for(context, llm.LlmConfig()) as client:
        _, final = ask(client, question)
    return final


def test_card_sentences_match_the_server() -> None:
    source = CARD_JS.read_text(encoding="utf-8")
    refusal = re.search(r'^const REFUSAL_TEXT = "([^"]*)";$', source, re.M)
    unknown = re.search(r'^const UNKNOWN_TEXT = "([^"]*)";$', source, re.M)
    assert refusal and refusal.group(1) == REFUSAL_TEXT
    assert unknown and unknown.group(1) == UNKNOWN_TEXT


def test_quote_only_final_carries_what_the_card_reads(
    nabiz,  # noqa: F811 - the imported fixture, requested by name
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with_index(monkeypatch, tmp_path, FEE_QUOTE)
    final = _final_for(nabiz, FEE_QUESTION)
    assert final["mode"] == "quote_only"
    citation = final["citations"][0]
    assert set(citation) >= {"url", "title", "quote", "fetched_at", "source_updated_at", "institution", "source"}
    assert citation["quote"] == FEE_QUOTE
    assert citation["source"] == "local:knowledge"


def test_knowledge_answer_final_carries_what_the_card_reads(
    nabiz,  # noqa: F811 - the imported fixture, requested by name
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with_index(monkeypatch, tmp_path, SERVICE_QUOTE)
    final = _final_for(nabiz, SERVICE_QUESTION)
    assert final["mode"] == "answer"
    citation = final["citations"][0]
    assert set(citation) >= {"url", "title", "quote", "fetched_at", "source_updated_at", "institution", "source"}
    assert citation["quote"] == SERVICE_QUOTE
    assert citation["source"] == "local:knowledge"


def test_refused_final_is_the_fixed_sentence_without_citations(
    nabiz,  # noqa: F811 - the imported fixture, requested by name
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(tmp_path / "missing-knowledge.db"))
    monkeypatch.delenv("NABIZ_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NABIZ_LLM_API_KEY", raising=False)
    final = _final_for(nabiz, "Otopark cezası ne kadar?")
    assert final["mode"] == "refused"
    assert final["answer"] == REFUSAL_TEXT
    assert final["citations"] == []


def test_tool_citations_carry_mode_and_age(
    nabiz,  # noqa: F811 - the imported fixture, requested by name
) -> None:
    metro = _final_for(nabiz, METRO_QUESTION)
    assert metro["citations"]
    assert set(metro["citations"][0]) >= {"source", "url", "observed_at", "age_s", "mode"}
    assert metro["citations"][0]["mode"] == "recorded"
    # Since the 26 Sep Metro equipment recording (93c16bf) the lift answer is recorded too; the
    # no-recording case (mode "unknown", no age) lives in test_console_chat.
    station = _final_for(nabiz, "Kartal metro istasyonunda asansör var mı?")
    lift = [item for item in station["citations"] if item.get("source") == "metro_equipment"]
    assert lift and all(item["mode"] == "recorded" for item in lift)
    assert all(item["observed_at"] is not None for item in lift)


def test_card_files_follow_the_page_rules() -> None:
    js = CARD_JS.read_text(encoding="utf-8")
    css = CARD_CSS.read_text(encoding="utf-8")
    dash = re.compile("[\\u2013\\u2014]")
    assert not dash.search(js + css)
    assert not re.search(r"\bETA\b", js + css, re.I)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(", css)
    for forbidden in (
        "fetch(", "localStorage", "sessionStorage", "XMLHttpRequest", "speechSynthesis",
        "data-card-act", "data-persona",
    ):
        assert forbidden not in js


def _token_block(css: str, selector: str) -> dict[str, str]:
    match = re.search(rf"(?m)^{re.escape(selector)}\s*{{([^{{}}]*)}}", css)
    assert match, f"missing token block: {selector}"
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", match.group(1)))


def _resolve_color(name: str, tokens: dict[str, str], seen: frozenset[str] = frozenset()) -> str:
    assert name in tokens and name not in seen, f"unresolved or cyclic token {name}"
    value = tokens[name].strip()
    ref = re.fullmatch(r"var\((--[\w-]+)\)", value)
    return _resolve_color(ref.group(1), tokens, seen | {name}) if ref else value


def _rgb(value: str) -> tuple[float, float, float]:
    raw = re.fullmatch(r"#([0-9a-fA-F]{6})", value)
    assert raw, f"expected a resolved six-digit token color, got {value}"
    digits = raw.group(1)
    return tuple(int(digits[index:index + 2], 16) / 255 for index in (0, 2, 4))


def _luminance(rgb: tuple[float, float, float]) -> float:
    channels = tuple(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in rgb)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(foreground: str, background: str) -> float:
    first, second = sorted((_luminance(_rgb(foreground)), _luminance(_rgb(background))), reverse=True)
    return (first + 0.05) / (second + 0.05)


def test_card_token_pairs_meet_wcag_aa() -> None:
    css = (STATIC / "css" / "tokens.css").read_text(encoding="utf-8")
    light = _token_block(css, ":root")
    dark = {**light, **_token_block(css, ':root[data-theme="dark"]')}
    pairs = (
        ("--text", "--surface"),
        ("--text-muted", "--surface"),
        ("--text-muted", "--surface-raised"),
        ("--link", "--surface"),
        ("--info", "--info-wash"),
        ("--warn", "--warn-wash"),
    )
    for theme in (light, dark):
        for foreground, background in pairs:
            ratio = _contrast(_resolve_color(foreground, theme), _resolve_color(background, theme))
            assert ratio >= 4.5, f"{foreground} on {background}: {ratio:.2f}:1"


def test_card_renders_a_quote_only_final(
    nabiz,  # noqa: F811 - the imported fixture, requested by name
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with_index(monkeypatch, tmp_path, FEE_QUOTE)
    final = _final_for(nabiz, FEE_QUESTION)
    html = _render(tmp_path, final)
    today = dt.datetime.now(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y")
    assert "Kaynakta geçen ifade" in html and FEE_QUOTE in html
    assert 'data-card="quote"' in html
    assert 'class="quote-text quote-exact"' in html and 'data-er-skip' in html
    assert '<p class="ac-source-line">İSKİ</p>' in html
    assert html.count("alındı: ") == 1 and f"alındı: {today}" in html
    assert html.count("İSKİ hizmet bilgisi") == 1
    assert "Resmî sayfadan alıntı" in html and "Resmî kaynağı aç" in html
    assert 'href="tel:153"' in html
    assert "son güncelleme" not in html and "Doğrulamak için 153" not in html and "Dinle" not in html


def test_model_text_never_enters_the_quote_box(tmp_path: Path) -> None:
    final = {
        "mode": "answer",
        "author": "model",
        "answer_text": "MODEL_CUMLESI",
        "citations": [{
            "source": "local:knowledge", "url": "https://www.iski.istanbul/abonelik",
            "title": "İSKİ hizmet bilgisi", "quote": "KAYNAK_CUMLESI",
            "fetched_at": "2026-09-25T12:00:00+03:00", "source_updated_at": None, "institution": "ISKI",
        }],
    }
    html = _render(tmp_path, final)
    box = html[html.index('<div class="quote-box"'):html.index("</div>", html.index('<div class="quote-box"'))]
    assert "MODEL_CUMLESI" not in box and "KAYNAK_CUMLESI" in box
    assert '<section class="answer-short ac-short">' in html and '<p data-er-target>' in html


def test_last_update_is_shown_only_when_the_page_gives_it(tmp_path: Path) -> None:
    base = {
        "mode": "quote_only", "citations": [{
            "source": "local:knowledge", "url": "https://www.iski.istanbul/abonelik",
            "title": "İSKİ hizmet bilgisi", "quote": "KAYNAK_CUMLESI",
            "fetched_at": "2026-09-25T12:00:00+03:00", "institution": "ISKI",
        }],
    }
    updated = _render(tmp_path, {**base, "citations": [{
        **base["citations"][0], "source_updated_at": "2026-09-01T00:00:00+03:00",
    }]})
    missing = _render(tmp_path, {**base, "citations": [{
        **base["citations"][0], "source_updated_at": None,
    }]})
    assert "İSKİ · son güncelleme: 01.09.2026" in updated
    assert "son güncelleme" not in missing


def test_old_evidence_says_confirm_with_153(tmp_path: Path) -> None:
    now = int(dt.datetime.fromisoformat("2026-09-25T12:00:00+00:00").timestamp() * 1000)
    citation = {
        "source": "local:knowledge", "url": "https://www.iski.istanbul/abonelik",
        "title": "İSKİ hizmet bilgisi", "quote": "KAYNAK_CUMLESI", "institution": "ISKI",
        "fetched_at": "2024-01-01T00:00:00Z", "source_updated_at": "2025-08-01T00:00:00Z",
    }
    stale = _render(tmp_path, {"mode": "quote_only", "citations": [citation]}, {"now": now})
    recent = _render(tmp_path, {"mode": "quote_only", "citations": [{
        **citation, "source_updated_at": "2026-08-26T00:00:00Z",
    }]}, {"now": now})
    fetched_only = _render(tmp_path, {"mode": "quote_only", "citations": [{
        **citation, "source_updated_at": None,
    }]}, {"now": now})
    assert "Eski olabilir, 153 ile teyit edin" in stale
    assert "Eski olabilir, 153 ile teyit edin" not in recent
    assert "Eski olabilir, 153 ile teyit edin" not in fetched_only


def test_unrecognised_mode_is_left_to_the_old_card(tmp_path: Path) -> None:
    assert _render(tmp_path, {"mode": "guard", "answer_text": "X"}) == ""
    assert _render(tmp_path, {"mode": "redirect", "emergency": False}) == ""


def test_tool_sources_are_labelled_honestly(tmp_path: Path) -> None:
    def card(citation: dict) -> str:
        return _render(tmp_path, {"mode": "answer", "answer_text": "Yanıt", "citations": [citation]})

    live = card({"source": "metro_status", "mode": "live", "age_s": 120, "url": "https://example.invalid"})
    recorded = card({
        "source": "metro_status", "mode": "recorded", "observed_at": "2026-09-25T12:00:00Z",
        "age_s": 120, "url": "https://example.invalid",
    })
    unknown = card({"source": "metro_status", "mode": "unknown", "age_s": None})
    assert "Canlı veri · 2 dk" in live
    assert "Kayıtlı veri" in recorded and "Canlı" not in recorded
    assert "Veri yaşı bilinmiyor" in unknown and "Canlı" not in unknown


def test_unknown_and_refused_cards_are_the_fixed_sentence(
    nabiz,  # noqa: F811 - the imported fixture, requested by name
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(tmp_path / "missing-knowledge.db"))
    monkeypatch.delenv("NABIZ_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NABIZ_LLM_API_KEY", raising=False)
    final = _final_for(nabiz, "Otopark cezası ne kadar?")
    refused = _render(tmp_path, final)
    unknown = _render(tmp_path, {"mode": "unknown", "answer_text": "SUNUCU_METNI"})
    assert REFUSAL_TEXT in html_lib.unescape(refused) and 'data-card="refused"' in refused
    assert UNKNOWN_TEXT in html_lib.unescape(unknown) and 'data-card="unknown"' in unknown
    for html in (refused, unknown):
        assert 'class="ac-fixed" data-er-skip' in html
        assert 'href="tel:153"' in html and 'class="chat-foot"' in html
        assert "quote-box" not in html and "SUNUCU_METNI" not in html


def test_emergency_final_is_left_to_the_old_card(tmp_path: Path) -> None:
    assert _render(tmp_path, {"mode": "redirect", "emergency": True}) == ""


def test_tool_answer_keeps_the_short_answer_outside_any_quote_box(
    nabiz,  # noqa: F811 - the imported fixture, requested by name
    tmp_path: Path,
) -> None:
    final = _final_for(nabiz, METRO_QUESTION)
    html = _render(tmp_path, final)
    assert '<section class="answer-short ac-short">' in html
    assert 'data-er-target' in html
    assert 'class="quote-box"' not in html
