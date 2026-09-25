"""Local history for Metro İstanbul's currently unusable equipment.

Each snapshot reads three detail groups and one summary from the same Metro host: at
most four requests, no İETT budget, and no extra sleep or client. The API publishes no
history, so this module writes only fresh, provenance-dated flat rows to the local lake.
History reads local gzip NDJSON only; Delta and Blob backends are outside this reader.
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator
from typing import Any

from ibb_mcp.sources.base import SourceContext
from ibb_mcp.sources.metro_equipment import EQUIPMENT_GROUPS, EquipmentRecord, MetroEquipmentSource
from nabiz.collector import lake
from nabiz.collector.snapshots import iso_utc, read_or_skip

EQUIPMENT_SOURCE = "metro_equipment_snapshot"
EQUIPMENT_INTERVAL_S = 900
MAX_REQUESTS_PER_SNAPSHOT = 4


async def snapshot_equipment(ctx: SourceContext) -> list[dict[str, Any]]:
    """Build one row per unusable item and a heartbeat for every successfully empty group."""
    read = await read_or_skip("metro_equipment", lambda: MetroEquipmentSource(ctx).snapshot(EQUIPMENT_GROUPS))
    if read is None:
        return []
    snapshot, provenance = read
    if not snapshot.available:
        return []

    stamp = iso_utc(provenance.observed_at)
    assert stamp is not None
    rows: list[dict[str, Any]] = []
    summaries = {summary.group: summary for summary in snapshot.summary}
    records_by_group: dict[str, list[EquipmentRecord]] = {group: [] for group in snapshot.groups_read}
    for record in snapshot.records:
        group = record.group or ""
        records_by_group.setdefault(group, []).append(record)
        summary = summaries.get(group)
        rows.append(
            {
                "snapshot_ts_utc": stamp,
                "ts_utc": stamp,
                "has_record": True,
                "group": group,
                "equipment_type": record.equipment_type,
                "equipment_code": record.code,
                "outage_id": record.outage_id,
                "line_id": record.line_id,
                "line_name": record.line_name,
                "station_id": record.station_id,
                "station_name": record.station_name,
                "location": record.location,
                "status_type": record.status_type,
                "status_class": record.status_class,
                "ibb_date": iso_utc(record.ibb_date),
                "ibb_date_raw": record.ibb_date_raw,
                "summary_inactive": summary.inactive if summary else None,
                "summary_consistent": summary.consistent if summary else None,
                "uncertainty": ",".join(snapshot.uncertainty),
            }
        )

    for group in snapshot.groups_read:
        if records_by_group.get(group):
            continue
        summary = summaries.get(group)
        rows.append(
            {
                "snapshot_ts_utc": stamp,
                "ts_utc": stamp,
                "has_record": False,
                "group": group,
                "equipment_type": None,
                "equipment_code": None,
                "outage_id": None,
                "line_id": None,
                "line_name": None,
                "station_id": None,
                "station_name": None,
                "location": None,
                "status_type": None,
                "status_class": "unknown",
                "ibb_date": None,
                "ibb_date_raw": None,
                "summary_inactive": summary.inactive if summary else None,
                "summary_consistent": summary.consistent if summary else None,
                "uncertainty": ",".join(snapshot.uncertainty),
            }
        )
    return rows


def iter_equipment_rows(lake_root: pathlib.Path | None = None) -> Iterator[dict[str, Any]]:
    """Read this source's local NDJSON.gz snapshots in stable path order."""
    root = lake_root if lake_root is not None else lake.lake_dir()
    for path in sorted((root / EQUIPMENT_SOURCE).rglob("*.ndjson.gz")):
        yield from lake.read_rows(path)


def equipment_fault_counts(lake_root: pathlib.Path | None = None) -> dict[str, int]:
    """Count distinct faulty snapshots by equipment code, or outage id when code is absent."""
    snapshots: dict[str, set[str]] = {}
    for row in iter_equipment_rows(lake_root):
        if row.get("has_record") is not True:
            continue
        key = row.get("equipment_code") or row.get("outage_id")
        stamp = row.get("snapshot_ts_utc")
        if key and stamp:
            snapshots.setdefault(str(key), set()).add(str(stamp))
    return {key: len(stamps) for key, stamps in snapshots.items()}


def snapshots_seen_faulty(equipment_code: str, lake_root: pathlib.Path | None = None) -> tuple[int, int]:
    """Return faulty and total distinct snapshots; an unseen code has a zero faulty count."""
    faulty: set[str] = set()
    total: set[str] = set()
    for row in iter_equipment_rows(lake_root):
        stamp = row.get("snapshot_ts_utc")
        if not stamp:
            continue
        total.add(str(stamp))
        if row.get("has_record") is True and row.get("equipment_code") == equipment_code:
            faulty.add(str(stamp))
    return len(faulty), len(total)
