#!/usr/bin/env python3
"""Record Metro İstanbul's faulty-equipment answers as dated test fixtures. NETWORK.

One run makes at most four requests, all to ``api.ibb.gov.tr`` and at least
:data:`MIN_GAP_S` seconds apart: the ``GetFaultyEquipments`` summary, then one
``GetFaultyEquipmentDetails`` POST per equipment group. Each request is sent once
(``max_attempts=1``): a retry would be a fifth call.

Every POST body is built by :func:`ibb_mcp.sources.metro_equipment.details_body`, which
refuses anything but a known group name, and all four are checked before the first request
leaves: the endpoint answers a missing or malformed body with a server error, so an invalid
request is never sent.

A response is written only when it is a 200 whose body parses as JSON: a ``{Success: true}``
envelope or a bare list. Anything else is reported by its status alone, never by its text: an
error page there can carry server internals that do not belong in a public repository. The
fixtures are published with the code, so read them before committing them.

Fixtures land in ``tests/fixtures/`` as ``metro_faulty_equipments_<YYYYMMDD>.json`` and
``metro_faulty_equipment_details_<group>_<YYYYMMDD>.json`` (UTC date), and each call is
recorded in ``tests/fixtures/_capture_report.json`` with its ``captured_at_utc``, which is how
offline answers date themselves.

    NABIZ_OFFLINE= .venv/bin/python scripts/capture_metro_equipment.py            # dry run: plan only
    NABIZ_OFFLINE= .venv/bin/python scripts/capture_metro_equipment.py --live     # the four calls
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import pathlib
import sys
import time
from dataclasses import dataclass
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ibb_mcp.config import METRO_FAULTY_EQUIPMENT_DETAILS, METRO_FAULTY_EQUIPMENTS  # noqa: E402
from ibb_mcp.http import PoliteClient, UpstreamUnavailable  # noqa: E402
from ibb_mcp.sources.base import CAPTURE_REPORT  # noqa: E402
from ibb_mcp.sources.metro_equipment import (  # noqa: E402
    EQUIPMENT_GROUPS,
    details_body,
    details_fixture_name,
    summary_fixture_name,
)

FIXTURES = ROOT / "tests" / "fixtures"
MAX_CALLS = 4
#: Above PoliteClient's own 6 s spacing for the gateway, so the rule holds even if that changes.
MIN_GAP_S = 6.5


@dataclass(frozen=True)
class PlannedCall:
    name: str
    method: str
    url: str
    body: dict[str, Any] | None


def plan(stamp: str) -> list[PlannedCall]:
    """The calls one run makes, bodies validated. Raises before any request is sent."""
    calls = [PlannedCall(summary_fixture_name(stamp), "GET", METRO_FAULTY_EQUIPMENTS, None)]
    calls += [
        PlannedCall(details_fixture_name(group, stamp), "POST", METRO_FAULTY_EQUIPMENT_DETAILS, details_body(group))
        for group in EQUIPMENT_GROUPS
    ]
    if len(calls) > MAX_CALLS:
        raise ValueError(f"{len(calls)} calls planned; the limit is {MAX_CALLS}")
    for call in calls:
        if call.method == "POST" and not call.body:
            raise ValueError(f"{call.name}: a POST without a body is never sent")
    return calls


def acceptable(payload: Any) -> bool:
    """A ``{Success: true, ...}`` envelope, or a bare list: what the source's ``unwrap`` reads."""
    return isinstance(payload, list) or (isinstance(payload, dict) and payload.get("Success") is True)


async def _send(client: PoliteClient, call: PlannedCall) -> Any:
    if call.method == "GET":
        return await client.get_json(call.url, source=call.name)
    return await client.post_json(call.url, source=call.name, body=call.body or {})


async def run(calls: list[PlannedCall], *, client: PoliteClient, fixtures: pathlib.Path) -> list[dict[str, Any]]:
    """Make the calls in order, spaced, writing each acceptable answer. Returns report rows."""
    rows: list[dict[str, Any]] = []
    last = 0.0
    for call in calls:
        wait = MIN_GAP_S - (time.monotonic() - last)
        if last and wait > 0:
            await asyncio.sleep(wait)
        started = time.monotonic()
        captured_at = dt.datetime.now(dt.UTC).replace(microsecond=0)
        last = started
        row: dict[str, Any] = {"name": call.name, "url": call.url, "captured_at_utc": captured_at.isoformat()}
        try:
            payload = await _send(client, call)
        except UpstreamUnavailable as exc:
            # The status only: the exception text is ours, but nothing of the answer's body.
            row.update(status=exc.status, written=False, reason="upstream_unavailable")
            rows.append(row)
            continue
        text = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
        row["seconds"] = round(time.monotonic() - started, 2)
        if not acceptable(payload):
            row.update(status=200, written=False, reason="success_false_or_unexpected_shape")
            rows.append(row)
            continue
        (fixtures / f"{call.name}.json").write_text(text, encoding="utf-8")
        row.update(status=200, bytes=len(text.encode("utf-8")), written=True)
        rows.append(row)
    return rows


def merge_report(fixtures: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    """Add the written calls to the capture report, replacing older rows of the same name."""
    path = fixtures / CAPTURE_REPORT
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    written = [{k: v for k, v in row.items() if k not in {"written", "reason"}} for row in rows if row.get("written")]
    names = {row["name"] for row in written}
    report = [row for row in report if row.get("name") not in names] + written
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--live", action="store_true", help="make the calls (NETWORK); without it, print the plan")
    args = parser.parse_args(argv)

    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d")
    calls = plan(stamp)
    for call in calls:
        print(f"{call.method:4} {call.url} body={json.dumps(call.body, ensure_ascii=False)} -> {call.name}.json")
    if not args.live:
        print(f"dry run: {len(calls)} call(s) planned, none sent")
        return 0

    async def go() -> list[dict[str, Any]]:
        async with PoliteClient(max_attempts=1) as client:
            return await run(calls, client=client, fixtures=FIXTURES)

    rows = asyncio.run(go())
    merge_report(FIXTURES, rows)
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    return 0 if all(row.get("written") for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
