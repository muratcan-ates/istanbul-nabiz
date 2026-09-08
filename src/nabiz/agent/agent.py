"""The Nabız city agent: a tool loop over ``ibb_mcp.tools.Nabiz`` that cannot invent numbers.

Three decisions shape this file.

**The tools are the MCP server's tools.** The agent calls :class:`~ibb_mcp.tools.Nabiz`
in-process rather than over MCP, but the twelve function schemas are built from those same
method signatures and carry the same Turkish descriptions the MCP server advertises. One
surface, two transports: whatever VS Code Copilot can ask, this agent can ask.

**Every answer is checked before it is returned.** After the model writes prose we run
:mod:`nabiz.agent.faithfulness` over it with the raw tool payloads as the evidence. A
failure buys exactly one repair attempt — the model is told which numbers are unsupported
and asked to rewrite. A second failure returns the answer with ``faithfulness.passed`` False
and a warning attached, because silently returning an unverified number is the one outcome
this project exists to prevent.

**The agent runs without a model at all.** Azure for Students may have zero Azure OpenAI
quota (DECISIONS #5). When :func:`nabiz.agent.llm.available` is False, :meth:`NabizAgent.ask`
switches to ``deterministic`` mode: keyword routing to a single tool plus a templated answer
built only from that tool's payload. It is not a language model and does not pretend to be —
it answers the four demo journeys, states its sources and ages, and passes the same
faithfulness check. That is what keeps the demo alive with no quota.
"""

from __future__ import annotations

import contextlib
import inspect
import json
import logging
import pathlib
import re
import time
import typing
from dataclasses import dataclass, field
from typing import Any

from ibb_mcp.http import RateLimitExceeded, UpstreamUnavailable
from ibb_mcp.models import ToolResult
from ibb_mcp.sources.places import normalize_tr
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.agent.faithfulness import FaithfulnessReport, check_faithfulness

log = logging.getLogger("nabiz.agent")

PROMPT_PATH = pathlib.Path(__file__).with_name("system_prompt.md")

#: Turkish descriptions, verbatim from ``ibb_mcp/server.py``. They are duplicated rather
#: than imported because the MCP tools are closures created inside ``build_server()``:
#: reading them would mean constructing a live server and an HTTP client just to read a
#: docstring. Keep the two in step when a description changes.
TOOL_DESCRIPTIONS: dict[str, str] = {
    "places_resolve": "İstanbul'da bir yer adını koordinata çevirir (semt, ilçe, metro istasyonu, simge yer). "
    "Kullanıcı bir yer adı söylediğinde önce bunu çağır, sonra koordinatları diğer araçlara ver.",
    "ispark_find_parking": "Bir yerin yakınındaki İSPARK otoparklarını canlı boş yer sayısıyla listeler. "
    "`place` (ör. \"Taksim\") ya da `lat`/`lon` ver. Sonuçta kapasite, boş yer, otopark tipi, yürüme mesafesi ve "
    "ilk üç otopark için tarife bilgisi döner. Veri ~10 dakikada bir güncellenir.",
    "ispark_typical_occupancy": "Bir otoparkın belirli gün ve saatteki tipik doluluğunu döner. İBB otopark geçmişi "
    "yayınlamadığı için bu profil projenin kendi topladığı anlık görüntülerden üretilir; yeterli gözlem yoksa "
    "`available: false` döner ve tahmin üretilmez.",
    "iett_stops_search": "İETT otobüs duraklarını ada göre arar; durak kodu, adı ve koordinatını döner. "
    "Dönen `stop_code` alanı `iett_next_arrivals` aracına verilecek olan koddur.",
    "iett_line_buses": "Bir otobüs hattındaki araçların anlık konumunu döner (ör. line_code=\"500T\"). "
    "`direction` verilirse yalnızca o yöne giden araçlar döner. Araç plakası hiçbir zaman döndürülmez; "
    "araçlar kapı numarasıyla tanımlanır.",
    "iett_next_arrivals": "Bir hattın bir durağa tahmini varış sürelerini döner. `stop` durak kodu veya durak adı "
    "olabilir. Her tahmin hangi yöntemle üretildiğini (`stop_sequence`, `distance`, `schedule`) ve güven düzeyini "
    "bildirir. BU BİR TAHMİNDİR, resmî İETT bilgisi değildir; kullanıcıya böyle söyle.",
    "metro_status": "Metro İstanbul hatlarındaki canlı arıza ve çalışma duyurularını döner. Servis yalnızca duyurusu "
    "olan hatları döndürür; bir hat listede yoksa o hat için bildirilmiş bir aksaklık yok demektir.",
    "metro_station_info": "Bir metro istasyonunun hattını, sırasını ve erişilebilirlik bilgisini döner. "
    "Asansör, yürüyen merdiven, WC, bebek bakım odası ve mescit bilgisi içerir.",
    "traffic_index": "İstanbul geneli trafik yoğunluk indeksini döner (1 akıcı, 99 kilitli). `window=\"now\"` anlık "
    "değeri, `window=\"24h\"` son 24 saati ve dünkü aynı saatle karşılaştırmayı döner.",
    "air_quality_now": "Bir yere en yakın istasyonun güncel hava kalitesi ölçümünü döner. PM10, SO2, O3, NO2, CO "
    "derişimleri ile AQI indeksi ve sağlık durumu metnini içerir. PM2.5 İBB API'sinde yoktur. "
    "Sağlık tavsiyesi değildir.",
    "air_quality_forecast": "Kısa vadeli PM10 tahmini ve önümüzdeki en temiz zaman aralığını döner. İndeks değil "
    "saatlik derişim tahmin edilir, çünkü İBB PM10 indeksini 24 saatlik hareketli ortalamadan hesaplar. "
    "Sağlık tavsiyesi değildir.",
    "city_freshness": "Her veri kaynağının ne kadar güncel olduğunu ve kalan istek bütçesini döner. Bir cevabın ne "
    "kadar taze veriye dayandığını söylemen gerektiğinde bunu çağır.",
}

