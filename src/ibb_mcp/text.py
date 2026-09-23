"""Turkish-insensitive text keys: the one home for folding and name matching.

Users type "sisli", "ŞİŞLİ" and "Şişli" for the same place, and İBB spells one station
several ways in one payload (``YENIKAPI`` in ``Name``, ``Yenikapı`` in ``Description``). So
every lookup compares folded keys, never raw strings.

``str.lower()`` and ``str.casefold()`` alone are wrong for Turkish: ``"I".lower()`` is
``i`` where Turkish means ``ı``, and ``"İ".casefold()`` is ``i`` plus a combining dot
(U+0307). Mapping the Turkish letters onto their ASCII skeleton *before* casefolding, then
stripping whatever combining marks are left, makes both halves of every pair collide the
same way, whichever keyboard typed them.

Two keys, because two behaviours are genuinely needed:

* :func:`normalize_tr` also turns punctuation into word breaks: ``"Kadıköy, iskele"`` and
  ``"KADIKÖY İSKELE"`` are the same key. The gazetteer, the GTFS index, the agent's
  keyword router and the events filter use it.
* :func:`fold_tr` keeps punctuation. The station searches rank a hit on the real spelling
  above one that only matched once punctuation was squashed (:func:`rank_match_loose`), so
  someone who typed ``Boğaziçi Ü.-Hisarüstü`` gets that station before
  ``Boğaziçi Ü./Hisarüstü``; with punctuation folded away the two would tie.

Until 2026-09-23 these lived as three functions all named ``normalize_tr``, in ``gtfs``,
``sources.metro`` and ``sources.places``, and a source importing another source just to
reach them coupled two upstreams' failure modes. The gtfs and places copies returned the
same key for every stop, route and place name in the reference data (the counts are in
``tests/test_text.py``, which pins both keys on the inputs the old copies were checked
against).

Foundation layer: this module imports nothing from the project.
"""

from __future__ import annotations

import unicodedata

#: Every Turkish letter onto its ASCII skeleton, before casefolding (see the module
#: docstring for why the order matters). The circumflexes would also fall to the
#: combining-mark strip below; listing them keeps the table readable as the whole mapping.
_TR_FOLD = str.maketrans(
    {
        "İ": "i", "I": "i", "ı": "i",
        "Ş": "s", "ş": "s",
        "Ğ": "g", "ğ": "g",
        "Ü": "u", "ü": "u",
        "Ö": "o", "ö": "o",
        "Ç": "c", "ç": "c",
        "Â": "a", "â": "a", "Î": "i", "î": "i", "Û": "u", "û": "u",
    }
)

#: Added to a rank that only survived punctuation squashing, so a hit on the real
#: spelling always outranks a loose one ("Levent" keeps beating "4.Levent").
LOOSE_RANK_PENALTY = 3


def _strip_marks(text: str) -> str:
    """Turkish letters to ASCII, casefolded, combining marks removed; spacing untouched."""
    folded = text.translate(_TR_FOLD).casefold()
    # Anything that arrived pre-decomposed (I + U+0307) still carries combining marks.
    decomposed = unicodedata.normalize("NFKD", folded)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_tr(text: str | None) -> str:
    """Fold Turkish text to a matching key: case, letters, diacritics and punctuation.

    ``"KADIKÖY İSKELE"``, ``"kadikoy iskele"`` and ``"Kadıköy, iskele"`` all become
    ``"kadikoy iskele"``: letters and digits only, one space between words.
    """
    if not text:
        return ""
    return " ".join("".join(ch if ch.isalnum() else " " for ch in _strip_marks(text)).split())


def fold_tr(text: str | None) -> str:
    """Fold Turkish text like :func:`normalize_tr`, but keep its punctuation.

    ``'Şişli-Mecidiyeköy'`` and ``'SISLI-MECIDIYEKOY'`` both become ``'sisli-mecidiyekoy'``.
    For the strict pass of :func:`rank_match_loose`, where the real spelling must win.
    """
    if not text:
        return ""
    return " ".join(_strip_marks(text).split())


def squash_punctuation(folded: str) -> str:
    """Keep only letters and digits of an already folded string."""
    return "".join(ch for ch in folded if ch.isalnum())


def rank_match(query: str, candidate: str) -> int | None:
    """Match quality: 0 exact, 1 prefix, 2 substring, ``None`` for no match."""
    if not candidate or not query:
        return None
    if candidate == query:
        return 0
    if candidate.startswith(query):
        return 1
    if query in candidate:
        return 2
    return None


def rank_match_loose(query: str, loose_query: str, candidate: str | None) -> int | None:
    """:func:`rank_match` with a punctuation-insensitive second chance.

    İBB spells one station several ways — the payload's ``Name`` says ``AYSE KADIN``,
    ``50. YIL BASTABYA`` and ``HASTANE - ADLIYE`` where ``Description`` says
    ``Ayşekadın``, ``50.Yıl-Baştabya`` and ``Hastane-Adliye`` — and a user types a fourth
    variant. Comparing the squashed forms absorbs spacing, dots and hyphens without
    loosening the match into per-word soup. ``query``/``loose_query`` are the
    :func:`fold_tr` and squashed forms of the user's text, hoisted out of the candidate loop.
    """
    folded = fold_tr(candidate)
    rank = rank_match(query, folded)
    if rank is not None:
        return rank
    loose = rank_match(loose_query, squash_punctuation(folded))
    return None if loose is None else loose + LOOSE_RANK_PENALTY
