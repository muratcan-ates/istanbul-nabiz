"""The console port bound to ``nexus_core``: the simulated operator's queue, cards and ledger.

:class:`NexusConsole` is what ``/api/console/*`` calls once the app is wired
(:mod:`nabiz.console.wiring`). It owns three things the decision core leaves to its caller:

* **Feeding it.** :meth:`NexusConsole.ingest` reads the Metro equipment snapshot and the city
  watch through the shared facade (:mod:`nabiz.console.signals`) and hands each signal to the
  engine. It runs when the queue is read, at most once per ``ingest_every_s``, so the page's
  refresh never turns into more upstream calls than the cache already allows.
* **Not re-queueing the same outage.** A fault stays in İBB's list for days and every snapshot
  of it is a new signal. One that is already waiting for a person (or deferred: it stays in the
  queue, decidable), or that a rule closed or a person rejected within :data:`QUIET_S`, is not
  handed over again (:func:`already_on_board`). An approved step-free alternative is: the next
  snapshot is exactly what the approved-alternative check (OA) needs. Any other approval
  published a one-off text; the same outage or alert is asked about again only after
  :data:`APPROVED_QUIET_S`, not at every read.
* **Not holding the page.** The sources and the Arena's model calls can take tens of seconds;
  a queue read waits at most :data:`QUEUE_WAIT_S` for them and answers with what is sealed so
  far (``reading_sources`` tells the page to look again soon).
* **Speaking the API contract.** The core's views give the queue, the card, the stats and the
  drafts; this module adds what the page reads beside them (the signal's title and status on
  the card, a card for a reflex-closed signal, a sentence per ledger step).

The engine is synchronous (SQLite, and possibly a model call in the Arena), so every call that
can process or decide runs in a worker thread and the event loop keeps serving pages.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import logging
import time
from collections.abc import Callable, Iterable
from typing import Any

from ibb_mcp.tools import Nabiz
from nabiz.console.ports import OPERATOR, PortConflict
from nabiz.console.signals import CITY_WATCH, Incoming, alert_incoming, equipment_incoming
from nexus_core import Approval, DecisionConflict, NexusEngine, Operator
from nexus_core.approved import BOUND_ACTION
from nexus_core.arena import assess_confidence, uncertainty_codes
from nexus_core.engine import default_evidence
from nexus_core.router import REASON_TEXT
from nexus_core.signals import system_clock
from nexus_core.state import SignalState
from nexus_core.views import decision_payload, drafts_payload, queue_item, queue_payload, stats_payload

log = logging.getLogger("nabiz.console.nexus")

#: After a rule closed it or a person rejected it, the same outage waits this long before a new
#: snapshot of it is handed to the core again. A design parameter, not a measured value.
QUIET_S = 3600
#: After a person approved a one-off text for it, the same outage or alert is asked about again
#: after this long (a day): a reminder that it is still there, not a card every five minutes.
#: A design parameter, not a measured value.
APPROVED_QUIET_S = 24 * 3600
#: How long a queue read waits for the sources and the Arena before answering with what it has.
QUEUE_WAIT_S = 8.0
DEFAULT_INGEST_EVERY_S = 300
OPEN = frozenset({"awaiting_approval", "deferred"})
SETTLED_QUIET = frozenset({"closed_by_reflex", "rejected"})

#: Recorded replays the console offers (``POST /api/console/simulate``).
SIMULATIONS = ("metro_faulty_kartal", "metro_equipment", "city_watch")
NO_RECORDING = "Kayıtlı Metro arıza verisi yok; oynatılacak sinyal bulunamadı."
#: What the server log says instead: the page is no place for a command line.
NO_RECORDING_LOG = "no Metro equipment recording; the owner records one with scripts/capture_metro_equipment.py --live"

ACTION_TR = {"approve": "Onaylandı", "edit": "Düzenlenerek onaylandı", "reject": "Reddedildi", "defer": "Ertelendi"}
KIND_TR = {
    "equipment_fault": "ekipman arızası", "long_outage": "uzun süren arıza", "hub_faults": "aktarma merkezinde arızalar",
    "source_stale": "bayat kaynak", "parking_full": "otopark doluluğu", "air_quality": "hava kalitesi",
    "bus_bunching": "otobüs yığılması",
}  # fmt: skip
LEVEL_TR = {"high": "yüksek", "medium": "orta", "low": "düşük"}
MODE_TR = {"live": "canlı", "recorded": "kayıtlı", "schedule": "tarife", "unknown": "bilinmiyor"}
SOURCE_TR = {
    "metro_equipment": "Metro İstanbul arıza kaydı", "Metro İstanbul": "Metro İstanbul arıza kaydı", "ispark": "İSPARK",
    "aq_readings": "İBB hava kalitesi", "traffic": "İBB trafik indeksi", "iett": "İETT", "nabiz_alerts": "Nabız uyarıları",
}  # fmt: skip


def board_key(state_or_incoming: SignalState | Incoming) -> tuple[str, str, str | None]:
    """The outage or alert a signal is about: its ``outage_id``, its alert key, or its fault list."""
    signal = state_or_incoming.signal
    outage = signal.payload.get("outage_id") or signal.payload.get("dedupe_key")
    if not isinstance(outage, str) and isinstance(listing := signal.payload.get("equipment_list"), str):
        # A hub's faults have no single outage: the same list of faults is the same event.
        outage = "list:" + hashlib.sha256(listing.encode("utf-8")).hexdigest()[:16]
    return signal.kind, signal.entity_id, outage if isinstance(outage, str) else None


def _quiet_for(state: SignalState) -> float | None:
    """How long a settled card keeps new snapshots of its event away; ``None``: it does not."""
    if state.status in SETTLED_QUIET:
        return QUIET_S
    if state.status == "approved" and state.decision is not None and state.decision.proposed_action.kind != BOUND_ACTION:
        return APPROVED_QUIET_S
    return None


def already_on_board(index: dict[tuple[str, str, str | None], list[SignalState]], incoming: Incoming, now: dt.datetime) -> bool:
    """The same outage is waiting for a person, or was settled a while ago: do not hand it over again."""
    states = index.get(board_key(incoming), [])
    if any(s.status in OPEN for s in states):
        return True
    latest = max(states, key=lambda s: s.received_at, default=None)
    quiet = _quiet_for(latest) if latest is not None else None
    if latest is None or quiet is None:
        return False
    settled = latest.rulings[-1].at if latest.rulings else latest.received_at
    return (now - settled).total_seconds() < quiet


def _index(states: Iterable[SignalState]) -> dict[tuple[str, str, str | None], list[SignalState]]:
    index: dict[tuple[str, str, str | None], list[SignalState]] = {}
    for state in states:
        index.setdefault(board_key(state), []).append(state)
    return index


def _reasons(detail: dict[str, Any]) -> str:
    return "; ".join(REASON_TEXT.get(r, r) for r in detail.get("reasons") or []) or "kural yolu"


def describe_step(kind: str, detail: dict[str, Any]) -> str:  # noqa: PLR0911 - one sentence per ledger entry kind
    """One Turkish sentence per ledger step, for the "bu karar nasıl verildi?" screen."""
    if kind == "signal_received":
        signal = detail.get("signal") or {}
        origin = signal.get("provenance") or {}
        payload = signal.get("payload") or {}
        where = payload.get("station") or payload.get("hub")
        what = KIND_TR.get(str(signal.get("kind")), "sinyal") + (f" · {where}" if where else "")
        mode = MODE_TR.get(str(origin.get("mode")), "bilinmiyor")
        source = SOURCE_TR.get(str(origin.get("source")), origin.get("source"))
        return f"Sinyal alındı: {what} (kaynak: {source}, {mode} veri)."
    if kind == "routed":
        path = "refleks" if detail.get("path") == "reflex" else "insan onayı (Arena)"
        rule = detail.get("rule_id") or "kural yok"
        return f"Yönlendirildi: {path}; {rule}; gerekçe: {_reasons(detail)}."
    if kind == "reflex_closed":
        card = (detail.get("action") or {}).get("card") or {}
        return f"Kural kapattı ({detail.get('elapsed_ms')} ms): {card.get('body', '')}"
    if kind == "reflex_failed":
        return f"Kural çalışamadı ({detail.get('rule_id')}): {detail.get('failure')}. İnsana gönderildi."
    if kind == "arena_drafted":
        decision = detail.get("decision") or {}
        level = LEVEL_TR.get(str((decision.get("confidence") or {}).get("level")), "bilinmiyor")
        text = (decision.get("proposed_action") or {}).get("text", "")
        return f"Arena kartı hazırladı ({decision.get('arena_label')}); güven: {level}. Öneri: {text}"
    if kind == "approval":
        action = ACTION_TR.get(detail.get("action", ""), detail.get("action", ""))
        reason = (detail.get("reason") or "gerekçe yazılmadı").rstrip(". ")
        published = detail.get("published_text")
        return f"{action}. Gerekçe: {reason}." + (f" Yayımlanan metin: {published}" if published else "")
    return kind


def titled(title: str, state: SignalState) -> str:
    """The kind's title with the place it is about: "Uzun süren arıza · Kartal"."""
    payload = state.signal.payload
    where = payload.get("station") or payload.get("hub")
    return f"{title} · {where}" if isinstance(where, str) and where else title


