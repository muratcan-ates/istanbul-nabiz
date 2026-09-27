"""Short-lived household outage confirmations, their private queue and sourced history."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import pathlib
import re
import sqlite3
import threading
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping
from typing import Any

from ibb_mcp.text import normalize_tr
from nabiz.console import text_guard
from nabiz.console.citizen_requests import HourlyLimit, new_code, per_hour
from nabiz.console.pii_guard import scan_pii
from nabiz.console.wiring import ledger_path
from nexus_core.ledger import Ledger

PATH_ENV = "NABIZ_OUTAGE_DB_PATH"
# Seven days is a short-lived queue design parameter, not a measured service target.
TTL_DAYS = 7
REPEAT_MINUTES = 30
MAX_NOTE = 280
MAX_NEIGHBOURHOOD = 40
SIGNAL_KIND = LEDGER_KIND = "outage_confirmation"
SEEN_KIND = "outage_seen"
_ADDRESS_MARKERS = re.compile(r"\b(?:sokak|sok|cadde|cad|bulvar|bulv|apartman|daire|kapı|bina|adres)\b|\bno\s*\.?\s*\d", re.I)
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
OUTAGE_DIR = REPO_ROOT / "data" / "reference" / "outage_watch"
SOURCES_PATH = OUTAGE_DIR / "outage_sources.json"
CAPTURE_PATH = OUTAGE_DIR / "su_kesintileri_2023_2024.json"
AGENCIES_PATH = REPO_ROOT / "data" / "agencies.json"

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS outage_reports ("
    " code TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,"
    " expires_at TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('waiting', 'seen')) ,"
    " district TEXT NOT NULL, neighbourhood TEXT NOT NULL, data TEXT NOT NULL);"
    " CREATE INDEX IF NOT EXISTS outage_reports_expiry ON outage_reports (expires_at);"
)


def outage_path(env: Mapping[str, str] | None = None) -> pathlib.Path:
    """Use an explicit store path, else place the outage table beside the decision ledger."""
    values = os.environ if env is None else env
    raw = (values.get(PATH_ENV) or "").strip()
    return pathlib.Path(raw) if raw else ledger_path(env).with_name("outage_watch.db")


def _agencies() -> dict[str, Any]:
    try:
        return json.loads(AGENCIES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"districts": [], "district_aliases": {}}


def districts() -> list[str]:
    """The district list used by both the API and validation."""
    return list(_agencies().get("districts") or [])


def normal_district(raw: str | None) -> str | None:
    """Resolve a district or its listed alias to the official spelling."""
    key = normalize_tr(raw)
    if not key:
        return None
    data = _agencies()
    lookup = {normalize_tr(name): name for name in data.get("districts", [])}
    for alias, official in (data.get("district_aliases") or {}).items():
        if official in data.get("districts", []):
            lookup[normalize_tr(alias)] = official
    return lookup.get(key)


def normal_neighbourhood(raw: str | None) -> tuple[str, int] | None:
    """Strip invisible characters and accept a short place name, never an address or identifier."""
    if raw is None:
        return None
    text, removed = text_guard.strip_invisible(raw)
    text = text.strip()
    if not 2 <= len(text) <= MAX_NEIGHBOURHOOD or not all(ch.isalpha() or ch.isdigit() or ch in " .’'" for ch in text):
        return None
    if _ADDRESS_MARKERS.search(text) or scan_pii(text):
        return None

    def title_word(word: str) -> str:
        lower = word.translate(str.maketrans({"I": "ı", "İ": "i"})).lower()
        first = {"i": "İ", "ı": "I"}.get(lower[:1], lower[:1].upper())
        return first + lower[1:]

    return " ".join(title_word(word) for word in text.split()), removed


def _now(clock: Any) -> dt.datetime:
    value = clock()
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def ledger_confirmation(ledger: Ledger, row: Mapping[str, Any]) -> int:
    """Record only area, code and lengths in the append-only ledger."""
    entry = ledger.append(
        LEDGER_KIND,
        actor="vatandaş (anonim)",
        entity_id=f"outage_confirmation:{row['code']}",
        detail={
            "kind": LEDGER_KIND,
            "code": row["code"],
            "district": row["district"],
            "neighbourhood": row["neighbourhood"],
            "confirmations": len(row["confirmations"]),
            "note_chars": len(row.get("note_masked") or ""),
        },
    )
    return entry.id


def ledger_seen(ledger: Ledger, row: Mapping[str, Any], actor: str) -> int:
    """Record an operator's acknowledgement without copying the citizen note."""
    entry = ledger.append(
        SEEN_KIND,
        actor=actor or "operatör (simüle)",
        entity_id=f"outage_confirmation:{row['code']}",
        detail={
            "kind": SEEN_KIND,
            "code": row["code"],
            "district": row["district"],
            "neighbourhood": row["neighbourhood"],
            "confirmations": len(row["confirmations"]),
            "note_chars": len(row.get("note_masked") or ""),
        },
    )
    return entry.id


