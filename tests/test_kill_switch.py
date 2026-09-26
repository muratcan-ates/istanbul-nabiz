"""The operator chat pause stays reasoned, private and safe on damaged state."""

from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest
from conftest import offline_settings
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import Mount
from fastapi.testclient import TestClient

from nabiz.agent import llm
from nabiz.console.access import OperatorAccess
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.kill_switch import (
    CHAT_ENTITY,
    CHAT_PAUSE_KIND,
    CHAT_RESUME_KIND,
    PAUSED_MESSAGE,
    ChatPause,
    PauseStore,
    set_chat_pause,
)
from nabiz.console.kill_switch_api import chat_gate, kill_switch_routes
from nexus_core.ledger import Ledger
from nexus_core.state import replay

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONSOLE_STATIC = ROOT / "src" / "nabiz" / "console" / "static"


@pytest.fixture
def paths(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Keep every state and ledger write inside this test's private temporary folder."""
    monkeypatch.setenv("NABIZ_CHAT_PAUSE_PATH", str(tmp_path / "chat_paused.json"))
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "nexus.db"))
    return tmp_path


def pause_client(access: OperatorAccess | None = None, base_url: str = "http://127.0.0.1:8090") -> TestClient:
    """Mount the new router before the app's static catch-all, as the integrator will."""
    app = build_console_app(
        settings=offline_settings(), llm_config=llm.LlmConfig(),
        guard=SpendGuard(BudgetConfig(state_path=None)), access=access or OperatorAccess(),
    )
    static = app.router.routes.pop()
    assert isinstance(static, Mount)
    app.include_router(kill_switch_routes)
    app.router.routes.append(static)
    return TestClient(app, base_url=base_url)


def test_no_file_means_the_chat_is_open(paths: pathlib.Path) -> None:
    store = PauseStore(paths / "missing.json")
    assert store.read() == ChatPause()
    with pause_client() as client:
        assert client.get("/api/service-status").json() == {"chat": "open", "message": None}


def test_pause_then_status_then_resume(paths: pathlib.Path) -> None:
    with pause_client() as client:
        paused = client.post("/api/console/chat-pause", json={"paused": True, "reason": "Model yanlış hat bilgisi veriyor"})
        assert paused.status_code == 200
        assert paused.json()["paused"] is True
        assert paused.json()["by_role"] == "Simüle operatör"
        assert isinstance(paused.json()["ledger_entry_id"], int)
        assert client.get("/api/service-status").json() == {"chat": "paused", "message": PAUSED_MESSAGE}
        assert "Model yanlış hat bilgisi veriyor" in client.get("/api/console/chat-pause").json()["reason"]
        resumed = client.post("/api/console/chat-pause", json={"paused": False, "reason": "Düzeltildi"})
        assert resumed.status_code == 200 and resumed.json()["paused"] is False
        assert client.get("/api/service-status").json() == {"chat": "open", "message": None}


def test_service_status_hides_the_reason_and_is_not_cached(paths: pathlib.Path) -> None:
    with pause_client() as client:
        client.post("/api/console/chat-pause", json={"paused": True, "reason": "private reason"})
        response = client.get("/api/service-status")
        assert set(response.json()) == {"chat", "message"}
        assert "private reason" not in response.text
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("body", [{"paused": True, "reason": ""}, {"paused": True, "reason": "   "}, {"paused": True}])
def test_a_missing_reason_is_400_and_changes_nothing(paths: pathlib.Path, body: dict[str, object]) -> None:
    with pause_client() as client:
        response = client.post("/api/console/chat-pause", json=body)
        assert response.status_code == 400 and response.json()["error"] == "reason_required"
        assert not (paths / "chat_paused.json").exists()
        assert Ledger(paths / "nexus.db").entries() == []


def test_the_same_state_twice_is_409(paths: pathlib.Path) -> None:
    with pause_client() as client:
        body = {"paused": True, "reason": "Yanlış bilgi"}
        assert client.post("/api/console/chat-pause", json=body).status_code == 200
        conflict = client.post("/api/console/chat-pause", json=body)
        assert conflict.status_code == 409 and conflict.json()["error"] == "conflict"
        assert client.post("/api/console/chat-pause", json={"paused": False, "reason": "Aç"}).status_code == 200
        conflict = client.post("/api/console/chat-pause", json={"paused": False, "reason": "Aç"})
        assert conflict.status_code == 409 and len(Ledger(paths / "nexus.db").entries()) == 2


