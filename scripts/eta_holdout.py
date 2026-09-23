#!/usr/bin/env python3
"""Score the calibrated arrival profile on predictions it was never fitted on.

``scripts/calibrate_eta.py`` reports how well its fitted rates explain the rows they were
fitted on. That is an in-sample fit, and it says nothing about the next stop or the next
evening. This script answers the question that matters: take every stop-sequence prediction
made *after* ``data/reference/eta_profile.json`` was written, re-time it with the rate the
``iett_next_arrivals`` tool would have chosen, and score both the logged estimate and the
re-timed one against the same observed arrivals.

It is a replay rather than a live measurement, because the collector logs predictions at the
untuned 120 s/stop (``build_eta_predictions`` passes no ``speed_profile``). The pairing is
``eta_report.score``'s, so the numbers are comparable with ``eval/results/eta.md``.

A prediction is scored only when collector ticks cover its whole 90-minute match window
with no gap over ``MAX_TICK_GAP``: near the end of a collection run only the fast journeys
have finished, and scoring those would flatter whichever rate is lower.

Nothing here calls İBB; it reads ``data/lake`` only.

Usage::

    NABIZ_OFFLINE=1 .venv/bin/python scripts/eta_holdout.py
"""

from __future__ import annotations

import bisect
import collections
import datetime as dt
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from eta_report import MATCH_HORIZON, observed_arrivals, parse_ts, read_source  # noqa: E402

from ibb_mcp.config import display_path  # noqa: E402
from ibb_mcp.eta_profile import EtaProfile, bucket_for, profile_path  # noqa: E402

#: The watched-line tick is three minutes; a longer silence means the collector was down.
MAX_TICK_GAP = dt.timedelta(minutes=10)


def window_is_covered(made_at: dt.datetime, ticks: list[dt.datetime]) -> bool:
    """True when the collector was watching for the whole match window after ``made_at``."""
    end = made_at + MATCH_HORIZON
    if not ticks or ticks[-1] < end:
        return False
    previous = made_at
    for stamp in ticks[bisect.bisect_left(ticks, made_at) :]:
        if stamp > end:
            break
        if stamp - previous > MAX_TICK_GAP:
            return False
        previous = stamp
    return end - previous <= MAX_TICK_GAP


def summarise(errors: list[float]) -> str:
    absolute = [abs(error) for error in errors]
    return f"{statistics.fmean(absolute):.2f} min (bias {statistics.fmean(errors):+.1f})"


def main() -> int:
    raw = json.loads(profile_path().read_text(encoding="utf-8"))
    profile = EtaProfile.from_dict(raw, source=display_path(profile_path()))
    fitted_at = parse_ts(raw.get("generated_at"))
    if fitted_at is None:
        print("The profile has no generated_at; cannot tell held-out rows from training rows.")
        return 1

    predictions = read_source("eta_predictions")
    snapshots = read_source("iett_line_snapshot")
    arrivals = observed_arrivals(snapshots)
    ticks = sorted({stamp for row in snapshots if (stamp := parse_ts(row.get("snapshot_ts_utc")))})

    groups: dict[str, dict[str, list[float]]] = collections.defaultdict(lambda: {"logged": [], "calibrated": []})
    counters = collections.Counter()
    for prediction in predictions:
        made_at = parse_ts(prediction.get("predicted_at_utc"))
        stops_away = prediction.get("stops_away")
        if made_at is None or made_at <= fitted_at or prediction.get("method") != "stop_sequence" or not stops_away:
            continue
        counters["held_out"] += 1
        if not window_is_covered(made_at, ticks):
            counters["window_not_covered"] += 1
            continue
        key = (prediction["line_code"], prediction["door_no"], prediction["stop_code"])
        candidates = [t for t in arrivals.get(key, []) if made_at <= t <= made_at + MATCH_HORIZON]
        if not candidates:
            counters["unresolved"] += 1
            continue
        actual = (min(candidates) - made_at).total_seconds() / 60.0
        rate, provenance = profile.seconds_per_stop_for(prediction["line_code"], made_at)
        # The same arithmetic and rounding as eta._estimate_one, so this is the tool's number.
        calibrated = round(int(stops_away) * rate / 60.0, 1)
        label = f"{prediction['line_code']} {bucket_for(made_at)} ({rate:.0f} s/stop, {provenance.split(',')[0]})"
        for group in ("All", label):
            groups[group]["logged"].append(float(prediction["eta_minutes"]) - actual)
            groups[group]["calibrated"].append(calibrated - actual)
        counters["scored"] += 1

    print(f"Profile fitted at {fitted_at.isoformat()}; counts: {dict(counters)}\n")
    if not counters["scored"]:
        print("No held-out prediction has resolved yet.")
        return 0
    print("| Held-out predictions | n | Logged, 120 s/stop | Calibrated profile |")
    print("|---|---|---|---|")
    for group, errors in sorted(groups.items(), key=lambda item: (item[0] != "All", item[0])):
        print(f"| {group} | {len(errors['logged'])} | {summarise(errors['logged'])} | {summarise(errors['calibrated'])} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
