"""Source-quoted transit fare catalogue: loading, validation and the public view."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.knowledge.guardrails import host_allowed
from nabiz.console.forbidden_terms import find_forbidden

FARES_PATH = REPO_ROOT / "data" / "reference" / "tarife" / "fares.json"
CAPTURE_PATH = REPO_ROOT / "data" / "reference" / "tarife" / "capture.json"
AGENCIES_PATH = REPO_ROOT / "data" / "agencies.json"
NOTICE = (
    "Ücretler resmî sayfalardan kaydedildi; hesap bir tahmindir, resmî ücret değildir. "
    "Hangi tarifenin kartınıza uygulandığını İstanbulkart belirler. Resmî İBB hizmeti değildir."
)
DISCLAIMER = "Resmî İBB hizmeti değildir."
_TR_AMOUNT = re.compile(r"^(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d{1,2})?\s*₺$")
_DOT_AMOUNT = re.compile(r"^\d+(?:\.\d{1,2})?$")


class FareCatalogError(RuntimeError):
    """The hand-maintained catalogue is absent, malformed, or not source-backed."""



def parse_amount(raw: str, style: str) -> int:
    """Parse a source's Turkish-lira spelling into kuruş without accepting other formats."""
    if not isinstance(raw, str):
        raise ValueError("amount must be text")
    if style == "tr" and _TR_AMOUNT.fullmatch(raw):
        value = raw.removesuffix("₺").strip().replace(".", "").replace(",", ".")
    elif style == "dot" and _DOT_AMOUNT.fullmatch(raw):
        value = raw
    else:
        raise ValueError("unsupported fare spelling")
    whole, _, fraction = value.partition(".")
    return int(whole) * 100 + int((fraction + "00")[:2])


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FareCatalogError("fare catalogue unavailable") from exc
    if not isinstance(payload, dict):
        raise FareCatalogError("fare catalogue must be an object")
    return payload


@lru_cache(maxsize=4)
def load_fare_catalog(path: Path = FARES_PATH) -> dict[str, Any]:
    """Load the local JSON catalogue once; never opens the knowledge database."""
    catalog = _read_json(Path(path))
    problems = validate_fare_catalog(catalog)
    if problems:
        raise FareCatalogError("fare catalogue failed validation")
    return catalog

