"""The emergency rules in the card languages, and a guess at the language a message is written in.

This is the first, synchronous layer of the multilingual emergency check (DECISIONS #40): fixed words,
no model, no I/O, compiled once at import. :func:`nabiz.console.policy.emergency_intent` asks it after
the Turkish rules, so a plea in Russian, Persian or Spanish stops the chat before any tool or model runs,
exactly as a Turkish one does. The optional model layer (:mod:`emergency_model`) only ever adds an
emergency this layer missed; it never takes one away.

:func:`guess_language` reads letters and a few function words. It picks the card language when more
than one language's rule fired ("police" is English and French) and tells the model layer whether a
message is outside Turkish and English. It is a guess, not a classifier: ``None`` when it cannot tell.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from nabiz.agent.templates_i18n import FIXED
from nabiz.console.emergency_text import CARD_LANGS
from nabiz.console.emergency_vocab import ACUTE_SIGNS, MEDICAL_ADVICE, SERVICE_CUES, TURKISH_MASKS, VOCAB, Vocab
from nabiz.console.health_mask import HEALTH_LABEL, HEALTH_LABEL_OTHER, health_spans
from nabiz.console.pii_guard import fold_keep_length

#: Arabic and Persian spell the same letters two ways; the Turkish dotless i; "!" kept as a token.
_LETTER_FORMS = str.maketrans({"ة": "ه", "ى": "ي", "ی": "ي", "ک": "ك", "ـ": None, "‌": " ", "‍": None, "ı": "i", "!": " ! "})
#: Arabic writes "and", "so", "with", "for", "like" and "the" onto the word.
_CLITICS = "(?:وال|فال|بال|كال|لل|ال|و|ف|ب|ل|ك)?"
#: Words that do not stop a plea from standing alone ("Hilfe bitte!", "помогите пожалуйста").
_POLITE = frozenset(
    ("please", "lutfen", "bitte", "por", "favor", "per", "favore", "s", "il", "vous", "plait", "пожалуиста", "будь",
     "ласка", "لطفا", "من", "فضلك", "لو", "سمحت")
)  # fmt: skip
#: Who a card falls back to when the model names a language the card does not speak.
#: The line an answer carries below it when the question stated a condition (KARAR 5).
CHRONIC_NOTE = FIXED["EMERGENCY"]["tr"]
_NEAREST_CARD = {"az": "tr", "tk": "tr", "uz": "ru", "kk": "ru", "ky": "ru", "tg": "ru", "be": "ru"}


def fold_for_emergency(text: str) -> str:
    """Case, accents, Arabic-script letter forms and punctuation folded away; words joined by one space."""
    text = unicodedata.normalize("NFKC", text).translate(_LETTER_FORMS)
    stripped = "".join(char for char in unicodedata.normalize("NFD", text) if not unicodedata.combining(char))
    return " ".join(re.findall(r"\w+|!", unicodedata.normalize("NFC", stripped).casefold()))


def _phrase(phrase: str, clitics: bool) -> str:
    words = []
    for word in phrase.split():
        body = re.escape(fold_for_emergency(word.rstrip("*")))
        words.append((_CLITICS if clitics else "") + body + (r"\w*" if word.endswith("*") else ""))
    return r"(?<!\w)" + " ".join(words) + r"(?!\w)"


def _any_of(phrases: tuple[str, ...], clitics: bool) -> re.Pattern[str] | None:
    # Longest first: at one position "help me" must win over "help", or "Help me!" would not stand alone.
    ordered = sorted(phrases, key=len, reverse=True)
    return re.compile("|".join(f"(?:{_phrase(p, clitics)})" for p in ordered)) if phrases else None


@dataclass(frozen=True)
class _Rules:
    terms: re.Pattern[str] | None
    gas: re.Pattern[str] | None
    pleas: re.Pattern[str] | None
    gated: re.Pattern[str] | None
    company: re.Pattern[str] | None


def _compile(vocab: Vocab) -> _Rules:
    c = vocab.clitics
    return _Rules(
        terms=_any_of(vocab.terms, c),
        gas=_any_of(vocab.gas, c),
        pleas=_any_of(vocab.pleas, c),
        gated=_any_of(vocab.gated, c),
        company=_any_of(vocab.company + vocab.pleas, c),
    )


_RULES = {lang: _compile(vocab) for lang, vocab in VOCAB.items()}
# Masks and negations hold for every language at once: "حريق" is Arabic and Persian, "accident" English and
# French, and "لا يوجد حريق" or "by accident" must not fire under the other language's rules.
_MASKS = re.compile("|".join(f"(?:{_phrase(mask, vocab.clitics)})" for vocab in VOCAB.values() for mask in vocab.masks))
_NEGATIONS = tuple(dict.fromkeys(fold_for_emergency(item) for vocab in VOCAB.values() for item in vocab.negations))
#: A shout or a cut-out mask ends the words a negation may reach over: "No! Fire!" is a fire.
_BOUNDARIES = frozenset({"!", "|"})


@dataclass(frozen=True)
class RuleHit:
    """Which languages' rules fired, and whether one of them was a gas leak."""

    langs: frozenset[str]
    gas: bool