#: Parameters the MCP server does not advertise; the agent keeps the same surface.
HIDDEN_PARAMS: dict[str, set[str]] = {"ispark_find_parking": {"with_tariff"}}

PARAM_HINTS: dict[str, str] = {
    "place": "Yer adı, ör. 'Taksim', 'Kadıköy', 'Beşiktaş'.",
    "query": "Aranacak metin.",
    "line_code": "İETT hat kodu, ör. '500T', '34AS'.",
    "line": "Metro hat adı, ör. 'M4'.",
    "stop": "Durak adı veya durak kodu.",
    "name": "İstasyon adı, ör. 'Kartal'.",
    "window": "'now' ya da '24h'.",
    "horizon_hours": "Kaç saatlik tahmin isteniyor (en fazla 6).",
    "park_id": "İSPARK otopark kimliği (ispark_find_parking sonucundaki park_id).",
    "radius_km": "Arama yarıçapı, kilometre.",
    "min_free": "En az kaç boş yer olsun.",
}

_JSON_TYPES: dict[Any, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}

try:  # Optional: traces land in Application Insights when the exporter is configured.
    from opentelemetry import trace as _otel  # noqa: PLC0415

    _tracer = _otel.get_tracer("nabiz.agent")
except ImportError:  # pragma: no cover - opentelemetry is not a hard dependency
    _tracer = None


@contextlib.contextmanager
def _span(name: str, **attributes: Any):
    """One span, or nothing at all when OpenTelemetry is not installed."""
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        yield span


@dataclass
class ToolCallRecord:
    """One tool invocation, kept so the eval harness can score the chain."""

    name: str
    arguments: dict[str, Any]
    ok: bool
    payload: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class AgentAnswer:
    """Everything a run produced: the prose, the evidence and the verdict on it."""

    text: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    faithfulness: FaithfulnessReport | None = None
    mode: str = "llm"
    lang: str = "tr"
    steps: int = 0
    repaired: bool = False
    warnings: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def tool_names(self) -> list[str]:
        return [call.name for call in self.tool_calls]


def _json_type(annotation: Any) -> str:
    """Map a Python annotation onto a JSON Schema type, unwrapping ``X | None``."""
    args = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
    base = args[0] if args else annotation
    return _JSON_TYPES.get(base, "string")


def build_tool_schemas(names: list[str] | None = None) -> list[dict[str, Any]]:
    """OpenAI-style function schemas derived from the ``Nabiz`` method signatures."""
    schemas: list[dict[str, Any]] = []
    for name in names or list(TOOL_DESCRIPTIONS):
        method = getattr(Nabiz, name)
        hints = typing.get_type_hints(method)
        hidden = HIDDEN_PARAMS.get(name, set())
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in inspect.signature(method).parameters.values():
            if param.name in {"self", "return"} or param.name in hidden:
                continue
            schema: dict[str, Any] = {"type": _json_type(hints.get(param.name, str))}
            if param.name in PARAM_HINTS:
                schema["description"] = PARAM_HINTS[param.name]
            if param.default is not inspect.Parameter.empty and param.default is not None:
                schema["default"] = param.default
            properties[param.name] = schema
            if param.default is inspect.Parameter.empty:
                required.append(param.name)
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": TOOL_DESCRIPTIONS[name],
                    "parameters": {"type": "object", "properties": properties, "required": required},
                },
            }
        )
    return schemas


