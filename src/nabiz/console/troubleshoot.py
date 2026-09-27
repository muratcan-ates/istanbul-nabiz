"""Pure flow validation and page-bound quote verification for İstanbulkart help."""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
from functools import lru_cache
from urllib.parse import urlsplit

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.knowledge.guardrails import clean_for_display, host_allowed, mask_personal
from ibb_mcp.knowledge.store import KnowledgeStore
from ibb_mcp.text import looks_like_instruction
from nabiz.console.culture_api import DISCLAIMER

FLOWS_PATH = REPO_ROOT / "data" / "knowledge" / "istanbulkart_flows.json"
AGENCIES_PATH = REPO_ROOT / "data" / "agencies.json"
KINDS = ("choice", "check", "when", "end")
CHECK_ANSWERS = ("failed", "not_tried", "solved")
MAX_DEPTH = 6
MAX_OPTIONS = 7
PART_MAX = 400
FRESHNESS_ENV = "NABIZ_KNOWLEDGE_FRESHNESS_SLA_S"
QUOTES_ENV = "NABIZ_IKART_QUOTES"
CLAIM_WORDS = (
    "iade edil",
    "iade edeceğ",
    "hak kazan",
    "uygunsunuz",
    "hakkınız var",
    "hakkınız yok",
    "başarılı",
    "başarıyla",
    "yüklendi",
    "refund",
    "eligible",
    "you are entitled",
    "succeeded",
    "went through successfully",
)
_DATE_FORMAT = "%m/%d/%Y %I:%M:%S %p"


def normalize(text: str) -> str:
    """Fold whitespace without changing the words that carry the source quote."""
    return " ".join(text.split())


def page_date_iso(raw: str) -> str | None:
    """Parse the source page's recorded month/day date without guessing its format."""
    try:
        return dt.datetime.strptime(raw, _DATE_FORMAT).date().isoformat()
    except (TypeError, ValueError):
        return None


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (dict, list)):
        items = value.values() if isinstance(value, dict) else value
        return [part for item in items for part in _strings(item)]
    return []


def _has_claim(text: str) -> bool:
    return any(word in text.casefold() for word in CLAIM_WORDS)


def _links(node: dict) -> list[str]:
    if node["kind"] == "choice":
        return [option["next"] for option in node["options"]]
    return [node["next"]] if node["kind"] in {"check", "when"} else []


def _validate_graph(start: str, nodes: dict) -> None:
    active: set[str] = set()
    depths: dict[str, int] = {}

    def visit(node_id: str) -> int:
        if node_id in active:
            raise ValueError("flow contains a cycle")
        if node_id in depths:
            return depths[node_id]
        active.add(node_id)
        targets = _links(nodes[node_id])
        if any(target not in nodes for target in targets):
            raise ValueError("unknown next node")
        depth = 1 + max((visit(target) for target in targets), default=0)
        active.remove(node_id)
        if depth > MAX_DEPTH:
            raise ValueError("flow exceeds maximum depth")
        depths[node_id] = depth
        return depth

    visit(start)
    if set(depths) != set(nodes):
        raise ValueError("flow contains unreachable nodes")


def _validate_sources(sources: dict) -> None:
    for source in sources.values():
        url = source.get("url") if isinstance(source, dict) else None
        try:
            host = urlsplit(url).hostname
        except (TypeError, ValueError):
            host = None
        if (
            not isinstance(url, str)
            or not url.startswith("https://")
            or not host
            or not host_allowed(host)
            or not page_date_iso(source.get("page_date_raw"))
        ):
            raise ValueError("invalid source")


def _validate_quotes(quotes: dict, sources: dict) -> set[str]:
    used_sources: set[str] = set()
    for quote_id, quote in quotes.items():
        if not isinstance(quote, dict):
            raise ValueError(f"invalid quote: {quote_id}")
        parts = quote.get("parts")
        source_id = quote.get("source")
        if source_id not in sources or not isinstance(parts, list) or not 1 <= len(parts) <= 3:
            raise ValueError(f"invalid quote: {quote_id}")
        used_sources.add(source_id)
        for part in parts:
            if not isinstance(part, str) or not part or normalize(part) != part or len(part) > PART_MAX:
                raise ValueError(f"invalid quote text: {quote_id}")
            if looks_like_instruction(part) or "—" in part or "–" in part:
                raise ValueError(f"unsafe quote text: {quote_id}")
            if clean_for_display(part) != part or mask_personal(part) != part:
                raise ValueError(f"quote needs display cleanup: {quote_id}")
    return used_sources


def _validate_options(node_id: str, options: object) -> None:
    if not isinstance(options, list) or not 2 <= len(options) <= MAX_OPTIONS or any(
        not isinstance(item, dict) for item in options
    ):
        raise ValueError(f"invalid options: {node_id}")
    ids = [item.get("id", "") for item in options]
    if len(set(ids)) != len(ids) or any(not isinstance(item, str) or not re.fullmatch(r"[a-z_]+", item) for item in ids):
        raise ValueError(f"invalid option ids: {node_id}")


def _validate_claims(node_id: str, values: list[str]) -> None:
    pattern = re.compile(r"\bETA\b|\blive\b|canlı|İBB onaylı", re.I)
    if any("—" in text or "–" in text or pattern.search(text) or _has_claim(text) for text in values):
        raise ValueError(f"unsupported claim in node: {node_id}")


