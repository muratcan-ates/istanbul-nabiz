"""Deterministic, offline routing from a citizen question to an institution."""

from __future__ import annotations

import functools
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.text import normalize_tr
from nabiz.console.policy import emergency_intent

AGENCIES_PATH = REPO_ROOT / "data" / "agencies.json"


@dataclass(frozen=True)
class AgencyRoute:
    agency: str | None
    name: str | None
    url: str | None
    district_needed: bool
    district: str | None
    matched: str | None
    text: str
    emergency: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = load_agencies(agencies_path())
        return {
            "agency": self.agency,
            "name": self.name,
            "url": self.url,
            "district_needed": self.district_needed,
            "district": self.district,
            "matched": self.matched,
            "text": self.text,
            "emergency": self.emergency,
            "call": data["call"],
            "districts": data["districts"] if self.district_needed else [],
        }


@dataclass(frozen=True)
class AgencyKeywordRule:
    agency: str
    words: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    phrases: tuple[str, ...] = ()
    together: tuple[str, ...] = ()
    unless: tuple[str, ...] = ()
    context: tuple[str, ...] = ()


# Metro station LineName values in tests/fixtures/metro_stations.json; "m1" is
# the common shorthand for M1A and M1B.
METRO_LINE_CODES = (
    "f1", "f4", "m1", "m1a", "m1b", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9",
    "t1", "t3", "t4", "t5", "tf1", "tf2",
)
# No "ariza": m2 and m3 are also square and cubic metres ("100 m2 dairede arıza", "30 m3, sayaç arızalı").
LITTER_WORDS = ("cop", "copu", "copum", "copun", "cope", "copler", "copleri", "coplerim", "coplerimiz")
LINE_CONTEXT = (
    "istasyon", "hat", "sefer", "asansor", "merdiven", "bant", "durak", "peron",
    "aktarma", "metro", "tramvay", "funikuler",
)


RULES = (
    AgencyKeywordRule("iski", words=("iski",)),
    AgencyKeywordRule("igdas", words=("igdas",)),
    AgencyKeywordRule("iett", words=("iett",)),
    AgencyKeywordRule("metro", phrases=("metro istanbul",)),
    AgencyKeywordRule("ispark", prefixes=("ispark",)),
    AgencyKeywordRule("sehir_hatlari", phrases=("sehir hatlari",)),
    AgencyKeywordRule("istanbulkart", words=("belbim",), prefixes=("istanbulkart", "akbil"), phrases=("istanbul kart",)),
    AgencyKeywordRule("cozum_153", words=("153",), phrases=("cozum merkez",)),
    AgencyKeywordRule("iski", words=("su", "suyu", "suyum", "sular", "sulari", "susuz"),
         prefixes=("kanalizasyon", "rogar", "logar", "lagim", "foseptik"), phrases=("atik su",)),
    AgencyKeywordRule("igdas", words=("gaz", "gazim"), prefixes=("dogalgaz",), phrases=("dogal gaz", "gazi kesil")),
    # Litter in a rail station or tram stop is Metro İstanbul's (it runs the trams too), on a ferry or at a pier
    # Şehir Hatları's (owner's call, DECISIONS #45); metrobus stations remain with IETT; street litter is the district's.
    AgencyKeywordRule("metro", words=LITTER_WORDS, context=("metro", "tramvay", "funikuler"), unless=("metrobus",)),
    AgencyKeywordRule("sehir_hatlari", words=LITTER_WORDS, context=("vapur", "iskele")),
    AgencyKeywordRule("ilce", words=LITTER_WORDS, unless=("metrobus",)),
    AgencyKeywordRule("iett", prefixes=("otobus", "metrobus"), unless=("deniz otobus",)),
    AgencyKeywordRule("metro", prefixes=("metro", "tramvay", "funikuler", "teleferik")),
    AgencyKeywordRule("metro", phrases=("yuruyen merdiven", "yuruyen bant"), unless=("marmaray", "avm", "alisveris")),
    AgencyKeywordRule("metro", words=METRO_LINE_CODES, context=LINE_CONTEXT, unless=("marmaray",)),
    AgencyKeywordRule("ispark", prefixes=("otopark", "parkomat"), phrases=("park yeri",)),
    AgencyKeywordRule("sehir_hatlari", prefixes=("vapur",)),
    AgencyKeywordRule("ilce", prefixes=("nikah", "evlendirme", "evlilik"),
         phrases=("emlak vergi", "cop toplama", "cop konteyner", "cop kutu")),
    AgencyKeywordRule("cozum_153", prefixes=("sikayet", "ihbar"), together=("sorun", "bildir")),
    AgencyKeywordRule("ibb", words=("ibb", "buyuksehir"), prefixes=("kres", "ismek", "mezarlik"),
         phrases=("sosyal yardim", "sosyal destek", "halk ekmek")),
)


