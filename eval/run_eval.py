#!/usr/bin/env python3
"""İstanbul Nabız evaluation harness — the source of every number in the README Results table.

Two modes, separated because they measure different things:

``--mode deterministic`` (default)
    Drives :class:`ibb_mcp.tools.Nabiz` with the tool calls each scenario records, so it
    measures the *data layer* — does the tool answer, does it carry the fields the journey
    needs, is there provenance and how old is the reading — with no LLM in the loop. It
    cannot measure tool *selection* or the wording of an answer; those rows print
    ``n/a`` with the reason instead of a flattering 100%.

``--mode agent``
    Asks :class:`nabiz.agent.NabizAgent` each scenario question and adds what only exists
    once something has written an answer: task success, tool-call accuracy, numeric
    faithfulness, forbidden phrases, refusal wording, tokens and cost. The agent is handed
    *this* harness's tool layer, so ``--offline`` and the upstream budget still apply. With
    no model configured it measures the agent's no-model keyword-routing path and labels
    every row as such; ``--require-llm`` turns that into a skip instead. A missing agent
    module is always a skip with a stated reason, never an invented number.

No metric is ever defaulted. One that could not be computed is printed as ``n/a (reason)``,
because a plausible placeholder in a results table is worse than an admission.

    python eval/run_eval.py --mode deterministic --offline
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import importlib
import json
import math
import pathlib
import re
import statistics
import subprocess
import sys
import time
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:  # run as `python eval/run_eval.py`, uninstalled
    sys.path.insert(0, str(REPO / "src"))

from ibb_mcp.config import Settings  # noqa: E402
from ibb_mcp.http import RateLimitExceeded, UpstreamUnavailable  # noqa: E402
from ibb_mcp.models import ToolResult  # noqa: E402
from ibb_mcp.sources.base import SourceContext  # noqa: E402
from ibb_mcp.tools import Nabiz  # noqa: E402

JOURNEYS = REPO / "eval" / "journeys.jsonl"
RESULTS = REPO / "eval" / "results"
OK_STATUS = {"ok", "refused_as_expected"}

#: Any of these set means "an LLM is reachable" (DECISIONS #5: swappable by environment).
LLM_ENV_VARS = ("LLM_BASE_URL", "LLM_MODEL", "OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "FOUNDRY_LOCAL_ENDPOINT")

#: A number plate must never cross the parsing boundary (NOTICE.md, DECISIONS #7). Both the
#: key and the İETT value shape ("34 HO 1000") are searched in every serialised result.
PLATE_KEY_RE = re.compile(r'"(plaka|plate)"\s*:', re.IGNORECASE)
PLATE_VALUE_RE = re.compile(r"\b\d{2} [A-Z]{1,3} \d{2,5}\b")

#: "resmi"/"official" are honest inside a disclaimer ("resmi İETT bilgisi değildir"), so a
#: hit followed closely by one of these markers is not counted as overclaiming.
NEGATIONS = ("değil", "degil", "is not", "are not", "isn't", "not an", "not the", "never")
_NO_VALUE = object()


# ---------------------------------------------------------------------------- scenarios
def parse_spec(spec: str) -> tuple[bool, list[str], Any]:
    """Split ``?tool.data.list[].field == 3`` into (optional, segments, expected value)."""
    optional = spec.startswith("?")
    body = spec[1:] if optional else spec
    expected: Any = _NO_VALUE
    if "==" in body:
        body, _, literal = body.partition("==")
        expected = json.loads(literal.strip())
    segments = [segment for segment in body.strip().split(".") if segment]
    if not segments:
        raise ValueError(f"empty field spec: {spec!r}")
    return optional, segments, expected


def load_scenarios(path: pathlib.Path) -> list[dict[str, Any]]:
    """Read journeys.jsonl, refusing anything the runner could not execute honestly."""
    scenarios: list[dict[str, Any]] = []
    seen: set[str] = set()
    tools = {name for name in dir(Nabiz) if not name.startswith("_")}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        missing = [k for k in ("id", "lang", "journey", "question", "expected_tools", "calls", "expected_fields") if k not in row]
        if missing:
            raise ValueError(f"{path.name}:{number} is missing {missing}")
        if row["id"] in seen:
            raise ValueError(f"{path.name}:{number} duplicate id {row['id']}")
        seen.add(row["id"])
        called = [call["tool"] for call in row["calls"]]
        if unknown := sorted(set(called) - tools):
            raise ValueError(f"{path.name}:{number} calls tools Nabiz does not have: {unknown}")
        if called != list(row["expected_tools"]):
            raise ValueError(f"{path.name}:{number} expected_tools {row['expected_tools']} != calls {called}")
        for spec in row["expected_fields"]:
            parse_spec(spec)  # raises on a malformed path
        scenarios.append(row)
    return scenarios


def _probe(node: Any, segments: list[str], expected: Any) -> str:
    """Walk a JSON tree. Returns 'pass', 'fail', or 'empty' for a list with no elements."""
    if not segments:
        if node is None:
            return "fail"
        if expected is not _NO_VALUE:
            return "pass" if node == expected else "fail"
        return "pass"
    head, rest = segments[0], segments[1:]
    mode: str | None = None
    if head.endswith("[]"):
        head, mode = head[:-2], "all"
    elif head.endswith("[?]"):
        head, mode = head[:-3], "any"
    if not isinstance(node, dict) or head not in node:
        return "fail"
    child = node[head]
    if mode is None:
        return _probe(child, rest, expected)
    if not isinstance(child, list):
        return "fail"
    if not child:
        return "empty"
    verdicts = [_probe(item, rest, expected) for item in child]
    if mode == "all":
        return "pass" if all(v == "pass" for v in verdicts) else "fail"
    return "pass" if any(v == "pass" for v in verdicts) else "fail"


def check_field(envelopes: dict[str, Any], spec: str) -> dict[str, str]:
    """Evaluate one ``expected_fields`` entry against a scenario's tool envelopes.

    ``?`` marks a field that is legitimately absent sometimes — a bus list emptied by the
    ETA engine's 600 s freshness window, an hour where the station published no PM10.
    Those are recorded as present or n/a and never counted as a failure, because scoring
    the weather as a defect would turn the headline number into noise.
    """
    optional, segments, expected = parse_spec(spec)
    tool = segments[0]
    verdict = _probe(envelopes[tool], segments[1:], expected) if tool in envelopes else "fail"
    if verdict == "pass":
        return {"spec": spec, "status": "pass", "detail": "present"}
    if optional:
        return {"spec": spec, "status": "na", "detail": "absent (optional)"}
    return {"spec": spec, "status": "fail", "detail": "empty list" if verdict == "empty" else "missing or null"}


# ------------------------------------------------------------------- answer-level checks
#: Digits that make no claim. Masked with spaces before the answer is read, so the offsets
#: of everything else survive: a timestamp, a date, a clock and the licence line all carry
#: digits that no tool needs to support.
CLAIMLESS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?"),
    re.compile(r"\d{1,2}\.\d{1,2}\.\d{2,4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?"),
    re.compile(r"\d{1,2}:\d{2}(?::\d{2})?"),
    re.compile(r"CC BY \d(?:\.\d)?", re.IGNORECASE),
)
_TOKEN_RE = re.compile(r"\d[\d.,]*")


def stated_tokens(text: str) -> list[str]:
    """The digit tokens in a text that are *claims*, as written.

    A digit glued to a letter is a name, not a quantity: ``PM10``, ``SO2``, ``M4``, ``500T``
    and ``4.Levent`` are the vocabulary of this domain, and asking a tool to support the "10"
    in PM10 would fill the report with violations that mean nothing. Only free-standing
    numbers are checked.
    """
    masked = text
    for pattern in CLAIMLESS:
        masked = pattern.sub(lambda m: " " * len(m.group(0)), masked)
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(masked):
        token = match.group(0).rstrip(".,")
        if not token:
            continue
        start, end = match.start(), match.start() + len(token)
        before = masked[start - 1] if start else ""
        after = masked[end] if end < len(masked) else ""
        tail = masked[end : end + 2]
        # "4.Levent" and "2.Etap" are written without a space, so the dot belongs to the
        # name, not to the number. Restricted to a bare integer so that a Turkish decimal
        # that happens to end a sentence ("%12,5.Bunlar") stays a claim.
        dotted_name = token.isdigit() and tail[:1] == "." and tail[1:2].isalpha()
        if before.isalpha() or after.isalpha() or dotted_name:
            continue  # PM10, 500T, 4.Levent — an identifier, not a measurement
        tokens.append(token)
    return tokens


def read_number(token: str, lang: str) -> float | None:
    """One reading of a written number, as a reader of that language would take it."""
    normalised = token.replace(".", "").replace(",", ".") if lang == "tr" else token.replace(",", "")
    try:
        return float(normalised)
    except ValueError:
        return None


def parse_numbers(text: str, lang: str) -> list[float]:
    """Numbers as a reader of that language would read them.

    ``1.250`` is one thousand two hundred fifty in Turkish and one-and-a-quarter in
    English; the same string cannot be normalised without knowing the language, so the
    scenario's ``lang`` decides which reading is reported.
    """
    return [value for token in stated_tokens(text) if (value := read_number(token, lang)) is not None]


def loose_numbers(text: str) -> set[float]:
    """Every value a string could be read as. Used on the *evidence* side only.

    Harvesting is deliberately greedier than reading: a stop named "15 Temmuz", a line code
    "500T" and an ISO timestamp all legitimately support a number the answer quotes, so the
    identifier and timestamp filters that apply to a claim must not apply here.
    """
    values: set[float] = set()
    for raw in _TOKEN_RE.findall(text):
        token = raw.rstrip(".,")
        for lang in ("tr", "en"):
            if (value := read_number(token, lang)) is not None:
                values.add(value)
    return values


def collect_numbers(node: Any) -> set[float]:
    """Every number a tool result contains, including those embedded in strings."""
    found: set[float] = set()
    if isinstance(node, bool):
        return found
    if isinstance(node, (int, float)):
        found.add(float(node))
    elif isinstance(node, str):
        found |= loose_numbers(node)
    elif isinstance(node, dict):
        for value in node.values():
            found |= collect_numbers(value)
    elif isinstance(node, list):
        for value in node:
            found |= collect_numbers(value)
    return found


def faithfulness(answer: str, lang: str, question: str, supported: set[float]) -> dict[str, Any]:
    """Share of the numbers in an answer that came from a tool result or from the question.

    A written token is given the benefit of every reading it could carry. ``41,0422`` is a
    coordinate to a Turkish reader and four hundred ten thousand to an English one, and the
    no-model path answers in Turkish whatever the question's language — so a token counts as
    unsupported only when *neither* reading appears in the evidence. The alternative,
    trusting the scenario's language, reports the fallback's Turkish coordinates as invented.
    """
    allowed = supported | loose_numbers(question)
    stated: list[float] = []
    unsupported: list[str] = []
    for token in stated_tokens(answer):
        readings = [v for lang_ in (lang, "tr" if lang == "en" else "en") if (v := read_number(token, lang_)) is not None]
        if not readings:
            continue
        stated.append(readings[0])
        if not any(math.isclose(v, ok, rel_tol=0.005, abs_tol=0.05) for v in readings for ok in allowed):
            unsupported.append(token)
    return {
        "numbers_stated": len(stated),
        "numbers_unsupported": len(unsupported),
        "unsupported": sorted(set(unsupported))[:10],
        "rate": None if not stated else round(1 - len(unsupported) / len(stated), 4),
    }


def forbidden_hits(text: str, phrases: list[str]) -> list[str]:
    """Overclaiming phrases, ignoring the ones a disclaimer negates right afterwards."""
    lowered = text.casefold()
    hits: list[str] = []
    for phrase in phrases:
        needle = phrase.casefold()
        start = lowered.find(needle)
        while start != -1:
            tail = lowered[start + len(needle) : start + len(needle) + 45]
            if not any(marker in tail for marker in NEGATIONS):
                hits.append(phrase)
                break
            start = lowered.find(needle, start + len(needle))
    return hits


def privacy_hits(payload: str) -> list[str]:
    """Number plates must never appear in a response (NOTICE.md, 'Kişisel veri')."""
    hits = [f"key:{m.group(1)}" for m in PLATE_KEY_RE.finditer(payload)]
    return (hits + [f"value:{m.group(0)}" for m in PLATE_VALUE_RE.finditer(payload)])[:5]


# ------------------------------------------------------------------------ upstream guard
class UpstreamBudget:
    """Counts real requests to İBB and stops the run before it becomes impolite.

    The gateway 503s after roughly fifteen rapid calls and İETT documents 100 requests an
    hour, so a live eval fanning out over 24 scenarios would be a small denial of service
    against a public endpoint. Past the ceiling the harness records a skip instead of
    making the request.
    """

    def __init__(self, ceiling: int) -> None:
        self.ceiling = ceiling
        self.used = 0

    def install(self, client: Any) -> None:
        original = client.request

        async def counted(*args: Any, **kwargs: Any) -> Any:
            if self.exhausted:
                raise UpstreamUnavailable(
                    f"eval upstream budget of {self.ceiling} requests is spent; refusing to call İBB again",
                    source=str(kwargs.get("source", "eval")),
                )
            self.used += 1
            return await original(*args, **kwargs)

        client.request = counted  # an instance attribute shadows the bound method

    @property
    def exhausted(self) -> bool:
        return bool(self.ceiling) and self.used >= self.ceiling


def classify(exc: BaseException) -> str:
    """The error taxonomy: one bucket per thing that can actually go wrong."""
    if isinstance(exc, RateLimitExceeded):
        return "rate_limited"
    if isinstance(exc, UpstreamUnavailable):
        return "upstream_budget" if "eval upstream budget" in str(exc) else "upstream_unavailable"
    if isinstance(exc, ValueError):
        return "bad_request"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return f"internal:{type(exc).__name__}"


# ---------------------------------------------------------------------------- execution
async def run_call(nabiz: Nabiz, call: dict[str, Any]) -> dict[str, Any]:
    """Execute one tool call, recording what happened and how long it took."""
    tool, args = call["tool"], dict(call.get("args", {}))
    expect = call.get("expect", "ok")
    record: dict[str, Any] = {"tool": tool, "args": args, "expect": expect}
    started = time.perf_counter()
    try:
        result: ToolResult = await getattr(nabiz, tool)(**args)
    except Exception as exc:  # noqa: BLE001 - every failure is data for the taxonomy
        record["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        kind = classify(exc)
        wanted = call.get("error_contains")
        refused_right = kind == "bad_request" and (not wanted or wanted in str(exc))
        record["error_kind"] = kind
        record["error_message"] = str(exc)[:400]
        record["status"] = (
            ("refused_as_expected" if refused_right else "wrong_refusal") if expect == "refusal" else "error"
        )
        return record

    record["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    payload = result.model_dump(mode="json")
    record["envelope"] = payload
    record["provenance"] = payload["provenance"]
    record["age_seconds"] = round(result.provenance.age_seconds, 1)
    record["has_reported_at"] = result.provenance.reported_at is not None
    record["note"] = result.note
    record["privacy_hits"] = privacy_hits(json.dumps(payload, ensure_ascii=False, default=str))
    record["status"] = "missing_refusal" if expect == "refusal" else "ok"
    return record


def skipped_record(scenario: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        **{k: scenario[k] for k in ("id", "lang", "journey", "question", "expected_tools")},
        "calls": [], "fields": [], "passed": None, "reason": reason, "latency_ms": 0.0,
    }


async def run_scenario(nabiz: Nabiz, scenario: dict[str, Any], budget: UpstreamBudget | None = None) -> dict[str, Any]:
    """Run one journey scenario end to end and score the fields it promised.

    A scenario whose *second* call runs into the upstream ceiling is abandoned as a skip,
    not scored as a failure. The ceiling is our own politeness, not İBB failing to answer,
    and counting it would let the cap chosen on the command line move the headline number.
    """
    calls: list[dict[str, Any]] = []
    envelopes: dict[str, Any] = {}
    for call in scenario["calls"]:
        record = await run_call(nabiz, call)
        if record.get("error_kind") == "upstream_budget":
            ceiling = budget.ceiling if budget is not None else "the configured"
            return skipped_record(scenario, f"skipped: upstream budget of {ceiling} requests spent mid-scenario")
        if "envelope" in record:
            envelopes[record["tool"]] = record.pop("envelope")
        calls.append(record)

    fields = [check_field(envelopes, spec) for spec in scenario["expected_fields"]]
    bad_calls = [c for c in calls if c["status"] not in OK_STATUS]
    bad_fields = [f["spec"] for f in fields if f["status"] == "fail"]
    reason = ""
    if bad_calls:
        reason = "; ".join(f"{c['tool']}: {c.get('error_kind', c['status'])}" for c in bad_calls)
    elif bad_fields:
        reason = "missing fields: " + ", ".join(bad_fields)
    return {
        **{k: scenario[k] for k in ("id", "lang", "journey", "question", "expected_tools")},
        "calls": calls,
        "fields": fields,
        "passed": not bad_calls and not bad_fields,
        "reason": reason,
        "latency_ms": round(sum(c["latency_ms"] for c in calls), 1),
        "numbers_available": sorted(collect_numbers(envelopes))[:200],
    }


async def run_deterministic(scenarios: list[dict[str, Any]], settings: Settings, budget: UpstreamBudget) -> list[dict[str, Any]]:
    """Drive the tool layer directly, sharing one cache exactly as the server does."""
    ctx = SourceContext.create(settings=settings)
    budget.install(ctx.client)
    nabiz = Nabiz(ctx)
    records: list[dict[str, Any]] = []
    try:
        for scenario in scenarios:
            if budget.exhausted:
                records.append(skipped_record(scenario, f"skipped: upstream budget of {budget.ceiling} requests spent"))
                continue
            records.append(await run_scenario(nabiz, scenario, budget))
    finally:
        await nabiz.aclose()
    return records


# --------------------------------------------------------------------------- agent mode
def _jsonable(payload: Any) -> Any:
    """Round-trip a tool payload through JSON, exactly as the agent hands it to the model."""
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


def _age_seconds(provenance: dict[str, Any]) -> float | None:
    """Age of the reading itself, from the timestamps the agent's payload carries."""
    stamp = provenance.get("reported_at") or provenance.get("observed_at")
    if not stamp:
        return None
    try:
        moment = dt.datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return max(0.0, (dt.datetime.now(dt.UTC) - moment).total_seconds())


