"""Pure validation and comparison rules for hypothetical lift-closure scenarios."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from types import SimpleNamespace
from typing import Any

from ibb_mcp.models import MetroStation
from ibb_mcp.text import fold_tr, rank_match_loose, squash_punctuation
from nabiz.console.pii_guard import mask_labels

# Design limits, not measured values.
MAX_ROUTES = 12
MAX_SAVED_PAIRS = 30
MIN_CELL = 3
MAX_PLACE_CHARS = 60
EFFECTS = ("blocked", "detour", "not_affected", "already_unavailable", "unverified")
SCENARIO_MARK = "nabiz-scenario"

# Offline examples are measured against the committed station and equipment recordings.
DEMO_ROUTES: tuple[tuple[str, str], ...] = (
    ("Zeytinburnu", "Bağcılar"),
    ("Bostancı", "Kartal"),
    ("Maltepe", "Pendik"),
)

ASSUMPTIONS = ("hypothetical", "endpoints_only", "same_record", "not_traffic", "model_times")
SAVED_ASSUMPTIONS = ("saved_scope", "small_hidden")
_COORDINATES = re.compile(r"^[+-]?\d{1,3}(?:\.\d+)?\s*[,;]\s*[+-]?\d{1,3}(?:\.\d+)?$")
_UNVERIFIED_CODES = {"equipment_data_unavailable", "station_data_unavailable"}
_SUPPORTED_NEEDS = ("step_free", "slow_walk")


def _line_key(name: str | None) -> str:
    match = re.match(r"[a-z0-9]+", fold_tr(name))
    return match.group(0).upper() if match else ""


def _station_key(name: str | None) -> str:
    return squash_punctuation(fold_tr(name))


def _resolve_platforms(name: str, stations: Sequence[MetroStation]) -> list[MetroStation]:
    query = fold_tr(name)
    if not query:
        return []
    loose = squash_punctuation(query)
    ranked = [(rank, station) for station in stations if (rank := rank_match_loose(query, loose, station.name)) is not None]
    if not ranked:
        return []
    best = min(rank for rank, _ in ranked)
    return [station for rank, station in ranked if rank == best]


def _record_matches_platform(record: Any, platform: MetroStation) -> bool:
    name, line = _station_key(record.station_name), _line_key(record.line_name)
    same_id = record.station_id is not None and platform.station_id == record.station_id
    if same_id and (not name or _station_key(platform.name) == name):
        return True
    return bool(name and _station_key(platform.name) == name and (not line or _line_key(platform.line_name) == line))


line_key = _line_key
station_key = _station_key
resolve_platforms = _resolve_platforms


def _place(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if not 2 <= len(text) <= MAX_PLACE_CHARS:
        raise ValueError("Başlangıç ve varış yerini 2 ile 60 karakter arasında yazın.")
    if _COORDINATES.fullmatch(text):
        raise ValueError("Güzergâh bir konum olamaz; istasyon ya da yer adı yazın.")
    _, count, _ = mask_labels(text)
    if count:
        raise ValueError("Güzergâhta kişisel bilgi olamaz.")
    return text


def route_from(raw: str | Mapping[str, Any]) -> dict[str, Any]:
    """Validate one route while keeping personal labels out of later work."""
    if isinstance(raw, str):
        parts = raw.split(">")
        if len(parts) != 2:
            raise ValueError("Güzergâhı Başlangıç > Varış biçiminde yazın.")
        origin, destination, needs = parts[0], parts[1], None
    elif isinstance(raw, Mapping):
        origin, destination, needs = raw.get("from"), raw.get("to"), raw.get("needs")
    else:
        raise ValueError("Güzergâh metnini ya da başlangıç ve varış alanlarını gönderin.")
    start, end = _place(origin), _place(destination)
    if fold_tr(start) == fold_tr(end):
        raise ValueError("Başlangıç ve varış aynı olamaz.")
    try:
        asked = tuple(dict.fromkeys(need.strip() for need in (needs or ()) if need and need.strip()))
        checked = asked or ("step_free",)
    except (AttributeError, TypeError) as exc:
        raise ValueError(f"İhtiyaç türü desteklenmiyor. Desteklenenler: {', '.join(_SUPPORTED_NEEDS)}.") from exc
    unknown = [need for need in checked if need not in _SUPPORTED_NEEDS]
    if unknown:
        raise ValueError(f"İhtiyaç türü desteklenmiyor. Desteklenenler: {', '.join(_SUPPORTED_NEEDS)}.")
    return {"from": start, "to": end, "needs": list(checked)}


def closure_records(stations: Sequence[MetroStation], station_name: str, line: str | None = None) -> list[Any]:
    """Create in-memory fault rows for every selected platform of a station."""
    platforms = _resolve_platforms(station_name, stations)
    if line:
        wanted = _line_key(line)
        platforms = [platform for platform in platforms if _line_key(platform.line_name) == wanted]
    if not platforms:
        raise LookupError(station_name)
    return [
        SimpleNamespace(
            equipment_type="elevator",
            station_id=platform.station_id,
            station_name=platform.name,
            line_name=platform.line_name,
            status_class="fault",
            code=SCENARIO_MARK,
            description="Senaryo: varsayımsal kapanış",
            outage_id=f"{SCENARIO_MARK}:{platform.station_id}:{_line_key(platform.line_name)}",
        )
        for platform in platforms
    ]


def closure_info(stations: Sequence[MetroStation], station_name: str, line: str | None, snapshot: Any) -> dict[str, Any]:
    platforms = _resolve_platforms(station_name, stations)
    if line:
        wanted = _line_key(line)
        platforms = [platform for platform in platforms if _line_key(platform.line_name) == wanted]
    if not platforms:
        raise LookupError(station_name)
    faulty = any(
        record.equipment_type == "elevator" and any(_record_matches_platform(record, platform) for platform in platforms)
        for record in snapshot.records
    )
    counts = [platform.lifts for platform in platforms]
    lift_count = None if any(count is None for count in counts) else sum(count or 0 for count in counts)
    return {
        "station": platforms[0].name or station_name,
        "lines": sorted({p.line_name for p in platforms if p.line_name}),
        "lift_count": lift_count,
        "already_faulty": faulty,
        "no_lift_record": any(count in (None, 0) for count in counts),
        "hypothetical": True,
    }


def lift_status_now(platforms: Sequence[MetroStation], records: Sequence[Any]) -> str:
    faulty = any(
        record.equipment_type == "elevator" and any(_record_matches_platform(record, platform) for platform in platforms)
        for record in records
    )
    if faulty:
        return "out_of_service"
    if any(platform.lifts is None for platform in platforms) or not any(platform.lifts for platform in platforms):
        return "unknown"
    return "working"


def _unverified(result: Mapping[str, Any]) -> bool:
    uncertainty = set(result.get("uncertainty") or ())
    reason = str(result.get("reason") or "").casefold()
    return bool(uncertainty & _UNVERIFIED_CODES) or any(
        fragment in reason
        for fragment in (
            "doğrulanamadı",
            "eşleşmedi",
            "istasyon bulunamadı",
            "metro istasyon verisi okunamadı",
            "bağlantı bulunamadı",
            "raylı yol yok",
        )
    )


def _route_summary(result: Mapping[str, Any], *, alternative: Any = None) -> dict[str, Any]:
    return {
        "available": result.get("available"),
        "extra_minutes": result.get("extra_minutes"),
        "reason": result.get("reason"),
        "alternative": alternative,
    }


def _classify(before: Mapping[str, Any], after: Mapping[str, Any], closed_station: str) -> dict[str, Any]:
    """Compare planner data without treating an unverifiable route as unaffected."""
    if _unverified(before):
        effect = "unverified"
        alternative = None
        added = None
    elif not before.get("available"):
        effect = "already_unavailable"
        alternative = None
        added = None
    elif not after.get("available"):
        effect = "blocked"
        alternative = None
        added = None
    else:
        used = after.get("alternatives_used") or []
        picked = next((item for item in used if fold_tr(item.get("avoided_station")) == fold_tr(closed_station)), None)
        if picked:
            effect = "detour"
            alternative = {key: picked.get(key) for key in ("station", "line", "reason")}
            left, right = before.get("extra_minutes"), after.get("extra_minutes")
            added = max(0, right - left) if isinstance(left, (int, float)) and isinstance(right, (int, float)) else None
        else:
            effect = "not_affected"
            alternative = None
            added = None
    after_alternatives = alternative
    before_view = _route_summary(before)
    after_view = _route_summary(after, alternative=after_alternatives)
    return {
        "effect": effect,
        "before": before_view,
        "after": after_view,
        "added_minutes": added,
        "uncertainty": list(dict.fromkeys(after.get("uncertainty") or [])),
    }


classify = _classify


def suppress(count: int) -> int | str:
    if count == 0:
        return 0
    return "lt3" if count < MIN_CELL else count


def _summarize(rows: Sequence[Mapping[str, Any]], saved: Mapping[str, Any] | None = None) -> dict[str, Any]:
    counts = {effect: 0 for effect in EFFECTS}
    for row in rows:
        if row.get("effect") in counts:
            counts[row["effect"]] += 1
    counts["affected"] = counts["blocked"] + counts["detour"]
    counts["total"] = len(rows)
    saved_result: dict[str, Any] | None = None
    if saved is not None:
        saved_result = dict(saved)
        if saved.get("status") == "ok":
            raw_considered = saved.get("considered")
            if raw_considered is not None:
                considered = int(raw_considered)
                saved_result["considered"] = suppress(considered)
                effects = saved.get("effects") or {}
                if considered < MIN_CELL:
                    saved_result["effects"] = {key: "lt3" for key in EFFECTS}
                else:
                    saved_result["effects"] = {key: suppress(int(effects.get(key) or 0)) for key in EFFECTS}
    return {"counts": counts, "saved": saved_result}


summarize = _summarize