def _payload(result: ToolResult) -> dict[str, Any]:
    """The JSON a tool result becomes for the model — provenance always included.

    Deliberately re-implemented rather than imported from ``ibb_mcp.server``: that renderer
    is a private helper of a module this agent must not depend on, and the agent needs the
    dict itself (for the faithfulness check), not a string.
    """
    provenance = result.provenance
    return {
        "data": result.data,
        "provenance": {
            "source": provenance.source,
            "source_url": provenance.source_url,
            "reported_at": provenance.reported_at.isoformat() if provenance.reported_at else None,
            "observed_at": provenance.observed_at.isoformat(),
            "age": provenance.describe_age(),
            "stale": provenance.cached,
            "license": provenance.license,
        },
        **({"note": result.note} if result.note else {}),
    }


def detect_language(text: str) -> str:
    """Turkish unless the question looks English. Cheap on purpose — no model call."""
    if re.search(r"[çğıöşüÇĞİÖŞÜ]", text):
        return "tr"
    words = set(re.findall(r"[a-zçğıöşü]+", text.lower()))
    turkish = {"var", "mi", "mı", "nasil", "nasıl", "nerede", "ne", "kac", "kaç", "hangi", "otopark", "durak", "hava"}
    english = {"the", "is", "are", "how", "what", "where", "when", "which", "parking", "air", "quality", "bus", "near"}
    return "en" if len(words & english) > len(words & turkish) else "tr"


# --------------------------------------------------------------------------------------
# deterministic mode: keyword routing + templates, for when there is no model quota
# --------------------------------------------------------------------------------------
#: A metro/tram/funicular code. The trailing guard is ``(?!\d)`` rather than ``\b`` so a
#: Turkish case ending still resolves: "M4'te", "M4te" and "M4ün" all name line M4.
_METRO_LINE_RE = re.compile(r"\b(M\d{1,2}[AB]?|T\d|F\d|MARMARAY)(?!\d)", re.IGNORECASE)
_BUS_LINE_RE = re.compile(r"\b(\d{1,3}[A-ZÇĞİÖŞÜ]{1,2})\b")
_BUS_NUMBER_RE = re.compile(r"\b(\d{2,3})\s*(?:hat|numaral[ıi]|line|otob[üu]s)", re.IGNORECASE)
_STOP_RE = re.compile(r"([\w'’.\- ]{2,32}?)\s*dura[ğg]", re.UNICODE)

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "air": ("hava kalitesi", "hava kirlil", "air quality", "hava", "aqi", "pm10", "pollution", "smog"),
    "window": ("ne zaman", "en iyi", "en uygun", "best time", "best window", "kosu", "spor", "yuruyus", "forecast", "tahmin"),
    "parking": ("park yeri", "car park", "otopark", "parking", "ispark"),
    "metro": ("metro", "marmaray", "tramvay", "funikuler"),
    "station": ("yuruyen merdiven", "istasyon", "asansor", "engelli", "station", "lift", "elevator", "escalator", "wc"),
    "arrival": ("ne zaman gelir", "kac dakika", "next bus", "when does", "varis", "gelir", "arrive", "arrival"),
    "stop": ("durak", "duragi", "stop"),
    "traffic": ("trafik", "traffic", "yogunluk", "congestion", "sikisik"),
    # "verinin yasi" is spelled out beside "veri yasi": a multi-word key is an exact
    # substring test, and Turkish declines the first word too, so the genitive form does
    # not match the nominative one.
    "fresh": (
        "veri yasi",
        "verinin yasi",
        "veri ne kadar",
        "ne kadar guncel",
        "guncel mi",
        "how old",
        "data age",
        "tazelik",
        "freshness",
    ),
}

#: Tokens that would otherwise trip a keyword prefix: an airport question is not an
#: air-quality question.
_NOT_KEYWORD = {"havalimani", "havaalani", "havacilik", "havuz"}


def _has(text: str, group: str) -> bool:
    """Keyword test over the folded question.

    Multi-word keys match as substrings; single words match as token *prefixes*, because
    Turkish glues its case endings on ("otoparkta", "trafikte", "havada") and an exact
    token test would miss every real sentence.
    """
    tokens = text.split()
    for word in _KEYWORDS[group]:
        if " " in word:
            if word in text:
                return True
        elif any(token.startswith(word) and not _excluded(token) for token in tokens):
            return True
    return False


def _excluded(token: str) -> bool:
    """Is this token one of the false friends?

    The exclusion has to be a **prefix** test for the same reason the keyword test is:
    "havalimanına", "havalimanında" and "havaalanına" are the forms people actually write,
    and an exact-token exclusion let every one of them through as an air-quality question.
    """
    return any(token.startswith(bad) for bad in _NOT_KEYWORD)


#: Folded tokens that introduce a line rather than belong to a stop name. "metro" is
#: deliberately absent: "4.LEVENT METRO" really is the stop's name.
_LINE_FILLER = {"otobus", "otobusu", "otobusun", "hat", "hatti", "hattin", "bus", "line", "numarali", "sefer"}
_FOLDED_BUS_LINE_RE = re.compile(r"\d{1,3}[a-z]{1,2}")
_FOLDED_METRO_LINE_RE = re.compile(r"m\d{1,2}[ab]?|t\d|f\d|marmaray")


