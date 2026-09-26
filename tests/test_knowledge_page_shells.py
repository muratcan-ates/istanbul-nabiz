"""Page shells that hid real text from the parser (E39 ingest, 26 Sep): an ASP.NET form, a Nuxt attribute.

The fixtures are short cuts of pages the owner's ingest cached (their comments name the URL); nothing in
them is written by hand except the marked cuts.
"""

from __future__ import annotations

import pathlib

from ibb_mcp.knowledge.parsers import PAGE_FORM_MIN_CHARS, html_to_blocks

FIXTURES = pathlib.Path(__file__).parent / "fixtures/knowledge"


def _text(page) -> str:
    return "\n".join(block.text for block in page.blocks)


def test_a_page_wrapped_in_one_form_is_read() -> None:
    page = html_to_blocks((FIXTURES / "sehirhatlari_sss_kesit.html").read_text(encoding="utf-8"))
    text = _text(page)
    assert page.parser_status == "ok"
    assert "1. Hangi Koşullarda Seferler İptal Edilmektedir?" in text
    assert "hava muhalefeti" in text and "ALO 153" in text
    assert {block.section_title for block in page.blocks if "hava muhalefeti" in block.text} == {"Sıkça Sorulan Sorular"}


def test_the_page_form_reading_drops_menus_link_lists_and_the_cookie_box() -> None:
    text = _text(html_to_blocks((FIXTURES / "sehirhatlari_sss_kesit.html").read_text(encoding="utf-8")))
    for boilerplate in ("Kişisel Verilerin Korunması", "Kabul Et", "Geri Dön", "A-", "A+", "Başkanın Mesajı", "İç Hat Seferleri"):
        assert boilerplate not in text


def test_a_form_inside_a_readable_page_is_still_skipped() -> None:
    page = html_to_blocks(
        "<html><body><p>Su kesintisi duyuruları bu sayfada yayımlanır.</p>"
        "<form><p>Arama kutusu metni</p><label>Ara</label></form></body></html>"
    )
    assert page.parser_status == "ok"
    assert "Arama kutusu" not in _text(page)


def test_a_form_page_with_too_little_text_stays_unsupported() -> None:
    page = html_to_blocks("<html><body><form id='aspnetForm'><h1>Başlık</h1><p>Kısa.</p></form></body></html>")
    assert len("Kısa.") < PAGE_FORM_MIN_CHARS
    assert page.parser_status == "unsupported_js" and not page.blocks


def test_a_form_page_keeps_list_items_with_their_own_text() -> None:
    items = "".join(f"<li>Tel: <a href='tel:153'>ALO 153</a> hattı {n}. madde, her gün 24 saat açıktır.</li>" for n in range(8))
    page = html_to_blocks(f"<html><body><form><ul>{items}</ul><ul><li><a href='/x'>Menü</a></li></ul></form></body></html>")
    text = _text(page)
    assert page.parser_status == "ok" and "Tel: ALO 153 hattı 0. madde" in text
    assert "Menü" not in text


def test_nuxt_vue_markdown_source_attribute_is_read() -> None:
    page = html_to_blocks((FIXTURES / "iski_vue_markdown_kesit.html").read_text(encoding="utf-8"))
    text = _text(page)
    assert page.parser_status == "ok"
    assert "Tüzel kişiler için yetki belgesi ve kaşe." in text
    assert "Gerekli Belgeler:" in text
    assert {block.section_title for block in page.blocks} == {"Konut – İşyeri Aboneliği"}
    assert "<p" not in text and "&amp;" not in text


def test_vue_markdown_plain_markdown_lines_become_blocks() -> None:
    page = html_to_blocks(
        "<html><body><vue-markdown source='Birinci satır metni.\nİkinci satır metni.'></vue-markdown></body></html>"
    )
    assert [block.text for block in page.blocks] == ["Birinci satır metni.", "İkinci satır metni."]
