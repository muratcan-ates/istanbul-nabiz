from __future__ import annotations

from ibb_mcp.knowledge.chunking import HARD_MAX_CHARS, PageBlock, chunk_blocks


def test_chunk_never_spans_two_pages() -> None:
    chunks = chunk_blocks(
        [PageBlock("Su aboneliği başvurusu burada açıklanır.", 1), PageBlock("İSKİ iletişim kanalları burada yazılıdır.", 2)]
    )
    assert [chunk.page_number for chunk in chunks] == [1, 2]


def test_paragraphs_pack_together_but_sections_stay_separate() -> None:
    first = "Su başvurusu için gerekli belgeler resmî sayfada sıralanmıştır. " * 20
    second = "Fatura itirazı ilgili kurum ekranından iletilir. " * 20
    chunks = chunk_blocks([PageBlock(first, 1, "Başvuru"), PageBlock(second, 1, "İtiraz")])
    assert {chunk.section_title for chunk in chunks} == {"Başvuru", "İtiraz"}
    assert all(not ("gerekli belgeler" in chunk.text and "fatura itirazı" in chunk.text) for chunk in chunks)


def test_long_text_splits_with_overlap() -> None:
    sentence = "İstanbul hizmet başvuru bilgisi doğrulanmış resmî kaynak metninde yer alır. "
    chunks = chunk_blocks([PageBlock(sentence * 180, 3, "Başvuru")])
    assert len(chunks) > 1
    assert all(len(chunk.text) <= HARD_MAX_CHARS for chunk in chunks)
    assert all(a.text[-180:] in b.text for a, b in zip(chunks, chunks[1:], strict=False))
    for chunk in chunks:
        for quote in chunk.quotes:
            assert chunk.text.find(quote.exact_text) >= 0
