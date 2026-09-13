#!/usr/bin/env python3
"""Fit the arrival estimator's seconds-per-stop rate to the arrivals we actually observed.

``scripts/eta_report.py`` measures how wrong the estimates are. This script does the next
step: it finds the rate that would have made them least wrong, per line and time-of-day
bucket, and writes ``data/reference/eta_profile.json`` for :mod:`ibb_mcp.eta_profile`.

The pairing is deliberately identical to ``eta_report.score``: a prediction is resolved by
the first observed arrival of that vehicle at that stop within ``MATCH_HORIZON``, where an
observation is the collector's tick catching the vehicle reporting that stop as its
nearest **having moved forward into it** (``observed_arrivals(require_approach=True)``, the
check that keeps a terminus layover from counting as a 40-minute journey). Using a
different pairing here would make the calibration and the published accuracy number
disagree, and the published number is the one in the README.

Only stop-sequence predictions take part — rows with ``stops_away >= 1``. The rate is
meaningless for the distance and schedule methods, which do not multiply by it.

What is fitted: the ``r`` minimising ``mean |stops_away * r/60 - actual_minutes|``, by grid
search over 30..600 s/stop in 5 s steps. MAE, not squared error, because a handful of
90-minute pairings (a vehicle matched to a later trip) would otherwise drag the rate up for
everyone. **Bound the search wide**: an earlier ad-hoc scan capped it at 90 s/stop, hit its
own ceiling and concluded no rate could beat the untuned default — the opposite of the
truth, which is that the default is roughly half the rate the road demands.

What is *not* fitted: the constant term. The best constant+rate pair on this sample is
11.5 min + 150 s/stop, but a constant that large is partly the measurement (3-minute tick,
nearest-stop semantics) and partly dwell time, and one day of data cannot separate them.
``EtaProfile.constant_seconds`` therefore stays 0.0 and is reported here for information
only. See the module docstring of ``ibb_mcp.eta_profile``.

Usage::

    .venv/bin/python scripts/calibrate_eta.py --dry-run    # print the table, write nothing
    .venv/bin/python scripts/calibrate_eta.py              # write data/reference/eta_profile.json
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from eta_report import MATCH_HORIZON, observed_arrivals, parse_ts, read_source  # noqa: E402

from ibb_mcp.eta_profile import (  # noqa: E402
    DEFAULT_SECONDS_PER_STOP,
    MAX_SECONDS_PER_STOP,
    MIN_SAMPLES,
    MIN_SECONDS_PER_STOP,
    Cell,
    EtaProfile,
    bucket_for,
    cell_key,
    profile_path,
    save_profile,
)
from ibb_mcp.models import ISTANBUL_TZ, utcnow  # noqa: E402

#: Grid step for the rate search. 5 s is well below the resolution the data supports
#: (a 3-minute observation tick), so a finer grid would only invent precision.
SEARCH_STEP = 5

#: One paired prediction: which line, the Istanbul local hour and bucket it was made in,
#: how many stops the bus still had to cover, and how many minutes it really took.
Sample = collections.namedtuple("Sample", "line_code hour bucket stops_away actual_minutes")


def collect_samples() -> tuple[list[Sample], dict[str, int]]:
    """Pair every stop-sequence prediction in the lake with the arrival that resolved it."""
    predictions = read_source("eta_predictions")
    snapshots = read_source("iett_line_snapshot")
    arrivals = observed_arrivals(snapshots)

    counters = {
        "predictions": len(predictions),
        "snapshots": len(snapshots),
        "stop_sequence": 0,
        "resolved": 0,
        "unresolved": 0,
    }
    samples: list[Sample] = []
    for prediction in predictions:
        made_at = parse_ts(prediction.get("predicted_at_utc"))
        stops_away = prediction.get("stops_away")
        if made_at is None or not stops_away or int(stops_away) <= 0:
            continue
        counters["stop_sequence"] += 1
        key = (prediction["line_code"], prediction["door_no"], prediction["stop_code"])
        candidates = [t for t in arrivals.get(key, []) if made_at <= t <= made_at + MATCH_HORIZON]
        if not candidates:
            counters["unresolved"] += 1
            continue
        counters["resolved"] += 1
        local = made_at.astimezone(ISTANBUL_TZ)
        samples.append(
            Sample(
                line_code=prediction["line_code"].strip().upper(),
                hour=local.hour,
                bucket=bucket_for(local),
                stops_away=int(stops_away),
                actual_minutes=(min(candidates) - made_at).total_seconds() / 60.0,
            )
        )
    return samples, counters


def errors_at(samples: list[Sample], seconds_per_stop: float) -> list[float]:
    """Signed error in minutes at a given rate; positive means we predicted too late."""
    return [s.stops_away * seconds_per_stop / 60.0 - s.actual_minutes for s in samples]


def mae_at(samples: list[Sample], seconds_per_stop: float) -> float:
    return statistics.fmean(abs(e) for e in errors_at(samples, seconds_per_stop))


def best_rate(samples: list[Sample]) -> tuple[float, float]:
    """Grid-search the rate with the lowest MAE. Returns ``(seconds_per_stop, mae)``."""
    grid = range(int(MIN_SECONDS_PER_STOP), int(MAX_SECONDS_PER_STOP) + 1, SEARCH_STEP)
    return min(((float(r), mae_at(samples, r)) for r in grid), key=lambda pair: pair[1])


def best_constant_and_rate(samples: list[Sample]) -> tuple[float, float, float]:
    """The constant+rate fit, reported but never written. See the module docstring."""
    best = (0.0, DEFAULT_SECONDS_PER_STOP, float("inf"))
    for half_minutes in range(0, 61):
        constant = half_minutes / 2.0
        for rate in range(int(MIN_SECONDS_PER_STOP), int(MAX_SECONDS_PER_STOP) + 1, 10):
            error = statistics.fmean(
                abs(constant + s.stops_away * rate / 60.0 - s.actual_minutes) for s in samples
            )
            if error < best[2]:
                best = (constant, float(rate), error)
    return best


def summarise(samples: list[Sample], rate_for) -> dict[str, float | int]:
    """MAE / median / bias / within-2 / within-5 for a rate rule applied per sample."""
    signed = [s.stops_away * rate_for(s) / 60.0 - s.actual_minutes for s in samples]
    absolute = [abs(e) for e in signed]
    return {
        "n": len(samples),
        "mae": statistics.fmean(absolute),
        "median": statistics.median(absolute),
        "bias": statistics.fmean(signed),
        "within_2": 100.0 * sum(e <= 2 for e in absolute) / len(absolute),
        "within_5": 100.0 * sum(e <= 5 for e in absolute) / len(absolute),
    }


def build_profile(samples: list[Sample], *, min_samples: int) -> EtaProfile:
    """Fit every (line, bucket) cell, every line, and the pooled global rate."""
    by_cell: dict[str, list[Sample]] = collections.defaultdict(list)
    by_line: dict[str, list[Sample]] = collections.defaultdict(list)
    for sample in samples:
        by_cell[cell_key(sample.line_code, sample.bucket)].append(sample)
        by_line[sample.line_code].append(sample)

    def fit(group: list[Sample]) -> Cell:
        rate, mae = best_rate(group)
        return Cell(
            seconds_per_stop=rate,
            samples=len(group),
            mae_minutes=mae,
            baseline_mae_minutes=mae_at(group, DEFAULT_SECONDS_PER_STOP),
        )

    return EtaProfile.from_cells(
        cells={key: fit(group) for key, group in by_cell.items()},
        lines={key: fit(group) for key, group in by_line.items()},
        overall=fit(samples) if samples else None,
        min_samples=min_samples,
        generated_at=utcnow().isoformat(),
        note=(
            "Fitted by scripts/calibrate_eta.py from eta_predictions x iett_line_snapshot. "
            "Rate only; constant_seconds is deliberately 0.0."
        ),
    )


def holdout_mae(samples: list[Sample], *, min_samples: int) -> dict[str, float]:
    """Leave-one-clock-hour-out: can a cell fitted on other hours predict an unseen hour?

    This is the check that decides four coarse buckets over per-hour cells, and the reason
    the bucket choice is not just taste. A random split cannot answer it — two predictions
    made in the same hour about the same buses in the same traffic are not independent
    draws, so a random fold leaks the answer into the training set and rewards ever-finer
    buckets. Holding out a whole hour does not.

    The 'per-hour' row is built exactly like the real profile with the bucket replaced by
    the clock hour, so the comparison is like for like, and it degrades to the per-line
    rate for the held-out hour precisely because that is what a per-hour profile does in
    production at an hour it has never seen.
    """
    hours = sorted({s.hour for s in samples})
    if len(hours) < 2:
        return {}
    scores: dict[str, list[float]] = collections.defaultdict(list)
    for held in hours:
        test = [s for s in samples if s.hour == held]
        train = [s for s in samples if s.hour != held]
        if not train:
            continue
        pooled = best_rate(train)[0]
        per_line = _fit_groups(train, lambda s: s.line_code, min_samples)
        per_bucket = _fit_groups(train, lambda s: cell_key(s.line_code, s.bucket), min_samples)
        per_hour = _fit_groups(train, lambda s: f"{s.line_code}|{s.hour:02d}", min_samples)
        for sample in test:
            line_rate = per_line.get(sample.line_code, pooled)
            chosen = {
                f"fixed {DEFAULT_SECONDS_PER_STOP:.0f}": DEFAULT_SECONDS_PER_STOP,
                "line only": line_rate,
                "line+bucket": per_bucket.get(cell_key(sample.line_code, sample.bucket), line_rate),
                "line+hour": per_hour.get(f"{sample.line_code}|{sample.hour:02d}", line_rate),
            }
            for name, rate in chosen.items():
                scores[name].append(abs(sample.stops_away * rate / 60.0 - sample.actual_minutes))
    return {name: statistics.fmean(values) for name, values in scores.items()}


def _fit_groups(samples: list[Sample], key_of, min_samples: int) -> dict[str, float]:
    """Best rate per group, dropping groups too thin to trust — the same rule as the profile."""
    groups: dict[str, list[Sample]] = collections.defaultdict(list)
    for sample in samples:
        groups[key_of(sample)].append(sample)
    return {key: best_rate(group)[0] for key, group in groups.items() if len(group) >= min_samples}


def render(
    samples: list[Sample],
    counters: dict[str, int],
    profile: EtaProfile,
    *,
    min_samples: int,
) -> str:
    """The before/after table, per cell, with n. Nothing here is rounded into a claim."""
    lines = ["# ETA calibration", ""]
    if not samples:
        return (
            "No resolved stop-sequence predictions in the lake. Nothing to calibrate.\n"
            "Run scripts/collect_forever.py until a watched vehicle reaches a target stop."
        )

    lines += [
        f"{counters['resolved']} of {counters['stop_sequence']} stop-sequence predictions resolved "
        f"({counters['unresolved']} unresolved) out of {counters['predictions']} predictions and "
        f"{counters['snapshots']} position snapshots.",
        "",
        f"Baseline: the engine's current fixed {DEFAULT_SECONDS_PER_STOP:.0f} s/stop.",
        f"After: the profile's fallback chain (line+bucket -> line -> global -> {DEFAULT_SECONDS_PER_STOP:.0f}).",
        "",
    ]

    def row(label: str, group: list[Sample], rate_for, rate_label: str) -> str:
        before = summarise(group, lambda _s: DEFAULT_SECONDS_PER_STOP)
        after = summarise(group, rate_for)
        return (
            f"| {label} | {before['n']} | {rate_label} | "
            f"{before['mae']:.1f} -> {after['mae']:.1f} | "
            f"{before['median']:.1f} -> {after['median']:.1f} | "
            f"{before['bias']:+.1f} -> {after['bias']:+.1f} | "
            f"{before['within_2']:.1f}% -> {after['within_2']:.1f}% | "
            f"{before['within_5']:.1f}% -> {after['within_5']:.1f}% |"
        )

    header = [
        "| Cell | n | s/stop | MAE (min) | median | bias | within 2 min | within 5 min |",
        "|---|---|---|---|---|---|---|---|",
    ]
    lines += ["## Before / after", ""] + header

    def chain_rate(sample: Sample) -> float:
        return profile.seconds_per_stop_for(sample.line_code, _moment_in(sample.bucket))[0]

    by_cell: dict[str, list[Sample]] = collections.defaultdict(list)
    for sample in samples:
        by_cell[cell_key(sample.line_code, sample.bucket)].append(sample)

    # The 'all' row's after-column is the whole chain at work, so its rate column names the
    # pooled global fit rather than pretending one number produced those minutes.
    pooled = f"{profile.overall.seconds_per_stop:.0f} global" if profile.overall else "chain"
    lines.append(row("**all**", samples, chain_rate, pooled))
    for key, group in sorted(by_cell.items()):
        cell = profile.cells.get(key)
        lines.append(row(f"`{key}`", group, chain_rate, f"{cell.seconds_per_stop:.0f}" if cell else "fallback"))

    lines += ["", f"Cells written: {len(profile.cells)} · lines: {len(profile.lines)} · min_samples: {min_samples}"]
    if profile.refused:
        lines += [
            "",
            "**Refused** (fewer than "
            f"{min_samples} paired arrivals — the fallback chain covers them instead): "
            + ", ".join(f"`{key}` n={n}" for key, n in sorted(profile.refused.items())),
        ]

    generalisation = holdout_mae(samples, min_samples=min_samples)
    if generalisation:
        lines += [
            "",
            "## Generalisation check — leave one clock hour out",
            "",
            "Train on every other hour, predict the hour never seen. This is what says four coarse",
            "buckets beat per-hour cells; a random fold would leak the same hour into training.",
            "",
            "| Rule | MAE (min) |",
            "|---|---|",
        ]
        lines += [f"| {name} | {value:.2f} |" for name, value in generalisation.items()]

    constant, rate, mae = best_constant_and_rate(samples)
    pure = (
        f", against {profile.overall.mae_minutes:.1f} min for the best pure rate"
        if profile.overall and profile.overall.mae_minutes is not None
        else ""
    )
    lines += [
        "",
        "## The constant we are not writing",
        "",
        f"The best constant+rate fit on this sample is **{constant:.1f} min + {rate:.0f} s/stop** "
        f"(MAE {mae:.1f} min){pure}.",
        "It is not written: with a 3-minute observation tick and nearest-stop semantics, a constant that "
        "large cannot be told apart from the measurement, and applying it would make a 1-stop ETA "
        "pessimistic by most of it. `constant_seconds` stays 0.0.",
    ]
    return "\n".join(lines)


def _moment_in(bucket: str) -> dt.datetime:
    """A datetime that lands in ``bucket``, so the profile's own lookup is exercised."""
    hour = {"morning": 8, "midday": 13, "evening": 18, "night": 23}[bucket]
    return dt.datetime(2026, 9, 13, hour, 0, tzinfo=ISTANBUL_TZ)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print the table, write nothing")
    parser.add_argument("--out", type=pathlib.Path, help="write somewhere other than data/reference/")
    parser.add_argument(
        "--min-samples",
        type=int,
        default=MIN_SAMPLES,
        help=f"paired arrivals a cell needs before its rate is written (default {MIN_SAMPLES})",
    )
    args = parser.parse_args(argv)

    samples, counters = collect_samples()
    profile = build_profile(samples, min_samples=args.min_samples)
    print(render(samples, counters, profile, min_samples=args.min_samples))

    if not samples:
        return 1

    before = summarise(samples, lambda _s: DEFAULT_SECONDS_PER_STOP)
    after = summarise(samples, lambda s: profile.seconds_per_stop_for(s.line_code, _moment_in(s.bucket))[0])
    if after["mae"] >= before["mae"]:
        print(
            f"\nREFUSING TO WRITE: the calibrated profile ({after['mae']:.2f} min MAE) does not beat the "
            f"fixed {DEFAULT_SECONDS_PER_STOP:.0f} s/stop default ({before['mae']:.2f} min). "
            "Nothing written; collect more data."
        )
        return 1

    if args.dry_run:
        print(f"\ndry run: nothing written (would have written {args.out or profile_path()})")
        return 0

    written = save_profile(profile, path=args.out)
    print(f"\nwritten: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