def _is_line_or_filler(word: str) -> bool:
    """Is this leading word part of the *line*, not of the stop name?"""
    folded = normalize_tr(word)
    if not folded:
        return True
    return bool(
        folded in _LINE_FILLER
        or _FOLDED_BUS_LINE_RE.fullmatch(folded)
        or _FOLDED_METRO_LINE_RE.fullmatch(folded)
    )


def _num(value: Any, digits: int = 1) -> str:
    """Format a number the Turkish way. Only ever called on values from a tool payload."""
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.{digits}f}".replace(".", ",")
    return str(int(value)) if isinstance(value, float) else str(value)


class NabizAgent:
    """A city agent over the twelve İBB tools, with or without a language model."""

    def __init__(
        self,
        nabiz: Nabiz | None = None,
        *,
        config: llm.LlmConfig | None = None,
        system_prompt: str | None = None,
        tools: list[str] | None = None,
    ) -> None:
        self.nabiz = nabiz or Nabiz()
        self.config = config if config is not None else llm.LlmConfig.from_env()
        self.schemas = build_tool_schemas(tools)
        self._prompt = system_prompt

    @property
    def system_prompt(self) -> str:
        if self._prompt is None:
            self._prompt = PROMPT_PATH.read_text(encoding="utf-8")
        return self._prompt

    async def aclose(self) -> None:
        await self.nabiz.aclose()

    # -- public entry point -------------------------------------------------------
    async def ask(self, question: str, lang: str | None = None, max_steps: int = 4) -> AgentAnswer:
        """Answer one question, then verify every number in the answer against the tools."""
        lang = lang or detect_language(question)
        warnings: list[str] = []
        with _span("nabiz.ask", **{"nabiz.lang": lang, "nabiz.provider": self.config.provider}):
            if llm.available(self.config):
                try:
                    return await self._ask_model(question, lang, max_steps)
                except llm.LlmError as exc:
                    log.warning("model unavailable mid-run, falling back to deterministic mode: %r", exc)
                    warnings.append(f"Model çağrısı başarısız ({exc}); deterministic moda düşüldü.")
            answer = await self._ask_deterministic(question, lang)
            answer.warnings = warnings + answer.warnings
            return answer

    # -- model path ---------------------------------------------------------------
    async def _ask_model(self, question: str, lang: str, max_steps: int) -> AgentAnswer:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": question},
        ]
        calls: list[ToolCallRecord] = []
        usage: dict[str, Any] = {}
        text, model_name, steps = "", None, 0
        #: True while the model is still mid-chain. A reply that asks for tools may also
        #: carry prose ("Trafiğe bakıyorum…") — that prose was written *before* the tool
        #: results existed, so it must never survive as the answer.
        pending_tools = False

        for _ in range(max(1, max_steps)):
            steps += 1
            with _span("nabiz.model", **{"nabiz.step": steps}):
                response = await llm.chat(self.config, messages, tools=self.schemas)
            _merge_usage(usage, response.get("usage"))
            model_name = response.get("model") or model_name
            text = (response.get("content") or "").strip()
            requested = response.get("tool_calls") or []
            pending_tools = bool(requested)
            if not requested:
                break
            messages.append(_assistant_message(response.get("content"), requested))
            for call in requested:
                record = await self._call_tool(call["name"], call["arguments"])
                calls.append(record)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": call["name"],
                        "content": json.dumps(
                            record.payload if record.ok else {"error": record.error},
                            ensure_ascii=False,
                            default=str,
                        ),
                    }
                )
        if pending_tools or not text:
            # Step budget spent while still calling tools: ask once more for prose only.
            with _span("nabiz.model", **{"nabiz.step": steps + 1, "nabiz.forced": True}):
                response = await llm.chat(self.config, [*messages, {"role": "user", "content": _FORCE_PROSE[lang]}])
            steps += 1
            _merge_usage(usage, response.get("usage"))
            text = (response.get("content") or "").strip() or text

        evidence = [call.payload for call in calls if call.payload]
        # A tool error is evidence too. The system prompt orders the model to relay one
        # verbatim ("bu durağa uğrayan hatlar: 153, 154, …"); flagging the numbers inside
        # it as fabrications would punish the model for obeying.
        errors = [call.error for call in calls if call.error]
        report = check_faithfulness(text, evidence, question=question, extra_sources=errors or None)
        warnings: list[str] = []
        repaired = False
        if not report.passed:
            log.info("faithfulness failed, repairing: %s", report.unsupported_texts)
            messages += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": report.repair_instruction(lang)},
            ]
            with _span("nabiz.model", **{"nabiz.repair": True}):
                response = await llm.chat(self.config, messages)
            steps += 1
            _merge_usage(usage, response.get("usage"))
            retry = (response.get("content") or "").strip()
            if retry:
                repaired, text = True, retry
                report = check_faithfulness(text, evidence, question=question, extra_sources=errors or None)
            if not report.passed:
                warnings.append(
                    "Sayısal sadakat denetimi geçilemedi; şu sayılar araç sonuçlarında yok: "
                    + ", ".join(report.unsupported_texts)
                )
        return AgentAnswer(
            text=text,
            tool_calls=calls,
            citations=_citations(calls),
            faithfulness=report,
            mode="llm",
            lang=lang,
            steps=steps,
            repaired=repaired,
            warnings=warnings,
            usage=usage,
            model=model_name or self.config.model,
            messages=messages,
        )

    # -- tool execution -----------------------------------------------------------
    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> ToolCallRecord:
        """Run one tool. A tool never raises out of here; a failure is data for the model."""
        started = time.perf_counter()
        arguments = dict(arguments or {})
        error: str | None = None
        payload: dict[str, Any] | None = None
        with _span("nabiz.tool", **{"nabiz.tool": name}):
            if name not in TOOL_DESCRIPTIONS:
                error = f"Bilinmeyen araç: {name}. Kullanılabilir araçlar: {', '.join(TOOL_DESCRIPTIONS)}."
            else:
                try:
                    result: ToolResult = await getattr(self.nabiz, name)(**arguments)
                    payload = _payload(result)
                except (ValueError, TypeError) as exc:
                    error = str(exc)
                except RateLimitExceeded as exc:
                    error = f"İstek bütçesi doldu: {exc}"
                except UpstreamUnavailable as exc:
                    error = f"İBB servisi şu anda yanıt vermiyor: {exc}"
                except Exception as exc:  # noqa: BLE001 - a tool must never end the turn
                    log.exception("tool %s failed", name)
                    error = f"Beklenmeyen hata: {type(exc).__name__}"
        return ToolCallRecord(
            name=name,
            arguments=arguments,
            ok=error is None,
            payload=payload,
            error=error,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    # -- deterministic path -------------------------------------------------------
    def route(self, question: str) -> tuple[str, dict[str, Any]]:
        """Pick one tool by keyword. The whole of "no LLM" mode's intelligence lives here."""
        text = normalize_tr(question)
        place = self._find_place(question)
        if _has(text, "air"):
            if not place:
                return "", _NEEDS_PLACE_REASON
            return ("air_quality_forecast" if _has(text, "window") else "air_quality_now"), {"place": place}
        if _has(text, "station") and place and not _has(text, "stop"):
            return "metro_station_info", {"name": place}
        # A bus line code outranks the word "metro": "500T 4. Levent metroya ne zaman
        # gelir" is a bus question whose destination happens to be a metro station.
        line_code = self._bus_line(question)
        if line_code and (_has(text, "arrival") or _has(text, "stop")):
            stop = self._stop_name(question) or place or ""
            if stop:
                return "iett_next_arrivals", {"line_code": line_code, "stop": stop}
        if _has(text, "metro") or _METRO_LINE_RE.search(question):
            line = _METRO_LINE_RE.search(question)
            return "metro_status", {"line": line.group(1).upper() if line else None}
        if _has(text, "parking"):
            if not place:
                return "", _NEEDS_PLACE_REASON
            return "ispark_find_parking", {"place": place}
        if line_code:
            return "iett_line_buses", {"line_code": line_code}
        if _has(text, "stop"):
            return "iett_stops_search", {"query": self._stop_name(question) or place or question}
        if _has(text, "traffic"):
            return "traffic_index", {"window": "24h" if "dun" in text or "yesterday" in text else "now"}
        if _has(text, "fresh"):
            return "city_freshness", {}
        if place:
            return "places_resolve", {"query": place}
        # Nothing matched and no place was named. Answering "how old is the data?" to
        # "how do I get to the airport?" is not a fallback, it is a non sequitur dressed
        # up as an answer; say what this agent can and cannot do instead.
        return "", _OUT_OF_SCOPE_REASON

    def _find_place(self, question: str) -> str | None:
        """Longest gazetteer name contained in the question, suffixes and all.

        ``PlaceIndex.resolve`` scores a *query*; here the place is buried inside a sentence
        and glued to Turkish case endings ("Taksim'e", "Kadıköy'den"), so a containment
        scan over the normalised gazetteer is the reliable move.
        """
        haystack = f" {normalize_tr(question)} "
        best: tuple[int, str] | None = None
        for place in self.nabiz.places.places:
            needle = normalize_tr(place.name)
            if len(needle) < 4 or needle not in haystack:
                continue
            if best is None or len(needle) > best[0]:
                best = (len(needle), place.name)
        return best[1] if best else None

    @staticmethod
    def _bus_line(question: str) -> str | None:
        match = _BUS_LINE_RE.search(question.upper())
        if match and not _METRO_LINE_RE.fullmatch(match.group(1)):
            return match.group(1)
        numeric = _BUS_NUMBER_RE.search(question)
        return numeric.group(1) if numeric else None

    @staticmethod
    def _stop_name(question: str) -> str | None:
        """The stop named before "durağı", with the line that precedes it stripped off.

        "500T otobüsü 4. Levent durağı" names *one* stop. The lazy capture reaches back to
        the start of the sentence, so without this the line code and the word introducing
        it are handed to the stop search, which then finds nothing at all — the question
        fails for a reason that has nothing to do with the data.
        """
        match = _STOP_RE.search(question)
        if not match:
            return None
        words = match.group(1).strip().split()
        while words and _is_line_or_filler(words[0]):
            words.pop(0)
        return " ".join(words[-3:]) if words else None

    async def _ask_deterministic(self, question: str, lang: str) -> AgentAnswer:
        """Route to one tool and render a template. No model, no free-form generation."""
        tool, arguments = self.route(question)
        if not tool:
            # Routed nowhere on purpose: either the question needs a place and named none
            # (guessing one would answer about a district the user never mentioned), or no
            # tool covers it at all.
            message = (_OUT_OF_SCOPE if arguments.get("reason") == "scope" else _NEED_PLACE)[lang]
            return AgentAnswer(
                text=message,
                faithfulness=check_faithfulness(message, None, question=question),
                mode="deterministic",
                lang=lang,
                warnings=[_DETERMINISTIC_NOTE[lang]],
            )
        with _span("nabiz.deterministic", **{"nabiz.tool": tool}):
            record = await self._call_tool(tool, arguments)
        if record.ok and record.payload is not None:
            text = _render(tool, record.payload, lang)
        else:
            text = f"{record.error}\n\n{ATTRIBUTION_LINE}" if record.error else _NO_DATA[lang]
        # The error is relayed verbatim, so its own numbers ("bu durağa uğrayan hatlar:
        # 153, 154 …") came from the tool and are not this agent's invention.
        report = check_faithfulness(text, [record.payload], question=question, extra_sources=record.error)
        warnings = [_DETERMINISTIC_NOTE[lang]]
        if not report.passed:
            # A template is hand-written Turkish, so a numeric constant can creep into one
            # and then no number in it came from the payload. The model path warns when the
            # check fails; this path must warn too, or a failed check is invisible here.
            warnings.append(
                "Sayısal sadakat denetimi geçilemedi; şu sayılar araç sonuçlarında yok: "
                + ", ".join(report.unsupported_texts)
            )
        return AgentAnswer(
            text=text,
            tool_calls=[record],
            citations=_citations([record]),
            faithfulness=report,
            mode="deterministic",
            lang=lang,
            steps=1,
            warnings=warnings,
            model=None,
        )


def _assistant_message(content: str | None, calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {
                "id": call["id"],
                "type": "function",
                "function": {"name": call["name"], "arguments": json.dumps(call["arguments"], ensure_ascii=False)},
            }
            for call in calls
        ],
    }


