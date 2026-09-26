"""Read recent citizen lift reports by station for the simulated operator console."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from fastapi import APIRouter, Request, Response

from ibb_mcp.text import fold_tr, squash_punctuation
from nabiz.console.map_layers_api import LIFT_RECORD_TEXT, offline_flag, stations_collection
from nabiz.console.operator import port_problem
from nabiz.console.report_api import KIND_TR_TEXT, REPORT_KIND, SUPPORT_ENTRY, report_engine
from nexus_core import NexusEngine
from nexus_core.signals import system_clock

log = logging.getLogger("nabiz.console.report_map")

# These are design parameters, not measurements.
REPORT_MAP_WINDOWS = {"30m": dt.timedelta(minutes=30), "24h": dt.timedelta(hours=24)}
REPORT_MAP_NOTE = "Vatandaş bildirimi, doğrulanmamış. Simüle operatör."
REPORT_MAP_MAX_ROWS = 60

report_map_routes = APIRouter()


def _within_window(at: dt.datetime, now: dt.datetime, window: dt.timedelta) -> bool:
    return now - window <= at <= now


def _count_report(
    counts: dict[str, dict[str, Any]],
    key: str,
    station: str,
    signal_id: str,
    report_kind: str,
    at: dt.datetime,
) -> None:
    row = counts.setdefault(
        key,
        {
            "station": station,
            "reports": 0,
            "by_kind": {kind: 0 for kind in KIND_TR_TEXT},
            "cards": 0,
            "open_signal_id": None,
            "last_at": at,
            "_card_ids": set(),
        },
    )
    row["reports"] += 1
    if report_kind in row["by_kind"]:
        row["by_kind"][report_kind] += 1
    row["_card_ids"].add(signal_id)
    if at >= row["last_at"]:
        row["station"] = station
        row["last_at"] = at


def _report_identity(state: Any) -> tuple[str, str, str] | None:
    if state.signal.kind != REPORT_KIND:
        return None
    payload = state.signal.payload
    station = payload.get("station")
    report_kind = payload.get("report_kind")
    if not isinstance(station, str) or report_kind not in KIND_TR_TEXT:
        return None
    return squash_punctuation(fold_tr(station)), station, report_kind


def _remember_open_card(
    open_cards: dict[str, tuple[dt.datetime, str]], key: str, at: dt.datetime, signal_id: str
) -> None:
    newest = open_cards.get(key)
    if newest is None or at > newest[0]:
        open_cards[key] = (at, signal_id)


def report_map_counts(engine: NexusEngine, now: dt.datetime, window: dt.timedelta) -> dict[str, dict[str, Any]]:
    """Count first reports and folded supports from one state and one ledger read."""
    states = engine.states()
    counts: dict[str, dict[str, Any]] = {}
    station_by_signal: dict[str, tuple[str, str, str]] = {}
    open_cards: dict[str, tuple[dt.datetime, str]] = {}

    for signal_id, state in states.items():
        identity = _report_identity(state)
        if identity is None:
            continue
        key, station, report_kind = identity
        station_by_signal[signal_id] = (key, station, report_kind)
        if state.status in {"awaiting_approval", "deferred"}:
            _remember_open_card(open_cards, key, state.received_at, signal_id)
        if _within_window(state.received_at, now, window):
            _count_report(counts, key, station, signal_id, report_kind, state.received_at)

    for entry in engine.ledger.entries(kinds=[SUPPORT_ENTRY]):
        if entry.signal_id is None or entry.signal_id not in station_by_signal:
            continue
        if not _within_window(entry.at, now, window):
            continue
        key, station, report_kind = station_by_signal[entry.signal_id]
        _count_report(counts, key, station, entry.signal_id, report_kind, entry.at)

    for key, row in counts.items():
        row["cards"] = len(row.pop("_card_ids"))
        row["open_signal_id"] = open_cards.get(key, (None, None))[1]
    return counts


def report_map_rows(
    counts: Mapping[str, Mapping[str, Any]],
    features: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Place station counts on gazetteer features and mark evidence-backed conflicts."""
    feature_by_key: dict[str, Mapping[str, Any]] = {}
    for feature in features:
        properties = feature.get("properties")
        name = properties.get("name") if isinstance(properties, Mapping) else None
        if isinstance(name, str):
            feature_by_key.setdefault(squash_punctuation(fold_tr(name)), feature)

    placed: list[dict[str, Any]] = []
    unplaced: list[dict[str, Any]] = []
    rows = sorted(
        counts.items(),
        key=lambda item: (-int(item[1]["reports"]), fold_tr(str(item[1]["station"])), str(item[1]["station"])),
    )[:REPORT_MAP_MAX_ROWS]
    for key, row in rows:
        common = {
            "station": str(row["station"]),
            "reports": int(row["reports"]),
            "by_kind": dict(row["by_kind"]),
            "cards": int(row["cards"]),
            "open_signal_id": row["open_signal_id"],
        }
        feature = feature_by_key.get(key)
        if feature is None:
            unplaced.append(common)
            continue

        properties = feature["properties"]
        geometry = feature["geometry"]
        lift_record = str(properties["lift_record"])
        kinds = common["by_kind"]
        conflict = (
            kinds["not_working"] > 0 and lift_record == "no_fault_record"
        ) or (
            kinds["data_wrong"] > 0 and lift_record == "recorded_fault"
        )
        if lift_record == "unread":
            record_text = "İBB kaydı okunamadı; karşılaştırılamadı"
        elif kinds["not_working"] > 0 and lift_record == "no_fault_record":
            record_text = "İBB kaydında arıza yok"
        elif kinds["data_wrong"] > 0 and lift_record == "recorded_fault":
            record_text = "İBB kaydında arıza var"
        else:
            record_text = LIFT_RECORD_TEXT[lift_record]
        coordinates = geometry["coordinates"]
        placed.append(
            {
                **common,
                "lat": float(coordinates[1]),
                "lon": float(coordinates[0]),
                "lift_record": lift_record,
                "conflict": conflict,
                "record_text": record_text,
            }
        )
    return placed, unplaced


@report_map_routes.get("/api/console/report-map", response_model=None)
async def report_map(request: Request, window: Literal["30m", "24h"] = "30m") -> Response | dict[str, Any]:
    """Return recent report counts at station points, behind the existing console gate."""
    engine = report_engine(request)
    nabiz = request.app.state.nabiz
    if not isinstance(engine, NexusEngine) or nabiz is None:
        return port_problem(503, "not_wired", "Bildirim haritası şu an okunamıyor; karar çekirdeği bağlı değil.")

    now = getattr(request.app.state, "report_clock", system_clock)()
    counts = await asyncio.to_thread(report_map_counts, engine, now, REPORT_MAP_WINDOWS[window])
    collection = await stations_collection(nabiz, offline=offline_flag(request))
    placed, unplaced = report_map_rows(counts, collection["features"])
    log.info("report map window=%s rows=%d", window, len(placed) + len(unplaced))
    return {
        "window": window,
        "window_min": int(REPORT_MAP_WINDOWS[window].total_seconds() // 60),
        "note": REPORT_MAP_NOTE,
        "total_reports": sum(int(row["reports"]) for row in counts.values()),
        "stations": placed,
        "unplaced": unplaced,
        "provenance": {"stations": collection["provenance"], "lift": collection["lift_provenance"]},
    }