def _negated(text: str, start: int) -> bool:
    words = text[:start].split()[-3:]
    for index in range(len(words) - 1, -1, -1):
        if words[index] in _BOUNDARIES:
            words = words[index + 1 :]
            break
    before = " ".join(words)
    return bool(before) and any(before == item or before.endswith(f" {item}") for item in _NEGATIONS)


def _live(pattern: re.Pattern[str] | None, text: str) -> list[re.Match[str]]:
    """The matches of ``pattern`` that no negation right before them cancels."""
    if pattern is None:
        return []
    return [match for match in pattern.finditer(text) if not _negated(text, match.start())]


def _shouted(text: str, match: re.Match[str]) -> bool:
    return text[match.end() :].lstrip().startswith("!")


def _alone(text: str, match: re.Match[str]) -> bool:
    rest = (text[: match.start()] + " " + text[match.end() :]).split()
    return all(word == "!" or word in _POLITE for word in rest)


def _accompanied(text: str, match: re.Match[str], rules: _Rules) -> bool:
    return any(other.end() <= match.start() or other.start() >= match.end() for other in _live(rules.company, text))


def _fires(text: str, rules: _Rules) -> tuple[bool, bool]:
    """(an emergency, a gas leak) under one language's rules, on text with its masks already cut out."""
    if _live(rules.gas, text):
        return True, True
    if _live(rules.terms, text):
        return True, False
    for match in _live(rules.pleas, text):
        if _alone(text, match) or _shouted(text, match) or _accompanied(text, match, rules):
            return True, False
    for match in _live(rules.gated, text):
        if _shouted(text, match) or _accompanied(text, match, rules):
            return True, False
    return False, False


def rule_match(message: str) -> RuleHit | None:
    """The card languages whose emergency rules fire on ``message`` as written or with its spelled-out words
    joined ("П.О.Ж.А.Р", :func:`unsplit`), or ``None`` when none does."""
    for reading in emergency_readings(message):
        if (hit := _rule_match(reading)) is not None:
            return hit
    return None


def _rule_match(message: str) -> RuleHit | None:
    text = _MASKS.sub(" | ", fold_for_emergency(message))
    langs, gas = set(), False
    for lang, rules in _RULES.items():
        fired, leak = _fires(text, rules)
        if fired:
            langs.add(lang)
            gas = gas or leak
    return RuleHit(frozenset(langs), gas) if langs else None


