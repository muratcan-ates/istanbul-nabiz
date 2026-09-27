"""Operator API for offline knowledge gap review and source candidate decisions."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import pathlib
import sqlite3
from typing import Literal
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ibb_mcp.knowledge.ingest import robots_error_allows_all
from nabiz.console.citizen_requests import RequestStore, requests_path
from nabiz.console.feedback_api import feedback_counts
from nabiz.console.operator import port_problem
from nabiz.console.pii_guard import mask_labels, scan_pii

from .knowledge_editor import (
    MAX_EVAL_QUESTIONS,
    MAX_GAPS,
    MAX_LINKED_QUESTIONS,
    apply_events,
    canonical,
    check_candidate,
    compare_trials,
    gap_from_measure,
    group_gaps,
    summarize_trial,
)
from .knowledge_editor_store import (
    KnowledgeEditorStore,
    knowledge_db_path,
    measure_rows,
    open_readonly_index,
)

log = logging.getLogger("nabiz.console.knowledge_editor")
knowledge_editor_routes = APIRouter()
_BASE = "/api/console/knowledge-editor"


class TagBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: Literal["missing_source", "wrong_route", "stale", "not_a_gap"]


class CandidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)
    gap_refs: list[str] = Field(min_length=1, max_length=MAX_LINKED_QUESTIONS)
    note: str = Field(min_length=5, max_length=280)


class CandidateDecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "reject"]
    reason: str = Field(min_length=5, max_length=280)


class UndoBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=5, max_length=280)


def evaluation_questions(root: pathlib.Path | None = None) -> list[dict]:
    """Read committed eval sets without copying questions to editor storage."""
    repo = root or pathlib.Path(__file__).resolve().parents[3]
    result = []
    for short, name in (("kc", "knowledge_calibration.jsonl"), ("kq", "knowledge_questions.jsonl")):
        path = repo / "eval" / name
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            result.append({
                "ref": f"eval:{short}:{row['id']}", "kind": "eval", "set": short, "id": str(row["id"]),
                "question": row["question"], "gold_urls": row.get("gold_urls", []),
                "category": row.get("category") or row.get("group") or "Genel bilgi",
                "group": row.get("group"), "lang": row.get("lang") or "tr", "sensitive": bool(row.get("sensitive")),
            })
            if len(result) >= MAX_EVAL_QUESTIONS:
                return result
    return result


def request_questions(path: pathlib.Path | None = None) -> list[dict]:
    """Return unanswered, masked requests with references derived from hashed codes."""
    result = []
    for item in RequestStore(path or requests_path()).items(status="waiting", limit=MAX_GAPS):
        code = str(item.get("code", ""))
        original, _, _ = mask_labels(str(item.get("original_masked", "")))
        translated, _, _ = mask_labels(str(item.get("turkish") or original))
        result.append({
            "ref": "request:" + hashlib.sha256(code.encode("utf-8")).hexdigest()[:12],
            "kind": "request", "question": original, "search_question": translated or original,
            "category": item.get("category") or "Genel bilgi", "lang": item.get("lang") or "tr",
            "gold_urls": [], "sensitive": False,
        })
    return result


def index_fingerprint(db_path: pathlib.Path, store=None) -> dict:
    """Count active pages and read build metadata without writing to the index."""
    uri = db_path.resolve().as_uri() + "?mode=ro"
    with contextlib.closing(sqlite3.connect(uri, uri=True)) as db:
        count, latest = db.execute("SELECT COUNT(*), MAX(fetched_at) FROM documents WHERE active=1").fetchone()
    from nabiz.console.how_api import index_part

    return {"documents": int(count), "latest_fetched_at": latest,
            "built_at": index_part(store)["built_at"] if store is not None else latest}


def versions(db_path: pathlib.Path, url: str) -> list[dict]:
    """Return version metadata for a canonical URL, never the indexed body."""
    uri = db_path.resolve().as_uri() + "?mode=ro"
    wanted = canonical(url)
    with contextlib.closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT canonical_url, url, title, fetched_at, source_updated_at, updated_at_method, "
            "sha256, license_id, parser_status, active FROM documents ORDER BY fetched_at DESC"
        ).fetchall()
    return [{
        "active": bool(row["active"]), "fetched_at": row["fetched_at"],
        "source_updated_at": row["source_updated_at"], "updated_at_method": row["updated_at_method"],
        "sha256": str(row["sha256"] or "")[:8], "title": row["title"],
        "license_id": row["license_id"], "parser_status": row["parser_status"],
    } for row in rows if canonical(row["url"] or row["canonical_url"]) == wanted]


def robots_for(host: str, url: str, robots_dir: pathlib.Path | None = None) -> dict:
    """Evaluate a saved robots snapshot without requesting a URL."""
    root = robots_dir or knowledge_db_path().parent / "robots"
    text_path, json_path = root / f"{hashlib.sha256(host.encode()).hexdigest()}.txt", root / f"{host}.json"
    if text_path.is_file():
        parser = RobotFileParser()
        parser.set_url(f"https://{host}/robots.txt")
        try:
            parser.parse(text_path.read_text(encoding="utf-8").splitlines())
            return {"status": "parsed", "allowed": parser.can_fetch("NabizKnowledgeBot", url)}
        except (OSError, UnicodeError, ValueError):
            return {"status": "unavailable", "allowed": None}
    if json_path.is_file():
        try:
            snapshot = json.loads(json_path.read_text(encoding="utf-8"))
            detail, status = snapshot.get("robots_snapshot", {}), snapshot.get("status")
            if status == "robots-unavailable" or robots_error_allows_all(detail.get("status")):
                return {"status": "allows_all", "allowed": True}
            if status == "robots-unreachable":
                return {"status": "unavailable", "allowed": None}
        except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
            pass
        return {"status": "unavailable", "allowed": None}
    return {"status": "missing", "allowed": None}


def _index(store: KnowledgeEditorStore):
    return open_readonly_index(knowledge_db_path())


def _no_index() -> JSONResponse:
    return port_problem(503, "index_unavailable", "Bilgi dizini bu sunucuda yok.")


def _pii_error(text: str) -> JSONResponse | None:
    return port_problem(422, "personal_data", "Kişisel bilgi yazmayın.") if scan_pii(text) else None


def _eval_by_ref() -> dict[str, dict]:
    return {row["ref"]: row for row in evaluation_questions()}


def _saved_eval_gaps(store: KnowledgeEditorStore) -> tuple[list[dict], int, dict | None]:
    scan = store.latest_scan()
    if scan is None:
        return [], 0, None
    current = _eval_by_ref()
    gaps = []
    refusals = 0
    for saved in scan["rows"]:
        question = current.get(saved.get("ref"))
        if question is None:
            continue
        merged = {**question, **saved}
        gap = gap_from_measure(merged)
        if gap and gap.get("why") == "required_refusal":
            refusals += 1
        elif gap:
            gaps.append(gap)
    return gaps, refusals, {"at": scan["at"], "fingerprint": scan["fingerprint"]}


async def _current_gaps(store: KnowledgeEditorStore, index_store=None) -> tuple[list[dict], int, dict | None]:
    gaps, refusals, last_scan = _saved_eval_gaps(store)
    requests = request_questions(requests_path())
    if index_store is not None:
        measured = await measure_rows(index_store, requests, db_path=knowledge_db_path())
    else:
        measured = [gap_from_measure({**row, "mode": "unknown", "level": "out_of_scope", "top_url": None})
                    for row in requests]
        measured = [row for row in measured if row is not None]
    gaps.extend(row for row in measured if row.get("why") != "required_refusal")

    tags = store.tags()
    candidate_counts: dict[str, int] = {}
    for candidate in store.candidates():
        for ref in candidate["gap_refs"]:
            candidate_counts[ref] = candidate_counts.get(ref, 0) + 1
    for gap in gaps:
        gap["candidates"] = candidate_counts.get(str(gap.get("ref")), 0)
    gaps = [gap for gap in gaps if tags.get(str(gap.get("ref")), {}).get("tag") != "not_a_gap"]
    return gaps[:MAX_GAPS], refusals, last_scan


def _feedback(request: Request) -> dict:
    counts = feedback_counts(request)
    reasons = {key: counts.get(("down", key), 0) for key in ("wrong", "stale", "misunderstood", "other")}
    reasons["none"] = counts.get(("down", "none"), 0)
    return {
        "up": sum(value for (vote, _reason), value in counts.items() if vote == "up"),
        "down": sum(value for (vote, _reason), value in counts.items() if vote == "down"),
        "reasons": reasons,
        "scope": "process",
    }


async def _snapshot(request: Request, store: KnowledgeEditorStore | None = None) -> dict:
    editor = store or KnowledgeEditorStore()
    index_store = _index(editor)
    if index_store is None:
        index_info = {"built": False, "documents": None, "chunks": None, "built_at": None}
    else:
        from nabiz.console.how_api import index_part

        index_info = index_part(index_store)
    gaps, refusals, last_scan = await _current_gaps(editor, index_store)
    tag_rows = editor.tags()
    groups = group_gaps(gaps, tag_rows)
    candidates = []
    for item in editor.candidates():
        details = editor.candidate(item["id"])
        status = apply_events(details or item, (details or {}).get("events", []))["status"]
        candidates.append({key: item[key] for key in ("id", "url", "host", "category", "gap_count", "created_at")} |
                          {"status": status})
    return {
        "index": index_info,
        "feedback": _feedback(request),
        "notes": {"chat_not_stored": True, "requests_ttl_days": 30},
        "last_scan": last_scan,
        "gaps": {"groups": groups, "required_refusals": refusals},
        "candidates": candidates,
    }


def _candidate_detail(editor: KnowledgeEditorStore, candidate_id: int) -> dict | None:
    candidate = editor.candidate(candidate_id)
    if candidate is None:
        return None
    candidate = apply_events(candidate, candidate["events"])
    trials = candidate["trials"]
    candidate["diff"] = compare_trials(trials[-2], trials[-1]) if len(trials) > 1 else None
    questions = {item["ref"]: item for item in [*evaluation_questions(), *request_questions(requests_path())]}
    candidate["gap_questions"] = {
        ref: {"question": mask_labels(str(questions[ref].get("question", "")))[0],
              "lang": questions[ref].get("lang") or "tr"}
        for ref in candidate["gap_refs"] if ref in questions
    }
    db_path = knowledge_db_path()
    candidate["versions"] = versions(db_path, candidate["url"]) if db_path.is_file() else []
    candidate["note_text"] = "Onay dizini değiştirmez; dizine alma ayrı adımdır."
    return candidate


async def _gap_source(store: KnowledgeEditorStore, ref: str, index_store) -> dict | None:
    if ref.startswith("request:"):
        row = next((item for item in request_questions(requests_path()) if item["ref"] == ref), None)
        if row is None:
            return None
    else:
        scan = store.latest_scan()
        saved = next((item for item in (scan or {}).get("rows", []) if item.get("ref") == ref), None)
        row = _eval_by_ref().get(ref)
        if saved is None or row is None:
            return None
        row = {**row, **saved}
    if index_store is not None:
        measured = await measure_rows(index_store, [row], db_path=knowledge_db_path())
        if measured:
            row = measured[0]
    return row


@knowledge_editor_routes.get(_BASE)
async def knowledge_editor_get(request: Request):
    return await _snapshot(request)


@knowledge_editor_routes.post(_BASE + "/scan")
async def knowledge_editor_scan(request: Request):
    editor = KnowledgeEditorStore()
    index_store = _index(editor)
    if index_store is None:
        return _no_index()
    rows = evaluation_questions()[:MAX_EVAL_QUESTIONS]
    measured = await measure_rows(index_store, rows, db_path=knowledge_db_path())
    fingerprint = index_fingerprint(knowledge_db_path(), index_store)
    editor.save_scan(fingerprint, measured)
    return await _snapshot(request, editor)


@knowledge_editor_routes.get(_BASE + "/gaps/{ref}")
async def knowledge_editor_gap(ref: str):
    editor = KnowledgeEditorStore()
    index_store = _index(editor)
    row = await _gap_source(editor, ref, index_store)
    if row is None:
        return port_problem(404, "not_found", "Bu bilgi açığı bulunamadı.")
    override = editor.tags().get(ref)
    versions_by_url = []
    for gold_url in row.get("gold_urls", []):
        versions_by_url.append({"url": gold_url, "versions": versions(knowledge_db_path(), gold_url)
                                if knowledge_db_path().is_file() else []})
    attached = [item for item in editor.candidates() if ref in item["gap_refs"]]
    return {
        "ref": ref,
        "kind": row.get("kind", "eval"),
        "source": "request" if row.get("kind") == "request" else "eval",
        "question": row.get("question", ""),
        "lang": row.get("lang") or "tr",
        "category": row.get("category") or row.get("group") or "Genel bilgi",
        "measurement": {key: row.get(key) for key in ("mode", "level", "top_url", "top_title", "top_institution",
                                                         "gold_rank", "gold_rank_label", "stale_hint", "stale_at",
                                                         "updated_at_method")},
        "gold_urls": versions_by_url,
        "tag": override["tag"] if override else row.get("tag_suggested", "missing_source"),
        "tag_by": "operator" if override else "suggestion",
        "candidates": [{"id": item["id"], "url": item["url"]} for item in attached],
    }


@knowledge_editor_routes.post(_BASE + "/gaps/{ref}/tag")
async def knowledge_editor_tag(ref: str, body: TagBody, request: Request):
    editor = KnowledgeEditorStore()
    if await _gap_source(editor, ref, _index(editor)) is None:
        return port_problem(404, "not_found", "Bu bilgi açığı bulunamadı.")
    editor.set_tag(ref, body.tag)
    return await _snapshot(request, editor)


@knowledge_editor_routes.post(_BASE + "/candidates", status_code=201)
async def knowledge_editor_propose(body: CandidateBody, request: Request):
    if problem := _pii_error(body.note):
        return problem
    editor = KnowledgeEditorStore()
    index_store = _index(editor)
    if index_store is None:
        return _no_index()
    gaps, _refusals, _scan = await _current_gaps(editor, index_store)
    gap_map = {str(gap["ref"]): gap for gap in gaps}
    selected = [gap_map.get(ref) for ref in dict.fromkeys(body.gap_refs)]
    if any(item is None for item in selected):
        return port_problem(422, "invalid_gap", "Bağlanan sorulardan biri artık seçilebilir değil.")
    categories = {str(item.get("category") or item.get("group") or "Genel bilgi") for item in selected}
    if len(categories) != 1:
        return port_problem(422, "invalid_gap", "Aynı hizmet kategorisindeki soruları bağlayın.")
    try:
        host = (urlsplit(body.url.strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        host = ""
    candidate_versions = versions(knowledge_db_path(), body.url) if knowledge_db_path().is_file() else []
    checks = check_candidate(body.url, robots=robots_for(host, body.url), active_versions=candidate_versions)["checks"]
    if any(check["state"] == "fail" for check in checks):
        return JSONResponse(status_code=422, content={"error": "candidate_rejected",
                                                      "message": "Aday çevrimdışı denetimlerden geçmedi.",
                                                      "checks": checks})
    candidate = editor.create_candidate(
        url=body.url.strip(), canonical_url=canonical(body.url), host=host,
        category=next(iter(categories)), gap_refs=list(dict.fromkeys(body.gap_refs)),
        note=body.note.strip(), checks=checks,
    )
    log.info("knowledge_editor candidate=%s host=%s event=proposed", candidate["id"], host)
    detail = _candidate_detail(editor, candidate["id"])
    return {**(detail or candidate), "note_text": "Onay dizini değiştirmez; dizine alma ayrı adımdır."}


@knowledge_editor_routes.get(_BASE + "/candidates/{candidate_id}")
async def knowledge_editor_candidate(candidate_id: int):
    result = _candidate_detail(KnowledgeEditorStore(), candidate_id)
    return result if result else port_problem(404, "not_found", "Kaynak adayı bulunamadı.")


@knowledge_editor_routes.post(_BASE + "/candidates/{candidate_id}/trial")
async def knowledge_editor_trial(candidate_id: int):
    editor = KnowledgeEditorStore()
    candidate = _candidate_detail(editor, candidate_id)
    if candidate is None:
        return port_problem(404, "not_found", "Kaynak adayı bulunamadı.")
    index_store = _index(editor)
    if index_store is None:
        return _no_index()
    questions = {item["ref"]: item for item in [*evaluation_questions(), *request_questions(requests_path())]}
    selected = [questions.get(ref) for ref in candidate["gap_refs"]]
    if any(item is None for item in selected):
        return port_problem(409, "stale_candidate", "Bağlı sorulardan biri artık bulunamıyor.")
    rows = await measure_rows(index_store, selected, db_path=knowledge_db_path(), candidate_url=candidate["url"])
    fingerprint = index_fingerprint(knowledge_db_path(), index_store)
    summary = summarize_trial(rows, candidate["url"])
    editor.save_trial(candidate_id, fingerprint, summary, rows)
    log.info("knowledge_editor candidate=%s host=%s event=tried", candidate_id, candidate["host"])
    return _candidate_detail(editor, candidate_id)


@knowledge_editor_routes.post(_BASE + "/candidates/{candidate_id}/decide")
async def knowledge_editor_decide(candidate_id: int, body: CandidateDecisionBody):
    if problem := _pii_error(body.reason):
        return problem
    editor = KnowledgeEditorStore()
    candidate = _candidate_detail(editor, candidate_id)
    if candidate is None:
        return port_problem(404, "not_found", "Kaynak adayı bulunamadı.")
    if candidate["status"] != "tried":
        return port_problem(409, "conflict", "Önce deneyin.")
    kind, status = ("approved", "approved") if body.action == "approve" else ("rejected", "rejected")
    latest = candidate["trials"][-1]["summary"] if candidate["trials"] else None
    if (problem := _pii_error(body.reason.strip())):
        return problem
    editor.add_decision(candidate_id, kind, body.reason.strip(), latest, status)
    log.info("knowledge_editor candidate=%s host=%s event=%s", candidate_id, candidate["host"], kind)
    return _candidate_detail(editor, candidate_id)


@knowledge_editor_routes.post(_BASE + "/candidates/{candidate_id}/events/{event_id}/undo")
async def knowledge_editor_undo(candidate_id: int, event_id: int, body: UndoBody):
    if problem := _pii_error(body.reason):
        return problem
    editor = KnowledgeEditorStore()
    candidate = _candidate_detail(editor, candidate_id)
    if candidate is None:
        return port_problem(404, "not_found", "Kaynak adayı bulunamadı.")
    events = candidate["events"]
    synthetic = {"id": max((event["id"] for event in events), default=0) + 1,
                 "kind": "undone", "undoes": event_id}
    try:
        status_after = apply_events(candidate, [*events, synthetic])["status"]
        latest = candidate["trials"][-1]["summary"] if candidate["trials"] else None
        editor.undo(candidate_id, event_id, body.reason.strip(), status_after, latest)
    except ValueError:
        return port_problem(409, "conflict", "Bu olay zaten geri alınmış ya da geri alınamaz.")
    log.info("knowledge_editor candidate=%s host=%s event=undone", candidate_id, candidate["host"])
    return _candidate_detail(editor, candidate_id)