def _merge_usage(total: dict[str, Any], usage: Any) -> None:
    for key, value in (usage or {}).items():
        if isinstance(value, (int, float)):
            total[key] = total.get(key, 0) + value


def _citations(calls: list[ToolCallRecord]) -> list[dict[str, Any]]:
    """One entry per distinct source reading, so the UI can print "İSPARK · 8 dk önce"."""
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for call in calls:
        if not call.payload:
            continue
        provenance = call.payload["provenance"]
        as_of = provenance.get("reported_at") or provenance["observed_at"]
        key = (provenance["source"], str(as_of))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "tool": call.name,
                "source": provenance["source"],
                "source_url": provenance["source_url"],
                "as_of": as_of,
                "age": provenance["age"],
                "stale": provenance["stale"],
                "license": provenance["license"],
            }
        )
    return out


# --------------------------------------------------------------------------------------
# Deterministic templates. Turkish only, by design: this is the no-quota fallback for a
# Turkish city demo, and a hand-written English branch for every phrase would double the
# surface without adding a single fact. An English question gets one English line saying
# the templated fallback answers in Turkish, so the language rule is broken openly rather
# than silently. Every number printed below is read straight out of the tool payload —
# nothing is derived — so a rendered answer passes the same faithfulness check the model's
# prose has to pass.
# --------------------------------------------------------------------------------------
ATTRIBUTION_LINE = "Kaynak: İBB Açık Veri (CC BY 4.0) · resmî bir servis değildir."
_EN_PREFACE = "(No language model is configured, so this fallback answers in Turkish.)"
_DETERMINISTIC_NOTE = {
    "tr": "LLM yapılandırılmadığı için deterministic mod kullanıldı: soru anahtar kelimeyle tek bir araca yönlendirildi.",
    "en": "No LLM configured, so deterministic mode answered: the question was keyword-routed to a single tool.",
}
_NO_DATA = {"tr": "Bu soruya verecek veri bulunamadı.", "en": "No data available for this question."}
_NEED_PLACE = {
    "tr": "Hangi semt ya da ilçe için bakayım? (örnek: Taksim, Kadıköy, Beşiktaş)",
    "en": "Which district should I look at? (for example Taksim, Kadıköy, Beşiktaş)",
}
_OUT_OF_SCOPE = {
    "tr": "Bu soruyu elimdeki verilerle yanıtlayamıyorum. Otopark, otobüs, metro, trafik, "
    "hava kalitesi ve veri tazeliği sorabilirsin.",
    "en": "I cannot answer that from the data I have. Ask about parking, buses, metro, "
    "traffic, air quality or data freshness.",
}
#: Why :meth:`NabizAgent.route` declined to pick a tool. Carried in the (unused) argument
#: slot so the caller can say which of the two refusals it is without a second signature.
_NEEDS_PLACE_REASON = {"reason": "place"}
_OUT_OF_SCOPE_REASON = {"reason": "scope"}
_FORCE_PROSE = {
    "tr": "Adım bütçesi doldu. Elindeki araç sonuçlarıyla, yeni araç çağırmadan cevabı şimdi yaz.",
    "en": "The step budget is spent. Write the answer now from the tool results you already have.",
}
_YES_NO = {True: "var", False: "yok"}


