"""What the chat will not answer, what it passes on about the person, and what it offers to remember.

Four rules, all decided before any model is asked, all deterministic:

**Refusal (plan rule R-06).** A question about rights, fares, fines or health gets no
generated answer, from a model or a template: a wrong fare or a wrong entitlement costs the
person money or a right, and a wrong health line costs more. The answer points to 153 (İBB's
call centre) and the relevant institution's official page, and to 112 in an emergency. No
official URL is printed because none has been verified for this repository yet. Three lines
hold it: this keyword test (Turkish and English, the way riders actually ask: "bedava mı",
"akbil parası", "hastasıyım", "How much is a ticket?"), a short follow-up to a refused
question ("Peki öğrenciler için ne kadar?"), and the model's own prompt
(``system_prompt.md`` §4a). A last filter drops a model answer that names a price
(:func:`names_a_price`) unless the person asked about car parks, whose tariff is İSPARK's
own data.

**An emergency comes first** (:func:`emergency_intent`): the page shows 112 before any model,
tool or refusal. "acil" and "düştü" count only with company ("acil yardım", "annem düştü"); a gas
leak or smell ("gaz kaçağı", "doğalgaz kokusu") counts alone. After the Turkish rules come the fixed
rules of the other card languages (:mod:`~nabiz.console.emergency_lang`, DECISIONS #37): "помогите,
пожар" stops the chat the same way, and :func:`emergency_card` names the language the card speaks.

**Needs are functional constraints, nothing else.** The page may send a few profile keys
("step_free", "stroller" …). Only the keys in :data:`NEEDS` pass, as one line of constraint
each in the system prompt; free text, identities and diagnoses do not. The profile itself
stays in the browser, and nothing here logs what was sent.

**Memory is offered, never taken.** When the person has asked for the same need in two of
their own messages and the profile does not hold it yet, the answer carries a
``memory_suggestion``. The page asks; only the person's yes writes it, in the browser.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

from ibb_mcp.text import normalize_tr
from nabiz.console import emergency_lang

#: Profile keys the server accepts, with the constraint each becomes for the model.
NEEDS: dict[str, str] = {
    "step_free": (
        "Adımsız erişim gerekiyor: merdivensiz yolu, asansörü ya da rampayı öner; merdivenli yolu önerme. "
        "Bir asansörün çalıştığını söyleme; en fazla 'İBB kaydında arıza yok' de."
    ),
    "stroller": "Bebek arabasıyla yolculuk: merdivensiz ve geniş geçişli yolu tercih et.",
    "slow_walk": (
        "Yavaş yürüyor: kısa yürüme mesafesini ve az aktarmayı tercih et; `plan_journey` çağırırken "
        "`slow_walk=true` ver ve en az aktarmalı seçeneği öne al."
    ),
    "low_vision": "Az görüyor: kısa, sıralı ve net cümleler kur; bilgiyi yalnız renge bağlama.",
    "hearing": "İşitme kısıtı var: sesli anonsa dayanan bilgi yerine yazılı bilgi ver.",
    "plain_language": (
        "Sade dil: en fazla 2 cümle, tek sayı, tek eylem; liste ve teknik terim yok; hat kodunu "
        "'M4 metrosu', '500T otobüsü' diye yaz."
    ),
    "answer_en": (
        "Cevap dilini İngilizce ver; arayüz Türkçe kalır, kullanıcı Türkçe sorsa bile bu cümle işaretliyse "
        "cevap İngilizce olur."
    ),
}

#: What the page shows when it offers to remember a need.
NEED_LABELS: dict[str, str] = {
    "step_free": "Adımsız erişim (asansör, rampa)",
    "stroller": "Bebek arabası",
    "slow_walk": "Yavaş yürüyüş",
}

#: Folded phrases that express a need in the person's own words. Only these three are ever
#: suggested: they describe a route, not a person.
_NEED_PHRASES: dict[str, tuple[str, ...]] = {
    "step_free": ("asansor", "merdivensiz", "adimsiz", "rampa", "tekerlekli sandalye"),
    "stroller": ("bebek arabasi", "puset"),
    "slow_walk": ("yavas yuru", "az yuru", "yurumekte zorlan"),
}

#: How many of the person's own messages must ask for a need before it is offered.
MEMORY_REPEAT_THRESHOLD = 2

# -- refusal vocabulary, over normalize_tr-folded text ------------------------------------
#: Whole words. "hak" stays whole: its prefix would catch "hakkında" ("about").
_REFUSE_WORDS = frozenset(
    {
        "hak", "hakki", "hakkim", "hakkimiz", "hakkimi", "hakkina", "haklar", "haklari", "haklarim",
        "haklarimiz", "haklarimi", "lira", "tl", "yasal", "yasa", "alerji", "alerjim", "abonman", "vize",
        "para", "parasi", "parasini", "parali", "parasiz", "paraya", "kalp", "koah",
        "nakit", "kira", "kirayi", "kirami", "kiraci", "zam", "zammi", "cash", "landlord",
        # English, for the tourist persona
        "fare", "fares", "ticket", "tickets", "price", "prices", "cost", "costs", "fine", "fines", "fined",
        "discount", "discounts", "penalty", "penalties", "rights", "entitled", "asthma", "pregnant", "medicine",
    }
)  # fmt: skip
#: Word prefixes, for Turkish case endings ("cezası", "ücretsiz", "ilacımı", "hastasıyım").
_REFUSE_PREFIXES = (
    "ucret", "fiyat", "indirim", "tazminat", "ceza", "saglig", "hastalik", "hastalig", "ilac",
    "doktor", "hekim", "tedavi", "teshis", "mevzuat", "kanun", "yonetmelik", "bedava", "bedel",
    "kurus", "refakat", "bilet", "astim", "hamile", "gebe", "health", "bahsis", "iade",
)  # fmt: skip
#: "hasta..." is a person's health ("hastasıyım"); "hastane..." is a place to travel to.
_ILL, _HOSPITAL = "hasta", "hastane"
#: Phrases, for the questions whose words are innocent alone.
_REFUSE_PHRASES = (
    "kac para", "ne kadar tutar", "zararli mi", "zarar ver", "maske tak", "saglik", "engelli kart",
    "how much is", "for free", "free ride", "free of charge", "is it free", "disability card",
    "free for", "the rent", "raise the rent", "rent increase", "tip the", "tipping", "kredi karti gec",
)  # fmt: skip

# G14 uses these terms to select quote-only answers. They do not change refusal behavior.
SENSITIVE_TOPIC_TERMS: dict[str, list[str]] = {
    "hak": ["hak", "hakkı", "right", "entitlement"],
    "ucret": ["ücret", "fiyat", "tarife", "bedel", "zam", "fee", "price", "tariff", "charge", "increase"],
    "ceza": ["ceza", "yaptırım", "gecikme", "penalty", "fine", "sanction", "late"],
    "saglik": ["sağlık", "tedavi", "health", "treatment"],
    "indirim": ["indirim", "muafiyet", "discount", "exemption"],
    "basvuru": ["başvuru şartı", "uygunluk", "zorunlu", "eligibility", "requirement", "mandatory"],
}
#: Travel questions that name a health place: "sağlık ocağına nasıl giderim" is a route.
_TRAVEL_TO_HEALTH = ("saglik ocag", "saglik merkez", "hastane")
#: "ne kadar" asks a price when it is about a ticket, a card or a transfer, and a duration or a
#: distance otherwise ("ne kadar sürer", "veri ne kadar güncel").
_FARE_OBJECTS = ("kart", "bilet", "abonman", "aktarma", "binis", "akbil", "istanbulkart")
_NOT_A_PRICE = ("sur", "uzak", "guncel", "dakika", "zaman", "bekle", "yogun", "dolu")
#: A short question that leans on the one before it ("Peki öğrenciler için ne kadar?").
_FOLLOW_UP = ("ne kadar", "kac", "peki", "ya ", "onlar", "bunun", "bunlar", "o zaman", "what about", "how about")
_PRICE = re.compile(r"₺|\b\d+(?:[.,]\d+)?\s*(?:tl|lira)\b", re.IGNORECASE)

# -- emergency vocabulary, over normalize_tr-folded text ----------------------------------
# An emergency bypasses the model, the tools and the refusal rule: the page shows 112 at once.
# A missed emergency costs more than a false alarm, but "acil" and "düştü" alone are everyday
# words ("acil durum toplanma alanı", "fiyat düştü"), so those two count only with company.
#: Word stems, matched at a word's start (the first vocabulary; "polis merkezi" still redirects). English
#: ("fire", "ambulance") moved to emergency_lang with its masks: "fire sale at the bazaar" is not a fire.
EMERGENCY_TERMS = {"acil": ("yangin", "ambulans", "polis", "siddet", "kalp", "bayildi")}
#: Whole words: "kaza" must not catch "kazan dairesi".
_EMERGENCY_WORDS = ("kaza", "kazasi", "yarali", "yaralilar", "kanama", "kalp krizi", "intihar", "saldiri")
#: Verb stems from a word boundary, so the person endings pass ("boğuluyorum", "yaralandık").
#: A gas leak or smell is an emergency on its own, with no person in the sentence: "gaz kaçağı var".
#: "doğalgaz" is one word, so its phrases are listed apart; "gaz faturası" and "doğalgaz aboneliği"
#: match none of these.
_EMERGENCY_STEMS = (
    "yaraland", "kaniyor", "nefes alamiyor", "boguluyor", "bilincini kaybet",
    "gaz kacag", "gaz kaciyor", "gaz koku", "gaz sizinti",
    "dogalgaz kacag", "dogalgaz kaciyor", "dogalgaz koku", "dogalgaz sizinti",
)  # fmt: skip
_EMERGENCY_RE = re.compile(r"\b(?:" + "|".join(_EMERGENCY_WORDS) + r")\b|\b(?:" + "|".join(_EMERGENCY_STEMS) + ")")
#: The gas phrases among the stems: the emergency card then also names İGDAŞ's gas emergency line.
_GAS_RE = re.compile(r"\b(?:" + "|".join(stem for stem in _EMERGENCY_STEMS if "gaz " in stem) + ")")
#: "acil" is an emergency only next to one of these ("acil yardım", "acil, biri düştü").
_URGENT = re.compile(r"\bacil\b")
_URGENT_COMPANY = re.compile(r"\b(?:yardim|ambulans|dustu|kaza\b|kazasi\b|yarali|doktor|hastane)")
#: "düştü" is an emergency only when a person fell ("annem düştü") or cannot get up.
_FELL = re.compile(r"\b(?:dustu|dustum|dusmus)\b")
_FALLEN_PERSON = re.compile(
    r"\b(?:biri|birisi|annem|babam|dedem|ninem|anneannem|babaannem|cocuk|cocugum|yasli|adam|kadin|teyze|amca"
    r"|esim|kardesim|arkadasim|oglum|kizim|bebegim|yolcu|raya|raylara)\b|\bkalkamiyor"
)

# -- a request for a person, the same phrases as js/handoff.js (PERSON_PHRASES, CONNECT_153) ----------
#: A test holds the two lists equal. "kişi" and "temsilci" count only in the forms listed, so "bir
#: insanın hakkı" or "muhtar temsilcisi" is not a request for a person.
PERSON_PHRASES = (
    "insanla", "bir insan", "gerçek kişi", "gerçek kişiyle", "gerçek bir kişi", "gerçek bir kişiyle",
    "canlı destek", "temsilci", "temsilciye", "temsilciyle", "temsilciden", "yetkiliyle", "operatörle",
    "talk to a human", "talk to a person", "real person", "representative",
)  # fmt: skip
_PERSON_RE = re.compile(r"(?<![^\W\d_])(?:" + "|".join(map(re.escape, PERSON_PHRASES)) + r")(?![^\W\d_])")
#: A bare "153" is not a request ("153'ü aradım"); "153'e bağla" is.
_CONNECT_153 = re.compile(r"153\S*\s+(?:ile\s+)?(?:bağla|bağlan|görüş|konuş|aktar)")

HANDOFF_TEXT = (
    "İnsanla görüşmek için 153 Çözüm Merkezi'ni arayabilirsin; aramayı sen yaparsın, Nabız kimseyi arayamaz. "
    "Görevliye sorununu, varsa hat, durak ya da ilçe adıyla kısaca anlat. Acil bir durumdaysan 112'yi ara."
)

REFUSAL_TEXT = (
    "Bu soru hak, ücret, ceza ya da sağlıkla ilgili. Bu konularda cevap üretmiyorum: "
    "yanlış bir bilgi sana para, hak ya da sağlık kaybettirebilir. "
    "Doğru bilgi için 153 Çözüm Merkezi'ni ara ya da ilgili kurumun resmî sayfasına bak. "
    "Acil bir durumdaysan 112'yi ara."
)


def _asks_a_price(text: str, words: Sequence[str]) -> bool:
    if "ne kadar" not in text or any(word.startswith(_NOT_A_PRICE) for word in words):
        return False
    return any(word.startswith(_FARE_OBJECTS) for word in words)


def refuses(question: str) -> bool:
    """Is this a rights, fare, fine or health question (R-06)?"""
    text = normalize_tr(question)
    words = text.split()
    if any(word in _REFUSE_WORDS for word in words):
        return True
    if any(word.startswith(_REFUSE_PREFIXES) for word in words):
        return True
    if any(word.startswith(_ILL) and not word.startswith(_HOSPITAL) for word in words):
        return True
    if _asks_a_price(text, words):
        return True
    phrases = [p for p in _REFUSE_PHRASES if p in text]
    if phrases == ["saglik"] and any(place in text for place in _TRAVEL_TO_HEALTH):
        return False
    return bool(phrases)


def refuses_in_context(question: str, earlier_user_messages: Sequence[str]) -> bool:
    """R-06 for this question, or for a short follow-up to a question it refused."""
    if refuses(question):
        return True
    if not earlier_user_messages or not refuses(earlier_user_messages[-1]):
        return False
    text = f"{normalize_tr(question)} "
    return len(text.split()) <= 8 and any(cue in text for cue in _FOLLOW_UP)


def _turkish_emergency(message: str) -> bool:
    text = normalize_tr(message)
    if any(word.startswith(EMERGENCY_TERMS["acil"]) for word in text.split()):
        return True
    if _EMERGENCY_RE.search(text):
        return True
    if _URGENT.search(text) and _URGENT_COMPANY.search(text):
        return True
    return bool(_FELL.search(text) and _FALLEN_PERSON.search(text))


def emergency_intent(message: str) -> bool:
    """Is this an emergency? Decided before any model, tool or refusal is reached: the Turkish rules,
    then the other card languages' rules. Both are fixed words; no model is ever waited for."""
    return _turkish_emergency(message) or emergency_lang.rule_match(message) is not None


