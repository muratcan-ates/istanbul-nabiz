"""A question about a phone line is not a bus line question (A9, rt-37).

"İBB'nin 444 1 999 numaralı yardım hattı çalışıyor mu?" reached ``iett_line_buses``: the rule router reads
"999 numaralı" as a bus number. The answer invented nothing, but it answered a question nobody asked. This
module recognises a question about a telephone line, without a model, and gives the rules path an honest
reply: Nabız cannot test a phone line, the official lines it knows are named, and an unknown number is
said to be unknown rather than confirmed or denied.

The official lines are :data:`nabiz.agent.faithfulness.OFFICIAL_LINES`, the one list the numeric check
also allows; the names below are only those this repository already states (112 on the emergency card,
153 İBB Çözüm Merkezi, 187 İGDAŞ on the gas card).
"""

from __future__ import annotations

import re

from ibb_mcp.text import normalize_tr
from nabiz.agent.faithfulness import OFFICIAL_LINES

#: Names this repository already gives: ``emergency_text`` (112, 187) and ``policy.HANDOFF_TEXT`` (153).
LINE_NAMES = {"112": "acil çağrı hattı", "153": "İBB Çözüm Merkezi", "187": "İGDAŞ doğalgaz acil hattı"}
#: Words that make a number a telephone line: "yardım hattı", "numaralı hat çalışıyor mu", "telefon".
_PHONE_WORDS = re.compile(
    r"\b(?:yardim hatt|cagri merkez|cagri hatt|ihbar hatt|destek hatt|telefon|numarayi ara|numarasi|numarali yardim"
    r"|numarali cagri|numarali ihbar|numarali destek|hotline|helpline|phone number|call centre|call center|emergency number)"
)
#: "numaralı hat" alone is a bus ("500 numaralı hat") unless the number is written like a phone number.
_PHONE_NUMBER = re.compile(r"(?<!\d)(?:444\s?\d\s?\d{3}|0?\s?\(?[2-5]\d{2}\)?\s?\d{3}\s?\d{2}\s?\d{2}|1\d{2})(?!\d)")
#: A service named next to an official line's number: "İtfaiye 110 hattı", "polis 155".
_SERVICE = re.compile(r"\b(?:itfaiye|polis|jandarma|ambulans|acil|igdas|iski|alo)\b")
_OFFICIAL = re.compile(r"(?<!\d)(?:" + "|".join(OFFICIAL_LINES) + r")(?!\d)")
_TRANSPORT = re.compile(r"\b(?:otobus|metrobus|metro|tramvay|vapur|durak|sefer|bus|tram|ferry)\b")
_NUMBER = re.compile(r"(?<![\d\w])(\d[\d ]{1,12}\d|\d{3})(?![\d\w])")

NO_NUMBER = (
    "İBB'ye 153 İBB Çözüm Merkezi'nden ulaşabilirsin; Nabız bir telefon hattının çalışıp çalışmadığını "
    "denetleyemez. Acil bir durumda 112'yi ara."
)
UNKNOWN_LINE = (
    "Nabız bir telefon hattının çalışıp çalışmadığını denetleyemez ve bu numarayı kayıtlı kaynaklarında "
    "bulamadı; doğrulayamıyorum. İBB'ye 153 İBB Çözüm Merkezi'nden ulaşabilirsin. Acil bir durumda 112'yi ara."
)
KNOWN_LINE = (
    "{number}, {name}. Nabız bir telefon hattının şu an çalışıp çalışmadığını denetleyemez. "
    "İBB'ye 153 İBB Çözüm Merkezi'nden ulaşabilirsin. Acil bir durumda 112'yi ara."
)


def asks_about_a_phone_line(message: str) -> bool:
    """Is this a question about a telephone line rather than a bus, metro or ferry line?"""
    text = normalize_tr(message)
    if _TRANSPORT.search(text):
        return False
    if _SERVICE.search(text) and _OFFICIAL.search(text):
        return True
    return bool(_PHONE_WORDS.search(text)) and bool(_PHONE_NUMBER.search(text) or "numara" in text or "hatt" in text)


def phone_line_answer(message: str) -> str | None:
    """The rules path's reply to a telephone line question, or ``None`` when it is not one."""
    if not asks_about_a_phone_line(message):
        return None
    numbers = ["".join(match.split()) for match in _NUMBER.findall(normalize_tr(message))]
    known = next((number for number in numbers if number in OFFICIAL_LINES and number in LINE_NAMES), None)
    if not numbers:
        return NO_NUMBER
    if known is not None and len(numbers) == 1:
        return KNOWN_LINE.format(number=known, name=LINE_NAMES[known])
    if len(numbers) == 1 and numbers[0] in OFFICIAL_LINES:
        return NO_NUMBER  # an official line this repository gives no name for: no name is made up
    return UNKNOWN_LINE
