"""Keep a person's reasoned chat decision durable without inventing one on corrupt state.

A pause must be a human decision sealed in the ledger. Treating a damaged file as paused
would silence every citizen without a decision anyone made. Read damage as open, log it,
and let an operator inspect and decide again. Each read reaches disk so workers see the
same state even when another process changed it.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import pathlib
import tempfile
import threading
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from ibb_mcp.config import REPO_ROOT
from nabiz.console.ports import OPERATOR, PortConflict
from nexus_core.decisions import REASON_MAX, Operator
from nexus_core.ledger import EntryKind, Ledger

log = logging.getLogger(__name__)

PAUSE_PATH_ENV = "NABIZ_CHAT_PAUSE_PATH"
DEFAULT_PAUSE_PATH = REPO_ROOT / "data" / "nexus" / "chat_paused.json"
PAUSED_MESSAGE = "Sohbet geçici olarak durduruldu. 153'ü arayabilirsiniz."
HELP_LINE = "153"
STATE_VERSION = 1
CHAT_PAUSE_KIND: str = str(getattr(EntryKind, "CHAT_PAUSED", "chat_pause"))
CHAT_RESUME_KIND: str = str(getattr(EntryKind, "CHAT_RESUMED", "chat_resume"))
CHAT_ENTITY = "service:citizen_chat"
_decision_lock = threading.Lock()


@dataclass(frozen=True)
class ChatPause:
    """The last operator decision; citizen responses expose only its open or paused state."""

    paused: bool = False
    reason: str | None = None
    since: str | None = None
    by_role: str | None = None
    ledger_entry_id: int | None = None

    def operator_view(self) -> dict[str, Any]:
        return {
            "paused": self.paused,
            "reason": self.reason,
            "since": self.since,
            "by_role": self.by_role,
            "ledger_entry_id": self.ledger_entry_id,
        }

    def citizen_view(self) -> dict[str, Any]:
        return {"chat": "paused" if self.paused else "open", "message": PAUSED_MESSAGE if self.paused else None}


def pause_path(env: Mapping[str, str] | None = None) -> pathlib.Path:
    """Use the configured state file, or the repository's ignored runtime path."""
    source = os.environ if env is None else env
    raw = source.get(PAUSE_PATH_ENV, "").strip()
    return pathlib.Path(raw) if raw else DEFAULT_PAUSE_PATH


class PauseStore:
    """Read and atomically replace one chat pause state file."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = pathlib.Path(path)

    def read(self) -> ChatPause:
        """Return open when the file is absent or unreadable; never log its contents."""
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            version = payload.get("version") if isinstance(payload, dict) else None
            if not isinstance(payload, dict) or type(version) is not int or version != STATE_VERSION:
                raise ValueError("unsupported state shape")
            paused = payload["paused"]
            reason, since, by_role = payload["reason"], payload["since"], payload["by_role"]
            entry_id = payload["ledger_entry_id"]
            if type(paused) is not bool:
                raise ValueError("invalid paused value")
            if any(value is not None and not isinstance(value, str) for value in (reason, since, by_role)):
                raise ValueError("invalid text value")
            if entry_id is not None and type(entry_id) is not int:
                raise ValueError("invalid ledger entry id")
            return ChatPause(paused, reason, since, by_role, entry_id)
        except FileNotFoundError:
            return ChatPause()
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            log.warning("chat pause file unreadable (%s); the chat stays open", type(exc).__name__)
            return ChatPause()

    def write(self, state: ChatPause) -> None:
        """Flush a same-directory temporary file before replacing the live state."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        payload = {
            "version": STATE_VERSION,
            "paused": state.paused,
            "reason": state.reason,
            "since": state.since,
            "by_role": state.by_role,
            "ledger_entry_id": state.ledger_entry_id,
        }
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent, prefix=".chat_paused.", suffix=".tmp", delete=False
            ) as handle:
                temporary = handle.name
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            if temporary is not None:
                with suppress(FileNotFoundError):
                    os.unlink(temporary)
            raise


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class SameState(PortConflict):
    """The requested state already matches the saved state."""


def set_chat_pause(
    store: PauseStore,
    ledger: Ledger,
    *,
    paused: bool,
    reason: str,
    by_role: str = OPERATOR,
    actor: str | None = None,
    now: Callable[[], dt.datetime] = _utc_now,
) -> ChatPause:
    """Record the operator's decision first, then publish it to the shared state file."""
    with _decision_lock:
        current = store.read()
        if current.paused == paused:
            message = "Sohbet zaten durdurulmuş." if paused else "Sohbet zaten açık."
            raise SameState(message)
        cleaned = reason.strip()
        if not cleaned:
            raise ValueError("Sohbeti durdurmak ve açmak için gerekçe zorunlu.")
        if len(cleaned) > REASON_MAX:
            raise ValueError(f"Gerekçe en fazla {REASON_MAX} karakter olabilir.")
        kind = CHAT_PAUSE_KIND if paused else CHAT_RESUME_KIND
        entry = ledger.append(
            kind,
            actor=actor or Operator().label,
            entity_id=CHAT_ENTITY,
            detail={
                "kind": "chat_pause",
                "action": "pause" if paused else "resume",
                "paused": paused,
                "reason": cleaned,
                "by_role": by_role,
            },
        )
        timestamp = now()
        timestamp = timestamp.replace(tzinfo=dt.UTC) if timestamp.tzinfo is None else timestamp.astimezone(dt.UTC)
        state = ChatPause(paused, cleaned, timestamp.isoformat(timespec="seconds"), by_role, entry.id)
        store.write(state)
        return state
