"""Streaming ingestion into the Azure Data Explorer free cluster.

The free cluster is the reason this module looks the way it does. It is not an ordinary
ADX deployment and three of its limits shape every decision here (DECISIONS.md §1):

* **No ARM resource.** The cluster does not exist in the subscription, so it has no
  managed identity of its own and cannot be granted access to anything. All
  authentication is the *caller* proving who it is.
* **No data-management endpoint.** A normal cluster also publishes ``ingest-<name>``,
  which is where queued ingestion goes. The free cluster does not, so queued ingestion is
  simply unavailable and everything here is **streaming** ingestion against the engine
  endpoint. Each table needs the policy switched on explicitly — see
  :func:`streaming_policy_command`.
* **The caller's identity must be added by hand**, once, from a session already signed in
  as the cluster owner::

      .add database nabiz ingestors ('aadapp=<clientId>;<tenantId>')

  :func:`principal_command` prints that line for the Function's managed identity. Whether
  the free cluster accepts a headless principal from this student subscription is the
  unverified Day-0 gate in PLAN.md §10; if it refuses, the fallback is Azure SQL free and
  this module is the only place that changes.

Everything degrades to a logged no-op. With ``NABIZ_KUSTO_URI`` unset — the state on this
machine and in CI — :class:`KustoSink` reports itself disabled, says so once, and the
timers keep filling the lake. History that reaches the lake can always be ingested later;
a collector that crashes because an optional analytics store is missing loses the data
permanently.
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
from dataclasses import dataclass
from typing import Any

from nabiz.collector.lake import encode_ndjson

log = logging.getLogger("nabiz.collector.kusto")

ENV_URI = "NABIZ_KUSTO_URI"
ENV_DATABASE = "NABIZ_KUSTO_DB"
ENV_MI_CLIENT_ID = "NABIZ_KUSTO_MI_CLIENT_ID"
#: Override the credential choice: ``msi``, ``azcli`` or ``device``.
ENV_AUTH = "NABIZ_KUSTO_AUTH"

DEFAULT_DATABASE = "nabiz"


@dataclass(frozen=True)
class KustoTable:
    """One ADX table: the name and its ordered ``(column, KQL type)`` pairs."""

    name: str
    columns: tuple[tuple[str, str], ...]

    @property
    def mapping_name(self) -> str:
        return f"{self.name}_mapping"


#: The five tables the collector fills, keyed by the source name the snapshot functions
#: use. Column names match the snapshot row keys exactly, so the JSON ingestion mapping
#: below is generated rather than maintained.
#:
#: ``traffic_index_hourly`` deviates from the ``traffic_index_5m`` sketched in PLAN.md
#: §4.2: the collector samples hourly, and a table name that claims five-minute
#: resolution would be a lie told to every future query.
#:
#: There is deliberately no plate column anywhere in this file (DECISIONS.md §7), and the
#: free cluster's terms forbid personal data regardless.
TABLES: dict[str, KustoTable] = {
    "ispark_snapshot": KustoTable(
        "ispark_snapshot",
        (
            ("park_id", "int"),
            ("ts_utc", "datetime"),
            ("snapshot_ts_utc", "datetime"),
            ("capacity", "int"),
            ("empty", "int"),
            ("occupancy_pct", "real"),
            ("is_open", "bool"),
            ("district", "string"),
        ),
    ),
    "iett_fleet_snapshot": KustoTable(
        "iett_fleet_snapshot",
        (
            ("door_no", "string"),
            ("ts_utc", "datetime"),
            ("snapshot_ts_utc", "datetime"),
            ("lat", "real"),
            ("lon", "real"),
            ("speed_kmh", "real"),
        ),
    ),
    "metro_status": KustoTable(
        "metro_status",
        (
            ("line_id", "int"),
            ("line_name", "string"),
            ("description", "string"),
            ("is_active", "bool"),
            ("has_notice", "bool"),
            ("ts_utc", "datetime"),
            ("snapshot_ts_utc", "datetime"),
            ("color", "string"),
        ),
    ),
    "traffic_index_hourly": KustoTable(
        "traffic_index_hourly",
        (
            ("traffic_index", "int"),
            ("ts_utc", "datetime"),
            ("snapshot_ts_utc", "datetime"),
        ),
    ),
    "aq_hourly": KustoTable(
        "aq_hourly",
        (
            ("station_id", "string"),
            ("station_name", "string"),
            ("ts_utc", "datetime"),
            ("snapshot_ts_utc", "datetime"),
            ("pm10", "real"),
            ("so2", "real"),
            ("o3", "real"),
            ("no2", "real"),
            ("co", "real"),
            ("aqi_index", "real"),
            ("dominant", "string"),
        ),
    ),
}


# --------------------------------------------------------------------------------------
# control commands
# --------------------------------------------------------------------------------------
def create_merge_command(table: KustoTable) -> str:
    """``.create-merge table`` — creates the table, or adds only the columns it lacks.

    ``create-merge`` rather than ``create`` so this can run on every deployment: adding a
    column to :data:`TABLES` becomes a schema migration that keeps the existing rows,
    and re-running against an up-to-date cluster is a no-op.
    """
    columns = ", ".join(f"{name}:{kind}" for name, kind in table.columns)
    return f".create-merge table {table.name} ({columns})"


def streaming_policy_command(table: KustoTable) -> str:
    """Enable streaming ingestion for one table.

    Mandatory on the free cluster: without the data-management endpoint there is no
    queued path, so a table without this policy rejects every write the collector makes.
    """
    return f".alter table {table.name} policy streamingingestion enable"


def mapping_command(table: KustoTable) -> str:
    """Create the JSON ingestion mapping, generated from the same column list.

    An explicit mapping rather than relying on ADX's by-name default: it pins the
    contract between the snapshot row keys and the table, so a renamed key fails loudly
    at deployment instead of quietly ingesting nulls forever.
    """
    mapping = [
        {"column": name, "path": f"$.{name}", "datatype": kind}
        for name, kind in table.columns
    ]
    payload = json.dumps(mapping, ensure_ascii=False)
    return f".create-or-alter table {table.name} ingestion json mapping '{table.mapping_name}' '{payload}'"


def principal_command(client_id: str, tenant_id: str, *, database: str | None = None, role: str = "ingestors") -> str:
    """The one command a human must run in the free cluster's web UI, signed in as owner."""
    db = database or os.getenv(ENV_DATABASE, DEFAULT_DATABASE)
    return f".add database {db} {role} ('aadapp={client_id};{tenant_id}')"


