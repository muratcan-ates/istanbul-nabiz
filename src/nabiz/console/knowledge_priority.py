"""When the chat asks the service-page index first (KARAR 2, §7b-13 E78).

Two windows, one switch:

(a) **Today, the default.** The E78 path (``knowledge_turn``) answers only when the rules path came back
    with its fixed out-of-scope sentence: a question no tool covers ("Engelli kartına nasıl başvururum?")
    is looked up in İBB's service pages instead of being told Nabız cannot help.
(b) **Knowledge first, behind** ``NABIZ_KNOWLEDGE_MODEL_FIRST`` (off unless it reads 1, true, yes or on).
    A question that asks how a service works ("başvuru şartları", "hangi belgeler", "how do I apply") goes
    to the index before any tool; a live question ("M4 çalışıyor mu?", a car park, a bus) still goes to its
    tool first, because a service page never knows today's state.

Pure: the words below are the whole decision, no model, no index. ``chat.py`` asks
:func:`knowledge_window` where it compares with ``OUT_OF_SCOPE`` today, and :func:`knowledge_before_tools`
before the rules path runs; both wirings are the Integrator's (P00).
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

from ibb_mcp.text import normalize_tr

KNOWLEDGE_MODEL_FIRST_ENV = "NABIZ_KNOWLEDGE_MODEL_FIRST"
_ON = frozenset({"1", "true", "yes", "on"})
#: How a service works: application, conditions, documents, opening hours, what a thing is. Folded.
_SERVICE_QUESTION = re.compile(
    r"\b(?:nasil basvur|basvuru|basvurmak|sartlar|sartlari|kosullar|hangi belge|gerekli belge|belgeler|evrak"
    r"|nereden alinir|nasil alinir|nasil yapilir|ne ise yarar|nedir|calisma saat|acilis saat|kimler yararlan"
    r"|how do i apply|how to apply|requirements|which documents|what documents|opening hours|what is)"
)
#: A live state only a tool has: a line, a car park, an arrival, a disruption, the air today.
_LIVE_QUESTION = re.compile(
    r"\b(?:calisiyor mu|ariza|gecikme|kac dakika|ne zaman gelir|bos yer|otopark|doluluk|trafik|hava kalitesi"
    r"|seferler|m\d{1,2}[ab]?|t\d|\d{1,3}[a-z]{1,2}|is it running|delay|disruption|free spaces|arrival)\b"
)


def model_first(env: Mapping[str, str] | None = None) -> bool:
    """Is option (b) switched on?"""
    env = os.environ if env is None else env
    return (env.get(KNOWLEDGE_MODEL_FIRST_ENV) or "").strip().lower() in _ON


def knowledge_window(author: str, answer_text: str, out_of_scope: str | None) -> bool:
    """(a): the rules path answered with its fixed out-of-scope sentence, so the index may answer instead."""
    return author == "kural" and out_of_scope is not None and answer_text == out_of_scope


def asks_how_a_service_works(question: str) -> bool:
    """A procedure, condition or document question with no live state in it."""
    text = normalize_tr(question)
    return bool(_SERVICE_QUESTION.search(text)) and not _LIVE_QUESTION.search(text)


def knowledge_before_tools(question: str, env: Mapping[str, str] | None = None) -> bool:
    """(b): with the switch on, a question about how a service works goes to the index before any tool."""
    return model_first(env) and asks_how_a_service_works(question)
