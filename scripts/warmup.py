#!/usr/bin/env python3
"""Fill the caches before a demo, so the first question is not the slow one.

The client holds at least six seconds between calls to ``api.ibb.gov.tr`` because the
gateway starts refusing every service after roughly fifteen rapid ones. That politeness is
correct and it is also visible: a cold "Taksim'de otopark var mı?" spends about eighteen
seconds fetching three tariffs, and answers instantly for the rest of the cache window.

Run this a minute before recording, or after a deploy. It touches each source exactly once
through the same code path the tools use, so what gets warmed is what the demo will read.
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from ibb_mcp.sources.base import SourceContext  # noqa: E402
from ibb_mcp.tools import Nabiz  # noqa: E402

#: One representative call per source, in the order a demo asks them.
STEPS: tuple[tuple[str, str, dict], ...] = (
    ("otopark", "ispark_find_parking", {"place": "Taksim", "min_free": 1}),
    ("durak arama", "iett_stops_search", {"query": "4.LEVENT METRO", "limit": 3}),
    ("otobüs konumları", "iett_line_buses", {"line_code": "500T"}),
    ("varış tahmini", "iett_next_arrivals", {"line_code": "500T", "stop": "301341", "limit": 3}),
    ("metro durumu", "metro_status", {}),
    ("istasyon bilgisi", "metro_station_info", {"name": "Kartal"}),
    ("trafik", "traffic_index", {"window": "now"}),
    ("hava kalitesi", "air_quality_now", {"place": "Beşiktaş"}),
)


async def warm(verbose: bool = True) -> int:
    app = Nabiz(SourceContext.create())
    failures = 0
    total = time.monotonic()
    try:
        for label, tool, arguments in STEPS:
            started = time.monotonic()
            try:
                result = await getattr(app, tool)(**arguments)
            except Exception as exc:  # noqa: BLE001 - a warm-up must report, not abort
                failures += 1
                if verbose:
                    print(f"  {label:18s} HATA  {type(exc).__name__}: {exc}")
                continue
            elapsed = time.monotonic() - started
            if verbose:
                age = result.provenance.describe_age()
                print(f"  {label:18s} {elapsed:5.1f} sn   veri: {age}")
    finally:
        await app.aclose()

    if verbose:
        print(f"\ntoplam {time.monotonic() - total:.1f} sn, {len(STEPS) - failures}/{len(STEPS)} kaynak hazır")
        print("önbellek sıcak: aynı sorular şimdi anında yanıtlanır")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    if not args.quiet:
        print("önbellek ısıtılıyor (her çağrı arasında ≥6 sn bekleniyor, bu normal)\n")
    return asyncio.run(warm(verbose=not args.quiet))


if __name__ == "__main__":
    raise SystemExit(main())