def ensure_tables(*, execute: bool = False, database: str | None = None) -> list[str]:
    """Return every control command the cluster needs, optionally running them.

    Returning the commands is the primary mode: they are checked into ``kql/schema.kql``
    and pasted into the free cluster's web UI, which is the only interface guaranteed to
    work before the headless-auth gate has been passed. ``execute=True`` needs
    ``azure-kusto-data`` and a reachable cluster.
    """
    commands: list[str] = []
    for table in TABLES.values():
        commands.append(create_merge_command(table))
        commands.append(streaming_policy_command(table))
        commands.append(mapping_command(table))

    if execute:
        uri = os.environ[ENV_URI]
        db = database or os.getenv(ENV_DATABASE, DEFAULT_DATABASE)
        from azure.kusto.data import KustoClient

        client = KustoClient(_connection_string(uri))
        for command in commands:
            log.info("kusto: %s", command.split(" (")[0])
            client.execute_mgmt(db, command)
    return commands


# --------------------------------------------------------------------------------------
# ingestion
# --------------------------------------------------------------------------------------
def choose_auth() -> str:
    """Pick a credential: ``msi``, ``azcli`` or ``device``.

    Managed identity first, because that is how the deployed Function authenticates and
    it is the only one that works unattended. Az CLI second — a developer who has run
    ``az login`` needs no extra step — but only when the binary actually exists, which it
    does not on a Functions host. Device code last: it always works and always needs a
    human at a browser, so it must never be reachable in Azure.

    The check is on the environment rather than on a failed sign-in on purpose: a Kusto
    connection string builder is lazy, so an unusable az-cli credential would not fail
    until the first ingest, far too late to fall back to anything interactive.
    """
    forced = os.getenv(ENV_AUTH, "").strip().lower()
    if forced in {"msi", "azcli", "device"}:
        return forced
    if os.getenv(ENV_MI_CLIENT_ID):
        return "msi"
    if shutil.which("az"):
        return "azcli"
    return "device"


