from __future__ import annotations

import asyncio
import datetime as dt

from test_knowledge_store import seed_page

from ibb_mcp.knowledge.embed import HashingEmbedder
from ibb_mcp.knowledge.guardrails import clean_for_display, mask_personal, verify_evidence
from ibb_mcp.knowledge.retrieve import search
from ibb_mcp.knowledge.store import KnowledgeStore


def test_fabricated_evidence_id_is_dropped(tmp_path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, "Su aboneliği başvurusu resmî kaynaktadır.")
    hits = asyncio.run(search(store, "su aboneliği", embedder=HashingEmbedder()))
    verdict = verify_evidence(["forged"], hits)
    assert verdict.blocked and verdict.dropped == ["forged"]


def test_no_valid_evidence_blocks() -> None:
    assert verify_evidence([], []).blocked


def test_unsupported_sentence_is_dropped() -> None:
    from ibb_mcp.knowledge.answer import drop_unsupported_sentences
    from ibb_mcp.knowledge.retrieve import Hit

    hit = Hit(
        "c",
        "q",
        "https://www.iski.istanbul",
        "İSKİ",
        "Su aboneliği için başvuru yapılır.",
        1,
        dt.datetime.now(dt.UTC).isoformat(),
        None,
        "ISKI",
        None,
        None,
    )
    kept = drop_unsupported_sentences("Su aboneliği için başvuru yapılır. Evler yarın ücretsiz olacak.", [hit])
    assert kept == "Su aboneliği için başvuru yapılır."


def test_xss_payload_is_cleaned() -> None:
    assert clean_for_display("Merhaba <script>alert(1)</script><b>kent</b>") == "Merhaba kent"


def test_allowlist_accepts_ibb_gov_tr_subdomains_and_iski_istanbul() -> None:
    from ibb_mcp.knowledge.ingest import is_allowed_url

    assert is_allowed_url("https://data." + "ibb" + ".gov.tr/dataset")
    assert is_allowed_url("https://www." + "iski" + ".istanbul/abonelik")


def test_allowlist_rejects_iski_gov_tr_and_off_list_hosts() -> None:
    from ibb_mcp.knowledge.ingest import is_allowed_url

    assert not is_allowed_url("https://www." + "iski" + ".gov.tr/abonelik")
    assert not is_allowed_url("https://evil.invalid/redirect")
    assert not is_allowed_url("file:///etc/passwd")


def test_evidence_from_inactive_document_is_rejected(tmp_path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    url = "https://www.iski.istanbul/abonelik"
    seed_page(store, "Su aboneliği başvurusu resmî kaynaktadır.", url)
    hits = asyncio.run(search(store, "su aboneliği", embedder=HashingEmbedder()))
    store.mark_inactive(url)
    verdict = verify_evidence([hits[0].quote_id], hits, store=store)
    assert verdict.blocked


def test_email_and_eleven_digit_value_are_masked() -> None:
    synthetic_email = "ad" + "@" + "example.com"
    assert mask_personal(f"{synthetic_email} 12345678901") == "[gizlendi] [gizlendi]"
