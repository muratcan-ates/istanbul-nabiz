"""Health details out of a citizen's request before it is stored or shown to an operator (KVKK special data).

A request to a person ("Operatöre aktar", :mod:`nabiz.console.requests_api`) may carry a diagnosis the
operator does not need: "Diyabetim var, sokağımızdaki rampa kırık". A health condition is special category
personal data (KVKK art. 6) and the P02 rule is that a health statement is added to no request, operator or
calendar. :func:`mask_request` replaces each health phrase with :data:`HEALTH_LABEL` and then applies the
identity mask (:func:`nabiz.console.pii_guard.mask_labels`), so the queue, the translation, the category and
the ledger only ever see the masked text. The raw text is never stored.

**What stays.** A functional need is what the operator needs to do the job and is not a diagnosis:
"tekerlekli sandalye kullanıyorum", "adımsız erişim", "görme engelliyim" are left as written. Place names
are left too: "Kalp Damar Hastanesi'ne otobüs" is a destination, not a condition, because ``kalp`` alone
is never a term here, only ``kalp hastası`` and ``kalp hastalığı``. ``şeker`` alone (a sweet) is not a
term either, only ``şeker hastası`` / ``şeker hastalığı``.

**How it matches.** Each term is folded with the same length-preserving fold as the identity mask
(:func:`~nabiz.console.pii_guard.fold_keep_length`), so offsets address the original text. A stem may take
any suffix ("Diyabetim", "diyabetli", "diyalize", "Diyaliz'e"); a whole word may not ("rak" is not "рак").
A following ``var``/``hastasıyım`` style predicate is swallowed with the term, so the sentence reads
"[sağlık bilgisi gizlendi], sokağımızdaki rampa kırık". Turkish, English, German, Arabic and Russian.
"""

from __future__ import annotations

import re

from nabiz.console.pii_guard import fold_keep_length, mask_labels

HEALTH_LABEL = "[sağlık bilgisi gizlendi]"
#: The label inside a request that is not Turkish. The Turkish label's "ğ" and "ı" would make the request
#: read as Turkish to :func:`~nabiz.console.translate.guess_request_language`, and a German request would then
#: reach the operator untranslated; the operator's Turkish text is the model's translation of this one.
HEALTH_LABEL_OTHER = "[health information hidden]"
HEALTH_KIND = "SAĞLIK"
#: The line the citizen reads before sending (KARAR 4); the page shows it from its i18n files.
CITIZEN_NOTE = "Sağlık bilginiz operatöre gösterilmez."

