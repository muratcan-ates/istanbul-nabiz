"""Resolve short follow-ups from closed vocabularies and the supplied chat history."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from ibb_mcp.text import normalize_tr

DISTRICTS = (
    "Adalar", "Arnavutköy", "Ataşehir", "Avcılar", "Bağcılar", "Bahçelievler", "Bakırköy", "Başakşehir",
    "Bayrampaşa", "Beşiktaş", "Beykoz", "Beylikdüzü", "Beyoğlu", "Büyükçekmece", "Çatalca", "Çekmeköy",
    "Esenler", "Esenyurt", "Eyüpsultan", "Fatih", "Gaziosmanpaşa", "Güngören", "Kadıköy", "Kağıthane",
    "Kartal", "Küçükçekmece", "Maltepe", "Pendik", "Sancaktepe", "Sarıyer", "Silivri", "Sultanbeyli",
    "Sultangazi", "Şile", "Şişli", "Tuzla", "Ümraniye", "Üsküdar", "Zeytinburnu",
)
DISTRICT_ALIASES = {"Eyüp": "Eyüpsultan"}


def _terms(source: str) -> dict[str, tuple[str, ...]]:
    return {key: tuple(values.split("|")) for key, values in (entry.split(":", 1) for entry in source.split(";"))}


TOPIC_TERMS = _terms(
    "parking:otopark|ispark|parking;metro:metro|marmaray|tramvay|funikuler|subway;bus:otobus|bus|buses;"
    "ferry:vapur|feribot|sehir hatlari|ferry|ferries;stop:durak|stop|stops;station:istasyon|station|stations;"
    "lift:asansor|yuruyen merdiven|merdiven|lift|elevator|escalator;air:hava|aqi|pm10|air|weather;"
    "traffic:trafik|traffic;library:kutuphane|library|libraries;museum:muze|museum|museums"
)

CLARIFY_PLACE = {
    "tr": "Hangi yeri kastettiniz? Semt, ilçe ya da istasyon adını yazın.",
    "en": "Which place do you mean? Write the neighbourhood, district or station name.",
}

_FOR_WHOM_TERMS = _terms(
    "child:cocug|cocuk|oglum|kizim|my child|my kid|my kids|my son|my daughter|child|kid;baby:bebeg|bebek|my baby|baby;mother:annem|my mother|my mum|mother;father:babam|my father|my dad|father;elderly:yasli|elderly|older adult"  # noqa: E501
)
_NEED_TERMS = _terms(
    "step_free:tekerlekli sandalye|merdivensiz|adimsiz|rampa|wheelchair|step free;stroller:bebek arabasi|puset|stroller|pram|pushchair;slow_walk:yavas yuru|az yuru|yurumekte zorlan|walk slowly|short walk"  # noqa: E501
)
_PREF_TERMS = _terms(
    "cheaper:daha ucuz|ucuzu|cheaper|cheapest;closer:daha yakin|yakini|closer|nearer;faster:daha hizli|hizlisi|faster|quicker;fewer_transfers:az aktarma|az aktarmali|aktarmasiz|fewer changes|fewer transfers|no changes"  # noqa: E501
)
_TIME_TERMS = _terms(
    "now:simdi|su an|now;today:bugun|today;tomorrow:yarin|tomorrow;morning:sabah|morning;evening:aksam|bu aksam|tonight|evening;weekend:hafta sonu|haftasonu|cumartesi|pazar|weekend"  # noqa: E501
)
_TIME_KEYS = frozenset(_TIME_TERMS)


def _label_map(source: str) -> dict[str, str]:
    return dict(part.split(":", 1) for part in source.split(";"))


LABELS = {
    "tr": _label_map(
        "parking:otopark;metro:metro;bus:otobüs;ferry:vapur;stop:durak;station:istasyon;lift:asansör;air:hava;"
        "traffic:trafik;library:kütüphane;museum:müze;now:şimdi;today:bugün;tomorrow:yarın;morning:sabah;"
        "evening:akşam;weekend:hafta sonu;child:çocuk için;baby:bebek için;mother:annem için;father:babam için;"
        "elderly:yaşlı biri için;step_free:merdivensiz;stroller:bebek arabasıyla;slow_walk:az yürüyerek;"
        "cheaper:daha ucuz;closer:daha yakın;faster:daha hızlı;fewer_transfers:az aktarmalı"
    ),
    "en": _label_map(
        "parking:parking;metro:metro;bus:bus;ferry:ferry;stop:stop;station:station;lift:elevator;air:weather;"
        "traffic:traffic;library:library;museum:museum;now:now;today:today;tomorrow:tomorrow;morning:morning;"
        "evening:evening;weekend:weekend;child:for a child;baby:for a baby;mother:for my mother;father:for my father;"
        "elderly:for an older adult;step_free:step-free;stroller:with a stroller;slow_walk:with a short walk;"
        "cheaper:cheaper;closer:closer;faster:faster;fewer_transfers:fewer transfers"
    ),
}
_PREFIX_ALIASES = frozenset("otopark|ispark|metro|marmaray|tramvay|funikuler|otobus|vapur|feribot|sehir hatlari|durak|istasyon|asansor|yuruyen merdiven|merdiven|hava|trafik|kutuphane|muze|daha ucuz|daha yakin|daha hizli|az aktarma".split("|"))  # noqa: E501, SIM905
_PREFIX_VALUES = frozenset({"tomorrow", "morning", "evening", "child", "baby", "mother", "father", "elderly", "step_free", "stroller", "slow_walk"})  # noqa: E501
_PLACE_SUFFIXES = ("deki", "daki", "teki", "taki", "den", "dan", "ten", "tan", "de", "da", "te", "ta", "ye", "ya", "e", "a")
_CASE_KINDS = {"de": "loc", "da": "loc", "te": "loc", "ta": "loc", "den": "abl", "dan": "abl", "ten": "abl", "tan": "abl", "e": "dat", "a": "dat", "ye": "dat", "ya": "dat", "deki": "loc_ki", "daki": "loc_ki", "teki": "loc_ki", "taki": "loc_ki"}  # noqa: E501
_NEW_QUESTION_MARKERS = frozenset({"nasil", "how", "giderim", "gider", "route", "var", "mi", "mu", "acik", "open", "is", "are", "does", "which", "hangi", "hangisi", "nerede", "what"})  # noqa: E501
_CLOCK = re.compile(r"(?<!\d)(?:([01]?\d|2[0-3])[:.]([0-5]\d))(?!\d)")
_TR_HOUR = re.compile(r"\bsaat\s+(2[0-3]|1\d|0?\d)\b")
_EN_HOUR = re.compile(r"\bat\s+(1[0-2]|0?\d)\s*(am|pm)\b")
_CORRECTION_START = ("yanlis anladin", "yanlis anladiniz", "you misunderstood")
_RESET_PATTERNS = (
    r"bastan basla\w*", r"bastan alalim", r"yeni (?:bir )?soru", r"baska bir sey soracag\w*",
    r"bosver\w*", r"unut bunu", r"start over", r"new question", r"never mind", r"forget it",
)


@dataclass(frozen=True)
class Slots:
    places: tuple[str, ...] = ()
    topic: str | None = None
    time: str | None = None
    for_whom: str | None = None
    needs: tuple[str, ...] = ()
    prefs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Resolution:
    action: Literal["new", "followup", "correction", "reset", "clarify", "pass"]
    question: str
    slots: Slots
    changed: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()
    ask: str | None = None
    lang: Literal["tr", "en"] = "tr"


def _ordered(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _term_matches(text: str, table: dict[str, tuple[str, ...]]) -> list[tuple[int, int, str]]:
    folded = normalize_tr(text)
    found: list[tuple[int, int, str]] = []
    for value, aliases in table.items():
        for alias in aliases:
            parts = normalize_tr(alias).split()
            if not parts:
                continue
            end = re.escape(parts[-1]) + (r"[a-z0-9]*" if value in _PREFIX_VALUES or alias in _PREFIX_ALIASES else "")
            pattern = r"(?<![a-z0-9])" + r"\s+".join([*(re.escape(part) for part in parts[:-1]), end]) + r"(?![a-z0-9])"
            found.extend((m.start(), m.end(), value) for m in re.finditer(pattern, folded) if not (value == "air" and m.group(0).startswith("havalimani")))  # noqa: E501
    found.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    chosen: list[tuple[int, int, str]] = []
    for item in found:
        if any(item[0] < prior[1] and prior[0] < item[1] for prior in chosen):
            continue
        chosen.append(item)
    return sorted(chosen)


def _place_mentions(message: str, places: Sequence[str]) -> list[tuple[int, int, str]]:
    folded = normalize_tr(message)
    names = _ordered(tuple(places) + DISTRICTS + tuple(DISTRICT_ALIASES))
    candidates = [(normalize_tr(name), DISTRICT_ALIASES.get(name, name)) for name in names if normalize_tr(name)]
    candidates.sort(key=lambda item: -len(item[0]))
    found: list[tuple[int, int, str]] = []
    endings = "|".join(sorted(_PLACE_SUFFIXES, key=len, reverse=True))
    for key, name in candidates:
        pattern = rf"(?<![a-z0-9]){re.escape(key)}(?:\s*(?:{endings}))?(?![a-z0-9])"
        for match in re.finditer(pattern, folded):
            tail = folded[match.end() :].lstrip()
            if name == "Bebek" and tail.startswith(("arabasi", "icin")):
                continue
            found.append((match.start(), match.end(), name))
    found.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    chosen: list[tuple[int, int, str]] = []
    for item in found:
        if not any(item[0] < prior[1] and prior[0] < item[1] or prior[2] == item[2] and prior[0] == item[0] for prior in chosen):
            chosen.append(item)
    return chosen


def _time_mentions(message: str) -> list[tuple[int, int, str]]:
    folded = normalize_tr(message)
    found = _term_matches(folded, _TIME_TERMS)
    found.extend((m.start(), m.end(), f"{int(m.group(1)):02d}:{m.group(2)}") for m in _CLOCK.finditer(message))
    found.extend((m.start(), m.end(), f"{int(m.group(1)):02d}:00") for m in _TR_HOUR.finditer(folded))
    for match in _EN_HOUR.finditer(folded):
        hour = int(match.group(1)) % 12 + (12 if match.group(2) == "pm" else 0)
        found.append((match.start(), match.end(), f"{hour:02d}:00"))
    found.sort(key=lambda item: item[0])
    unique: list[tuple[int, int, str]] = []
    for item in found:
        if item[2] not in {hit[2] for hit in unique}:
            unique.append(item)
    return unique


def _extract_many(message: str, places: Sequence[str]) -> dict[str, list[tuple[int, int, str]]]:
    topics = _term_matches(message, TOPIC_TERMS)
    for_whom = _term_matches(message, _FOR_WHOM_TERMS)
    stroller_spans = [item for item in _term_matches(message, _NEED_TERMS) if item[2] == "stroller"]
    for_whom = [item for item in for_whom if item[2] != "baby" or not any(item[0] >= span[0] and item[0] < span[1] for span in stroller_spans)]  # noqa: E501
    return {
        "places": _place_mentions(message, places), "topic": topics, "time": _time_mentions(message), "for_whom": for_whom,
        "needs": _term_matches(message, _NEED_TERMS), "prefs": _term_matches(message, _PREF_TERMS),
    }


def _combine_time(values: Sequence[str]) -> str | None:
    unique = _ordered(values)
    if not unique:
        return None
    day = next((value for value in reversed(unique) if value in _TIME_KEYS), None)
    clock = next((value for value in reversed(unique) if value not in _TIME_KEYS), None)
    return " ".join(value for value in (day, clock) if value is not None)


def extract(message: str, *, places: Sequence[str] = ()) -> Slots:
    """Extract only canonical values from this message's fixed vocabularies."""
    mentions = _extract_many(message, places)
    values = {key: [item[2] for item in rows] for key, rows in mentions.items()}
    return Slots(tuple(values["places"]), values["topic"][0] if values["topic"] else None,
        _combine_time(values["time"]), values["for_whom"][-1] if values["for_whom"] else None,
        _ordered(values["needs"]), _ordered(values["prefs"]))