def classify_message(message: str) -> str:
    """The agent turns exceptions into Turkish strings, so the taxonomy reads them back.

    ``NabizAgent._call_tool`` deliberately never lets a tool raise into the turn — a failure
    is data for the model. That means the eval sees prose, not exception types, and the
    prefixes below are the agent's own wording (``agent.py``). Keep them in step.
    """
    if "İstek bütçesi doldu" in message:
        return "rate_limited"
    if "eval upstream budget" in message:
        return "upstream_budget"
    if "İBB servisi şu anda yanıt vermiyor" in message:
        return "upstream_unavailable"
    if message.startswith("Bilinmeyen araç"):
        return "unknown_tool"
    if message.startswith("Beklenmeyen hata"):
        return "internal:agent"
    return "bad_request"


async def build_agent(
    settings: Settings, budget: UpstreamBudget, *, require_llm: bool
) -> tuple[Any, Any, str | None, dict[str, Any]]:
    """Return (agent, context, skip reason, provenance of the run's model choice).

    The agent is given *this harness's* :class:`~ibb_mcp.tools.Nabiz`, built on the eval's
    settings and with the upstream budget installed on its client. Letting ``NabizAgent()``
    build its own would ignore ``--offline`` and, worse, make uncapped live requests to
    İBB — so a constructor this harness cannot hand a client to is a skip, not a fallback.
    """
    try:
        module = importlib.import_module("nabiz.agent")
    except Exception as exc:  # noqa: BLE001 - a missing agent is a skip, not a crash
        return None, None, f"nabiz.agent is not importable ({type(exc).__name__}: {exc})", {}
    factory = getattr(module, "NabizAgent", None)
    if factory is None:
        return None, None, "nabiz.agent exposes no NabizAgent", {}
    try:
        llm = importlib.import_module("nabiz.agent.llm")
        config = llm.LlmConfig.from_env()
        has_llm = bool(llm.available(config))
    except Exception as exc:  # noqa: BLE001
        return None, None, f"nabiz.agent.llm could not be read ({type(exc).__name__}: {exc})", {}
    if not has_llm and require_llm:
        return None, None, (
            f"no LLM configured; set one of {', '.join(LLM_ENV_VARS)}. Drop --require-llm to measure the "
            "agent's no-model path instead — it answers from keyword routing and is scored as such"
        ), {}

    ctx = SourceContext.create(settings=settings)
    budget.install(ctx.client)
    try:
        agent = factory(Nabiz(ctx), config=config)
    except TypeError as exc:
        # ``build_agent`` runs inside the event loop ``run_agent`` was started in, so the
        # client has to be closed with ``await`` — ``asyncio.run`` here would raise
        # "cannot be called from a running event loop" and turn this skip into a crash.
        await ctx.aclose()
        return None, None, (
            f"NabizAgent(nabiz, config=...) is not the constructor this harness knows ({exc}); "
            "refusing to let the agent build its own client, which would ignore --offline and the upstream budget"
        ), {}
    provenance = {
        "llm_configured": has_llm,
        "provider": getattr(config, "provider", None),
        "model": getattr(config, "model", None),
        "base_url": getattr(config, "base_url", None),
    }
    return agent, ctx, None, provenance


