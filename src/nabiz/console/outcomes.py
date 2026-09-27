"""Privacy-safe outcome measures and their small, retained snapshots."""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sqlite3
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from nabiz.console.report_timeline import STAGES
from nabiz.console.wiring import ledger_path
from nexus_core.signals import as_utc, system_clock
from nexus_core.state import SignalState
from nexus_core.stats import MIN_RULINGS_FOR_WARNING

MIN_N, WINDOWS, DEFAULT_WINDOW = MIN_RULINGS_FOR_WARNING, (7, 30), 30
PATH_ENV, TTL_DAYS, MAX_SNAPSHOTS = "NABIZ_OUTCOMES_DB_PATH", 90, 500
SAVE_COOLDOWN = dt.timedelta(minutes=5)

# E66's stage names, not a copy: a resolution was reported, then confirmed, or reopened (a state outside STAGES).
RESOLUTION_REACHED = frozenset((*STAGES[STAGES.index("resolution_reported"):], "reopened"))
REQUEST_SOURCE, CARD_SOURCE, TIMELINE_SOURCE = (
    "Karar defteri, vatandaş talepleri", "Karar defteri, insan kararına giden kartlar", "Bildirim zaman çizgisi"
)
FIDELITY_SOURCE = "Bilgi dizini değerlendirmesi (çevrimdışı, eval/results/knowledge-calibration.md)"
FIDELITY_NOTE = "Altın dışı kaynak her zaman yanlış değildir. Bu, bilgi dizini ölçüsüdür; ürünün başarı oranı değildir."


@dataclass(frozen=True)
class OutcomeMetricSpec:
    label: str
    kind: str
    source: str
    note: str | None = None
    min_n: int = MIN_N


SPECS = {
    "o1_requests": OutcomeMetricSpec("İş tamamlanma: vatandaş talepleri", "ratio", REQUEST_SOURCE),
    "o2_reply_median": OutcomeMetricSpec("Yanıt bekleme süresi, ortanca", "duration", REQUEST_SOURCE),
    "o2_reply_p90": OutcomeMetricSpec("Yanıt bekleme süresi, 90. yüzdelik", "duration", REQUEST_SOURCE),
    "o1_cards": OutcomeMetricSpec("İş tamamlanma: insan kararı verilen kartlar", "ratio", CARD_SOURCE),
    "o2_decision_median": OutcomeMetricSpec("Taslak sonrası ilk insan kararı, ortanca", "duration", CARD_SOURCE),
    "o3_confirmed": OutcomeMetricSpec("Vatandaş teyidi", "ratio", TIMELINE_SOURCE),
    "o4_reopened": OutcomeMetricSpec("Yeniden açılma", "ratio", TIMELINE_SOURCE),
    "o5_first_source": OutcomeMetricSpec("İlk kaynağı altın sayfa olan cevaplar", "ratio", FIDELITY_SOURCE, FIDELITY_NOTE),
    "o5_negative_answers": OutcomeMetricSpec("Negatif kümede cevaplanan sorular", "ratio", FIDELITY_SOURCE, FIDELITY_NOTE),
}


class TimelineRows(list[dict[str, Any]]):
    """Rows read from E66, with a count of malformed rows that were skipped."""

    def __init__(self, rows: Iterable[dict[str, Any]] = (), *, skipped: int = 0) -> None:
        super().__init__(rows)
        self.skipped = skipped


class TooSoon(Exception):
    """A snapshot was saved less than five minutes ago."""


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)


def _time(value: Any) -> dt.datetime | None:
    try:
        return as_utc(value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value)))
    except (TypeError, ValueError):
        return None


def _in_window(value: Any, now: dt.datetime, days: int) -> bool:
    return (stamp := _time(value)) is not None and now - dt.timedelta(days=days) <= stamp <= now


def metric(key: str, spec: OutcomeMetricSpec, numerator: int | float | None, denominator: int | None) -> dict[str, Any]:
    """Return one rate or duration without calculating it below the shared sample threshold."""
    if spec.kind not in {"ratio", "duration"}:
        raise ValueError("kind must be ratio or duration")
    base = {
        "key": key, "label": spec.label, "kind": spec.kind, "numerator": numerator, "denominator": denominator,
        "value": None, "status": "unmeasured", "reason": "Bu ölçü için kaynak yok.",
        "source": spec.source, "note": spec.note,
    }
    if denominator is None:
        return base
    if denominator < spec.min_n:
        base["status"] = "insufficient"
        base["reason"] = f"En az {spec.min_n} örnek gerekir, şu an {denominator}."
        return base
    if numerator is None:
        return base
    base.update(status="measured", reason=None,
                value=round(100 * numerator / denominator) if spec.kind == "ratio" else round(numerator))
    return base


