"""Where a prepared e-mail goes: a local outbox by default, Azure Communication Services when set up.

* :class:`OutboxEmailSender` (the default) sends nothing. It writes each e-mail as one JSON file
  under ``data/outbox/`` (``NABIZ_OUTBOX_DIR``, gitignored), and Profilim shows the account's own
  files as "Gönderilecek e-posta önizlemesi". Deleting an account deletes its files; files older
  than :data:`OUTBOX_KEEP_DAYS` are removed by the digest run.
* :class:`AcsEmailSender` uses the ``azure-communication-email`` SDK (the optional ``email`` extra,
  imported only when a send happens). It is off unless both ``NABIZ_ACS_CONNECTION_STRING`` and
  ``NABIZ_ACS_SENDER`` are set, and :func:`sender_from_env` returns it only when the caller asks
  for real delivery too. No ACS resource exists yet; creating one, verifying the sender domain and
  the first real send are the owner's steps (DECISIONS #38).

The example sign-in never verifies an address, so the verification e-mail always goes to the
outbox, whatever is configured.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import secrets
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.models import utcnow

DEFAULT_OUTBOX = "data/outbox"
OUTBOX_KEEP_DAYS = 30
NOT_OFFICIAL = "Resmî İBB hizmeti değildir. İstanbul Nabız bağımsız bir öğrenci projesidir."


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str
    kind: str  # "verify" | "digest"
    account_id: str


@dataclass(frozen=True)
class SendResult:
    sender: str
    delivered: bool
    reference: str


class EmailSender(Protocol):
    name: str

    def send(self, email: Email) -> SendResult: ...


def outbox_dir_from_env() -> pathlib.Path:
    path = pathlib.Path(os.environ.get("NABIZ_OUTBOX_DIR") or DEFAULT_OUTBOX).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


class OutboxEmailSender:
    """Writes the e-mail to a file and says plainly that nothing was sent."""

    name = "outbox"

    def __init__(self, directory: str | pathlib.Path) -> None:
        self.directory = pathlib.Path(directory)

    def send(self, email: Email) -> SendResult:
        self.directory.mkdir(parents=True, exist_ok=True)
        now = utcnow()
        reference = f"{now.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(4)}"
        record = {**asdict(email), "id": reference, "created_at": now.isoformat(timespec="microseconds"), "sent": False,
                  "note": "Önizleme: bu e-posta gönderilmedi, yalnız bu sunucunun outbox klasörüne yazıldı."}  # fmt: skip
        (self.directory / f"{reference}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return SendResult(self.name, delivered=False, reference=reference)

    def _records(self) -> list[tuple[pathlib.Path, dict[str, Any]]]:
        if not self.directory.is_dir():
            return []
        found = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                found.append((path, json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError):
                continue
        return found

    def previews(self, account_id: str, limit: int = 5) -> list[dict[str, Any]]:
        """The account's newest e-mails, newest first: subject, text and when, nothing else."""
        mine = [record for _, record in self._records() if record.get("account_id") == account_id]
        mine.sort(key=lambda record: str(record.get("created_at")), reverse=True)
        keep = ("id", "kind", "subject", "text", "created_at", "sent", "note")
        return [{key: record.get(key) for key in keep} for record in mine[:limit]]

    def purge(self, account_id: str) -> int:
        """Delete every file of one account; how many went."""
        gone = 0
        for path, record in self._records():
            if record.get("account_id") == account_id:
                path.unlink(missing_ok=True)
                gone += 1
        return gone

    def purge_older_than(self, days: int = OUTBOX_KEEP_DAYS, now: dt.datetime | None = None) -> int:
        cutoff = (now or utcnow()) - dt.timedelta(days=days)
        gone = 0
        for path, record in self._records():
            try:
                created = dt.datetime.fromisoformat(str(record.get("created_at")))
            except ValueError:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=dt.UTC)
            if created < cutoff:
                path.unlink(missing_ok=True)
                gone += 1
        return gone


class AcsEmailSender:
    """Azure Communication Services e-mail. Constructed only through :meth:`from_env`."""

    name = "acs"

    def __init__(self, connection_string: str, sender: str) -> None:
        self._connection_string = connection_string
        self.sender = sender

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AcsEmailSender | None:
        """The sender when both variables are set, else ``None`` (off). Values are never printed."""
        env = os.environ if env is None else env
        connection = (env.get("NABIZ_ACS_CONNECTION_STRING") or "").strip()
        sender = (env.get("NABIZ_ACS_SENDER") or "").strip()
        return cls(connection, sender) if connection and sender else None

    def send(self, email: Email) -> SendResult:
        from azure.communication.email import EmailClient  # the `email` extra, only when sending

        client = EmailClient.from_connection_string(self._connection_string)
        message = {
            "senderAddress": self.sender,
            "recipients": {"to": [{"address": email.to}]},
            "content": {"subject": email.subject, "plainText": email.text},
        }
        result = client.begin_send(message).result()
        return SendResult(self.name, delivered=True, reference=str((result or {}).get("id", "")))


def sender_from_env(*, deliver: bool = False, env: Mapping[str, str] | None = None) -> EmailSender:
    """ACS only when asked to deliver and configured; otherwise the outbox."""
    acs = AcsEmailSender.from_env(env) if deliver else None
    return acs if acs is not None else OutboxEmailSender(outbox_dir_from_env())