class OutageStore:
    """The seven-day outage queue, separate from citizen requests."""

    def __init__(self, path: str | pathlib.Path | None = None, *, clock: Any = dt.datetime.now) -> None:
        self.path = pathlib.Path(path) if path is not None else outage_path()
        self.clock = clock
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
        self.purge()

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def now(self) -> dt.datetime:
        return _now(self.clock)

    def _purge(self, conn: sqlite3.Connection) -> int:
        return conn.execute("DELETE FROM outage_reports WHERE expires_at <= ?", (self.now().isoformat(),)).rowcount

    def purge(self) -> int:
        with self._lock, self._connect() as conn:
            return self._purge(conn)

    def create(
        self,
        district: str,
        neighbourhood: str,
        *,
        announced_end: str | None,
        note_masked: str | None,
        masked_count: int,
        masked_kinds: tuple[str, ...],
        lang: str,
    ) -> dict[str, Any]:
        self.purge()
        now = self.now()
        expires = now + dt.timedelta(days=TTL_DAYS)
        data = {
            "confirmations": [
                {"at": now.isoformat(), "source": "user", **({"announced_end": announced_end} if announced_end else {})}
            ],
            "note_masked": note_masked or None,
            "masked_count": masked_count,
            "masked_kinds": list(masked_kinds),
            "lang": lang,
        }
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for _ in range(8):
                    code = new_code()
                    if conn.execute("SELECT 1 FROM outage_reports WHERE code = ?", (code,)).fetchone() is None:
                        break
                else:
                    raise sqlite3.IntegrityError("could not allocate report code")
                conn.execute(
                    "INSERT INTO outage_reports VALUES (?, ?, ?, ?, 'waiting', ?, ?, ?)",
                    (
                        code,
                        now.isoformat(),
                        now.isoformat(),
                        expires.isoformat(),
                        district,
                        neighbourhood,
                        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return self.get(code) or {}

    def confirm_again(
        self,
        code: str,
        *,
        announced_end: str | None,
        note_masked: str | None = None,
        masked_count: int = 0,
        masked_kinds: tuple[str, ...] = (),
    ) -> dict[str, Any] | None:
        self.purge()
        now = self.now()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                record = conn.execute(
                    "SELECT * FROM outage_reports WHERE code = ? AND expires_at > ?", (code, now.isoformat())
                ).fetchone()
                if record is None:
                    conn.execute("COMMIT")
                    return None
                data = json.loads(record["data"])
                latest = dt.datetime.fromisoformat(data["confirmations"][-1]["at"])
                if now - latest < dt.timedelta(minutes=REPEAT_MINUTES):
                    conn.execute("COMMIT")
                    return None
                item = {"at": now.isoformat(), "source": "user"}
                if announced_end:
                    item["announced_end"] = announced_end
                data["confirmations"].append(item)
                if note_masked is not None:
                    data["note_masked"] = note_masked or None
                    data["masked_count"] = masked_count
                    data["masked_kinds"] = list(masked_kinds)
                conn.execute(
                    "UPDATE outage_reports SET updated_at = ?, data = ? WHERE code = ?",
                    (now.isoformat(), json.dumps(data, ensure_ascii=False, separators=(",", ":")), code),
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return self.get(code)

    def get(self, code: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            self._purge(conn)
            row = conn.execute("SELECT * FROM outage_reports WHERE code = ?", (code,)).fetchone()
            return _row(row) if row else None

    def items(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            self._purge(conn)
            if status in {"waiting", "seen"}:
                rows = conn.execute(
                    "SELECT * FROM outage_reports WHERE status = ? ORDER BY created_at DESC", (status,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM outage_reports ORDER BY created_at DESC").fetchall()
            return [_row(row) for row in rows]

    def mark_seen(self, code: str) -> dict[str, Any] | None:
        self.purge()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = conn.execute(
                    "UPDATE outage_reports SET status = 'seen' WHERE code = ? AND status = 'waiting' AND expires_at > ?",
                    (code, self.now().isoformat()),
                )
                conn.execute("COMMIT")
                if result.rowcount != 1:
                    return None
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return self.get(code)

    def rollback_seen(self, code: str) -> None:
        self.purge()
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE outage_reports SET status = 'waiting' WHERE code = ? AND status = 'seen'", (code,))

    def rollback_confirmation(self, code: str, expected_updated_at: str, previous: Mapping[str, Any]) -> None:
        self.purge()
        data = {key: previous.get(key) for key in ("confirmations", "note_masked", "masked_count", "masked_kinds", "lang")}
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE outage_reports SET updated_at = ?, data = ? WHERE code = ? AND updated_at = ?",
                (previous["updated_at"], json.dumps(data, ensure_ascii=False, separators=(",", ":")), code, expected_updated_at),
            )

    def discard(self, code: str) -> None:
        """Undo a just-created row when its required ledger entry could not be written."""
        self.purge()
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM outage_reports WHERE code = ?", (code,))

    def area_counts(self) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for row in self.items():
            key = (row["district"], row["neighbourhood"])
            area = grouped.setdefault(
                key, {"district": key[0], "neighbourhood": key[1], "waiting": 0, "confirmations": 0, "last_confirmation": None}
            )
            area["waiting"] += row["status"] == "waiting"
            confirmations = row["confirmations"]
            area["confirmations"] += len(confirmations)
            at = confirmations[-1]["at"] if confirmations else None
            if at and (area["last_confirmation"] is None or at > area["last_confirmation"]):
                area["last_confirmation"] = at
        return sorted(grouped.values(), key=lambda item: (-item["waiting"], item["district"], item["neighbourhood"]))


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "code": row["code"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "expires_at": row["expires_at"],
        "status": row["status"],
        "district": row["district"],
        "neighbourhood": row["neighbourhood"],
        **json.loads(row["data"]),
    }


def _column(header: list[str], *names: str) -> int | None:
    indexed = {normalize_tr(name): index for index, name in enumerate(header)}
    return next((indexed[normalize_tr(name)] for name in names if normalize_tr(name) in indexed), None)


def _year(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        serial = float(text)
    except ValueError:
        serial = -1
    if 20_000 <= serial <= 80_000:
        return (dt.datetime(1899, 12, 30) + dt.timedelta(days=serial)).year
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, fmt).year
        except ValueError:
            pass
    return None


def _neighbourhood_candidates(value: Any) -> set[str]:
    candidates = set()
    for raw_name in str(value or "").split(","):
        name = re.sub(r"\s*(?:mah(?:alle(?:si)?)?\.?)\s*$", "", raw_name.strip(), flags=re.I).strip()
        cleaned = normal_neighbourhood(name)
        if cleaned:
            candidates.add(cleaned[0])
    return candidates


def build_history(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce the open-data capture to district, neighbourhood and cause counts; drop work-site addresses."""
    header = snapshot.get("header")
    if not isinstance(header, list):
        raise ValueError("history header missing")
    district_i = _column(header, "ILCE", "İLÇE")
    neighbourhood_i = _column(header, "MAHALLE")
    cause_i = _column(header, "KESİNTİ SEBEP", "ARIZA SEBEBİ", "SEBEP")
    date_i = _column(header, "ARIZA KESİNTİ TARİHİ", "KESİNTİ TARİHİ", "TARİH")
    if None in (district_i, neighbourhood_i, cause_i, date_i):
        raise ValueError(f"history columns not found: {header!r}")
    grouped: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    rows = snapshot.get("rows")
    if not isinstance(rows, list):
        raise ValueError("history rows missing")
    for row in rows:
        if not isinstance(row, list) or max(district_i, neighbourhood_i, cause_i, date_i) >= len(row):
            continue
        year = _year(row[date_i])
        district = normal_district(str(row[district_i] or ""))
        cause = str(row[cause_i] or "").strip()
        if year not in {2023, 2024} or not district or not cause:
            continue
        for neighbourhood in _neighbourhood_candidates(row[neighbourhood_i]):
            grouped[(district, neighbourhood)][cause] += 1
    areas = []
    for (district, neighbourhood), causes in sorted(
        grouped.items(), key=lambda pair: (normalize_tr(pair[0][0]), normalize_tr(pair[0][1]))
    ):
        top = sorted(causes.items(), key=lambda item: (-item[1], normalize_tr(item[0])))[:3]
        areas.append(
            {
                "district": district,
                "neighbourhood": neighbourhood,
                "count": sum(causes.values()),
                "causes": [{"text": text, "count": count} for text, count in top],
            }
        )
    return {
        "period": "2023-2024",
        "dataset": snapshot.get("dataset"),
        "source_url": snapshot.get("source_url"),
        "license": snapshot.get("license"),
        "captured_at": snapshot.get("captured_at"),
        "capture_sha256": snapshot.get("sha256"),
        "source_records": len(rows),
        "areas": areas,
    }


def history_for(history: Mapping[str, Any], district: str, neighbourhood: str) -> dict[str, Any] | None:
    district_key, neighbourhood_key = normalize_tr(district), normalize_tr(neighbourhood)
    return next(
        (
            area
            for area in history.get("areas", [])
            if normalize_tr(area.get("district")) == district_key and normalize_tr(area.get("neighbourhood")) == neighbourhood_key
        ),
        None,
    )


def sources_data() -> dict[str, Any]:
    return json.loads(SOURCES_PATH.read_text(encoding="utf-8"))


def hourly_limit() -> HourlyLimit:
    return HourlyLimit(per_hour())