def _metric(key: str, numerator: int | float | None, denominator: int | None) -> dict[str, Any]:
    return metric(key, SPECS[key], numerator, denominator)


def _unmeasured(key: str, reason: str) -> dict[str, Any]:
    return {**_metric(key, None, None), "reason": reason}


def percentile(values: Iterable[float], q: int) -> int | None:
    """Nearest-rank percentile, rounded to whole seconds; no observations means no duration."""
    ordered = sorted(values)
    return round(ordered[max(0, min(len(ordered) - 1, (len(ordered) * q + 99) // 100 - 1))]) if ordered else None


def _entry_code(entry: Any) -> str:
    detail, entity = _field(entry, "detail", {}) or {}, str(_field(entry, "entity_id", "") or "").removeprefix("citizen_request:")
    return str((detail.get("code") or entity) if isinstance(detail, Mapping) else entity)


def request_metrics(entries: Iterable[Any], now: dt.datetime, days: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Count requests received in-window and use their first sealed operator reply."""
    current = as_utc(now)
    requests, replies = {}, {}
    for entry in entries:
        kind, stamp, code = _field(entry, "kind"), _time(_field(entry, "at")), _entry_code(entry)
        if not code or stamp is None:
            continue
        if kind == "citizen_request":
            requests.setdefault(code, entry)
        elif kind == "operator_reply":
            replies[code] = min(stamp, replies.get(code, stamp))
    recent = [row for row in requests.values() if _in_window(_field(row, "at"), current, days)]
    answered = [row for row in recent if _entry_code(row) in replies]
    waits = [max(0.0, (replies[_entry_code(row)] - _time(_field(row, "at"))).total_seconds()) for row in answered]
    waiting = [row for row in recent if _entry_code(row) not in replies]
    oldest = max((max(0, int((current - _time(_field(row, "at"))).total_seconds())) for row in waiting), default=None)
    metrics = [
        _metric("o1_requests", len(answered), len(recent)),
        _metric("o2_reply_median", percentile(waits, 50), len(answered)),
        _metric("o2_reply_p90", percentile(waits, 90), len(answered)),
    ]
    return metrics, {"waiting_count": len(waiting), "oldest_waiting_s": oldest}


def card_metrics(states: Iterable[SignalState], now: dt.datetime, days: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Measure Arena cards only; reflex closures are reported separately from human completion."""
    current, all_states = as_utc(now), list(states)
    cards = [s for s in all_states if s.path == "arena" and _in_window(s.received_at, current, days)]
    decided = [s.first_ruling for s in cards if s.first_ruling is not None]
    durations = [max(0.0, (s.first_ruling.at - s.drafted_at).total_seconds())
                 for s in cards if s.first_ruling is not None and s.drafted_at is not None]
    metrics = [_metric("o1_cards", sum(r.status in {"approved", "rejected"} for r in decided), len(cards)),
               _metric("o2_decision_median", percentile(durations, 50), len(decided))]
    counts = {
        "expired": sum(s.expired_at is not None for s in cards),
        "deferred_or_waiting": sum(s.status in {"deferred", "awaiting_approval"} for s in cards),
        "closed_by_reflex": sum(s.status == "closed_by_reflex" for s in all_states
                                 if _in_window(s.received_at, current, days)),
    }
    return metrics, counts


def _history(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [item for item in row.get("history", []) if isinstance(item, Mapping) and isinstance(item.get("stage"), str)]


def timeline_metrics(
    rows: Iterable[Mapping[str, Any]] | None, now: dt.datetime, days: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Measure resolution confirmation and reopen history; an absent E66 source stays unknown."""
    if rows is None:
        metrics = [_unmeasured(key, "Bildirim zaman çizgisi bu sürümde yok.")
                   for key in ("o3_confirmed", "o4_reopened")]
        return metrics, {"no_reply_7_days": None, "timeline_skipped": None}
    current = as_utc(now)
    recent = [r for r in rows if _in_window(r.get("created_at"), current, days)]
    reached = [r for r in recent if any(h.get("stage") == "resolution_reported" for h in _history(r))
               or r.get("stage") in RESOLUTION_REACHED]
    cutoff = current - dt.timedelta(days=7)
    no_reply = sum(
        row.get("stage") == "resolution_reported"
        and (max((stamp for h in _history(row) if h.get("stage") == "resolution_reported"
                  if (stamp := _time(h.get("at"))) is not None), default=_time(row.get("updated_at"))) or current) <= cutoff
        for row in recent
    )
    confirmed = sum(r.get("stage") == "confirmed" for r in reached)
    reopened = sum(int(r.get("reopen_count") or 0) > 0 for r in reached)
    metrics = [
        _metric("o3_confirmed", confirmed, len(reached)),
        _metric("o4_reopened", reopened, len(reached)),
    ]
    return metrics, {"no_reply_7_days": int(no_reply), "timeline_skipped": int(getattr(rows, "skipped", 0))}


def _tables(text: str) -> list[tuple[list[str], list[dict[str, str]]]]:
    result: list[tuple[list[str], list[dict[str, str]]]] = []
    for block in text.split("\n\n"):
        lines = [line for line in block.splitlines() if "|" in line]
        if len(lines) < 2:
            continue
        header = [cell.strip() for cell in lines[0].strip().strip("|").split("|")]
        rows = [dict(zip(header, cells, strict=True)) for line in lines[2:]
                if len(cells := [cell.strip() for cell in line.strip().strip("|").split("|")]) == len(header)]
        result.append((header, rows))
    return result


def _number(value: str | None) -> int | None:
    return int(value.strip()) if value and value.strip().isdecimal() else None


def fidelity_metrics(md_text: str | None) -> list[dict[str, Any]]:
    """Read only named totals from the offline calibration report; never infer missing values."""
    if md_text is None:
        return [_unmeasured(key, "Değerlendirme dosyası okunamadı.") for key in ("o5_first_source", "o5_negative_answers")]
    table_rows = [row for _, rows in _tables(md_text) for row in rows]
    summary = next((row for row in table_rows if row.get("Küme") == "negatif" and "n" in row), None)
    first_den = next((row for row in table_rows if row.get("Ölçü") == "Cevaplanan (answer/quote_only) ve altını olan"), None)
    first_num = next((row for row in table_rows if row.get("Ölçü", "").startswith("… ilk kaynağı altın URL")), None)
    negative_num = next((row for row in table_rows if row.get("Ölçü") == "Negatif kümede cevap (yanlış pozitif)"), None)
    a, b = _number(first_num.get("sonra") if first_num else None), _number(first_den.get("sonra") if first_den else None)
    c, d = _number(negative_num.get("sonra") if negative_num else None), _number(summary.get("n") if summary else None)
    return [
        _unmeasured("o5_first_source", "Değerlendirme dosyasında bu satır yok.") if a is None or b is None
        else _metric("o5_first_source", a, b),
        _unmeasured("o5_negative_answers", "Değerlendirme dosyasında bu satır yok.") if c is None or d is None
        else _metric("o5_negative_answers", c, d),
    ]


def board(
    *, entries: Iterable[Any] | None, states: Iterable[Any] | None,
    timeline_rows: Iterable[Mapping[str, Any]] | None, fidelity_md: str | None,
    now: dt.datetime, days: int,
) -> dict[str, Any]:
    """Build five outcome groups from already-read sources and an explicit time window."""
    if days not in WINDOWS:
        raise ValueError("Pencere 7 ya da 30 gün olmalı.")
    current = as_utc(now)
    request_result, request_counts = (request_metrics(entries, current, days) if entries is not None else (
        [_unmeasured(key, "Karar çekirdeği bu süreçte bağlı değil.")
         for key in ("o1_requests", "o2_reply_median", "o2_reply_p90")],
        {"waiting_count": None, "oldest_waiting_s": None}))
    cards, card_counts = (card_metrics(states, current, days) if states is not None else (
        [_unmeasured(key, "Karar çekirdeği bu süreçte bağlı değil.")
         for key in ("o1_cards", "o2_decision_median")],
        {"expired": None, "deferred_or_waiting": None, "closed_by_reflex": None}))
    timeline, timeline_counts = timeline_metrics(timeline_rows, current, days)
    fidelity = fidelity_metrics(fidelity_md)
    return {
        "window_days": days, "generated_at": current.isoformat(), "min_n": MIN_N,
        "groups": [
            {"key": "O1", "title": "İş tamamlanma", "metrics": [request_result[0], cards[0]],
             "counts": {**request_counts, **card_counts}},
            {"key": "O2", "title": "Yanıt bekleme süresi", "metrics": [*request_result[1:], cards[1]], "counts": {}},
            {"key": "O3", "title": "Vatandaş teyidi", "metrics": [timeline[0]], "counts": timeline_counts},
            {"key": "O4", "title": "Yeniden açılma", "metrics": [timeline[1]], "counts": {}},
            {"key": "O5", "title": "Kaynağa sadakat", "metrics": fidelity, "counts": {},
             "measured_at": None},
        ],
    }


def read_timeline(path: str | pathlib.Path | None = None, env: Mapping[str, str] | None = None) -> TimelineRows | None:
    """Read only E66's aggregate timeline fields; a missing file or table is not created."""
    raw = ((os.environ if env is None else env).get("NABIZ_REPORT_TIMELINE_DB_PATH") or "").strip()
    target = pathlib.Path(path or raw or ledger_path(env).with_name("report_timeline.db"))
    if not target.is_file():
        return None
    uri = target.resolve().as_uri() + "?mode=ro"
    rows: list[dict[str, Any]] = []
    skipped = 0
    try:
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            selected = conn.execute("SELECT stage, reopen_count, created_at, updated_at, expires_at, data "
                                    "FROM report_timeline WHERE expires_at > ?", (as_utc(system_clock()).isoformat(),)).fetchall()
    except sqlite3.Error:
        return None
    for row in selected:
        try:
            data = json.loads(row["data"])
            rows.append({"stage": row["stage"], "reopen_count": row["reopen_count"],
                         "created_at": row["created_at"], "updated_at": row["updated_at"],
                         "history": [{"stage": item["stage"], "at": item.get("at")}
                                     for item in (data.get("history", []) if isinstance(data, dict) else [])
                                     if isinstance(item, dict) and isinstance(item.get("stage"), str)]})
        except (TypeError, ValueError, KeyError):
            skipped += 1
    return TimelineRows(rows, skipped=skipped)


def read_fidelity(path: str | pathlib.Path | None = None) -> str | None:
    """Read the checked-in calibration report without running its producer."""
    target = pathlib.Path(path or pathlib.Path(__file__).resolve().parents[3] / "eval/results/knowledge-calibration.md")
    try:
        return target.read_text(encoding="utf-8")
    except OSError:
        return None


def snapshots_path(env: Mapping[str, str] | None = None) -> pathlib.Path:
    raw = (os.environ if env is None else env).get(PATH_ENV, "").strip()
    return pathlib.Path(raw) if raw else ledger_path(env).with_name("outcomes.db")


_SNAPSHOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS outcome_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, taken_at TEXT NOT NULL,
window_days INTEGER NOT NULL, expires_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS outcome_snapshots_expiry ON outcome_snapshots (expires_at);
"""


class SnapshotStore:
    """Store aggregate metric values for 90 days, enough for three-month comparisons."""

    def __init__(self, path: str | pathlib.Path | None = None, *, clock=system_clock) -> None:
        self.path, self._clock, self._lock = pathlib.Path(path) if path is not None else snapshots_path(), clock, threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.executescript(_SNAPSHOT_SCHEMA)
        self.purge()

    def now(self) -> dt.datetime:
        return as_utc(self._clock())

    def _purge(self, conn: sqlite3.Connection) -> int:
        return conn.execute("DELETE FROM outcome_snapshots WHERE expires_at <= ?", (self.now().isoformat(),)).rowcount

    def purge(self) -> int:
        with self._lock, sqlite3.connect(self.path) as conn:
            return self._purge(conn)

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return None if row is None else dict(
            taken_at=row["taken_at"], window_days=row["window_days"], metrics=json.loads(row["data"])
        )

    def latest(self, window_days: int | None = None) -> dict[str, Any] | None:
        with self._lock, sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            self._purge(conn)
            now = self.now().isoformat()
            where, params = (" AND window_days=?", (now, window_days)) if window_days is not None else ("", (now,))
            row = conn.execute(f"SELECT * FROM outcome_snapshots WHERE expires_at>?{where} ORDER BY id DESC LIMIT 1",
                               params).fetchone()
            return self._row(row)

    def next_save_at(self) -> dt.datetime | None:
        latest = self.latest()
        return (stamp + SAVE_COOLDOWN) if (stamp := _time(latest["taken_at"]) if latest else None) else None

    def save(self, data: dict[str, Any]) -> dict[str, Any]:
        now = self.now()
        metrics = [{key: item.get(key) for key in ("key", "status", "numerator", "denominator", "value")}
                   for group in data["groups"] for item in group["metrics"]]
        payload = json.dumps(metrics, ensure_ascii=False, separators=(",", ":"))
        expires = (now + dt.timedelta(days=TTL_DAYS)).isoformat()
        with self._lock, sqlite3.connect(self.path, timeout=10, isolation_level=None) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            self._purge(conn)
            latest = conn.execute("SELECT taken_at FROM outcome_snapshots ORDER BY id DESC LIMIT 1").fetchone()
            previous_at = _time(latest["taken_at"]) if latest else None
            if previous_at is not None and now - previous_at < SAVE_COOLDOWN:
                conn.execute("ROLLBACK")
                raise TooSoon
            cursor = conn.execute(
                "INSERT INTO outcome_snapshots (taken_at, window_days, expires_at, data) VALUES (?, ?, ?, ?)",
                (now.isoformat(), data["window_days"], expires, payload),
            )
            conn.execute("DELETE FROM outcome_snapshots WHERE id IN "
                         "(SELECT id FROM outcome_snapshots ORDER BY id DESC LIMIT -1 OFFSET ?)", (MAX_SNAPSHOTS,))
            conn.execute("COMMIT")
            return {"id": cursor.lastrowid, "taken_at": now.isoformat(), "window_days": data["window_days"]}
