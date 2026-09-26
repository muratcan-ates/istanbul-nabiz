"""Small, deterministic emergency classifier for the citizen console."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypedDict

from ibb_mcp.text import fold_tr


class EmergencyVerdict(TypedDict):
    emergency: bool
    lines: list[str]


@dataclass(frozen=True)
class _Term:
    parts: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    company: str | None = None
    language: str = "tr"


EMERGENCY_LINES = ("112", "153")
_ARABIC_FOLD = str.maketrans({"ة": "ه", "ى": "ي"})
_ARABIC_PREFIXES = ("وال", "بال", "ال", "لل", "و", "ب", "ف")


def fold_same_length(text: str) -> str:
    """Fold each character without changing the number of code points."""
    folded = "".join((value if len(value := fold_tr(char)) == 1 else char) for char in text)
    return folded.translate(_ARABIC_FOLD)


def _term(parts: str, *, exclude: tuple[str, ...] = (), company: str | None = None, language: str = "tr") -> _Term:
    return _Term(
        tuple(fold_same_length(part) for part in parts.split()),
        tuple(fold_same_length(word) for word in exclude),
        company,
        language,
    )


_TERMS = (
    _term("yangın"),
    _term("ambulans"),
    _term("polis", exclude=("polisiye",)),
    _term("şiddet", exclude=("şiddetli",)),
    _term("kalp"),
    _term("bayıl", exclude=("bayilik",)),
    _term("kaza"),
    _term("kazası"),
    _term("yaralı"),
    _term("yaralan"),
    _term("kanıyor"),
    _term("kanama"),
    _term("kalp krizi"),
    _term("intihar"),
    _term("saldırı"),
    _term("nefes alamıyor"),
    _term("boğul"),
    _term("bilincini kaybet"),
    _term("gaz koku"),
    _term("gaz kaçağ"),
    _term("gaz kaçıyor"),
    _term("gaz sızıntı"),
    _term("doğalgaz koku"),
    _term("doğalgaz kaçağ"),
    _term("doğalgaz kaçıyor"),
    _term("doğalgaz sızıntı"),
    _term("bina çatla"),
    _term("binada çatlak"),
    _term("bina çöktü"),
    _term("bina çöküyor"),
    _term("bina çökmüş"),
    _term("enkaz"),
    _term("zehirlen"),
    _term("elektrik çarp"),
    _term("imdat"),
    _term("yardım edin", company="plea_tr"),
    _term("bıçakla"),
    _term("acil", company="acil"),
    _term("düştü", company="fallen"),
    _term("düştüm", company="fallen"),
    _term("düşmüş", company="fallen"),
    _term("fire", language="en"),
    _term("ambulance", language="en"),
    _term("police", language="en"),
    _term("accident", language="en"),
    _term("injured", language="en"),
    _term("unconscious", language="en"),
    _term("fainted", language="en"),
    _term("bleeding", language="en"),
    _term("heart attack", language="en"),
    _term("not breathing", language="en"),
    _term("can t breathe", language="en"),
    _term("cannot breathe", language="en"),
    _term("choking", language="en"),
    _term("drowning", language="en"),
    _term("stabbed", language="en"),
    _term("overdose", language="en"),
    _term("gas leak", language="en"),
    _term("smell gas", language="en"),
    _term("smell of gas", language="en"),
    _term("someone fell", language="en"),
    _term("fell on the tracks", language="en"),
    _term("emergency", company="emergency", language="en"),
    # Arabic stays as input only (DECISIONS #35): the page no longer speaks Arabic, but a plea written in it
    # must still stop the chat and show the 112 card, which then renders in the page language.
    _term("حريق", language="ar"),
    _term("إسعاف", language="ar"),
    _term("شرطة", language="ar"),
    _term("نجدة", language="ar"),
    _term("طوارئ", language="ar"),
    _term("أغمي", language="ar"),
    _term("نزيف", language="ar"),
    _term("حادث", language="ar"),
    _term("تسرب غاز", language="ar"),
    _term("رائحة غاز", language="ar"),
    _term("لا يتنفس", language="ar"),
    _term("ساعدوني", company="plea_ar", language="ar"),
    _term("انهار", company="building", language="ar"),
)

_EXACT_WORDS = frozenset(
    fold_same_length(word)
    for word in ("kaza", "kazası", "imdat", "fire", "police", "accident")
)
_MASKS = tuple(
    tuple(fold_same_length(part) for part in phrase.split())
    for phrase in (
        "acil değil",
        "acil bir durum değil",
        "acil durum toplanma",
        "acil çıkış",
        "acil servis",
        "yangın merdiven",
        "yangın çıkış",
        "yangın tüp",
        "yangın söndür",
        "yangın sigorta",
        "gaz fatura",
        "gaz sayaç",
        "enkaz kaldır",
        "kalp hastane",
        "kalp merkez",
        "emergency exit",
        "emergency room",
        "emergency assembly",
        "fire exit",
        "fire escape",
        "fire extinguisher",
        "مخرج طوارئ",
        "قسم طوارئ",
    )
)
_COMPANIONS = {
    "acil": tuple(
        fold_same_length(word)
        for word in ("yardım", "ambulans", "düştü", "kaza", "kazası", "yaralı", "doktor", "hastane")
    ),
    "emergency": tuple(
        fold_same_length(word) for word in ("help", "ambulance", "someone", "hurt", "injured", "fell", "bleeding")
    ),
    "fallen": tuple(
        fold_same_length(word)
        for word in (
            "biri", "birisi", "annem", "babam", "dedem", "ninem", "anneannem", "babaannem", "çocuk",
            "çocuğum", "yaşlı", "adam", "kadın", "teyze", "amca", "eşim", "kardeşim", "arkadaşım", "oğlum",
            "kızım", "bebeğim", "yolcu", "raya", "raylara", "kalkamıyor",
        )
    ),
    "building": tuple(fold_same_length(word) for word in ("مبنى", "بناء", "عمارة", "سقف")),
}
_TR_NEGATIONS = frozenset(("degil", "degildi", "yok", "yoktu", "olmadi", "olmayan"))
_EN_NEGATIONS = frozenset(("no", "not", "isn", "wasn", "without"))
_AR_NEGATIONS = frozenset(("ليس", "ليست", "لا", "لم"))


def _tokens(text: str) -> list[re.Match[str]]:
    return list(re.finditer(r"\w+", text))


def _variants(word: str) -> tuple[str, ...]:
    variants = [word]
    for prefix in _ARABIC_PREFIXES:
        if word.startswith(prefix) and len(word) - len(prefix) >= 3:
            variants.append(word[len(prefix) :])
            break
    return tuple(variants)


def _matches_part(word: str, part: str, *, exact: bool) -> bool:
    return any(candidate == part if exact else candidate.startswith(part) for candidate in _variants(word))


def _matches_phrase(words: list[str], start: int, parts: tuple[str, ...], *, final_prefix: bool = True) -> bool:
    if start + len(parts) > len(words):
        return False
    for offset, part in enumerate(parts):
        exact = offset < len(parts) - 1 or not final_prefix
        if not _matches_part(words[start + offset], part, exact=exact):
            return False
    return True


def _masked(words: list[str]) -> set[int]:
    covered: set[int] = set()
    for mask in _MASKS:
        for start in range(len(words)):
            if _matches_phrase(words, start, mask):
                covered.update(range(start, start + len(mask)))
    return covered


def _has_companion(words: list[str], covered: set[int], company: str) -> bool:
    companions = _COMPANIONS.get(company, ())
    return any(
        index not in covered and any(_matches_part(word, companion, exact=False) for companion in companions)
        for index, word in enumerate(words)
    )


def _is_negated(start: int, end: int, words: list[str], language: str) -> bool:
    if language == "tr":
        return any(word in _TR_NEGATIONS for word in words[end + 1 : end + 3])
    negatives = _AR_NEGATIONS if language == "ar" else _EN_NEGATIONS
    return any(word in negatives for word in words[max(0, start - 2) : start])


def _term_end(words: list[str], start: int, term: _Term) -> int | None:
    if not _matches_phrase(words, start, term.parts):
        return None
    if len(term.parts) == 1:
        word = words[start]
        if any(_matches_part(word, excluded, exact=False) for excluded in term.exclude):
            return None
        if term.parts[0] in _EXACT_WORDS and not _matches_part(word, term.parts[0], exact=True):
            return None
    return start + len(term.parts) - 1


def _matches_emergency_plea(folded: str, tokens: list[re.Match[str]], words: list[str], covered: set[int]) -> bool:
    phrases = (("yardim", "edin"), ("ساعدوني",))
    for phrase in phrases:
        for start in range(len(words) - len(phrase) + 1):
            end = start + len(phrase) - 1
            if any(index in covered for index in range(start, end + 1)):
                continue
            if not _matches_phrase(words, start, phrase, final_prefix=False):
                continue
            alone = len(tokens) == len(phrase) and all(words[index] == phrase[index] for index in range(len(phrase)))
            shouted = folded[tokens[end].end() :].lstrip().startswith("!")
            if alone or shouted:
                return True
    return False


def _has_unmasked_match(
    words: list[str], covered: set[int], terms: tuple[_Term, ...]
) -> bool:
    for term in terms:
        for start in range(len(words)):
            end = _term_end(words, start, term)
            if end is None or any(index in covered for index in range(start, end + 1)):
                continue
            if term.company and not _has_companion(words, covered, term.company):
                continue
            if not _is_negated(start, end, words, term.language):
                return True
    return False


def classify(text: str) -> EmergencyVerdict:
    """Classify a message with fixed vocabulary, masking and local negation rules."""
    folded = fold_same_length(text)
    tokens = _tokens(folded)
    words = [match.group() for match in tokens]
    covered = _masked(words)
    emergency = _matches_emergency_plea(folded, tokens, words, covered) or _has_unmasked_match(words, covered, _TERMS)
    return {"emergency": emergency, "lines": list(EMERGENCY_LINES) if emergency else []}