# -- the language a message is written in ----------------------------------------------------------
_SCRIPTS = (
    ("hy", 0x0530, 0x058F), ("he", 0x0590, 0x05FF), ("ar", 0x0600, 0x06FF), ("ar", 0x0750, 0x077F),
    ("hi", 0x0900, 0x097F), ("th", 0x0E00, 0x0E7F), ("ka", 0x10A0, 0x10FF), ("ko", 0x1100, 0x11FF),
    ("el", 0x0370, 0x03FF), ("ru", 0x0400, 0x04FF), ("ja", 0x3040, 0x30FF), ("zh", 0x3400, 0x4DBF),
    ("zh", 0x4E00, 0x9FFF), ("ko", 0xAC00, 0xD7AF), ("ar", 0xFB50, 0xFDFF), ("ar", 0xFE70, 0xFEFF),
)  # fmt: skip
#: Letters that name a language inside its script. Checked in order: the first hit wins.
_ARABIC_SCRIPT = (("ur", "ٹڈڑںےھ"), ("fa", "پچژگیک"))
_CYRILLIC = (("kk", "әғқңөұүһ"), ("be", "ў"), ("uk", "їєґі"), ("sr", "ђјљњћџѓќ"), ("ru", "ыэё"), ("bg", "ъ"))
_LATIN_LETTERS = (
    ("az", "ə"), ("tr", "ğış"), ("de", "ßä"), ("es", "ñ¿¡"), ("fr", "œâêîôûëïù"), ("it", "ìò"),
    ("pl", "ąęłńśźż"), ("ro", "șțăâ"), ("cs", "řěůčšž"), ("hu", "őű"), ("pt", "ãõ"),
)  # fmt: skip
#: A handful of function words per Latin-script language, folded.
_FUNCTION_WORDS = {
    "tr": "ve bir bu var yok mi mu ne icin ile cok lutfen nasil nerede nereye ben benim acil hemen",
    "en": "the a an is are my there and of to in it please i you not at on with this where what how me",
    "de": "der die das und ist ein eine mein meine nicht ich hat es bitte mit zu wo wie was in heute",
    "fr": "le la les et est un une il elle ne pas au du de je mon ma ou comment svp vous",
    "es": "el la los las y es un una de del mi no por favor que en con hay donde como usted",
    "it": "il lo gli e un una di del mio mia non per che ce dove come sono ho in",
    "nl": "de het een en is ik niet mijn waar hoe wat er",
    "pt": "o os as e um uma do da meu minha nao por que em com onde",
}
_WORD_SETS = {lang: frozenset(words.split()) for lang, words in _FUNCTION_WORDS.items()}


def _script(text: str) -> str | None:
    counts: dict[str, int] = {}
    for char in text:
        point = ord(char)
        for name, low, high in _SCRIPTS:
            if low <= point <= high:
                counts[name] = counts.get(name, 0) + 1
                break
        else:
            if char.isalpha():
                counts["latin"] = counts.get("latin", 0) + 1
    return max(counts, key=counts.__getitem__) if counts else None


def _marked(text: str, table: tuple[tuple[str, str], ...]) -> str | None:
    return next((lang for lang, letters in table if any(letter in text for letter in letters)), None)


def _latin(text: str) -> str | None:
    words = fold_for_emergency(text).split()
    scores = {lang: sum(word in vocab for word in words) for lang, vocab in _WORD_SETS.items()}
    if marked := _marked(text, _LATIN_LETTERS):
        scores[marked] = scores.get(marked, 0) + 3
    # ç, ö and ü are Turkish too ("çocuk düştü"): a weak Turkish hint, so they never make a message French.
    scores["tr"] += sum(letter in text for letter in "çöü")
    best = max(scores, key=scores.__getitem__)
    return best if scores[best] > 0 else None


#: A follow-up this short ("Peki Kartal'da?", "Und morgen?") has too few words for the function-word vote.
_SHORT_WORDS, _SHORT_CHARS = 4, 24
#: Strong Turkish in a short follow-up: a case ending after an apostrophe ("Kartal'da", "Üsküdar'a",
#: "Kadıköy'den"), a letter only Turkish uses, or a question particle standing alone ("Yarın da mı?").
_TURKISH_SUFFIX = re.compile(r"[^\W\d_]['’](?:[dt][ae]n?|y?[ae]|n?[ıiuü]n|y?[ıiuü]|[dt][ae]ki|l[ae]r\w*)(?![^\W\d_])")
_TURKISH_PARTICLE = re.compile(r"(?<![^\W\d_])m[ıiuü](?:s[ıiuü]n|y[ıiuü]m)?(?![^\W\d_])")
_TURKISH_ONLY = "ğış"
#: Function words of other languages that are Turkish words too: "Peki Kartal da?" is not Portuguese.
_TURKISH_TOO = frozenset(("da", "de", "ya", "a", "e", "o", "en", "ne", "mi", "mu", "ki", "bu", "ve"))


