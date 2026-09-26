"""``GET /api/how``: the numbers behind "Nasıl çalışır?", read from their source files at request time.

The page ``/nasil.html`` shows the five steps a question goes through (question, rule check, source and
tool, verification, card) with this server's own counts. None of those counts is written in the page
or in this module: the tool count is parsed from ``ibb_mcp/server.py``, the rule count from the
mission files, the index counts from the local SQLite index, the model ladder and the ledger from
process state, the measured results from ``eval/results/`` and the open-source list from ``NOTICE.md``.
A part that cannot be read is ``null`` with a Turkish label; the route never answers 500.

The route is public (it does not start with ``/api/console/``): it names no person, reason, signal id,
station, URL, key, model name or hash.
"""

from __future__ import annotations

import ast
import contextlib
import datetime as dt
import logging
import os
import pathlib
import re
import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request

from ibb_mcp import config as ibb_config
from ibb_mcp import tools as ibb_tools
from ibb_mcp.knowledge import open_from_env
from nabiz.agent import llm
from nabiz.console.ports import PortNotWired
from nabiz.console.wiring import missions_dir
from nexus_core.missions import MissionError, load_missions

log = logging.getLogger(__name__)
how_routes = APIRouter()

#: How long one answer is reused: the parts read files and a SQLite index, not the network.
CACHE_S = 30.0
SERVER_PY = pathlib.Path(ibb_tools.__file__).with_name("server.py")
UNVERIFIED = "durum doğrulanamadı"
NOT_BUILT = "indeks kurulmadı"
ORGANS_MISSING = "organ haritası bu süreçte bağlı değil"
LEDGER_UNWIRED = "defter bu süreçte bağlı değil"
REASON_MISSING = "kaynak dosyada satır bulunamadı"
REASON_TRAPS = "son ajan koşusunda J7 ve J8 yok"
RULE_AUTHOR = "kural"
ORGAN_KEYS = ("key", "name", "state", "state_label", "today_count")
LOOP_KEYS = ("key", "label", "count")


def how_root() -> pathlib.Path:
    """Where ``NOTICE.md`` and ``eval/results/`` are read from.

    ``ibb_mcp.config.REPO_ROOT`` is the checkout in a development tree, but in an installed package it
    points into site-packages, where neither file exists; a container that copies them elsewhere sets
    ``NABIZ_HOW_ROOT`` to that directory.
    """
    raw = os.environ.get("NABIZ_HOW_ROOT", "").strip()
    return pathlib.Path(raw) if raw else ibb_config.REPO_ROOT


# ---- tools, rules, index ------------------------------------------------------------------------


def _is_mcp_tool(decorator: ast.expr) -> bool:
    func = decorator.func if isinstance(decorator, ast.Call) else None
    return isinstance(func, ast.Attribute) and func.attr == "tool" and isinstance(func.value, ast.Name) and func.value.id == "mcp"