def reflex_card(state: SignalState, now: dt.datetime, stale_after_s: int) -> dict[str, Any]:
    """A card for a signal a rule closed: what the rule published, on what evidence. Nothing to decide."""
    evidence = default_evidence(state.signal)
    confidence = assess_confidence(uncertainty_codes(evidence, [], now, stale_after_s))
    card = state.action.card if state.action else None
    return {
        "signal_id": state.signal.signal_id,
        "signal": state.signal.model_dump(mode="json"),
        "status": state.status,
        "reasons": list(state.reasons),
        "evidence": [{"text": e.text, "provenance": e.provenance.as_provenance(now)} for e in evidence],
        "freshness_s": state.signal.provenance.age_s(now),
        "alternatives": [],
        "opinions": [],
        "dissent_summary": "",
        "proposed_action": {
            "kind": state.action.kind if state.action else "publish_card",
            "text": card.body if card else (state.reflex_failure or ""),
            "expires_at": None,
        },
        "confidence": {"level": confidence.level, "reasons": list(confidence.reasons)},
        "author": "kural",
        "arena_label": f"Kural {state.rule_id} refleksle kapattı; insan kararı gerekmedi" if state.rule_id else "Refleks",
    }


class NexusConsole:
    """:class:`~nabiz.console.ports.ConsolePort` over one :class:`~nexus_core.NexusEngine`."""

    def __init__(
        self,
        engine: NexusEngine,
        nabiz: Nabiz,
        *,
        recorded: Callable[[], Nabiz],
        offline: bool,
        ingest_every_s: int = DEFAULT_INGEST_EVERY_S,
        clock: Callable[[], dt.datetime] = system_clock,
    ) -> None:
        self.engine = engine
        self.nabiz = nabiz
        self._recorded = recorded
        self.offline = offline
        self.ingest_every_s = ingest_every_s
        self._clock = clock
        self._last_ingest: float | None = None
        self._ingest_lock = asyncio.Lock()
        self._ingest_task: asyncio.Task[list[str]] | None = None
        self.queue_wait_s = QUEUE_WAIT_S

    # ------------------------------------------------------------------ feeding the core
    def _process_all(self, incoming: list[Incoming]) -> list[str]:
        now = self._clock()
        index = _index(self.engine.states().values())
        taken: list[str] = []
        for one in incoming:
            if already_on_board(index, one, now):
                continue
            try:
                result = self.engine.process(one.signal, evidence=one.evidence)
            except Exception as exc:  # noqa: BLE001 - one bad signal must not stop the batch
                log.error("signal %s not processed: %s", one.signal.kind, type(exc).__name__)
                continue
            taken.append(result.signal_id)
            state = self.engine.states().get(result.signal_id)
            if state is not None:
                index.setdefault(board_key(state), []).append(state)
        return taken

    async def _read_sources(self, nabiz: Nabiz) -> list[Incoming]:
        incoming: list[Incoming] = []
        try:
            incoming += equipment_incoming(await nabiz.metro_equipment_signals())
        except Exception as exc:  # noqa: BLE001 - one dead source must not stop the other
            log.warning("equipment signals unavailable: %s", type(exc).__name__)
        try:
            incoming += alert_incoming(await nabiz.check_alerts(CITY_WATCH), offline=nabiz.settings.offline)
        except Exception as exc:  # noqa: BLE001
            log.warning("city watch unavailable: %s", type(exc).__name__)
        return incoming

    async def ingest(self, *, force: bool = False) -> list[str]:
        """Read the sources and hand new signals to the core; throttled unless ``force``."""
        if not force and self.ingest_every_s <= 0:
            return []
        async with self._ingest_lock:
            due = self._last_ingest is None or time.monotonic() - self._last_ingest >= self.ingest_every_s
            if not (force or due):
                return []
            self._last_ingest = time.monotonic()
            incoming = await self._read_sources(self.nabiz)
            return await asyncio.to_thread(self._process_all, incoming)

    async def _read_in_background(self) -> bool:
        """Start a read of the sources if none runs; wait for it a bounded time. True while it still runs."""
        if self._ingest_task is None or self._ingest_task.done():
            self._ingest_task = asyncio.create_task(self.ingest())
            self._ingest_task.add_done_callback(_log_failure)
        await asyncio.wait({self._ingest_task}, timeout=self.queue_wait_s)
        return not self._ingest_task.done()

    # ------------------------------------------------------------------ the port
    async def queue(self) -> dict[str, Any]:
        reading = await self._read_in_background()
        states = self.engine.states()
        payload = queue_payload(states.values())
        for item in payload["items"]:
            item["title"] = titled(item["title"], states[item["signal_id"]])
            item["operator_summary"] = states[item["signal_id"]].signal.payload.get("operator_text", item["summary"])
        payload["reading_sources"] = reading
        return payload

    def _state(self, signal_id: str) -> SignalState:
        state = self.engine.states().get(signal_id)
        if state is None:
            raise KeyError(signal_id)
        return state

    async def decision(self, signal_id: str) -> dict[str, Any]:
        state, now = self._state(signal_id), self._clock()
        body = reflex_card(state, now, self.engine.stale_after_s) if state.decision is None else decision_payload(state, now)
        # The page reads the queue row's fields (title, status, summary, time) on the card's signal.
        row = queue_item(state) or {}
        body["signal"] = {**body["signal"], **row, "title": titled(row.get("title", state.signal.title), state)}
        return body

    async def decide(self, signal_id: str, *, action: str, reason: str, edited_text: str | None, actor: str) -> dict[str, Any]:
        if actor != OPERATOR:
            raise ValueError("Yalnız simüle operatör karar verebilir.")
        approval = Approval(signal_id=signal_id, action=action, reason=reason, edited_text=edited_text, actor=Operator())
        try:
            receipt = await asyncio.to_thread(self.engine.decide, approval)
        except DecisionConflict as exc:
            raise PortConflict("Bu kart zaten sonuçlanmış.") from exc
        return {"status": receipt.status, "ledger_entry_id": receipt.ledger_entry_id, "published_text": receipt.published_text}

    async def trace(self, signal_id: str) -> dict[str, Any]:
        self._state(signal_id)
        trace = self.engine.trace(signal_id)
        steps = [
            {"at": s.at.isoformat(), "actor": s.actor, "kind": s.kind, "detail": describe_step(s.kind, s.detail)}
            for s in trace.steps
        ]
        return {"steps": steps, "hash_ok": trace.hash_ok}

    async def verify(self) -> dict[str, Any]:
        result = self.engine.verify()
        return {"ok": result.ok, "entries": result.entries, "head": result.head, "first_bad_id": result.first_bad_id}

    async def stats(self) -> dict[str, Any]:
        return stats_payload(self.engine.stats())

    async def rule_drafts(self) -> dict[str, Any]:
        return drafts_payload(self.engine.drafts.drafts())

    async def adopt_rule(self, draft_id: str, *, reason: str, actor: str) -> dict[str, Any]:
        if actor != OPERATOR:
            raise ValueError("Yalnız simüle operatör kural benimseyebilir.")
        adopted = await asyncio.to_thread(self.engine.drafts.adopt, draft_id, reason, Operator())
        return {"rule_id": adopted.rule_id, "expires_at": adopted.expires_at.isoformat()}

    async def simulate(self, fixture: str) -> dict[str, Any]:
        """Replay one recorded signal (never live data, never a made-up one) through the core."""
        if fixture not in SIMULATIONS:
            raise ValueError(f"Bilinmeyen kayıt: {fixture}. Bilinenler: {', '.join(SIMULATIONS)}.")
        recorded = self._recorded()
        if fixture == "city_watch":
            incoming = await self._read_sources(recorded)
            incoming = [one for one in incoming if one.signal.entity_id.startswith("alert:")]
        else:
            incoming = equipment_incoming(await recorded.metro_equipment_signals())
        chosen = pick_replay(incoming, fixture)
        if chosen is None:
            if fixture != "city_watch":
                log.warning(NO_RECORDING_LOG)
            raise PortConflict(NO_RECORDING if fixture != "city_watch" else "Kayıtlı veride şehir uyarısı yok.")
        result = await asyncio.to_thread(self.engine.process, chosen.signal, chosen.evidence)
        return {"signal_id": result.signal_id, "status": result.status, "path": result.path, "duplicate": result.duplicate}


def _log_failure(task: asyncio.Task[list[str]]) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.error("reading the sources failed: %s", type(task.exception()).__name__)


def pick_replay(incoming: list[Incoming], fixture: str) -> Incoming | None:
    """The signal a replay plays: Kartal's lift when asked and recorded, else the first lift, else anything."""
    faults = [one for one in incoming if one.signal.kind == "equipment_fault"]
    lifts = [one for one in faults if one.signal.payload.get("equipment_type") == "elevator"]
    if fixture == "metro_faulty_kartal":
        kartal = [one for one in lifts if "kartal" in str(one.signal.payload.get("station", "")).casefold()]
        if kartal:
            return kartal[0]
    with_alternative = [one for one in lifts if one.signal.payload.get("alternative_station")]
    for group in (with_alternative, lifts, faults, incoming):
        if group:
            return group[0]
    return None
