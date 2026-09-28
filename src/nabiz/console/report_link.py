"""One citizen-facing report code across the photo (E51), timeline (E66), incident (E67) and outcome (E75) records.

The E33 report code is the only identity a citizen follows. A photo keeps its own short code for
withdrawal, but once the citizen chooses to link it, every other record names it by ``photo_ref``:
a one-way digest, so the timeline, the incident file and the card can say "a photo was added"
without holding the photo code, the photo, or its address.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import pathlib
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from nabiz.console.photo_reports import photo_reports_path
from nabiz.console.report_timeline import STAGES, WAITING_ON, timeline_path

PHOTO_CARD_TYPE = "photo_report"
# E33/E66 reports are lift reports; the card names the report's category, so every endpoint shows the same one.
REPORT_CATEGORY = "lift"
PHOTO_CARD_STATES = ("received", "reviewed", "forwarded", "answered", "citizen_confirmed", "reopened", "closed")
# The one mapping table from each record's own state names to the card's; tests hold both total.
CARD_STATE_BY_STAGE = {
    "recorded": "received",
    "reviewing": "reviewed",
    "info_needed": "reviewed",
    "referred": "forwarded",
    "resolution_reported": "answered",
    "confirmed": "citizen_confirmed",
    "reopened": "reopened",
}
CARD_STATE_BY_PHOTO_STATUS = {"new": "received", "reviewed": "reviewed", "forwarded": "forwarded", "closed": "closed"}
# SOZLESME v0 action table: kind and base consent come from here, never from the producer's wish.
PHOTO_CARD_ACTIONS = {
    "review_report": ("view", False),
    "confirm_resolved": ("nabiz", True),
    "reopen": ("nabiz", True),
    "send": ("nabiz", True),
}
_ACTION_LABELS = {
    "tr": {"review_report": "Bildirimi gör", "confirm_resolved": "Çözüldü, onaylıyorum",
           "reopen": "Hâlâ sürüyor", "send": "Bilgi gönder"},
    "en": {"review_report": "View report", "confirm_resolved": "Yes, it is fixed",
           "reopen": "Still not fixed", "send": "Send details"},
}
_TITLES = {"tr": "Bildirim {code}", "en": "Report {code}"}
_SOURCE_NAMES = {"tr": "Nabız bildirim zaman çizgisi (örnek akış)", "en": "Nabız report timeline (sample flow)"}
_EVENT_BY = frozenset({"citizen", "operator", "system"})
# 422 for a report that exists but no longer takes photos; 403 for any code that does not match.
LINK_STATUS = {"photo_not_found": 404, "photo_closed": 409, "report_closed": 422,
               "report_mismatch": 403, "already_linked": 403}


class LinkRefused(Exception):
    """A photo cannot join this report; ``reason`` is a key of ``LINK_STATUS``."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = LINK_STATUS[reason]


def photo_ref(photo_code: str) -> str:
    """The only name other records keep for a photo: ``photo:`` and 12 hex of its code's SHA-256."""
    return f"photo:{hashlib.sha256(photo_code.encode('utf-8')).hexdigest()[:12]}"


def _now(now: dt.datetime | None) -> str:
    return (now or dt.datetime.now(dt.UTC)).astimezone(dt.UTC).isoformat()


