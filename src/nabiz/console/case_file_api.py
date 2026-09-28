"""HTTP routes for the consented, source-linked case-file prototype."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, Field

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.knowledge.guardrails import host_allowed
from ibb_mcp.knowledge.store import KnowledgeStore
from ibb_mcp.models import ISTANBUL_TZ
from nabiz.console import accounts_api
from nabiz.console.accounts import token_hash
from nabiz.console.case_file import (
    BAND,
    CASE_HEADER,
    CONSENT_TEXT,
    CONSENT_VERSION,
    CREATES_PER_HOUR,
    CaseFileError,
    CaseFileStore,
    PlanError,
    case_files_path,
    due_reminders,
    progress,
)
from nabiz.console.citizen_requests import HourlyLimit
from nabiz.console.operator import port_problem

case_file_routes = APIRouter(prefix="/api/case-file")
create_limit = HourlyLimit(CREATES_PER_HOUR)
_agency_path = REPO_ROOT / "data/agencies.json"
_plan_path = REPO_ROOT / "data/knowledge/life_events.json"
_point_row = re.compile(r"\|\s*(\d+)\s*\n\s*\|\s*([^\n|]+?)\s*\n\s*\|\s*([^\n|]+)")
_district_suffix = re.compile(r"\s+([^\s/]+)\s*/\s*İstanbul\s*$", re.IGNORECASE)


class CreateBody(BaseModel):
    plan_id: str = Field(min_length=1, max_length=40)
    consent: bool = False


class AnswerBody(BaseModel):
    step_id: str = Field(min_length=1, max_length=40)
    choice: str = Field(min_length=1, max_length=40)


class StepBody(BaseModel):
    step_id: str = Field(min_length=1, max_length=40)
    done: bool | None = None
    note: str | None = Field(default=None, max_length=1000)
    ref_code: str | None = Field(default=None, max_length=1000)
    remind_on: str | None = Field(default=None, max_length=30)


def _agency_map(agencies: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = {item["id"]: item for item in agencies.get("agencies", []) if isinstance(item, dict)}
    district = agencies.get("district_office")
    if isinstance(district, dict):
        entries["district_office"] = district
    return entries


def _fold_space(value: str) -> str:
    return " ".join(value.split())


def _check_fragments(items: Any, body: str, field: str) -> list[str]:
    if not isinstance(items, list) or len(items) > (4 if field == "quotes" else 6):
        raise PlanError("Kaynak alıntısı ya da belge listesi geçersiz.")
    folded_body = _fold_space(body)
    checked = []
    for item in items:
        if not isinstance(item, str) or not item or len(item) > 240:
            raise PlanError("Kaynak alıntısı ya da belge maddesi 240 karakteri aşamaz.")
        if _fold_space(item) not in folded_body:
            raise PlanError("Kaynak alıntısı ya da belge maddesi dizin metninde bulunamadı.")
        checked.append(item)
    return checked


def _agency(agency_id: str, agencies: dict[str, Any]) -> dict[str, Any]:
    agency = _agency_map(agencies).get(agency_id)
    if agency is None:
        raise PlanError("Plan bilinmeyen bir kuruma bağlı.")
    return dict(agency)


def _source(source: dict[str, Any], store: Any | None) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise PlanError("Kaynak bilgisi geçersiz.")
    url = source.get("url")
    try:
        parsed = urlsplit(url) if isinstance(url, str) else None
    except ValueError as exc:
        raise PlanError("Kaynak adresi doğrulanamadı.") from exc
    if (
        parsed is None
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or not host_allowed(parsed.hostname)
    ):
        raise PlanError("Kaynak adresi doğrulanamadı.")
    result = {
        "indexed": False,
        "title": None,
        "institution": None,
        "fetched_at": None,
        "url": None,
        "quotes": [],
        "documents": [],
    }
    document = store.current_document(url) if store is not None else None
    if not document or not document.get("active"):
        return result
    body = str(document.get("body") or "")
    result.update(
        indexed=True,
        title=document["title"],
        institution=document["institution"],
        fetched_at=document["fetched_at"],
        url=url,
        quotes=_check_fragments(source.get("quotes", []), body, "quotes"),
        documents=_check_fragments(source.get("documents", []), body, "documents"),
    )
    return result


def _social_points(body: str, agencies: dict[str, Any]) -> list[dict[str, str]]:
    aliases, points = agencies.get("district_aliases", {}), []
    for _, name, address in _point_row.findall(body):
        name, address = name.strip(), address.strip()
        suffix = _district_suffix.search(address)
        if suffix:
            district = suffix.group(1).strip()
            points.append({"name": name, "address": address, "district": aliases.get(district, district)})
    return points


def _validate_choice_sources(step: dict[str, Any]) -> None:
    choices = step.get("choices")
    if not isinstance(choices, list) or not choices:
        raise PlanError("Seçim adımında seçenek bulunamadı.")
    for choice in choices:
        index = choice.get("source") if isinstance(choice, dict) else False
        if index is not None and (type(index) is not int or not 0 <= index < len(step["sources"])):
            raise PlanError("Seçim bilinmeyen bir kaynağa bağlı.")


def _add_points(step: dict[str, Any], agencies: dict[str, Any], store: Any | None) -> None:
    step["districts"] = list(agencies.get("districts", []))
    source = next((item for item in step["sources"] if item["indexed"]), None)
    document = store.current_document(source["url"]) if source and store else None
    step["points"] = _social_points(str(document["body"]), agencies) if document else []
    if not step["points"]:
        step["kind"], step["source_missing"] = "link", True


def _make_step(source_step: Any, agencies: dict[str, Any], store: Any | None) -> dict[str, Any]:
    required = {"id", "title", "title_en", "agency", "kind", "sources"}
    if not isinstance(source_step, dict) or not required <= set(source_step):
        raise PlanError("Plan adımının alanları eksik.")
    step = dict(source_step)
    if (
        not isinstance(step["id"], str)
        or not isinstance(step["agency"], str)
        or step["kind"] not in {"choice", "task", "link", "points"}
    ):
        raise PlanError("Plan adımının kimliği, kurumu ya da türü geçersiz.")
    step["agency_info"] = _agency(step["agency"], agencies)
    raw_sources = step["sources"]
    if not isinstance(raw_sources, list):
        raise PlanError("Plan kaynağı listesi geçersiz.")
    step["sources"] = [_source(item, store) for item in raw_sources]
    step["source_missing"] = bool(raw_sources) and not any(item["indexed"] for item in step["sources"])
    if step["kind"] == "link" and raw_sources:
        raise PlanError("Kurum bağlantısı adımına dizin alıntısı eklenemez.")
    if step["kind"] == "choice":
        _validate_choice_sources(step)
    if step["kind"] == "points":
        _add_points(step, agencies, store)
    return step


def load_plans(path: str | pathlib.Path, store: Any | None, agencies: dict[str, Any]) -> list[dict[str, Any]]:
    """Load reviewed plan text with metadata from current local pages and agencies."""
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanError("Yaşam olayı planları okunamadı.") from exc
    if not isinstance(data, dict) or set(data) != {"version", "checked_at", "index", "plans"} or data.get("version") != 1:
        raise PlanError("Yaşam olayı planlarının biçimi geçersiz.")
    if not isinstance(data["plans"], list):
        raise PlanError("Yaşam olayı planlarının biçimi geçersiz.")
    seen_plans, plans = set(), []
    for plan in data["plans"]:
        if not isinstance(plan, dict) or not {"id", "title", "title_en", "steps"} <= set(plan):
            raise PlanError("Plan başlığı ya da adımları eksik.")
        if not isinstance(plan["id"], str) or plan["id"] in seen_plans or not isinstance(plan["steps"], list):
            raise PlanError("Plan kimliği yinelenmiş ya da adımlar geçersiz.")
        seen_plans.add(plan["id"])
        steps, seen_steps = [], set()
        for source_step in plan["steps"]:
            step = _make_step(source_step, agencies, store)
            if step["id"] in seen_steps:
                raise PlanError("Plan adımının kimliği yinelenmiş.")
            seen_steps.add(step["id"])
            steps.append(step)
        plans.append({"id": plan["id"], "title": plan["title"], "title_en": plan["title_en"], "steps": steps})
    return plans


def _readonly_knowledge() -> KnowledgeStore | None:
    raw = os.environ.get("NABIZ_KNOWLEDGE_DB", "data/knowledge/knowledge.db")
    path = pathlib.Path(raw).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    if not path.is_file():
        return None
    # current_document only reads; skip KnowledgeStore.__init__, whose setup path may optimize FTS.
    store = object.__new__(KnowledgeStore)
    store.path = path
    return store


def plans_for(request: Request) -> list[dict[str, Any]]:
    cached = getattr(request.app.state, "life_events", None)
    if cached is None:
        agencies = json.loads(_agency_path.read_text(encoding="utf-8"))
        cached = load_plans(_plan_path, _readonly_knowledge(), agencies)
        request.app.state.life_events = cached
    return cached


def case_store_for(request: Request) -> CaseFileStore:
    state = request.app.state
    if getattr(state, "case_files", None) is None:
        accounts = accounts_api.store_for(request)
        state.case_files = CaseFileStore(case_files_path(), accounts_path=accounts.path)
    return state.case_files


def _account_owner(request: Request) -> tuple[str, str] | None:
    account = accounts_api.current_account(request)
    return ("account", account.id) if account is not None else None


def _owner(request: Request) -> tuple[str, str]:
    account_owner = _account_owner(request)
    if account_owner is not None:
        return account_owner
    key = request.headers.get(CASE_HEADER)
    if key:
        return "device", token_hash(key)
    raise CaseFileError(401, "no_owner", "Bu cihazda iş dosyası yok.")


def _plan(plans: list[dict[str, Any]], plan_id: str) -> dict[str, Any]:
    return next(item for item in plans if item["id"] == plan_id)


def _public_file(file: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    steps_by_id = {item["step_id"]: item for item in file["steps"]}
    steps = []
    for plan_step in plan["steps"]:
        saved = steps_by_id.get(plan_step["id"], {})
        steps.append(
            {
                "step_id": plan_step["id"],
                "done_at": saved.get("done_at"),
                "note": saved.get("note"),
                "ref_code": saved.get("ref_code"),
                "remind_on": saved.get("remind_on"),
                "added_by": "user",
                "verified": False,
            }
        )
    return {
        "id": file["id"],
        "plan_id": file["plan_id"],
        "answers": file["answers"],
        "steps": steps,
        "progress": progress(file, plan),
        "updated_at": file["updated_at"],
        "expires_at": file["expires_at"],
        "plan": plan,
        "message": "İş dosyanız kaydedildi.",
        "band": BAND,
    }


def _reminders(files: list[dict[str, Any]], plans: list[dict[str, Any]]) -> list[dict[str, str]]:
    plan_by_id = {plan["id"]: plan for plan in plans}
    today = dt.datetime.now(ISTANBUL_TZ).date()
    return [
        {"file_id": file["id"], "plan_id": file["plan_id"], **item}
        for file in files
        if file["plan_id"] in plan_by_id
        for item in due_reminders(file, plan_by_id[file["plan_id"]], today)
    ]


def _rate_key(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return hashlib.sha256(host.encode("utf-8")).hexdigest()


def _case_error(exc: CaseFileError):
    return port_problem(exc.status, exc.code, exc.message)


@case_file_routes.get("/plans")
async def list_plans(request: Request):
    try:
        plans = plans_for(request)
    except (PlanError, OSError, json.JSONDecodeError):
        return port_problem(503, "plans_unavailable", "Plan bilgisi açılamadı. Yeniden deneyin.")
    return {
        "plans": plans,
        "band": BAND,
        "consent": {"text": CONSENT_TEXT, "version": CONSENT_VERSION},
        "limits": {"note": 280, "reference": 40, "reminder_days": 365},
    }


@case_file_routes.post("")
async def create_file(request: Request, body: CreateBody):
    host_key = _rate_key(request)
    if not create_limit.allow(host_key):
        return port_problem(429, "too_many_creates", "Bir saat içinde en çok on iş dosyası açabilirsiniz.")
    try:
        plans = plans_for(request)
        account_owner = _account_owner(request)
        owner = account_owner or ("device", request.headers.get(CASE_HEADER, ""))
        file, key = case_store_for(request).create(owner, body.plan_id, body.consent)
        result = {"file": _public_file(file, _plan(plans, file["plan_id"])), "band": BAND}
        if key is not None:
            result["key"] = key
        return result
    except CaseFileError as exc:
        return _case_error(exc)
    except (PlanError, OSError, json.JSONDecodeError):
        return port_problem(503, "plans_unavailable", "Plan bilgisi açılamadı. Yeniden deneyin.")


@case_file_routes.post("/open")
async def open_files(request: Request):
    try:
        plans = plans_for(request)
        files = case_store_for(request).files(_owner(request))
        return {
            "files": [_public_file(file, _plan(plans, file["plan_id"])) for file in files],
            "reminders": _reminders(files, plans),
            "band": BAND,
        }
    except CaseFileError as exc:
        return _case_error(exc)
    except (PlanError, OSError, json.JSONDecodeError):
        return port_problem(503, "plans_unavailable", "Plan bilgisi açılamadı. Yeniden deneyin.")


@case_file_routes.post("/{file_id}/answer")
async def answer_step(request: Request, body: AnswerBody, file_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,32}$")):
    try:
        plans = plans_for(request)
        file = case_store_for(request).set_answer(_owner(request), file_id, body.step_id, body.choice)
        return {"file": _public_file(file, _plan(plans, file["plan_id"])), "band": BAND}
    except CaseFileError as exc:
        return _case_error(exc)
    except (PlanError, OSError, json.JSONDecodeError):
        return port_problem(503, "plans_unavailable", "Plan bilgisi açılamadı. Yeniden deneyin.")


@case_file_routes.post("/{file_id}/step")
async def update_step(request: Request, body: StepBody, file_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,32}$")):
    try:
        plans = plans_for(request)
        file = case_store_for(request).set_step(
            _owner(request),
            file_id,
            body.step_id,
            done=body.done,
            note=body.note,
            ref_code=body.ref_code,
            remind_on=body.remind_on,
        )
        return {"file": _public_file(file, _plan(plans, file["plan_id"])), "band": BAND}
    except CaseFileError as exc:
        return _case_error(exc)
    except (PlanError, OSError, json.JSONDecodeError):
        return port_problem(503, "plans_unavailable", "Plan bilgisi açılamadı. Yeniden deneyin.")


@case_file_routes.delete("/{file_id}")
async def delete_file(request: Request, file_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,32}$")):
    try:
        case_store_for(request).delete(_owner(request), file_id)
        return {"deleted": True, "band": BAND}
    except CaseFileError as exc:
        return _case_error(exc)


__all__ = ["case_file_routes", "create_limit", "case_store_for", "plans_for"]