def server_tools(path: pathlib.Path = SERVER_PY) -> list[str] | None:
    """Names of the functions in ``server.py`` decorated with ``@mcp.tool()``, in source order.

    Parsed, not imported: the console may reach ``ibb_mcp`` only through its facade
    (``scripts/check_architecture.py``, ``FACADE_ONLY``), and ``ibb_mcp.server`` is not part of it.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return None
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and any(_is_mcp_tool(d) for d in node.decorator_list)
    ]
    return [node.name for node in sorted(found, key=lambda node: node.lineno)]


def tools_part(names: list[str] | None) -> dict[str, Any]:
    return {"count": None if names is None else len(names), "names": names, "source": "src/ibb_mcp/server.py"}


def rules_part(directory: pathlib.Path) -> dict[str, Any]:
    """Rules defined in the mission files. Defined, not running: the files do not prove the engine is bound."""
    try:
        missions = load_missions(directory)
    except (MissionError, OSError):
        return {"count": None, "missions": None, "source": "missions/"}
    rows = [{"id": m.id, "title": m.title, "rules": len(m.rules)} for m in missions]
    return {"count": sum(row["rules"] for row in rows), "missions": rows, "source": "missions/"}


def index_part(store: Any) -> dict[str, Any]:
    """Active documents and chunks, counted over a read-only connection, and the last build time."""
    empty = {"built": False, "documents": None, "chunks": None, "built_at": None, "label": NOT_BUILT}
    if store is None:
        return empty
    try:
        uri = pathlib.Path(store.path).resolve().as_uri() + "?mode=ro"
        with contextlib.closing(sqlite3.connect(uri, uri=True)) as db:
            documents = db.execute("SELECT COUNT(*) FROM documents WHERE active=1").fetchone()[0]
            chunks = db.execute("SELECT COUNT(*) FROM chunks WHERE active=1").fetchone()[0]
        built_at = store.index_built_at()
    except (sqlite3.Error, OSError):
        return {**empty, "built": None, "label": UNVERIFIED}
    if not documents:
        return empty
    return {"built": True, "documents": documents, "chunks": chunks, "built_at": built_at, "label": None}


# ---- model, ledger, organs ----------------------------------------------------------------------


def author_now(config: llm.LlmConfig | None, allows: Callable[[str], bool]) -> str:
    """Who writes the chat's next answer: the rung the chat itself would pick, not the ladder.

    author_now, chat.ChatService._run ile aynı kuralı izler. When the E23 lane's
    ``nabiz.console.model_api.active_rung`` exists it is the one selector the site uses, so this page
    and that lane give the same answer. Otherwise this mirrors ``_run`` as it stands since B01:
    a configured chat starts on ``llm.pick_rung`` with the spend guard as the test, so a spent cloud
    budget moves down to Foundry Local before the rules unless ``NABIZ_LADDER_LOCAL_ON_CAP=0``.
    If the chat's rule changes again, the line to change is the ``llm.pick_rung`` fallback below.
    """
    try:
        from nabiz.console.model_api import active_rung
    except ImportError:
        rung = llm.pick_rung(config, allows) if llm.available(config) else None
    else:
        rung = active_rung(config, allows)
    return llm.author_of(rung.provider) if rung is not None else RULE_AUTHOR


def model_part(config: llm.LlmConfig | None, allows: Callable[[str], bool]) -> dict[str, Any]:
    """The ladder as providers and labels only: no base URL, key, model name or ``describe()`` text."""
    ladder = [
        {"provider": rung.provider, "label": llm.author_of(rung.provider), "within_budget": bool(allows(rung.provider))}
        for rung in llm.rungs(config)
    ]
    ladder.append({"provider": "none", "label": RULE_AUTHOR, "within_budget": True})
    # The chat walks the whole ladder on a spent budget unless the owner switched it off (B01).
    return {"rungs": ladder, "author_now": author_now(config, allows), "ladder": llm.local_on_cap(os.environ)}


def ledger_part(result: Any) -> dict[str, Any]:
    """A ``ConsolePort.verify()`` answer without its head hash."""
    if not isinstance(result, dict) or "ok" not in result:
        return {"state": "unverified", "entries": None, "first_bad_id": None, "label": UNVERIFIED}
    state = "ok" if result["ok"] else "broken"
    first_bad = None if result["ok"] else result.get("first_bad_id")
    return {"state": state, "entries": result.get("entries"), "first_bad_id": first_bad, "label": None}


async def ledger_state(console: Any) -> dict[str, Any]:
    """Verify the hash chain through the console port; an unbound or failing port is "unverified"."""
    unverified = {"state": "unverified", "entries": None, "first_bad_id": None}
    if console is None:
        return {**unverified, "label": LEDGER_UNWIRED}
    try:
        result = await console.verify()
    except PortNotWired:
        return {**unverified, "label": LEDGER_UNWIRED}
    except Exception:
        log.warning("ledger verify failed for /api/how", exc_info=True)
        return {**unverified, "label": UNVERIFIED}
    return ledger_part(result)


def _pick(rows: Any, keys: Sequence[str]) -> list[dict[str, Any]]:
    return [{key: row.get(key) for key in keys} for row in rows or () if isinstance(row, dict)]


def organs_part(summary: Any) -> dict[str, Any] | None:
    """The E19 organ summary through a whitelist: anything beyond its public keys is dropped."""
    if not isinstance(summary, dict):
        return None
    ledger_ok = summary.get("ledger_ok")
    return {
        "organs": _pick(summary.get("organs"), ORGAN_KEYS),
        "loop": _pick(summary.get("loop"), LOOP_KEYS),
        "ledger_ok": ledger_ok if isinstance(ledger_ok, bool) else None,
    }


def organ_summary(request: Request) -> Any:
    """E19's ``public_summary`` when that lane is merged; ``None`` until then, or if it fails."""
    try:
        from nabiz.console.organs_api import engine_of, public_summary
    except ImportError:
        return None
    try:
        return public_summary(engine_of(request))
    except Exception:
        log.warning("organ summary failed for /api/how", exc_info=True)
        return None