@contextlib.contextmanager
def _photo_db(path: pathlib.Path | None, attach: pathlib.Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path or photo_reports_path(), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA secure_delete = ON")
    try:
        if attach is not None:
            # One transaction over both files: SQLite commits attached rollback-journal databases atomically.
            conn.execute("ATTACH DATABASE ? AS tl", (str(attach),))
        yield conn
    finally:
        conn.close()


def _photo_row(conn: sqlite3.Connection, photo_code: str, stamp: str) -> tuple[str, dict[str, Any]]:
    row = conn.execute(
        "SELECT status, data FROM photo_reports WHERE code = ? AND expires_at > ?", (photo_code, stamp)
    ).fetchone()
    if row is None:
        raise LinkRefused("photo_not_found")
    return str(row["status"]), json.loads(row["data"])


def link_photo(
    photo_code: str, report_code: str | None, signal_id: str | None, *,
    photos_db: pathlib.Path | None = None, timeline_db: pathlib.Path | None = None, now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Link a photo to an open E66 timeline in one transaction, or refuse; linking twice is a no-op.

    With no report code the photo stays a standalone report, exactly as before P07.
    """
    ref = photo_ref(photo_code)
    if report_code is None or signal_id is None:
        return {"photo_ref": ref, "report_code": None, "linked": False}
    stamp = _now(now)
    with _photo_db(photos_db, timeline_db or timeline_path()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            status, photo = _photo_row(conn, photo_code, stamp)
            linked = photo.get("linked_report_code")
            if linked == report_code:
                conn.execute("ROLLBACK")
                return {"photo_ref": ref, "report_code": report_code, "linked": True}
            if linked is not None:
                raise LinkRefused("already_linked")
            if status == "closed":
                raise LinkRefused("photo_closed")
            row = conn.execute(
                "SELECT signal_id, stage, data FROM tl.report_timeline WHERE code = ? AND expires_at > ?",
                (report_code, stamp),
            ).fetchone()
            if row is None or row["signal_id"] != signal_id:
                raise LinkRefused("report_mismatch")
            if row["stage"] == "confirmed":
                raise LinkRefused("report_closed")
            photo.update(linked_signal_id=signal_id, linked_report_code=report_code)
            timeline = json.loads(row["data"])
            refs = timeline.setdefault("photo_refs", [])
            if ref not in refs:
                refs.append(ref)
                timeline["history"].append({"by": "citizen", "step": "photo_added", "photo_ref": ref, "at": stamp})
            conn.execute("UPDATE photo_reports SET data = ? WHERE code = ?", (json.dumps(photo, ensure_ascii=False), photo_code))
            conn.execute(
                "UPDATE tl.report_timeline SET data = ?, updated_at = ? WHERE code = ?",
                (json.dumps(timeline, ensure_ascii=False), stamp, report_code),
            )
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return {"photo_ref": ref, "report_code": report_code, "linked": True}


def unlink_photo(
    photo_code: str, report_code: str, *, timeline_db: pathlib.Path | None = None, now: dt.datetime | None = None,
) -> bool:
    """Drop a withdrawn photo's ref from its timeline so the timeline never claims a photo that is gone."""
    ref, stamp = photo_ref(photo_code), _now(now)
    with contextlib.closing(sqlite3.connect(timeline_db or timeline_path(), timeout=10, isolation_level=None)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT data FROM report_timeline WHERE code = ?", (report_code,)).fetchone()
        data = json.loads(row[0]) if row else {}
        if ref not in data.get("photo_refs", []):
            conn.execute("ROLLBACK")
            return False
        data["photo_refs"].remove(ref)
        data["history"].append({"by": "citizen", "step": "photo_removed", "photo_ref": ref, "at": stamp})
        conn.execute("UPDATE report_timeline SET data = ?, updated_at = ? WHERE code = ?",
                     (json.dumps(data, ensure_ascii=False), stamp, report_code))
        conn.execute("COMMIT")
    return True


def report_for_photo(photo_code: str, *, photos_db: pathlib.Path | None = None) -> dict[str, str] | None:
    """The report a photo was linked to, or None for a standalone (or expired) photo."""
    with _photo_db(photos_db) as conn:
        try:
            _status, data = _photo_row(conn, photo_code, _now(None))
        except LinkRefused:
            return None
    code, signal_id = data.get("linked_report_code"), data.get("linked_signal_id")
    return {"report_code": code, "signal_id": signal_id} if code and signal_id else None


def photos_for_report(report_code: str, *, photos_db: pathlib.Path | None = None) -> list[str]:
    """Photo codes linked to a report: operator side only, the citizen view carries ``photo_ref``s."""
    with _photo_db(photos_db) as conn:
        rows = conn.execute(
            "SELECT code FROM photo_reports WHERE json_extract(data, '$.linked_report_code') = ? AND expires_at > ? "
            "ORDER BY created_at",
            (report_code, _now(None)),
        ).fetchall()
    return [str(row["code"]) for row in rows]


def card_state(stage: str | None = None, photo_status: str | None = None) -> str:
    """A timeline stage wins; a standalone photo's status is used only when there is no timeline."""
    if stage is not None:
        return CARD_STATE_BY_STAGE[stage]
    if photo_status is not None:
        return CARD_STATE_BY_PHOTO_STATUS[photo_status]
    raise ValueError("stage or photo_status is required")


def _card_status(state: str, waiting_on: str | None) -> str:
    if state == "answered":
        return "awaiting_confirmation"
    if state in {"citizen_confirmed", "closed"}:
        return "done"
    return "needs_input" if waiting_on == "citizen" else "ready"


def _steps(history: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"at": event.get("at"), "step": str(event.get("step") or event.get("stage")),
         "by": event.get("by") if event.get("by") in _EVENT_BY else "system"}
        for event in history
        if event.get("step") or event.get("stage") in STAGES or event.get("stage") == "reopened"
    ]


def _actions(report_code: str, state: str, stage: str, lang: str, step_count: int) -> list[dict[str, Any]]:
    ids = ["review_report"]
    if state == "answered":
        ids += ["confirm_resolved", "reopen"]
    elif stage == "info_needed":
        ids.append("send")
    actions = []
    for action_id in ids:
        kind, consent = PHOTO_CARD_ACTIONS[action_id]
        operation = None
        if kind == "nabiz":
            # Stable per report step, so a second press of the same card is the same operation.
            digest = hashlib.sha256(f"{report_code}\0{action_id}\0{step_count}".encode()).hexdigest()
            operation = f"op-{digest[:16]}"
        actions.append({"id": action_id, "label": _ACTION_LABELS[lang][action_id], "kind": kind,
                        "requires_consent": consent, "operation_id": operation})
    return actions


def card_from_report(
    report_code: str, *, lang: str, timeline: Mapping[str, Any], photo: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A ChatCard v0 ``photo_report`` card: plain data only, never the photo or an address for it.

    ``timeline`` is the E66 row; ``photo`` is passed only when the caller already holds that
    photo's code (the citizen who sent it), so knowing the report code never reveals it.
    """
    if lang not in _TITLES:
        raise ValueError("lang must be tr or en")
    stage = str(timeline["stage"])
    data = timeline.get("data") or {}
    history = list(data.get("history") or [])
    state = card_state(stage)
    waiting = WAITING_ON.get(stage)
    waiting_on = waiting if waiting in {"citizen", "operator"} else None
    body = {
        "report_code": report_code,
        "photo_code": str(photo["code"]) if photo else None,
        "category": REPORT_CATEGORY,
        "place": {"kind": "station", "name": str(timeline.get("station") or "")},
        "state": state,
        "waiting_on": waiting_on,
        "timeline": _steps(history),
        "has_photo": bool(data.get("photo_refs")),
        "simulated": True,
    }
    return {
        "v": 0,
        "id": f"card-{PHOTO_CARD_TYPE}-{hashlib.sha256(report_code.encode()).hexdigest()[:8]}",
        "type": PHOTO_CARD_TYPE,
        "status": _card_status(state, waiting_on),
        "title": _TITLES[lang].format(code=report_code),
        "data": body,
        "source": {"name": _SOURCE_NAMES[lang], "url": None, "observed_at": timeline.get("updated_at"),
                   "freshness": "kayitli"},
        "linked": {"event_id": None, "report_code": report_code, "operation_id": None},
        "actions": _actions(report_code, state, stage, lang, len(history)),
        "sensitive": False,
    }


__all__ = [
    "CARD_STATE_BY_PHOTO_STATUS", "CARD_STATE_BY_STAGE", "LINK_STATUS", "PHOTO_CARD_ACTIONS", "PHOTO_CARD_STATES",
    "PHOTO_CARD_TYPE", "REPORT_CATEGORY", "LinkRefused", "card_from_report", "card_state", "link_photo", "photo_ref",
    "photos_for_report", "report_for_photo", "unlink_photo",
]
