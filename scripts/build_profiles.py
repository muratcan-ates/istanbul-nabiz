#!/usr/bin/env python3
"""Build ``data/reference/occupancy_profile.json`` from the collected İSPARK snapshots.

This is the script that turns the collector's reason for existing into an answer. İSPARK
publishes only the current free-space count, so "bu otoparkta bu saatte genelde ne kadar
yer olur?" is unanswerable from the live API at any budget. It becomes answerable once a
few weeks of ``data/lake/ispark_snapshot/`` exist — and the point of the coverage report
this script prints is to say, out loud and in numbers, how far from that we currently are.

Nothing here touches the network.

Usage::

    .venv/bin/python scripts/build_profiles.py
    .venv/bin/python scripts/build_profiles.py --dry-run          # report, write nothing
    .venv/bin/python scripts/build_profiles.py --out /tmp/p.json
    .venv/bin/python scripts/build_profiles.py --json             # machine-readable stats
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from eta_report import lake_dir, read_source  # noqa: E402  (needs the sys.path bootstrap)

from ibb_mcp.config import Settings  # noqa: E402
from ibb_mcp.occupancy import (  # noqa: E402
    CLASS_TR,
    OccupancyProfile,
    build_profile,
    profile_path,
    save_profile,
)

SOURCE = "ispark_snapshot"


def _histogram(profile: OccupancyProfile) -> list[tuple[str, int, int, int]]:
    """Per weekday class: cells observed, cells over the sample floor, cells reportable."""
    observed: collections.Counter[str] = collections.Counter()
    enough: collections.Counter[str] = collections.Counter()
    usable: collections.Counter[str] = collections.Counter()
    for cell in profile.cells.values():
        observed[cell.weekday_class] += 1
        if cell.samples >= profile.min_samples:
            enough[cell.weekday_class] += 1
    for cell in profile.usable_cells():
        usable[cell.weekday_class] += 1
    return [(klass, observed[klass], enough[klass], usable[klass]) for klass in ("weekday", "saturday", "sunday")]


def _hours_covered(profile: OccupancyProfile) -> dict[str, list[int]]:
    hours: dict[str, set[int]] = collections.defaultdict(set)
    for cell in profile.cells.values():
        if cell.samples:
            hours[cell.weekday_class].add(cell.hour)
    return {klass: sorted(values) for klass, values in hours.items()}


def report(profile: OccupancyProfile, target: pathlib.Path | None) -> dict[str, Any]:
    """Print the coverage report and return the same numbers as a dict."""
    coverage = profile.coverage()
    hours = _hours_covered(profile)

    print(f"source          : {lake_dir() / SOURCE}")
    print(f"rows read       : {coverage['rows_read']}")
    print(f"observation span: {coverage['observation_span_hours']:.1f} h "
          f"({coverage['first_sample_utc']} -> {coverage['last_sample_utc']})")
    print(f"parks with any cell      : {coverage['parks_with_any_cell']}")
    print(f"parks with usable cell   : {coverage['parks_with_usable_cell']}")
    print(f"cells observed           : {coverage['cells']}")
    print(f"cells >= MIN_SAMPLES ({coverage['min_samples']})  : {coverage['cells_meeting_min_samples']}")
    print(f"cells reportable         : {coverage['cells_usable']}  "
          f"(also need span >= {coverage['min_span_hours']} h)")
    print()
    print(f"{'class':<10} {'observed':>9} {'>=min_samples':>14} {'reportable':>11}  hours seen (İstanbul)")
    for klass, observed, enough, usable in _histogram(profile):
        seen = hours.get(klass, [])
        compact = ",".join(f"{h:02d}" for h in seen) if seen else "-"
        print(f"{CLASS_TR[klass]:<10} {observed:>9} {enough:>14} {usable:>11}  {compact}")
    print()

    if coverage["cells_usable"] == 0:
        print("NO CELL IS REPORTABLE YET.")
        print("  Every cell buckets one hour of the clock, so its samples can only span more than an")
        print("  hour if two different dates fed it. With the history currently on disk no (park, class,")
        print("  hour) cell has been seen on two separate days, which is exactly the case the span guard")
        print("  exists for: six snapshots of one afternoon are six views of one afternoon, not a habit.")
        print("  ispark_typical_occupancy will therefore answer available:false and say so. Let the")
        print("  collector run across whole days and re-run this script; nothing else needs to change.")
        print()

    if target is not None:
        size_kb = target.stat().st_size / 1024
        print(f"written         : {target} ({size_kb:.0f} KB)")
    else:
        print("written         : nothing (--dry-run)")
    return coverage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--out", type=pathlib.Path, default=None, help="output path (default: data/reference/occupancy_profile.json)"
    )
    parser.add_argument("--dry-run", action="store_true", help="compute and report, but do not write the file")
    parser.add_argument("--json", action="store_true", help="also print the coverage stats as JSON")
    args = parser.parse_args()

    rows = read_source(SOURCE)
    if not rows:
        print(f"No rows under {lake_dir() / SOURCE}. Run the collector first (make collect / scripts/collect_forever.py).")
        return 1

    profile = build_profile(rows)
    target = None
    if not args.dry_run:
        target = save_profile(profile, args.out, settings=Settings.from_env())

    coverage = report(profile, target)
    if args.json:
        print(json.dumps(coverage, ensure_ascii=False, indent=2))
    if args.dry_run:
        print(f"(would have written {args.out or profile_path(Settings.from_env())})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
