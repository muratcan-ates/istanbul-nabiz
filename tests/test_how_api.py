"""``GET /api/how`` and the "Nasıl çalışır?" page (``/nasil.html``).

Every number the page shows comes from a file or from process state; these tests re-derive each one on
their own (the server's tool list, ``load_missions``, SQL counts, their own regexes over the eval
reports and NOTICE.md) and compare. No value is written here either. Offline, no network, tmp dirs.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import re
import shutil
import sys
import types
from typing import Any

from conftest import REPO_ROOT
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_console_api import FakeConsole
from test_knowledge_store import seed_page

from ibb_mcp.config import HardeningConfig
from ibb_mcp.knowledge.store import KnowledgeStore
from ibb_mcp.server import build_server
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console import how_api
from nabiz.console.access import is_operator_path
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.how_api import (
    REASON_MISSING,
    REASON_TRAPS,
    how_payload,
    how_routes,
    ledger_state,
    model_part,
    notice_rows,
    organs_part,
    server_tools,
)
from nabiz.console.ports import Ports, UnwiredConsole
from nexus_core.missions import load_missions

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
RESULTS = REPO_ROOT / "eval" / "results"
ETA_FILE = RESULTS / "eta.md"
AGENT_FILE = sorted(RESULTS.glob("*-agent-*.md"))[-1]
NOW = dt.datetime(2026, 9, 26, 9, 0, 0, tzinfo=dt.UTC)
TOP_KEYS = {
    "checked_at", "tools", "rules", "index", "model", "ledger", "organs", "organs_label", "capabilities", "metrics",
    "open_source",
}  # fmt: skip
PAID = llm.LlmConfig(base_url="https://model.invalid/v1", provider="openai_compatible", api_key="k-123", model="m")
LOCAL = llm.LlmConfig(base_url=llm.FOUNDRY_LOCAL_URL, provider="foundry_local")


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def payload(**overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "root": REPO_ROOT,
        "missions_path": REPO_ROOT / "missions",
        "store": None,
        "model": model_part(llm.LlmConfig(), lambda provider: True),
        "ledger": None,
        "organs": None,
        "now": NOW,
    }
    return how_payload(**{**args, **overrides})


def metric(body: dict[str, Any], key: str) -> dict[str, Any]:
    return next(row for row in body["metrics"] if row["key"] == key)


def results_copy(tmp_path) -> tuple[Any, Any, Any]:
    results = tmp_path / "eval" / "results"
    results.mkdir(parents=True)
    eta = results / "eta.md"
    agent = results / AGENT_FILE.name
    shutil.copy(ETA_FILE, eta)
    shutil.copy(AGENT_FILE, agent)
    return tmp_path, eta, agent


def columns(p: dict[str, Any]) -> tuple[set[str], set[str]]:
    caps = p["capabilities"]
    return {c["key"] for c in caps["today"]}, {c["key"] for c in caps["planned"]}


# ---- tools, rules, index --------------------------------------------------------------------------


async def test_tool_count_matches_the_registered_server_tools(ctx) -> None:
    registered = {t.name for t in await build_server(app=Nabiz(ctx), hardening=HardeningConfig()).list_tools()}
    names = server_tools()
    assert names is not None and set(names) == registered and len(names) == len(registered)
    assert payload()["tools"]["count"] == len(registered)


def test_rule_count_comes_from_the_mission_files(tmp_path) -> None:
    (tmp_path / "deneme.toml").write_text(
        """
[mission]
id = "deneme"
title = "Deneme"
reviewed_on = 2026-09-25

[[rules]]
id = "T-01"
path = "reflex"
expires_days = 30
[rules.when]
kind = "equipment_fault"
conditions = [{ field = "equipment_type", op = "eq", value = "elevator" }]
[rules.then]
action = "publish_card"
card_kind = "metro_equipment"
card_template = "{station} istasyonunda asansör kaydı var."

