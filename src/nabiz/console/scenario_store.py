"""Private SQLite storage for operator scenarios and a read-only E65 counter."""

from __future__ import annotations

import contextlib
import datetime as dt
import importlib
import json
import os
import pathlib
import secrets
import sqlite3
import threading
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from ibb_mcp.text import fold_tr
from nabiz.console.scenario import MAX_SAVED_PAIRS, route_from
from nabiz.console.wiring import ledger_path
from nexus_core.signals import Clock, as_utc, system_clock

PATH_ENV = "NABIZ_SCENARIOS_DB_PATH"
TTL_DAYS = 30
MAX_SAVED = 20
SCENARIO_CONSENT_VERSIONS: frozenset[str] = frozenset()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scenarios (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    station TEXT NOT NULL,
    line TEXT,
    routes TEXT NOT NULL,
    result TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS scenarios_expiry ON scenarios (expires_at);
"""


def scenarios_path(env: Mapping[str, str] | None = None) -> pathlib.Path:
    source = os.environ if env is None else env
    raw = (source.get(PATH_ENV) or "").strip()
    return pathlib.Path(raw) if raw else ledger_path(env).with_name("scenarios.db")


class ScenarioStore:
    """A bounded, expiring table with no operator or request identity columns."""

    def __init__(self, path: str | pathlib.Path | None = None, *, clock: Clock = system_clock) -> None:
        self.path = pathlib.Path(path) if path is not None else scenarios_path()
        self._clock = clock
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(_SCHEMA)
            self._purge(connection)

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA secure_delete = ON")
        try:
            yield connection
        finally:
            connection.close()

    def _now(self) -> dt.datetime:
        return as_utc(self._clock())

    def _purge(self, connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM scenarios WHERE expires_at <= ?", (self._now().isoformat(),))

    def add(self, station: str, line: str | None, routes: list[dict[str, Any]], result: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            self._purge(connection)
            now = self._now()
            row_id = f"scn-{secrets.token_hex(6)}"
            encoded_routes = json.dumps(routes, ensure_ascii=False)
            encoded_result = json.dumps(result, ensure_ascii=False)
            connection.execute(
                "INSERT INTO scenarios VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    row_id,
                    now.isoformat(),
                    (now + dt.timedelta(days=TTL_DAYS)).isoformat(),
                    station,
                    line,
                    encoded_routes,
                    encoded_result,
                ),
            )
            connection.execute(
                "DELETE FROM scenarios WHERE id IN ("
                "SELECT id FROM scenarios ORDER BY created_at DESC, id DESC LIMIT -1 OFFSET ?)",
                (MAX_SAVED,),
            )
            stored = connection.execute("SELECT * FROM scenarios WHERE id = ?", (row_id,)).fetchone()
        return self._row(stored)

    def items(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            self._purge(connection)
            rows = connection.execute(
                "SELECT id, created_at, station, line, result FROM scenarios ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                "id": row["id"],
                "station": row["station"],
                "line": row["line"],
                "created_at": row["created_at"],
                "counts": json.loads(row["result"]).get("counts", {}),
            }
            for row in rows
        ]

    def get(self, row_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            self._purge(connection)
            row = connection.execute("SELECT * FROM scenarios WHERE id = ?", (row_id,)).fetchone()
        return self._row(row) if row is not None else None

    def delete(self, row_id: str) -> None:
        with self._lock, self._connect() as connection:
            self._purge(connection)
            cursor = connection.execute("DELETE FROM scenarios WHERE id = ?", (row_id,))
        if not cursor.rowcount:
            raise LookupError(row_id)

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        result = json.loads(row["result"])
        return {
            "id": row["id"],
            "computed_at": row["created_at"],
            "station": row["station"],
            "line": row["line"],
            "routes": json.loads(row["routes"]),
            **result,
            "recomputed": False,
        }


@dataclass(frozen=True)
class SavedJourneyBatch:
    status: str
    pairs: tuple[tuple[dict[str, Any], int], ...] = ()
    considered: int = 0
    truncated: bool = False


class SavedJourneys:
    """Read only consented E65 route rows; never returns ids, accounts, or timestamps."""

    def __init__(
        self,
        path: str | pathlib.Path | None = None,
        *,
        clock: Clock = system_clock,
        module_available: bool | None = None,
        consent_versions: frozenset[str] | None = None,
    ) -> None:
        self.path = pathlib.Path(path) if path is not None else None
        self._clock = clock
        self._module_available = module_available
        self._consent_versions = SCENARIO_CONSENT_VERSIONS if consent_versions is None else consent_versions

    def _source_path(self) -> pathlib.Path:
        if self.path is not None:
            return self.path
        module = importlib.import_module("nabiz.console.journey_watch")
        env_name = getattr(module, "PATH_ENV", "NABIZ_JOURNEY_WATCH_DB_PATH")
        raw = os.environ.get(env_name, "").strip()
        if raw:
            return pathlib.Path(raw)
        for name in ("journeys_path", "journey_watch_path", "journey_path", "watch_path", "database_path"):
            helper = getattr(module, name, None)
            if callable(helper):
                return pathlib.Path(helper())
        return ledger_path().with_name("journey_watch.db")

    def status(self) -> str:
        """Check availability without selecting any journey rows."""
        try:
            if self._module_available is False:
                return "missing"
            if self._module_available is not True:
                importlib.import_module("nabiz.console.journey_watch")
            path = self._source_path()
        except ImportError:
            return "missing"
        if not path.is_file():
            return "no_table"
        if not self._consent_versions:
            return "consent_scope"
        try:
            uri = f"file:{path.resolve().as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=5) as connection:
                row = connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'journey_watch'").fetchone()
            return "ok" if row else "no_table"
        except sqlite3.OperationalError:
            return "no_table"

    def read(self) -> SavedJourneyBatch:
        try:
            if self._module_available is False:
                return SavedJourneyBatch("missing")
            if self._module_available is not True:
                importlib.import_module("nabiz.console.journey_watch")
            path = self._source_path()
        except ImportError:
            return SavedJourneyBatch("missing")
        if not path.is_file():
            return SavedJourneyBatch("no_table")
        if not self._consent_versions:
            return SavedJourneyBatch("consent_scope")
        now = as_utc(self._clock()).isoformat()
        marks = ",".join("?" for _ in self._consent_versions)
        sql = f"SELECT consent_version, expires_at, data FROM journey_watch WHERE expires_at > ? AND consent_version IN ({marks})"
        grouped: Counter[tuple[str, str, tuple[str, ...]]] = Counter()
        try:
            uri = f"file:{path.resolve().as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=5) as connection:
                rows = connection.execute(sql, (now, *sorted(self._consent_versions))).fetchall()
        except sqlite3.OperationalError:
            return SavedJourneyBatch("no_table")
        for _version, _expires, raw in rows:
            try:
                data = json.loads(raw)
                # E65 stores the pair as "from"/"to" (Journey.public); older drafts used "origin"/"destination".
                origin = data.get("from", data.get("origin"))
                destination = data.get("to", data.get("destination"))
                route = route_from({"from": origin, "to": destination, "needs": data.get("needs")})
            except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
                continue
            key = (fold_tr(route["from"]), fold_tr(route["to"]), tuple(route["needs"]))
            grouped[key] += 1
        ordered = sorted(grouped.items(), key=lambda item: item[0])
        considered = sum(grouped.values())
        chosen = ordered[:MAX_SAVED_PAIRS]
        pairs = tuple((route_from({"from": key[0], "to": key[1], "needs": key[2]}), count) for key, count in chosen)
        return SavedJourneyBatch("ok", pairs, considered, len(ordered) > MAX_SAVED_PAIRS)
