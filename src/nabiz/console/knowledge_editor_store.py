"""Persistence and read-only knowledge-index access for the knowledge editor."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import pathlib
import sqlite3
import threading
from typing import Any

from ibb_mcp.knowledge.store import KnowledgeStore
from ibb_mcp.text import looks_like_instruction
from nabiz.console.citizen_requests import TTL_DAYS
from nabiz.console.pii_guard import mask_labels
from nabiz.console.policy import refuses
from nabiz.console.wiring import ledger_path
from nexus_core.ledger import Ledger

from .knowledge_editor import TOP_K, canonical, gap_from_measure

_JSONL_LOCK = threading.Lock()
_RETENTION_DAYS = 180
_ACTOR = "simulated-operator"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS ked_tags (
 ref TEXT PRIMARY KEY, tag TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ked_candidates (
 id INTEGER PRIMARY KEY, url TEXT NOT NULL, canonical_url TEXT NOT NULL, host TEXT NOT NULL,
 category TEXT NOT NULL, gap_refs TEXT NOT NULL, note TEXT NOT NULL, checks TEXT NOT NULL,
 created_at TEXT NOT NULL, actor TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ked_events (
 id INTEGER PRIMARY KEY, candidate_id INTEGER NOT NULL, kind TEXT NOT NULL, at TEXT NOT NULL,
 actor TEXT NOT NULL, reason TEXT, ledger_entry INTEGER, undoes INTEGER, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ked_trials (
 id INTEGER PRIMARY KEY, candidate_id INTEGER NOT NULL, at TEXT NOT NULL,
 fingerprint TEXT NOT NULL, summary TEXT NOT NULL, rows TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ked_scans (
 id INTEGER PRIMARY KEY, at TEXT NOT NULL, fingerprint TEXT NOT NULL, rows TEXT NOT NULL,
 expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ked_events_candidate ON ked_events(candidate_id, id);
CREATE INDEX IF NOT EXISTS ked_trials_candidate ON ked_trials(candidate_id, id);
"""


def knowledge_db_path(env: dict[str, str] | None = None) -> pathlib.Path:
    values = os.environ if env is None else env
    configured = pathlib.Path(values.get("NABIZ_KNOWLEDGE_DB", "data/knowledge/knowledge.db")).expanduser()
    return configured if configured.is_absolute() else pathlib.Path(__file__).resolve().parents[3] / configured


def open_readonly_index(path: pathlib.Path | None = None) -> KnowledgeStore | None:
    """Build a KnowledgeStore-compatible reader without running its mutating initializer."""
    index_path = path or knowledge_db_path()
    if not index_path.is_file():
        return None

    class ReadOnlyKnowledgeStore(KnowledgeStore):
        def __init__(self, db_path: pathlib.Path) -> None:
            self.path = db_path
            with self._connect() as db:
                self._fts_available = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks_fts'"
                ).fetchone() is not None

        def _connect(self) -> sqlite3.Connection:
            uri = self.path.resolve().as_uri() + "?mode=ro"
            db = sqlite3.connect(uri, uri=True, timeout=15)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            return db

    return ReadOnlyKnowledgeStore(index_path)


def active_canonical_urls(db_path: pathlib.Path) -> set[str]:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    with contextlib.closing(sqlite3.connect(uri, uri=True)) as db:
        rows = db.execute("SELECT url, canonical_url FROM documents WHERE active=1").fetchall()
    return {canonical(url or source) for url, source in rows}


def _safe_trial_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = ("ref", "mode", "top_url", "candidate_rank", "level")
    return [{key: row.get(key) for key in fields} for row in rows]


