"""Classify short chat turns deterministically before the agent needs a model.

Greetings, thanks and clarification should be immediate; emergency and refusal checks
run before this layer. Conversation history is supplied per request and is never stored.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import Any, Literal, TypedDict

from ibb_mcp.text import normalize_tr

PHRASES_PATH = Path(__file__).with_name("selamlar.toml")
LAYER_KINDS = ("greeting", "thanks", "unclear", "split", "followup", "pass")
_LANGUAGES = ("tr", "en", "ar")
_MATCH_LANGUAGES = ("ar", "en", "tr")
_ARABIC = re.compile(r"[\u0600-\u06ff]")
_TURKISH = re.compile(r"[çğıöşüÇĞİÖŞÜ]")
_METRO_LINE = re.compile(r"\b(M\d{1,2}[AB]?|T\d|F\d|MARMARAY)(?!\d)", re.IGNORECASE)
_BUS_LINE = re.compile(r"\b(\d{1,3}[A-ZÇĞİÖŞÜ]{1,2})\b")
_STOP_CODE = re.compile(r"^\d{1,6}$")
_TRAILING_PUNCTUATION = "?!.,;:؟"


def _word_set(words: str) -> frozenset[str]:
    """Keep fixed word vocabularies readable without spending a line on each token."""
    return frozenset(words.split())


_ENGLISH_WORDS = _word_set(
    "the is are how what where when which bus stop station hello hi thanks thank you please help line about there"
)
_TURKISH_WORDS = frozenset({"var", "mi", "mu", "nasil", "nerede", "ne", "kac", "hangi", "otopark", "durak", "hava", "peki", "ya"})
_NOT_AIR = ("havalimani", "havaalani", "havacilik", "havuz")
_FIELD_PREFIXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("parking", ("otopark", "ispark", "parking")),
    ("air", ("hava", "aqi", "pm10", "air")),
    ("traffic", ("trafik", "traffic")),
    ("metro", ("metro", "marmaray", "tramvay", "funikuler")),
    ("bus", ("otobus", "bus")),
    ("stop", ("durak", "durag", "stop")),
    ("station", ("istasyon", "asansor", "yuruyen", "merdiven", "station", "lift", "elevator", "escalator")),
)
_FOLLOW_HINTS = ("peki ", "ya ", "bir de ", "o zaman ", "what about ", "how about ", "and ")
_DEICTIC = frozenset({"orada", "orasi", "oraya", "oradan", "orda", "orasinda", "there"})
_GENERIC_WORDS = _word_set("hmm hm hmmm sey yani bilmiyorum ne soru sorum var bir yardim help huh ee eee what")
_SLOT_FILLERS = _word_set(
    "ne nerede nerde neresi nasil kac kacta mi mu var yok zaman gelir gelecek geliyor "
    "calisiyor calismiyor acik kapali hangi bir en yakin yakindaki bu su where when is "
    "the a next working open which nearest what time does come"
)
_SLOT_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("stop", ("durak", "durag", "stop")),
    ("line", ("otobus", "bus", "hat", "hatti", "hattin", "hatta", "hattan", "line")),
    ("station", ("istasyon", "asansor", "yuruyen", "merdiven", "station", "lift", "elevator", "escalator")),
)


class TurnLayer(TypedDict):
    kind: Literal["greeting", "thanks", "unclear", "split", "followup", "pass"]
    lang: Literal["tr", "en", "ar"]
    message: str
    parts: list[str]
    entity: dict[str, str] | None
    ask: Literal["stop", "line", "station", "generic"] | None
    unclear_streak: int
    handoff: bool
    first_turn: bool


class LayerReply(TypedDict):
    answer: str
    mode: Literal["small_talk", "clarify"]
    rule_id: Literal["layer:greeting", "layer:thanks", "layer:clarify", "layer:handoff"]
    handoff: bool


def _required(data: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            raise ValueError(f"selamlar.toml: {'.'.join(path)}")
        value = value[key]
    return value


def _fold_group(data: dict[str, Any], group: str) -> None:
    patterns = _required(data, (group, "patterns"))
    replies = _required(data, (group, "reply"))
    if not isinstance(patterns, Mapping) or not isinstance(replies, Mapping):
        raise ValueError(f"selamlar.toml: {group}")
    folded: dict[str, tuple[str, ...]] = {}
    for lang in _LANGUAGES:
        raw = patterns.get(lang)
        reply = replies.get(lang)
        valid = isinstance(raw, list) and raw and all(isinstance(item, str) and normalize_tr(item) for item in raw)
        if not valid or not isinstance(reply, str) or not reply.strip():
            raise ValueError(f"selamlar.toml: {group}.{lang}")
        folded[lang] = tuple(sorted((normalize_tr(item) for item in raw), key=len, reverse=True))
    data[group]["patterns"] = folded


def _fold_addresses(data: dict[str, Any]) -> None:
    words = _required(data, ("address", "words"))
    if not isinstance(words, list) or not all(isinstance(item, str) and normalize_tr(item) for item in words):
        raise ValueError("selamlar.toml: address.words")
    data["address"]["words"] = tuple(sorted((normalize_tr(item) for item in words), key=len, reverse=True))


def _validate_translations(data: dict[str, Any], path: tuple[str, ...]) -> None:
    translations = _required(data, path)
    if not isinstance(translations, Mapping) or any(
        not isinstance(translations.get(lang), str) or not translations[lang].strip() for lang in _LANGUAGES
    ):
        raise ValueError(f"selamlar.toml: {'.'.join(path)}")


@cache
def load_phrases(path: Path = PHRASES_PATH) -> dict[str, Any]:
    """Load and fold the package phrase file once; the package path works in wheels too."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"selamlar.toml: {exc}") from exc
    if data.get("version") != 1:
        raise ValueError("selamlar.toml: version")
    for group in ("greeting", "thanks"):
        _fold_group(data, group)
    _fold_addresses(data)
    for section in ("stop", "line", "station", "generic"):
        _validate_translations(data, ("clarify", section))
    _validate_translations(data, ("handoff",))
    return data


