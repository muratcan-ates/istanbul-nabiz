#!/usr/bin/env python3
"""Cut ``tests/fixtures/gtfs_mini/`` out of the full İBB GTFS export.

``data/reference/gtfs/`` is gitignored — 180 MB, and İBB's to publish, not ours — so CI
never has it, and every test that quietly leaned on it passed locally and failed on every
push. This keeps a few hundred real rows instead: enough for the stop search, the arrival
estimate and the off-route refusal to run exactly the code paths they run in production.

Rows are copied **byte for byte**, never re-serialised, because the loaders exist to repair
İBB's quirks and a tidied fixture would test nothing: the UTF-8 BOM, ``;`` separators and
CRLF endings, coordinates written with thousands separators (``410.191.700.005.564``),
mojibaked route names and codes (``14ÅžB`` for ``14ŞB``), stops with no ``stop_code``, and
a stop whose coordinate cannot be repaired at all. ``stop_times.txt`` is the complete ZIP
variant (comma separated, no BOM); the Excel-truncated ``stop_times.csv`` is left out on
purpose — see ``ibb_mcp.gtfs._stop_times_path``.

What is kept, and why:

* every ``routes.csv`` row of 500T (27 variants), so ``routes_for_short_name("500T")``
  answers exactly as it does against the full file;
* the longest trip — the one ``build_stop_sequences`` would pick — of 500T in both
  directions (Şifa Sondurak <-> 4.Levent Metro); of 8A and 14ŞB, which call at the Kadıköy
  pier; and of 153 and 25S1, which call at the Sarıyer stop named plain "ŞİFA". Those four
  give an off-route refusal something honest to suggest instead;
* every stop those trips call at, every stop the recorded 500T vehicles report as their
  nearest stop, and every stop whose name contains "Kadıköy" or "Şifa" — so the stop
  search ranks those two queries the same way the full index does.

Run from the repository root; it reads local files only and never touches the network::

    .venv/bin/python tests/fixtures/gtfs_mini/extract.py
    .venv/bin/python tests/fixtures/gtfs_mini/extract.py --check   # compare, write nothing
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ibb_mcp.config import Settings  # noqa: E402  (import must follow the sys.path bootstrap)
from ibb_mcp.gtfs import _fix_mojibake, build_stop_sequences, normalize_tr, reset_index_cache  # noqa: E402
from ibb_mcp.models import repair_coordinate  # noqa: E402

#: Route variants whose longest trip is kept, so their stop sequence can be rebuilt.
SEQUENCE_ROUTE_CODES = ("500T_G_D0", "500T_D_D0", "8A_G_D0", "14ŞB_G_D0", "153_G_D0", "25S1_G_D0")
#: Lines whose every routes.csv variant is kept, used or not.
ALL_VARIANTS_OF = ("500T",)
#: Every stop whose folded name contains one of these tokens: the stop names the suite asks for.
STOP_NAME_TOKENS = ("kadikoy", "sifa")
#: How many code-less stops and unrepairable-coordinate stops to keep as loader edge cases.
CODELESS_STOPS = 2
UNPLACEABLE_STOPS = 1

FILES = ("stops.csv", "routes.csv", "trips.csv", "stop_times.txt")


def split_lines(path: pathlib.Path) -> tuple[bytes, list[bytes]]:
    """Header line and data lines, each with its original line ending and the header's BOM."""
    lines = path.read_bytes().splitlines(keepends=True)
    return lines[0], lines[1:]


def fields(header: bytes, line: bytes, delimiter: str) -> dict[str, str]:
    names = next(csv.reader(io.StringIO(header.decode("utf-8-sig")), delimiter=delimiter))
    values = next(csv.reader(io.StringIO(line.decode("utf-8")), delimiter=delimiter), [])
    return dict(zip(names, values, strict=False))


