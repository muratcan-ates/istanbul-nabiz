#!/usr/bin/env python3
"""Build the per-line reliability table from the lake and report what it can support.

Reads ``iett_line_snapshot`` — the vehicle positions the collector archived — turns them
into headway statistics with :mod:`ibb_mcp.reliability`, writes
``data/reference/line_reliability.json`` and ``eval/results/reliability.md``, and prints
the same table to stdout.

Nothing here touches the network: the snapshots are already on disk, and the GTFS stop
sequences come from the cached index. Run it as often as you like.

The report prints refused cells alongside published ones on purpose. A reliability page
that silently omits the hours it could not measure reads as complete when it is not; a
line that shows "yetersiz gözlem" for nine of its twelve hours is telling the reader
exactly how far two days of collection got.

Usage::

    .venv/bin/python scripts/reliability_report.py
    .venv/bin/python scripts/reliability_report.py --line 500T
    .venv/bin/python scripts/reliability_report.py --no-write
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from eta_report import read_source  # noqa: E402  (import follows the sys.path bootstrap)

from ibb_mcp.config import Settings  # noqa: E402
from ibb_mcp.models import ISTANBUL_TZ  # noqa: E402
from ibb_mcp.reliability import (  # noqa: E402
    CV_BUNCHED,
    CV_REGULAR,
    HEADWAY_RESOLUTION_MINUTES,
    MIN_CAPTURE_RATE,
    MIN_HEADWAYS_PER_STOP,
    MIN_SAMPLES,
    MIN_STOPS_FOR_CV,
    ReliabilityTable,
    build_table,
    save_table,
)

SOURCE = "iett_line_snapshot"
DEFAULT_MARKDOWN = ROOT / "eval" / "results" / "reliability.md"


def load_sequences() -> dict:
    """Route stop orders. Optional: without them the forward-movement filter is skipped."""
    try:
        from ibb_mcp.gtfs import load_stop_sequences

        return load_stop_sequences(Settings.from_env())
    except Exception as exc:  # noqa: BLE001 - a missing GTFS cache must degrade, not abort
        print(f"warning: stop sequences unavailable ({exc!r}); arrivals will not be direction-filtered")
        return {}


def render(table: ReliabilityTable, *, sequences_loaded: bool) -> str:
    """The markdown report: what was measured, then what could not be."""
    published = [c for c in table.cells if c.available]
    refused = [c for c in table.cells if not c.available]
    span = table.span_hours
    lines = [
        "# Hat düzenliliği / Per-line reliability",
        "",
        "Derived entirely from vehicle positions this project archived; İETT publishes no headway or",
        "bunching data. Built by `scripts/reliability_report.py`, no network access.",
        "",
    ]
    if not table.cells:
        lines += [
            "No vehicle snapshots in the lake yet, so there is nothing to measure. Run",
            "`scripts/collect_forever.py` (or `make collect-bg`) and try again.",
            "",
        ]
        return "\n".join(lines)

    lines += [
        f"- Observation span: **{_fmt(table.observed_from)} → {_fmt(table.observed_to)}** "
        f"({span} h wall-clock, {len(table.days_covered)} calendar day(s): {', '.join(table.days_covered)})",
        f"- Vehicle snapshots read: **{table.snapshots_read:,}** across lines {', '.join(table.lines())}",
        f"- Cells published: **{len(published)}** of {len(table.cells)}; "
        f"**{len(refused)}** refused for want of observations",
        f"- Cells whose cv exceeds its own sampling floor (i.e. irregularity that missed passages alone "
        f"cannot explain): **{sum(1 for c in published if c.cv_exceeds_floor)}** of {len(published)}",
        f"- Arrival resolution: **~{table.resolution_minutes:.1f} min** (one collector tick)",
    ]
    if not sequences_loaded:
        lines.append("- ⚠ GTFS stop sequences were unavailable: no forward-movement filter, no stops/hour rate")
    lines += [
        "",
        "Hours are İstanbul local time (UTC+3).",
        "",
        "## Measured cells",
        "",
        "| Hat | Saat | Ortanca aralık | cv | cv tabanı | Taban üstü | Kümelenme | Filo | Durak | "
        "Aralık gözlemi | Yakalama | Durak/sa | km/sa |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for cell in published:
        lines.append(
            f"| {cell.line_code} | {cell.hour:02d}:00 | {cell.median_headway_min} dk | {cell.headway_cv} | "
            f"{_num(cell.cv_sampling_floor)} | {'evet' if cell.cv_exceeds_floor else 'hayır'} | "
            f"{cell.bunching_label} | {cell.vehicles_seen} | "
            f"{cell.stops_measured} | {cell.samples} | {_pct(cell.stop_capture_rate)} | "
            f"{_num(cell.stops_per_hour_median)} | {_num(cell.median_speed_kmh)} |"
        )
    if not published:
        lines.append("| — | — | — | — | — | — | — | — | — | — | — | — | — |")
        lines.append("")
        lines.append("**No cell cleared the guards.** Every hour observed so far is listed below with its reason.")

    lines += [
        "",
        "## Refused cells — what the archive cannot support yet",
        "",
        "| Hat | Saat | Aralık gözlemi | Filo | cv'li durak | Yakalama | Neden |",
        "|---|---|---|---|---|---|---|",
    ]
    for cell in refused:
        lines.append(
            f"| {cell.line_code} | {cell.hour:02d}:00 | {cell.samples} | {cell.vehicles_seen} | "
            f"{cell.stops_with_cv} | {_pct(cell.stop_capture_rate)} | {cell.reason} |"
        )
    if not refused:
        lines.append("| — | — | — | — | — | — | every observed cell cleared the guards |")

    lines += [
        "",
        "## How to read this",
        "",
        f"- **cv** is the coefficient of variation of the headways at a stop, `std/mean`, taken per stop "
        f"(minimum {MIN_HEADWAYS_PER_STOP} gaps) and then medianed across at least {MIN_STOPS_FOR_CV} stops. "
        "0 is a perfectly even service; 1 is the cv of a Poisson process, i.e. arrivals that carry no "
        "information about each other.",
        f"- Bands: `< {CV_REGULAR}` düzenli · `{CV_REGULAR}–{CV_BUNCHED}` biraz düzensiz · "
        f"`≥ {CV_BUNCHED}` kümelenme var.",
        f"- A cell needs at least {MIN_SAMPLES} headway observations, {MIN_STOPS_FOR_CV} stops with a cv, "
        f"two distinct vehicles and a capture rate of {MIN_CAPTURE_RATE:.0%}. Below any of those it reports "
        "no number at all.",
        "- **Yakalama** (capture) is measured, not assumed: when a bus advances three stop positions between "
        "two ticks it passed three stops and we witnessed one, so `steps / stops advanced` is the share of "
        "stop passages this sampling rate can see.",
        "- **cv tabanı** is the cv a *perfectly regular* line would still show at that capture rate, "
        "`sqrt(1 - capture)`. Compare it with the measured cv before believing a bunching verdict.",
        "",
        "## What this measurement can and cannot say",
        "",
        f"1. **Quantisation.** Arrivals are located to one collector tick (~{HEADWAY_RESOLUTION_MINUTES} min), "
        "so headways come out as multiples of it. Read a median of 12.9 min as \"about 13\", never as 12.9.",
        "2. **The cv is an upper bound, and the bound is wide.** A bus that passes a stop between two ticks "
        "is never seen there and its two headways merge into one double gap, which raises both the median "
        "headway and the cv. The capture column says how often that happens — line-wide it is under half — "
        "so treat the headway as an over-estimate and the cv as an over-estimate. The `cv tabanı` column is "
        "the floor this produces on a perfectly regular line. Measured cvs sitting *below* their floor are "
        "not a contradiction: a stop only enters the cv when it yielded three witnessed arrivals in the "
        "hour, which selects exactly the stops where buses dwell and are easy to catch, so their local "
        "capture is much better than the line average. It does mean that comparing one line's cv against "
        "another's is not yet safe — comparing hours within one line is.",
        "3. **Samples are correlated.** Two buses running nose-to-tail generate a short headway at every stop "
        "they pass, so `Aralık gözlemi` is not an independent sample count — `Araç` and `Durak` are the "
        "honest bound on how much was really seen.",
        f"4. **This is not a typical week.** {len(table.days_covered)} calendar day(s) of partial collection "
        "covering the hours in the table above. A cell says what happened on those days at that hour, not "
        "what happens every Tuesday. Hours nobody collected simply do not appear.",
        "5. **Direction matters and is kept.** Headways are computed per (line, direction, stop); the two "
        "directions of a line are never mixed.",
        "",
        "Not affiliated with İBB or İETT. Kamu sektörü bilgilerini içerir — İBB Açık Veri Portalı, "
        "İBB Açık Veri Lisansı (CC BY 4.0).",
        "",
    ]
    return "\n".join(lines)


def _fmt(moment: dt.datetime | None) -> str:
    if moment is None:
        return "n/a"
    return moment.astimezone(ISTANBUL_TZ).strftime("%Y-%m-%d %H:%M") + " (TRT)"


def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"%{value * 100:.0f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--json", type=pathlib.Path, default=None,
        help="where to write the table (default: data/reference/line_reliability.json)",
    )
    parser.add_argument("--markdown", type=pathlib.Path, default=DEFAULT_MARKDOWN, help="where to write the report")
    parser.add_argument("--line", action="append", default=None, help="restrict to one line code; repeatable")
    parser.add_argument("--no-write", action="store_true", help="print the report without writing any file")
    args = parser.parse_args(argv)

    rows = read_source(SOURCE)
    if args.line:
        wanted = set(args.line)
        rows = [row for row in rows if row.get("line_code") in wanted]
    sequences = load_sequences()
    table = build_table(rows, sequences)
    report = render(table, sequences_loaded=bool(sequences))
    print(report)

    if not args.no_write:
        json_path = save_table(table) if args.json is None else save_table(table, args.json)
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(report, encoding="utf-8")
        print(f"\nwrote {json_path}\nwrote {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