def emergency_card(message: str) -> dict[str, str | None]:
    """The card for an emergency the rules found: ``lang``, the language the message is written in among
    those whose rules fired (Turkish when only the Turkish rules did), and ``hazard``."""
    hit = emergency_lang.rule_match(message)
    langs = (hit.langs if hit else frozenset()) | ({"tr"} if _turkish_emergency(message) else frozenset())
    lang = emergency_lang.pick_card_lang(message, langs) if langs else "tr"
    return {"lang": lang, "hazard": emergency_hazard(message)}


def asks_for_person(message: str) -> bool:
    """Does the person ask to talk to a human? The chat then answers with the handoff, not the index."""
    lowered = message.replace("I", "ı").replace("İ", "i").lower()
    return any(_PERSON_RE.search(text) or _CONNECT_153.search(text) for text in (lowered, message.lower()))


def emergency_hazard(message: str) -> str | None:
    """``"gas"`` when an emergency is a gas leak or smell, in Turkish or a card language, else ``None``.
    The page adds İGDAŞ's 187 line to the 112 card for it; 112 stays the first action whatever this says."""
    if _GAS_RE.search(normalize_tr(message)):
        return "gas"
    hit = emergency_lang.rule_match(message)
    return "gas" if hit is not None and hit.gas else None


