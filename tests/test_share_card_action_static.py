"""P00 D2a: a chat card's "share" action sends only the card title and an https source, never anything else."""

from __future__ import annotations

import re

from conftest import REPO_ROOT

SHARE = REPO_ROOT / "src" / "nabiz" / "console" / "static" / "js" / "share.js"


def chat_card_block() -> str:
    source = SHARE.read_text(encoding="utf-8")
    start = source.index("function chatCardArticle(")
    return source[start:source.index("function makeSavedSection()")]


def test_share_listens_for_the_card_action_and_releases_it() -> None:
    source = SHARE.read_text(encoding="utf-8")
    assert "import { releaseCardAction } from './chat_card_actions.js';" in source
    block = chat_card_block()
    assert "document.addEventListener('nabiz:card-action'" in block
    assert "detail.action !== 'share' || detail.type === 'memory'" in block
    assert "event.preventDefault();" in block
    assert "releaseCardAction(detail.card_id, detail.action);" in block


def test_only_the_title_and_an_https_source_leave_the_page() -> None:
    block = chat_card_block()
    assert "/^https:\\/\\//.test(" in block
    assert "{ title, url: link.getAttribute('href') }" in block
    assert "navigator.share(shared)" in block and "copyToClipboard(shared.url, status)" in block
    for leak in ("readProfile", "currentQuestion", "currentNeeds", "cardCopyText", "cardDetails", "localStorage",
                 "buildShareUrl", "geolocation", "memory_store", "conversation"):
        assert leak not in block, leak
    assert not re.search(r"\.body\b|answer", block)
