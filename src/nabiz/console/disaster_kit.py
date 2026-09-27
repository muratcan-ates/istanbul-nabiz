"""AKOM-sourced household kit content and provenance checks."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.knowledge.guardrails import host_allowed
from nabiz.console.forbidden_terms import find_forbidden

DISASTER_KIT_PATH = REPO_ROOT / "data" / "knowledge" / "disaster_kit.json"
AKOM_CAPTURE_PATH = REPO_ROOT / "data" / "reference" / "disaster_kit" / "akom_sss.json"
CATALOG_PATH = REPO_ROOT / "data" / "reference" / "ibb_catalog.json"
NOTICE = (
    "Bu dosya yalnız bu cihazda durur. Nabız binanızın ya da evinizin güvenliği hakkında değerlendirme yapmaz. "
    "Resmî İBB hizmeti değildir."
)
DISCLAIMER = "Resmî İBB hizmeti değildir."
NOTICE_EN = "This file stays on this device. Nabız does not assess your building or household. Not an official İBB service."
DISCLAIMER_EN = "Not an official İBB service."
_KIT_QUESTION = "Afet çantasında nelerin olması gerekir?"
_AFIS_QUESTION = "Bazı mahallelerde bulunan deprem konteynırları AKOM’a mı ait?"
_TR_LOWER = str.maketrans({"İ": "i", "I": "ı"})
_SPACE = re.compile(r"\s+")
_BANNED_WORDS = re.compile(r"\b(?:hazırsınız|güvenli|risk|puan)\b", re.IGNORECASE)


class KitError(Exception):
    """The local, reviewed disaster-kit catalogue cannot be read."""


class DocumentLookup(Protocol):
    def current_document(self, url: str) -> Mapping[str, Any] | None: ...


@lru_cache(maxsize=4)
def load_kit(path: Path = DISASTER_KIT_PATH) -> dict[str, Any]:
    """Load the committed catalogue only; the captures are verification inputs, not runtime sources."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KitError("Afet hazırlık listesi bu sunucuda hazır değil.") from exc
    if not isinstance(payload, dict):
        raise KitError("Afet hazırlık listesi bu sunucuda hazır değil.")
    return payload


