"""Length-preserving personal-data masking for console questions and history."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from ibb_mcp.text import fold_tr

KINDS: tuple[tuple[str, str], ...] = (
    ("iban", "IBAN"),
    ("kart", "KART NO"),
    ("tckn", "TC KİMLİK"),
    ("telefon", "TELEFON"),
    ("eposta", "E-POSTA"),
    ("arac", "PLAKA"),
)

_PATTERNS = (
    ("iban", re.compile(r"(?<![0-9a-z])tr[0-9]{2}(?: ?[0-9]{4}){5} ?[0-9]{2}(?![0-9a-z])")),
    (
        "kart",
        re.compile(
            r"(?<![0-9])(?:[0-9]{4}(?:[ -]?[0-9]{4}){3}|[0-9]{4}[ -]?[0-9]{6}[ -]?[0-9]{5}|[0-9]{13,19})(?![0-9])"
        ),
    ),
    ("tckn", re.compile(r"(?<![0-9])[1-9][0-9]{10}(?![0-9])")),
    (
        "telefon",
        re.compile(r"(?<![0-9+(])\(?(?:(?:\+|00)90[ -]?|0[ -]?)?\(?5[0-9]{2}\)?[ -]?[0-9]{3}[ -]?[0-9]{2}[ -]?[0-9]{2}(?![0-9])"),
    ),
    ("eposta", re.compile(r"(?<![a-z0-9._%+-])[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}")),
    (
        "arac",
        re.compile(r"(?<![0-9a-z])(0[1-9]|[1-7][0-9]|8[01])[ -]?([a-z]{1,3})[ -]?([0-9]{2,5})(?![0-9a-z])"),
    ),
)
_ARAC_WORDS = frozenset(
    ("dk", "sn", "km", "m", "cm", "mm", "kg", "gr", "tl", "lt", "no", "ve", "ile", "ya", "da", "de", "mi", "mu",
     "ki", "bu", "su", "ne", "cok", "az", "en", "her", "bir", "iki", "uc", "ay", "yil", "gun", "hat")
)
_ARAC_AFTER = re.compile(r" (?:dk|dakika|durak|sefer|km|metre|m|tl|lira|kisi|kez|saat|sn|saniye)(?![a-z])")


@lru_cache(maxsize=4096)
def _fold_character(ch: str) -> str:
    if ch.isspace():
        return " "
    if "٠" <= ch <= "٩":
        return str(ord(ch) - 0x0660)
    if "۰" <= ch <= "۹":
        return str(ord(ch) - 0x06F0)
    folded = fold_tr(ch)
    if len(folded) == 1:
        return folded
    lowered = ch.lower()
    return lowered if len(lowered) == 1 else ch


def fold_keep_length(text: str) -> str:
    """Fold each code point independently so match offsets still address the input."""
    return "".join(_fold_character(ch) for ch in text)


def tckn_valid(digits: str) -> bool:
    if len(digits) != 11 or not digits.isascii() or not digits.isdigit() or digits[0] == "0":
        return False
    odd = sum(int(digits[index]) for index in (0, 2, 4, 6, 8))
    even = sum(int(digits[index]) for index in (1, 3, 5, 7))
    return (odd * 7 - even) % 10 == int(digits[9]) and sum(map(int, digits[:10])) % 10 == int(digits[10])


def luhn_valid(digits: str) -> bool:
    if not 13 <= len(digits) <= 19 or not digits.isascii() or not digits.isdigit():
        return False
    total = 0
    for index, ch in enumerate(reversed(digits)):
        value = int(ch)
        if index % 2:
            value *= 2
            value = value - 9 if value > 9 else value
        total += value
    return total % 10 == 0


def iban_valid(compact: str) -> bool:
    if len(compact) != 26 or compact[:2].lower() != "tr" or not compact[2:].isascii() or not compact[2:].isdigit():
        return False
    rearranged = compact[4:] + compact[:4].upper()
    remainder = 0
    for ch in rearranged:
        digits = str(ord(ch) - 55) if ch.isalpha() else ch
        for digit in digits:
            remainder = (remainder * 10 + int(digit)) % 97
    return remainder == 1


@dataclass(frozen=True, slots=True)
class PiiHit:
    kind: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class MaskedTurn:
    message: str
    history: tuple[str, ...]
    count: int
    kinds: tuple[str, ...]


def _valid_candidate(kind: str, candidate: re.Match[str], folded: str) -> bool:
    if kind == "iban":
        return iban_valid(candidate.group().replace(" ", ""))
    if kind == "kart":
        return luhn_valid(candidate.group().replace(" ", "").replace("-", ""))
    if kind == "tckn":
        return tckn_valid(candidate.group())
    if kind == "telefon":
        return True
    if kind == "eposta":
        return True
    letters, digits = candidate.group(2), candidate.group(3)
    digit_count = len(digits)
    if len(letters) == 1:
        allowed_digits = 4 <= digit_count <= 5
    elif len(letters) == 2:
        allowed_digits = 3 <= digit_count <= 4
    else:
        allowed_digits = 2 <= digit_count <= 3
    if letters in _ARAC_WORDS or not allowed_digits:
        return False
    return _ARAC_AFTER.match(folded, candidate.end()) is None


def _overlaps(start: int, end: int, hits: list[PiiHit]) -> bool:
    return any(start < hit.end and end > hit.start for hit in hits)


def scan_pii(text: str) -> list[PiiHit]:
    """Return only identifier kinds and offsets; matched text is never retained."""
    folded = fold_keep_length(text)
    hits: list[PiiHit] = []
    for kind, pattern in _PATTERNS:
        position = 0
        while candidate := pattern.search(folded, position):
            start, end = candidate.span()
            if _valid_candidate(kind, candidate, folded) and not _overlaps(start, end, hits):
                hits.append(PiiHit(kind, start, end))
                position = end
            else:
                position = start + 1
    return sorted(hits, key=lambda hit: hit.start)


def _label(kind: str) -> str:
    return next(label for item_kind, label in KINDS if item_kind == kind)


def mask_labels(text: str) -> tuple[str, int, tuple[str, ...]]:
    hits = scan_pii(text)
    if not hits:
        return text, 0, ()
    parts: list[str] = []
    labels: list[str] = []
    cursor = 0
    for hit in hits:
        label = _label(hit.kind)
        parts.extend((text[cursor:hit.start], f"[{label}]"))
        cursor = hit.end
        if label not in labels:
            labels.append(label)
    parts.append(text[cursor:])
    return "".join(parts), len(hits), tuple(labels)


def mask(text: str) -> tuple[str, int]:
    masked, count, _ = mask_labels(text)
    return masked, count


def mask_turn(message: str, history: Sequence[str]) -> MaskedTurn:
    masked, count, kinds = mask_labels(message)
    return MaskedTurn(masked, tuple(mask(item)[0] for item in history), count, kinds)


def pii_final_fields(turn: MaskedTurn) -> dict[str, object]:
    return {"masked_count": turn.count, "masked_kinds": list(turn.kinds)}