def with_case(name: str, suffix: str) -> str:
    """Attach a supported Turkish location ending from the previous place token."""
    folded = normalize_tr(re.split(r"['’]", suffix)[-1]).split()
    kind = _CASE_KINDS.get(folded[-1] if folded else "")
    if kind is None:
        return name
    last_vowel = next((char for char in reversed(name.casefold()) if char in "aeıiöouü"), "a")
    thick = last_vowel in "aıou"
    hard = name.casefold()[-1:] in {"f", "s", "t", "k", "ç", "ş", "h", "p"}
    vowel = "a" if thick else "e"
    ending = (("t" if hard else "d") + vowel + ("ki" if kind == "loc_ki" else "n" if kind == "abl" else "")) if kind != "dat" else ("y" if name.casefold()[-1:] in "aeıioöuü" else "") + vowel  # noqa: E501
    return f"{name}'{ending}"


def _replace_surface(text: str, category: str, old: str, new: str, lang: str) -> str:
    table = {"topic": TOPIC_TERMS, "time": _TIME_TERMS, "for_whom": _FOR_WHOM_TERMS, "needs": _NEED_TERMS, "prefs": _PREF_TERMS}.get(category, {})  # noqa: E501
    aliases = sorted(table.get(old, ()), key=len, reverse=True)
    for alias in aliases:
        pattern = re.compile(r"(?<!\w)" + re.escape(alias).replace(r"\ ", r"\s+") + r"\w*(?!\w)", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            return text[: match.start()] + LABELS[lang].get(new, new) + text[match.end() :]
    if category == "time" and re.fullmatch(r"\d{2}:\d{2}", old):
        match = re.search(re.escape(old[:2]) + r"[:.]" + re.escape(old[3:]), text)
        if match:
            return text[: match.start()] + new + text[match.end() :]
    return text


def _replace_place(text: str, old: str, new: str, places: Sequence[str], occurrence: int = 0) -> str | None:
    del places
    name = r"\s+".join(re.escape(part) for part in old.split())
    pattern = re.compile(rf"(?<!\w){name}(?P<suffix>['’]?(?:{'|'.join(_PLACE_SUFFIXES)}))?(?!\w)", re.IGNORECASE)
    matches = list(pattern.finditer(text))
    if occurrence >= len(matches):
        return None
    match = matches[occurrence]
    suffix = match.group("suffix") or ""
    replacement = with_case(new, suffix) if suffix else new
    return text[: match.start()] + replacement + text[match.end() :]


def _time_parts(value: str | None) -> tuple[str, ...]:
    return tuple(value.split()) if value else ()


def _slot_values(slots: Slots, category: str) -> tuple[str, ...]:
    value = getattr(slots, category)
    return _time_parts(value) if category == "time" else tuple(value) if category in {"places", "needs", "prefs"} else (value,) if value else ()  # noqa: E501


def _set_value(slots: Slots, category: str, old: str | None, new: str | None) -> Slots:
    values = list(_slot_values(slots, category))
    if old in values:
        values[values.index(old)] = new
    elif new:
        values = [new]
    values = [value for value in values if value]
    result = _combine_time(values) if category == "time" else _ordered(values) if category in {"places", "needs", "prefs"} else values[-1] if values else None  # noqa: E501
    return replace(slots, **{category: result})


def _reset(message: str) -> bool:
    text = normalize_tr(message).strip()
    return any(re.fullmatch(pattern, text) for pattern in _RESET_PATTERNS)


def _has_hint(message: str) -> bool:
    text = normalize_tr(message)
    return text.startswith(("peki ", "ya ", "bir de ", "o zaman ", "what about ", "how about ", "and "))


def _is_short_followup(message: str) -> bool:
    return len(normalize_tr(message).split()) <= 5 or _has_hint(message)


def _is_new_question(message: str, slots: Slots) -> bool:
    if slots.topic:
        return True
    words = normalize_tr(message).split()
    return bool(slots.places and not _has_hint(message) and len(words) >= 3 and any(word in _NEW_QUESTION_MARKERS for word in words))  # noqa: E501


def _negative_pair(
    category: str, values: list[tuple[int, int, str]], negative: re.Match[str], text: str
) -> tuple[str, str | None, str | None, bool, str | None] | None:
    first, second = values[:2]
    position = negative.start()
    if first[0] < position < second[0]:
        reverse = any((negative.group(1) == "not", "i meant" in text, "i mean" in text))
        return (category, second[2], first[2], False, None) if reverse else (category, first[2], second[2], False, None)
    if position < first[0] or second[0] < position:
        before = second[0] < position
        return (category, second[2], first[2], False, None) if before else (category, first[2], second[2], False, None)
    return None


def _correction_candidate(message: str, places: Sequence[str]) -> tuple[str, str | None, str | None, bool, str | None] | None:
    """Return category, old, new, old_only, ask for a recognized correction phrase."""
    text = normalize_tr(message)
    mentions = _extract_many(message, places)
    correction_prefix = any(text.startswith(prefix) for prefix in _CORRECTION_START)
    meant = any(phrase in text for phrase in ("demek istedim", "kastettim", "olacak", "i meant", "i mean", "will be"))
    negative = re.search(r"\b(degil|not)\b", text)
    if negative:
        for category, values in mentions.items():
            if len(values) < 2:
                continue
            candidate = _negative_pair(category, values, negative, text)
            if candidate:
                return candidate
        if text.endswith((" degil", " not")):  # noqa: E501
            single = next(((category, values[-1][2]) for category, values in mentions.items() if values), None)
            if single:
                return single[0], single[1], None, True, None
    wants_correction = any((correction_prefix, meant, text.startswith(("hayir ", "no "))))
    if wants_correction:
        single = next(((category, values) for category, values in mentions.items() if values), None)
        if single:
            category, values = single
            return (
                (category, values[-2][2], values[-1][2], False, None)
                if len(values) > 1
                else (category, None, values[-1][2], False, None)
            )
        if correction_prefix:
            return "generic", None, None, False, "generic"
    return None


def _render(anchor: str, slots: Slots, base: Slots, lang: str) -> str:
    labels: list[str] = []
    base_time = set(_time_parts(base.time))
    labels.extend(LABELS[lang].get(value, value) for value in _time_parts(slots.time) if value not in base_time)
    if slots.for_whom and slots.for_whom != base.for_whom:
        labels.append(LABELS[lang][slots.for_whom])
    labels.extend(LABELS[lang][value] for value in slots.needs if value not in base.needs)
    labels.extend(LABELS[lang][value] for value in slots.prefs if value not in base.prefs)
    question = anchor + (f" ({', '.join(labels)})" if labels else "")
    return question if len(question) <= 1000 else ""


def _update_correction(
    anchor: str | None,
    slots: Slots,
    base: Slots,
    candidate: tuple[str, str | None, str | None, bool, str | None],
    lang: str,
    places: Sequence[str],
) -> tuple[str | None, Slots, Slots, tuple[str, ...], tuple[str, ...], str | None, bool]:
    category, old, new, old_only, ask = candidate
    current = _slot_values(slots, category)
    if category == "generic":
        return anchor, slots, base, (), (), "generic", False
    if old is not None and old not in current:
        return anchor, slots, base, (), (), None, False
    if old is None:
        if len(current) != 1:
            return anchor, slots, base, (), (), "places" if category == "places" and current else None, False
        old = current[0]
    dropped = (f"{category}:{old}",)
    if old_only:
        return anchor, _set_value(slots, category, old, None), _set_value(base, category, old, None), (category,), dropped, category, True  # noqa: E501
    if new is None:
        return anchor, slots, base, (), (), category, False
    new_anchor = anchor
    if anchor:
        if category == "places":
            index = base.places[: base.places.index(old)].count(old) if old in base.places else 0
            new_anchor = _replace_place(anchor, old, new, places, index)
        else:
            new_anchor = _replace_surface(anchor, category, old, new, lang)
    if category == "places" and anchor and new_anchor is None:
        return anchor, slots, base, (), (), None, False
    new_slots = _set_value(slots, category, old, new)
    new_base = _set_value(base, category, old, new) if old in _slot_values(base, category) else base
    return new_anchor, new_slots, new_base, (category,), dropped, None, True


def _history_state(earlier: Sequence[str], places: Sequence[str], lang: str) -> tuple[str | None, Slots, Slots]:
    anchor: str | None = None
    slots = Slots()
    base = Slots()
    for message in earlier[-8:]:
        if _reset(message):
            anchor, slots, base = None, Slots(), Slots()
            continue
        candidate = _correction_candidate(message, places)
        if candidate:
            anchor, slots, base, _, _, _, applied = _update_correction(anchor, slots, base, candidate, lang, places)
            if applied or candidate[1] is not None or candidate[4] is not None:
                continue
        found = extract(message, places=places)
        if _is_new_question(message, found):
            anchor, slots, base = message, found, found
            continue
        if anchor and _is_short_followup(message):
            prior_places = slots.places
            slots = _merge_followup(slots, found)
            if found.places and len(slots.places) == 1:
                updated = _replace_place(anchor, prior_places[0], found.places[0], places) if prior_places else None
                if updated:
                    anchor = updated
                    base = extract(anchor, places=places)
    return anchor, slots, base


def _merge_followup(slots: Slots, found: Slots) -> Slots:
    values = slots
    if found.places:
        values = replace(values, places=found.places if len(values.places) <= 1 else values.places)
    for field in ("topic", "for_whom"):
        if getattr(found, field):
            values = replace(values, **{field: getattr(found, field)})
    if found.time:
        values = replace(values, time=_combine_time(_time_parts(values.time) + _time_parts(found.time)))
    for field in ("needs", "prefs"):
        if getattr(found, field):
            values = replace(values, **{field: _ordered(getattr(values, field) + getattr(found, field))})
    return values


def _correction_result(message: str, candidate: tuple | None, state: tuple, lang: str, places: Sequence[str]) -> Resolution | None:  # noqa: E501
    if not candidate:
        return None
    anchor, slots, base = state
    new_anchor, new_slots, new_base, changed, dropped, ask, applied = _update_correction(anchor, slots, base, candidate, lang, places)  # noqa: E501
    if applied and (candidate[3] or ask):
        return Resolution("clarify", message, new_slots, changed, dropped, ask, lang)
    if applied:
        question = _render(new_anchor or message, new_slots, new_base, lang)
        return Resolution("correction", question or message, new_slots, changed, dropped, lang=lang)
    if ask:
        return Resolution("clarify", message, slots, (), (), ask, lang)
    return Resolution("pass", message, slots, lang=lang) if candidate[1] is not None else None


def resolve(message: str, earlier: Sequence[str], *, places: Sequence[str] = (), lang: str = "tr") -> Resolution:
    """Replay at most eight supplied turns, then resolve this message without stored state."""
    language: Literal["tr", "en"] = "en" if lang == "en" else "tr"
    anchor, slots, base = _history_state(earlier, places, language)
    if _reset(message):
        return Resolution("reset", message, Slots(), _slot_names(slots), lang=language)

    correction = _correction_result(message, _correction_candidate(message, places), (anchor, slots, base), language, places)
    if correction:
        return correction

    found = extract(message, places=places)
    if _is_new_question(message, found):
        return Resolution("new", message, found, _slot_names(found), lang=language)

    has_new_slot = bool(found.places or found.time or found.for_whom or found.needs or found.prefs)
    if anchor and not found.topic and has_new_slot and _is_short_followup(message):
        merged = _merge_followup(slots, found)
        changed = tuple(name for name in _slot_names(merged) if getattr(merged, name) != getattr(slots, name))
        updated_anchor = anchor
        updated_base = base
        if found.places and len(slots.places) == 1 and len(found.places) == 1:
            updated_anchor = _replace_place(anchor, slots.places[0], found.places[0], places) or anchor
            merged = replace(merged, places=(found.places[0],))
            updated_base = extract(updated_anchor, places=places)
            if found.places[0] != slots.places[0] and "places" not in changed:
                changed += ("places",)
        question = _render(updated_anchor, merged, updated_base, language)
        if question:
            return Resolution("followup", question, merged, _ordered(changed), lang=language)

    if not anchor and not found.topic and not found.places:
        return Resolution("pass", message, Slots(), lang=language)
    return Resolution("pass", message, slots if anchor else found, lang=language)


def _slot_names(slots: Slots) -> tuple[str, ...]:
    return tuple(name for name in ("places", "topic", "time", "for_whom", "needs", "prefs") if getattr(slots, name))