def _lang(text: str) -> Literal["tr", "en", "ar"]:
    if _ARABIC.search(text):
        return "ar"
    if _TURKISH.search(text):
        return "tr"
    words = set(normalize_tr(text).split())
    return "en" if len(words & _ENGLISH_WORDS) > len(words & _TURKISH_WORDS) else "tr"


def _consume(text: str, patterns: Mapping[str, Sequence[str]]) -> tuple[str, str | None]:
    matched: str | None = None
    for lang in _MATCH_LANGUAGES:
        for pattern in patterns[lang]:
            phrase = f" {pattern} "
            while phrase in text:
                text = text.replace(phrase, " ", 1)
                if matched is None:
                    matched = lang
    return text, matched


def _small_talk(message: str, phrases: Mapping[str, Any]) -> tuple[Literal["greeting", "thanks"], str] | None:
    text = f" {normalize_tr(message)} "
    text, thanks_lang = _consume(text, phrases["thanks"]["patterns"])
    text, greeting_lang = _consume(text, phrases["greeting"]["patterns"])
    text, _ = _consume(text, {"ar": phrases["address"]["words"], "en": (), "tr": ()})
    if text.strip() or (thanks_lang is None and greeting_lang is None):
        return None
    if thanks_lang is not None:
        return "thanks", thanks_lang
    return "greeting", greeting_lang or "tr"