def _short(text: str) -> bool:
    return len(text.split()) <= _SHORT_WORDS or len(text.strip()) <= _SHORT_CHARS


def _strong_turkish(text: str) -> bool:
    lowered = text.replace("I", "ı").replace("İ", "i").lower()
    return bool(
        _TURKISH_SUFFIX.search(lowered) or _TURKISH_PARTICLE.search(lowered) or any(ch in lowered for ch in _TURKISH_ONLY)
    )


def _weak_latin(text: str, lang: str) -> bool:
    """A short Latin guess resting only on words Turkish writes too ("da", "de", "ya") and no letter of its own."""
    words = fold_for_emergency(text).split()
    backed = any(word in _WORD_SETS.get(lang, ()) and word not in _TURKISH_TOO for word in words)
    return not backed and _marked(text, _LATIN_LETTERS) != lang


def guess_language(message: str, previous: str | None = None) -> str | None:
    """A two-letter guess at the message's language, or ``None`` when its letters say nothing.

    A short follow-up in Latin letters is judged apart (Görev 0-b): strong Turkish is Turkish, and a weak
    guess ("Peki Kartal'da?" once read as Portuguese for its "da") gives way to ``previous``, the
    conversation's language, or else Turkish, so no model is asked about it. "Und morgen?" and "And in
    Kartal?" keep German and English: each has a function word of its own.
    """
    text = unicodedata.normalize("NFC", message)
    lowered = text.lower()
    script = _script(lowered)
    if script == "ar":
        return _marked(lowered, _ARABIC_SCRIPT) or "ar"
    if script == "ru":
        return _marked(lowered, _CYRILLIC) or "ru"
    if script != "latin":
        return script
    if _short(text) and _strong_turkish(text):
        return "tr"
    guessed = _latin(lowered)
    if _short(text) and (guessed is None or _weak_latin(lowered, guessed)):
        return previous or "tr"
    return guessed


def card_lang_for(code: str | None) -> str:
    """The card language for a language code: itself when the card speaks it, a near one, else English."""
    code = (code or "").strip().lower()[:2]
    if code in CARD_LANGS:
        return code
    return _NEAREST_CARD.get(code, "en")


def pick_card_lang(message: str, langs: frozenset[str]) -> str:
    """Among the languages whose rules fired, the one the message is written in; else the first in card order."""
    guessed = guess_language(message)
    if guessed in langs:
        return guessed
    return next(lang for lang in CARD_LANGS if lang in langs)


# -- a stated condition next to an everyday question (KARAR 5) --------------------------------------------
# "Kalp hastasıyım, M4'te asansör var mı?" states a chronic condition and asks about a lift: the Turkish
# rules' "kalp" must not take the question away. An acute sign in the same message ("göğsüm çok ağrıyor",
# "bayılacak gibiyim") keeps every rule as it was, and with a stated condition opens the emergency card on its
# own. The health phrases are the request mask's (nabiz.console.health_mask), so one list says what a
# condition is.


def _stems(entries: tuple[str, ...]) -> re.Pattern[str]:
    """Word-start matches over :func:`~nabiz.console.pii_guard.fold_keep_length` text; ``!`` ends a whole word."""
    parts = (re.escape(fold_keep_length(entry.rstrip("!"))) + (r"(?!\w)" if entry.endswith("!") else "") for entry in entries)
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + ")")


_ACUTE_RE = _stems(ACUTE_SIGNS)
_MEDICAL_ADVICE_RE = _stems(MEDICAL_ADVICE)
_SERVICE_RE = _stems(SERVICE_CUES)
_TURKISH_MASK_RE = _stems(TURKISH_MASKS)


#: The input guard (text_guard.check_input) has already put a label where the statement was; the label is
#: a stated condition too, so the rules below read "[sağlık bilgisi gizlendi], bayılacak gibiyim" as before.
_CONDITION_LABEL_RE = re.compile("|".join(re.escape(fold_keep_length(label)) for label in (HEALTH_LABEL, HEALTH_LABEL_OTHER)))


