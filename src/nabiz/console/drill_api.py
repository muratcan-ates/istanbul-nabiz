"""Operator endpoint for integrity drills against a temporary ledger copy."""

from __future__ import annotations

import asyncio
import threading

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from nabiz.console.operator import port_problem
from nexus_core.engine import NexusEngine
from nexus_core.ledger_drill import DrillRefused, run_drill

drill_routes = APIRouter(prefix="/api/console")
_DRILL_LOCK = threading.Lock()


class DrillBody(BaseModel):
    kind: str = Field(default="", max_length=16)


def _engine(request: Request) -> NexusEngine | None:
    ports = getattr(request.app.state, "ports", None)
    console = getattr(ports, "console", None)
    engine = getattr(console, "engine", None)
    return engine if isinstance(engine, NexusEngine) else None


@drill_routes.post("/ledger/drill")
async def console_ledger_drill(request: Request, body: DrillBody):
    if not _DRILL_LOCK.acquire(blocking=False):
        return port_problem(409, "drill_busy", "Bir tatbikat zaten sürüyor; birazdan yeniden deneyin.")
    try:
        engine = _engine(request)
        if engine is None:
            return port_problem(503, "not_wired", "Karar çekirdeği bu süreçte bağlı değil.")
        try:
            result = await asyncio.to_thread(run_drill, engine.ledger, body.kind.strip())
        except DrillRefused as exc:
            errors = {
                "unknown_kind": (400, "unknown_drill", "Bilinmeyen tatbikat türü. Bilinenler: detay, silme, sira, hash."),
                "empty": (409, "empty_ledger", "Defter boş; bozulacak kayıt yok."),
                "too_few": (409, "too_few_entries", "Bu tatbikat için defterde en az 2 kayıt gerekir."),
            }
            status, code, message = errors[exc.code]
            return port_problem(status, code, message)
        return result.model_dump(mode="json")
    finally:
        _DRILL_LOCK.release()