def extract(source: pathlib.Path) -> dict[str, bytes]:
    """Return ``{filename: bytes}`` for the mini feed. Pure: writes nothing."""
    routes_head, routes = split_lines(source / "routes.csv")
    stops_head, stops = split_lines(source / "stops.csv")
    trips_head, trips = split_lines(source / "trips.csv")

    # routes: repaired code/short name decide, the raw line is what gets written.
    keep_routes: list[bytes] = []
    route_code_by_id: dict[str, str] = {}
    for line in routes:
        row = fields(routes_head, line, ";")
        code = _fix_mojibake(row.get("route_code", "")).strip()
        short = _fix_mojibake(row.get("route_short_name", "")).strip()
        if code in SEQUENCE_ROUTE_CODES or short in ALL_VARIANTS_OF:
            keep_routes.append(line)
            route_code_by_id[row["route_id"].strip()] = code
    wanted_route_ids = {rid for rid, code in route_code_by_id.items() if code in SEQUENCE_ROUTE_CODES}
    missing = set(SEQUENCE_ROUTE_CODES) - {route_code_by_id[r] for r in wanted_route_ids}
    if missing:
        raise SystemExit(f"route codes not in {source / 'routes.csv'}: {sorted(missing)}")

    trip_lines: dict[str, bytes] = {}
    trip_route: dict[str, str] = {}
    for line in trips:
        row = fields(trips_head, line, ";")
        if row.get("route_id", "").strip() in wanted_route_ids:
            trip_id = row["trip_id"].strip()
            trip_lines[trip_id] = line
            trip_route[trip_id] = route_code_by_id[row["route_id"].strip()]

    stop_code_by_id: dict[str, str] = {}
    for line in stops:
        row = fields(stops_head, line, ";")
        if row.get("stop_id", "").strip() and row.get("stop_code", "").strip():
            stop_code_by_id[row["stop_id"].strip()] = row["stop_code"].strip()

    # stop_times.txt is 150 MB: stream it, and hold only the rows of candidate trips.
    per_trip: dict[str, list[bytes]] = {}
    joinable: dict[str, int] = {}
    with (source / "stop_times.txt").open("rb") as fh:
        times_head = fh.readline()
        names = next(csv.reader(io.StringIO(times_head.decode("utf-8-sig"))))
        stop_col = names.index("stop_id")
        for line in fh:
            trip_id = line.split(b",", 1)[0].decode("utf-8").strip()
            if trip_id not in trip_route:
                continue
            per_trip.setdefault(trip_id, []).append(line)
            stop_id = next(csv.reader(io.StringIO(line.decode("utf-8"))))[stop_col].strip()
            joinable[trip_id] = joinable.get(trip_id, 0) + (stop_id in stop_code_by_id)

    # The same rule as build_stop_sequences: most joinable rows wins, first seen on a tie.
    best: dict[str, str] = {}
    for trip_id in per_trip:
        code = trip_route[trip_id]
        if code not in best or joinable[trip_id] > joinable[best[code]]:
            best[code] = trip_id
    chosen = set(best.values())

    served_stop_ids = {
        next(csv.reader(io.StringIO(line.decode("utf-8"))))[stop_col].strip()
        for trip_id in chosen
        for line in per_trip[trip_id]
    }
    fleet = json.loads((ROOT / "tests" / "fixtures" / "iett_hat_500T.json").read_text(encoding="utf-8"))
    fleet_codes = {str(bus.get("yakinDurakKodu", "")).strip() for bus in fleet} - {""}

    keep_stops: list[bytes] = []
    codeless = unplaceable = 0
    for line in stops:
        row = fields(stops_head, line, ";")
        stop_id, code = row.get("stop_id", "").strip(), row.get("stop_code", "").strip()
        placeable = (
            repair_coordinate(row.get("stop_lat"), "lat") is not None
            and repair_coordinate(row.get("stop_lon"), "lon") is not None
        )
        keep = (
            stop_id in served_stop_ids
            or code in fleet_codes
            or any(token in normalize_tr(_fix_mojibake(row.get("stop_name", ""))) for token in STOP_NAME_TOKENS)
        )
        if not keep and not code and placeable and codeless < CODELESS_STOPS:
            keep, codeless = True, codeless + 1
        if not keep and not placeable and unplaceable < UNPLACEABLE_STOPS:
            keep, unplaceable = True, unplaceable + 1
        if keep:
            keep_stops.append(line)

    return {
        "routes.csv": routes_head + b"".join(keep_routes),
        "stops.csv": stops_head + b"".join(keep_stops),
        "trips.csv": trips_head + b"".join(trip_lines[t] for t in trip_lines if t in chosen),
        "stop_times.txt": times_head + b"".join(line for t in per_trip if t in chosen for line in per_trip[t]),
    }


def verify(source: pathlib.Path, out: pathlib.Path) -> list[str]:
    """Rebuild the sequences from the mini feed and compare them with the full feed's."""
    problems: list[str] = []
    reset_index_cache()
    full = build_stop_sequences(Settings(gtfs_dir=source, offline=True))
    reset_index_cache()
    mini = build_stop_sequences(Settings(gtfs_dir=out, offline=True))
    reset_index_cache()
    if sorted(mini) != sorted(SEQUENCE_ROUTE_CODES):
        problems.append(f"mini feed builds {sorted(mini)}, expected {sorted(SEQUENCE_ROUTE_CODES)}")
    for code in SEQUENCE_ROUTE_CODES:
        if code in mini and full.get(code) != mini[code]:
            problems.append(f"{code}: mini sequence differs from the full feed's")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=pathlib.Path, default=ROOT / "data" / "reference" / "gtfs")
    parser.add_argument("--out", type=pathlib.Path, default=HERE)
    parser.add_argument("--check", action="store_true", help="compare with the committed files, write nothing")
    args = parser.parse_args(argv)

    missing = [name for name in FILES if not (args.source / name).is_file()]
    if missing:
        print(f"{args.source} lacks {', '.join(missing)}; download the İBB GTFS export first", file=sys.stderr)
        return 2

    files = extract(args.source)
    if args.check:
        stale = [name for name, data in files.items() if (args.out / name).read_bytes() != data]
        for name in stale:
            print(f"{name} differs from what the full feed would produce")
        return 1 if stale else 0

    for name, data in files.items():
        (args.out / name).write_bytes(data)
        print(f"{name:15} {data.count(b'\n') - 1:5} rows {len(data):8,} bytes")
    problems = verify(args.source, args.out)
    for problem in problems:
        print(f"MISMATCH {problem}", file=sys.stderr)
    print(f"total {sum(len(d) for d in files.values()):,} bytes; sequences match the full feed: {not problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
