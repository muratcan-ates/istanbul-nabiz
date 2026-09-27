"""P14 staging: the six page catalogues in docs/i18n/ keep tr.json's contract, and the unlinked RTL sheet
touches nothing on a left-to-right page."""

from __future__ import annotations

import json
import re

import pytest
from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
SOURCE = STATIC / "i18n" / "tr.json"
STAGING = REPO_ROOT / "docs" / "i18n"
RTL_CSS = STATIC / "css" / "rtl.css"
DIRECTION = {"de": "ltr", "ru": "ltr", "ar": "rtl", "fa": "rtl", "fr": "ltr", "es": "ltr"}
LANGS = sorted(DIRECTION)
DASHES = ("—", "–")
PLACEHOLDER = re.compile(r"\{\w+\}")
TAG = re.compile(r"</?[A-Za-z][^<>]*>")
#: Institutions, the product and the phone numbers stay as they are in every language (P14 brief).
KEPT_NAMES = ("İBB", "İETT", "Metro İstanbul", "İSKİ", "İGDAŞ", "Nabız", "153", "112")
RTL_SCOPE = ('[dir="rtl"]', ":dir(rtl)")
RTL_CSS_MAX_LINES = 300


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _values(value):
    return value if isinstance(value, list) else [value]


def _text(value) -> str:
    return " ".join(_values(value))


def test_the_staging_folder_holds_the_six_languages() -> None:
    assert sorted(path.stem for path in STAGING.glob("*.json")) == LANGS


@pytest.mark.parametrize("lang", LANGS)
def test_catalogue_is_json_with_the_source_keys_in_order(lang: str) -> None:
    assert list(_read(STAGING / f"{lang}.json")) == list(_read(SOURCE))


@pytest.mark.parametrize("lang", LANGS)
def test_meta_names_the_language_and_its_direction(lang: str) -> None:
    catalogue = _read(STAGING / f"{lang}.json")
    assert catalogue["meta.lang"] == lang
    assert catalogue["meta.dir"] == DIRECTION[lang]


@pytest.mark.parametrize("lang", LANGS)
def test_every_value_is_filled_and_shaped_like_the_source(lang: str) -> None:
    """i18n.js writes a list value text node by text node ('segments'), so a list keeps its length."""
    catalogue = _read(STAGING / f"{lang}.json")
    for key, source in _read(SOURCE).items():
        target = catalogue[key]
        assert isinstance(target, type(source)), key
        if isinstance(source, list):
            assert len(target) == len(source), key
        assert all(isinstance(text, str) and text.strip() for text in _values(target)), key


@pytest.mark.parametrize("lang", LANGS)
def test_placeholders_tags_and_kept_names_survive(lang: str) -> None:
    catalogue = _read(STAGING / f"{lang}.json")
    for key, source in _read(SOURCE).items():
        before, after = _text(source), _text(catalogue[key])
        assert sorted(PLACEHOLDER.findall(after)) == sorted(PLACEHOLDER.findall(before)), key
        assert sorted(TAG.findall(after)) == sorted(TAG.findall(before)), key
        for name in KEPT_NAMES:
            assert name not in before or name in after, (key, name)


@pytest.mark.parametrize("lang", LANGS)
def test_no_em_or_en_dash(lang: str) -> None:
    for key, value in _read(STAGING / f"{lang}.json").items():
        assert not any(dash in text for text in _values(value) for dash in DASHES), key


def _top_level_split(selectors: str) -> list[str]:
    parts, depth, start = [], 0, 0
    for index, char in enumerate(selectors):
        depth += {"(": 1, ")": -1}.get(char, 0)
        if char == "," and depth == 0:
            parts.append(selectors[start:index])
            start = index + 1
    return [part.strip() for part in [*parts, selectors[start:]] if part.strip()]


def test_rtl_sheet_scopes_every_rule_to_rtl() -> None:
    source = RTL_CSS.read_text(encoding="utf-8")
    assert len(source.splitlines()) <= RTL_CSS_MAX_LINES
    css = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    selectors = []
    for prelude in (match.strip() for match in re.findall(r"([^{};]+)\{", css)):
        if prelude.startswith("@"):
            # A wrapper holds scoped rules; an at-rule that is a rule itself (@font-face, @import) is not one.
            assert prelude.split()[0] in {"@media", "@supports"}, prelude
            continue
        selectors.extend(_top_level_split(prelude))
    assert len(selectors) >= 20
    for selector in selectors:
        assert any(scope in selector for scope in RTL_SCOPE), selector
    assert "@import" not in css