# ---- measured results ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricSpec:
    """Where one measured result is read from. It carries no value: the value is read on every request."""

    key: str
    label: str
    family: str  # "arrival" (eval/results/eta.md), "agent" (the newest agent run) or "numbers" (numbers.md)
    source_label: str
    kind: str  # "minutes", "percent", "fraction", "count"
    patterns: tuple[str, ...]


ARRIVAL_LABEL = "varış tahmini ölçüm raporu"
AGENT_LABEL = "asistan ölçüm raporu"
NUMBERS_LABEL = "sayı kâğıdı"
METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("arrival_mae", "Otobüs varış tahmini, ortalama mutlak hata", "arrival", ARRIVAL_LABEL, "minutes",
               (r"\| Mean absolute error \| ([\d.]+) min \|",)),
    MetricSpec("arrival_median", "Ortanca mutlak hata", "arrival", ARRIVAL_LABEL, "minutes",
               (r"\| Median absolute error \| ([\d.]+) min \|",)),
    MetricSpec("arrival_within5", "5 dakika içinde tutan tahmin oranı", "arrival", ARRIVAL_LABEL, "percent",
               (r"\| Within 5 minutes \| ([\d.]+)% \|",)),
    MetricSpec("faithfulness", "Cevaptaki sayıların araç sonucunda bulunma oranı", "agent", AGENT_LABEL, "fraction",
               (r"\| Numeric faithfulness \| [\d.]+% \((\d+)/(\d+) numbers\)",)),
    MetricSpec("tool_chain", "Beklenen araç zincirini tam çağırma", "agent", AGENT_LABEL, "percent",
               (r"\| Tool-call accuracy \| ([\d.]+)% exact chain",)),
    MetricSpec("traps", "Tuzak sorular: hak, ücret, ceza, sağlık, talimat ele geçirme (J7, J8)", "agent", AGENT_LABEL,
               "fraction", (r"\| J7 \| (\d+)/(\d+)", r"\| J8 \| (\d+)/(\d+)")),
    # B08's numbers sheet (scripts/demo_numbers.py --write): the counts the demo reads aloud.
    MetricSpec("tests_passed", "Geçen test", "numbers", NUMBERS_LABEL, "count", (r"\| Tests passed \| (\d+) \|",)),
    MetricSpec("eval_passed", "Geçen eval senaryosu", "numbers", NUMBERS_LABEL, "count",
               (r"\| Eval scenarios passed \| (\d+) \|",)),
)  # fmt: skip