#: ``stem*`` takes any suffix; a bare entry is a whole word or phrase.
_TERMS: dict[str, tuple[str, ...]] = {
    "tr": (
        "diyabet*", "şeker hastası*", "şeker hastalığı*", "şeker hastasıyım", "kalp hastası*", "kalp hastalığı*",
        "kalp yetmezliği*", "diyaliz*", "böbrek yetmezliği*", "böbrek hastası*", "kanser*", "kemoterapi*",
        "epilepsi*", "sara hastası*", "hiv", "aids", "hamile*", "gebeyim", "gebelik*", "insülin*", "depresyon*", "antidepresan*",
        "ilaç kullanıyorum", "ilaç kullanıyor*", "ilaçlarımı", "tansiyon hastası*", "astım*", "alzheimer*",
        "parkinson*", "şizofreni*", "bipolar*", "ms hastası*", "koah*", "hepatit*", "lösemi*", "tümör*",
    ),
    "en": (
        "diabetes", "diabetic*", "heart disease", "heart condition", "heart failure", "dialysis", "cancer*",
        "chemotherapy", "epilepsy", "epileptic", "pregnant", "pregnancy", "insulin", "depression", "depressed",
        "antidepressant*", "on medication", "i take medication", "my medication", "asthma*", "hepatitis",
        "leukemia", "leukaemia", "tumour*", "tumor*", "schizophreni*", "bipolar", "alzheimer*", "parkinson*",
    ),
    "de": (
        "diabetes", "diabetiker*", "zuckerkrank*", "herzkrank*", "herzerkrankung*", "dialyse*", "krebs*",
        "chemotherapie*", "epilepsie*", "epileptiker*", "schwanger*", "insulin*", "depression*", "depressiv*",
        "medikamente*", "asthma*", "nierenversagen", "niereninsuffizienz",
    ),
    "ar": ("السكري", "سكري", "مرض القلب", "امراض القلب", "غسيل الكلى", "غسيل كلوي", "سرطان", "الصرع", "صرع",
           "انا حامل", "حامل في", "انسولين", "إنسولين", "اكتئاب", "الاكتئاب", "فيروس نقص المناعة", "العلاج الكيميائي"),
    "ru": (
        "диабет*", "сахарный диабет", "сердечн* заболевани*", "болезнь сердца", "диализ*", "рак", "раком",
        "онколог*", "химиотерап*", "эпилепси*", "беременн*", "инсулин*", "депресси*", "вич", "спид", "астм*",
        "лекарства", "принимаю лекарства",
    ),
}  # fmt: skip
#: A predicate that belongs to the statement, swallowed with it: "Diyabetim var", "kalp hastasıyım".
_TAIL = r"(?:\s+(?:var(?:dir)?|hastas\w*|oldu\w*))?"
_WORD_EDGE = r"(?<!\w)"
_WORD_END = r"(?!\w)"
_APOSTROPHE = r"(?:['’]\w+)?"
_ARABIC_CLITICS = "(?:وال|بال|ال|و|ب|ل)?"
_ARABIC_FIRST, _ARABIC_LAST = "\u0600", "\u06ff"


def _term(term: str) -> str:
    """One term as a pattern over folded text; ``*`` is "any suffix", a space is any run of spaces."""
    parts = []
    for word in term.split():
        stem = word.endswith("*")
        folded = re.escape(fold_keep_length(word.rstrip("*")))
        parts.append(folded + (r"\w*" if stem else "") + _APOSTROPHE)
    # Arabic attaches clitics (و، ب، ال) to the word; those are allowed, any other letter before the term is
    # not ("عسكري", military, is not "سكري").
    arabic = any(_ARABIC_FIRST <= ch <= _ARABIC_LAST for ch in term)
    left = _WORD_EDGE + (_ARABIC_CLITICS if arabic else "")
    return left + r"\s+".join(parts) + _WORD_END


_PATTERN = re.compile(
    "(?:" + "|".join(_term(term) for terms in _TERMS.values() for term in sorted(terms, key=len, reverse=True)) + ")" + _TAIL
)


def health_spans(text: str) -> list[tuple[int, int]]:
    """Offsets of the health phrases in ``text``; the matched words are never returned or kept."""
    folded = fold_keep_length(text)
    return [match.span() for match in _PATTERN.finditer(folded)]


def _label_for(text: str) -> str:
    """The Turkish label unless the request reads as another Latin-script language (another script decides
    the guess by itself, so the Turkish label cannot change it there)."""
    # Imported here: policy imports this module for the emergency rules and must not load the model client.
    from nabiz.console.translate import guess_request_language

    lang, source = guess_request_language(text, None)
    return HEALTH_LABEL if lang == "tr" or source == "alfabe" else HEALTH_LABEL_OTHER


def mask_health(text: str) -> tuple[str, int]:
    """``text`` with every health phrase replaced by :data:`HEALTH_LABEL`, and how many were replaced."""
    spans = health_spans(text)
    if not spans:
        return text, 0
    label = _label_for(text)
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.extend((text[cursor:start], label))
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts), len(spans)


def mask_request(text: str) -> tuple[str, int, tuple[str, ...]]:
    """The request mask: health first, then identity numbers; the same shape as :func:`mask_labels`."""
    without_health, health = mask_health(text)
    masked, count, kinds = mask_labels(without_health)
    if not health:
        return masked, count, kinds
    return masked, count + health, (HEALTH_KIND, *kinds)