def names_a_price(text: str) -> bool:
    """Does an answer state an amount of money? A model answer that does is not shown (R-06)."""
    return bool(_PRICE.search(text))


def functional_needs(raw: Iterable[Any]) -> list[str]:
    """The known functional constraints among what the page sent, in a stable order."""
    sent = {str(item).strip().lower() for item in raw if isinstance(item, str)}
    return [key for key in NEEDS if key in sent]


def constraint_block(needs: Sequence[str]) -> str:
    """The system-prompt lines for the person's functional constraints."""
    if not needs:
        return ""
    lines = [
        "## Kullanıcının işlevsel kısıtları",
        "Kullanıcı bunları kendi cihazındaki profilde seçti. Önerini bunlara göre kur; kısıtı cevapta tekrar etme.",
        *(f"- {NEEDS[key]}" for key in needs),
    ]
    return "\n".join(lines)


def _mentions(text: str, key: str) -> bool:
    folded = f" {normalize_tr(text)}"
    return any(f" {phrase}" in folded for phrase in _NEED_PHRASES[key])


def memory_suggestion(message: str, earlier_user_messages: Sequence[str], needs: Sequence[str]) -> dict[str, str] | None:
    """Offer to remember a need the person keeps asking for and has not saved. Never saves."""
    for key in _NEED_PHRASES:
        if key in needs or not _mentions(message, key):
            continue
        times = 1 + sum(_mentions(earlier, key) for earlier in earlier_user_messages)
        if times >= MEMORY_REPEAT_THRESHOLD:
            return {"key": key, "label": NEED_LABELS[key]}
    return None