def _condition_spans(message: str) -> list[tuple[int, int]]:
    """A stated condition, as written or already masked."""
    labels = [match.span() for match in _CONDITION_LABEL_RE.finditer(fold_keep_length(message))]
    return health_spans(message) + labels


def acute_signal(message: str) -> bool:
    """Does the message carry an acute sign: pain, breath, consciousness, bleeding, a fall, a plea?"""
    return _ACUTE_RE.search(fold_keep_length(message)) is not None


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    for start, end in spans:
        text = text[:start] + " " * (end - start) + text[end:]
    return text


def without_calm_condition(message: str) -> str:
    """The text the emergency rules read: a stated condition and a Turkish fire-equipment phrase blanked,
    when nothing in the message is acute.

    "Kalp hastasıyım, M4'te asansör var mı?" has no "kalp" left to fire on and "Yangın tüpü nereden alınır?"
    no "yangın", while "Kalp hastasıyım, göğsüm ağrıyor" comes back unchanged. Blanking keeps every offset.
    """
    if acute_signal(message):
        return message
    masks = [match.span() for match in _TURKISH_MASK_RE.finditer(fold_keep_length(message))]
    return _blank(message, _condition_spans(message) + masks)


def acute_with_condition(message: str) -> bool:
    """A stated condition with an acute sign ("Diyabetim var, bayılacak gibiyim"): the emergency card opens."""
    return bool(_condition_spans(message)) and acute_signal(message)


def ordinary_question(message: str) -> str | None:
    """The question without its stated condition, when it states one, asks about travel or a service, asks
    no medical advice and carries no acute sign; else ``None``. R-06 reads the rest: "Diyaliz hastasıyım,
    Kartal'a nasıl giderim?" is a route question; "Diyabetim var, hangi ilacı kullanmalıyım?" and "Kalp
    hastasıyım, bugün yürüyebilir miyim?" stay refused."""
    spans = _condition_spans(message)
    if not spans or acute_signal(message):
        return None
    rest = _blank(message, spans)
    folded = fold_keep_length(rest)
    if _MEDICAL_ADVICE_RE.search(folded) or not _SERVICE_RE.search(folded):
        return None
    return rest


def chronic_note(message: str) -> str | None:
    """:data:`CHRONIC_NOTE` below an answer to a question that stated a condition, else ``None``."""
    return CHRONIC_NOTE if _condition_spans(message) else None


# -- an emergency word spelled out or split (A7, rt-46) -------------------------------------------------------
# "Y.a.n.g.ı.n var", "y a n g ı n", "YAN-GIN", "İ-M-D-A-T": the letters are there, the word is not. The
# rules read the message twice, as written and with these runs joined, and an emergency in either counts,
# so joining can only add a card, never take one away. "Y.K.S." joins to "YKS" and "A.Ş." stays as it is:
# neither is an emergency word. The page's rules (static/js/voice_intent.js) need the same step.

#: Three or more single letters, each followed by a dot, a hyphen, a space, an underscore or a middle dot.
_SPELLED = re.compile(r"(?<!\w)[^\W\d_](?:[.\-\s_·*•]+[^\W\d_](?!\w)){2,}")
#: Parts of one word split by hyphens or dots: "YAN-GIN", "yan-gın", "am.bu.lans".
_SPLIT = re.compile(r"(?<!\w)[^\W\d_]{2,}(?:[-.·][^\W\d_]{2,})+(?!\w)")
_JOINERS = re.compile(r"[.\-\s_·*•]+")


def unsplit(message: str) -> str:
    """The message with spelled-out and split words joined; the message itself when there are none."""
    joined = _SPELLED.sub(lambda match: _JOINERS.sub("", match.group()), message)
    return _SPLIT.sub(lambda match: _JOINERS.sub("", match.group()), joined)


def emergency_readings(message: str) -> tuple[str, ...]:
    """The readings the emergency rules check: as written, and joined when that differs."""
    joined = unsplit(message)
    return (message,) if joined == message else (message, joined)
