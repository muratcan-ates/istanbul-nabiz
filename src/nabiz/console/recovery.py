"""Pure flow validation and source checks for the digital access guide."""

from __future__ import annotations

import datetime as dt
import json
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.knowledge.guardrails import clean_for_display, host_allowed, mask_personal
from ibb_mcp.text import looks_like_instruction
from nabiz.console.culture_api import DISCLAIMER

FLOWS_PATH = REPO_ROOT / "data" / "knowledge" / "recovery_flows.json"
CAPTURE_PATH = REPO_ROOT / "data" / "reference" / "erisim" / "capture.json"
AGENCIES_PATH = REPO_ROOT / "data" / "agencies.json"
KINDS, FROMS = ("choice", "check", "end"), ("index", "capture")
HANDOFFS, CHECK_ANSWERS = ("kart-sorun",), ("failed", "not_tried", "solved")
MAX_DEPTH, MAX_OPTIONS, PART_MAX = 6, 6, 400
FRESHNESS_ENV = "NABIZ_KNOWLEDGE_FRESHNESS_SLA_S"
QUOTES_ENV = "NABIZ_ERISIM_QUOTES"
CLAIM_WORDS = (
    "hesabınız açıldı", "erişiminiz geri", "kurtarıldı", "güncellendi", "başarılı", "başarıyla",
    "hak kazan", "uygunsunuz", "iade edil", "restored", "unlocked", "recovered", "succeeded", "eligible", "refund",
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_LONG_DASHES = re.compile(r"[\u2013\u2014]")
_THREE_DIGITS = re.compile(r"\d{3,}")


def fold_recovery_whitespace(text: str) -> str:
    """Fold all whitespace for exact source sentence comparisons."""
    return " ".join(text.split())


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _localized(value: Any, label: str) -> list[str]:
    _require(isinstance(value, dict) and set(value) == {"tr", "en"}, f"{label} must have tr and en")
    _require(all(isinstance(value[lang], str) and value[lang].strip() for lang in ("tr", "en")), f"{label} text is empty")
    return [value[lang] for lang in ("tr", "en")]


def _own_text_is_safe(text: str) -> bool:
    folded = text.casefold()
    return not (_LONG_DASHES.search(text) or re.search(r"\bETA\b|\blive\b|canlı|İBB onaylı", text, re.IGNORECASE)) \
        and not (_EMAIL.search(text) or any(word in folded for word in CLAIM_WORDS)) \
        and all(match.group() == "153" for match in _THREE_DIGITS.finditer(text))


def _agency_ids(agencies: dict) -> set[str]:
    by_id = agencies.get("by_id", agencies)
    return set(by_id) if isinstance(by_id, dict) else set()


def _validate_sources(data: dict) -> None:
    sources = data.get("sources")
    _require(isinstance(sources, dict) and sources, "sources must be a non-empty object")
    for source_id, source in sources.items():
        _require(isinstance(source_id, str) and isinstance(source, dict), "source is invalid")
        try:
            parts = urlsplit(source.get("url", ""))
            host = parts.hostname or ""
        except (TypeError, ValueError) as exc:
            raise ValueError("source URL is invalid") from exc
        _require(parts.scheme == "https" and host and host_allowed(host), "source URL is not allowlisted HTTPS")
        _require(not parts.username and not parts.password and source.get("from") in FROMS, "source URL metadata is invalid")
        _localized(source.get("label"), "source label")


def _validate_quotes(data: dict) -> tuple[set[str], set[str]]:
    quotes = data.get("quotes")
    _require(isinstance(quotes, dict) and quotes, "quotes must be a non-empty object")
    used_sources: set[str] = set()
    for quote_id, quote in quotes.items():
        _require(isinstance(quote_id, str) and isinstance(quote, dict), "quote is invalid")
        source_id = quote.get("source")
        _require(isinstance(source_id, str) and source_id in data["sources"], "quote source is missing")
        used_sources.add(source_id)
        parts = quote.get("parts")
        _require(isinstance(parts, list) and 1 <= len(parts) <= 3, "quote parts are invalid")
        for part in parts:
            _require(isinstance(part, str) and bool(part.strip()), "quote part is empty")
            _require(
                fold_recovery_whitespace(part) == part and len(part) <= PART_MAX and not looks_like_instruction(part)
                and mask_personal(clean_for_display(part)) == part and not _LONG_DASHES.search(part),
                "quote part is unsafe, unnormalized, or too long",
            )
    return set(quotes), used_sources


def _node_texts(node: dict, node_id: str) -> list[str]:
    options = node.get("options", [])
    _require(isinstance(options, list), f"node {node_id} options are invalid")
    _require(all(isinstance(option, dict) for option in options), f"node {node_id} option is invalid")
    return [*_localized(node.get("text"), f"node {node_id} text"),
            *(text for option in options for text in _localized(option.get("text"), f"node {node_id} option text")),
            *(_localized(node["gap"], f"node {node_id} gap") if "gap" in node else [])]


def _validate_nodes(data: dict, agencies: dict, quote_ids: set[str]) -> tuple[set[str], dict[str, list[str]]]:
    nodes = data.get("nodes")
    _require(isinstance(nodes, dict) and nodes, "nodes must be a non-empty object")
    _require(isinstance(data.get("start"), str) and data["start"] in nodes, "start node is missing")
    known_agencies = _agency_ids(agencies)
    used_quotes: set[str] = set()
    edges: dict[str, list[str]] = {}
    for node_id, node in nodes.items():
        _require(isinstance(node_id, str) and isinstance(node, dict), "node is invalid")
        kind = node.get("kind")
        _require(kind in KINDS, "node kind is invalid")
        _node_texts(node, node_id)
        quote_refs, alt_refs = node.get("quotes", []), node.get("alt", [])
        _require(isinstance(quote_refs, list) and isinstance(alt_refs, list), "quote references are invalid")
        refs = quote_refs + alt_refs
        _require(all(isinstance(ref, str) and ref in quote_ids for ref in refs), "node quote reference is missing")
        used_quotes.update(refs)
        _require(("alt" not in node or bool(alt_refs)) and ("handoff" not in node or node["handoff"] in HANDOFFS),
                 "alt or handoff reference is invalid")
        next_ids: list[str] = []
        if kind == "choice":
            options = node.get("options")
            _require(isinstance(options, list) and 2 <= len(options) <= MAX_OPTIONS, "choice option count is invalid")
            _require(all(isinstance(option.get("id"), str) and re.fullmatch(r"[a-z_]+", option["id"])
                         and isinstance(option.get("next"), str) for option in options),
                     "choice option IDs or next nodes are invalid")
            option_ids = [option["id"] for option in options]
            _require(len(set(option_ids)) == len(option_ids), "choice option IDs are not unique")
            next_ids.extend(option["next"] for option in options)
        elif kind == "check":
            _require(bool(quote_refs) and isinstance(node.get("next"), str), "check evidence or next node is invalid")
            next_ids.append(node["next"])
        else:
            _require("next" not in node and "options" not in node and bool(quote_refs or node.get("gap")),
                     "end node cannot continue or has no evidence")
            _require(isinstance(node.get("agency"), str) and node["agency"] in known_agencies, "end agency is unknown")
        edges[node_id] = next_ids
    _require(all(target in nodes for targets in edges.values() for target in targets), "next node is missing")
    return used_quotes, edges


def _check_graph(start: str, edges: dict[str, list[str]]) -> None:
    depths: dict[str, int] = {}
    active: set[str] = set()

    def visit(node_id: str) -> int:
        if node_id in active:
            raise ValueError("flow contains a cycle")
        if node_id in depths:
            return depths[node_id]
        active.add(node_id)
        depth = 1 + max((visit(target) for target in edges[node_id]), default=0)
        active.remove(node_id)
        depths[node_id] = depth
        return depth
    _require(visit(start) <= MAX_DEPTH, "flow is too deep")
    _require(set(depths) == set(edges), "flow contains an unreachable node")


def validate_recovery_flows(data: dict, agencies: dict) -> dict:
    """Validate the reviewed bilingual tree and its privacy and evidence boundaries."""
    _require(isinstance(data, dict) and data.get("version") == 1, "flow version must be 1")
    _validate_sources(data)
    quote_ids, quote_sources = _validate_quotes(data)
    used_quotes, edges = _validate_nodes(data, agencies, quote_ids)
    _require(used_quotes == quote_ids, "flow contains an unused quote")
    _require(quote_sources == set(data["sources"]), "flow contains an unused source")
    _check_graph(data["start"], edges)
    own_texts = [*data.get("summary", {}).values(), *_localized(data.get("alt_note"), "alt_note")]
    own_texts.extend(text for source in data["sources"].values() for text in source["label"].values())
    own_texts.extend(text for node_id, node in data["nodes"].items() for text in _node_texts(node, node_id))
    _require(all(isinstance(text, str) and _own_text_is_safe(text) for text in own_texts), "flow has unsafe Nabız text")
    return data


@lru_cache(maxsize=1)
def load_recovery_flows() -> dict:
    """Read and validate the versioned local flow catalog."""
    return validate_recovery_flows(json.loads(FLOWS_PATH.read_text(encoding="utf-8")), load_recovery_agencies())


@lru_cache(maxsize=1)
def load_recovery_agencies() -> dict:
    """Load only the official call number and the institutions used by this flow."""
    data = json.loads(AGENCIES_PATH.read_text(encoding="utf-8"))
    return {"call": data["call"], "by_id": {item["id"]: {"name": item["name"], "url": item["url"]}
                                                  for item in data["agencies"]}}


def _parsed_time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.replace(tzinfo=dt.UTC) if stamp.tzinfo is None else stamp.astimezone(dt.UTC)


def load_capture(path: Path = CAPTURE_PATH) -> dict[str, dict[str, str]]:
    """Read approved capture entries only when their final URL stays on the same reviewed host."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("entries"), list):
        return {}
    result: dict[str, dict[str, str]] = {}
    for item in data["entries"]:
        if not isinstance(item, dict) or item.get("status") != "ok":
            continue
        url, final_url = item.get("url"), item.get("final_url")
        try:
            original, final = urlsplit(url or ""), urlsplit(final_url or "")
        except (TypeError, ValueError):
            continue
        if (original.scheme != "https" or final.scheme != "https" or not original.hostname or not final.hostname
                or original.hostname.lower() != final.hostname.lower() or not host_allowed(original.hostname)
                or not isinstance(item.get("text"), str)):
            continue
        result[url] = {"text": fold_recovery_whitespace(item["text"]), "fetched_at": item.get("fetched_at", "")}
    return result


def verified_recovery_quotes(
    store: Any, capture: dict[str, dict[str, str]], flows: dict, *, now: dt.datetime, max_age_s: float
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Keep only complete, fresh verbatim quotes still present on their reviewed source page."""
    kept: dict[str, dict] = {}
    sources: dict[str, dict] = {}
    docs = {key: (store.current_document(source["url"]) if source["from"] == "index" and store
                  else capture.get(source["url"]) if source["from"] == "capture" else None)
            for key, source in flows["sources"].items()}
    current = now.replace(tzinfo=dt.UTC) if now.tzinfo is None else now.astimezone(dt.UTC)
    for quote_id, quote in flows["quotes"].items():
        source_id = quote["source"]
        source, document = flows["sources"][source_id], docs[source_id]
        if source["from"] == "index" and store is None:
            continue
        if not document or not isinstance(document.get("body", document.get("text")), str):
            continue
        fetched_at = _parsed_time(document.get("fetched_at"))
        if fetched_at is None or (current - fetched_at).total_seconds() > max_age_s:
            continue
        body = fold_recovery_whitespace(document.get("body", document.get("text", "")))
        if not all(fold_recovery_whitespace(part) in body for part in quote["parts"]):
            continue
        host = urlsplit(source["url"]).hostname or ""
        kept[quote_id] = quote
        sources[source_id] = {"url": source["url"], "host": host, "label": source["label"],
                              "fetched_at": document["fetched_at"], "from": source["from"]}
    return kept, sources


def prune_recovery_nodes(flows: dict, kept: dict) -> dict:
    """Remove unsupported citations and make unsupported checks non-interactive skips."""
    nodes = deepcopy(flows["nodes"])
    for node in nodes.values():
        for key in ("quotes", "alt"):
            if key in node:
                node[key] = [quote for quote in node[key] if quote in kept]
        if node["kind"] == "check" and not node["quotes"]:
            node["kind"] = "skip"
            node.pop("quotes", None)
        if node["kind"] == "end" and not node.get("quotes") and not node.get("gap"):
            node["unverified"] = True
    return nodes


def recovery_flows_payload(
    store: Any, capture: dict[str, dict[str, str]], *, now: dt.datetime, max_age_s: float, quotes_enabled: bool
) -> dict:
    """Build a source-bounded response; answers never enter this server payload."""
    flows, agencies = load_recovery_flows(), load_recovery_agencies()
    kept, sources = verified_recovery_quotes(store, capture, flows, now=now, max_age_s=max_age_s) if quotes_enabled else ({}, {})
    nodes = prune_recovery_nodes(flows, kept)
    agency_ids = {node["agency"] for node in nodes.values() if node.get("agency")}
    return {"version": flows["version"], "start": flows["start"], "nodes": nodes, "quotes": kept,
            "sources": sources, "summary": flows["summary"], "alt_note": flows["alt_note"],
            "contact": {"call": agencies["call"], "agencies": {key: agencies["by_id"][key] for key in sorted(agency_ids)}},
            "disclaimer": DISCLAIMER, "quotes_enabled": quotes_enabled}