def _validate_node(node_id: str, node: dict, quotes: dict) -> set[str]:
    if not isinstance(node, dict):
        raise ValueError(f"invalid node: {node_id}")
    kind = node.get("kind")
    if kind not in KINDS:
        raise ValueError(f"unknown node kind: {node_id}")
    if not isinstance(node.get("text"), dict) or any(not node["text"].get(lang) for lang in ("tr", "en")):
        raise ValueError(f"missing bilingual node text: {node_id}")
    refs = node.get("quotes", [])
    if not isinstance(refs, list) or any(quote_id not in quotes for quote_id in refs):
        raise ValueError(f"unknown quote on node: {node_id}")
    if kind == "choice":
        _validate_options(node_id, node.get("options"))
    elif kind == "check" and (not refs or not node.get("next")):
        raise ValueError(f"check needs a quote and next node: {node_id}")
    elif kind == "when" and not node.get("next"):
        raise ValueError(f"when needs a next node: {node_id}")
    elif kind == "end" and ("next" in node or "options" in node or not refs and not node.get("gap")):
        raise ValueError(f"invalid end node: {node_id}")
    values = _strings(node.get("text")) + _strings(node.get("gap")) + _strings(node.get("options", []))
    _validate_claims(node_id, values)
    return set(refs)


def validate_flows(data: dict) -> dict:
    """Reject malformed, unsafe or unsourced flows before they can reach the page."""
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("unsupported flow version")
    agencies = json.loads(AGENCIES_PATH.read_text(encoding="utf-8"))
    agency_ids = {item.get("id") for item in agencies.get("agencies", [])}
    if data.get("agency") not in agency_ids:
        raise ValueError("unknown agency")
    sources, quotes, nodes = (data.get(key) for key in ("sources", "quotes", "nodes"))
    if not all(isinstance(item, dict) for item in (sources, quotes, nodes)):
        raise ValueError("sources, quotes and nodes must be objects")
    _validate_sources(sources)
    used_sources = _validate_quotes(quotes, sources)
    start = data.get("start")
    if start not in nodes:
        raise ValueError("unknown start node")
    used_quotes: set[str] = set()
    for node_id, node in nodes.items():
        used_quotes.update(_validate_node(node_id, node, quotes))
    if used_quotes != set(quotes) or used_sources != set(sources):
        raise ValueError("unused quote")
    _validate_claims("summary", _strings(data.get("summary", {})))
    _validate_graph(start, nodes)
    return data


@lru_cache(maxsize=1)
def load_flows() -> dict:
    """Load and validate the reviewed flow catalog once per process."""
    return validate_flows(json.loads(FLOWS_PATH.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def load_contact() -> dict:
    """Resolve the hotline and BELBİM's site from the shared agency catalog."""
    flows = load_flows()
    catalog = json.loads(AGENCIES_PATH.read_text(encoding="utf-8"))
    agency = next(item for item in catalog["agencies"] if item["id"] == flows["agency"])
    return {"call": catalog["call"], "agency": {"name": agency["name"], "url": agency["url"]}}


def _as_utc(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=dt.UTC) if parsed.tzinfo is None else parsed.astimezone(dt.UTC)
    except (AttributeError, TypeError, ValueError):
        return None


def verified_quotes(store: KnowledgeStore, flows: dict, *, now: dt.datetime, max_age_s: float) -> tuple[dict, dict]:
    """Keep exact quote parts only while their own active page is recent and still contains them."""
    kept: dict = {}
    sources: dict = {}
    for quote_id, quote in flows["quotes"].items():
        source_id = quote["source"]
        page = store.current_document(flows["sources"][source_id]["url"])
        fetched = _as_utc(page.get("fetched_at")) if page else None
        if not page or not fetched or (now.astimezone(dt.UTC) - fetched).total_seconds() > max_age_s:
            continue
        body = normalize(page.get("body", ""))
        if not all(part in body for part in quote["parts"]):
            continue
        if not all(clean_for_display(part) == part and mask_personal(part) == part for part in quote["parts"]):
            continue
        kept[quote_id] = quote
        if source_id not in sources:
            raw_date = flows["sources"][source_id]["page_date_raw"]
            sources[source_id] = {
                "url": flows["sources"][source_id]["url"],
                "host": urlsplit(flows["sources"][source_id]["url"]).hostname,
                "name": load_contact()["agency"]["name"],
                "fetched_at": page["fetched_at"],
                "page_date": page_date_iso(raw_date) if raw_date in body else None,
            }
    return kept, sources


def prune(flows: dict, kept: dict) -> dict:
    """Remove unsupported quote references and skip checks that lost their evidence."""
    nodes = copy.deepcopy(flows["nodes"])
    for node in nodes.values():
        node["quotes"] = [item for item in node.get("quotes", []) if item in kept]
        if node["kind"] == "check" and not node["quotes"]:
            node["kind"] = "skip"
        if node["kind"] == "end" and not node["quotes"] and not node.get("gap"):
            node["unverified"] = True
    return nodes


def flows_payload(store, *, now: dt.datetime, max_age_s: float, quotes_enabled: bool) -> dict:
    """Build a read-only response; no user answer or query enters this function."""
    flows = load_flows()
    kept, sources = ({}, {})
    if store is not None and quotes_enabled:
        kept, sources = verified_quotes(store, flows, now=now, max_age_s=max_age_s)
    return {
        "version": flows["version"],
        "start": flows["start"],
        "nodes": prune(flows, kept),
        "quotes": {key: {"source": value["source"], "parts": value["parts"]} for key, value in kept.items()},
        "sources": sources,
        "summary": flows["summary"],
        "contact": load_contact(),
        "disclaimer": DISCLAIMER,
        "quotes_enabled": quotes_enabled,
    }