@cache
def _folded_places(places: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    folded = ((normalize_tr(name), name) for name in places)
    return tuple(sorted(((key, name) for key, name in folded if len(key) >= 4), key=lambda item: len(item[0]), reverse=True))


def _entity(text: str, places: Sequence[str]) -> dict[str, str] | None:
    metro = _METRO_LINE.search(text)
    if metro:
        return {"type": "metro_line", "value": metro.group(1).upper()}
    bus = _BUS_LINE.search(text.upper())
    if bus:
        return {"type": "bus_line", "value": bus.group(1).upper()}
    haystack = normalize_tr(text)
    for folded, name in _folded_places(tuple(places)):
        if folded in haystack:
            return {"type": "place", "value": name}
    return None


def _word_fields(word: str) -> tuple[str, ...]:
    folded = normalize_tr(word)
    if not folded or any(folded.startswith(prefix) for prefix in _NOT_AIR):
        return ()
    return tuple(name for name, prefixes in _FIELD_PREFIXES if any(folded.startswith(prefix) for prefix in prefixes))


def _token_fields(token: str, places: Sequence[str]) -> tuple[str, ...]:
    fields = list(_word_fields(token))
    found = _entity(token, places)
    if found is not None:
        if found["type"] == "metro_line" and "metro" not in fields:
            fields.append("metro")
        elif found["type"] == "bus_line" and "bus" not in fields:
            fields.append("bus")
    return tuple(fields)


def _has_area_keyword(text: str) -> bool:
    return any(_word_fields(token) for token in text.split())


def _anchor(history: Sequence[str], places: Sequence[str]) -> str | None:
    for message in reversed(history):
        if _entity(message, places) is not None or any(_token_fields(token, places) for token in message.split()):
            return message
    return None


def _trailing_punctuation(token: str) -> str:
    punctuation = ""
    for char in reversed(token):
        if char not in _TRAILING_PUNCTUATION:
            break
        punctuation = char + punctuation
    return punctuation


def _entity_token(message: str, entity_type: str, places: Sequence[str]) -> tuple[int, str] | None:
    for index, token in enumerate(message.split()):
        core = token[: len(token) - len(_trailing_punctuation(token))] if _trailing_punctuation(token) else token
        found = _entity(core, places)
        if found is not None and found["type"] == entity_type:
            return index, token
    return None


def _replace_entity(anchor: str, current: str, entity_type: str, places: Sequence[str]) -> str | None:
    old = _entity_token(anchor, entity_type, places)
    new = _entity_token(current, entity_type, places)
    if old is None or new is None:
        return None
    old_index, old_token = old
    new_token = new[1]
    new_core = (
        new_token[: len(new_token) - len(_trailing_punctuation(new_token))] if _trailing_punctuation(new_token) else new_token
    )
    words = anchor.split()
    words[old_index] = new_core + _trailing_punctuation(old_token)
    return " ".join(words)


def _clarification_answer(message: str, history: Sequence[str], places: Sequence[str]) -> tuple[str, dict[str, str]] | None:
    if not history or _unclear_kind(history[-1], places) not in {"stop", "line", "station"}:
        return None
    words = normalize_tr(message).split()
    if not 1 <= len(words) <= 3 or _has_area_keyword(message):
        return None
    found = _entity(message, places)
    if found is None and len(words) == 1 and _STOP_CODE.fullmatch(words[0]):
        found = {"type": "stop_code", "value": words[0]}
    if found is None:
        return None
    return f"{message.strip().rstrip(_TRAILING_PUNCTUATION).strip()} {history[-1].strip()}", found


def _replace_deictic(message: str, entity: Mapping[str, str]) -> str | None:
    words = message.split()
    target = next((index for index, word in enumerate(words) if normalize_tr(word) in _DEICTIC), None)
    if target is None:
        return None
    replacement = entity["value"] + _trailing_punctuation(words[target])
    words[target] = replacement
    if words and normalize_tr(words[0]) in {"peki", "ya"}:
        words.pop(0)
    return " ".join(words)


def _followup(message: str, history: Sequence[str], places: Sequence[str]) -> tuple[str, dict[str, str]] | None:
    clarified = _clarification_answer(message, history, places)
    if clarified is not None:
        return clarified
    found = _entity(message, places)
    if found is not None and not _has_area_keyword(message):
        folded = normalize_tr(message)
        has_hint = folded.startswith(_FOLLOW_HINTS)
        if len(folded.split()) <= 2 or (len(folded.split()) <= 5 and has_hint):
            anchor = _anchor(history, places)
            if anchor is not None:
                old = _entity(anchor, places)
                if old is not None and old["type"] == found["type"]:
                    rewritten = _replace_entity(anchor, message, found["type"], places)
                    if rewritten is not None:
                        return rewritten[:1000], found
    if found is None and any(normalize_tr(word) in _DEICTIC for word in message.split()):
        anchor = _anchor(history, places)
        old = _entity(anchor, places) if anchor is not None else None
        if anchor is not None and old is not None:
            rewritten = _replace_deictic(message, old)
            if rewritten is not None:
                return rewritten[:1000], old
    return None


def _split(message: str, places: Sequence[str]) -> list[str] | None:
    conjunction = re.search(r"\s+ve\s+", message, re.IGNORECASE)
    if conjunction is None:
        return None
    left, right = message[: conjunction.start()].rstrip(", "), message[conjunction.end() :].strip()
    left_words, right_words = left.split(), right.split()
    if not left_words or not right_words:
        return None
    left_fields = [_token_fields(word, places) for word in left_words]
    right_fields = [_token_fields(word, places) for word in right_words]
    left_positions = [index for index, values in enumerate(left_fields) if values]
    right_positions = [index for index, values in enumerate(right_fields) if values]
    if not left_positions or not right_positions:
        return None
    left_domains = {field for values in left_fields for field in values}
    right_first = right_fields[right_positions[0]][0]
    if right_first in left_domains:
        return None
    left_last, right_first_index, right_last = left_positions[-1], right_positions[0], right_positions[-1]
    prefix = " ".join(left_words[: left_positions[0]])
    suffix = " ".join(right_words[right_last + 1 :])
    first = left if left_last + 1 < len(left_words) or not suffix else f"{left} {suffix}"
    second = right if right_first_index > 0 or not prefix else f"{prefix} {right}"
    return [first.strip(), second.strip()]


def _slot_kind(words: Sequence[str]) -> Literal["stop", "line", "station"] | None:
    for kind, terms in _SLOT_TERMS:
        if any(word.startswith(term) for word in words for term in terms):
            return kind
    return None


def _unclear_kind(text: str, places: Sequence[str]) -> Literal["stop", "line", "station", "generic"] | None:
    words = normalize_tr(text).split()
    if not words or (len(words) <= 6 and all(word in _GENERIC_WORDS for word in words)):
        return "generic"
    if len(words) > 4 or _entity(text, places) is not None:
        return None
    kind = _slot_kind(words)
    allowed = _SLOT_FILLERS | frozenset(term for _, terms in _SLOT_TERMS for term in terms)
    if kind is not None and all(
        word in allowed or any(word.startswith(term) for _, terms in _SLOT_TERMS for term in terms) for word in words
    ):
        return kind
    return None


def _unclear_streak(history: Sequence[str], places: Sequence[str]) -> int:
    streak = 1
    for message in reversed(history):
        if _unclear_kind(message, places) is None:
            break
        streak += 1
    return streak


def _turn(
    kind: Literal["greeting", "thanks", "unclear", "split", "followup", "pass"],
    message: str,
    lang: Literal["tr", "en", "ar"],
    history: Sequence[str],
    metadata: Mapping[str, Any] | None = None,
) -> TurnLayer:
    metadata = metadata or {}
    unclear_streak = metadata.get("unclear_streak", 0)
    return {
        "kind": kind,
        "lang": lang,
        "message": message.strip(),
        "parts": metadata.get("parts", []),
        "entity": metadata.get("entity"),
        "ask": metadata.get("ask"),
        "unclear_streak": unclear_streak,
        "handoff": kind == "unclear" and unclear_streak >= 2,
        "first_turn": not history,
    }


def classify_turn(
    message: str,
    history: Sequence[str] = (),
    *,
    places: Sequence[str] = (),
    phrases: Mapping[str, Any] | None = None,
) -> TurnLayer:
    """Classify a turn using only its text, supplied history, place names and phrase file."""
    phrases = phrases or load_phrases()
    lang = _lang(message)
    small_talk = _small_talk(message, phrases)
    if small_talk is not None:
        kind, talk_lang = small_talk
        return _turn(kind, message, talk_lang, history)
    followup = _followup(message, history, places)
    if followup is not None:
        rewritten, found = followup
        return _turn("followup", rewritten, lang, history, {"entity": found})
    parts = _split(message, places)
    if parts is not None:
        return _turn("split", message, lang, history, {"parts": parts})
    ask = _unclear_kind(message, places)
    if ask is not None:
        streak = _unclear_streak(history, places)
        return _turn("unclear", message, lang, history, {"ask": ask, "unclear_streak": streak})
    return _turn("pass", message, lang, history)


def layer_reply(turn: TurnLayer, *, phrases: Mapping[str, Any] | None = None) -> LayerReply | None:
    """Return fixed copy for greetings, thanks and clarification, without an AI notice."""
    phrases = phrases or load_phrases()
    kind = turn["kind"]
    if kind in {"greeting", "thanks"}:
        answer = phrases[kind]["reply"][turn["lang"]]
        rule_id: Literal["layer:greeting", "layer:thanks", "layer:clarify", "layer:handoff"] = f"layer:{kind}"
        return {"answer": answer, "mode": "small_talk", "rule_id": rule_id, "handoff": False}
    if kind != "unclear":
        return None
    ask = turn["ask"] or "generic"
    answer = phrases["clarify"][ask][turn["lang"]]
    rule_id = "layer:clarify"
    if turn["handoff"]:
        answer += " " + phrases["handoff"][turn["lang"]]
        rule_id = "layer:handoff"
    return {"answer": answer, "mode": "clarify", "rule_id": rule_id, "handoff": turn["handoff"]}
