"""Read Metro equipment snapshots for the citizen's seven-day history card.

This reader stays in the console composition root: the layer rules keep the publishable
``ibb_mcp`` package independent of the application lake and restrict the console to its facade.
The local G-9 format is gzip NDJSON under Hive-style partitions.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import logging
import os
import pathlib
from collections.abc import Iterable
from statistics import fmean
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from ibb_mcp.text import fold_tr, squash_punctuation
from nabiz.console.cards import card, display_text, number_tr, provenance_view, unknown_provenance
from nabiz.console.operator import port_problem

EQUIPMENT_HISTORY_SOURCE = "metro_equipment_snapshot"
HISTORY_WINDOW_DAYS = 7
FAULT_STATUSES = frozenset({"fault", "revision", "not_operated"})
STATUS_TEXT = {
    "fault": "arızalı",
    "revision": "revizyonda",
    "not_operated": "hizmet dışı",
    "unknown": "bilinmiyor",
}
log = logging.getLogger("nabiz.console.history")
history_routes = APIRouter()


def _utc(value: dt.datetime) -> dt.datetime:
    """Normalize stored and supplied timestamps to aware UTC."""
    return (value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value).astimezone(dt.UTC)


def _parse_timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _utc(dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def _station_key(value: str | None) -> str:
    return squash_punctuation(fold_tr(value))


def _lake_root() -> pathlib.Path:
    return pathlib.Path(os.getenv("NABIZ_LAKE_DIR", "data/lake")).expanduser()


def read_equipment_snapshots(lake_root: pathlib.Path | None = None) -> list[dict[str, Any]]:
    """Read every G-9 gzip NDJSON partition in deterministic path order.

    Delta and Blob backends are outside this local file reader; each line follows G-9's
    flat ``snapshot_ts_utc`` / ``has_record`` equipment row contract.
    """
    root = lake_root if lake_root is not None else _lake_root()
    rows: list[dict[str, Any]] = []
    source_root = root / EQUIPMENT_HISTORY_SOURCE
    if not source_root.is_dir():
        return rows
    for path in sorted(source_root.rglob("*.ndjson.gz")):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                for line in stream:
                    if line.strip():
                        value = json.loads(line)
                        if isinstance(value, dict):
                            rows.append(value)
        except (OSError, EOFError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            log.warning("equipment history partition unreadable: %s", type(exc).__name__)
    return rows


def _matches(row: dict[str, Any], station: str | None, equipment_code: str | None) -> bool:
    if station and _station_key(str(row.get("station_name") or "")) != _station_key(station):
        return False
    return not equipment_code or row.get("equipment_code") == equipment_code


def _dated_rows(rows: Iterable[dict[str, Any]]) -> list[tuple[dt.datetime, dict[str, Any]]]:
    dated: list[tuple[dt.datetime, dict[str, Any]]] = []
    for row in rows:
        stamp = _parse_timestamp(row.get("snapshot_ts_utc"))
        if stamp is not None:
            dated.append((stamp, row))
    return dated


def _fault_durations(rows: list[tuple[dt.datetime, dict[str, Any]]]) -> list[float]:
    by_outage: dict[str, set[dt.datetime]] = {}
    for stamp, row in rows:
        if row.get("has_record") is not True or row.get("status_class") not in FAULT_STATUSES:
            continue
        outage_id = row.get("outage_id")
        if isinstance(outage_id, str) and outage_id:
            by_outage.setdefault(outage_id, set()).add(stamp)
    return [
        (max(stamps) - min(stamps)).total_seconds() / 3600
        for stamps in by_outage.values()
        if stamps
    ]


def station_history(
    rows: list[dict[str, Any]],
    *,
    station: str | None = None,
    equipment_code: str | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Summarize one station or equipment code using distinct faulty snapshots in seven days."""
    matched = [row for row in rows if _matches(row, station, equipment_code)]
    dated = _dated_rows(matched)
    if not matched:
        return {
            "station": station,
            "equipment_code": equipment_code,
            "fault_count": None,
            "avg_duration_hours": None,
            "current_status": "unknown",
            "data_since": None,
            "observed_at": None,
        }

    current_time = _utc(now or dt.datetime.now(dt.UTC))
    start = current_time - dt.timedelta(days=HISTORY_WINDOW_DAYS)
    recent = [(stamp, row) for stamp, row in dated if start <= stamp <= current_time]
    faulty = [
        (stamp, row)
        for stamp, row in recent
        if row.get("has_record") is True and row.get("status_class") in FAULT_STATUSES
    ]
    durations = _fault_durations(faulty)
    newest = max(dated, key=lambda item: item[0]) if dated else None
    recent_newest = max(recent, key=lambda item: item[0]) if recent else None
    first_station = next((row.get("station_name") for row in matched if row.get("station_name")), station)
    first_code = next((row.get("equipment_code") for row in matched if row.get("equipment_code")), equipment_code)
    return {
        "station": first_station,
        "equipment_code": first_code,
        "fault_count": len({stamp for stamp, _ in faulty}),
        "avg_duration_hours": fmean(durations) if durations else None,
        "current_status": (recent_newest[1].get("status_class") or "unknown") if recent_newest else "unknown",
        "data_since": min((stamp for stamp, _ in dated), default=None),
        "observed_at": newest[0] if newest else None,
    }


