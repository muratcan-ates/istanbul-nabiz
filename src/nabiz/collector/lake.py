"""Where a snapshot goes to become history.

The collector must keep working in three quite different places, so the backend is
chosen from the environment rather than compiled in:

* **This laptop, today.** Neither ``deltalake`` nor ``pyarrow`` is installed, PyPI is
  slow from here, and the collector had to start filling the lake on Day 0 — so the
  default is gzipped newline-delimited JSON, which needs nothing but the standard
  library. Nothing about the layout depends on that choice.
* **This laptop with the ``collector`` extra installed.** ``deltalake`` + ``pyarrow``
  turn the same rows into a Delta table: ACID commits make a retried timer idempotent
  instead of a duplicate-row problem, and time travel answers "what did we know at
  08:00?" when auditing a wrong ETA (DECISIONS.md §6).
* **Azure Functions.** ``AZURE_STORAGE_ACCOUNT`` switches the whole thing to ADLS Gen2
  via ``azure-storage-blob``, authenticating with the Function's managed identity.

Every backend writes the *same* Hive-style layout, because that is what makes the choice
reversible::

    <source>/year=2026/month=09/day=08/hour=07/20260908T071500Z-<uuid>.ndjson.gz

**Idempotency, and its exact limit.** The file name carries the snapshot timestamp
truncated to the second *and* a UUID derived from the content, so a write repeated inside
the same second with identical rows produces the identical name and overwrites itself
instead of appending a second copy. That is the whole guarantee: a retry a minute later
carries a later tick time and therefore writes a second file, and rows that differ at all
always write a new file — a real second observation, not a duplicate. Deduplication across
ticks is the reader's job (``arg_max`` on ``snapshot_ts_utc``), not the file name's.

The Azure imports live inside the functions on purpose: this module must import cleanly
in the test suite and on a machine that has never seen an Azure SDK.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import gzip
import hashlib
import json
import logging
import os
import pathlib
import uuid
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("nabiz.collector.lake")

#: Namespace for the content-derived file UUID. Fixed forever: changing it would rename
#: every future file and break the "same rows, same name" guarantee across versions.
NAMESPACE = uuid.UUID("6f0f6c1a-6b52-5f0a-9a7f-2d9b0f6a4c31")

DEFAULT_LAKE_DIR = "data/lake"
DEFAULT_CONTAINER = "bronze"

ENV_LAKE_DIR = "NABIZ_LAKE_DIR"
ENV_LAKE_FORMAT = "NABIZ_LAKE_FORMAT"
ENV_CONTAINER = "NABIZ_LAKE_CONTAINER"
ENV_ACCOUNT = "AZURE_STORAGE_ACCOUNT"
ENV_CONNECTION_STRING = "AZURE_STORAGE_CONNECTION_STRING"

JSON_EXT = "ndjson.gz"


@dataclass(frozen=True)
class LakeWriteResult:
    """What a write actually did. Logged by the timer as its one-line summary."""

    backend: str
    path: str
    rows: int
    bytes_written: int = 0
    skipped: bool = False

    def __str__(self) -> str:
        if self.skipped:
            return f"{self.backend}: nothing to write"
        return f"{self.backend}: {self.rows} rows, {self.bytes_written} B -> {self.path}"


# --------------------------------------------------------------------------------------
# naming and encoding
# --------------------------------------------------------------------------------------
def partition_path(source: str, snapshot_ts: dt.datetime) -> str:
    """Hive-style partition directory for one tick, in UTC.

    Hour granularity matches the slowest timer and keeps the fastest one (fleet, every
    two minutes) at 30 files per directory — small enough to list, large enough that a
    day's query touches 24 prefixes rather than 720.
    """
    stamp = _as_utc(snapshot_ts)
    return f"{source}/year={stamp:%Y}/month={stamp:%m}/day={stamp:%d}/hour={stamp:%H}"


def object_name(source: str, snapshot_ts: dt.datetime, payload: bytes, ext: str = JSON_EXT) -> str:
    """File name for one snapshot: sortable timestamp plus a content-derived UUID.

    The UUID is ``uuid5`` over the source, the tick and a digest of the bytes, which is
    what makes a repeated write land on the file it already wrote.

    ``microsecond`` is dropped deliberately. The visible prefix has always been
    second-precision, so keeping microseconds in the hashed part made the name depend on a
    field the name does not show: two writes of byte-identical rows within one second
    produced two files, and the caller is ``run_job``, which stamps every tick with
    ``datetime.now(UTC)``. Truncating makes the name a function of exactly what it
    displays — source, second, content.
    """
    stamp = _as_utc(snapshot_ts).replace(microsecond=0)
    digest = hashlib.sha256(payload).hexdigest()
    name = uuid.uuid5(NAMESPACE, f"{source}|{stamp.isoformat()}|{digest}")
    return f"{stamp:%Y%m%dT%H%M%SZ}-{name}.{ext}"


def encode_ndjson(rows: list[dict[str, Any]]) -> bytes:
    """One compact JSON object per line — the format ADX ingests as ``DataFormat.JSON``."""
    lines = (json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str) for row in rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def encode_ndjson_gz(rows: list[dict[str, Any]]) -> bytes:
    """Gzipped NDJSON. ``mtime=0`` so identical rows always give identical bytes."""
    return gzip.compress(encode_ndjson(rows), mtime=0)


def decode_ndjson_gz(payload: bytes) -> list[dict[str, Any]]:
    """Inverse of :func:`encode_ndjson_gz`; used by tests and by any local backfill."""
    text = gzip.decompress(payload).decode("utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def read_rows(path: str | pathlib.Path) -> list[dict[str, Any]]:
    """Read back one local snapshot file."""
    return decode_ndjson_gz(pathlib.Path(path).read_bytes())


# --------------------------------------------------------------------------------------
# backend selection
# --------------------------------------------------------------------------------------
def lake_dir() -> pathlib.Path:
    return pathlib.Path(os.getenv(ENV_LAKE_DIR, DEFAULT_LAKE_DIR)).expanduser()


def _delta_available() -> bool:
    """Whether both halves of the Delta stack can actually be imported."""
    try:  # pragma: no cover - depends on the optional 'collector' extra
        import deltalake  # noqa: F401
        import pyarrow  # noqa: F401
    except ImportError:
        return False
    return True


def choose_backend() -> str:
    """Resolve the backend name from the environment.

    ``NABIZ_LAKE_FORMAT`` forces ``delta`` or ``json`` locally; ``auto`` (the default)
    uses Delta when its wheels are present. A forced ``delta`` without the wheels falls
    back with a warning rather than failing the tick — losing a snapshot is worse than
    losing a file format.
    """
    if os.getenv(ENV_ACCOUNT):
        return "blob"
    wanted = os.getenv(ENV_LAKE_FORMAT, "auto").strip().lower()
    if wanted == "json":
        return "local-json"
    if wanted in {"delta", "auto"}:
        if _delta_available():
            return "local-delta"
        if wanted == "delta":
            log.warning("%s=delta but deltalake/pyarrow are not installed; writing NDJSON.gz", ENV_LAKE_FORMAT)
    return "local-json"


# --------------------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------------------
def write_rows(
    source: str,
    rows: list[dict[str, Any]],
    *,
    snapshot_ts: dt.datetime | None = None,
    backend: str | None = None,
) -> LakeWriteResult:
    """Persist one snapshot. Synchronous; the timer calls :func:`awrite_rows`.

    An empty ``rows`` is a no-op by design: :mod:`nabiz.collector.snapshots` returns
    ``[]`` precisely when a tick learned nothing, and writing an empty file would turn
    "İBB was unreachable" into a record that looks like data.
    """
    stamp = _as_utc(snapshot_ts or dt.datetime.now(dt.UTC))
    if not rows:
        return LakeWriteResult(backend=backend or choose_backend(), path="", rows=0, skipped=True)

    chosen = backend or choose_backend()
    if chosen == "blob":
        return _write_blob(source, rows, stamp)
    if chosen == "local-delta":
        return _write_delta(source, rows, stamp)
    return _write_local_json(source, rows, stamp)


async def awrite_rows(
    source: str,
    rows: list[dict[str, Any]],
    *,
    snapshot_ts: dt.datetime | None = None,
    backend: str | None = None,
) -> LakeWriteResult:
    """Async wrapper. Both the Azure SDK and the Delta writer block, so they go to a thread."""
    return await asyncio.to_thread(write_rows, source, rows, snapshot_ts=snapshot_ts, backend=backend)


def _write_local_json(source: str, rows: list[dict[str, Any]], stamp: dt.datetime) -> LakeWriteResult:
    payload = encode_ndjson_gz(rows)
    directory = lake_dir() / partition_path(source, stamp)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / object_name(source, stamp, payload)
    target.write_bytes(payload)
    return LakeWriteResult(backend="local-json", path=str(target), rows=len(rows), bytes_written=len(payload))


def _write_delta(source: str, rows: list[dict[str, Any]], stamp: dt.datetime) -> LakeWriteResult:
    """Append one snapshot to a partitioned Delta table.

    The partition columns are added to the rows so ``write_deltalake`` lays the files out
    under exactly the path :func:`partition_path` describes; the Delta log, not the file
    name, is what makes a retried commit safe here.
    """
    from deltalake import write_deltalake

    table_uri = str(lake_dir() / source)
    partitioned = [{**row, **_partition_columns(stamp)} for row in rows]
    write_deltalake(
        table_uri,
        partitioned,
        mode="append",
        partition_by=["year", "month", "day", "hour"],
    )
    return LakeWriteResult(
        backend="local-delta",
        path=table_uri,
        rows=len(rows),
        # The Delta writer reports no byte count, so this is the NDJSON-equivalent size of
        # the same rows — an order-of-magnitude figure for the log line, not the bytes
        # Parquet actually wrote. Named in the log as such rather than left to imply more.
        bytes_written=len(encode_ndjson(rows)),
    )


def _write_blob(source: str, rows: list[dict[str, Any]], stamp: dt.datetime) -> LakeWriteResult:
    """Upload one snapshot to ADLS Gen2 / Blob Storage.

    Auth order is connection string (local ``func start``) then
    ``DefaultAzureCredential``, which resolves to the Function's managed identity in
    Azure. ``overwrite=True`` is safe *because* the name is content-derived: the only
    blob it can replace is a byte-identical one.
    """
    from azure.storage.blob import BlobServiceClient

    account = os.environ[ENV_ACCOUNT]
    container = os.getenv(ENV_CONTAINER, DEFAULT_CONTAINER)
    payload = encode_ndjson_gz(rows)
    blob_path = f"{partition_path(source, stamp)}/{object_name(source, stamp, payload)}"

    connection_string = os.getenv(ENV_CONNECTION_STRING)
    if connection_string:
        service = BlobServiceClient.from_connection_string(connection_string)
    else:
        from azure.identity import DefaultAzureCredential

        service = BlobServiceClient(
            account_url=f"https://{account}.blob.core.windows.net",
            credential=DefaultAzureCredential(),
        )

    blob = service.get_blob_client(container=container, blob=blob_path)
    blob.upload_blob(payload, overwrite=True)
    return LakeWriteResult(
        backend="blob",
        path=f"{container}/{blob_path}",
        rows=len(rows),
        bytes_written=len(payload),
    )


def _partition_columns(stamp: dt.datetime) -> dict[str, str]:
    return {
        "year": f"{stamp:%Y}",
        "month": f"{stamp:%m}",
        "day": f"{stamp:%d}",
        "hour": f"{stamp:%H}",
    }


def _as_utc(moment: dt.datetime) -> dt.datetime:
    return moment.replace(tzinfo=dt.UTC) if moment.tzinfo is None else moment.astimezone(dt.UTC)
