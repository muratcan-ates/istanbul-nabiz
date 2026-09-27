"""Evidence-checked official route cards, kept outside the chat orchestration module."""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import sqlite3
from functools import lru_cache
from typing import Any, Literal
from urllib.parse import urlsplit

from ibb_mcp.knowledge.guardrails import clean_for_display, host_allowed, mask_personal
from ibb_mcp.knowledge.store import KnowledgeStore
from ibb_mcp.text import looks_like_instruction, normalize_tr
from nabiz.agent.templates_i18n import quote_frame
from nabiz.console import chat_pipeline as pipeline
from nabiz.console.agency_router import load_agencies
from nabiz.console.cards import display_text
from nabiz.console.official_intent import agency_and_topic, help_topic, intent
from nabiz.console.policy import names_a_price

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PATHS_FILE = REPO_ROOT / "data" / "official_paths.json"
_THREE_DIGITS = re.compile(r"\d{3,}")
_EMAIL_OR_ID = re.compile(r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b\d{11}\b)")
_ACCOUNT_ACTIONS = frozenset({
    "abonelik", "iptal", "fatura", "borc", "sayac", "randevu", "basvuru", "vize", "kart", "bakiye",
    "kesinti", "odeme", "takip", "sefer",
})


class ReadOnlyKnowledgeStore(KnowledgeStore):
    """Use the retrieval API while opening the supplied index with SQLite mode=ro."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self._fts_available = False
        with self._connect() as db:
            self._fts_available = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks_fts'"
            ).fetchone() is not None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection


@lru_cache(maxsize=1)
def load_paths() -> dict[str, Any]:
    """Load the reviewed route catalog once per process."""
    return json.loads(PATHS_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def _readonly_store(path_text: str) -> ReadOnlyKnowledgeStore:
    return ReadOnlyKnowledgeStore(pathlib.Path(path_text))


def _readonly_store_for(path_text: str) -> ReadOnlyKnowledgeStore | None:
    """A missing index is not cached, so an index built after start-up is still found."""
    if not pathlib.Path(path_text).is_file():
        return None
    try:
        return _readonly_store(path_text)
    except sqlite3.Error:
        return None


def readonly_index() -> tuple[KnowledgeStore | None, None]:
    """Open the configured local index read-only, without loading a .env or embedder."""
    configured = pathlib.Path(os.environ.get("NABIZ_KNOWLEDGE_DB", "data/knowledge/knowledge.db")).expanduser()
    path = configured if configured.is_absolute() else REPO_ROOT / configured
    return _readonly_store_for(str(path.resolve())), None


def _path(path_id: str) -> dict[str, Any] | None:
    return next((item for item in load_paths()["paths"] if item["id"] == path_id), None)


def _matching_path(kind: str, agency: str | None, topic: str | None) -> dict[str, Any] | None:
    paths = load_paths()["paths"]
    if kind == "ferry":
        return next((item for item in paths if item["kind"] == "ferry"), None)
    if kind == "help" and topic:
        return next((item for item in paths if item["kind"] == "help" and item.get("topic") == topic), None)
    if agency and topic:
        exact = next(
            (item for item in paths if item["kind"] == "account" and item["agency"] == agency and topic in item["topics"]),
            None,
        )
        if exact:
            return exact
    if agency:
        return next(
            (item for item in paths if item["kind"] == "account" and item["agency"] == agency and not item["topics"]),
            None,
        )
    return None


def select_path(question: str, kind: str) -> dict[str, Any] | None:
    """Select a topic route first, then an institution default, and finally the general account route."""
    agency, topic = agency_and_topic(question)
    if kind == "help":
        return _matching_path(kind, "ibb", help_topic(question))
    if kind == "ferry":
        return _matching_path(kind, agency, topic)
    if kind == "fallback":
        folded = normalize_tr(question)
        if agency == "sehir_hatlari" and intent(question) == "ferry":
            return _matching_path("ferry", agency, topic)
        if not any(word.startswith(action) for word in folded.split() for action in _ACCOUNT_ACTIONS):
            return None
        if agency is None and help_topic(question) is None:
            return None
        if agency == "sehir_hatlari" and topic == "sefer":
            return _matching_path("ferry", agency, topic)
        return _matching_path("account", agency, topic) or _matching_path("help", "ibb", help_topic(question))
    if kind != "account":
        return None
    selected = _matching_path(kind, agency, topic)
    return selected if selected is not None or agency is not None else _path("ibb")


def _fresh(document: dict[str, Any]) -> bool:
    try:
        limit = int(os.environ.get("NABIZ_KNOWLEDGE_FRESHNESS_SLA_S", "31536000"))
        fetched = dt.datetime.fromisoformat(str(document["fetched_at"]).replace("Z", "+00:00"))
        fetched = fetched if fetched.tzinfo else fetched.replace(tzinfo=dt.UTC)
    except (KeyError, TypeError, ValueError):
        return False
    return (dt.datetime.now(dt.UTC) - fetched.astimezone(dt.UTC)).total_seconds() <= max(0, limit)


def _citation(source: dict[str, Any], agency: dict[str, str], store: KnowledgeStore | None, lang: str) -> dict[str, Any]:
    url = source["url"]
    excerpt = source.get("excerpt")
    host = urlsplit(url).hostname or ""
    document = store.current_document(url) if store is not None and excerpt else None
    body = " ".join(str(document.get("body", "")).split()) if document else ""
    verified = bool(
        document
        and document.get("active") == 1
        and len(excerpt) <= 300
        and excerpt in body
        and host_allowed(host)
        and not looks_like_instruction(excerpt)
        and not names_a_price(excerpt)
        and not _EMAIL_OR_ID.search(excerpt)
        and _fresh(document)
    )
    if not verified:
        return {"source": "local:agencies", "url": url, "title": agency["name"]}
    quote = mask_personal(clean_for_display(excerpt))
    item = {
        "source": "local:knowledge",
        "url": url,
        "title": document["title"],
        "quote": quote,
        "fetched_at": document["fetched_at"],
        "source_updated_at": document.get("source_updated_at"),
        "institution": document["institution"],
    }
    if lang != "tr":
        item.update(quote_frame(lang, quote, url))
    return item


def _lead(kind: str, path: dict[str, Any], agency: dict[str, str], lang: str, *, fallback: bool) -> str:
    if kind == "help" or (fallback and path["kind"] == "help"):
        return (
            "Nabız kimin hangi destekten yararlanabileceğine karar vermez."
            if lang == "tr"
            else "Nabız does not decide who can receive which support."
        )
    if kind == "ferry" or path["kind"] == "ferry":
        return (
            "Sefer saatlerini doğrulayabildiğim bir kaynakta bulamadım. Güncel saatler Şehir Hatlarının resmî sayfasında."
            if lang == "tr"
            else "I could not verify the departure times. The timetable is on Şehir Hatları's official page."
        )
    if fallback:
        name = agency["name"]
        return (
            f"Bu konuda doğrulayabildiğim bir cevap bulamadım. {name} için resmî yol şu:"
            if lang == "tr"
            else f"I could not find an answer I can verify. The official path for {name}:"
        )
    if path["agency"] == "ibb" and agency["name"] == "İBB":
        if lang == "tr":
            return (
                "Nabız hiçbir kurumdaki hesabınızı göremez ve sizin yerinize işlem yapamaz. "
                "Hesabınız hangi kurumdaysa onun resmî kanalını kullanın; emin değilseniz 153'ü arayın."
            )
        return (
            "Nabız cannot see any of your accounts or act on them for you. "
            "Use the official channel of the institution that holds your account; if you are not sure, call 153."
        )
    name, possessive = agency["name"], agency["possessive"]
    return (
        f"Nabız {name} hesabınızı göremez ve sizin yerinize işlem yapamaz. Bunu {possessive} resmî kanallarından yaparsınız."
        if lang == "tr"
        else f"Nabız cannot see your {name} account or act on it for you. You can do this through {name}'s official channels."
    )


def card_events(
    question: str,
    kind: Literal["account", "help", "ferry"],
    turn: pipeline.TurnContext,
    *,
    store: KnowledgeStore | None = None,
    fallback: bool = False,
) -> list[str] | None:
    """Build the fixed, cited final card for an account, help, ferry, or knowledge fallback turn."""
    selected = select_path(question, "fallback" if fallback else kind)
    if selected is None:
        return None
    agencies = load_agencies()["agencies"]
    agency = next((item for item in agencies if item["id"] == selected["agency"]), agencies[0])
    citations = [_citation(source, agency, store, turn.lang) for source in selected["sources"]]
    verified_quotes = [item for item in citations if item["source"] == "local:knowledge"]
    turn.trace.checks["kanit"] = bool(verified_quotes)
    lead = _lead(kind, selected, agency, turn.lang, fallback=fallback)
    if kind == "help" and verified_quotes:
        lead += (
            " Aşağıdaki alıntı İBB'nin resmî sayfasından; koşulları ve başvuruyu resmî yoldan doğrulayın."
            if turn.lang == "tr"
            else (
                " The quote below is from İBB's official page; check the conditions "
                "and how to apply through the official channels."
            )
        )
    lines = [
        f"{item['quote']}\nKaynak: {item['url']} ({item['fetched_at'][:10]})."
        if item["source"] == "local:knowledge"
        else f"Kaynak: {item['url']}."
        for item in citations
    ]
    answer = display_text(lead + ("\n\n" + "\n".join(lines) if lines else ""))
    if stopped := pipeline.output_guard(answer, citations, "kural", turn.started, turn.trace, turn.lang):
        return stopped
    rule_id = "yardim" if kind == "help" and not fallback else "resmi_yol:yedek" if fallback else "resmi_yol"
    how = pipeline.empty_how(turn.started, rule_id=rule_id, trace=turn.trace)
    steps = selected["steps_en" if turn.lang == "en" else "steps_tr"]
    fields = pipeline.FinalFields(refused=False, how=how, mode="answer", steps=steps)
    return pipeline.answer_events(answer, citations, "kural", turn.suggestion, fields)


async def early_events(
    service: Any,
    question: str,
    masked: str,
    kind: Literal["account", "help", "ferry"],
    turn: pipeline.TurnContext,
) -> list[str] | None:
    """Keep direct account/help turns tool-free; ferry first tries the existing knowledge route."""
    store, _ = readonly_index()
    if kind == "ferry":
        if events := await service._from_knowledge(masked, sensitive=False, turn=turn):
            return events
        return card_events(question, kind, turn, store=store, fallback=True)
    return card_events(question, kind, turn, store=store)


def unknown_fallback(
    question: str, found: Any, turn: pipeline.TurnContext, searched: list[str]
) -> list[str] | None:
    """Replace a non-sensitive knowledge unknown with its reviewed route card when one exists."""
    if found.mode != "unknown" or found.refused:
        return None
    store, _ = readonly_index()
    agency, topic = agency_and_topic(question)
    kind: Literal["account", "ferry"] = "ferry" if agency == "sehir_hatlari" and intent(question) == "ferry" else "account"
    card = card_events(question, kind, turn, store=store, fallback=True)
    return searched + card if card else None
