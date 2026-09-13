#!/usr/bin/env python3
"""Measure how wrong the bus arrival estimates actually are.

The README promises a *measured* ETA error rather than a plausible one, and this is the
script that produces it. Nothing here calls İBB: it reads two series the collector already
wrote and joins them.

**Predictions** come from ``eta_predictions``: at time ``T`` we said vehicle ``D`` would
reach stop ``S`` in ``N`` minutes, by method ``M``.

**Observations** come from ``iett_line_snapshot``: every tick records which stop each
vehicle is nearest to. The first tick at which vehicle ``D`` reports stop ``S`` is the tick
at which it arrived. That is the only ground truth available — İETT publishes no arrival
feed — and it is coarse in a way worth stating plainly:

* The arrival is located to within one collection interval (three minutes), so a perfect
  predictor would still show a mean absolute error of roughly half an interval.
* A vehicle that passes a stop between two ticks is never observed there at all, and its
  predictions stay unresolved rather than being scored as wrong.
* ``yakinDurakKodu`` is *nearest* stop, not *stopped at*: a bus in traffic beside a stop
  reports it. This inflates measured arrivals slightly earlier than the real ones.

All three limitations are reported alongside the number, because an ETA error quoted
without its measurement window is not a measurement.

Usage::

    .venv/bin/python scripts/eta_report.py
    .venv/bin/python scripts/eta_report.py --json eval/results/eta.json
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import gzip
import json
import os
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

#: A prediction is scored only if the vehicle is later seen at the stop within this
#: window. Beyond it the pairing is more likely to be a different trip of the same
#: vehicle than the journey we predicted.
MATCH_HORIZON = dt.timedelta(minutes=90)

#: The collector's watched-line cadence. Half of it is the floor on measurable accuracy.
TICK_INTERVAL_MINUTES = 3.0


def lake_dir() -> pathlib.Path:
    return pathlib.Path(os.getenv("NABIZ_LAKE_DIR", ROOT / "data" / "lake"))


def read_source(source: str) -> list[dict]:
    directory = lake_dir() / source
    if not directory.exists():
        return []
    rows: list[dict] = []
    for path in sorted(directory.rglob("*.ndjson.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            rows.extend(json.loads(line) for line in fh if line.strip())
    return rows


def parse_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sequences() -> dict:
    """Route stop orders, used to tell a real approach from a layover. Optional."""
    try:
        from ibb_mcp.config import Settings
        from ibb_mcp.gtfs import load_stop_sequences

        return load_stop_sequences(Settings.from_env())
    except Exception:  # noqa: BLE001 - the report still works without them, just looser
        return {}


def observed_arrivals(
    snapshots: list[dict],
    *,
    require_approach: bool = True,
) -> dict[tuple[str, str, str], list[dt.datetime]]:
    """When each vehicle actually arrived at each stop, having travelled to it.

    Consecutive ticks reporting the same stop collapse into one arrival, and a later
    return is a second one.

    ``require_approach`` is the part that matters. Without it, *any* first sighting at a
    stop counts, which quietly includes two things that are not arrivals:

    * a bus resting at a terminus, still reporting it as nearest for the whole layover,
    * a bus reaching the stop on the opposite direction's run.

    Both inflate the measured travel time. With the route stop order available, an arrival
    is recorded only when the vehicle's previous sighting was at an *earlier* stop on the
    same route — that is, it moved forward into this one. When no sequence is known for a
    route the check cannot be applied and the sighting is kept, so the report degrades
    rather than silently dropping data.
    """
    sequences = _sequences() if require_approach else {}

    by_vehicle: dict[tuple[str, str], list[tuple[dt.datetime, str, str | None]]] = collections.defaultdict(list)
    for row in snapshots:
        stamp = parse_ts(row.get("snapshot_ts_utc"))
        stop = row.get("nearest_stop_code")
        if stamp is None or not stop:
            continue
        by_vehicle[(row["line_code"], row["door_no"])].append((stamp, stop, row.get("route_code")))

    arrivals: dict[tuple[str, str, str], list[dt.datetime]] = collections.defaultdict(list)
    for (line, door), entries in by_vehicle.items():
        entries.sort()
        previous: tuple[str, str | None] | None = None
        for stamp, stop, route in entries:
            if previous is None or previous[0] != stop:
                approached = True
                if require_approach and previous is not None:
                    sequence = sequences.get(route or "") or sequences.get(previous[1] or "")
                    if sequence is not None:
                        here = sequence.position_of(stop)
                        before = sequence.position_of(previous[0])
                        # Both known and moving forward, or the check does not apply.
                        approached = here is None or before is None or before < here
                if approached:
                    arrivals[(line, door, stop)].append(stamp)
            previous = (stop, route)
    return arrivals


def score(predictions: list[dict], arrivals: dict[tuple[str, str, str], list[dt.datetime]]) -> dict:
    """Pair each prediction with the next observed arrival and compute the error."""
    scored: list[dict] = []
    unresolved = 0

    for prediction in predictions:
        made_at = parse_ts(prediction.get("predicted_at_utc"))
        minutes = prediction.get("eta_minutes")
        if made_at is None or minutes is None:
            continue
        key = (prediction["line_code"], prediction["door_no"], prediction["stop_code"])
        candidates = [t for t in arrivals.get(key, []) if made_at <= t <= made_at + MATCH_HORIZON]
        if not candidates:
            unresolved += 1
            continue
        actual = min(candidates)
        predicted_for = made_at + dt.timedelta(minutes=float(minutes))
        error = (predicted_for - actual).total_seconds() / 60.0
        scored.append(
            {
                "line_code": prediction["line_code"],
                "stop_code": prediction["stop_code"],
                "door_no": prediction["door_no"],
                "method": prediction.get("method"),
                "confidence": prediction.get("confidence"),
                "predicted_minutes": float(minutes),
                "actual_minutes": (actual - made_at).total_seconds() / 60.0,
                "error_minutes": error,
            }
        )

    def summarise(items: list[dict]) -> dict:
        if not items:
            return {"n": 0}
        errors = [abs(item["error_minutes"]) for item in items]
        signed = [item["error_minutes"] for item in items]
        return {
            "n": len(items),
            "mae_minutes": round(statistics.fmean(errors), 2),
            "median_abs_error_minutes": round(statistics.median(errors), 2),
            "bias_minutes": round(statistics.fmean(signed), 2),
            "p90_abs_error_minutes": round(sorted(errors)[int(0.9 * (len(errors) - 1))], 2),
            "within_2_min_pct": round(100.0 * sum(e <= 2 for e in errors) / len(errors), 1),
            "within_5_min_pct": round(100.0 * sum(e <= 5 for e in errors) / len(errors), 1),
        }

    by_method: dict[str, list[dict]] = collections.defaultdict(list)
    for item in scored:
        by_method[item["method"] or "unknown"].append(item)

    return {
        "predictions_total": len(predictions),
        "predictions_scored": len(scored),
        "predictions_unresolved": unresolved,
        "resolution_rate_pct": round(100.0 * len(scored) / len(predictions), 1) if predictions else 0.0,
        "overall": summarise(scored),
        "by_method": {method: summarise(items) for method, items in sorted(by_method.items())},
        "measurement_floor_minutes": TICK_INTERVAL_MINUTES / 2,
    }


def render(report: dict) -> str:
    lines = ["# ETA accuracy", ""]
    total, done = report["predictions_total"], report["predictions_scored"]
    if not total:
        return "No ETA predictions collected yet. Run scripts/collect_forever.py first."
    lines += [
        f"{done} of {total} predictions resolved ({report['resolution_rate_pct']}%); "
        f"{report['predictions_unresolved']} vehicles were never observed at the target stop "
        f"within {int(MATCH_HORIZON.total_seconds() // 60)} minutes.",
        "",
    ]
    if not done:
        lines.append("Nothing scored yet — the collector needs to run long enough for a watched")
        lines.append("vehicle to actually reach a target stop.")
        return "\n".join(lines)

    overall = report["overall"]
    lines += [
        "| Metric | Value |",
        "|---|---|",
        f"| Mean absolute error | {overall['mae_minutes']} min |",
        f"| Median absolute error | {overall['median_abs_error_minutes']} min |",
        f"| Bias (positive = predicted late) | {overall['bias_minutes']} min |",
        f"| p90 absolute error | {overall['p90_abs_error_minutes']} min |",
        f"| Within 2 minutes | {overall['within_2_min_pct']}% |",
        f"| Within 5 minutes | {overall['within_5_min_pct']}% |",
        f"| Sample size | {overall['n']} |",
        "",
        "## By method",
        "",
        "| Method | n | MAE (min) | Within 2 min | Within 5 min |",
        "|---|---|---|---|---|",
    ]
    for method, stats in report["by_method"].items():
        if not stats["n"]:
            continue
        lines.append(
            f"| `{method}` | {stats['n']} | {stats['mae_minutes']} | "
            f"{stats['within_2_min_pct']}% | {stats['within_5_min_pct']}% |"
        )
    lines += [
        "",
        "## How this is measured, and what limits it",
        "",
        f"- Arrivals are observed by the collector's watched-line tick, so they are located to "
        f"within {TICK_INTERVAL_MINUTES:.0f} minutes. A perfect predictor would still show a mean "
        f"absolute error near {report['measurement_floor_minutes']:.1f} minutes.",
        "- A vehicle that passes a stop between two ticks is never observed there; its predictions "
        "stay unresolved rather than being counted as wrong.",
        "- İETT reports the *nearest* stop, not a stop event, so a bus held in traffic beside a stop "
        "registers as arrived slightly early.",
        "",
        "İBB publishes no arrival feed, so this is the best ground truth available. The numbers above "
        "are honest about that rather than quoting a figure the method cannot support.",
    ]
    return "\n".join(lines)


def diagnose(predictions: list[dict], arrivals: dict[tuple[str, str, str], list[dt.datetime]]) -> str:
    """Ask whether the error is the model's fault or the measurement's.

    The engine predicts ``stops_away * seconds_per_stop``, a straight line through the
    origin. If that shape is right, the best-fitting rate should beat the current default.
    If instead the best fit needs a large constant term, the extra time is being added
    before the journey starts — which is a property of how arrivals are observed, not of
    traffic, and calibrating the rate against it would bake the artefact into the engine.

    On the first 115 resolved predictions (500T, one evening) both signals appeared at
    once: the best pure rate, 165 s/stop, does beat the untuned 120 s/stop default
    (12.8 min against 14.3), *and* adding a ~17 minute constant cuts the error further to
    8.8. So the rate is genuinely too low for an express line in evening traffic, and
    something is also inflating every observation by a fixed amount. Only the first is
    safe to act on; a 17-minute constant is not a bus leaving a stop.

    A caution learned the hard way here: bound the rate search wide. An earlier ad-hoc
    scan capped it at 90 s/stop, hit the boundary, and concluded no rate could help —
    the opposite of the truth.
    """
    samples: dict[str, list[tuple[int, float]]] = collections.defaultdict(list)
    for prediction in predictions:
        made_at = parse_ts(prediction.get("predicted_at_utc"))
        stops_away = prediction.get("stops_away")
        if made_at is None or not stops_away or stops_away <= 0:
            continue
        key = (prediction["line_code"], prediction["door_no"], prediction["stop_code"])
        candidates = [t for t in arrivals.get(key, []) if made_at <= t <= made_at + MATCH_HORIZON]
        if candidates:
            samples[prediction["line_code"]].append(
                (int(stops_away), (min(candidates) - made_at).total_seconds() / 60.0)
            )

    if not samples:
        return "No resolved stop-sequence predictions yet; nothing to diagnose."

    out = ["## Diagnosis: model error or measurement error?", ""]
    out += ["| Line | n | current 120 s/stop | best rate alone | best constant + rate |", "|---|---|---|---|---|"]
    verdicts: list[str] = []
    for line, data in sorted(samples.items()):
        current = statistics.fmean(abs(n * 2.0 - actual) for n, actual in data)
        best_rate = min(
            ((r, statistics.fmean(abs(n * r / 60 - actual) for n, actual in data)) for r in range(10, 900, 5)),
            key=lambda item: item[1],
        )
        best_pair = min(
            (
                (c / 2, r, statistics.fmean(abs(c / 2 + n * r / 60 - actual) for n, actual in data))
                for c in range(0, 60, 1)
                for r in range(10, 600, 10)
            ),
            key=lambda item: item[2],
        )
        out.append(
            f"| {line} | {len(data)} | {current:.1f} min | {best_rate[0]} s/stop -> {best_rate[1]:.1f} min | "
            f"{best_pair[0]:.1f} min + {best_pair[1]} s/stop -> {best_pair[2]:.1f} min |"
        )
        if best_pair[0] >= 5 and best_rate[1] >= current:
            verdicts.append(
                f"- **{line}: measurement, not model.** No per-stop rate beats the untuned default, and the "
                f"best fit needs a {best_pair[0]:.0f}-minute constant. Fix how arrivals are observed before "
                f"tuning the engine."
            )
        else:
            verdicts.append(f"- **{line}: the rate is tunable.** {best_rate[0]} s/stop would cut the error.")
    return "\n".join(out + ["", *verdicts])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", type=pathlib.Path, help="also write the raw report here")
    parser.add_argument("--diagnose", action="store_true", help="is the error the model's or the measurement's?")
    args = parser.parse_args(argv)

    predictions = read_source("eta_predictions")
    snapshots = read_source("iett_line_snapshot")
    arrivals = observed_arrivals(snapshots)
    report = score(predictions, arrivals)
    report["snapshot_rows"] = len(snapshots)

    text = render(report)
    if args.diagnose:
        text += "\n\n" + diagnose(predictions, arrivals)
    print(text)

    out = ROOT / "eval" / "results" / "eta.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\nwritten: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
