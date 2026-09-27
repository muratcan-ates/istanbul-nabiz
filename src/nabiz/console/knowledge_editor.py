"""Pure rules for classifying knowledge gaps and reviewing source candidates."""

from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any
from urllib.parse import unquote, urlsplit

from ibb_mcp.knowledge.guardrails import DEFAULT_ALLOWLIST, host_allowed

# Design limits; these values describe the editor, not measured system behaviour.
STALE_DAYS = 365
TOP_K = 8
MAX_GAPS = 200
MAX_EVAL_QUESTIONS = 250
MAX_LINKED_QUESTIONS = 12
TAGS = ("missing_source", "wrong_route", "stale", "not_a_gap")
ANSWERED = ("answer", "quote_only")
TAG_LABELS = {
    "missing_source": "Kaynak yok",
    "wrong_route": "Yanlış yönlendirme",
    "stale": "Eski bilgi",
    "not_a_gap": "Açık değil",
}


def _canonical(url: str) -> str:
    """Normalize URLs the same way as the offline knowledge calibration script."""
    parts = urlsplit(unquote(url.strip()))
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    return f"{host}{path}" + (f"?{parts.query}" if parts.query else "")


canonical = _canonical


def _date(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def gap_from_measure(row: dict[str, Any]) -> dict[str, Any] | None:
    """Turn one eval or request measurement into an open gap, without reading external state."""
    mode = str(row.get("mode") or "unknown")
    is_request = row.get("kind") == "request" or str(row.get("ref", "")).startswith("request:")
    sensitive = bool(row.get("sensitive"))
    if sensitive and mode == "refused":
        return {**row, "tag_suggested": "not_a_gap", "why": "required_refusal", "stale_hint": False}

    gold_urls = [url for url in row.get("gold_urls", []) if isinstance(url, str)]
    active_urls = {canonical(url) for url in row.get("active_urls", []) if isinstance(url, str)}
    top_url = row.get("top_url") if isinstance(row.get("top_url"), str) else None
    top_is_gold = bool(gold_urls and top_url and canonical(top_url) in {canonical(url) for url in gold_urls})

    if is_request:
        if mode in ANSWERED:
            tag, why = "wrong_route", "answers_now"
        else:
            tag, why = "missing_source", None
    elif mode in ANSWERED and (not gold_urls or top_is_gold):
        return None
    elif gold_urls and not any(canonical(url) in active_urls for url in gold_urls):
        tag, why = "missing_source", None
    elif gold_urls:
        tag, why = "wrong_route", None
    else:
        tag, why = "missing_source", None

    source_date = row.get("top_source_updated_at") or row.get("top_fetched_at")
    as_of = _date(row.get("as_of"))
    source_at = _date(source_date)
    stale_hint = bool(as_of and source_at and as_of - source_at > dt.timedelta(days=STALE_DAYS))
    result = {**row, "tag_suggested": tag, "why": why, "stale_hint": stale_hint}
    if stale_hint:
        result["stale_at"] = source_date
        result["updated_at_method"] = row.get("top_updated_at_method") or (
            "fetched" if not row.get("top_source_updated_at") else "source_updated_at"
        )
    if gold_urls and row.get("gold_rank") is None:
        result["gold_rank_label"] = "not_in_top_k"
    return result


def group_gaps(gaps: list[dict[str, Any]], overrides: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Group open gaps by service category, applying operator tags over suggestions."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for gap in gaps:
        if gap.get("why") == "required_refusal" or gap.get("tag_suggested") == "not_a_gap":
            continue
        override = overrides.get(str(gap.get("ref")))
        if override and override.get("tag") == "not_a_gap":
            continue
        category = gap.get("category") or gap.get("group") or "Genel bilgi"
        grouped.setdefault(str(category), []).append(gap)

    groups = []
    for category, items in grouped.items():
        rendered = []
        labels: Counter[str] = Counter()
        for gap in items:
            override = overrides.get(str(gap.get("ref")))
            tag = override["tag"] if override else str(gap.get("tag_suggested", "missing_source"))
            labels[tag] += 1
            rendered.append({
                "ref": gap.get("ref"),
                "kind": gap.get("kind", "eval"),
                "excerpt": gap.get("excerpt", ""),
                "lang": gap.get("lang") or "tr",
                "tag": tag,
                "tag_by": "operator" if override else "suggestion",
                "why": gap.get("why"),
                "mode": gap.get("mode", "unknown"),
                "top_url": gap.get("top_url"),
                "top_title": gap.get("top_title"),
                "top_institution": gap.get("top_institution"),
                "level": gap.get("level"),
                "gold_urls": gap.get("gold_urls", []),
                "gold_rank": gap.get("gold_rank"),
                "gold_rank_label": gap.get("gold_rank_label"),
                "stale_hint": bool(gap.get("stale_hint")),
                "updated_at_method": gap.get("updated_at_method"),
                "candidates": int(gap.get("candidates", 0)),
            })
        dominant = min(labels, key=lambda key: (-labels[key], TAGS.index(key) if key in TAGS else len(TAGS)))
        groups.append({"category": category, "count": len(items), "dominant_tag": dominant, "items": rendered})
    return sorted(groups, key=lambda row: (-row["count"], row["category"].casefold()))


def check_candidate(
    url: str,
    *,
    allowlist=DEFAULT_ALLOWLIST,
    robots: dict[str, Any],
    active_versions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check a URL using only local policy snapshots and index metadata."""
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
        valid_authority = bool(host) and not parts.username and not parts.password and port in (None, 443)
    except ValueError:
        parts, host, valid_authority = urlsplit(""), "", False
    secure = parts.scheme.lower() == "https" and valid_authority
    allowed = bool(host) and host_allowed(host, allowlist)
    igdas = host == "igdas.istanbul" or host.endswith(".igdas.istanbul")
    robot_status = robots.get("status", "missing")
    if robot_status == "missing":
        robot_state, robot_detail = "unknown", "robots bilinmiyor; dizine alma sırasında denetlenir"
    elif robot_status == "parsed":
        robot_allowed = robots.get("allowed")
        robot_state = "pass" if robot_allowed is True else "fail"
        robot_detail = "robots izin veriyor" if robot_allowed is True else "robots bu yolu taramaya kapatıyor"
    elif robot_status == "allows_all":
        robot_state, robot_detail = "pass", "robots kaynağı erişilemez olarak kaydedilmiş; politika tüm yollara izin veriyor"
    else:
        robot_state, robot_detail = "fail", "robots politikası bilinmiyor; bu kaynak için tarama kapalı"
    indexed = bool(active_versions)
    checks = [
        {"key": "https", "state": "pass" if secure else "fail",
         "detail": "HTTPS adresi" if secure else "HTTPS adresi gerekli"},
        {"key": "allowlist", "state": "pass" if allowed else "fail",
         "detail": "izinli ana makine" if allowed else "ana makine izin listesinde değil"},
        {"key": "not_igdas", "state": "fail" if igdas else "pass",
         "detail": "Bu kurum sitesi projede taranmıyor" if igdas else "kurum kapsam dışı değil"},
        {"key": "robots", "state": robot_state, "detail": robot_detail},
        {"key": "in_index", "state": "pass" if indexed else "unknown",
         "detail": "sayfa dizinde var" if indexed else "Bu sayfa dizinde yok"},
    ]
    return {
        "accepted": all(item["state"] != "fail" for item in checks),
        "url": url.strip(),
        "host": host,
        "canonical_url": canonical(url),
        "checks": checks,
    }


def summarize_trial(rows: list[dict[str, Any]], candidate_url: str) -> dict[str, Any]:
    """Summarize candidate ranks without retaining question text."""
    ranks = [row.get("candidate_rank") for row in rows]
    indexed_flags = [row.get("candidate_indexed") for row in rows if "candidate_indexed" in row]
    return {
        "questions": len(rows),
        "top1": sum(rank == 1 for rank in ranks),
        "in_top_k": sum(isinstance(rank, int) and 1 <= rank <= TOP_K for rank in ranks),
        "absent": sum(rank is None or (isinstance(rank, int) and rank > TOP_K) for rank in ranks),
        "not_indexed": not any(indexed_flags) if indexed_flags else not any(
            canonical(str(row.get("top_url") or "")) == canonical(candidate_url) for row in rows
        ),
    }


def compare_trials(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any] | None:
    """Describe a before/after change only when the index fingerprint changed."""
    if before.get("fingerprint") == after.get("fingerprint"):
        return None
    old = before.get("summary", {})
    new = after.get("summary", {})
    return {
        "before": old,
        "after": new,
        "before_fingerprint": before.get("fingerprint"),
        "after_fingerprint": after.get("fingerprint"),
    }


def apply_events(candidate: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Replay append-only candidate events; an undo neutralizes its referenced event."""
    undone = {event.get("undoes") for event in events if event.get("kind") == "undone"}
    effective = [event for event in events if event.get("kind") != "undone" and event.get("id") not in undone]
    if not any(event.get("kind") == "proposed" for event in effective):
        return {**candidate, "status": "proposed"}
    status = "proposed"
    has_any_trial = any(event.get("kind") == "tried" for event in events)
    for event in effective:
        kind = event.get("kind")
        if kind == "tried":
            status = "tried"
        elif kind == "approved":
            if status != "tried":
                if not has_any_trial:
                    raise ValueError("A candidate needs a trial before approval.")
                continue
            status = "approved"
        elif kind == "rejected" and status == "tried":
            status = "rejected"
    return {**candidate, "status": status}
