"""Find claims that a model must not present as established fact.

1. Match each sentence separately, because an elevator mention must not make a later,
   unrelated service sentence look like a claim about that elevator.
2. Fold Turkish with the shared text keys, so spelling and keyboard variants have one rule.
3. Keep the term table here: callers receive rule keys, never the matched text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ibb_mcp.text import normalize_tr

__all__ = ["ForbiddenTerm", "FORBIDDEN_TERMS", "find_forbidden"]


@dataclass(frozen=True)
class ForbiddenTerm:
    """One claim family and the local context or negation that changes its meaning."""

    key: str
    phrases: tuple[str, ...] = ()
    raw_pattern: str | None = None
    context: tuple[str, ...] = ()
    negated_after: tuple[str, ...] = ()
    negated_before: tuple[str, ...] = ()


FORBIDDEN_TERMS: tuple[ForbiddenTerm, ...] = (
    ForbiddenTerm(
        key="ibb_onayli",
        phrases=(
            "ibb onayli", "ibb tarafindan onayl", "ibb onayiyla", "resmi ibb hizmeti",
            "resmi ibb uygulamasi", "ibb approved", "approved by ibb", "endorsed by ibb",
            "official ibb service",
        ),
        negated_after=("degil",),
        negated_before=("not",),
    ),
    ForbiddenTerm(
        key="calisiyor",
        phrases=(
            "calisiyor", "calisir durumda", "calisir vaziyette", "calismakta", "sorunsuz calis",
            "is working", "is operational", "works fine", "in service",
        ),
        context=("asansor", "yuruyen merdiven", "lift", "elevator", "escalator"),
        negated_after=("degil",),
    ),
    ForbiddenTerm(
        key="basvuru_olusturuldu",
        phrases=(
            "basvurunuz olusturul", "talebiniz olusturul", "kaydiniz olusturul",
            "bildiriminiz olusturul", "sikayetiniz olusturul",
            "basvurunuz alin", "talebiniz alin", "kaydiniz alin", "bildiriminiz alin", "sikayetiniz alin",
            "basvurunuz iletil", "talebiniz iletil", "kaydiniz iletil", "bildiriminiz iletil", "sikayetiniz iletil",
            "basvurunuz kaydedil", "talebiniz kaydedil", "kaydiniz kaydedil",
            "bildiriminiz kaydedil", "sikayetiniz kaydedil",
            "basvurunuzu olusturdum", "talebinizi olusturdum", "bildiriminizi olusturdum", "sikayetinizi olusturdum",
            "basvurunuzu ilettim", "talebinizi ilettim", "bildiriminizi ilettim", "sikayetinizi ilettim",
            "basvurunuzu aldim", "talebinizi aldim", "bildiriminizi aldim", "sikayetinizi aldim",
            "basvurunuzu kaydettim", "talebinizi kaydettim", "bildiriminizi kaydettim", "sikayetinizi kaydettim",
            *(
                f"your {noun} {auxiliary} {verb}"
                for noun in ("application", "request", "complaint", "report", "ticket")
                for auxiliary in ("has been", "was")
                for verb in ("created", "submitted", "filed", "received", "forwarded")
            ),
        ),
    ),
    ForbiddenTerm(
        key="onay_iddiasi",
        phrases=("basvurunuz onaylan", "talebiniz onaylan", "sikayetiniz onaylan", "basvurunuzu onayladim",
                 "onayladim", "kart onaylan", "your application has been approved",
                 "your request has been approved", "i have approved", "i approved your"),
        negated_after=("degil",),
        negated_before=("not",),
    ),
    ForbiddenTerm(
        key="uygunluk_hukmu",
        phrases=("hak kazandiniz", "hak kazanirsiniz", "hak kazanmissiniz", "uygunsunuz", "yararlanmaya hak",
                 "you are eligible", "you qualify", "you are entitled"),
    ),
    ForbiddenTerm(
        key="kvkk_uyumlu",
        phrases=(
            "kvkk uyumlu", "kvkk ile uyumlu", "kvkk ya uygun", "kvkk compliant",
            "gdpr compliant", "kvkk uyarinca guvende",
        ),
    ),
    ForbiddenTerm(key="eta", raw_pattern=r"\bETA\b"),
)

_SENTENCE_SPLIT = re.compile(r"[.!?\n;]+")


def _phrase_end(tokens: list[str], phrase: str) -> tuple[int, int] | None:
    """Return token bounds when a phrase's words and final word root match."""
    wanted = phrase.split()
    if not wanted or len(tokens) < len(wanted):
        return None
    last_start = len(tokens) - len(wanted)
    for start in range(last_start + 1):
        if tokens[start : start + len(wanted) - 1] != wanted[:-1]:
            continue
        if tokens[start + len(wanted) - 1].startswith(wanted[-1]):
            return start, start + len(wanted)
    return None


def _is_negated(tokens: list[str], start: int, end: int, term: ForbiddenTerm) -> bool:
    """Apply only the short, explicit negations in the term's rule."""
    after = tokens[end : end + 2]
    before = tokens[max(0, start - 2) : start]
    return any(token.startswith(root) for token in after for root in term.negated_after) or any(
        token.startswith(root) for token in before for root in term.negated_before
    )


def _sentence_has_term(sentence: str, term: ForbiddenTerm) -> bool:
    if term.raw_pattern and re.search(term.raw_pattern, sentence):
        return True
    folded = normalize_tr(sentence)
    tokens = folded.split()
    if term.context and not any(_phrase_end(tokens, root) for root in term.context):
        return False
    return any(
        (match := _phrase_end(tokens, phrase)) is not None and not _is_negated(tokens, *match, term)
        for phrase in term.phrases
    )


def find_forbidden(text: str) -> tuple[str, ...]:
    """Return matching rule keys in table order, once each, without retaining excerpts."""
    sentences = _SENTENCE_SPLIT.split(text)
    return tuple(
        term.key for term in FORBIDDEN_TERMS if any(_sentence_has_term(sentence, term) for sentence in sentences)
    )
