"""Fixed citizen-facing answers and language helpers for the chat surface."""

from __future__ import annotations

import unicodedata

from nabiz.agent.templates import NO_DATA, OUT_OF_SCOPE

LANGS = ("tr", "en", "ar")
RTL_LANGS = frozenset({"ar"})

FIXED: dict[str, dict[str, str]] = {
    "NO_DATA": {
        "tr": NO_DATA["tr"],
        "en": NO_DATA["en"],
        "ar": "لا توجد بيانات للإجابة عن هذا السؤال.",
    },
    "OUT_OF_SCOPE": {
        "tr": OUT_OF_SCOPE["tr"],
        "en": OUT_OF_SCOPE["en"],
        "ar": (
            "لا أستطيع الإجابة عن هذا السؤال من البيانات المتوفرة لدي. يمكنك السؤال عن مواقف السيارات والحافلات والمترو "
            "وحركة المرور وجودة الهواء وحداثة البيانات. يمكنك الاتصال بمركز الحلول 153 التابع لـ İBB أو زيارة الصفحة "
            "الرسمية المعنية."
        ),
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
        "ar": (
            "هذا السؤال يتعلق بالحقوق أو الرسوم أو الغرامات أو الصحة. لا أكتب إجابات في هذه المواضيع، لأن معلومة خاطئة قد "
            "تكلّفك مالًا أو حقًا أو صحتك. للحصول على المعلومة الصحيحة اتصل بمركز الحلول 153 التابع لـ İBB أو راجع الصفحة "
            "الرسمية للمؤسسة المعنية. إذا كانت حالة طارئة فاتصل بالرقم 112."
        ),
    },
    "EMERGENCY": {
        "tr": "Bu acil bir durum olabilir. Lütfen doğrudan ara: 112 (Acil) veya 153 (İBB).",
        "en": "This may be an emergency. Please call directly: 112 (Emergency) or 153 (İBB).",
        "ar": "قد تكون هذه حالة طارئة. يُرجى الاتصال مباشرة: 112 (الطوارئ) أو 153 (İBB).",
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
        "ar": (
            "لم أجد مصدرًا حديثًا من İBB يمكنني التحقق منه بشأن هذا الموضوع. لا أريد التخمين. يمكنك الاتصال بالرقم 153 "
            "أو زيارة الصفحة الرسمية المعنية."
        ),
    },
    "AI_NOTICE": {
        "tr": "Ben İstanbul şehir bilgi asistanıyım ve yapay zekâ kullanıyorum. Resmî karar veren bir görevli değilim.",
        "en": (
            "I am the Istanbul city information assistant and I use artificial intelligence. "
            "I am not an official who makes decisions."
        ),
        "ar": "أنا مساعد معلومات مدينة إسطنبول وأستخدم الذكاء الاصطناعي. لست موظفًا رسميًا يتخذ القرارات.",
    },
}

SOURCE_IS_TURKISH = {
    "tr": "Kaynak metin Türkçedir.",
    "en": "Source text is Turkish.",
    "ar": "النص المصدر باللغة التركية.",
}


def fixed_text(key: str, lang: str) -> str:
    """Return one fixed answer, falling back to Turkish for unsupported languages."""
    translations = FIXED[key.upper()]
    return translations.get(lang) or translations["tr"]


def text_dir(lang: str) -> str:
    """Return the writing direction for a supported language."""
    return "rtl" if lang in RTL_LANGS else "ltr"


def detect_lang(text: str, chosen: str | None = None) -> str | None:
    """Choose an explicit language or detect Arabic script without a model or network."""
    if chosen in LANGS:
        return chosen

    arabic = 0
    latin = 0
    for char in text:
        codepoint = ord(char)
        if any(start <= codepoint <= end for start, end in (
            (0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)
        )) and char.isalpha():
            arabic += 1
        elif char.isalpha() and "LATIN" in unicodedata.name(char, ""):
            latin += 1
    return "ar" if arabic > latin else None


def quote_frame(lang: str, quote: str, url: str | None) -> dict[str, str | None]:
    """Attach the source language without changing or copying the quoted text."""
    return {
        "quote": quote,
        "quote_lang": "tr",
        "url": url,
        "label": None if lang == "tr" else SOURCE_IS_TURKISH.get(lang, SOURCE_IS_TURKISH["en"]),
    }