def _r_parking(d: dict[str, Any]) -> list[str]:
    parks = d.get("parks") or []
    if not parks:
        return [f"{d.get('near')} çevresinde boş yeri olan otopark bulunamadı."]
    lines = [f"{d.get('near')} çevresinde {_num(d.get('radius_km'))} km içinde {d.get('count')} otopark bulundu:"]
    for park in parks[:3]:
        bits = [str(park.get("name", ""))]
        if park.get("empty") is not None:
            bits.append(f"{park['empty']} boş yer")
        if park.get("capacity"):
            bits.append(f"{park['capacity']} kapasite")
        if park.get("distance_km") is not None:
            bits.append(f"{_num(park['distance_km'])} km")
        if park.get("tariff"):
            bits.append(str(park["tariff"]))
        lines.append("• " + " · ".join(bits))
    return lines


def _r_arrivals(d: dict[str, Any]) -> list[str]:
    stop = (d.get("stop") or {}).get("name") or (d.get("stop") or {}).get("stop_code", "")
    line_code = d.get("line_code", "")
    arrivals = d.get("arrivals") or []
    if not arrivals:
        return [f"{line_code} hattında {stop} durağına yaklaşan araç görünmüyor."]
    lines = [f"{line_code} hattının {stop} durağına tahmini varışı (TAHMİNDİR, resmî İETT bilgisi değildir):"]
    for arrival in arrivals:
        bits = []
        if arrival.get("eta_minutes") is not None:
            bits.append(f"~{_num(arrival['eta_minutes'])} dakika")
        if arrival.get("stops_away") is not None:
            bits.append(f"{arrival['stops_away']} durak uzakta")
        bits += [f"yöntem: {arrival.get('method')}", f"güven: {arrival.get('confidence')}"]
        lines.append("• " + " · ".join(bits))
    return lines