def _collection_start(rows: list[dict[str, Any]], now: dt.datetime) -> str:
    stamps = [stamp for stamp, _ in _dated_rows(rows)]
    if stamps:
        return min(stamps).date().isoformat()
    return now.astimezone(ZoneInfo("Europe/Istanbul")).date().isoformat()


def _history_text(history: dict[str, Any], now: dt.datetime, all_rows: list[dict[str, Any]]) -> str:
    count = history["fault_count"]
    if count is None:
        return f"Tarihçe henüz yok (toplama başladı: {_collection_start(all_rows, now)})."
    status = STATUS_TEXT.get(history["current_status"], "bilinmiyor")
    if count == 0:
        return f"Bu ekipman son 7 günde 0 kez arızalı görüldü. Şu an: {status}."
    average = history["avg_duration_hours"]
    if average is None:
        return f"Bu ekipman son 7 günde {count} kez arızalı görüldü, ortalama süre henüz hesaplanamadı. Şu an: {status}."
    return f"Bu ekipman son 7 günde {count} kez arızalı görüldü, ortalama {number_tr(average)} saat sürdü. Şu an: {status}."


class EquipmentHistoryService:
    """Serve the console from one local snapshot read per request."""

    def __init__(self, lake_root: pathlib.Path | None = None) -> None:
        self.rows = read_equipment_snapshots(lake_root)

    def history(
        self,
        *,
        station: str | None = None,
        equipment_code: str | None = None,
        now: dt.datetime | None = None,
    ) -> dict[str, Any]:
        current_time = _utc(now or dt.datetime.now(dt.UTC))
        result = station_history(self.rows, station=station, equipment_code=equipment_code, now=current_time)
        available = result["fault_count"] is not None
        if available and result["observed_at"] is not None:
            source_provenance = provenance_view(
                SimpleNamespace(
                    source=EQUIPMENT_HISTORY_SOURCE,
                    source_url="",
                    observed_at=result["observed_at"],
                    reported_at=result["observed_at"],
                    age_seconds=max(0.0, (current_time - result["observed_at"]).total_seconds()),
                ),
                offline=True,
                mode="recorded",
            )
        else:
            source_provenance = unknown_provenance(EQUIPMENT_HISTORY_SOURCE)
        body = display_text(_history_text(result, current_time, self.rows))
        station_value = result["station"] or station
        code_value = result["equipment_code"] or equipment_code
        if not available or result["current_status"] == "unknown":
            status = "unverified"
        else:
            status = "warning" if result["current_status"] in FAULT_STATUSES else "ok"
        view = card(
            "equipment_history",
            str(station_value or code_value or "unknown"),
            title="Arıza geçmişi",
            body=body,
            status=status,
            provenance=source_provenance,
        )
        view.update(
            station=station_value,
            equipment_code=code_value,
            fault_count_7d=result["fault_count"],
            avg_duration_hours=result["avg_duration_hours"],
            current_status=result["current_status"],
            data_since=result["data_since"].isoformat() if result["data_since"] else None,
            text=body,
        )
        return view


@history_routes.get("/api/equipment/history")
async def equipment_history(
    station: str = Query("", max_length=80),
    equipment_id: str = Query("", max_length=40),
) -> Any:
    wanted_station = station.strip() or None
    wanted_code = equipment_id.strip() or None
    if wanted_station is None and wanted_code is None:
        return port_problem(400, "bad_request", "Bir istasyon adı ya da ekipman kodu gerekli.")
    service = EquipmentHistoryService()
    return service.history(station=wanted_station, equipment_code=wanted_code)
