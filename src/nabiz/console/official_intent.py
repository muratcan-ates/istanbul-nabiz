"""Pure intent and topic matching for reviewed official-path cards."""

from __future__ import annotations

from typing import Literal

from ibb_mcp.text import normalize_tr
from nabiz.console.agency_router import agency_for

Intent = Literal["account", "help", "ferry"]

_PERSONAL_PREFIXES = (
    "faturam", "faturalarim", "borcum", "borclarim", "aboneligim", "aboneliklerim", "sayacim",
    "bakiyem", "hesabim", "basvurum", "randevum", "kartim",
)
_ACCOUNT_WORDS = (
    "fatura", "borc", "abonelik", "sayac", "bakiye", "hesap", "basvuru", "randevu",
    "bill", "bills", "account", "accounts", "subscription", "subscriptions", "balance", "debt",
    "meter", "application", "appointment", "card",
)
_ACCOUNT_ACTIONS = (
    "kontrol et", "sorgula", "listele", "goster", "ode", "iptal et", "onayla", "randevu al", "istiyorum",
    "check", "list", "show", "pay", "cancel", "approve", "book", "i want to",
)
_HOW_WHERE = ("nasil", "nereden", "nerede", "nereye", "hangi kanal", "how", "where")
_OUTSIDE_IBB = (
    "elektrik", "telefon", "gsm", "internet", "banka", "kredi", "vergi", "sigorta", "e devlet",
    "electricity", "phone", "bank", "credit", "tax",
)
_HELP_WORDS = ("yardim", "destek", "sosyal hizmet", "burs", "help", "support", "benefit", "aid", "assistance")
_HELP_ELIGIBILITY = (
    "alabilir miyim", "alabilirim", "yararlanabilir miyim", "yararlanabilirim", "basvurabilir miyim", "bana uygun",
    "can i get", "am i eligible", "which benefits",
)
_TRANSPORT_CONTEXT = ("istasyon", "durak", "hat", "metro", "otobus", "vapur", "asansor", "otopark", "sefer")
_FERRY_WORDS = ("vapur", "feribot", "sehir hatlari", "ferry", "ferries")
_FERRY_TIME_PREFIXES = ("saat", "sefer", "kacta", "tarife", "timetable", "schedule", "departure")
_FERRY_TIME_PHRASES = ("ilk vapur", "son vapur", "ne zaman kalk", "what time")
_OTHER_TOPICS = ("otopark", "metro", "otobus", "hava", "trafik")
_ACTION_TOPICS = (
    "abonelik", "iptal", "fatura", "borc", "sayac", "randevu", "basvuru", "vize", "kart", "bakiye",
    "kesinti", "odeme", "takip", "sefer",
)
_TOPIC_PREFIXES = (
    ("iptal", ("iptal",)),
    ("vize", ("vize",)),
    ("kesinti", ("kesinti",)),
    ("randevu", ("randevu",)),
    ("fatura", ("fatura",)),
    ("borc", ("borc",)),
    ("sayac", ("sayac",)),
    ("basvuru", ("basvuru",)),
    ("takip", ("takip",)),
    ("odeme", ("odeme",)),
    ("abonelik", ("abonelik",)),
    ("bakiye", ("bakiye",)),
    ("kart", ("kart",)),
    ("sefer", ("sefer",)),
)
_ALLOWED_ACCOUNT_AGENCIES = frozenset({"iski", "igdas", "istanbulkart", "ispark", "cozum_153", "ibb", "sehir_hatlari"})


def _has_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    padded = f" {text} "
    return any(f" {phrase} " in padded for phrase in phrases)


def _has_prefix(words: list[str], prefixes: tuple[str, ...]) -> bool:
    return any(word.startswith(prefix) for word in words for prefix in prefixes)


def _personal_account(words: list[str]) -> bool:
    if _has_prefix(words, _PERSONAL_PREFIXES):
        return True
    if "benim" in words and any(
        word.startswith(_ACCOUNT_WORDS[:8]) for word in words[words.index("benim") + 1 :]
    ):
        return True
    return "my" in words and any(word in _ACCOUNT_WORDS[8:] for word in words[words.index("my") + 1 :])


def _account_request(text: str, words: list[str]) -> bool:
    account_name = _has_prefix(words, _ACCOUNT_WORDS)
    personal = _personal_account(words)
    if not personal and not (account_name and _has_phrase(text, _ACCOUNT_ACTIONS)):
        return False
    if _has_prefix(words, ("bildirim",)) or _has_phrase(text, _HOW_WHERE):
        return False
    if _has_prefix(words, tuple(item for item in _OUTSIDE_IBB if " " not in item)) or _has_phrase(
        text, tuple(item for item in _OUTSIDE_IBB if " " in item)
    ):
        return False
    agency = agency_for(text)
    return agency in _ALLOWED_ACCOUNT_AGENCIES or agency is None


def _eligible_help(text: str, words: list[str]) -> bool:
    has_help = _has_prefix(words, _HELP_WORDS)
    if not has_help or "askida" in words or _has_phrase(text, _TRANSPORT_CONTEXT):
        return False
    if any(
        word == "hangi" and _has_prefix(words[index + 1 : index + 4], _HELP_WORDS)
        for index, word in enumerate(words)
    ):
        return True
    if _has_phrase(text, _HELP_ELIGIBILITY):
        return True
    return "what" in words and "can" in words and "i" in words and "get" in words


def _ferry_request(text: str, words: list[str]) -> bool:
    if _has_prefix(words, ("ido",)) or _has_phrase(text, ("deniz otobus",)):
        return False
    if _has_phrase(text, _OTHER_TOPICS):
        return False
    has_ferry = _has_prefix(words, ("vapur", "feribot", "ferry", "ferries")) or _has_phrase(text, ("sehir hatlari",))
    return has_ferry and (
        _has_prefix(words, _FERRY_TIME_PREFIXES) or _has_phrase(text, _FERRY_TIME_PHRASES)
    )


def intent(message: str) -> Intent | None:
    """Classify a citizen turn without file, network, model, or database access."""
    text = normalize_tr(message)
    words = text.split()
    if _account_request(text, words):
        return "account"
    if _eligible_help(text, words):
        return "help"
    if _ferry_request(text, words):
        return "ferry"
    return None


def agency_and_topic(question: str) -> tuple[str | None, str | None]:
    """Return the institution and the most specific operation named in a question."""
    text = normalize_tr(question)
    words = text.split()
    agency = agency_for(text)
    if agency is None and "kredi karti" not in f" {text} ":
        card_terms = ("kart", "karti", "kartim", "kartini", "card")
        student_terms = ("ogrenci", "vize", "abonman", "bakiye", "kayip", "kayb", "student")
        if _has_prefix(words, card_terms) and _has_prefix(words, student_terms):
            agency = "istanbulkart"
    if agency is None and _has_prefix(words, ("ferry", "ferries")):
        agency = "sehir_hatlari"
    topic = next((topic for topic, prefixes in _TOPIC_PREFIXES if _has_prefix(words, prefixes)), None)
    return agency, topic


def help_topic(question: str) -> str | None:
    """Name a requested help group; an unspecified eligible help question means social support."""
    text = normalize_tr(question)
    words = text.split()
    if not _eligible_help(text, words):
        return None
    if _has_prefix(words, ("engelli", "disability", "disabled")):
        return "engelli"
    if _has_prefix(words, ("yasli", "yaşli", "elderly", "older")):
        return "yasli"
    if _has_prefix(words, ("ogrenci", "student")) and not _has_prefix(words, ("kart", "karti", "card")):
        return "ogrenci"
    return "sosyal_destek"