async def measure_rows(
    store: KnowledgeStore,
    questions: list[dict[str, Any]],
    *,
    db_path: pathlib.Path | None = None,
    candidate_url: str | None = None,
) -> list[dict[str, Any]]:
    """Apply the product's offline search and answer rules to a bounded set of questions."""
    from ibb_mcp.knowledge import answer, search
    from ibb_mcp.knowledge.answer import assess_evidence, evidence_thresholds

    index_path = db_path or knowledge_db_path()
    all_active_urls = active_canonical_urls(index_path)
    measured = []
    for item in questions:
        question = str(item.get("search_question") or item.get("question") or "")
        sensitive = refuses(question)
        hits = [hit for hit in await search(store, question, embedder=None, limit=TOP_K)
                if not looks_like_instruction(hit.quote)]
        evidence = assess_evidence(hits, query=question, **evidence_thresholds())
        result = await answer(question, store=store, embedder=None, sensitive=sensitive)
        gold = {canonical(value) for value in item.get("gold_urls", [])}
        ranks = [index for index, hit in enumerate(hits, start=1) if canonical(hit.url) in gold]
        candidate_rank = next((index for index, hit in enumerate(hits, start=1)
                               if candidate_url and canonical(hit.url) == canonical(candidate_url)), None)
        top = hits[0] if hits else None
        row = {
            **item,
            "excerpt": mask_labels(str(item.get("question") or question))[0][:120],
            "sensitive": sensitive,
            "active_urls": [url for url in item.get("gold_urls", []) if canonical(url) in all_active_urls],
            "as_of": dt.datetime.now(dt.UTC).isoformat(),
            "mode": "refused" if result.refused else result.mode,
            "level": evidence.level,
            "top_url": top.url if top else None,
            "top_title": top.title if top else None,
            "top_institution": top.institution if top else None,
            "top_fetched_at": top.fetched_at if top else None,
            "top_source_updated_at": top.source_updated_at if top else None,
            "top_updated_at_method": "source_updated_at" if top and top.source_updated_at else "fetched",
            "gold_rank": ranks[0] if ranks else None,
            "candidate_rank": candidate_rank,
            "candidate_indexed": bool(candidate_url and canonical(candidate_url) in all_active_urls),
            "top_is_gold": bool(gold and top and canonical(top.url) in gold),
        }
        gap = gap_from_measure(row)
        measured.append(gap if gap is not None else row)
    return measured


