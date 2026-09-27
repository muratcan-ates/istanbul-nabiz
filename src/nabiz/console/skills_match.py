"""Read-only course discovery over the captured Enstitu Istanbul catalog."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.text import normalize_tr
from nabiz.console.cards import display_text
from nabiz.console.pii_guard import scan_pii

DATA_ENV = "NABIZ_SKILLS_DATA_DIR"
MAX_AREAS = 3
MAX_KEYWORD = 40
MAX_RESULTS = 10
MODES = ("Yüz Yüze", "Uzaktan")
SELF_STEPS = ("read_page", "checked_travel", "applied_myself")
BIO_URL = "https://bio.ibb.istanbul/"
ISMEK_HOME = "https://enstitu.ibb.istanbul/"


@dataclass(frozen=True, slots=True)
class Reference:
    """Immutable snapshot wrapper; source dictionaries are only read by this module."""

    available: bool
    reason: str | None
    data: Mapping[str, Any]
    bio: Mapping[str, Any]


def data_dir(env=None): return Path((os.environ if env is None else env).get(DATA_ENV) or REPO_ROOT / "data/reference/ismek_bio")


def _clean(value: Any) -> str: return display_text(value.strip()) if isinstance(value, str) else ""


def _valid_official_url(value: Any) -> bool: return isinstance(value, str) and value.startswith("https://enstitu.ibb.istanbul/")


@lru_cache(maxsize=8)
def _read_reference(directory: str, snapshot: tuple[int, ...]) -> Reference:
    del snapshot
    root = Path(directory)
    try:
        data = json.loads((root / "ismek.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    try:
        bio = json.loads((root / "bio.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        bio = {}
    valid = (
        isinstance(data, dict)
        and data.get("status") == "alindi"
        and isinstance(data.get("programs"), list)
        and isinstance(data.get("areas"), list)
        and isinstance(data.get("centers"), list)
        and isinstance(data.get("featured"), list)
    )
    reason = None if valid else _clean(data.get("reason")) or "İSMEK kataloğu bu sunucuda yok."
    return Reference(bool(valid), reason, data if isinstance(data, dict) else {}, bio if isinstance(bio, dict) else {})


def load_reference(path: str | Path | None = None) -> Reference:
    """Load a captured catalog once and refresh the cache when its file changes."""
    root = Path(path).parent if path is not None and Path(path).suffix == ".json" else Path(path or data_dir())
    snapshot = tuple(value for name in ("ismek.json", "bio.json") for value in _file_signature(root / name))
    return _read_reference(str(root.resolve()), snapshot)


def _file_signature(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return 0, 0


def bio_card(path: str | Path | None = None) -> dict[str, Any]: return _bio_card(load_reference(path))


def _bio_card(ref: Reference) -> dict[str, Any]:
    bio = ref.bio
    name = _clean(bio.get("source")) or "Bölgesel İstihdam Ofisleri"
    return {
        "name": name, "title": _clean(bio.get("title")) or name,
        "url": BIO_URL, "status": _clean(bio.get("status")) or "veri_alinamadi",
        "reason": _clean(bio.get("reason")) or "İlan verisi alınamadı.",
    }


def _rows(ref, key): return [x for x in raw if isinstance(x, dict)] if isinstance(raw := ref.data.get(key, []), list) else []


def _safe_url(value: Any) -> str | None: return value if _valid_official_url(value) else None


@dataclass(frozen=True, slots=True)
class Choices:
    branch: str = ""
    areas: tuple[str, ...] = ()
    keyword: str = ""
    district: str = ""
    mode: str = ""
    time: str = ""


def _match_name(value, allowed): return next((item for item in allowed if normalize_tr(item) == normalize_tr(value)), None)


def _catalog_choice(raw: Mapping[str, Any], key: str, values: list[str], label: str) -> str:
    value = raw.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{label} seçimi geçersiz.")
    found = _match_name(value.strip(), values) if value.strip() else ""
    if value.strip() and found is None:
        raise ValueError(f"Katalogdaki bir {label.lower()} seçin.")
    return found or ""


def _selected_areas(raw: Mapping[str, Any], ref: Reference, branch: str) -> tuple[str, ...]:
    area_raw = raw.get("areas", [])
    if not isinstance(area_raw, list) or any(not isinstance(item, str) for item in area_raw):
        raise ValueError("Alan seçimi geçersiz.")
    if len(area_raw) > MAX_AREAS:
        raise ValueError("En çok üç alan seçebilirsiniz.")
    area_by_name = {normalize_tr(_clean(row.get("name"))): row for row in _rows(ref, "areas")}
    keys = [normalize_tr(item.strip()) for item in area_raw]
    if any(
        key not in area_by_name
        or (branch and normalize_tr(str(area_by_name[key].get("branch", ""))) != normalize_tr(branch))
        for key in keys
    ):
        raise ValueError("Seçtiğiniz alan bu dalda bulunmuyor.")
    return tuple(dict.fromkeys(_clean(area_by_name[key].get("name")) for key in keys))


def _keyword(raw: Mapping[str, Any]) -> str:
    value = raw.get("keyword", "")
    if not isinstance(value, str):
        raise ValueError("Anahtar kelime metin olmalı.")
    keyword = value.strip()
    if len(keyword) > MAX_KEYWORD:
        raise ValueError("Anahtar kelime en çok 40 karakter olabilir.")
    if scan_pii(keyword):
        raise ValueError("Anahtar kelimede kişisel bilgi olmasın.")
    return keyword


def validate_choices(raw: Mapping[str, Any], ref: Reference) -> Choices:
    """Validate only catalog choices and a short, PII-screened search word."""
    if not ref.available:
        return Choices()
    branches = [item for item in ref.data.get("branches", []) if isinstance(item, str)]
    branch = _catalog_choice(raw, "branch", branches, "Dal")
    areas, keyword = _selected_areas(raw, ref, branch), _keyword(raw)
    districts = [item for item in ref.data.get("districts", []) if isinstance(item, str)]
    times = [item for item in ref.data.get("times", []) if isinstance(item, str)]
    district, time = _catalog_choice(raw, "district", districts, "İlçe"), _catalog_choice(raw, "time", times, "Zaman")
    mode = raw.get("mode", "")
    if not isinstance(mode, str) or (mode and mode not in MODES):
        raise ValueError("Eğitim tipi seçimi geçersiz.")
    return Choices(branch, areas, keyword, district, mode, time)


def _tokens(value: str) -> tuple[str, ...]: return tuple(part for part in normalize_tr(value).split() if part)


def _has_terms(value, terms): return bool(terms) and all(term in normalize_tr(value) for term in terms)


def _featured_mode(feature, mode):
    wanted = "yuz yuze" if mode == "Yüz Yüze" else "uzaktan"
    return None if not mode else any(wanted in normalize_tr(item) for item in feature.get("modes", []) if isinstance(item, str))


def _bio_data(ref: Reference, choices: Choices) -> dict[str, Any]:
    terms = list({normalize_tr(value): value for value in (*choices.areas, choices.keyword) if value}.values())
    return {"card": _bio_card(ref), "search_terms": terms[:4], "label": "Nabız önerisi; ilan değildir"}


def _area_results(ref: Reference, choices: Choices, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen = {normalize_tr(item) for item in choices.areas}
    return [{"name": _clean(row.get("name")), "programs": row.get("programs"), "url": _safe_url(row.get("url"))}
            for row in rows if normalize_tr(_clean(row.get("name"))) in chosen and _safe_url(row.get("url"))]


def _program_item(
    program: Mapping[str, Any], feature: Mapping[str, Any] | None, choices: Choices, area_by_name: Mapping[str, Any]
) -> tuple[dict[str, Any], int] | None:
    source = feature or {}
    name = _clean(program.get("name") or source.get("name"))
    url = _safe_url(program.get("url") or source.get("url"))
    if not name or not url:
        return None
    item = {"code": str(program.get("code") or _code_from_url(url)), "name": name, "url": url,
            "featured": bool(feature), "reasons": [], "note": None}
    terms = _tokens(choices.keyword)
    points = 0
    if _has_terms(name, terms):
        item["reasons"].append({"text": display_text(f"Program adında '{choices.keyword}' geçiyor"), "from": "choice"})
        points += 3
    if feature:
        hour, kind = _clean(feature.get("hours_text")), _clean(feature.get("kind"))
        facts = ", ".join(value for value in (hour, kind) if value)
        text = f"İSMEK kataloğunda öne çıkan eğitim: {facts or 'kayıtlı'}"
        item["reasons"].append({"text": display_text(text), "from": "catalog"})
        points += 1
        field = _clean(feature.get("field"))
        field_row = area_by_name.get(normalize_tr(field))
        branch_match = bool(
            field_row and choices.branch
            and normalize_tr(str(field_row.get("branch", ""))) == normalize_tr(choices.branch)
        )
        if field and (normalize_tr(field) in {normalize_tr(value) for value in choices.areas} or branch_match):
            item["reasons"].append({"text": display_text(f"Katalog alanı: {field}"), "from": "catalog"})
        if choices.branch == "Mesleki ve Teknik Eğitimler" and kind == "İstihdam Hedefli Mesleki Eğitim":
            item["reasons"].append({"text": "Katalogda türü: İstihdam Hedefli Mesleki Eğitim", "from": "catalog"})
            points += 2
        matched_mode = _featured_mode(feature, choices.mode)
        modes = [_clean(value) for value in feature.get("modes", []) if isinstance(value, str)]
        if matched_mode is True:
            item["reasons"].append({"text": display_text(f"Eğitim tipi: {choices.mode} (katalogda)"), "from": "catalog"})
            points += 1
        elif matched_mode is False:
            text = display_text(f"Katalogda yalnız {', '.join(modes)} görünüyor")
            item["reasons"].append({"text": text, "from": "catalog"})
    else:
        item["note"] = "Süre, gün ve merkez katalogda yok; resmî sayfada."
    return item, points


def _program_results(ref: Reference, choices: Choices) -> list[dict[str, Any]]:
    areas = _rows(ref, "areas")
    area_by_name = {normalize_tr(_clean(row.get("name"))): row for row in areas}
    programs = {normalize_tr(_clean(row.get("name"))): row for row in _rows(ref, "programs")}
    featured = {normalize_tr(_clean(row.get("name"))): row for row in _rows(ref, "featured")}
    terms = _tokens(choices.keyword)
    chosen_areas = {normalize_tr(item) for item in choices.areas}
    results = {
        key: candidate for key, row in programs.items()
        if terms and key not in featured and _has_terms(_clean(row.get("name")), terms)
        if (candidate := _program_item(row, None, choices, area_by_name)) is not None
    }
    for key, feature in featured.items():
        field = _clean(feature.get("field"))
        field_area = area_by_name.get(normalize_tr(field))
        branch_match = bool(
            choices.branch and field_area
            and normalize_tr(str(field_area.get("branch", ""))) == normalize_tr(choices.branch)
        )
        area_match = normalize_tr(field) in chosen_areas
        keyword_match = bool(terms and (_has_terms(_clean(feature.get("name")), terms) or _has_terms(field, terms)))
        unconstrained = not choices.branch and not choices.areas and not terms
        if branch_match or area_match or keyword_match or unconstrained:
            candidate = _program_item(programs.get(key, {}), feature, choices, area_by_name)
            if candidate:
                results[key] = candidate
    ordered = sorted(results.values(), key=lambda pair: (-pair[1], normalize_tr(pair[0]["name"])))[:MAX_RESULTS]
    return [item for item, _ in ordered]


def _center_results(ref: Reference, district: str) -> list[dict[str, Any]]:
    if not district:
        return []
    selected = normalize_tr(district)
    rows = [
        {"name": _clean(row.get("name")), "classrooms": row.get("classrooms"), "programs": row.get("programs"),
         "url": _safe_url(row.get("url")), "note": "Bu merkezde hangi eğitimin açıldığı katalogda yok."}
        for row in _rows(ref, "centers")
        if normalize_tr(_clean(row.get("district"))) == selected and _safe_url(row.get("url"))
    ]
    return sorted(rows, key=lambda item: normalize_tr(item["name"]))


def _source_info(ref: Reference) -> dict[str, Any]:
    return {"name": _clean(ref.data.get("source")) or "Enstitü İstanbul İSMEK",
        "retrieved_at": _clean(ref.data.get("retrieved_at")) or None,
        "license": _clean(ref.data.get("license")), "programs_url": _safe_url(ref.data.get("programs_url")) or ISMEK_HOME,
        "centers_url": _safe_url(ref.data.get("centers_url")) or ISMEK_HOME,
    }


def match(ref: Reference, choices: Choices) -> dict[str, Any]:
    """Build stable catalog matches with a source attached to each reason."""
    jobs = _bio_data(ref, choices)
    if not ref.available:
        official = [{"name": "Enstitü İstanbul İSMEK", "url": ISMEK_HOME}, {"name": jobs["card"]["name"], "url": BIO_URL}]
        return {"available": False, "reason": ref.reason, "official": official, "jobs": jobs}
    areas = _area_results(ref, choices, _rows(ref, "areas"))
    programs = _program_results(ref, choices)
    centers = _center_results(ref, choices.district)
    time_hint = {
        "text": display_text(f"Resmî arama sayfasında 'Eğitim Zamanı: {choices.time}' filtresini seçin."),
        "url": _safe_url(ref.data.get("programs_url")) or ISMEK_HOME, "from": "nabiz",
    } if choices.time else None
    empty_reason = "Bu seçimle katalogda program adı bulunamadı. Alan kartından İSMEK'te arayın." if not programs else None
    return {"available": True, "areas": areas, "programs": programs, "centers": centers, "time_hint": time_hint,
            "jobs": jobs, "source": _source_info(ref), "empty_reason": empty_reason}


def _code_from_url(url: str) -> str: return found.group(1) if (found := re.search(r"BransCode=(\d+)", url)) else ""


def checklist(ref: Reference, code: str) -> dict[str, Any] | None:
    """Return official references and user-owned check steps for one catalog program."""
    if not ref.available or not re.fullmatch(r"\d{1,12}", code):
        return None
    program = next((item for item in _rows(ref, "programs") if str(item.get("code")) == code), None)
    if program is None or not (url := _safe_url(program.get("url"))):
        return None
    retrieved, source = _clean(ref.data.get("retrieved_at")) or None, _safe_url(ref.data.get("programs_url")) or ISMEK_HOME
    official = [{"kind": "official", "text": "Programın resmî sayfası", "url": url}]
    apply_url = ref.data.get("apply_url")
    if isinstance(apply_url, str) and apply_url == "https://enstitukayit.ibb.istanbul/":
        official.append({"kind": "official", "text": "Başvuru adresi", "url": apply_url})
    quote = ({"kind": "quote", "text": sentence, "source": source, "retrieved_at": retrieved}
             if (sentence := _clean(ref.data.get("login_sentence"))) else None)
    return {"code": code, "name": _clean(program.get("name")), "official": official, "quote": quote,
            "self_steps": [{"kind": "self", "id": step} for step in SELF_STEPS],
            "note": "Başvurunuzun durumunu Nabız göremez; kurum doğrulaması değildir."}
