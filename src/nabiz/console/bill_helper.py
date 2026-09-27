"""Source-bound catalogue for explaining a bill without judging its correctness."""

from __future__ import annotations

import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.knowledge.guardrails import host_allowed
from nabiz.console.forbidden_terms import find_forbidden

BILL_ITEMS_PATH = REPO_ROOT / "data" / "knowledge" / "bill_items.json"
NOTICE = (
    "Bilgileri siz girersiniz; bu cihazdan çıkmaz. Nabız faturanızı hesaplamaz ve doğruluğu hakkında karar vermez; "
    "karar kurumunuzundur. Resmî İBB hizmeti değildir."
)
DISCLAIMER = "Nabız faturanızı hesaplamaz ve doğruluğu hakkında karar vermez; karar kurumunuzundur."
NOTICE_EN = (
    "You enter the information; it stays on this device. Nabız does not calculate your bill or decide whether it is "
    "correct; the agency decides. Not an official İBB service."
)
DISCLAIMER_EN = "Nabız does not calculate your bill or decide whether it is correct; the agency decides."
_WS = re.compile(r"\s+")
_DASHES = ("\u2014", "\u2013")


class BillCatalogError(ValueError):
    """The local catalogue cannot be safely used."""


@lru_cache(maxsize=4)
def load_bill_catalog(path: Path = BILL_ITEMS_PATH) -> dict[str, Any]:
    """Read and validate a cached catalogue file; never open the knowledge index here."""
    try:
        catalog = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BillCatalogError("Fatura açıklama kataloğu okunamadı.") from exc
    problems = validate_bill_catalog(catalog)
    if problems:
        raise BillCatalogError("Fatura açıklama kataloğu doğrulanamadı.")
    return catalog


def _source_problems(source: Any, name: str) -> list[str]:
    if source is None:
        return []
    if not isinstance(source, dict):
        return [f"{name}: source nesne ya da null olmalı"]
    problems = []
    url = source.get("url")
    try:
        host = urlsplit(url).hostname if isinstance(url, str) else None
    except ValueError:
        host = None
    if not host or not host_allowed(host):
        problems.append(f"{name}: kaynak adresi izin listesinde değil")
    for key in ("title", "quote", "fetched_at"):
        if not isinstance(source.get(key), str) or not source[key].strip():
            problems.append(f"{name}: {key} boş")
    page = source.get("page")
    if page is not None and (not isinstance(page, int) or page < 1):
        problems.append(f"{name}: sayfa numarası geçersiz")
    return problems


def _localized_problems(value: Any, name: str) -> list[str]:
    if not isinstance(value, dict) or set(value) != {"tr", "en"}:
        return [f"{name}: tr ve en metinleri gerekli"]
    return [f"{name}.{lang}: metin boş" for lang in ("tr", "en") if not isinstance(value[lang], str) or not value[lang].strip()]


def _agency_problems(agencies: Any) -> list[str]:
    if not isinstance(agencies, dict) or not {"iski", "igdas"} <= agencies.keys():
        return ["İSKİ ve İGDAŞ kurum kayıtları gerekli"]
    problems = []
    for agency_id, agency in agencies.items():
        if not isinstance(agency, dict):
            problems.append(f"agencies.{agency_id}: nesne olmalı")
            continue
        problems.extend(_localized_problems(agency.get("name"), f"agencies.{agency_id}.name"))
        if not isinstance(agency.get("url"), str) or not agency["url"].startswith("https://"):
            problems.append(f"agencies.{agency_id}: kurum adresi geçersiz")
        if not isinstance(agency.get("channel"), str) or not agency["channel"].strip():
            problems.append(f"agencies.{agency_id}: resmî kanal gerekli")
    return problems


def _item_problems(items: Any) -> list[str]:
    if not isinstance(items, list) or not items:
        return ["kalem listesi boş"]
    problems = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        label = f"items[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{label}: nesne olmalı")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id or item_id in seen:
            problems.append(f"{label}: id eksik ya da yinelenmiş")
        else:
            seen.add(item_id)
        if item.get("agency") not in {"iski", "igdas"}:
            problems.append(f"{label}: kurum geçersiz")
        for field in ("label", "explain"):
            problems.extend(_localized_problems(item.get(field), f"{label}.{field}"))
        if item.get("agency") == "igdas" and item.get("source") is not None:
            problems.append(f"{label}: İGDAŞ açıklaması kaynaklı olamaz")
        problems.extend(_source_problems(item.get("source"), label))
    return problems


def _tariff_problems(tariff: Any) -> list[str]:
    if not isinstance(tariff, dict) or tariff.get("agency") != "iski":
        return ["İSKİ tarifesi gerekli"]
    problems = []
    rows = tariff.get("rows")
    if not isinstance(rows, list) or len(rows) != 3:
        problems.append("üç konut kademesi gerekli")
        rows = []
    for row in rows:
        if not isinstance(row, dict):
            problems.append("tarife satırı geçersiz")
            continue
        try:
            amounts = float(row["water"]), float(row["wastewater"]), float(row["total"])
            cents = round((amounts[0] + amounts[1] - amounts[2]) * 100)
        except (KeyError, TypeError, ValueError, OverflowError):
            problems.append("tarife satırı geçersiz")
            continue
        if cents != 0:
            problems.append(f"kademe {row.get('tier')}: toplam su ve atık su sütunlarıyla eşleşmiyor")
    problems.extend(_source_problems(tariff.get("source"), "tariff"))
    problems.extend(_localized_problems(tariff.get("note_human_right"), "tariff.note_human_right"))
    return problems


