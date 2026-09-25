"""Static contract checks for the citizen card share and save module."""

from __future__ import annotations

import re

from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
DASHES = (chr(0x2014), chr(0x2013))


def read(path: str) -> str:
    return (STATIC / path).read_text(encoding="utf-8")


def test_share_assets_exist_and_the_page_loads_the_module() -> None:
    assert (STATIC / "js" / "share.js").is_file()
    assert (STATIC / "css" / "share.css").is_file()
    assert 'src="/js/share.js"' in read("index.html")


def test_share_module_imports_resolve() -> None:
    source = read("js/share.js")
    for spec in re.findall(r"""from\s+['"](\.[^'"]+)['"]""", source):
        assert (STATIC / "js" / spec.removeprefix("./")).is_file(), f"share.js imports {spec}, which is missing"


def test_share_labels_have_no_long_dash() -> None:
    source = read("js/share.js")
    for label in ("Kartı kopyala", "Paylaş", "Bağlantıyı kopyala", "Bugün listeme ekle", "Kaldır"):
        assert label in source
    for path in ("js/share.js", "css/share.css"):
        for dash in DASHES:
            assert dash not in read(path), f"{path} carries a dash"


def test_question_links_are_validated_and_auto_submit() -> None:
    source = read("js/share.js")
    assert "new URLSearchParams(location.search)" in source
    assert "get('q')" in source
    assert "encodeURIComponent" in source
    assert "needs=${encodeURIComponent" in source
    assert "form.requestSubmit()" in source


def test_card_actions_survive_refresh_and_use_browser_share_apis() -> None:
    source = read("js/share.js")
    assert "new MutationObserver" in source
    assert all(f"id: '{host}'" in source for host in ("cards", "arrival", "alternative"))
    assert "navigator.clipboard?.writeText" in source
    assert "navigator.share" in source
    assert "AbortError" in source


def test_saved_cards_stay_bounded_and_do_not_write_the_profile() -> None:
    source = read("js/share.js")
    assert "nabiz.saved-cards.v1" in source
    assert "slice(0, 12)" in source
    assert "setItem(SAVED_KEY" in source
    assert "writeProfile" not in source