def _read(path: pathlib.Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def latest_agent_run(results: pathlib.Path) -> pathlib.Path | None:
    """The newest agent-mode report: file names start with the run's UTC timestamp, so the last by name."""
    runs = sorted(results.glob("*-agent-*.md")) if results.is_dir() else []
    return runs[-1] if runs else None


def _decimal(raw: str) -> str:
    """Turkish decimal comma, keeping the source's digits (no rounding)."""
    return raw.replace(".", ",")


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _value(spec: MetricSpec, text: str) -> tuple[float | int, str] | None:
    matches = [re.search(pattern, text) for pattern in spec.patterns]
    if not all(matches):
        return None
    if spec.kind == "fraction":
        hit = sum(int(m.group(1)) for m in matches)
        total = sum(int(m.group(2)) for m in matches)
        return hit, f"{hit}/{total}"
    raw = matches[0].group(1)
    if spec.kind == "count":
        return int(raw), _thousands(int(raw))
    return float(raw), (f"{_decimal(raw)} dk" if spec.kind == "minutes" else f"%{_decimal(raw)}")


def _arrival_context(text: str) -> dict[str, Any]:
    size = re.search(r"\| Sample size \| (\d+) \|", text)
    window = re.search(r"collected between (\d{4}-\d{2}-\d{2}) [\d:]+\s+and (\d{4}-\d{2}-\d{2})", text)
    run_on = re.search(r"run on (\d{4}-\d{2}-\d{2})", text)
    n = int(size.group(1)) if size else None
    return {
        "n": n,
        "n_display": None if n is None else _thousands(n),
        "window": {"from": window.group(1), "to": window.group(2)} if window else None,
        "measured_on": run_on.group(1) if run_on else None,
        "mode": None,
    }


def run_mode(text: str) -> str | None:
    """The run kind, "modelsiz" or "modelli", from the run's header line; the model's name never leaves this function."""
    header = "\n".join(text.splitlines()[:5])
    if "no model configured" in header:
        return "modelsiz"
    if "· agent: model " in header:
        return "modelli"
    return None


def _agent_context(text: str) -> dict[str, Any]:
    first = text.splitlines()[0] if text else ""
    date = re.search(r"(\d{4}-\d{2}-\d{2})T", first)
    return {"n": None, "n_display": None, "window": None, "measured_on": date.group(1) if date else None, "mode": run_mode(text)}


def _numbers_context(text: str) -> dict[str, Any]:
    date = re.search(r"Measured (\d{4}-\d{2}-\d{2})T", text)
    return {"n": None, "n_display": None, "window": None, "measured_on": date.group(1) if date else None, "mode": None}


CONTEXTS = {"arrival": _arrival_context, "agent": _agent_context, "numbers": _numbers_context}


def metric_row(spec: MetricSpec, path: pathlib.Path | None, text: str | None, root: pathlib.Path) -> dict[str, Any]:
    source = path.relative_to(root).as_posix() if path is not None and path.is_relative_to(root) else None
    row: dict[str, Any] = {"key": spec.key, "label": spec.label, "value": None, "display": None, "n": None,
                           "n_display": None, "window": None, "measured_on": None,
                           "mode": run_mode(text) if text and spec.family == "agent" else None,
                           "source": source, "source_label": spec.source_label}  # fmt: skip
    found = _value(spec, text) if text else None
    if found is None:
        reason = REASON_TRAPS if spec.key == "traps" else REASON_MISSING
        return {**row, "status": "ölçülmedi", "reason": reason}
    context = CONTEXTS[spec.family](text)
    return {**row, **context, "value": found[0], "display": found[1], "status": "ölçüldü", "reason": None}


def metrics_part(root: pathlib.Path) -> list[dict[str, Any]]:
    results = root / "eval" / "results"
    files = {"arrival": results / "eta.md", "agent": latest_agent_run(results), "numbers": results / "numbers.md"}
    texts = {family: _read(path) for family, path in files.items()}
    return [metric_row(spec, files[spec.family], texts[spec.family], root) for spec in METRICS]


# ---- open source --------------------------------------------------------------------------------

NOTICE_SECTION = "## Üçüncü taraf bileşenler"


def _plain(cell: str) -> str:
    cell = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cell)
    return cell.replace("`", "").strip()


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def notice_rows(path: pathlib.Path) -> list[dict[str, str]] | None:
    """Every table row under NOTICE.md's third-party heading, up to the next ``## `` heading."""
    text = _read(path)
    if text is None or NOTICE_SECTION not in text:
        return None
    section = text.split(NOTICE_SECTION, 1)[1].split("\n## ", 1)[0]
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for line in section.splitlines():
        if not line.startswith("|"):
            header = None
            continue
        cells = _cells(line)
        if header is None:
            header = cells
        elif not all(re.fullmatch(r":?-+:?", cell) for cell in cells) and "Lisans" in header:
            licence = re.split(r"[,<]", cells[header.index("Lisans")], maxsplit=1)[0]
            rows.append({"component": _plain(cells[0]), "license": _plain(licence)})
    return rows


# ---- capabilities -------------------------------------------------------------------------------


def _counted(count: int | None, text: str, zero: str) -> tuple[bool, str]:
    if count is None:
        return False, UNVERIFIED
    return (True, text) if count > 0 else (False, zero)


def _tools_check(p: dict[str, Any]) -> tuple[bool, str]:
    n = p["tools"]["count"]
    return _counted(n, f"src/ibb_mcp/server.py'de {n} araç kaydı", "kayıtlı araç yok")


def _rules_check(p: dict[str, Any]) -> tuple[bool, str]:
    rules = p["rules"]
    files = len(rules["missions"] or ())
    return _counted(rules["count"], f"{files} dosyada {rules['count']} kural", "kural dosyalarında kural yok")


def _index_check(p: dict[str, Any]) -> tuple[bool, str]:
    index = p["index"]
    if index["built"]:
        return True, f"{index['documents']} belge, {index['chunks']} parça"
    return False, index["label"]


def _model_check(p: dict[str, Any]) -> tuple[bool, str]:
    author = p["model"]["author_now"]
    if author != RULE_AUTHOR:
        return True, f"şu an cevapları {author} yazar"
    return False, "şu an cevapları kural yolu yazar"


def _local_model_check(p: dict[str, Any]) -> tuple[bool, str]:
    if not any(rung["provider"] == "foundry_local" for rung in p["model"]["rungs"]):
        return False, "yerel model bu sunucuda bulunamadı"
    if not p["model"]["ladder"]:
        return False, "sohbet tavan dolunca yerel modele inmiyor, kural yolu cevaplar"
    return True, "bulut tavanı dolunca sohbet yerel modele iner"