def _concept_problems(concepts: Any) -> list[str]:
    if not isinstance(concepts, list):
        return ["concepts listesi gerekli"]
    problems = []
    concept_ids: set[str] = set()
    for index, concept in enumerate(concepts):
        label = f"concepts[{index}]"
        if not isinstance(concept, dict):
            problems.append(f"{label}: nesne olmalı")
            continue
        concept_id = concept.get("id")
        if not isinstance(concept_id, str) or not concept_id or concept_id in concept_ids:
            problems.append(f"{label}: id eksik ya da yinelenmiş")
        else:
            concept_ids.add(concept_id)
        for field in ("label", "explain"):
            problems.extend(_localized_problems(concept.get(field), f"{label}.{field}"))
        problems.extend(_source_problems(concept.get("source"), label))
    return problems


def validate_bill_catalog(catalog: Any) -> list[str]:
    """Check bilingual text, provenance, privacy-safe copy and tariff arithmetic."""
    if not isinstance(catalog, dict):
        return ["katalog nesne olmalı"]
    problems = []
    if catalog.get("version") != 1:
        problems.append("katalog sürümü 1 olmalı")
    if not isinstance(catalog.get("captured_at"), str) or not catalog["captured_at"].strip():
        problems.append("captured_at gerekli")
    problems.extend(_agency_problems(catalog.get("agencies")))
    problems.extend(_item_problems(catalog.get("items")))
    problems.extend(_tariff_problems(catalog.get("tariff")))
    problems.extend(_concept_problems(catalog.get("concepts")))
    content = _all_catalog_text(catalog)
    if any(dash in content for dash in _DASHES):
        problems.append("katalogda yasak uzun tire var")
    if "canlı" in content.casefold():
        problems.append("katalogda kayıtlı veriyi canlı diye niteleyen metin var")
    problems.extend(f"yasaklı iddia: {term}" for term in find_forbidden(content))
    return list(dict.fromkeys(problems))


def _all_catalog_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_all_catalog_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_all_catalog_text(item) for item in value)
    return ""


def bill_quotes_in_store(catalog: dict[str, Any], store: Any) -> list[str]:
    """Find quotes that no longer match their captured page or numbered PDF part."""
    problems: list[str] = []
    sources = [item.get("source") for item in catalog.get("items", []) if isinstance(item, dict)]
    sources += [concept.get("source") for concept in catalog.get("concepts", []) if isinstance(concept, dict)]
    tariff = catalog.get("tariff")
    if isinstance(tariff, dict):
        sources.append(tariff.get("source"))
    checked: set[tuple[str, int | None, str]] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        url, page, quote = source.get("url"), source.get("page"), source.get("quote")
        key = (url, page, quote)
        if key in checked:
            continue
        checked.add(key)
        document = store.current_document(url)
        if not document:
            problems.append(f"kaynak dizinde yok: {url}")
            continue
        normalized_quote = _WS.sub(" ", quote).strip()
        body = _WS.sub(" ", document.get("body", "")).strip()
        if normalized_quote not in body:
            problems.append(f"alıntı gövdede yok: {url}")
            continue
        if page is not None:
            chunks = _page_chunks(store, document["document_id"], page)
            if not any(normalized_quote in _WS.sub(" ", text).strip() for text in chunks):
                problems.append(f"alıntı s. {page} içinde yok: {url}")
    return problems


def _page_chunks(store: Any, document_id: str, page: int) -> list[str]:
    """Read numbered evidence chunks without using the store's write-capable initializer."""
    if hasattr(store, "page_chunks"):
        return store.page_chunks(document_id, page)
    path = Path(store.path).resolve()
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return [
            str(row[0])
            for row in connection.execute(
                "SELECT text FROM chunks WHERE document_id=? AND page_number=? AND active=1 ORDER BY ordinal",
                (document_id, page),
            )
        ]
    finally:
        connection.close()


def public_bill_catalog(catalog: dict[str, Any], lang: str) -> dict[str, Any]:
    """Return one language's labels and explanations while keeping source quotes in Turkish."""
    selected = "en" if lang == "en" else "tr"
    agencies = {
        key: {**value, "name": value["name"][selected]}
        for key, value in catalog["agencies"].items()
    }
    items = [
        {**item, "label": item["label"][selected], "explain": item["explain"][selected]}
        for item in catalog["items"]
    ]
    concepts = [
        {**concept, "label": concept["label"][selected], "explain": concept["explain"][selected]}
        for concept in catalog["concepts"]
    ]
    tariff = {**catalog["tariff"], "note_human_right": catalog["tariff"]["note_human_right"][selected]}
    return {
        "version": catalog["version"],
        "lang": selected,
        "agencies": agencies,
        "items": items,
        "tariff": tariff,
        "concepts": concepts,
        "notice": NOTICE_EN if selected == "en" else NOTICE,
        "disclaimer": DISCLAIMER_EN if selected == "en" else DISCLAIMER,
        "captured_at": catalog["captured_at"],
    }