def _normalized(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


def _capture_quotes(kit: Mapping[str, Any]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for key in ("kit_items", "kit_care"):
        records = kit.get(key, [])
        if isinstance(records, list):
            values.extend(
                (_KIT_QUESTION, item["quote"])
                for item in records
                if isinstance(item, dict) and item.get("source") == "akom_sss" and isinstance(item.get("quote"), str)
            )
    contact = kit.get("contact_basis")
    if isinstance(contact, dict) and contact.get("source") == "akom_sss" and isinstance(contact.get("quote"), str):
        values.append((_KIT_QUESTION, contact["quote"]))
    assembly = kit.get("assembly")
    afis = assembly.get("afis") if isinstance(assembly, dict) else None
    if isinstance(afis, dict) and afis.get("source") == "akom_sss" and isinstance(afis.get("quote"), str):
        values.append((_AFIS_QUESTION, afis["quote"]))
    return values


def _store_quotes(kit: Mapping[str, Any]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    assembly = kit.get("assembly")
    plan = assembly.get("plan_mention") if isinstance(assembly, dict) else None
    if isinstance(plan, dict) and plan.get("source") == "seferberlik" and isinstance(plan.get("quote"), str):
        values.append(("seferberlik", plan["quote"]))
    building = kit.get("building")
    quotes = building.get("quotes", []) if isinstance(building, dict) else []
    if isinstance(quotes, list):
        values.extend(
            (item["source"], item["quote"])
            for item in quotes
            if isinstance(item, dict) and item.get("source") in {"seferberlik", "bina_sss"} and isinstance(item.get("quote"), str)
        )
    return values


def quotes_in_capture(kit: Mapping[str, Any], capture: Mapping[str, Any]) -> list[str]:
    """Return AKOM quotations missing from their captured question and answer."""
    qa = capture.get("qa", [])
    by_question = (
        {
            item.get("question"): _normalized(" ".join(item.get("answer", [])))
            for item in qa
            if isinstance(item, dict) and isinstance(item.get("answer"), list)
        }
        if isinstance(qa, list)
        else {}
    )
    return [quote for question, quote in _capture_quotes(kit) if _normalized(quote) not in by_question.get(question, "")]


def quotes_in_store(kit: Mapping[str, Any], store: DocumentLookup) -> list[str]:
    """Return missing quotations from a caller-provided document lookup."""
    sources = kit.get("sources", {})
    bodies: dict[str, str] = {}
    for source_id in {source for source, _ in _store_quotes(kit)}:
        source = sources.get(source_id) if isinstance(sources, dict) else None
        if not isinstance(source, dict) or not isinstance(source.get("url"), str):
            bodies[source_id] = ""
            continue
        document = store.current_document(source["url"])
        body = document.get("body", "") if isinstance(document, Mapping) else ""
        bodies[source_id] = _normalized(body) if isinstance(body, str) else ""
    return [quote for source, quote in _store_quotes(kit) if _normalized(quote) not in bodies.get(source, "")]


def _tr_lower(value: str) -> str:
    return value.translate(_TR_LOWER).lower()


def catalog_matches(catalog: Mapping[str, Any], terms: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    """Search only dataset names and descriptive fields, with Turkish-aware lowercase rules."""
    datasets = catalog.get("datasets", [])
    if not isinstance(datasets, list):
        return []
    needles = tuple(_tr_lower(term) for term in terms if term)
    matches: list[dict[str, Any]] = []
    for dataset in datasets:
        if not isinstance(dataset, dict):
            continue
        fields = (dataset.get("name", ""), dataset.get("title", ""), dataset.get("notes", ""), dataset.get("tags", []))
        words = (value for field in fields for value in (field if isinstance(field, list) else [field]))
        haystack = _tr_lower(" ".join(str(value) for value in words))
        if any(needle in haystack for needle in needles):
            matches.append(dataset)
    return matches


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def _source_errors(sources: Mapping[str, Any]) -> list[str]:
    errors = []
    for source_id, source in sources.items():
        if not isinstance(source, dict):
            errors.append(f"source:{source_id}")
            continue
        try:
            host = urlsplit(source.get("url", "")).hostname
        except ValueError:
            host = None
        if not host or not host_allowed(host):
            errors.append(f"source_host:{source_id}")
    return errors


def _item_errors(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["kit_items_count"]
    errors = ["kit_items_count"] if len(value) != 19 else []
    ids = []
    for item in value:
        if not isinstance(item, dict):
            errors.append("item_shape")
        elif isinstance(item.get("id"), str):
            ids.append(item["id"])
        else:
            errors.append("item_id")
    if len(ids) != len(set(ids)):
        errors.append("item_ids_unique")
    return errors


def _catalog_records(kit: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    quoted: list[dict[str, Any]] = []
    translated: list[dict[str, Any]] = []
    for key in ("kit_items", "kit_care"):
        values = kit.get(key, [])
        if isinstance(values, list):
            records = [item for item in values if isinstance(item, dict)]
            quoted.extend(records)
            translated.extend(records)
    building = kit.get("building")
    quotes = building.get("quotes", []) if isinstance(building, dict) else []
    if isinstance(quotes, list):
        quoted.extend(item for item in quotes if isinstance(item, dict))
    contact = kit.get("contact_basis")
    if isinstance(contact, dict):
        quoted.append(contact)
    assembly = kit.get("assembly")
    if isinstance(assembly, dict):
        quoted.extend(value for value in (assembly.get("plan_mention"), assembly.get("afis")) if isinstance(value, dict))
    return quoted, translated


def _reference_errors(records: list[dict[str, Any]], sources: Mapping[str, Any]) -> list[str]:
    errors = []
    for item in records:
        source = item.get("source")
        if source not in sources:
            errors.append(f"quote_source:{source}")
        quote = item.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            errors.append("quote_empty")
    return errors


def _translation_errors(records: list[dict[str, Any]]) -> list[str]:
    errors = []
    for item in records:
        translated = item.get("label", item.get("text"))
        if not isinstance(translated, dict) or not all(
            isinstance(translated.get(lang), str) and translated[lang].strip() for lang in ("tr", "en")
        ):
            errors.append("translation")
    return errors


def _display_errors(kit: Mapping[str, Any]) -> list[str]:
    values = list(_strings(kit)) + [NOTICE, DISCLAIMER, NOTICE_EN, DISCLAIMER_EN]
    errors = []
    for text in values:
        if find_forbidden(text):
            errors.append("forbidden_claim")
        if _BANNED_WORDS.search(text) and text != NOTICE:
            errors.append("banned_display_word")
    if any("—" in text or "–" in text for text in values):
        errors.append("dash_glyph")
    if any("canlı" in text.lower() for text in values):
        errors.append("live_word")
    return errors


def validate_kit(kit: Mapping[str, Any]) -> list[str]:
    """Describe catalogue contract violations without changing or repairing its data."""
    sources = kit.get("sources")
    if not isinstance(sources, dict):
        return ["sources"]
    quoted, translated = _catalog_records(kit)
    return (
        _source_errors(sources)
        + _item_errors(kit.get("kit_items"))
        + _reference_errors(quoted, sources)
        + _translation_errors(translated)
        + _display_errors(kit)
    )


def public_kit(kit: Mapping[str, Any], lang: str) -> dict[str, Any]:
    """Return one language of the reviewed catalogue and its public provenance."""
    language = "en" if lang == "en" else "tr"
    sources: dict[str, Any] = {}
    for source_id, value in kit["sources"].items():
        source = {key: item for key, item in value.items() if key != "capture_file" and key != "note"}
        if isinstance(value.get("note"), dict):
            source["note"] = value["note"][language]
        sources[source_id] = source
    assembly = kit["assembly"]
    return {
        "version": kit["version"],
        "lang": language,
        "sources": sources,
        "items": [{**item, "label": item["label"][language]} for item in kit["kit_items"]],
        "care": [{**item, "text": item["text"][language]} for item in kit["kit_care"]],
        "contact_basis": kit["contact_basis"],
        "assembly": {
            "dataset_found": assembly["dataset_found"],
            "catalog_check": {
                "captured_at_utc": assembly["catalog_check"]["captured_at_utc"],
                "count": assembly["catalog_check"]["count"],
                "terms": assembly["catalog_check"]["terms"],
            },
            "plan_mention": assembly["plan_mention"],
            "afis": assembly["afis"],
        },
        "building": kit["building"],
        "channels": kit["channels"],
        "notice": NOTICE if language == "tr" else NOTICE_EN,
        "disclaimer": DISCLAIMER if language == "tr" else DISCLAIMER_EN,
        "captured_at": kit["captured_at"],
    }


def readonly_documents(path: Path) -> DocumentLookup:
    """Build a small read-only lookup over the local index for evidence checks."""

    class ReadOnlyLookup:
        def current_document(self, url: str) -> Mapping[str, Any] | None:
            uri = f"file:{Path(path).resolve()}?mode=ro"
            try:
                with closing(sqlite3.connect(uri, uri=True)) as connection:
                    connection.row_factory = sqlite3.Row
                    row = connection.execute(
                        "SELECT url, body FROM documents WHERE canonical_url=? AND active=1 ORDER BY fetched_at DESC LIMIT 1",
                        (url,),
                    ).fetchone()
            except sqlite3.Error:
                return None
            return dict(row) if row else None

    return ReadOnlyLookup()