def _agent_call_record(call: Any, refusals: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Normalise one ``ToolCallRecord`` into the same shape the deterministic runner emits."""
    expected = refusals.get(call.name)
    record: dict[str, Any] = {
        "tool": call.name,
        "args": call.arguments,
        "expect": "refusal" if expected else "ok",
        "latency_ms": float(call.duration_ms or 0.0),
    }
    if call.ok and call.payload is not None:
        payload = _jsonable(call.payload)
        provenance = payload.get("provenance") or {}
        record["provenance"] = provenance
        record["has_reported_at"] = bool(provenance.get("reported_at"))
        record["age_seconds"] = _age_seconds(provenance)
        record["note"] = payload.get("note")
        record["privacy_hits"] = privacy_hits(json.dumps(payload, ensure_ascii=False, default=str))
        record["status"] = "missing_refusal" if expected else "ok"
        return record, payload
    message = call.error or ""
    kind = classify_message(message)
    wanted = (expected or {}).get("error_contains")
    record["error_kind"] = kind
    record["error_message"] = message[:400]
    record["status"] = (
        ("refused_as_expected" if kind == "bad_request" and (not wanted or wanted in message) else "wrong_refusal")
        if expected
        else "error"
    )
    return record, None


async def run_agent_scenario(agent: Any, scenario: dict[str, Any]) -> dict[str, Any]:
    """Ask one question and score the prose as well as the data behind it."""
    refusals = {c["tool"]: c for c in scenario["calls"] if c.get("expect") == "refusal"}
    record: dict[str, Any] = {k: scenario[k] for k in ("id", "lang", "journey", "question", "expected_tools")}
    started = time.perf_counter()
    try:
        answer = await agent.ask(scenario["question"], lang=scenario["lang"])
    except Exception as exc:  # noqa: BLE001 - an agent that raises is a failed scenario, not a dead run
        return record | {
            "calls": [], "fields": [], "passed": False, "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "reason": f"agent raised {type(exc).__name__}: {exc}", "error_kind": classify(exc),
        }
    record["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)

    text = (getattr(answer, "text", "") or "").strip()
    calls: list[dict[str, Any]] = []
    envelopes: dict[str, Any] = {}
    for call in getattr(answer, "tool_calls", []) or []:
        normalised, payload = _agent_call_record(call, refusals)
        calls.append(normalised)
        if payload is not None:
            envelopes.setdefault(call.name, payload)

    if any(c.get("error_kind") == "upstream_budget" for c in calls):
        # Same rule as the deterministic runner: the ceiling is our politeness, not a defect
        # in the answer, so the scenario leaves every denominator instead of failing.
        return skipped_record(scenario, "skipped: upstream budget spent mid-scenario")

    called = [c["tool"] for c in calls]
    fields = [check_field(envelopes, spec) for spec in scenario["expected_fields"]]
    bad_fields = [f["spec"] for f in fields if f["status"] == "fail"]
    missing_tools = [t for t in scenario["expected_tools"] if t not in called]
    markers = [m for m in scenario.get("answer_must_contain_any", []) if m]
    marker_ok = None if not markers else any(m.casefold() in text.casefold() for m in markers)
    forbidden = forbidden_hits(text, scenario.get("forbidden_phrases", []))
    faith = faithfulness(text, scenario["lang"], scenario["question"], collect_numbers(envelopes))
    verdict = getattr(answer, "faithfulness", None)

    passed = bool(text) and not missing_tools and not bad_fields
    reasons = []
    if not text:
        reasons.append("empty answer")
    if missing_tools:
        reasons.append("tools not called: " + ", ".join(missing_tools))
    if bad_fields:
        reasons.append("missing fields: " + ", ".join(bad_fields))
    if forbidden:
        reasons.append("forbidden phrase: " + ", ".join(forbidden))
    if marker_ok is False:
        reasons.append("answer never states the refusal/limit: " + " | ".join(markers))
    if faith["numbers_unsupported"]:
        reasons.append(f"{faith['numbers_unsupported']} unsupported number(s): {faith['unsupported']}")

    return record | {
        "calls": calls,
        "fields": fields,
        "answer": text,
        "answer_mode": getattr(answer, "mode", None),
        "model": getattr(answer, "model", None),
        "steps": getattr(answer, "steps", None),
        "repaired": bool(getattr(answer, "repaired", False)),
        "warnings": list(getattr(answer, "warnings", []) or []),
        "tool_calls": called,
        "tool_call_match": called == list(scenario["expected_tools"]),
        "tool_chain_covered": not missing_tools,
        "faithfulness": faith,
        "agent_faithfulness_passed": None if verdict is None else bool(getattr(verdict, "passed", False)),
        "forbidden": forbidden,
        "marker_ok": marker_ok,
        "privacy_hits": privacy_hits(text),
        "usage": dict(getattr(answer, "usage", {}) or {}),
        "passed": passed,
        "clean": bool(passed and not forbidden and marker_ok is not False and faith["numbers_unsupported"] == 0),
        "reason": "; ".join(reasons),
    }


async def run_agent(
    scenarios: list[dict[str, Any]], settings: Settings, budget: UpstreamBudget, *, require_llm: bool
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any]]:
    """Ask the agent every scenario question, or explain why the mode could not run."""
    agent, ctx, reason, provenance = await build_agent(settings, budget, require_llm=require_llm)
    if agent is None:
        return [], reason, {}
    records: list[dict[str, Any]] = []
    try:
        for scenario in scenarios:
            if budget.exhausted:
                records.append(skipped_record(scenario, f"skipped: upstream budget of {budget.ceiling} requests spent"))
                continue
            records.append(await run_agent_scenario(agent, scenario))
    finally:
        closer = getattr(agent, "aclose", None)
        await closer() if closer else await ctx.aclose()
    models = {r["model"] for r in records if r.get("model")}
    provenance["answer_modes"] = sorted({r["answer_mode"] for r in records if r.get("answer_mode")})
    provenance["models_used"] = sorted(models)
    return records, None, provenance


# ------------------------------------------------------------------------------ metrics
def _pct(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile; ``None`` for an empty sample rather than a misleading zero."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _rate(numerator: int, denominator: int) -> float | None:
    return None if not denominator else round(numerator / denominator, 4)


def summarise(records: list[dict[str, Any]], mode: str, budget: UpstreamBudget) -> dict[str, Any]:
    """Aggregate the run. Every value here is counted, or ``None`` when it cannot be."""
    ran = [r for r in records if r.get("passed") is not None]
    calls = [c for r in ran for c in r.get("calls", [])]
    ok = [c for c in calls if c["status"] in OK_STATUS]
    fields = [f for r in ran for f in r.get("fields", [])]
    required = [f for f in fields if f["status"] != "na"]
    passed_fields = sum(1 for f in required if f["status"] == "pass")
    ages = [c["age_seconds"] for c in calls if c.get("has_reported_at") and c.get("age_seconds") is not None]
    stamped: dict[str, list[float]] = {}
    for call in calls:
        if call.get("has_reported_at") and call.get("age_seconds") is not None:
            stamped.setdefault(call["provenance"]["source"], []).append(call["age_seconds"])
    by_source = {
        source: {"calls": len(values), "median_s": round(statistics.median(values), 1), "max_s": round(max(values), 1)}
        for source, values in sorted(stamped.items())
    }
    latencies = [r["latency_ms"] for r in ran if "latency_ms" in r]
    passed = sum(1 for r in ran if r["passed"])

    taxonomy: dict[str, int] = {}
    for call in calls:
        status = call["status"]
        if status == "refused_as_expected":
            kind = "refused_as_expected"
        elif status in {"missing_refusal", "wrong_refusal"}:
            # A tool that answered where it should have refused carries no exception, so
            # bucketing by `error_kind` would drop the most expensive failure we have from
            # the table entirely. Bucket those two by status instead.
            kind = status
        elif status not in OK_STATUS:
            kind = call.get("error_kind") or status
        else:
            kind = None
        if kind:
            taxonomy[kind] = taxonomy.get(kind, 0) + 1

    per_tool: dict[str, dict[str, Any]] = {}
    for call in calls:
        bucket = per_tool.setdefault(call["tool"], {"calls": 0, "ok": 0, "_lat": []})
        bucket["calls"] += 1
        bucket["ok"] += int(call["status"] in OK_STATUS)
        bucket["_lat"].append(call["latency_ms"])
    for bucket in per_tool.values():
        bucket["p50_ms"], bucket["p95_ms"] = _pct(bucket["_lat"], 0.5), _pct(bucket["_lat"], 0.95)
        bucket.pop("_lat")

    per_journey: dict[str, dict[str, int]] = {}
    for record in ran:
        bucket = per_journey.setdefault(record["journey"], {"run": 0, "passed": 0})
        bucket["run"] += 1
        bucket["passed"] += int(bool(record["passed"]))

    faiths = [r["faithfulness"] for r in ran if r.get("faithfulness")]
    stated = sum(f["numbers_stated"] for f in faiths)
    unsupported = sum(f["numbers_unsupported"] for f in faiths)
    matched = [r["tool_call_match"] for r in ran if r.get("tool_call_match") is not None]
    covered = [r["tool_chain_covered"] for r in ran if r.get("tool_chain_covered") is not None]
    markers = [r["marker_ok"] for r in ran if r.get("marker_ok") is not None]
    answered = [r for r in ran if r.get("answer") is not None]
    faithful_scenarios = [r for r in answered if r.get("faithfulness") and r["faithfulness"]["numbers_stated"]]
    return {
        "mode": mode,
        "scenarios_total": len(records),
        "scenarios_run": len(ran),
        "scenarios_skipped": len(records) - len(ran),
        "scenarios_passed": passed,
        "task_success_rate": _rate(passed, len(ran)),
        "tool_calls": len(calls),
        "tool_calls_ok": len(ok),
        "tool_success_rate": _rate(len(ok), len(calls)),
        "fields_checked": len(fields),
        "fields_required": len(required),
        "fields_passed": passed_fields,
        "fields_na": len(fields) - len(required),
        "field_coverage": _rate(passed_fields, len(required)),
        "provenance_present": sum(1 for c in calls if c.get("provenance")),
        "provenance_expected": len(ok) - sum(1 for c in calls if c["status"] == "refused_as_expected"),
        "provenance_with_reported_at": len(ages),
        "freshness_by_source": by_source,
        "freshness_median_s": None if not ages else round(statistics.median(ages), 1),
        "freshness_p95_s": None if not ages else round(_pct(ages, 0.95) or 0.0, 1),
        "latency_p50_ms": _pct(latencies, 0.5),
        "latency_p95_ms": _pct(latencies, 0.95),
        "per_tool": per_tool,
        "per_journey": per_journey,
        "error_taxonomy": taxonomy,
        "privacy_violations": sum(len(c.get("privacy_hits") or []) for c in calls)
        + sum(len(r.get("privacy_hits") or []) for r in ran),
        "numeric_faithfulness_rate": None if not stated else round(1 - unsupported / stated, 4),
        "numbers_stated": stated,
        "numbers_unsupported": unsupported,
        "tool_call_accuracy": _rate(sum(1 for m in matched if m), len(matched)),
        "tool_chain_coverage": _rate(sum(1 for c in covered if c), len(covered)),
        "answers_produced": len(answered),
        "answers_clean": sum(1 for r in answered if r.get("clean")),
        "answer_clean_rate": _rate(sum(1 for r in answered if r.get("clean")), len(answered)),
        "scenarios_fully_faithful": sum(1 for r in faithful_scenarios if not r["faithfulness"]["numbers_unsupported"]),
        "scenarios_with_numbers": len(faithful_scenarios),
        "refusal_marker_respected": _rate(sum(1 for m in markers if m), len(markers)),
        "refusal_marker_cases": len(markers),
        "self_check_agreed": sum(
            1 for r in answered
            if r.get("agent_faithfulness_passed") is not None
            and r["agent_faithfulness_passed"] == (not r["faithfulness"]["numbers_unsupported"])
        ),
        "self_check_scenarios": sum(1 for r in answered if r.get("agent_faithfulness_passed") is not None),
        "forbidden_violations": sum(len(r.get("forbidden") or []) for r in ran) if mode == "agent" else None,
        "upstream_calls": budget.used,
        "tokens": _sum_usage(ran),
    }


def _sum_usage(records: list[dict[str, Any]]) -> dict[str, float] | None:
    """Token and cost totals, only when the provider actually reported them."""
    total: dict[str, float] = {}
    for usage in (r["usage"] for r in records if isinstance(r.get("usage"), dict)):
        for key, value in usage.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                total[key] = total.get(key, 0) + float(value)
    return total or None


# ------------------------------------------------------------------------------- report
def _ratio(numerator: int, denominator: int) -> str:
    return "n/a (nothing ran)" if not denominator else f"{numerator}/{denominator} ({100 * numerator / denominator:.1f}%)"


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f} ms"


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    if seconds < 90:
        return f"{seconds:.0f} s"
    return f"{seconds / 60:.1f} min" if seconds < 5400 else f"{seconds / 3600:.1f} h"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header), *["| " + " | ".join(r) + " |" for r in rows]]


def readme_rows(summary: dict[str, Any], offline: bool) -> list[list[str]]:
    """The six rows the README's Results section expects, measured or ``n/a (reason)``."""
    det = summary["mode"] == "deterministic"
    task = _ratio(summary["scenarios_passed"], summary["scenarios_run"])
    faith = (
        f"{summary['numeric_faithfulness_rate'] * 100:.1f}% "
        f"({summary['numbers_stated'] - summary['numbers_unsupported']}/{summary['numbers_stated']} numbers)"
        if summary["numeric_faithfulness_rate"] is not None
        else "n/a (deterministic mode generates no answer text)" if det
        else "n/a (no answer stated a number, so nothing could be traced)"
    )
    accuracy = (
        f"{summary['tool_call_accuracy'] * 100:.1f}% exact chain, "
        f"{summary['tool_chain_coverage'] * 100:.1f}% expected tools called"
        if summary["tool_call_accuracy"] is not None and summary["tool_chain_coverage"] is not None
        else "n/a (the harness calls the expected chain itself; only an agent can pick the wrong tool)" if det
        else "n/a (no scenario ran)"
    )
    fresh = (
        "n/a (no upstream timestamp in any result)"
        if summary["freshness_median_s"] is None
        else f"{_duration(summary['freshness_median_s'])} median, {_duration(summary['freshness_p95_s'])} p95"
    )
    return [
        [
            "Task success rate", task,
            f"journey scenarios from `eval/journeys.jsonl` ({summary['scenarios_total']} selected, "
            f"{summary['scenarios_run']} run); a scenario passes when every tool call returns (or refuses exactly "
            "where it should) and every required field is present"
            if det else "the agent answered, called every tool the scenario expects and produced every required "
            "field; the hedges, the unsupported numbers and the refusal wording are scored separately below, "
            "because a single pass/fail would hide which of them broke",
        ],
        [
            "Bus ETA mean absolute error",
            "n/a (no observed arrivals logged yet: the collector must run for several days before a prediction "
            "can be paired with the arrival it predicted)",
            "`eta_log` — every estimate is written with its method; the collector marks the vehicle's real arrival "
            "at that stop; MAE over those pairs",
        ],
        ["Numeric faithfulness", faith,
         "share of the free-standing numbers in the answer that appear in a tool result or in the question; "
         "`PM10`, `500T` and timestamps are names, not claims, and an ambiguous `1.250` is allowed either "
         "the Turkish (1250) or the English (1.25) reading"],
        ["Tool-call accuracy", accuracy, "called chain vs. the scenario's `expected_tools`"],
        ["p95 end-to-end latency", _ms(summary["latency_p95_ms"]),
         ("sum of the scenario's tool calls, cache shared across scenarios" if det else "question to answer, wall clock")
         + (", fixtures, no network"
            if offline
            else ", live network — a cold-cache call also waits out the client's own ≥6 s per-host spacing, "
                 "so this is politeness plus İBB, not İBB alone")],
        ["Data freshness at answer time", fresh,
         f"age of the reading itself (`provenance.reported_at`) over the {summary['provenance_with_reported_at']} of "
         f"{summary['tool_calls']} calls whose source stamps its data; a metro notice is stamped when it was issued, "
         "so it is legitimately days old while the read is seconds old — see 'Freshness by source'"
         + (" — offline this is the age of the recorded fixtures, not of live data" if offline else "")],
    ]


def answer_layer(summary: dict[str, Any], context: dict[str, Any]) -> list[str]:
    """The rows only an agent run can fill: what the prose said, and whether it holds up."""
    if summary["mode"] != "agent":
        return []
    agent = context.get("agent") or {}
    modes = ", ".join(agent.get("answer_modes") or []) or "unknown"
    model = ", ".join(agent.get("models_used") or []) or (agent.get("model") or "none")
    marker = (
        f"{summary['refusal_marker_respected'] * 100:.1f}% ({summary['refusal_marker_cases']} scenarios require a "
        "refusal or a limit to be stated in words)"
        if summary["refusal_marker_respected"] is not None
        else "n/a (no scenario in this selection requires one)"
    )
    faithful = (
        _ratio(summary["scenarios_fully_faithful"], summary["scenarios_with_numbers"])
        if summary["scenarios_with_numbers"]
        else "n/a (no answer stated a number)"
    )
    return [
        "## Answer layer",
        "",
        *_table(
            ["Metric", "Result"],
            [
                ["Model", f"`{model}` · provider `{agent.get('provider') or 'none'}` · answer mode `{modes}`"],
                ["Answers produced", str(summary["answers_produced"])],
                ["Expected tools all called", "n/a" if summary["tool_chain_coverage"] is None
                 else f"{summary['tool_chain_coverage'] * 100:.1f}%"],
                ["Exact expected chain", "n/a" if summary["tool_call_accuracy"] is None
                 else f"{summary['tool_call_accuracy'] * 100:.1f}%"],
                ["Scenarios with every number supported", faithful],
                ["Refusal / limit stated in the answer", marker],
                ["Agent's own faithfulness guard agreed with this harness",
                 _ratio(summary["self_check_agreed"], summary["self_check_scenarios"])],
                ["Clean answers (passed, no hedge, no unsupported number, refusal stated)",
                 _ratio(summary["answers_clean"], summary["answers_produced"])],
            ],
        ),
        "",
    ]


def render(summary: dict[str, Any], records: list[dict[str, Any]], context: dict[str, Any]) -> str:
    """Markdown whose first table is exactly the README's Results section."""
    offline = context["offline"]
    lines = [
        f"# Eval results — {context['started_utc']}",
        "",
        f"`mode={summary['mode']}` · `{'offline' if offline else 'live'}` · data source: "
        f"{'recorded fixtures (tests/fixtures)' if offline else 'live İBB endpoints'} · "
        f"{summary['scenarios_run']}/{summary['scenarios_total']} scenarios run"
        + (f", {summary['scenarios_skipped']} skipped" if summary["scenarios_skipped"] else "")
        + f" · upstream requests to İBB: {summary['upstream_calls']}"
        + ("" if summary["mode"] != "agent" else
           " · agent: " + ("model " + (", ".join((context.get("agent") or {}).get("models_used") or [])
                                       or str((context.get("agent") or {}).get("model") or "configured"))
                           if (context.get("agent") or {}).get("llm_configured")
                           else "**no model configured — keyword-routed answers**")),
        "",
        "## Results",
        "",
        *_table(["Metric", "Result", "How it is measured"], readme_rows(summary, offline)),
        "",
        "## Data layer",
        "",
        *_table(
            ["Metric", "Result"],
            [
                ["Tool success rate", _ratio(summary["tool_calls_ok"], summary["tool_calls"])],
                ["Required fields present", _ratio(summary["fields_passed"], summary["fields_required"])],
                ["Optional checks not applicable", f"{summary['fields_na']} of {summary['fields_checked']}"],
                ["Provenance present (calls that returned data)",
                 _ratio(summary["provenance_present"], summary["provenance_expected"])],
                ["Of those, carrying an upstream timestamp",
                 _ratio(summary["provenance_with_reported_at"], summary["provenance_expected"])],
                ["Number-plate leaks", str(summary["privacy_violations"])],
                ["p50 scenario latency", _ms(summary["latency_p50_ms"])],
                ["Forbidden-phrase violations", "n/a (no generated answer in this mode)"
                 if summary["forbidden_violations"] is None else str(summary["forbidden_violations"])],
                ["Tokens / cost", "n/a (no provider usage reported)" if not summary["tokens"]
                 else ", ".join(f"{k}={v:g}" for k, v in sorted(summary["tokens"].items()))],
            ],
        ),
        "",
        *answer_layer(summary, context),
        "## Freshness by source",
        "",
        *(
            _table(
                ["Source", "Calls", "Median age", "Oldest"],
                [[f"`{s}`", str(b["calls"]), _duration(b["median_s"]), _duration(b["max_s"])]
                 for s, b in summary["freshness_by_source"].items()],
            )
            if summary["freshness_by_source"]
            else ["No result carried an upstream timestamp, so no age could be attributed to a source."]
        ),
        "",
        "## Per journey",
        "",
        *_table(
            ["Journey", "Passed"],
            [[j, _ratio(b["passed"], b["run"])] for j, b in sorted(summary["per_journey"].items())],
        ),
        "",
        "## Per tool",
        "",
        *_table(
            ["Tool", "Calls", "OK", "p50", "p95"],
            [
                [f"`{tool}`", str(b["calls"]), str(b["ok"]), _ms(b["p50_ms"]), _ms(b["p95_ms"])]
                for tool, b in sorted(summary["per_tool"].items())
            ],
        ),
        "",
        "## Error taxonomy",
        "",
    ]
    if summary["error_taxonomy"]:
        lines += _table(["Kind", "Count"], [[f"`{k}`", str(v)] for k, v in sorted(summary["error_taxonomy"].items())])
    else:
        lines.append("No tool call failed, and no refusal was expected.")
    lines += [
        "",
        "## Scenarios",
        "",
        *_table(
            ["id", "lang", "journey", "Result", "Latency", "Note"],
            [
                [
                    f"`{r['id']}`", r["lang"], r["journey"],
                    "skipped" if r.get("passed") is None else ("pass" if r["passed"] else "**fail**"),
                    _ms(r.get("latency_ms")), (r.get("reason") or "").replace("|", "/")[:130],
                ]
                for r in records
            ],
        ),
        "",
        "---",
        "",
        f"Harness `eval/run_eval.py` · scenarios `eval/journeys.jsonl` · commit `{context['commit']}` · "
        f"Python {context['python']} · finished {context['finished_utc']}",
        "",
        "Contains public sector information from the İstanbul Metropolitan Municipality Open Data Portal, "
        "licensed under the İBB Open Data Licence (CC BY 4.0).",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------------- main
def selftest(scenarios: list[dict[str, Any]]) -> int:
    """Validate the scenario file and the metric helpers, touching neither data nor network."""
    problems: list[str] = []
    languages: dict[str, int] = {}
    journeys: dict[str, int] = {}
    for scenario in scenarios:
        languages[scenario["lang"]] = languages.get(scenario["lang"], 0) + 1
        journeys[scenario["journey"]] = journeys.get(scenario["journey"], 0) + 1
    if len(scenarios) != 24:
        problems.append(f"expected 24 scenarios, found {len(scenarios)}")
    if languages.get("tr") != 12 or languages.get("en") != 12:
        problems.append(f"expected 12 TR and 12 EN, found {languages}")
    problems += [f"{j} has {n} scenarios, expected 6" for j, n in sorted(journeys.items()) if n != 6]
    covered = {call["tool"] for s in scenarios for call in s["calls"]}
    exposed = {n for n in dir(Nabiz) if not n.startswith("_")} - {"gtfs", "aclose"}
    if missing := sorted(exposed - covered):
        problems.append(f"tools never exercised: {missing}")
    refusals = [s["id"] for s in scenarios if any(c.get("expect") == "refusal" for c in s["calls"])]
    # An "honest limits" case is one that asserts the *unavailability itself* — `available ==
    # false`, `baseline_only == true` — not merely that the field exists, which every air-quality
    # scenario asserts.
    limits = [
        s["id"] for s in scenarios
        if any(spec.replace(" ", "").endswith(("==false", "baseline_only==true")) for spec in s["expected_fields"])
    ]
    if len(refusals) < 1 or len(limits) < 2:
        problems.append(f"expected >=1 refusal and >=2 honest-limits scenarios, found {len(refusals)} and {len(limits)}")
    # A refusal or a stated limit only counts if the *answer* says it, so those scenarios must
    # carry the words agent mode looks for; without them the check would silently pass on prose
    # that quietly produced an estimate anyway.
    for scenario in scenarios:
        markers = scenario.get("answer_must_contain_any", [])
        if not isinstance(markers, list) or any(not isinstance(m, str) or not m for m in markers):
            problems.append(f"{scenario['id']}: answer_must_contain_any must be a list of non-empty strings")
    unmarked = [i for i in refusals + limits if not next(s for s in scenarios if s["id"] == i).get("answer_must_contain_any")]
    if unmarked:
        problems.append(f"refusal/limit scenarios without answer_must_contain_any: {unmarked}")

    checks = [
        ("tr numbers", parse_numbers("1.250 araç, %12,5 dolu", "tr") == [1250.0, 12.5]),
        ("en numbers", parse_numbers("1,250 vehicles, 12.5% full", "en") == [1250.0, 12.5]),
        ("faithful answer", faithfulness("18 boş yer var", "tr", "Taksim?", {18.0})["rate"] == 1.0),
        ("invented number caught", faithfulness("42 boş yer var", "tr", "Taksim?", {18.0})["rate"] == 0.0),
        ("pollutant symbol is a name", parse_numbers("PM10 5 µg/m³, SO2 1,7", "tr") == [5.0, 1.7]),
        ("line code is a name", parse_numbers("500T ve M4 hattı, 3 durak", "tr") == [3.0]),
        ("dotted station name is a name", parse_numbers("4.Levent Metro, 2 peron", "tr") == [2.0]),
        ("a decimal ending a sentence is still a claim", parse_numbers("Doluluk %12,5.Bunlar", "tr") == [12.5]),
        ("timestamp is not a claim", parse_numbers("08.09.2026 05:10:17 · 2026-09-08T05:10:17+03:00", "tr") == []),
        ("licence line is not a claim", parse_numbers("Kaynak: İBB Açık Veri (CC BY 4.0)", "tr") == []),
        ("turkish text in an english scenario", faithfulness("41,0422 enlem", "en", "", {41.0422})["rate"] == 1.0),
        ("either reading still catches an invention", faithfulness("77,7 enlem", "en", "", {41.0422})["rate"] == 0.0),
        ("forbidden phrase caught", forbidden_hits("Otobüs kesinlikle 5 dakikada gelir.", ["kesinlikle"]) == ["kesinlikle"]),
        ("disclaimer not a violation", forbidden_hits("Bu resmi İETT bilgisi değildir.", ["resmi"]) == []),
        ("plate key caught", privacy_hits('{"Plaka": "34 HO 1000"}') != []),
        ("door number is clean", privacy_hits('{"door_no": "C-338", "lat": 41.05}') == []),
        ("probe all", _probe({"a": [{"b": 1}, {"b": 2}]}, ["a[]", "b"], _NO_VALUE) == "pass"),
        ("probe any", _probe({"a": [{"b": 1}, {}]}, ["a[?]", "b"], _NO_VALUE) == "pass"),
        ("probe strict", _probe({"a": [{"b": 1}, {}]}, ["a[]", "b"], _NO_VALUE) == "fail"),
        ("probe empty list", _probe({"a": []}, ["a[]", "b"], _NO_VALUE) == "empty"),
        ("probe false is a value", _probe({"a": False}, ["a"], False) == "pass"),
        ("percentile", _pct([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0 and _pct([], 0.5) is None),
        ("agent refusal read back", classify_message("500T hattı 'KADIKÖY' durağına uğramıyor.") == "bad_request"),
        ("agent outage read back", classify_message("İBB servisi şu anda yanıt vermiyor: 503") == "upstream_unavailable"),
        ("age of a stamped reading", (_age_seconds({"reported_at": "2000-01-01T00:00:00+00:00"}) or 0) > 8e8),
        ("age of an unstamped reading", _age_seconds({}) is None),
    ]
    problems += [f"metric self-check failed: {name}" for name, ok in checks if not ok]

    print(f"scenarios: {len(scenarios)} {languages} journeys: {journeys}")
    print(f"tools exercised: {len(covered)}/{len(exposed)} · refusal cases: {refusals} · honest-limits cases: {limits}")
    print(f"metric self-checks: {sum(1 for _, ok in checks if ok)}/{len(checks)} passed")
    for problem in problems:
        print(f"  PROBLEM: {problem}")
    print("selftest FAILED" if problems else "selftest OK")
    return 1 if problems else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the İstanbul Nabız journey evaluation.")
    parser.add_argument("--mode", choices=("deterministic", "agent"), default="deterministic")
    parser.add_argument("--offline", action="store_true", help="Serve recorded fixtures; makes no network call")
    parser.add_argument("--limit", type=int, default=0, help="Run only the first N selected scenarios")
    parser.add_argument("--only", default="", help="Comma-separated scenario ids or id prefixes (e.g. j2,j3-en)")
    parser.add_argument("--max-upstream", type=int, default=8,
                        help="Ceiling on real requests to İBB (0 = no ceiling); the run skips the rest instead of exceeding it")
    parser.add_argument("--journeys", type=pathlib.Path, default=JOURNEYS)
    parser.add_argument("--results-dir", type=pathlib.Path, default=RESULTS)
    parser.add_argument("--require-llm", action="store_true",
                        help="Agent mode: skip unless a model is configured, instead of measuring the no-model path")
    parser.add_argument("--selftest", action="store_true", help="Check the scenario file and metric helpers, then exit")
    return parser.parse_args(argv)


def _display(path: pathlib.Path) -> str:
    """Repo-relative when it can be, absolute when --results-dir points elsewhere."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def git_commit() -> str:
    try:
        done = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=5, check=False)
        return done.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 - a missing git is not an eval failure
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    scenarios = load_scenarios(args.journeys)
    if args.selftest:
        return selftest(scenarios)

    chosen = scenarios
    if args.only:
        wanted = tuple(part.strip() for part in args.only.split(",") if part.strip())
        chosen = [s for s in chosen if s["id"].startswith(wanted)]
    if args.limit:
        chosen = chosen[: args.limit]
    if not chosen:
        print("No scenario matched the selection.", file=sys.stderr)
        return 2

    settings = Settings(offline=True) if args.offline else Settings.from_env()
    budget = UpstreamBudget(0 if args.offline else args.max_upstream)
    started = dt.datetime.now(dt.UTC)
    agent_context: dict[str, Any] = {}
    if args.mode == "deterministic":
        records, skip_reason = asyncio.run(run_deterministic(chosen, settings, budget)), None
    else:
        records, skip_reason, agent_context = asyncio.run(
            run_agent(chosen, settings, budget, require_llm=args.require_llm)
        )
    finished = dt.datetime.now(dt.UTC)

    if skip_reason:
        print(f"--mode agent skipped: {skip_reason}")
        print("Deterministic mode still measures the data layer; the agent-only rows stay n/a until an agent runs.")
        return 3
    if args.mode == "agent" and not agent_context.get("llm_configured"):
        # Not a skip: NabizAgent answers without a model by routing on keywords (DECISIONS #5).
        # It is a different system from the model path and every row below says so.
        print(
            "No LLM is configured, so this measures NabizAgent's no-model path: keyword routing to a single "
            f"tool and a templated answer. Set one of {', '.join(LLM_ENV_VARS)} to measure the model path, "
            "or pass --require-llm to make the absence a skip instead."
        )

    context = {
        "started_utc": started.isoformat(timespec="seconds"),
        "finished_utc": finished.isoformat(timespec="seconds"),
        "offline": bool(args.offline),
        "commit": git_commit(),
        "python": sys.version.split()[0],
        "max_upstream": budget.ceiling,
        "selection": {"limit": args.limit, "only": args.only},
        "agent": agent_context,
    }
    summary = summarise(records, args.mode, budget)
    report = render(summary, records, context)
    args.results_dir.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    json_path = args.results_dir / f"{stamp}-{args.mode}-{'offline' if args.offline else 'live'}.json"
    json_path.write_text(
        json.dumps({"context": context, "summary": summary, "scenarios": records}, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    # Each run keeps its own markdown as well as its JSON: `latest.md` is the pointer the
    # README quotes from, and it would otherwise be overwritten by the next run, losing the
    # only readable record of, say, the one live run of the day.
    report_path = json_path.with_suffix(".md")
    report_path.write_text(report, encoding="utf-8")
    (args.results_dir / "latest.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"written: {_display(json_path)} · {_display(report_path)} · {_display(args.results_dir / 'latest.md')}")
    return 1 if any(r.get("passed") is False for r in records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