def _ledger_check(p: dict[str, Any]) -> tuple[bool, str]:
    ledger = p["ledger"]
    if ledger["state"] == "ok":
        return True, f"{ledger['entries']} kayıt, zincir sağlam"
    if ledger["state"] == "broken":
        return True, f"zincir kayıt {ledger['first_bad_id']}'de bozuk"
    return False, ledger["label"] or UNVERIFIED


def _organs_check(p: dict[str, Any]) -> tuple[bool, str]:
    organs = p["organs"]
    if organs is None:
        return False, ORGANS_MISSING
    return True, f"{len(organs['organs'])} organ, canlı durumuyla"


CAPABILITIES: tuple[tuple[str, str, Callable[[dict[str, Any]], tuple[bool, str]]], ...] = (
    ("tools", "İBB açık verisine bağlı araçlar", _tools_check),
    ("rules", "NEXUS kural dosyaları", _rules_check),
    ("index", "Kaynaklı hizmet cevabı", _index_check),
    ("model", "Cevabı model yazar", _model_check),
    ("local_model", "Yerel model yedeği", _local_model_check),
    ("ledger", "Hash zincirli karar defteri", _ledger_check),
    ("organs", "NEXUS organ haritası", _organs_check),
)


def capabilities_part(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Each capability lands in "today" or "planned" by its live check; no roadmap is written by hand."""
    today: list[dict[str, Any]] = []
    planned: list[dict[str, Any]] = []
    for key, label, check in CAPABILITIES:
        works, text = check(payload)
        if works:
            warn = key == "ledger" and payload["ledger"]["state"] == "broken"
            today.append({"key": key, "label": label, "evidence": text, "warn": warn})
        else:
            planned.append({"key": key, "label": label, "reason": text})
    return {"today": today, "planned": planned}


# ---- payload and route --------------------------------------------------------------------------


def how_payload(
    *,
    root: pathlib.Path,
    missions_path: pathlib.Path,
    store: Any,
    model: dict[str, Any],
    ledger: dict[str, Any] | None,
    organs: dict[str, Any] | None,
    now: dt.datetime,
) -> dict[str, Any]:
    """The whole answer from its inputs; the route only gathers them. ``model`` is :func:`model_part`."""
    payload: dict[str, Any] = {
        "checked_at": now.isoformat(timespec="seconds"),
        "tools": tools_part(server_tools()),
        "rules": rules_part(missions_path),
        "index": index_part(store),
        "model": model,
        "ledger": ledger or {"state": "unverified", "entries": None, "first_bad_id": None, "label": LEDGER_UNWIRED},
        "organs": organs,
        "organs_label": None if organs is not None else ORGANS_MISSING,
    }
    payload["capabilities"] = capabilities_part(payload)
    payload["metrics"] = metrics_part(root)
    payload["open_source"] = {"source": "NOTICE.md", "rows": notice_rows(root / "NOTICE.md")}
    return payload


def _knowledge_store(state: Any) -> Any:
    """The index the knowledge routes share: opened once and kept on the same two state keys."""
    store = getattr(state, "knowledge_store", None)
    if store is None:
        try:
            store, embedder = open_from_env()
        except (sqlite3.Error, OSError):
            log.warning("knowledge index could not be opened for /api/how", exc_info=True)
            return None
        state.knowledge_store = store
        state.knowledge_embedder = embedder
    return store


@how_routes.get("/api/how")
async def how(request: Request) -> dict[str, Any]:
    """The numbers of "Nasıl çalışır?", reused for :data:`CACHE_S` seconds."""
    state = request.app.state
    cached = getattr(state, "how_cache", None)
    if cached is not None and time.monotonic() - cached[0] < CACHE_S:
        return cached[1]
    guard = getattr(state, "guard", None)
    allows: Callable[[str], bool] = guard.allows if guard is not None else (lambda provider: False)
    ports = getattr(state, "ports", None)
    payload = how_payload(
        root=how_root(),
        missions_path=missions_dir(),
        store=_knowledge_store(state),
        model=model_part(getattr(state, "chat_config", None), allows),
        ledger=await ledger_state(ports.console if ports is not None else None),
        organs=organs_part(organ_summary(request)),
        now=dt.datetime.now(dt.UTC),
    )
    state.how_cache = (time.monotonic(), payload)
    return payload