def agencies_path() -> Path:
    """Resolve the agency data path at call time so deployments can override it."""
    return Path(os.environ.get("NABIZ_AGENCIES_PATH") or AGENCIES_PATH)


@functools.lru_cache(maxsize=4)
def load_agencies(path: Path | None = None) -> dict[str, Any]:
    path = path or agencies_path()
    return json.loads(path.read_text(encoding="utf-8"))


def _local_emergency(text: str) -> bool:
    words = text.split()
    gas = ("gaz koku" in text or "gaz kacag" in text) and not ("gaz fatura" in text or "gaz sayac" in text)
    building = any(word.startswith("bina") for word in words) and any(word.startswith("catla") for word in words)
    return gas or "enkaz" in text or building


def _prefix_hit(prefixes: tuple[str, ...], words: list[str]) -> str | None:
    return next((prefix for prefix in prefixes if any(word.startswith(prefix) for word in words)), None)


def _vetoed(rule: AgencyKeywordRule, text: str) -> bool:
    return any(f" {phrase}" in f" {text}" for phrase in rule.unless)


def _in_context(rule: AgencyKeywordRule, words: list[str]) -> bool:
    return not rule.context or any(word.startswith(prefix) for prefix in rule.context for word in words)


def _match_rule(rule: AgencyKeywordRule, text: str, words: list[str]) -> str | None:
    if _vetoed(rule, text):
        return None
    hit = next((word for word in rule.words if word in words), None)
    hit = hit or _prefix_hit(rule.prefixes, words)
    hit = hit or next((phrase for phrase in rule.phrases if f" {phrase}" in f" {text}"), None)
    if hit is None and rule.together and all(_prefix_hit((prefix,), words) for prefix in rule.together):
        hit = " ".join(rule.together)
    return hit if hit and _in_context(rule, words) else None


def _district_candidates(data: dict[str, Any]) -> list[tuple[str, str]]:
    candidates = [(normalize_tr(name), name) for name in data["districts"]]
    candidates.extend((normalize_tr(alias), canonical) for alias, canonical in data["district_aliases"].items())
    return candidates


def find_district(text: str, data: dict[str, Any]) -> str | None:
    words = normalize_tr(text).split()
    for word in words:
        for key, canonical in _district_candidates(data):
            if word == key or (word.startswith(key) and len(word) - len(key) <= 3):
                return canonical
    return None


def _district_route(question: str, district: str | None, matched: str, data: dict[str, Any]) -> AgencyRoute:
    selected = district if district is not None else question
    canonical = find_district(selected, data)
    if canonical:
        message = (
            f"Bu, {canonical} Belediyesinin işi. Adresini doğrulamadık: "
            "ilçe belediyenizin resmî sitesine bakın ya da 153'ü arayın."
        )
        return AgencyRoute("ilce", f"{canonical} Belediyesi", None, False, canonical, matched,
                           message)
    if district and normalize_tr(district):
        return AgencyRoute("ilce", "İlçe belediyesi", None, True, None, matched, "Bu ilçe adını tanımadım; listeden seçin.")
    office = data["district_office"]
    return AgencyRoute("ilce", office["name"], None, True, None, matched, "Bu, ilçe belediyenizin işi. Hangi ilçedesiniz?")


def route(question: str, district: str | None = None) -> AgencyRoute:
    data = load_agencies(agencies_path())
    text = normalize_tr(question)
    if emergency_intent(question) or _local_emergency(text):
        return AgencyRoute(None, None, None, False, None, None, "Acil bir durumdaysanız 112'yi arayın.", True)
    words = text.split()
    for rule in RULES:
        matched = _match_rule(rule, text, words)
        if matched:
            if rule.agency == "ilce":
                return _district_route(question, district, matched, data)
            item = next(item for item in data["agencies"] if item["id"] == rule.agency)
            return AgencyRoute(rule.agency, item["name"], item["url"], False, None, matched,
                               f"Bu, {item['possessive']} işi.")
    return AgencyRoute(None, None, None, False, None, None,
                       "Bu sorunun hangi kuruma ait olduğunu çıkaramadım. 153 Çözüm Merkezi doğru kuruma yönlendirir.")
