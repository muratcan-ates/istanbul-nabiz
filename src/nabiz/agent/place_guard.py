"""Deterministic place and service-intent decisions for the rule-based agent.

The caller supplies gazetteer names so this module stays below the data-source layer.
It never stores a question or makes a network request.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ibb_mcp.text import normalize_tr

# Case/location endings are allowed after a whole gazetteer token. Plurals and
# derivational or possessive endings stay out: "Bebekler" and "Yıldızlı" are words,
# not reliable mentions of the place.
SUFFIXES: tuple[str, ...] = (
    "a", "e", "ya", "ye", "na", "ne", "i", "u", "yi", "yu", "in", "un", "nin", "nun",
    "da", "de", "ta", "te", "dan", "den", "tan", "ten", "daki", "deki", "taki", "teki",
    "la", "le", "yla", "yle", "nda", "nde", "ndan", "nden", "ndaki", "ndeki",
)

# Each value is also an ordinary Turkish word or a personal name. Keep the reasons
# beside the entries so a later gazetteer change can be reviewed one by one.
COMMON_WORD_PLACES: frozenset[str] = frozenset(
    {
        "bebek",   # a baby; a common noun
        "moda",    # fashion; a common noun
        "mobil",   # mobile; a common adjective
        "huzur",   # peace; a common noun
        "kilise",  # church; a common noun
        "meclis",  # assembly; a common noun
        "vatan",   # homeland; a common noun
        "carsi",   # bazaar; a common noun
        "cakmak",  # lighter; a common noun
        "fener",   # lantern; a common noun
        "yildiz",  # star; a common noun and personal name
        "kartal",  # eagle; a common noun
        "levent",  # a personal name
        "fatih",   # a personal name and title
        "otogar",  # bus terminal; a common noun
    }
)

REASONS: tuple[str, ...] = (
    "place_ok", "inside_word", "common_word_no_cue", "intent_billing", "intent_schedule",
    "intent_procedure", "no_place",
)


@dataclass(frozen=True)
class PlaceMatch:
    """A gazetteer name matched to a whole question token sequence."""

    name: str
    token: str
    suffix: str
    cue: bool


_PLACE_LOOKUP_PHRASES = (
    "nerede", "nerde", "nasil giderim", "nasil gidilir", "yol tarifi", "konum",
    "where is", "how do i get", "near",
)
_PLACE_CONTEXT_WORDS = (
    "istasyon", "station", "metro", "durak", "stop", "iskele", "meydan", "ilce", "semt", "mahalle",
    "asansor", "lift", "elevator", "merdiven", "wc", "bildirim",
)
_INTENT_KEYS: dict[str, tuple[str, ...]] = {
    "billing": (
        "fatura", "abone", "abonelik", "odeme", "ode", "borc", "tahsilat", "sayac", "endeks", "iade", "taksit",
        "bill", "invoice", "payment", "subscription",
    ),
    "schedule": (
        "sefer", "saatleri", "saat kacta", "kalkis", "tarife", "vapur saat", "calisma saat", "timetable", "schedule",
        "departure",
    ),
    "procedure": (
        "basvuru", "basvur", "belge", "randevu", "iptal", "devir", "kayit", "nasil yapilir", "apply", "application",
        "cancel", "document",
    ),
}
# Prefix matching follows the deterministic router's keyword rule. This explicit
# false friend documents that "odun" is never an "ode" payment request.
_INTENT_EXCLUSIONS: dict[str, tuple[str, ...]] = {"billing": ("odun",)}
_INTENT_ORDER = ("billing", "schedule", "procedure", "place_lookup")
_VOWELS = frozenset("aeiou")
_SOFTENING = {"k": "g", "t": "d", "p": "b", "ç": "c"}
_TOKEN_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)
_NEED_SEPARATOR = re.compile(r"(?i)\b(?:bir\s+de|ayrıca|ayrica|sonra|and|also|ve)\b|,")
_CUE_BOUNDARY = re.compile(r"(?i)[,;?!]|\b(?:bir\s+de|ayrıca|ayrica|sonra|and|also|ve)\b")


def _folded_question(question: str) -> str:
    return normalize_tr(question)


def _question_tokens(question: str) -> tuple[list[str], list[str], list[int]]:
    """Return folded words and their source word, retaining apostrophe grouping."""
    tokens: list[str] = []
    source_words: list[str] = []
    segments: list[int] = []
    boundary_ends = [match.end() for match in _CUE_BOUNDARY.finditer(question)]
    segment = 0
    next_boundary = 0
    for match in _TOKEN_RE.finditer(question):
        while next_boundary < len(boundary_ends) and boundary_ends[next_boundary] <= match.start():
            segment += 1
            next_boundary += 1
        raw = match.group()
        folded = normalize_tr(raw).split()
        tokens.extend(folded)
        source_words.extend([raw] * len(folded))
        segments.extend([segment] * len(folded))
    return tokens, source_words, segments


def _place_lookup(tokens: list[str]) -> bool:
    return bool(_place_lookup_spans(tokens))


def _place_lookup_spans(tokens: list[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for phrase in _PLACE_LOOKUP_PHRASES:
        parts = phrase.split()
        if len(parts) > 1:
            for start in range(len(tokens) - len(parts) + 1):
                if tokens[start:start + len(parts)] == parts:
                    spans.append((start, start + len(parts)))
        else:
            spans.extend(
                (start, start + 1)
                for start, token in enumerate(tokens)
                if token.startswith(phrase) and token not in {"nereden", "neredeyse"}
            )
    return spans


def _lookup_near(tokens: list[str], segments: list[int], start: int, end: int) -> bool:
    for cue_start, cue_end in _place_lookup_spans(tokens):
        if segments[cue_start] != segments[start] or any(
            segments[index] != segments[cue_start] for index in range(cue_start, cue_end)
        ):
            continue
        return True
    return False


def _key_present(folded: str, tokens: list[str], key: str, excluded: tuple[str, ...] = ()) -> bool:
    if " " in key:
        return key in folded
    return any(
        token.startswith(key) and not any(token.startswith(bad) for bad in excluded)
        for token in tokens
    )


def intents(question: str) -> frozenset[str]:
    """Find billing, timetable, procedure and explicit place-lookup language."""
    folded = _folded_question(question)
    tokens = folded.split()
    found = {
        group
        for group, keys in _INTENT_KEYS.items()
        if any(_key_present(folded, tokens, key, _INTENT_EXCLUSIONS.get(group, ())) for key in keys)
    }
    if _place_lookup(tokens):
        found.add("place_lookup")
    return frozenset(found)


def _suffix_match(base: str, token: str) -> str | None:
    if token == base:
        return ""
    remainder = token[len(base):] if token.startswith(base) else ""
    if remainder in SUFFIXES:
        return remainder
    ending = base[-1:]
    softened = _SOFTENING.get(ending)
    if softened and len(token) > len(base) and token.startswith(base[:-1] + softened):
        remainder = token[len(base):]
        if remainder and remainder[0] in _VOWELS and remainder in SUFFIXES:
            return remainder
    return None


def _candidate_at(
    question_tokens: list[str], source_words: list[str], segments: list[int], start: int, name: str,
    name_tokens: list[str],
) -> tuple[PlaceMatch, int] | None:
    if start + len(name_tokens) > len(question_tokens):
        return None
    last = start + len(name_tokens) - 1
    if question_tokens[start:last] != name_tokens[:-1]:
        return None
    suffix = _suffix_match(name_tokens[-1], question_tokens[last])
    consumed = len(name_tokens)
    if suffix is None:
        return None
    raw_last = source_words[last]
    # normalize_tr splits apostrophes into two tokens; retain the ending as the
    # suffix and consume it only when it came from the same apostrophised word.
    if not suffix and last + 1 < len(question_tokens):
        separated = question_tokens[last + 1]
        if (
            source_words[last + 1] == raw_last
            and ("'" in raw_last or "’" in raw_last)
            and separated in SUFFIXES
        ):
            suffix = separated
            consumed += 1
    proper_later = start > 0 and source_words[start][:1].isupper()
    adjacent = question_tokens[start - 1] if start else ""
    after = question_tokens[start + consumed] if start + consumed < len(question_tokens) else ""
    context_cue = any(
        word.startswith(context)
        for word in (adjacent, after)
        for context in _PLACE_CONTEXT_WORDS
    )
    referential_cue = after == "adi" and any(
        token.startswith(context)
        for token in question_tokens[start + consumed + 1:]
        for context in _PLACE_CONTEXT_WORDS
    )
    lookup_cue = _lookup_near(question_tokens, segments, start, start + consumed)
    cue = bool(suffix or lookup_cue or proper_later or context_cue or referential_cue)
    if normalize_tr(name) in COMMON_WORD_PLACES and not cue:
        return None
    actual = " ".join(question_tokens[start:start + consumed])
    return PlaceMatch(name=name, token=actual, suffix=suffix, cue=cue), consumed


def _prepared_names(names: Iterable[str]) -> list[tuple[str, list[str], str]]:
    prepared: list[tuple[str, list[str], str]] = []
    seen: set[tuple[str, str]] = set()
    for name in names:
        folded = normalize_tr(name)
        parts = folded.split()
        if len(folded) < 4 or not parts or (name, folded) in seen:
            continue
        seen.add((name, folded))
        prepared.append((name, parts, folded))
    return prepared


def _matches(question: str, names: Iterable[str]) -> tuple[list[tuple[int, int, int, PlaceMatch]], str | None]:
    question_tokens, source_words, segments = _question_tokens(question)
    prepared = _prepared_names(names)
    found: list[tuple[int, int, int, PlaceMatch]] = []
    common_rejected = False
    inside_rejected = False
    for start in range(len(question_tokens)):
        for name, parts, folded_name in prepared:
            candidate = _candidate_at(question_tokens, source_words, segments, start, name, parts)
            if candidate:
                match, consumed = candidate
                found.append((start, consumed, len(folded_name), match))
            elif folded_name in COMMON_WORD_PLACES:
                for pos in range(start, len(question_tokens)):
                    if folded_name in question_tokens[pos] and question_tokens[pos] != folded_name:
                        common_rejected = True
                        break
                if start < len(question_tokens) and question_tokens[start] == folded_name:
                    common_rejected = True
            else:
                if any(folded_name in token and token != folded_name for token in question_tokens[start:]):
                    inside_rejected = True
    rejection = "common_word_no_cue" if common_rejected else "inside_word" if inside_rejected else None
    return found, rejection


def find_places(question: str, names: Iterable[str]) -> list[PlaceMatch]:
    """Return non-overlapping matches in question order, preferring the longest at each point."""
    found, _ = _matches(question, names)
    found.sort(key=lambda item: (item[0], -item[2], -item[1], item[3].name.casefold()))
    selected: list[PlaceMatch] = []
    occupied_until = -1
    for start, consumed, _, match in found:
        if start < occupied_until:
            continue
        selected.append(match)
        occupied_until = start + consumed
    return selected


def find_place(question: str, names: Iterable[str]) -> PlaceMatch | None:
    """Match a whole gazetteer token, with an optional Turkish place ending."""
    found, _ = _matches(question, names)
    if not found:
        return None
    # Keep the old longest-name preference; equal lengths go to the first mention.
    found.sort(key=lambda item: (-item[2], item[0], -item[1], item[3].name.casefold()))
    return found[0][3]


def fallback_tool(question: str, place: PlaceMatch | None) -> tuple[str, dict] | None:
    """Choose the final fallback after earlier deterministic route branches."""
    found = intents(question)
    service_intents = found & {"billing", "schedule", "procedure"}
    if place and (not service_intents or "place_lookup" in found):
        return "places_resolve", {"query": place.name}
    if service_intents and "place_lookup" not in found:
        return "ibb_services_search", {"query": question}
    return None


def explain(question: str, names: Iterable[str]) -> dict:
    """Explain the pure place and final-fallback decision with short internal reason codes."""
    names = tuple(names)
    found, rejection = _matches(question, names)
    place = find_place(question, names)
    found_intents = intents(question)
    fallback = fallback_tool(question, place)
    if place:
        service = next((key for key in ("billing", "schedule", "procedure") if key in found_intents), None)
        reason = f"intent_{service}" if service and "place_lookup" not in found_intents else "place_ok"
    elif rejection:
        reason = rejection
    else:
        service = next((key for key in ("billing", "schedule", "procedure") if key in found_intents), None)
        reason = f"intent_{service}" if service and "place_lookup" not in found_intents else "no_place"
    return {
        "place": place.name if place else None,
        "reason": reason,
        "intents": [key for key in _INTENT_ORDER if key in found_intents],
        "fallback": fallback[0] if fallback else None,
    }


def split_needs(question: str, names: Iterable[str]) -> list[dict]:
    """Split explicit conjunctions while copying whole-question travel constraints."""
    names = tuple(names)
    pieces = [piece.strip() for piece in _NEED_SEPARATOR.split(question) if piece.strip()]
    if not pieces:
        pieces = [question.strip()]
    folded = _folded_question(question)
    constraints: list[str] = []
    for needle, label in (
        ("aksam", "aksam"), ("az yuru", "az yuruyorum"), ("tekerlekli sandalye", "tekerlekli sandalye"),
        ("evening", "evening"), ("slow", "slow"),
    ):
        if needle in folded and label not in constraints:
            constraints.append(label)
    result: list[dict] = []
    for piece in pieces:
        place = find_place(piece, names)
        detected = intents(piece)
        fallback = fallback_tool(piece, place)
        result.append(
            {
                "text": piece,
                "place": place.name if place else None,
                "intents": [key for key in _INTENT_ORDER if key in detected],
                "fallback": fallback[0] if fallback else None,
                "constraints": list(constraints),
            }
        )
    return result


def _cli_names() -> list[str]:
    root = Path(__file__).resolve().parents[3]
    configured = os.environ.get("NABIZ_PLACES_CSV")
    path = Path(configured) if configured else root / "data" / "reference" / "places.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        return [row["name"].strip() for row in csv.DictReader(handle) if row.get("name", "").strip()]


if __name__ == "__main__":
    question = " ".join(sys.argv[1:])
    print(json.dumps(explain(question, _cli_names()), ensure_ascii=False))