[[rules]]
id = "T-02"
path = "arena"
expires_days = 30
[rules.when]
kind = "source_stale"
conditions = [{ field = "source", op = "present" }]
[rules.then]
action = "publish_card"
card_kind = "metro_status"
card_template = "{source} verisi eski."
""",
        encoding="utf-8",
    )
    rules = payload(missions_path=tmp_path)["rules"]
    assert rules["count"] == 2 and rules["missions"] == [{"id": "deneme", "title": "Deneme", "rules": 2}]
    real = payload()["rules"]
    assert real["count"] == sum(len(m.rules) for m in load_missions(REPO_ROOT / "missions"))


def test_missing_index_says_not_built() -> None:
    index = payload(store=None)["index"]
    assert index["built"] is False and index["label"] == "indeks kurulmadı"
    assert index["documents"] is None and index["chunks"] is None


def test_seeded_index_reports_documents_chunks_and_last_ingest(tmp_path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, "Su aboneliği başvurusu resmî kaynak sayfasında açıklanır. İkinci cümle de burada durur.")
    with store._connect() as db:
        chunks = db.execute("SELECT COUNT(*) FROM chunks WHERE active=1").fetchone()[0]
    index = payload(store=store)["index"]
    assert index["built"] is True and index["documents"] == 1 and index["chunks"] == chunks
    assert index["built_at"] and index["label"] is None


# ---- measured results -----------------------------------------------------------------------------


def test_metrics_follow_the_eval_files(tmp_path) -> None:
    eta_text, agent_text = ETA_FILE.read_text(encoding="utf-8"), AGENT_FILE.read_text(encoding="utf-8")
    real = payload()
    mae = re.search(r"\| Mean absolute error \| ([\d.]+) min \|", eta_text).group(1)
    median = re.search(r"\| Median absolute error \| ([\d.]+) min \|", eta_text).group(1)
    within = re.search(r"\| Within 5 minutes \| ([\d.]+)% \|", eta_text).group(1)
    size = int(re.search(r"\| Sample size \| (\d+) \|", eta_text).group(1))
    hit, total = re.search(r"\| Numeric faithfulness \| [\d.]+% \((\d+)/(\d+) numbers\)", agent_text).groups()
    chain = re.search(r"\| Tool-call accuracy \| ([\d.]+)% exact chain", agent_text).group(1)
    assert metric(real, "arrival_mae")["value"] == float(mae)
    assert metric(real, "arrival_mae")["display"] == f"{mae.replace('.', ',')} dk"
    assert metric(real, "arrival_mae")["n"] == size
    assert metric(real, "arrival_mae")["n_display"] == f"{size:,}".replace(",", ".")
    assert metric(real, "arrival_median")["value"] == float(median)
    assert metric(real, "arrival_within5")["display"] == f"%{within.replace('.', ',')}"
    assert metric(real, "faithfulness")["display"] == f"{hit}/{total}" and metric(real, "faithfulness")["value"] == int(hit)
    assert metric(real, "tool_chain")["value"] == float(chain)
    run_on = re.search(r"run on (\d{4}-\d{2}-\d{2})", eta_text).group(1)
    assert metric(real, "arrival_mae")["measured_on"] == run_on
    assert metric(real, "faithfulness")["measured_on"] == re.search(r"(\d{4}-\d{2}-\d{2})T", agent_text).group(1)
    assert all(row["status"] == "ölçüldü" for row in real["metrics"] if row["key"] != "traps")

    root, eta, _ = results_copy(tmp_path)
    eta.write_text(
        eta_text.replace(f"| Mean absolute error | {mae} min |", "| Mean absolute error | 9.87 min |"), encoding="utf-8"
    )
    changed = metric(payload(root=root), "arrival_mae")
    assert changed["display"] == "9,87 dk" and changed["value"] == 9.87


def test_the_numbers_sheet_rows_follow_numbers_md(tmp_path) -> None:
    numbers = REPO_ROOT / "eval" / "results" / "numbers.md"
    text = numbers.read_text(encoding="utf-8")
    passed = int(re.search(r"\| Tests passed \| (\d+) \|", text).group(1))
    real = payload()
    assert metric(real, "tests_passed")["value"] == passed
    assert metric(real, "tests_passed")["display"] == f"{passed:,}".replace(",", ".")
    assert metric(real, "tests_passed")["source"] == "eval/results/numbers.md"
    assert metric(real, "tests_passed")["measured_on"] == re.search(r"Measured (\d{4}-\d{2}-\d{2})T", text).group(1)
    assert metric(real, "eval_passed")["value"] == int(re.search(r"\| Eval scenarios passed \| (\d+) \|", text).group(1))

    root, _, _ = results_copy(tmp_path)
    assert metric(payload(root=root), "tests_passed")["status"] == "ölçülmedi"  # no sheet, no number
    sheet = root / "eval" / "results" / "numbers.md"
    sheet.write_text(text.replace(f"| Tests passed | {passed} |", "| Tests passed | 7 |"), encoding="utf-8")
    assert metric(payload(root=root), "tests_passed")["display"] == "7"


def test_a_metric_without_its_row_is_not_measured(tmp_path) -> None:
    root, eta, _ = results_copy(tmp_path)
    eta.write_text(
        "\n".join(line for line in eta.read_text(encoding="utf-8").splitlines() if "Mean absolute error" not in line),
        encoding="utf-8",
    )
    row = metric(payload(root=root), "arrival_mae")
    assert row["status"] == "ölçülmedi" and row["value"] is None and row["display"] is None
    assert row["reason"] == "kaynak dosyada satır bulunamadı" == REASON_MISSING
    eta.unlink()
    assert metric(payload(root=root), "arrival_median")["reason"] == REASON_MISSING


def test_traps_are_not_measured_until_a_run_has_j7_j8(tmp_path) -> None:
    row = metric(payload(), "traps")
    assert row["status"] == "ölçülmedi" and row["reason"] == "son ajan koşusunda J7 ve J8 yok" == REASON_TRAPS
    root, _, agent = results_copy(tmp_path)
    text = agent.read_text(encoding="utf-8").replace("| J4 |", "| J7 | 5/6 (83.3%) |\n| J8 | 6/6 (100.0%) |\n| J4 |", 1)
    agent.write_text(text, encoding="utf-8")
    row = metric(payload(root=root), "traps")
    assert row["status"] == "ölçüldü" and row["display"] == "11/12" and row["reason"] is None


def test_run_mode_comes_from_the_agent_file(tmp_path) -> None:
    real = payload()
    assert metric(real, "faithfulness")["mode"] == metric(real, "tool_chain")["mode"] == "modelsiz"
    for row in real["metrics"]:
        assert "modelsiz" not in row["label"] and "modelli" not in row["label"]
    root, _, agent = results_copy(tmp_path)
    original = agent.read_text(encoding="utf-8")
    agent.write_text(original.replace("no model configured", "keyword"), encoding="utf-8")
    body = payload(root=root)
    assert metric(body, "faithfulness")["mode"] is None
    assert "modelsiz" not in json.dumps(body["metrics"], ensure_ascii=False)
    header = re.sub(r"· agent: .*$", "· agent: model x-secret-model", original.splitlines()[2])
    agent.write_text(original.replace(original.splitlines()[2], header), encoding="utf-8")
    body = payload(root=root)
    assert metric(body, "faithfulness")["mode"] == "modelli"
    assert "x-secret-model" not in json.dumps(body, ensure_ascii=False)
    source = read("js/how.js")
    assert '"(modelsiz' not in source and "'(modelsiz" not in source and "(modelsiz" not in source
    assert "row.mode" in source and "modeSuffix(" in source


def test_metric_sources_show_no_file_path_to_the_citizen() -> None:
    for row in payload()["metrics"]:
        assert row["source_label"]
        assert not re.search(r"(?i)\beta\b|\.md\b|/", row["source_label"])
    source = read("js/how.js")
    row_builder = source[source.index("function metricRow") : source.index("function metricsMarkup")]
    assert "row.source_label" in row_builder and "row.source)" not in row_builder and "row.source}" not in row_builder
    assert "title=" not in row_builder
    assert "eta.md" not in read("nasil.html") and "eta.md" not in source


# ---- model, ledger, organs ------------------------------------------------------------------------


def test_model_ladder_names_no_url_key_or_model() -> None:
    config = llm.LlmConfig(base_url="http://localhost:5273/v1", provider="foundry_local", model="x-secret-model", api_key="k-123")
    text = json.dumps(payload(model=model_part(config, lambda provider: True)), ensure_ascii=False)
    for secret in ("http", "5273", "k-123", "x-secret-model", "base_url", "api_key"):
        assert secret not in text
    rungs = model_part(config, lambda provider: True)["rungs"]
    assert rungs[-1] == {"provider": "none", "label": "kural", "within_budget": True}


async def test_author_now_follows_the_chat_rule_not_the_ladder(monkeypatch, ctx) -> None:
    from nabiz.console.chat import ChatService

    monkeypatch.setitem(sys.modules, "nabiz.console.model_api", None)
    capped = SpendGuard(BudgetConfig(daily_calls=0, state_path=None))
    open_guard = SpendGuard(BudgetConfig(state_path=None))
    ladder = dataclasses.replace(PAID, fallback=LOCAL)

    # What the chat itself does: record the rung ChatService._run hands the model, then fall to the rules.
    picked: list[str] = []

    async def ask_model(self, tools, question, prompt, context, rung, lang="tr"):
        picked.append(llm.author_of(rung.provider))
        return None

    async def no_emit(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(ChatService, "_ask_model", ask_model)
    for config, guard in ((ladder, capped), (ladder, open_guard), (PAID, capped), (PAID, open_guard)):
        picked.clear()
        await ChatService(Nabiz(ctx), config, guard, offline=True)._run("merhaba", "", no_emit)
        chat_author = picked[0] if picked else "kural"
        assert model_part(config, guard.allows)["author_now"] == chat_author

    # Today's chat (G8) moves a spent cloud budget down to Foundry Local, so the page says so.
    capped_model = model_part(ladder, capped.allows)
    assert capped_model["author_now"] == "yerel model"
    assert model_part(PAID, capped.allows)["author_now"] == "kural"
    assert model_part(PAID, open_guard.allows)["author_now"] == llm.author_of(PAID.provider)
    today, _ = columns(payload(model=capped_model))
    assert "local_model" in today
    monkeypatch.setattr(llm, "local_on_cap", lambda env: False, raising=False)
    _, planned = columns(payload(model=model_part(ladder, capped.allows)))
    assert "local_model" in planned

    fake = types.ModuleType("nabiz.console.model_api")
    fake.active_rung = lambda config, allows: LOCAL
    monkeypatch.setitem(sys.modules, "nabiz.console.model_api", fake)
    assert model_part(PAID, open_guard.allows)["author_now"] == "yerel model"
    fake.active_rung = lambda config, allows: None
    assert model_part(PAID, open_guard.allows)["author_now"] == "kural"


async def test_step_two_says_defined_not_running() -> None:
    page, script = read("nasil.html"), read("js/how.js")
    assert "kural çalışır" not in page and "kural çalışır" not in script
    assert "kural tanımlı" in script
    ledger = await ledger_state(Ports().console)
    assert ledger["state"] == "unverified"
    assert "Karar çekirdeği bu süreçte bağlı değil." in script and "state === 'unverified'" in script


class BrokenConsole(FakeConsole):
    async def verify(self) -> dict[str, Any]:
        return {"ok": False, "entries": 5, "head": "abc123", "first_bad_id": 4}


class FailingConsole(FakeConsole):
    async def verify(self) -> dict[str, Any]:
        raise RuntimeError("disk")


async def test_ledger_states() -> None:
    ok = await ledger_state(FakeConsole())
    assert ok["state"] == "ok" and ok["entries"] == 3
    broken = await ledger_state(BrokenConsole())
    assert broken["state"] == "broken" and broken["first_bad_id"] == 4 and "head" not in broken
    unwired = await ledger_state(UnwiredConsole())
    assert unwired["state"] == "unverified" and unwired["label"] == "defter bu süreçte bağlı değil"
    failing = await ledger_state(FailingConsole())
    assert failing["state"] == "unverified" and failing["label"] == "durum doğrulanamadı"
    body = payload(ledger=broken)
    today = {c["key"]: c for c in body["capabilities"]["today"]}
    assert today["ledger"]["warn"] is True and "abc123" not in json.dumps(body)
    assert "ledger" in columns(payload(ledger=unwired))[1]


def test_organs_are_optional_and_whitelisted(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "nabiz.console.organs_api", None)
    assert how_api.organ_summary(None) is None
    body = payload(organs=organs_part(how_api.organ_summary(None)))
    assert body["organs"] is None and body["organs_label"] == "organ haritası bu süreçte bağlı değil"

    fake = types.ModuleType("nabiz.console.organs_api")
    fake.engine_of = lambda request: object()
    fake.public_summary = lambda engine, now=None: {
        "organs": [{"key": "k", "name": "Duyu", "state": "on", "state_label": "açık", "today_count": 2, "actor": "op-1"}],
        "loop": [{"key": "l", "label": "Algıla", "count": 1, "reason": "x"}],
        "ledger_ok": True,
        "actor": "op-1",
    }
    monkeypatch.setitem(sys.modules, "nabiz.console.organs_api", fake)
    organs = organs_part(how_api.organ_summary(None))
    assert set(organs) == {"organs", "loop", "ledger_ok"}
    assert set(organs["organs"][0]) == {"key", "name", "state", "state_label", "today_count"}
    assert set(organs["loop"][0]) == {"key", "label", "count"}
    text = json.dumps(payload(organs=organs), ensure_ascii=False)
    assert "op-1" not in text and '"reason": "x"' not in text


def test_capabilities_split_today_and_planned(tmp_path) -> None:
    today, planned = columns(payload())
    assert {"index", "organs"} <= planned and {"tools", "rules"} <= today
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, "Su aboneliği başvurusu resmî kaynak sayfasında açıklanır.")
    today, planned = columns(payload(store=store))
    assert "index" in today and "index" not in planned


# ---- open source ----------------------------------------------------------------------------------


def test_open_source_rows_come_from_notice_and_carry_no_gpl() -> None:
    text = (REPO_ROOT / "NOTICE.md").read_text(encoding="utf-8")
    section = text.split("## Üçüncü taraf bileşenler", 1)[1].split("\n## ", 1)[0]
    table_lines = [line for line in section.splitlines() if line.startswith("|")]
    separators = [line for line in table_lines if re.fullmatch(r"\|(\s*:?-+:?\s*\|)+", line)]
    expected = len(table_lines) - 2 * len(separators)  # each table: one header and one separator line
    rows = notice_rows(REPO_ROOT / "NOTICE.md")
    assert rows is not None and len(rows) == expected
    assert payload()["open_source"]["rows"] == rows
    for row in rows:
        assert row["component"] and row["license"]
        assert "`" not in row["license"] and "<" not in row["license"]
        assert not re.search(r"\b(A|L)?GPL", row["license"]), f"{row['component']} is GPL-family"


# ---- page -----------------------------------------------------------------------------------------


def test_forbidden_strings_are_absent() -> None:
    texts = [json.dumps(payload(), ensure_ascii=False), read("nasil.html"), read("js/how.js"), read("css/how.css")]
    forbidden = ("85/248", "16,8→11,2", "16.8", "555", "KVKK uyumlu", "CC BY 4.0", "İBB onaylı", "12 aşama", "7 hafıza",
                 "Azure'da karşılığı")  # fmt: skip
    for text in texts:
        for phrase in forbidden:
            assert phrase not in text
        assert not re.search(r"\bETA\b", text)
        assert chr(0x2014) not in text and chr(0x2013) not in text
        assert "kanca" not in text.lower()


def test_the_page_structure() -> None:
    html = read("nasil.html")
    assert html.count("<h1") == 1
    for needle in ('class="skip-link"', 'id="main"', "<header", "<main", "<footer", 'role="status"', 'aria-live="polite"',
                   "Resmî İBB hizmeti değildir", 'id="how-ai-notice"'):  # fmt: skip
        assert needle in html
    assert html.count('class="band how-band" role="note"') == 2
    assert "logo" not in html.lower()
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    assert not re.search(r" on[a-z]+=", html)
    for ref in re.findall(r'(?:href|src)="(/(?:css|js)/[^"#?]+)"', html):
        assert (STATIC / ref.lstrip("/")).is_file(), ref
    assert '<link rel="modulepreload" href="/js/how.js">' in html
    for label in re.findall(r'aria-labelledby="([\w-]+)"', html):
        assert f'id="{label}"' in html


def test_the_page_meets_the_console_static_page_rules() -> None:
    html = read("nasil.html")
    external = set(re.findall(r'<symbol id="i-([\w-]+)"', read("icons.svg")))
    assert '<use href="#i-' not in html
    for ref in re.findall(r'<use href="/icons.svg#i-([\w-]+)"', html):
        assert ref in external
    text = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    assert chr(0x2014) not in text and chr(0x2013) not in text
    assert not re.search(r"\bETA\b", text)
    for ref in re.findall(r"icon\('([\w-]+)'", read("js/how.js")):
        assert ref in external


def test_the_ai_notice_comes_from_disclosure() -> None:
    assert "import { AI_NOTICE } from './disclosure.js';" in read("js/how.js")
    assert "yapay zekâ kullanıyorum" not in read("nasil.html")


def test_the_page_fits_a_320px_phone() -> None:
    css = read("css/how.css")
    assert "minmax(min(100%" in css and "overflow-x: auto" in css
    assert not re.search(r"\b(3[3-9]\d|[4-9]\d\d|\d{4,})px", css)
    assert re.findall(r"^\.([\w-]+)", css, flags=re.M) and all(
        name.startswith("how-") for name in re.findall(r"^\.([\w-]+)", css, flags=re.M)
    )


# ---- route ----------------------------------------------------------------------------------------


def test_the_route_is_public_and_answers_json() -> None:
    app = FastAPI()
    app.include_router(how_routes)
    app.state.chat_config = llm.LlmConfig()
    app.state.guard = SpendGuard(BudgetConfig(state_path=None))
    app.state.ports = Ports()
    with TestClient(app) as client:
        response = client.get("/api/how")
        assert response.status_code == 200 and response.headers["content-type"].startswith("application/json")
        body = response.json()
        assert set(body) == TOP_KEYS
        assert body["ledger"]["state"] == "unverified" and body["index"]["built"] is False
        assert client.get("/api/how").json()["checked_at"] == body["checked_at"], "reused within the cache window"
    assert is_operator_path("/api/how") is False


def test_numbers_are_derived_not_written() -> None:
    source = (REPO_ROOT / "src" / "nabiz" / "console" / "how_api.py").read_text(encoding="utf-8")
    for literal in ("12.94", "11.24", "27.3", "126", "41.7", "1351"):
        assert literal not in source
