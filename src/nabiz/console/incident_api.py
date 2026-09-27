"""Operator-only read and write routes for incident files."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from nabiz.console.incident import (
    WAIT_HOURS,
    build_incidents,
    equipment_members,
    photo_members,
    report_members,
)
from nabiz.console.incident_store import AlreadyUndone, IncidentStore, clean_reason, incidents_path
from nabiz.console.operator import port_problem
from nabiz.console.report_api import report_engine, support_counts
from nabiz.console.report_triage import TRIAGE_NOTE, report_agency
from nexus_core import NexusEngine
from nexus_core.decisions import Operator
from nexus_core.signals import system_clock

log = logging.getLogger("nabiz.console.incident")
incident_routes = APIRouter()


class _SplitBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str
    reason: str = ""


class _MergeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str
    reason: str = ""


class _UndoBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = ""


class _PriorityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: Literal["high", "medium", "normal", "suggested"]
    reason: str = ""


def _clock(request: Request):
    return (
        getattr(request.app.state, "incident_clock", None)
        or getattr(
            request.app.state,
            "report_clock",
            None,
        )
        or system_clock
    )


def _store(request: Request) -> IncidentStore:
    return IncidentStore(incidents_path(), clock=_clock(request))


def _photo_items() -> tuple[list[Mapping[str, Any]], bool]:
    try:
        from nabiz.console.photo_reports import PhotoReportStore

        store = PhotoReportStore()
        return list(store.items(open_only=True)), True
    except ImportError:
        return [], False
    except Exception as error:
        log.warning("photo adapter unavailable (%s)", type(error).__name__)
        return [], False


def _snapshot(request: Request, engine: NexusEngine, store: IncidentStore) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    now = _clock(request)()
    states = [state.model_dump(mode="json") for state in engine.states().values()]
    window_hours = engine.router.escalation.settings.window_hours
    reports = report_members(states, support_counts(engine), now, window_hours)
    equipment = equipment_members(states)
    photo_items, photos_available = _photo_items()
    photos = photo_members(photo_items)
    actions = store.actions()
    overrides = store.overrides()
    incidents = build_incidents(reports, photos, equipment, actions, overrides, now)
    return incidents, {
        "now": now,
        "window_hours": window_hours,
        "photos_available": photos_available,
        "reports": reports,
        "photos": photos,
        "equipment": equipment,
    }


def _summary(incident: Mapping[str, Any]) -> dict[str, Any]:
    members = incident["members"]
    reports = members["report"]
    return {
        "id": incident["id"],
        "stations": incident["stations"],
        "title_station": incident["title_station"],
        "priority": {key: incident["priority"][key] for key in ("level", "by", "suggested_level")},
        "members": {
            "reports": len(reports),
            "people": sum(int(item.get("support") or 1) for item in reports),
            "photos": len(members["photo"]),
            "equipment": len(members["equipment"]),
        },
        "oldest_open_at": incident["oldest_open_at"],
    }


def _detail_actions(actions: list[dict[str, Any]], incident_id: str) -> list[dict[str, Any]]:
    matched = []
    for row in actions:
        data = row["data"]
        related = row["incident_id"] == incident_id or data.get("source") == incident_id or data.get("target") == incident_id
        related = related or (row["kind"] == "split" and f"inc-a{row['id']}" == incident_id)
        if related:
            matched.append(
                {
                    key: row.get(key)
                    for key in (
                        "id",
                        "kind",
                        "at",
                        "reason",
                        "actor",
                        "ledger_entry",
                        "undone_at",
                        "undo_reason",
                        "undo_ledger_entry",
                    )
                }
            )
    return matched


def _detail(
    incident: Mapping[str, Any], store: IncidentStore, actions: list[dict[str, Any]], photos_available: bool
) -> dict[str, Any]:
    source = incident["members"]
    members = {
        "reports": [dict(value) for value in source["report"]],
        "photos": [dict(value) for value in source["photo"]],
        "equipment": [dict(value) for value in source["equipment"]],
    }
    for photo in members["photos"]:
        if photos_available and photo.get("has_photo"):
            photo["photo_url"] = f"/api/console/photo-reports/{photo['photo_code']}/photo"
        else:
            photo["photo_code"] = None
            photo["photo_url"] = None
    return {
        **_summary(incident),
        "multi_station": len(incident["stations"]) > 1,
        "suggestion": incident["suggestion"],
        "priority": incident["priority"],
        "members": members,
        "photos_available": photos_available,
        "record_note": None if members["equipment"] else "no_record",
        "priority_history": store.priority_history(incident["id"]),
        "actions": _detail_actions(actions, incident["id"]),
        "agency": report_agency(),
        "note": TRIAGE_NOTE,
    }


def _find(incidents: list[dict[str, Any]], incident_id: str) -> dict[str, Any] | None:
    return next((item for item in incidents if item["id"] == incident_id), None)


def _reason_error(reason: str) -> tuple[str, str] | None:
    try:
        clean_reason(reason)
    except ValueError as error:
        message = str(error)
        if "kişisel" in message:
            return "reason_has_pii", message
        if "en fazla" in message:
            return "reason_too_long", message
        return "reason_required", message
    return None


def _bad_reason(reason: str):
    problem = _reason_error(reason)
    return port_problem(400, *problem) if problem else None


def _engine_problem() -> Any:
    return port_problem(503, "not_wired", "Olay dosyalarını şu an görüntüleyemiyorsunuz; karar çekirdeği bağlı değil.")


def _current(request: Request, engine: NexusEngine, store: IncidentStore) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return _snapshot(request, engine, store)


@incident_routes.get("/api/console/incidents")
async def incident_list(request: Request) -> Any:
    engine = report_engine(request)
    if engine is None:
        return _engine_problem()
    store = _store(request)
    incidents, context = _snapshot(request, engine, store)
    return {
        "items": [_summary(item) for item in incidents],
        "counts": {
            "incidents": len(incidents),
            "reports": sum(len(item["members"]["report"]) for item in incidents),
            "photos": sum(len(item["members"]["photo"]) for item in incidents),
            "with_record": sum(bool(item["members"]["equipment"]) for item in incidents),
        },
        "window_hours": context["window_hours"],
        "wait_hours": WAIT_HOURS,
        "photos_available": context["photos_available"],
        "generated_at": context["now"].isoformat(),
        "note": TRIAGE_NOTE,
    }


@incident_routes.get("/api/console/incidents/{incident_id}")
async def incident_detail(incident_id: str, request: Request) -> Any:
    engine = report_engine(request)
    if engine is None:
        return _engine_problem()
    store = _store(request)
    incidents, context = _snapshot(request, engine, store)
    incident = _find(incidents, incident_id)
    if incident is None:
        return port_problem(404, "unknown_incident", "İstediğiniz olay dosyasına erişilemiyor; olay bulunamadı.")
    return _detail(incident, store, store.actions(), context["photos_available"])


@incident_routes.post("/api/console/incidents/{incident_id}/split")
async def incident_split(incident_id: str, body: _SplitBody, request: Request) -> Any:
    engine = report_engine(request)
    if engine is None:
        return _engine_problem()
    if problem := _bad_reason(body.reason):
        return problem
    store = _store(request)
    incidents, _context = _current(request, engine, store)
    incident = _find(incidents, incident_id)
    if incident is None:
        return port_problem(404, "unknown_incident", "İstediğiniz olay dosyasına erişilemiyor; olay bulunamadı.")
    all_members = [member for kind in ("report", "photo", "equipment") for member in incident["members"][kind]]
    member = next((item for item in all_members if item["ref"] == body.ref), None)
    if member is None:
        return port_problem(409, "member_moved", "Bu üye başka bir olay dosyasına taşınmış olabilir.")
    if len(all_members) <= 1:
        return port_problem(409, "last_member", "Olay dosyasındaki son üyeyi ayıramazsınız.")
    try:
        row = store.add_action(
            "split",
            incident_id,
            {"ref": body.ref, "station_key": member["station_key"]},
            body.reason,
            Operator().label,
            engine.ledger,
        )
    except ValueError as error:
        if problem := _bad_reason(body.reason):
            return problem
        return port_problem(400, "invalid_action", str(error))
    except Exception as error:
        log.warning("incident write failed (%s)", type(error).__name__)
        return port_problem(503, "store_failed", "Ayrım deftere işlendi ancak olay tablosuna kaydedilemedi; yeniden deneyin.")
    return {
        "incident_id": incident_id,
        "new_incident_id": f"inc-a{row['id']}",
        "action_id": row["id"],
        "ledger_entry_id": row["ledger_entry"],
        "ledger_changed": True,
    }


@incident_routes.post("/api/console/incidents/{incident_id}/merge")
async def incident_merge(incident_id: str, body: _MergeBody, request: Request) -> Any:
    engine = report_engine(request)
    if engine is None:
        return _engine_problem()
    if body.target == incident_id:
        return port_problem(400, "same_target", "Bir olayı kendi içine birleştiremezsiniz.")
    if problem := _bad_reason(body.reason):
        return problem
    store = _store(request)
    incidents, _context = _current(request, engine, store)
    source, target = _find(incidents, incident_id), _find(incidents, body.target)
    if source is None or target is None:
        return port_problem(404, "unknown_incident", "Birleştirmek istediğiniz olay dosyasına erişilemiyor.")
    try:
        row = store.add_action(
            "merge",
            incident_id,
            {"source": incident_id, "target": body.target, "station_key": source["station_key"]},
            body.reason,
            Operator().label,
            engine.ledger,
        )
    except ValueError as error:
        if problem := _bad_reason(body.reason):
            return problem
        return port_problem(400, "invalid_action", str(error))
    except Exception as error:
        log.warning("incident write failed (%s)", type(error).__name__)
        return port_problem(
            503, "store_failed", "Birleştirme deftere işlendi ancak olay tablosuna kaydedilemedi; yeniden deneyin."
        )
    return {"incident_id": body.target, "action_id": row["id"], "ledger_entry_id": row["ledger_entry"], "ledger_changed": True}


@incident_routes.post("/api/console/incidents/actions/{action_id}/undo")
async def incident_undo(action_id: int, body: _UndoBody, request: Request) -> Any:
    engine = report_engine(request)
    if engine is None:
        return _engine_problem()
    if problem := _bad_reason(body.reason):
        return problem
    store = _store(request)
    try:
        row = store.undo(action_id, body.reason, Operator().label, engine.ledger)
    except LookupError:
        return port_problem(404, "unknown_action", "Geri almak istediğiniz eylem bulunamadı.")
    except AlreadyUndone:
        return port_problem(409, "already_undone", "Bu eylem daha önce geri alınmış.")
    except ValueError:
        return _bad_reason(body.reason)
    except Exception as error:
        log.warning("incident write failed (%s)", type(error).__name__)
        return port_problem(503, "store_failed", "Geri alma deftere işlendi ancak olay tablosuna kaydedilemedi; yeniden deneyin.")
    return {"action_id": row["id"], "ledger_entry_id": row["undo_ledger_entry"], "ledger_changed": True}


@incident_routes.post("/api/console/incidents/{incident_id}/priority")
async def incident_priority(incident_id: str, body: _PriorityBody, request: Request) -> Any:
    engine = report_engine(request)
    if engine is None:
        return _engine_problem()
    if problem := _bad_reason(body.reason):
        return problem
    store = _store(request)
    incidents, _context = _current(request, engine, store)
    incident = _find(incidents, incident_id)
    if incident is None:
        return port_problem(404, "unknown_incident", "İstediğiniz olay dosyasına erişilemiyor; olay bulunamadı.")
    row, problem = _write_priority(incident_id, body, incident, store, engine)
    if problem is not None:
        return problem
    suggestion = incident["suggestion"]["level"] if body.level == "suggested" else body.level
    priority = {
        "level": suggestion,
        "by": "suggestion" if body.level == "suggested" else "operator",
        "suggested_level": incident["suggestion"]["level"],
        "reason": None if body.level == "suggested" else row["reason"],
        "at": row["at"],
        "actor": row["actor"],
    }
    return {"priority": priority, "ledger_entry_id": row["ledger_entry"], "ledger_changed": True}


def _write_priority(incident_id: str, body: _PriorityBody, incident: dict, store: IncidentStore, engine):
    current = incident["priority"]
    if body.level == "suggested":
        if current["by"] != "operator":
            return None, port_problem(409, "same_level", "Öncelik zaten öneri düzeyinde.")
        write = store.clear_priority
        args = (incident_id, body.reason, Operator().label, engine.ledger)
    else:
        if current["level"] == body.level:
            return None, port_problem(409, "same_level", "Bu olay dosyası zaten bu öncelik düzeyinde.")
        write = store.set_priority
        args = (
            incident_id,
            body.level,
            body.reason,
            incident["suggestion"]["level"],
            Operator().label,
            engine.ledger,
        )
    try:
        return write(*args), None
    except ValueError:
        return None, _bad_reason(body.reason)
    except Exception as error:
        log.warning("incident write failed (%s)", type(error).__name__)
        return None, port_problem(
            503,
            "store_failed",
            "Öncelik deftere işlendi ancak olay tablosuna kaydedilemedi; yeniden deneyin.",
        )
