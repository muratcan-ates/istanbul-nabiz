"""The ETA prediction log: what we said about a bus, written down before it arrived.

The README's ETA error is *measured*, not self-reported, and this is the half of the
measurement that has to be taken live. Every watched-line tick predicts arrivals for a
fixed set of (line, stop) pairs and writes the predictions to ``eta_predictions``;
``scripts/eta_report.py`` later pairs each one with the tick at which that door number
actually reported the stop as its nearest (``iett_line_snapshot``) and reports the error.
Nothing extra is fetched: the prediction is computed from the positions the tick already
holds.

Until now this lived only in ``scripts/collect_forever.py``, which is why the Azure
Function — five timers, none of them for lines — could never feed the ETA claim. It is
here so that :mod:`nabiz.collector.job` can run it in the cloud. It is a **port, not a
redesign**: the watched lines, the targets, the engine inputs (no speed profile) and the
row shape are exactly the laptop's, so the series stays one series across the move and
the errors measured before and after it are comparable. ``tests/test_collector_job.py``
loads the laptop script read-only and fails if the two ever disagree. Changing what is
predicted — the calibrated per-line rates, say — is a separate decision that should be
made once, in both places, and noted in DECISIONS.md.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from ibb_mcp.config import Settings
from ibb_mcp.eta import EtaParams, estimate_arrivals
from ibb_mcp.gtfs import get_index, load_stop_sequences
from ibb_mcp.models import BusPosition, parse_ibb_datetime, utcnow
from nabiz.collector.snapshots import iso_utc

#: Lines watched for ETA ground truth. Long, busy and geographically spread, so the sample
#: covers both free-flowing and congested conditions. 500T is the verified reference
#: route (Şifa Sondurak <-> 4. Levent Metro, 64 stops).
WATCHED_LINES: tuple[str, ...] = ("500T", "34", "15F")

#: (line, stop_code) pairs predicted on every watched-line tick.
#:
#: All mid-route, and that is a correction rather than a preference: the laptop's first
#: run used 500T's terminus, where a bus on layover keeps reporting the terminus as its
#: nearest stop, so "arrival" absorbed the whole rest break (a 17-minute constant in the
#: fit). Terminus targets were dropped before any calibration was attempted. Positions sit
#: at roughly 30%, 50% and 70% along each route.
ETA_TARGETS: tuple[tuple[str, str], ...] = (
    ("500T", "205501"),  # ATATÜRK CADDESİ (~30% along)
    ("500T", "261262"),  # MEHMET ALİ TUNGA CAMİ (~50%)
    ("500T", "206042"),  # ANADOLU ADALET SARAYI (~70%)
    ("15F", "219532"),  # PAŞABAHÇE (~30%)
    ("15F", "260141"),  # ŞEHİT MURAT AKDEMİR (~50%)
    ("34", "900121"),  # DARÜLACEZE PERPA (~50%, metrobüs)
)

#: Arrivals kept per (line, stop) prediction — the laptop's value.
MAX_PREDICTIONS_PER_TARGET = 6


def rows_to_positions(rows: Sequence[dict[str, Any]]) -> list[BusPosition]:
    """Rebuild models from ``iett_line_snapshot`` rows so the ETA engine can run on them.

    The engine takes models, the lake holds rows; going through the rows rather than
    keeping the models from the read is deliberate — it means a prediction can be
    recomputed later from nothing but what the lake stored.
    """
    return [
        BusPosition(
            door_no=row["door_no"],
            lat=row.get("lat"),
            lon=row.get("lon"),
            line_code=row.get("line_code"),
            route_code=row.get("route_code"),
            direction=row.get("direction"),
            nearest_stop_code=row.get("nearest_stop_code"),
            reported_at=parse_ibb_datetime(row.get("ts_utc")),
        )
        for row in rows
    ]


def build_eta_predictions(
    rows: Sequence[dict[str, Any]],
    settings: Settings,
    *,
    now: dt.datetime | None = None,
) -> list[dict[str, Any]]:
    """Predict arrivals for every target in :data:`ETA_TARGETS` from one tick's rows.

    One row per (target, vehicle), stamped with the method that produced it, because
    ``eta_report.py`` reports the error per method. ``now`` exists for tests; in
    production it is the moment of the call, exactly as on the laptop.

    Raises ``FileNotFoundError`` when the GTFS reference is missing — the caller decides
    whether that is fatal. It is not silently turned into ``[]`` here, because an image
    built without ``data/reference/gtfs`` would then log no predictions forever while
    every tick reported success.

    Schema (stable, ``eta_predictions``):

    predicted_at_utc    str      when the prediction was made
    line_code           str      watched line
    stop_code           str      GTFS ``stop_code`` of the target
    stop_name           str?     as GTFS names it
    door_no             str      vehicle identity; never the plate
    eta_minutes         float?   the prediction
    method              str      ``stop_sequence`` / ``distance`` / ``schedule``
    confidence          str      ``high`` / ``medium`` / ``low``
    stops_away          int?     only for the ``stop_sequence`` method
    distance_km         float?   only for the ``distance`` method
    buses_considered    int?     vehicles the engine was given for that line
    """
    if not rows:
        return []
    index = get_index(settings)
    sequences = load_stop_sequences(settings)
    moment = now or utcnow()
    predictions: list[dict[str, Any]] = []

    by_line: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_line.setdefault(row["line_code"], []).append(row)

    for line_code, stop_code in ETA_TARGETS:
        target = index.lookup_stop(stop_code)
        line_rows = by_line.get(line_code.upper())
        if target is None or not line_rows:
            continue
        arrivals, diagnostics = estimate_arrivals(
            buses=rows_to_positions(line_rows),
            target=target,
            index=index,
            sequences=sequences,
            params=EtaParams(max_results=MAX_PREDICTIONS_PER_TARGET),
            now=moment,
        )
        for arrival in arrivals:
            predictions.append(
                {
                    "predicted_at_utc": iso_utc(moment),
                    "line_code": line_code.upper(),
                    "stop_code": stop_code,
                    "stop_name": target.name,
                    "door_no": arrival.door_no,
                    "eta_minutes": arrival.eta_minutes,
                    "method": arrival.method,
                    "confidence": arrival.confidence,
                    "stops_away": arrival.stops_away,
                    "distance_km": arrival.distance_km,
                    "buses_considered": diagnostics.get("buses_received"),
                }
            )
    return predictions