def _metro_quote_pairs(metro: dict[str, Any], url: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for group in ("single", "subscription"):
        section = metro.get(group, {})
        for row in section.get("rows", {}).values():
            pairs.append((url, row.get("quote", "")))
        for row in section.get("other", []):
            pairs.append((url, row.get("quote", "")))
    for row in metro.get("eticket", {}).get("packs", []):
        pairs.append((url, row.get("quote", "")))
    return pairs


def _ferry_quote_pairs(ferry: dict[str, Any], url: str) -> list[tuple[str, str]]:
    pairs = [(url, row.get("quote", "")) for group in ("routes", "transfers") for row in ferry.get(group, [])]
    rules = ferry.get("rules", {})
    names = ("transfer_scope", "personalized_only", "night_double", "subscription_valid", "distance_based")
    pairs.extend((url, rules.get(name, {}).get("quote", "")) for name in names)
    pairs.append((url, rules.get("window_quote", "")))
    return pairs


def _quote_pairs(catalog: dict[str, Any]) -> list[tuple[str, str]]:
    sources = catalog.get("sources", {})
    pairs: list[tuple[str, str]] = []
    for key in ("metro", "ferry", "cards_note"):
        source = sources.get(key, {})
        url = source.get("url") if isinstance(source, dict) else None
        if not url:
            continue
        if key == "metro":
            pairs.extend(_metro_quote_pairs(catalog.get("metro", {}), url))
        elif key == "ferry":
            pairs.extend(_ferry_quote_pairs(catalog.get("ferry", {}), url))
        else:
            pairs.append((url, source.get("quote", "")))
    return pairs


def _quote_entries(catalog: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Return source id, source URL and exact snippet for every cited line."""
    result = []
    for url, quote in _quote_pairs(catalog):
        source_key = next((key for key, value in catalog.get("sources", {}).items() if value.get("url") == url), "")
        result.append((source_key, url, quote))
    return result


def _normalize_quote(value: str) -> str:
    return " ".join(value.split())


def _validate_sources(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    sources = catalog.get("sources")
    if not isinstance(sources, dict):
        return ["sources must be an object"]
    for name in ("metro", "ferry", "iett", "cards_note"):
        source = sources.get(name)
        if not isinstance(source, dict):
            errors.append(f"source missing: {name}")
            continue
        url = source.get("url")
        try:
            parsed = urlsplit(url or "")
        except ValueError:
            parsed = None
        if parsed is None or parsed.scheme != "https" or not parsed.hostname or not host_allowed(parsed.hostname):
            errors.append(f"source host not allowed: {name}")
        if not source.get("fetched_at"):
            errors.append(f"source date missing: {name}")
    for source_id, _, quote in _quote_entries(catalog):
        if source_id not in sources or not isinstance(quote, str) or not quote.strip():
            errors.append(f"quote missing: {source_id}")
            continue
        if "\u2014" in quote or "\u2013" in quote:
            errors.append(f"dash in quote: {source_id}")
    return errors

def _validate_metro_group(errors: list[str], name: str, group: dict[str, Any]) -> None:
    for tariff in ("tam", "ogrenci", "ogrenci30"):
        row = group.get("rows", {}).get(tariff)
        if not isinstance(row, dict):
            errors.append(f"{name} row missing: {tariff}")
            continue
        _check_amount(errors, row, "tr", f"{name}.{tariff}")
        if row.get("raw") not in row.get("quote", ""):
            errors.append(f"raw is not in quote: {name}.{tariff}")
        if name == "subscription" and row.get("passes") is not None and row["passes"] <= 0:
            errors.append(f"invalid pass count: {tariff}")
    for index, row in enumerate(group.get("other", [])):
        _check_amount(errors, row, "tr", f"{name}.other.{index}")
        if row.get("raw") not in row.get("quote", ""):
            errors.append(f"raw is not in quote: {name}.other.{index}")


def _validate_metro(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    metro = catalog.get("metro", {})
    for name in ("single", "subscription"):
        _validate_metro_group(errors, name, metro.get(name, {}))
    if metro.get("subscription", {}).get("rows", {}).get("ogrenci30", {}).get("passes", 0) is not None:
        errors.append("ogrenci30 subscription pass count must remain unknown")
    for index, row in enumerate(metro.get("eticket", {}).get("packs", [])):
        _check_amount(errors, row, "tr", f"eticket.{index}")
        if row.get("passes", 0) <= 0 or row.get("raw") not in row.get("quote", ""):
            errors.append(f"invalid electronic ticket: {index}")
    return errors


def _validate_ferry_route(errors: list[str], route: dict[str, Any], index: int) -> None:
    label = route.get("label", "").casefold()
    if "adalar" in label or "eminönü - kadıköy" in label:
        errors.append(f"excluded ferry route present: {index}")
    if not route.get("quote"):
        errors.append(f"route quote missing: {index}")
    for tariff in ("tam", "ogrenci30", "ogrenci"):
        fare = route.get("fares", {}).get(tariff)
        if not isinstance(fare, dict):
            errors.append(f"route fare missing: {route.get('id')}.{tariff}")
            continue
        _check_amount(errors, fare, "dot", f"route.{route.get('id')}.{tariff}")
        if fare.get("raw") not in route.get("quote", ""):
            errors.append(f"route amount is not in quote: {route.get('id')}.{tariff}")
    other = route.get("other", {}).get("İndirimli (TL)")
    if not isinstance(other, dict):
        errors.append(f"route other fare missing: {route.get('id')}")
        return
    _check_amount(errors, other, "dot", f"route.{route.get('id')}.other")
    if other.get("raw") not in route.get("quote", ""):
        errors.append(f"route other amount is not in quote: {route.get('id')}")


def _validate_ferry(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    ferry = catalog.get("ferry", {})
    routes = ferry.get("routes", [])
    if not routes:
        errors.append("ferry routes missing")
    route_ids = set()
    for index, route in enumerate(routes):
        route_ids.add(route.get("id"))
        _validate_ferry_route(errors, route, index)
    if len(route_ids) != len(routes):
        errors.append("ferry route ids are not unique")
    for index, transfer in enumerate(ferry.get("transfers", [])):
        if transfer.get("n") != index + 1:
            errors.append(f"transfer sequence invalid: {index}")
        for key, fare in transfer.get("fares", {}).items():
            _check_amount(errors, fare, "dot", f"transfer.{index}.{key}")
            if fare.get("raw") not in transfer.get("quote", ""):
                errors.append(f"transfer amount is not in quote: {index}.{key}")
    return errors


def _validate_display(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for _, quote in _quote_pairs(catalog):
        if not isinstance(quote, str) or not quote.strip():
            errors.append("empty quote")
    for text in (NOTICE, DISCLAIMER):
        if find_forbidden(text):
            errors.append("forbidden claim in notice")
        if "\u2014" in text or "\u2013" in text or "canlı" in text.casefold():
            errors.append("forbidden display text")
    bus = catalog.get("missing", {}).get("bus")
    if not isinstance(bus, dict) or bus.get("status") != "alinamadi" or not bus.get("checked_at"):
        errors.append("bus capture must say unavailable with its check time")
    return errors


def validate_fare_catalog(catalog: dict[str, Any]) -> list[str]:
    """Report broken URLs, arithmetic, citations, or unsafe display claims."""
    if not isinstance(catalog.get("sources"), dict):
        return ["sources must be an object"]
    errors = _validate_sources(catalog)
    errors.extend(_validate_metro(catalog))
    errors.extend(_validate_ferry(catalog))
    errors.extend(_validate_display(catalog))
    return errors


def _check_amount(errors: list[str], row: dict[str, Any], style: str, field: str) -> None:
    try:
        parsed = parse_amount(row.get("raw"), style)
    except (TypeError, ValueError):
        errors.append(f"bad amount: {field}")
        return
    if parsed != row.get("kurus"):
        errors.append(f"amount mismatch: {field}")
    if parsed <= 0:
        errors.append(f"nonpositive amount: {field}")


def fare_quotes_in_store(catalog: dict[str, Any], store: Any) -> list[str]:
    """Check each saved snippet and source timestamp against an already-open store-like reader."""
    problems: list[str] = []
    checked: dict[str, dict[str, Any] | None] = {}
    for source_id, url, quote in _quote_entries(catalog):
        if url not in checked:
            try:
                checked[url] = store.current_document(url)
            except (AttributeError, OSError, RuntimeError):
                checked[url] = None
        document = checked[url]
        source = catalog.get("sources", {}).get(source_id, {})
        if not document:
            problems.append(f"source absent: {source_id}")
            continue
        if document.get("canonical_url") != url:
            problems.append(f"source URL mismatch: {source_id}")
        if document.get("fetched_at") != source.get("fetched_at"):
            problems.append(f"source timestamp mismatch: {source_id}")
        body = document.get("body", "")
        if not isinstance(body, str) or _normalize_quote(quote) not in _normalize_quote(body):
            problems.append(f"quote absent: {source_id}")
    return problems



def public_fare_catalog(catalog: dict[str, Any], lang: str) -> dict[str, Any]:
    """Expose only static fare choices, source metadata, and the captured missing status."""
    if lang not in {"tr", "en"}:
        raise ValueError("invalid language")
    agencies = _read_json(AGENCIES_PATH)
    agency = next((item for item in agencies.get("agencies", []) if item.get("id") == "istanbulkart"), None)
    if agency is None or not agencies.get("call"):
        raise FareCatalogError("official contact source unavailable")
    return {
        "language": lang,
        "tariffs": ["tam", "ogrenci", "ogrenci30", "other"],
        "ferry_routes": [{"id": row["id"], "label": row["label"]} for row in catalog["ferry"]["routes"]],
        "sources": catalog["sources"],
        "missing": catalog["missing"],
        "official_contact": {"phone": agencies["call"], "name": agency["name"], "url": agency["url"]},
    }