class KnowledgeEditorStore:
    """Short-lived editor state; question text is never copied into this database."""

    def __init__(
        self,
        db_path: str | pathlib.Path | None = None,
        *,
        source_path: str | pathlib.Path | None = None,
        ledger: Ledger | None = None,
    ) -> None:
        default_db = ledger_path().with_name("knowledge_editor.db")
        self.path = pathlib.Path(db_path or os.environ.get("NABIZ_KNOWLEDGE_EDITOR_DB_PATH") or default_db)
        raw_source = source_path or os.environ.get("NABIZ_SOURCE_CANDIDATES_PATH")
        self.source_path = pathlib.Path(raw_source) if raw_source else knowledge_db_path().parent / "source_candidates.jsonl"
        if not self.source_path.is_absolute():
            self.source_path = pathlib.Path(__file__).resolve().parents[3] / self.source_path
        self.ledger = ledger
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(_SCHEMA)
        self.purge()

    @contextlib.contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    def now() -> str:
        return dt.datetime.now(dt.UTC).isoformat()

    def _purge(self, db: sqlite3.Connection) -> None:
        now = self.now()
        for table in ("ked_tags", "ked_candidates", "ked_events", "ked_trials", "ked_scans"):
            db.execute(f"DELETE FROM {table} WHERE expires_at <= ?", (now,))

    def purge(self) -> None:
        with self._connect() as db:
            self._purge(db)

    def tags(self) -> dict[str, dict[str, str]]:
        with self._connect() as db:
            self._purge(db)
            rows = db.execute("SELECT ref, tag, actor, at FROM ked_tags").fetchall()
        return {row["ref"]: dict(row) for row in rows}

    def set_tag(self, ref: str, tag: str) -> dict[str, str]:
        now = self.now()
        days = TTL_DAYS if ref.startswith("request:") else _RETENTION_DAYS
        expiry = (dt.datetime.fromisoformat(now) + dt.timedelta(days=days)).isoformat()
        value = {"ref": ref, "tag": tag, "actor": _ACTOR, "at": now}
        with self._connect() as db:
            self._purge(db)
            db.execute(
                "INSERT INTO ked_tags VALUES (?, ?, ?, ?, ?) ON CONFLICT(ref) DO UPDATE SET "
                "tag=excluded.tag, actor=excluded.actor, at=excluded.at, expires_at=excluded.expires_at",
                (ref, tag, _ACTOR, now, expiry),
            )
        return value

    def latest_scan(self) -> dict[str, Any] | None:
        with self._connect() as db:
            self._purge(db)
            row = db.execute("SELECT * FROM ked_scans ORDER BY id DESC LIMIT 1").fetchone()
        return {"at": row["at"], "fingerprint": json.loads(row["fingerprint"]), "rows": json.loads(row["rows"])} if row else None

    def save_scan(self, fingerprint: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        now = self.now()
        safe_rows = []
        fields = ("ref", "kind", "set", "id", "category", "group", "lang", "gold_urls", "active_urls",
                  "sensitive", "mode", "level", "top_url", "top_title", "top_institution", "gold_rank", "as_of",
                  "top_fetched_at", "top_source_updated_at", "top_updated_at_method", "why", "tag_suggested",
                  "stale_hint", "stale_at", "updated_at_method", "gold_rank_label")
        for row in rows:
            safe_rows.append({key: row.get(key) for key in fields if key in row})
        expiry = (dt.datetime.fromisoformat(now) + dt.timedelta(days=_RETENTION_DAYS)).isoformat()
        with self._connect() as db:
            self._purge(db)
            db.execute("INSERT INTO ked_scans(at, fingerprint, rows, expires_at) VALUES (?, ?, ?, ?)",
                       (now, json.dumps(fingerprint), json.dumps(safe_rows, ensure_ascii=False), expiry))
            db.execute("DELETE FROM ked_scans WHERE id NOT IN (SELECT id FROM ked_scans ORDER BY id DESC LIMIT 3)")
        return {"at": now, "fingerprint": fingerprint, "rows": safe_rows}

    def _ledger(self) -> Ledger:
        return self.ledger or Ledger(ledger_path())

    def _ledger_event(self, candidate_id: int, kind: str, url: str, host: str, reason: str | None,
                      summary: dict[str, Any] | None) -> int:
        detail = {"candidate_id": candidate_id, "url": url, "host": host, "event": kind,
                  "reason": reason, "trial": summary}
        ledger_kind = "knowledge_candidate_undone" if kind == "undone" else "knowledge_candidate"
        entry = self._ledger().append(ledger_kind, actor=_ACTOR, detail=detail, signal_id=None,
                                      entity_id=f"knowledge-candidate:{candidate_id}")
        return entry.id

    def _append_jsonl(self, candidate: dict[str, Any], kind: str, reason: str | None,
                      summary: dict[str, Any] | None, status: str) -> None:
        row = {
            "schema": 1, "event": kind, "candidate_id": candidate["id"], "url": candidate["url"],
            "canonical_url": candidate["canonical_url"], "host": candidate["host"],
            "category": candidate["category"], "gap_count": len(candidate["gap_refs"]),
            "trial": summary, "at": self.now(), "actor": _ACTOR, "reason": reason,
            "status_after": status, "source": "nabiz-console-knowledge-editor",
            "note": "Dizine alma ayrı adımdır; bu satır dizini değiştirmez.",
        }
        self.source_path.parent.mkdir(parents=True, exist_ok=True)
        with _JSONL_LOCK, self.source_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    @staticmethod
    def _candidate(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["gap_refs"] = json.loads(result.pop("gap_refs"))
        result["checks"] = json.loads(result.pop("checks"))
        result.pop("expires_at", None)
        return result

    def create_candidate(self, *, url: str, canonical_url: str, host: str, category: str,
                         gap_refs: list[str], note: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
        now = self.now()
        expiry = (dt.datetime.fromisoformat(now) + dt.timedelta(days=_RETENTION_DAYS)).isoformat()
        with self._connect() as db:
            self._purge(db)
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                "INSERT INTO ked_candidates(url, canonical_url, host, category, gap_refs, note, checks, "
                "created_at, actor, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (url, canonical_url, host, category, json.dumps(gap_refs), note, json.dumps(checks, ensure_ascii=False),
                 now, _ACTOR, expiry),
            )
            candidate_id = int(cursor.lastrowid)
            candidate = {"id": candidate_id, "url": url, "canonical_url": canonical_url, "host": host,
                         "category": category, "gap_refs": gap_refs, "note": note, "checks": checks,
                         "created_at": now, "actor": _ACTOR}
            ledger_id = self._ledger_event(candidate_id, "proposed", url, host, None, None)
            self._append_jsonl(candidate, "proposed", None, None, "proposed")
            db.execute("INSERT INTO ked_events(candidate_id, kind, at, actor, reason, ledger_entry, undoes, expires_at) "
                       "VALUES (?, 'proposed', ?, ?, NULL, ?, NULL, ?)",
                       (candidate_id, now, _ACTOR, ledger_id, expiry))
            db.execute("COMMIT")
        return candidate

    def candidates(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            self._purge(db)
            rows = db.execute("SELECT * FROM ked_candidates ORDER BY id DESC").fetchall()
            counts = {row["candidate_id"]: row["n"] for row in db.execute(
                "SELECT candidate_id, COUNT(*) AS n FROM ked_events WHERE kind='proposed' GROUP BY candidate_id"
            )}
        return [{**self._candidate(row), "gap_count": len(self._candidate(row)["gap_refs"]),
                 "events_count": counts.get(row["id"], 0)} for row in rows]

    def candidate(self, candidate_id: int) -> dict[str, Any] | None:
        with self._connect() as db:
            self._purge(db)
            row = db.execute("SELECT * FROM ked_candidates WHERE id=?", (candidate_id,)).fetchone()
            if row is None:
                return None
            events = db.execute("SELECT * FROM ked_events WHERE candidate_id=? ORDER BY id", (candidate_id,)).fetchall()
            trials = db.execute("SELECT * FROM ked_trials WHERE candidate_id=? ORDER BY id DESC LIMIT 3",
                                (candidate_id,)).fetchall()
        event_rows = [dict(item) for item in events]
        undone_by = {item["undoes"]: item["id"] for item in event_rows if item["kind"] == "undone"}
        rendered_events = [{"id": item["id"], "kind": item["kind"], "at": item["at"], "actor": item["actor"],
                            "reason": item["reason"], "ledger_entry": item["ledger_entry"],
                            "undoes": item["undoes"], "undone_by": undone_by.get(item["id"])} for item in event_rows]
        rendered_trials = [{"id": item["id"], "at": item["at"], "fingerprint": json.loads(item["fingerprint"]),
                            "summary": json.loads(item["summary"]), "rows": json.loads(item["rows"])} for item in trials]
        candidate = self._candidate(row)
        candidate.update({"events": rendered_events, "trials": list(reversed(rendered_trials))})
        return candidate

    def save_trial(self, candidate_id: int, fingerprint: dict[str, Any], summary: dict[str, Any],
                   rows: list[dict[str, Any]]) -> dict[str, Any]:
        now = self.now()
        expiry = (dt.datetime.fromisoformat(now) + dt.timedelta(days=_RETENTION_DAYS)).isoformat()
        safe_rows = _safe_trial_rows(rows)
        with self._connect() as db:
            self._purge(db)
            db.execute("INSERT INTO ked_trials(candidate_id, at, fingerprint, summary, rows, expires_at) "
                       "VALUES (?, ?, ?, ?, ?, ?)",
                       (candidate_id, now, json.dumps(fingerprint), json.dumps(summary),
                        json.dumps(safe_rows), expiry))
            db.execute("DELETE FROM ked_trials WHERE candidate_id=? AND id NOT IN "
                       "(SELECT id FROM ked_trials WHERE candidate_id=? ORDER BY id DESC LIMIT 3)",
                       (candidate_id, candidate_id))
            self._add_event(db, candidate_id, "tried", None, None)
        return {"at": now, "fingerprint": fingerprint, "summary": summary, "rows": safe_rows}

    def _add_event(self, db: sqlite3.Connection, candidate_id: int, kind: str, reason: str | None,
                   undoes: int | None, ledger_id: int | None = None) -> int:
        now = self.now()
        expiry = (dt.datetime.fromisoformat(now) + dt.timedelta(days=_RETENTION_DAYS)).isoformat()
        cursor = db.execute("INSERT INTO ked_events(candidate_id, kind, at, actor, reason, ledger_entry, undoes, expires_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (candidate_id, kind, now, _ACTOR, reason, ledger_id, undoes, expiry))
        return int(cursor.lastrowid)

    def add_decision(self, candidate_id: int, kind: str, reason: str,
                     summary: dict[str, Any] | None, status: str) -> dict[str, Any]:
        candidate = self.candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        ledger_id = self._ledger_event(candidate_id, kind, candidate["url"], candidate["host"], reason, summary)
        self._append_jsonl(candidate, kind, reason, summary, status)
        with self._connect() as db:
            self._purge(db)
            event_id = self._add_event(db, candidate_id, kind, reason, None, ledger_id)
        return {"id": event_id, "kind": kind, "ledger_entry": ledger_id, "at": self.now(), "actor": _ACTOR,
                "reason": reason}

    def undo(self, candidate_id: int, event_id: int, reason: str, status_after: str,
             summary: dict[str, Any] | None) -> dict[str, Any]:
        candidate = self.candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        event = next((item for item in candidate["events"] if item["id"] == event_id), None)
        if event is None or event["undone_by"] is not None or event["kind"] == "undone":
            raise ValueError("The event cannot be undone.")
        ledger_id = self._ledger_event(candidate_id, "undone", candidate["url"], candidate["host"], reason, summary)
        self._append_jsonl(candidate, "undone", reason, summary, status_after)
        with self._connect() as db:
            self._purge(db)
            new_id = self._add_event(db, candidate_id, "undone", reason, event_id, ledger_id)
        return {"id": new_id, "kind": "undone", "at": self.now(), "actor": _ACTOR,
                "reason": reason, "ledger_entry": ledger_id, "undoes": event_id}