def _connection_string(uri: str) -> Any:
    """Build the connection string for whichever credential :func:`choose_auth` picked."""
    from azure.kusto.data import KustoConnectionStringBuilder

    auth = choose_auth()
    log.info("kusto: authenticating with %s", auth)
    if auth == "msi":
        return KustoConnectionStringBuilder.with_aad_managed_service_identity_authentication(
            uri, client_id=os.getenv(ENV_MI_CLIENT_ID)
        )
    if auth == "azcli":
        return KustoConnectionStringBuilder.with_az_cli_authentication(uri)
    return KustoConnectionStringBuilder.with_aad_device_authentication(uri)


class KustoSink:
    """Streaming ingest, or a no-op that says so once.

    One instance per process. The SDK client is built lazily on the first successful
    ingest so that importing this module — which the test suite and every local run do —
    never touches the network or an Azure SDK.
    """

    def __init__(self, uri: str | None = None, database: str | None = None) -> None:
        self.uri = uri if uri is not None else os.getenv(ENV_URI)
        self.database = database or os.getenv(ENV_DATABASE, DEFAULT_DATABASE)
        self._client: Any = None
        self._announced = False

    @property
    def enabled(self) -> bool:
        """Whether ingestion is configured *and* the SDK is importable."""
        if not self.uri:
            return False
        try:
            import azure.kusto.ingest  # noqa: F401
        except ImportError:
            return False
        return True

    def _announce_disabled(self) -> None:
        if self._announced:
            return
        self._announced = True
        if not self.uri:
            log.info("kusto: %s not set; ingestion disabled, snapshots go to the lake only", ENV_URI)
        else:
            log.warning(
                "kusto: %s is set but azure-kusto-ingest is not installed "
                "(pip install '.[collector]'); ingestion disabled",
                ENV_URI,
            )

    def client(self) -> Any:
        """The streaming ingest client, built on first use."""
        if self._client is None:
            from azure.kusto.ingest import KustoStreamingIngestClient

            self._client = KustoStreamingIngestClient(_connection_string(self.uri or ""))
        return self._client

    def ingest(self, source: str, rows: list[dict[str, Any]]) -> int:
        """Ingest one snapshot. Returns the number of rows accepted, ``0`` for a no-op.

        Never raises: a failed ingest is logged and the rows stay in the lake, which is
        the durable copy. The alternative — failing the timer — would cost the *next*
        snapshot too, and ADX is explicitly not on the critical path (DECISIONS.md §1).
        """
        if not rows:
            return 0
        table = TABLES.get(source)
        if table is None:
            log.error("kusto: no table defined for source %r; not ingesting", source)
            return 0
        if not self.enabled:
            self._announce_disabled()
            return 0

        try:
            from azure.kusto.data.data_format import DataFormat
            from azure.kusto.ingest import IngestionProperties

            properties = IngestionProperties(
                database=self.database,
                table=table.name,
                data_format=DataFormat.JSON,
                ingestion_mapping_reference=table.mapping_name,
            )
            self.client().ingest_from_stream(io.BytesIO(encode_ndjson(rows)), properties)
        except Exception as exc:  # noqa: BLE001 - the lake already holds the rows
            log.error("kusto: ingest into %s failed (%d rows kept in the lake): %r", table.name, len(rows), exc)
            return 0
        return len(rows)