def test_a_too_long_reason_is_422_in_turkish(paths: pathlib.Path) -> None:
    with pause_client() as client:
        response = client.post("/api/console/chat-pause", json={"paused": True, "reason": "x" * 281})
    assert response.status_code == 422 and response.json()["error"] == "invalid_request"
    assert "pydantic" not in response.text


@pytest.mark.parametrize(
    "contents",
    ["{", "", "[]", '{"version":1,"paused":"yes"}', '{"version":9,"paused":true}',
     '{"version":1,"paused":true,"reason":5}'],
)
def test_a_corrupt_file_leaves_the_chat_open_and_logs(
    paths: pathlib.Path, caplog: pytest.LogCaptureFixture, contents: str
) -> None:
    path = paths / "chat_paused.json"
    path.write_text(contents, encoding="utf-8")
    store = PauseStore(path)
    with caplog.at_level("WARNING"):
        assert store.read().paused is False
    assert len(caplog.records) == 1
    if contents:
        assert contents not in caplog.text
    with pause_client() as client:
        response = client.post("/api/console/chat-pause", json={"paused": True, "reason": "Tekrar karar verildi"})
    assert response.status_code == 200 and store.read().paused is True


def test_the_write_is_atomic(paths: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = paths / "chat_paused.json"
    store = PauseStore(path)
    state = ChatPause(True, "Gerekçe", "2026-09-28T06:05:00+00:00", "Simüle operatör", 42)
    store.write(state)
    original = path.read_bytes()
    assert {item.name for item in paths.iterdir()} == {"chat_paused.json"}

    def fail_replace(source: str, target: pathlib.Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError):
        store.write(ChatPause(False))
    assert path.read_bytes() == original
    assert {item.name for item in paths.iterdir()} == {"chat_paused.json"}


def test_the_ledger_records_both_decisions_and_nothing_else_moves(paths: pathlib.Path) -> None:
    store, ledger = PauseStore(paths / "chat_paused.json"), Ledger(paths / "nexus.db")
    set_chat_pause(store, ledger, paused=True, reason="Yanlış bilgi")
    set_chat_pause(store, ledger, paused=False, reason="Düzeltildi")
    entries = ledger.entries()
    assert len(entries) == 2
    assert entries[0].kind == CHAT_PAUSE_KIND and entries[1].kind == CHAT_RESUME_KIND
    assert CHAT_PAUSE_KIND != CHAT_RESUME_KIND and "approval" not in {CHAT_PAUSE_KIND, CHAT_RESUME_KIND}
    assert [entry.detail["action"] for entry in entries] == ["pause", "resume"]
    assert all(entry.detail["kind"] == "chat_pause" and entry.signal_id is None for entry in entries)
    assert all(entry.entity_id == CHAT_ENTITY for entry in entries)
    assert all(entry.actor == "Simüle operatör (simule-operator)" for entry in entries)
    assert ledger.verify().ok is True and replay(entries) == {}


def test_a_ledger_failure_leaves_the_state_unchanged(paths: pathlib.Path) -> None:
    class FailingLedger:
        def append(self, *args: object, **kwargs: object) -> None:
            raise OSError("unavailable")

    store = PauseStore(paths / "chat_paused.json")
    with pytest.raises(OSError):
        set_chat_pause(store, FailingLedger(), paused=True, reason="Gerekçe")  # type: ignore[arg-type]
    assert store.read().paused is False and not store.path.exists()


def test_chat_gate_answers_503_only_while_paused(paths: pathlib.Path) -> None:
    app = FastAPI()
    app.state.chat_pause_store = PauseStore(paths / "chat_paused.json")

    @app.post("/api/chat")
    async def chat(request: Request):
        return chat_gate(request) or JSONResponse({"ok": True})

    client = TestClient(app)
    assert client.post("/api/chat").status_code == 200
    app.state.chat_pause_store.write(ChatPause(True, "Private", "2026-09-28T06:05:00+00:00", "role", 1))
    response = client.post("/api/chat")
    assert response.status_code == 503
    assert response.json() == {"error": "chat_paused", "message": PAUSED_MESSAGE, "tel": "153"}
    assert response.headers["cache-control"] == "no-store"


def test_the_console_door_guards_the_switch(paths: pathlib.Path) -> None:
    evil = pause_client(OperatorAccess(), base_url="http://evil.example:8090")
    assert evil.post("/api/console/chat-pause", json={"paused": True, "reason": "X"}).status_code == 403
    assert evil.get("/api/service-status").status_code == 200
    guarded = pause_client(OperatorAccess(token="t", bound_host="0.0.0.0"))
    assert guarded.post("/api/console/chat-pause", json={"paused": True, "reason": "X"}).status_code == 401
    assert guarded.post("/api/console/chat-pause", json={"paused": True, "reason": "X"},
                        headers={"X-Nabiz-Operator": "t"}).status_code == 200
    assert guarded.get("/api/service-status").status_code == 200


def test_kill_switch_modules_import_no_model_or_network() -> None:
    forbidden = {"httpx", "openai", "nabiz.agent", "ibb_mcp.tools"}
    for name in ("kill_switch.py", "kill_switch_api.py"):
        tree = ast.parse((ROOT / "src" / "nabiz" / "console" / name).read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        assert not any(item == blocked or item.startswith(f"{blocked}.") for item in imports for blocked in forbidden)


def _node_json(module_path: pathlib.Path, expression: str) -> dict[str, object] | None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    module = json.dumps(module_path.as_uri())
    script = (
        "globalThis.window = { location: { search: '', origin: 'http://localhost' } };\n"
        f"const mod = await import({module});\n"
        f"console.log(JSON.stringify({expression}));\n"
    )
    proc = subprocess.run([node, "--input-type=module", "--eval", script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_console_switch_markup() -> None:
    data = _node_json(
        CONSOLE_STATIC / "js" / "console_kill.js",
        "({section:mod.sectionMarkup(), pause:mod.dialogMarkup(false), resume:mod.dialogMarkup(true), "
        "badge:mod.badgeText({paused:true,since:'2026-09-28T06:05:00+00:00'}), "
        "empty:mod.pauseRequest(true,'  ')})",
    )
    assert data is not None
    assert 'role="switch"' in data["section"] and 'aria-checked="true"' in data["section"]
    assert 'id="chat-pause-state"' in data["section"] and 'role="status"' in data["section"]
    assert "Vatandaş sohbetini durdur" in data["pause"] and 'maxlength="280"' in data["pause"]
    assert "Vazgeç" in data["pause"] and "Kişi adı yazmayın" in data["pause"]
    assert "Sohbeti aç" in data["resume"]
    assert data["badge"] == "Sohbet durduruldu · 09:05" and data["empty"] is None


def test_service_band_markup() -> None:
    data = _node_json(
        CONSOLE_STATIC / "js" / "service_status.js",
        "({html:mod.bandMarkup({chat:'paused',message:'Sohbet durduruldu.'}), "
        "open:mod.isPaused({chat:'open'})})",
    )
    assert data is not None
    assert "Sohbet durduruldu" in data["html"]
    assert 'href="tel:153"' in data["html"] and data["html"].count("tel:") == 1
    assert data["open"] is False


def test_kill_switch_assets_follow_the_page_rules() -> None:
    assets = [
        CONSOLE_STATIC / "js" / "console_kill.js",
        CONSOLE_STATIC / "js" / "service_status.js",
        CONSOLE_STATIC / "css" / "service_status.css",
    ]
    assert all(path.is_file() for path in assets)
    content = {path.name: path.read_text(encoding="utf-8") for path in assets}
    for text in content.values():
        assert "\u2014" not in text and "\u2013" not in text
        assert "ETA" not in text
        assert "Ben İstanbul şehir bilgi asistanıyım" not in text
    styles = content["service_status.css"]
    assert not any(token in styles for token in ("#", "rgb(", "hsl(", "oklch(", "animation", "transition", "@keyframes"))
    assert "min-height: 44px" in styles
    for filename in ("console_kill.js", "service_status.js"):
        script = content[filename]
        forbidden = ("localStorage", "sessionStorage", "indexedDB", "window.confirm", "window.prompt")
        assert not any(token in script for token in forbidden)
        assert len(script.splitlines()) <= 300
    status = content["service_status.js"]
    assert "fetch(" not in status and "setInterval" in status and "visibilitychange" in status
    assert "'/api/service-status'" in status and "window.addEventListener('submit', guard, true)" in status
    assert "document.addEventListener('submit'" not in status
    easy = CONSOLE_STATIC / "kolay.html"
    if easy.exists():
        html = easy.read_text(encoding="utf-8")
        assert all(f'id="{name}"' in html for name in ("chat-form", "chat-input", "chat-submit"))
    assert len(styles.splitlines()) <= 350
    for script_path in assets[:2]:
        for target in re.findall(r"from\s+['\"]\./([^'\"]+)['\"]", script_path.read_text(encoding="utf-8")):
            assert (script_path.parent / target).is_file()
