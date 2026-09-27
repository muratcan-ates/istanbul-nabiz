"""Small, deterministic checks around the citizen's question and model answer.

1. Remove format, tag, variation-selector and control characters before length or pattern
   checks, so invisible text cannot change what the server and counter see.
2. Refuse instruction changes before the length limit, because a short attack should not
   reach tools or a model just because it fits in the box.
3. Check only model-authored answers for unsupported links and claims; fixed rules and
   quoted source text keep their existing meaning.
4. Log a rule key only. Questions, matches, links and matched terms can contain private text.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from ibb_mcp.text import fold_tr, normalize_tr

from .forbidden_terms import find_forbidden

__all__ = [
    "MAX_QUESTION_CHARS", "WARN_FROM_CHARS", "MODEL_AUTHORS", "INJECTION_REFUSAL_TEXT", "GuardReason",
    "InputVerdict", "OutputVerdict", "strip_invisible", "too_long_text", "check_input", "check_output",
]

MAX_QUESTION_CHARS = 300
WARN_FROM_CHARS = 280
MODEL_AUTHORS = frozenset({"model", "yerel model"})
INJECTION_REFUSAL_TEXT = (
    "Bu isteği yerine getiremem. İstanbul hakkında şehir bilgisi veriyorum ve çalışma kurallarım sohbetle değişmez. "
    "Sorunu İstanbul'la ilgili tek bir soru olarak yazabilirsin; insanla konuşmak için 153'ü arayabilirsin."
)
GuardReason = Literal["too_long", "injection", "hidden_text", "unsourced_link", "forbidden_term"]

_LOG = logging.getLogger(__name__)
_TAG_START, _TAG_END = 0xE0000, 0xE007F
_VARIATION_START, _VARIATION_END = 0xE0100, 0xE01EF


@dataclass(frozen=True)
class InputVerdict:
    ok: bool
    text: str
    reason: GuardReason | None
    message: str | None
    length: int
    removed: int


@dataclass(frozen=True)
class OutputVerdict:
    ok: bool
    reason: GuardReason | None
    links: tuple[str, ...] = ()
    terms: tuple[str, ...] = ()


_RAW_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"^\s*(?:sistem\s+mesaj\w*|gizli\s+talimat\w*|system(?:\s+prompt|\s+message)?|admin|developer)\s*[:\]]",
        r"\[(?:admin|system|sistem|developer|inst|/inst)\]",
        r"<\|?(?:im_start|im_end|system|endoftext)\|?>",
        r"^\s*#{2,}\s*(?:system|instruction|talimat)\b",
        r"</?s\s*>",
        r"^\s*(?:assistant|asistan|user)\s*:\s*.{0,60}\b(?:kural|talimat|bundan\s+sonra)",
    )
)

_FOLDED_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\b(?:onceki|yukaridaki|tum|butun|verilen|eski)\b.{0,32}\b(?:talimat\w*|yonerge\w*|kural\w*|komut\w*|kaynak\w*)\b.{0,36}\b(?:unut(?:un|arak)?|yok\s+say|gormezden\s+gel|iptal\s+et|gecersiz|bosver|dikkate\s+alma)",
        r"\b(?:talimat\w*|yonerge\w*|kural\w*|kaynak\w*|sources?)\b\s+(?:bolumunu\s+)?(?:gormezden\s+gel|yok\s+say|iptal\s+et)",
        r"\bkural(?:lar)?\s+(?:guncellendi|degisti|kaldirildi)",
        r"\bkaynak\s+(?:sarti|kontrolu|zorunlulugu|denetimi)\s+(?:yok|kaldirildi|devre\s+disi|kapali|kapatildi)",
        r"\b(?:filtre|guvenlik|kisit|sinir)\w*\s+(?:kapat\w*|devre\s+disi|kaldir\w*)",
        r"\b(?:sistem|gizli|ic)\s+(?:mesaj|talimat|istem|prompt|komut)\w*\s+(?:goster\w*|yaz\w*|soyle\w*|paylas\w*|tekrarla\w*|dok\w*)",
        r"\bpromptunu\s+(?:goster\w*|yaz\w*|paylas\w*)",
        r"\bilk\s+mesajini\s+tekrarla\w*",
        r"\b(?:sistem|gizli|ic)\s+(?:istem|talimat|prompt)\w*.{0,36}\b(?:ver\w*|cevir\w*|aktar\w*)",
        r"\b(?:ver\w*|cevir\w*|aktar\w*)\b.{0,28}\b(?:sistem|gizli|ic)\s+(?:istem|talimat|prompt)\w*",
        r"\b(?:ilk|onceki)\s+(?:yazdigin\s+)?mesaj\w*.{0,48}\btekrar\s+et\b",
        r"\byazdigin\s+(?:ilk|onceki)\s+mesaj\w*.{0,48}\btekrar\w*",
        r"\basistan\b.{0,40}\b(?:bundan\s+sonra|artik|kural)\b",
        r"\b(?:sen\s+)?artik\s+(?:bir\s+)?(?:ibb\s+)?(?:gorevli|memur|yetkili|operator|admin|yonetici)\w*\b",
        r"\bgibi\s+davran\b|\brolune\s+gir\b|\brolunu\s+oyna\b|\bkuralsiz\s+mod\w*|\bsinirsiz\s+mod\w*|\bgelistirici\s+mod\w*",
        r"\b(?:ignore|disregard|forget|override|bypass)\b.{0,30}\b(?:previous|prior|above|earlier|all|your|system|the)\b.{0,20}\b(?:instructions?|prompts?|rules?|messages?|directions?)\b",
        r"\b(?:reveal|show|print|repeat|tell\s+me|output)\b.{0,20}\b(?:system\s+(?:prompt|message)|your\s+(?:instructions|prompt|rules)|hidden\s+(?:prompt|instructions)|initial\s+prompt)\b",
        r"\bwhat\s+are\s+your\s+(?:instructions?|rules?|system\s+prompt)\b",
        r"\btranslate\s+your\s+(?:system\s+prompt|instructions?)\b",
        r"\bfrom\s+now\s+on\s+you\s+are\b",
        r"\byou\s+are\s+now\s+(?:an?\s+)?(?:ibb\s+)?(?:officer|official|operator|admin)\b",
        r"\byou\s+are\s+now\b|\b(?:act|behave)\s+as\s+(?:an?\s+)?(?:unrestricted|different|dan|developer|jailbroken)\b",
        r"\bpretend\s+(?:to\s+be|you\s+are)\b|\bdeveloper\s+mode\b|\bjailbreak\b|\bdo\s+anything\s+now\b",
        r"\bno\s+(?:rules|restrictions|filters)\s+(?:mode|apply)\b",
    )
)


def strip_invisible(text: str) -> tuple[str, int]:
    """Drop non-visible format classes without normalization, keeping Python/JS counts aligned."""
    kept: list[str] = []
    removed = 0
    for char in text:
        point = ord(char)
        category = unicodedata.category(char)
        invisible = (
            category == "Cf"
            or _VARIATION_START <= point <= _VARIATION_END
            or (category == "Cc" and char not in "\t\n\r")
        )
        if invisible:
            removed += 1
        else:
            kept.append(char)
    return "".join(kept), removed


def too_long_text(length: int) -> str:
    """Ask for one shorter question and give the established human contact route."""
    return (
        f"Sorun {length} karakter; en fazla 300 karakter alabiliyorum. Lütfen tek bir soru olarak kısaltıp yeniden yaz. "
        "İnsanla konuşmak için 153'ü arayabilirsin."
    )


def _raw_hit(text: str) -> bool:
    folded = fold_tr(text)
    return any(pattern.search(folded) for pattern in _RAW_PATTERNS)


def _folded_hit(text: str) -> bool:
    folded = normalize_tr(text)
    return any(pattern.search(folded) for pattern in _FOLDED_PATTERNS)


def _blocked(text: str, reason: GuardReason, message: str) -> InputVerdict:
    _LOG.info("input guard: %s", reason)
    return InputVerdict(False, text, reason, message, len(text), 0)


def check_input(text: str) -> InputVerdict:
    """Sanitize and classify a question before the emergency path, model or tools see it."""
    has_tags = any(_TAG_START <= ord(char) <= _TAG_END for char in text)
    clean, removed = strip_invisible(text)
    length = len(clean)
    if has_tags:
        verdict = InputVerdict(False, clean, "hidden_text", INJECTION_REFUSAL_TEXT, length, removed)
    elif _raw_hit(clean) or _folded_hit(clean):
        verdict = InputVerdict(False, clean, "injection", INJECTION_REFUSAL_TEXT, length, removed)
    elif length > MAX_QUESTION_CHARS:
        verdict = InputVerdict(False, clean, "too_long", too_long_text(length), length, removed)
    else:
        return InputVerdict(True, clean, None, None, length, removed)
    _LOG.info("input guard: %s", verdict.reason)
    return verdict


_LINK_RE = re.compile(
    r"\[[^\]]*\]\(\s*(?P<markdown><[^>]+>|[^\s)]+)\s*\)"
    r"|(?P<web>(?<![\w@])(?:https?|ftp)://[^\s<>\[\]{}\"']+)"
    r"|(?P<www>(?<![\w@])www\.(?:[a-z0-9-]+\.)+[a-z]{2,}(?::\d+)?(?:/[^\s<>\[\]{}\"']*)?)"
    r"|(?P<special>(?<![\w])(?:mailto|sms|javascript|data|tel):[^\s<>\[\]{}\"']+)"
    r"|(?P<bare>(?<![\w@])(?:[a-z0-9-]+\.)+(?:com|net|org|tr|istanbul|gov|edu|io|app|info|me|co)\b(?::\d+)?(?:/[^\s<>\[\]{}\"']*)?)",
    re.IGNORECASE,
)
_LINK_END = ".,;:!?)]}'\"»"


def _extract_links(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in _LINK_RE.finditer(text):
        value = match.group("markdown") if match.group("markdown") is not None else match.group(0)
        if match.group("markdown") is not None:
            value = value.strip("<>")
        value = value.rstrip(_LINK_END)
        if value:
            found.append(value)
    return tuple(found)


def _source_strings(sources_used: Iterable[Any]) -> list[str]:
    if isinstance(sources_used, (dict, list, tuple, str)):
        stack: list[tuple[Any, int]] = [(sources_used, 0)]
    else:
        stack = [(item, 0) for item in sources_used]
    strings: list[str] = []
    while stack and len(strings) < 2000:
        value, depth = stack.pop()
        if isinstance(value, str):
            strings.append(value)
        elif depth < 6 and isinstance(value, dict):
            stack.extend((item, depth + 1) for item in value.values())
        elif depth < 6 and isinstance(value, (list, tuple)):
            stack.extend((item, depth + 1) for item in value)
    return strings


def _normalize_link(link: str) -> str:
    normalized = link.split("#", 1)[0].lower()
    normalized = re.sub(r"^(?:https?|ftp)://", "", normalized)
    normalized = re.sub(r"^www\.", "", normalized)
    return normalized.rstrip("/")


def _unsourced_links(answer_links: tuple[str, ...], sources_used: Iterable[Any]) -> tuple[str, ...]:
    source_links = {_normalize_link(link) for value in _source_strings(sources_used) for link in _extract_links(value)}
    unsourced: list[str] = []
    for link in answer_links:
        normalized = _normalize_link(link)
        if normalized in {"tel:112", "tel:153"}:
            continue
        if not any(normalized == source or source.startswith(normalized + "/") for source in source_links):
            unsourced.append(link)
    return tuple(unsourced)


def check_output(answer: str, sources_used: Iterable[Any], *, author: str) -> OutputVerdict:
    """Check model answers against citation URLs and unsupported claim rules."""
    if author not in MODEL_AUTHORS:
        return OutputVerdict(True, None)
    links = _unsourced_links(_extract_links(answer), sources_used)
    terms = find_forbidden(answer)
    if links:
        verdict = OutputVerdict(False, "unsourced_link", links, terms)
    elif terms:
        verdict = OutputVerdict(False, "forbidden_term", (), terms)
    else:
        return OutputVerdict(True, None)
    _LOG.info("output guard: %s", verdict.reason)
    return verdict
