"""The integrity drill breaks only a temporary database and explains what caught it."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nexus_helpers import Clock, build_engine

import nabiz.console.drill_api as drill_api
from nabiz.console.drill_api import drill_routes
from nabiz.console.nexus_port import NexusConsole
from nabiz.console.ports import Ports
from nexus_core.ledger import EntryKind, Ledger
from nexus_core.ledger_drill import DRILL_KINDS, DrillRefused, run_drill

EXPECTED = {
    "detay": (3, "icerik"),
    "silme": (4, "eksik_kayit"),
    "sira": (3, "bag"),
    "hash": (4, "bag"),
}


def populated(tmp_path: pathlib.Path, count: int = 6):
    engine = build_engine(tmp_path, Clock())
    for number in range(count):
        engine.ledger.append(
            EntryKind.SIGNAL,
            actor="kaynak",
            detail={"sample": number},
            signal_id=f"signal-{number}",
            entity_id=f"entity-{number}",
        )
    return engine


def client_for(engine) -> TestClient:
    app = FastAPI()
    app.state.ports = Ports(
        console=NexusConsole(engine, nabiz=None, recorded=lambda: None, offline=True),  # type: ignore[arg-type]
    )
    app.include_router(drill_routes)
    return TestClient(app)


@pytest.mark.parametrize(("kind", "expected_id", "check"), [(key, *value) for key, value in EXPECTED.items()])
def test_each_break_is_caught_where_the_chain_says(
    tmp_path: pathlib.Path, kind: str, expected_id: int, check: str
) -> None:
    engine = populated(tmp_path)
    result = run_drill(engine.ledger, kind, work_dir=tmp_path)
    assert result.caught and result.caught_at_id == expected_id
    assert result.check == check and result.copy_entries == 6
    assert result.target_id == 3 and result.original.unchanged and result.original.verify_ok


def test_the_original_ledger_is_byte_for_byte_the_same(tmp_path: pathlib.Path) -> None:
    engine = populated(tmp_path)
    before = engine.ledger.path.read_bytes()
    for kind in DRILL_KINDS:
        result = run_drill(engine.ledger, kind, work_dir=tmp_path)
        assert result.original.unchanged
        assert engine.ledger.path.read_bytes() == before


def test_the_work_dir_is_empty_after_a_drill_and_after_a_failure(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = populated(tmp_path)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    run_drill(engine.ledger, "detay", work_dir=work_dir)
    assert list(work_dir.iterdir()) == []

    def fail_verify(self):
        raise RuntimeError("verification failed")

    monkeypatch.setattr(Ledger, "verify", fail_verify)
    with pytest.raises(RuntimeError, match="verification failed"):
        run_drill(engine.ledger, "detay", work_dir=work_dir)
    assert list(work_dir.iterdir()) == []


def test_an_empty_ledger_and_a_single_entry_are_refused_honestly(tmp_path: pathlib.Path) -> None:
    empty = populated(tmp_path / "empty", count=0)
    with pytest.raises(DrillRefused) as empty_error:
        run_drill(empty.ledger, "detay", work_dir=tmp_path)
    assert empty_error.value.code == "empty"

    one = populated(tmp_path / "one", count=1)
    with pytest.raises(DrillRefused) as small_error:
        run_drill(one.ledger, "silme", work_dir=tmp_path)
    assert small_error.value.code == "too_few"
    result = run_drill(one.ledger, "detay", work_dir=tmp_path)
    assert result.caught and result.target_id == 1


def test_a_drill_during_two_concurrent_appends(tmp_path: pathlib.Path) -> None:
    engine = populated(tmp_path)
    book = engine.ledger
    start = threading.Barrier(3)

    def append_many(worker: int) -> None:
        start.wait()
        for number in range(20):
            book.append(
                EntryKind.SIGNAL,
                actor=f"worker-{worker}",
                detail={"worker": worker, "number": number},
                signal_id=f"worker-{worker}-{number}",
            )

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(append_many, worker) for worker in range(2)]
        start.wait()
        results = [run_drill(book, kind, work_dir=tmp_path) for kind in DRILL_KINDS]
        for future in futures:
            future.result(timeout=30)

    assert all(result.caught for result in results)
    verified = book.verify()
    assert verified.ok and verified.entries == 6 + 40


def test_the_drill_route_contract_and_its_errors(tmp_path: pathlib.Path) -> None:
    engine = populated(tmp_path / "full")
    with client_for(engine) as client:
        success = client.post("/api/console/ledger/drill", json={"kind": "silme"})
        assert success.status_code == 200, success.text
        payload = success.json()
        assert {
            "kind", "kind_label", "target_id", "caught", "caught_at_id", "check", "check_label",
            "copy_entries", "sentence", "note", "original",
        } == payload.keys()
        assert payload["original"]["unchanged"] and payload["caught"]
        unknown = client.post("/api/console/ledger/drill", json={"kind": "unknown"})
        assert unknown.status_code == 400 and unknown.json()["error"] == "unknown_drill"

    empty = populated(tmp_path / "empty", count=0)
    with client_for(empty) as client:
        response = client.post("/api/console/ledger/drill", json={"kind": "detay"})
        assert response.status_code == 409 and response.json()["error"] == "empty_ledger"

    one = populated(tmp_path / "one", count=1)
    with client_for(one) as client:
        response = client.post("/api/console/ledger/drill", json={"kind": "silme"})
        assert response.status_code == 409 and response.json()["error"] == "too_few_entries"
        assert client.post("/api/console/ledger/drill", json={"kind": "detay"}).status_code == 200

    app = FastAPI()
    app.state.ports = Ports()
    app.include_router(drill_routes)
    with TestClient(app) as client:
        response = client.post("/api/console/ledger/drill", json={"kind": "detay"})
        assert response.status_code == 503 and response.json()["error"] == "not_wired"


def test_the_drill_route_leaves_the_real_ledger_file_unchanged(tmp_path: pathlib.Path) -> None:
    engine = populated(tmp_path)
    before = engine.ledger.path.read_bytes()
    with client_for(engine) as client:
        result = client.post("/api/console/ledger/drill", json={"kind": "hash"})
    assert result.status_code == 200 and result.json()["original"]["unchanged"]
    assert engine.ledger.path.read_bytes() == before


def test_a_second_route_call_is_refused_while_a_drill_is_running(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    busy = threading.Lock()
    busy.acquire()
    monkeypatch.setattr(drill_api, "_DRILL_LOCK", busy)
    engine = populated(tmp_path)
    with client_for(engine) as client:
        response = client.post("/api/console/ledger/drill", json={"kind": "detay"})
    busy.release()
    assert response.status_code == 409 and response.json()["error"] == "drill_busy"


def test_the_drill_card_says_the_real_ledger_did_not_change(tmp_path: pathlib.Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    module = json.dumps((pathlib.Path(__file__).parents[1] / "src/nabiz/console/static/js/console_drill.js").as_uri())
    harness = tmp_path / "drill_harness.mjs"
    harness.write_text(
        "globalThis.window = { location: { search: '', origin: 'http://localhost' } };\n"
        f"const {{drillControls, drillCard, DRILL_KINDS}} = await import({module});\n"
        "const base = {kind:'silme',caught:true,sentence:'Kayıt #3 bozuldu.',note:'tatbikat · gerçek defter değişmedi',"
        "original:{sha256_before:'abcdef0123456789',sha256_after:'abcdef0123456789',unchanged:true,verify_ok:true,entries:6}};\n"
        "const ok = drillCard(base);\n"
        "const missed = drillCard({...base,caught:false,original:{...base.original,unchanged:false}});\n"
        "console.log(JSON.stringify({controls:drillControls(),ok,missed,kinds:DRILL_KINDS.length}));\n",
        encoding="utf-8",
    )
    process = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert process.returncode == 0, process.stderr
    rendered = json.loads(process.stdout)
    assert rendered["kinds"] == 4
    assert rendered["ok"].count('class="tag is-ok"') == 1
    assert "gerçek defter değişmedi" in rendered["ok"] and "Kayıt #3 bozuldu." in rendered["ok"]
    assert "yakalamadı" in rendered["missed"] and 'class="tag is-bad"' in rendered["missed"]
    assert all(f'data-nx-drill="{kind}"' in rendered["controls"] for kind in DRILL_KINDS)
    assert 'aria-live="polite"' in rendered["controls"]
