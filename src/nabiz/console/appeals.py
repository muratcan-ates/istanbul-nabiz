"""A minimal in-app appeal queue with human decisions and no free-text citizen data."""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace

from nabiz.console.restriction import RestrictionBook

APPEAL_REASONS = {
    "mistake": "Kısıtın hatalı olduğunu düşünüyorum.",
    "shared_device": "Bu cihazı başka biri de kullanıyor.",
    "other": "İnsan incelemesi istiyorum.",
}
DECISION_REASONS = {
    "mistaken_restriction": "İncelemede kısıt hatalı bulundu.",
    "shared_device": "Ortak cihaz kullanımı doğrulandı.",
    "insufficient_evidence": "Kısıtı sürdürmek için yeterli kanıt bulunmadı.",
    "restriction_upheld": "İstek yoğunluğu kaydı kısıtı destekliyor.",
}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass(frozen=True)
class Appeal:
    id: str
    subject: str
    category: str
    submitted_at: dt.datetime
    restriction_until: dt.datetime
    status: str = "pending"
    decision_reason: str | None = None
    decided_at: dt.datetime | None = None

    def citizen_view(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "category": self.category,
            "status": self.status,
            "submitted_at": self.submitted_at.isoformat(),
            "decision_reason": DECISION_REASONS.get(self.decision_reason),
        }

class AppealBook:
    """Fake in-memory queue; a production adapter must preserve decisions across restarts."""

    def __init__(self, restrictions: RestrictionBook, *, clock: Callable[[], dt.datetime] = _now) -> None:
        self.restrictions = restrictions
        self.clock = clock
        self._lock = threading.RLock()
        self._appeals: dict[str, Appeal] = {}

    def submit(self, subject: str, category: str) -> Appeal:
        if category not in APPEAL_REASONS:
            raise ValueError("İtiraz gerekçesi tanınmıyor.")
        active = self.restrictions.current(subject)
        if active is None:
            raise ValueError("Etkin kısıt bulunamadı.")
        with self._lock:
            for appeal in self._appeals.values():
                if appeal.subject == active.subject and appeal.restriction_until == active.until:
                    return appeal
            appeal = Appeal(uuid.uuid4().hex, active.subject, category, self.clock(), active.until)
            self._appeals[appeal.id] = appeal
            return appeal

    def for_subject(self, appeal_id: str, subject: str) -> Appeal:
        with self._lock:
            appeal = self._appeals.get(appeal_id)
            if appeal is None or appeal.subject != subject:
                raise LookupError("İtiraz bulunamadı.")
            return appeal

    def queue(self) -> list[Appeal]:
        with self._lock:
            return [appeal for appeal in self._appeals.values() if appeal.status == "pending"]

    def purge_subject(self, subject: str) -> int:
        """Remove this subject's appeal history and restriction on account deletion."""
        with self._lock:
            ids = [item.id for item in self._appeals.values() if item.subject == subject]
            for appeal_id in ids:
                del self._appeals[appeal_id]
            self.restrictions.reopen(subject)
            return len(ids)

    def decide(self, appeal_id: str, *, action: str, reason: str) -> Appeal:
        """A human-only call: the API must authenticate the operator before reaching here."""
        if action not in {"reopen", "uphold"}:
            raise ValueError("Karar tanınmıyor.")
        if reason not in DECISION_REASONS:
            raise ValueError("Gerekçeli karar zorunlu.")
        if action == "uphold" and reason != "restriction_upheld":
            raise ValueError("Sürdürme kararı için uygun gerekçe seçin.")
        if action == "reopen" and reason == "restriction_upheld":
            raise ValueError("Geri açma için uygun gerekçe seçin.")
        with self._lock:
            appeal = self._appeals.get(appeal_id)
            if appeal is None:
                raise LookupError("İtiraz bulunamadı.")
            if appeal.status != "pending":
                raise RuntimeError("İtiraz zaten karara bağlandı.")
            if action == "reopen":
                current = self.restrictions.current(appeal.subject)
                if current is None or current.until != appeal.restriction_until:
                    raise RuntimeError("Kısıt değişti; yeni durumu inceleyin.")
                self.restrictions.reopen(appeal.subject)
            decided = replace(
                appeal, status="reopened" if action == "reopen" else "upheld",
                decision_reason=reason, decided_at=self.clock(),
            )
            self._appeals[appeal_id] = decided
            return decided
