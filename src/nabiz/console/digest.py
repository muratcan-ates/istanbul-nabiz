"""The daily follow digest: for each account, the essential changes in its topics, in one e-mail.

``scripts/notify_digest.py`` (``make notify-digest``) runs :func:`run_digest`. Per account with
follows, at most once per Istanbul day:

1. each followed topic is evaluated once for the whole run (:mod:`nabiz.console.follow_eval`);
2. the change since that follow's stored state is taken, and only the essential kinds count
   (a new or cleared fault, a line notice, a new service page; not a bus line's bunching);
3. the follow's state is stored, so the same news is never sent twice;
4. with at least one essential change, one plain-text e-mail in Turkish and English goes to the
   :class:`~nabiz.console.email_sender.EmailSender` (the outbox unless real delivery was asked for).

A topic whose source could not be read keeps its old state and adds nothing. An account that
already had its e-mail today is skipped whole, states included, so tomorrow's e-mail still carries
today's news. Accounts unused for twelve months are purged first, with their outbox files.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
from dataclasses import dataclass, field
from typing import Any

from ibb_mcp.models import ISTANBUL_TZ, utcnow
from nabiz.console.accounts import Account, AccountStore
from nabiz.console.email_sender import NOT_OFFICIAL, Email, EmailSender, OutboxEmailSender
from nabiz.console.follow import topic_from
from nabiz.console.follow_eval import Change, diff, essential, evaluate_topics

DEFAULT_PUBLIC_URL = "http://127.0.0.1:8090"
_WORD_TR = {"new": "Yeni", "resolved": "Giderildi"}
_WORD_EN = {"new": "New", "resolved": "Cleared"}


@dataclass
class DigestReport:
    accounts: int = 0
    emails: int = 0
    skipped_today: int = 0
    purged: int = 0
    topics: int = 0
    unavailable: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def public_url() -> str:
    return (os.environ.get("NABIZ_PUBLIC_URL") or DEFAULT_PUBLIC_URL).rstrip("/")


def unsubscribe_token(secret: bytes, follow_id: str) -> str:
    """``<follow id>.<signature>``: lets the link stop one follow and nothing else."""
    signature = hmac.new(secret, follow_id.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{follow_id}.{signature}"


def check_unsubscribe(secret: bytes, token: str) -> str | None:
    follow_id, _, signature = str(token or "").partition(".")
    if not follow_id or not signature:
        return None
    expected = unsubscribe_token(secret, follow_id).partition(".")[2]
    return follow_id if hmac.compare_digest(expected, signature) else None


def compose(account: Account, sections: list[tuple[dict[str, Any], list[Change]]], *, secret: bytes, day: str) -> Email:
    """One plain-text digest: Turkish first, then English, each change with its source and age."""
    count = sum(len(changes) for _, changes in sections)
    base = public_url()
    lines = [NOT_OFFICIAL, "", f"Takip ettiğin konularda {count} önemli değişiklik var ({day}).", ""]
    english = ["", "English", f"{count} important change(s) in the topics you follow ({day}).", ""]
    for follow, changes in sections:
        lines.append(f"{follow['label']}:")
        english.append(f"{follow['label']}:")
        lines += [f"  {_WORD_TR[change.kind]}: {change.text_tr}" for change in changes]
        english += [f"  {_WORD_EN[change.kind]}: {change.text_en}" for change in changes]
        link = f"{base}/#takibi-birak={unsubscribe_token(secret, follow['id'])}"
        lines.append(f"  Takibi bırak: {link}")
        english.append(f"  Stop following: {link}")
        lines.append("")
    footer = [
        "",
        "Veriler İBB Açık Veri Portalı kaynaklıdır (İBB Açık Veri Lisansı). Her satır kaynağını ve veri yaşını söyler.",
        "Hesabını ve verilerini silmek için: " + f"{base}/#hesap",
        NOT_OFFICIAL,
    ]
    return Email(
        to=account.email,
        subject=f"İstanbul Nabız: takip ettiğin konularda {count} değişiklik (örnek hesap)",
        text="\n".join(lines + english + footer),
        kind="digest",
        account_id=account.id,
    )


def verification_email(account: Account) -> Email:
    """The sign-in's confirmation: always written to the outbox, never sent (nothing is verified)."""
    text = "\n".join(
        [
            NOT_OFFICIAL,
            "",
            "Örnek hesabın oluşturuldu. Bu bir gösterim: gerçek İBB, İstanbulkart ya da Google hesabına bağlanılmadı",
            "ve e-posta adresin doğrulanmadı. Bu e-posta gönderilmedi; yalnız önizleme olarak saklandı.",
            "Hesabını ve verilerini Profilim bölümünde tek tuşla silebilirsin: " + f"{public_url()}/#hesap",
            "",
            "Your example account was created. Nothing was verified and this e-mail was not sent.",
        ]
    )
    return Email(account.email, "İstanbul Nabız: örnek hesap oluşturuldu (gönderilmedi)", text, "verify", account.id)


async def run_digest(
    store: AccountStore,
    nabiz: Any,
    sender: EmailSender,
    *,
    now: dt.datetime | None = None,
    outbox: OutboxEmailSender | None = None,
) -> DigestReport:
    now = now or utcnow()
    day = now.astimezone(ISTANBUL_TZ).date().isoformat()
    report = DigestReport()
    for account_id in store.purge_inactive():
        report.purged += 1
        if outbox is not None:
            outbox.purge(account_id)
    if outbox is not None:
        outbox.purge_older_than(now=now)
    accounts = store.accounts_with_follows()
    report.accounts = len(accounts)
    follows = {account.id: store.follows(account.id) for account in accounts}
    topics = [topic_from(f["kind"], f["value"]) for items in follows.values() for f in items]
    states = await evaluate_topics(nabiz, topics)
    report.topics = len(states)
    report.unavailable = sorted({state.topic.label for state in states.values() if state.unavailable})
    secret = store.secret()
    for account in accounts:
        if account.last_digest_on == day:
            report.skipped_today += 1
            continue
        sections = []
        for follow in follows[account.id]:
            topic = topic_from(follow["kind"], follow["value"])
            state = states.get(topic.key)
            if state is None or state.unavailable:
                continue
            changes = essential(topic, diff(follow["last_state"], state))
            store.set_follow_state(follow["id"], state.active)
            if changes:
                sections.append((follow, changes))
        if sections:
            result = sender.send(compose(account, sections, secret=secret, day=day))
            store.mark_digest(account.id, day)
            report.emails += 1
            report.references.append(result.reference)
    return report
