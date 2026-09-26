"""Which questions ask what data İBB publishes: those go to the open-data catalogue (``ibb_datasets_search``).

"İBB'nin otopark verisi var mı?" is not a parking question: it names car parks, but it asks whether a
dataset exists. Sent down the parking path it asked for a place and answered with none. So a question
that asks about data itself ("açık veri", "veri seti", "X verisi var mı") is routed here first, and
the catalogue search drops the words that only ask ("veri", "var", "mı") and searches the subject.

A question about *requesting* data ("veri talebi nasıl yapılır?") is a service question: it stays on
the service-page path, which holds the portal's own request page.
"""

from __future__ import annotations

from typing import Any

from ibb_mcp.text import normalize_tr

#: Folded phrases (``ibb_mcp.text.normalize_tr``) that ask about data, matched as substrings.
DATA_PHRASES = (
    "acik veri", "veri seti", "veri setleri", "veriseti", "verisetleri", "verisi var", "verileri var",
    "hangi veri", "ne verisi", "verisi yayim", "verileri yayim", "veri portal", "data ibb",
    "open data", "dataset", "data set",
)  # fmt: skip
#: Folded words that make it a service question about the portal: a data request, an application.
SERVICE_WORDS = ("talep", "talebi", "talebin", "istegi", "istek", "basvur")
#: The portal's nine categories, folded, to their titles (``ibb_mcp.catalog.CATEGORIES``).
_CATEGORIES = {
    normalize_tr(name): name
    for name in (
        "Bilgi ve İletişim Teknolojileri", "Enerji", "Ekonomi", "Güvenlik", "Mobilite", "Çevre", "İnsan", "Yönetişim",
        "Yaşam",
    )
}  # fmt: skip


def asks_for_datasets(folded: str) -> bool:
    """Does this folded question ask which data İBB publishes (and not how to request some)?"""
    return any(phrase in folded for phrase in DATA_PHRASES) and not any(word in folded for word in SERVICE_WORDS)


def dataset_route(folded: str, question: str) -> tuple[str, dict[str, Any]] | None:
    """``ibb_datasets_search`` with the question as its query and a named category, or ``None``."""
    if not asks_for_datasets(folded):
        return None
    arguments: dict[str, Any] = {"query": question.strip()[:200]}
    if "kategori" in folded or "category" in folded:
        # Only when a category is asked for by that word: "enerji verisi" is a subject, searched in every category.
        padded = f" {folded} "
        category = next((name for key, name in _CATEGORIES.items() if f" {key} " in padded), None)
        if category:
            arguments["category"] = category
    return "ibb_datasets_search", arguments
