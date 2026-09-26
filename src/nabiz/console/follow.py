"""Followed topics: what "X'i takip etmek istiyorum" becomes, and which topics today's data can serve.

A chat turn that asks to follow something gets a ``follow_suggestion`` in its ``final`` event
("Takip edilecek konu: M2 · onayla"), the way a repeated need gets a memory suggestion. The page
asks; only the person's yes adds it: on the device (up to three topics) or, with an account, on
the server (up to ten). Keyword rules decide, before any model, so the same sentence always gives
the same topic:

* a follow cue is required ("takip et", "haber ver", "follow", "notify me");
* a topic no source of ours carries (water or gas cuts, power cuts) is said honestly: the
  suggestion has ``supported: false`` and names the gap (:data:`NO_SOURCE`);
* a metro line code (``M2``, ``M1A``, ``T1``) follows the line's notices and its recorded lift faults;
* a name before "asansör" / "istasyon" / "yürüyen merdiven" follows that station's lift and
  escalator faults (Metro İstanbul's fault record, ``lift_outage``);
* a bus line code with "hat" or "otobüs" follows the line's measured bunching (``check_alerts``);
* anything else becomes a keyword in the service-page archive (new pages that match it).

A topic is a line, a station or a word: never a place the person is, never a coordinate. The
input is the masked question (:mod:`nabiz.console.pii_guard`).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from ibb_mcp.text import normalize_tr

#: The kinds, what each is fed by, and whether its changes are worth an e-mail.
KINDS: dict[str, dict[str, Any]] = {
    "metro_line": {"source": "Metro İstanbul duyuru ve arıza kaydı", "email": True},
    "station": {"source": "Metro İstanbul arızalı ekipman kaydı", "email": True},
    "bus_line": {
        "source": "İETT araç konumlarından ölçülen hat düzenliliği",
        "email": False,
        "note": "İETT hat duyurusu için veri kaynağı yok; yalnız ölçülen düzensizlik sayfada gösterilir, e-posta gönderilmez.",
    },
    "knowledge": {"source": "Bilgi arşivi (İBB hizmet sayfaları, yerel dizin)", "email": True},
}
NO_SOURCE = "Bu konu için veri kaynağı yok (İBB entegrasyonu gerekir)."
_CUES = ("takip et", "takip etmek", "takibe al", "takip eder", "takip edebilir", "haber ver", "bildirim ver",
         "follow", "notify me", "keep me posted")  # fmt: skip
#: Topics we have no feed for, by folded phrase, with the institution that would have it.
_UNSUPPORTED = (
    (("su kesinti", "suyun kesil", "sular kesil", "iski"), "İSKİ su kesintisi"),
    (("dogalgaz kesinti", "gaz kesinti", "igdas"), "İGDAŞ doğalgaz kesintisi"),
    (("elektrik kesinti", "elektrikler kesil", "bedas", "ayedas"), "elektrik kesintisi"),
)
_METRO = re.compile(r"\b(m1a|m1b|m\d{1,2}|tf\d|t\d|f\d)\b")
_BUS = re.compile(r"\b(\d{1,3}[a-z]{0,3})\b")
_STATION_WORDS = ("asansor", "istasyon", "yuruyen")
_FILLER = frozenset({
    "ben", "bunu", "sunu", "onu", "bu", "su", "o", "lutfen", "istiyorum", "isterim", "etmek", "et", "edebilir",
    "misin", "mi", "mu", "icin", "ve", "ile", "da", "de", "ki", "takip", "takibe", "haber", "ver", "bildir",
    "konusunu", "konusu", "konusundaki", "hakkinda", "hakkindaki", "yeni", "gelismeleri", "gelismelerini",
    "haberleri", "haberlerini", "please", "me", "the", "a", "an", "of", "about", "follow", "notify", "keep",
    "posted", "hatti", "hattini", "hattinin", "hat", "otobus", "otobusu", "metro", "istasyonu",
})  # fmt: skip
MAX_KEYWORD_CHARS = 40
#: A pair of decimal numbers reads as a coordinate: a topic is never a place the person is.
_COORDINATE = re.compile(r"\d{1,3}[.,]\d{2,}\D{1,3}\d{1,3}[.,]\d{2,}")


@dataclass(frozen=True)
class Topic:
    kind: str
    value: str
    label: str
    supported: bool = True
    note: str | None = None

    @property
    def key(self) -> str:
        return f"{self.kind}:{normalize_tr(self.value)}"

    def as_suggestion(self) -> dict[str, Any]:
        """The ``follow_suggestion`` body; the page shows ``prompt`` and, when supported, a confirm button."""
        body = asdict(self)
        body["key"] = self.key
        body["prompt"] = f"Takip edilecek konu: {self.label}" if self.supported else self.note
        body["email"] = bool(KINDS.get(self.kind, {}).get("email")) if self.supported else False
        return body


def _has_cue(folded: str) -> bool:
    return any(cue in folded for cue in _CUES)


def _unsupported(folded: str) -> Topic | None:
    for phrases, name in _UNSUPPORTED:
        if any(phrase in folded for phrase in phrases):
            return Topic("unsupported", name, name, supported=False, note=f"{name}: {NO_SOURCE}")
    return None


def _clean_word(word: str) -> str:
    """A word as the person wrote it, without an apostrophe suffix ("Etiler'deki" is "Etiler")."""
    return re.split(r"['’`]", word.strip('.,;:!?()"«»'), maxsplit=1)[0]


def _station(message: str) -> Topic | None:
    words = message.split()
    folded = [normalize_tr(word) for word in words]
    for index, word in enumerate(folded):
        if not word.startswith(_STATION_WORDS) or index == 0:
            continue
        name = [_clean_word(w) for w, f in zip(words[max(0, index - 2) : index], folded[max(0, index - 2) : index], strict=True)
                if f and f.split()[0] not in _FILLER and not _METRO.fullmatch(f)]  # fmt: skip
        name = [part for part in name if part]
        if name:
            station = " ".join(name)[:60]
            return Topic("station", station, f"{station} istasyonu: asansör ve yürüyen merdiven arızaları")
    return None


def _keyword(message: str) -> Topic | None:
    words = [_clean_word(word) for word in message.split()]
    kept = [word for word in words if word and normalize_tr(word) and normalize_tr(word).split()[0] not in _FILLER]
    keyword = " ".join(kept[:3])[:MAX_KEYWORD_CHARS].strip()
    if len(normalize_tr(keyword)) < 3:
        return None
    return Topic("knowledge", keyword, f"Bilgi arşivinde yeni kaynak: {keyword}")


def suggest_follow(message: str) -> Topic | None:
    """The topic a follow request names, or ``None`` when the message asks to follow nothing."""
    folded = f" {normalize_tr(message)} "
    if not _has_cue(folded) or _COORDINATE.search(message):
        return None
    if (gap := _unsupported(folded)) is not None:
        return gap
    if (line := _METRO.search(folded)) is not None:
        code = line.group(1).upper()
        return Topic("metro_line", code, f"{code} hattı: duyurular ve asansör arızaları")
    if (station := _station(message)) is not None:
        return station
    if " hat" in folded or "otobus" in folded or "iett" in folded:
        for match in _BUS.finditer(folded):
            if any(ch.isdigit() for ch in match.group(1)):
                code = match.group(1).upper()
                return Topic("bus_line", code, f"{code} otobüs hattı: ölçülen düzensizlik", note=KINDS["bus_line"]["note"])
    return _keyword(message)


def topic_from(kind: str, value: str) -> Topic:
    """A topic the page sends back (to follow or to check), validated again: never trusted as sent."""
    value = " ".join(str(value or "").split())[: MAX_KEYWORD_CHARS if kind == "knowledge" else 60]
    if _COORDINATE.search(value):
        raise ValueError("Takip konusu bir konum olamaz; hat, istasyon ya da anahtar kelime yazın.")
    folded = normalize_tr(value)
    if kind == "metro_line" and _METRO.fullmatch(folded):
        return Topic(kind, folded.upper(), f"{folded.upper()} hattı: duyurular ve asansör arızaları")
    if kind == "station" and 2 <= len(folded) <= 60:
        return Topic(kind, value, f"{value} istasyonu: asansör ve yürüyen merdiven arızaları")
    if kind == "bus_line" and re.fullmatch(r"\d{1,3}[a-z]{0,3}", folded):
        return Topic(kind, folded.upper(), f"{folded.upper()} otobüs hattı: ölçülen düzensizlik", note=KINDS["bus_line"]["note"])
    if kind == "knowledge" and len(folded) >= 3:
        return Topic(kind, value, f"Bilgi arşivinde yeni kaynak: {value}")
    raise ValueError("Bu konu takip edilemiyor: türü ya da adı tanınmadı.")
