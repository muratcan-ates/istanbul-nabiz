#!/usr/bin/env python3
"""Record the İBB Open Data catalogue (every dataset on data.ibb.gov.tr) into one local file. NETWORK.

One run makes at most :data:`MAX_CALLS` (3) requests, all to CKAN's ``package_search`` on
``data.ibb.gov.tr``, at least :data:`MIN_GAP_S` seconds apart, through :class:`PoliteClient`, each
sent once (``max_attempts=1``: a retry would be one more call). A page asks for
:data:`ROWS` datasets; the portal listed roughly 550 in September 2026, so one call is expected and
the next page is asked for only while datasets remain. Should the portal cap a page lower than
asked, the run stops at three calls and says the catalogue is partial, rather than calling more.

A page is kept only when it is a 200 whose body parses as JSON with ``success: true`` and a result
list; anything else is reported by status alone, and nothing is written. Written on success:

* ``data/reference/ibb_catalog.json``: every dataset slimmed to what Nabız reads (name, title, the
  first 600 characters of its description, publisher, categories, tags, licence, last update,
  resources with name, format, URL, last update and datastore flag). Gitignored.
* ``data/reference/ibb_catalog_summary.json``: counts by category, format and publisher, and the
  30 most recently updated datasets.

    NABIZ_OFFLINE=1 .venv/bin/python scripts/capture_ibb_catalog.py          # plan only: no request
    make capture-catalog                                                        # the calls (owner only)
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ibb_mcp.catalog import CATALOG_FILE, SEARCH_URL, SUMMARY_FILE, build_catalog, summarize  # noqa: E402
from ibb_mcp.http import PoliteClient, UpstreamUnavailable  # noqa: E402

REFERENCE = ROOT / "data" / "reference"
MAX_CALLS = 3
ROWS = 1000
#: Well above PoliteClient's own spacing for the portal, so the rule holds even if that changes.
MIN_GAP_S = 6.5


@dataclass
class Capture:
    """What the pages returned: the packages, the count CKAN reported, and one report row per call."""

    packages: list[dict[str, Any]] = field(default_factory=list)
    count: int | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.count is not None and len({p.get("name") for p in self.packages}) >= self.count

    @property
    def failed(self) -> bool:
        return any(not row.get("ok") for row in self.rows)


def plan_lines() -> list[str]:
    return [
        f"GET {SEARCH_URL}?rows={ROWS}&start=0",
        f"  then start={ROWS}, {2 * ROWS}: only while datasets remain; at most {MAX_CALLS} calls, >= {MIN_GAP_S} s apart",
        f"-> data/reference/{CATALOG_FILE} (gitignored) and data/reference/{SUMMARY_FILE}",
    ]


def page_results(payload: Any) -> tuple[int, list[dict[str, Any]]] | None:
    """``(count, results)`` from a CKAN ``package_search`` answer, or ``None`` when it is not one."""
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return None
    result = payload.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("results"), list):
        return None
    count = result.get("count")
    return (count if isinstance(count, int) else len(result["results"])), [p for p in result["results"] if isinstance(p, dict)]


async def capture(client: PoliteClient, *, max_calls: int = MAX_CALLS, gap_s: float = MIN_GAP_S) -> Capture:
    """Page through ``package_search`` until every dataset is in hand, a page fails, or the calls run out."""
    got = Capture()
    last = 0.0
    start = 0
    for _ in range(max_calls):
        wait = gap_s - (time.monotonic() - last)
        if last and wait > 0:
            await asyncio.sleep(wait)
        last = time.monotonic()
        row: dict[str, Any] = {"start": start, "rows": ROWS, "at_utc": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()}
        got.rows.append(row)
        try:
            payload = await client.get_json(SEARCH_URL, source="ibb_catalog", params={"rows": ROWS, "start": start})
        except UpstreamUnavailable as exc:
            row.update(ok=False, status=exc.status)  # the status only, never the body
            break
        parsed = page_results(payload)
        if parsed is None:
            row.update(ok=False, status=200, reason="not_a_package_search_answer")
            break
        got.count, results = parsed
        row.update(ok=True, status=200, received=len(results))
        got.packages.extend(results)
        start += len(results)
        if not results or start >= got.count:
            break
    return got


def write_files(got: Capture, reference: pathlib.Path, captured_at: dt.datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    catalog = build_catalog(got.packages, captured_at=captured_at, count_reported=got.count, calls=len(got.rows))
    catalog["meta"]["complete"] = got.complete
    summary = summarize(catalog)
    reference.mkdir(parents=True, exist_ok=True)
    (reference / CATALOG_FILE).write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (reference / SUMMARY_FILE).write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return catalog, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--live", action="store_true", help="make the calls (NETWORK); without it, print the plan")
    args = parser.parse_args(argv)
    for line in plan_lines():
        print(line)
    if not args.live:
        print(f"dry run: at most {MAX_CALLS} call(s) planned, none sent")
        return 0
    if os.getenv("NABIZ_OFFLINE", "").lower() in {"1", "true", "yes"}:
        print("NABIZ_OFFLINE is set: refusing to call data.ibb.gov.tr (run `make capture-catalog`)")
        return 2

    async def go() -> Capture:
        async with PoliteClient(max_attempts=1) as client:
            return await capture(client)

    captured_at = dt.datetime.now(dt.UTC)
    got = asyncio.run(go())
    for row in got.rows:
        print(json.dumps(row, ensure_ascii=False))
    if got.failed or not got.packages:
        print(f"nothing written: {len(got.rows)} call(s), a page failed or came back empty")
        return 1
    catalog, summary = write_files(got, REFERENCE, captured_at)
    meta = catalog["meta"]
    print(
        f"{meta['count_captured']} dataset(s) of {meta['count_reported']} reported, {meta['calls']} call(s),"
        f" complete={meta['complete']}; {summary['resources']} resource(s), {summary['datastore_datasets']} with a datastore"
    )
    print("by category: " + ", ".join(f"{name} {count}" for name, count in summary["by_category"].items()))
    return 0 if got.complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