def _r_metro_status(d: dict[str, Any]) -> list[str]:
    statuses = d.get("lines") or []
    if not statuses:
        return ["Metro hatlarında bildirilmiş bir arıza veya çalışma duyurusu yok."]
    return [f"{d.get('count')} hat için duyuru var:"] + [
        f"• {status.get('line_name') or ''}: {status.get('description') or ''}".strip() for status in statuses[:5]
    ]


def _r_station(d: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for station in (d.get("stations") or [])[:3]:
        head = f"{station.get('name')} ({station.get('line_name')})"
        if station.get("order") is not None:
            head += f", hat sırası {station['order']}"
        lines.append(head)
        facts = []
        if station.get("lifts") is not None:
            facts.append(f"asansör: {station['lifts']}")
        if station.get("escalators") is not None:
            facts.append(f"yürüyen merdiven: {station['escalators']}")
        for key, label in (("wc", "WC"), ("baby_room", "bebek bakım odası"), ("masjid", "mescit")):
            if station.get(key) is not None:
                facts.append(f"{label}: {_YES_NO[bool(station[key])]}")
        if facts:
            lines.append("• " + " · ".join(facts))
    return lines


def _r_air_now(d: dict[str, Any]) -> list[str]:
    station, reading = d.get("station") or {}, d.get("reading") or {}
    lines = [f"{d.get('place')} için en yakın ölçüm istasyonu: {station.get('name')}."]
    facts = []
    if reading.get("aqi_index") is not None:
        band = (d.get("band") or {}).get("label")
        facts.append(f"AQI {_num(reading['aqi_index'])}" + (f" ({band})" if band else ""))
    for key in ("pm10", "so2", "o3", "no2"):
        if reading.get(key) is not None:
            facts.append(f"{key.upper()} {_num(reading[key])} µg/m³")
    if reading.get("dominant"):
        facts.append(f"baskın kirletici: {reading['dominant']}")
    if facts:
        lines.append("• " + " · ".join(facts))
    lines.append(
        "Sağlık tavsiyesi değildir; sağlık kararları için hekiminize ve resmî sağlık otoritelerine başvurun. "
        "İBB API'sinde PM2.5 ölçümü yoktur."
    )
    return lines


def _r_air_forecast(d: dict[str, Any]) -> list[str]:
    if not d.get("available"):
        return [f"{d.get('place')} için saatlik PM10 tahmini üretilemedi."]
    station = (d.get("station") or {}).get("name")
    lines = [f"{d.get('place')} · {station} istasyonu, {d.get('horizon_hours')} saatlik PM10 görünümü:"]
    lines += [f"• {item.get('at')} — PM10 {_num(item.get('pm10'))} µg/m³" for item in (d.get("forecast") or [])[:6]]
    if best := d.get("best_window"):
        lines.append(f"En temiz saat: {best.get('at')} (PM10 {_num(best.get('pm10'))} µg/m³).")
    lines.append("Sağlık tavsiyesi değildir.")
    return lines


def _r_traffic(d: dict[str, Any]) -> list[str]:
    if d.get("index") is not None:
        return [f"İstanbul trafik yoğunluk indeksi: {_num(d['index'])} ({d.get('description')})."]
    lines = [str(d.get("description") or "")]
    if d.get("now") is not None:
        lines.append(f"Şu an: {_num(d['now'])}")
    if d.get("same_hour_yesterday") is not None:
        lines.append(f"Dün aynı saat: {_num(d['same_hour_yesterday'])}")
    return lines


def _r_line_buses(d: dict[str, Any]) -> list[str]:
    directions = ", ".join(d.get("directions") or [])
    head = f"{d.get('line_code')} hattında konum bildiren {d.get('count')} araç var"
    return [
        head + (f" (yönler: {directions})." if directions else "."),
        "Araç plakası paylaşılmaz; araçlar kapı numarasıyla anılır.",
    ]


def _r_stops(d: dict[str, Any]) -> list[str]:
    stops = d.get("stops") or []
    if not stops:
        return [f"'{d.get('query')}' için durak bulunamadı."]
    return [f"'{d.get('query')}' için {d.get('count')} durak:"] + [
        f"• {stop.get('name')} ({stop.get('stop_code')})" for stop in stops[:5]
    ]


def _r_places(d: dict[str, Any]) -> list[str]:
    matches = d.get("matches") or []
    if not matches:
        return [f"'{d.get('query')}' için yer bulunamadı."]
    return [f"• {m.get('label')} — {_num(m.get('lat'), 4)}, {_num(m.get('lon'), 4)}" for m in matches[:3]]


def _r_freshness(d: dict[str, Any]) -> list[str]:
    sources = d.get("sources") or {}
    if not sources:
        return ["Henüz hiçbir kaynak sorgulanmadı."]
    lines = ["Kaynak tazeliği:"]
    for name, entry in list(sources.items())[:8]:
        age = entry.get("age_seconds") if isinstance(entry, dict) else None
        detail = entry.get("detail") if isinstance(entry, dict) else entry
        lines.append(f"• {name}: " + (f"{_num(age)} saniye önce" if age is not None else str(detail or "")))
    return lines


def _r_generic(d: dict[str, Any]) -> list[str]:
    """Fallback: state availability and let the tool's own note carry the detail."""
    if isinstance(d, dict) and d.get("available") is False:
        return ["Bu bilgi için yeterli veri yok."]
    return ["Araç sonucu aşağıdadır."]


_RENDERERS = {
    "ispark_find_parking": _r_parking,
    "iett_next_arrivals": _r_arrivals,
    "metro_status": _r_metro_status,
    "metro_station_info": _r_station,
    "air_quality_now": _r_air_now,
    "air_quality_forecast": _r_air_forecast,
    "traffic_index": _r_traffic,
    "iett_line_buses": _r_line_buses,
    "iett_stops_search": _r_stops,
    "places_resolve": _r_places,
    "city_freshness": _r_freshness,
}


def _render(tool: str, payload: dict[str, Any], lang: str) -> str:
    """Turn one tool payload into a templated answer carrying its age and attribution."""
    lines = [_EN_PREFACE] if lang == "en" else []
    lines += _RENDERERS.get(tool, _r_generic)(payload.get("data") or {})
    if payload.get("note"):
        lines.append(str(payload["note"]))
    lines.append(f"Verinin yaşı: {payload['provenance']['age']}.")
    lines.append(ATTRIBUTION_LINE)
    return "\n".join(line for line in lines if line)
