"""Fixed citizen-facing answers and language helpers for the chat surface."""

from __future__ import annotations

from nabiz.agent.templates import NO_DATA, OUT_OF_SCOPE

#: DECISIONS #35: the product speaks Turkish and English only; any other language falls back to Turkish.
LANGS = ("tr", "en")

FIXED: dict[str, dict[str, str]] = {
    "NO_DATA": {
        "tr": NO_DATA["tr"],
        "en": NO_DATA["en"],
    },
    "OUT_OF_SCOPE": {
        "tr": OUT_OF_SCOPE["tr"],
        "en": OUT_OF_SCOPE["en"],
    },
    "SENSITIVE_REFUSAL": {
        "tr": (
            "Bu soru hak, ücret, ceza ya da sağlıkla ilgili. Bu konularda cevap üretmiyorum: "
            "yanlış bir bilgi sana para, hak ya da sağlık kaybettirebilir. "
            "Doğru bilgi için 153 Çözüm Merkezi'ni ara ya da ilgili kurumun resmî sayfasına bak. "
            "Acil bir durumdaysan 112'yi ara."
        ),
        "en": (
            "This question is about rights, fares, fines or health. I do not write answers on these topics: wrong information "
            "could cost you money, a right or your health. For correct information, call İBB's 153 Solution Centre or check "
            "the official page of the relevant institution. If this is an emergency, call 112."
        ),
    },
    "EMERGENCY": {
        "tr": "Bu acil bir durum olabilir. Lütfen doğrudan ara: 112 (Acil) veya 153 (İBB).",
        "en": "This may be an emergency. Please call directly: 112 (Emergency) or 153 (İBB).",
    },
    "UNKNOWN": {
        "tr": (
            "Bu konuda doğrulayabildiğim güncel bir İBB kaynağı bulamadım. Tahmin yürütmek istemiyorum. "
            "153'e bağlanabilir veya ilgili resmî sayfaya gidebilirsin."
        ),
        "en": (
            "I could not find a current İBB source I can verify for this. I do not want to guess. "
            "You can call 153 or go to the relevant official page."
        ),
    },
    "AI_NOTICE": {
        "tr": "Ben İstanbul şehir bilgi asistanıyım ve yapay zekâ kullanıyorum. Resmî karar veren bir görevli değilim.",
        "en": (
            "I am the Istanbul city information assistant and I use artificial intelligence. "
            "I am not an official who makes decisions."
        ),
    },
}

SOURCE_IS_TURKISH = {
    "tr": "Kaynak metin Türkçedir.",
    "en": "Source text is Turkish.",
}


def fixed_text(key: str, lang: str) -> str:
    """Return one fixed answer, falling back to Turkish for unsupported languages."""
    translations = FIXED[key.upper()]
    return translations.get(lang) or translations["tr"]


def detect_lang(text: str, chosen: str | None = None) -> str | None:
    """Return an explicit tr/en choice; script detection went with Arabic (DECISIONS #35), so ``text`` is unused."""
    return chosen if chosen in LANGS else None


def quote_frame(lang: str, quote: str, url: str | None) -> dict[str, str | None]:
    """Attach the source language without changing or copying the quoted text."""
    return {
        "quote": quote,
        "quote_lang": "tr",
        "url": url,
        "label": None if lang == "tr" else SOURCE_IS_TURKISH.get(lang, SOURCE_IS_TURKISH["en"]),
    }
