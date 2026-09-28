"""Account object checks and explicit browser-to-account migration selection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


class OwnershipDenied(PermissionError):
    """The object is absent or belongs to another account; callers respond as not found."""


def require_owner(account_id: str | None, record_owner_id: str | None) -> None:
    """Call on every account record read, write and delete before returning any record data."""
    if not account_id or not record_owner_id or account_id != record_owner_id:
        raise OwnershipDenied("Kayıt bulunamadı.")


def owned_record(records: Mapping[str, Mapping[str, Any]], record_id: str, account_id: str | None) -> Mapping[str, Any]:
    """Look up an object without exposing whether another account owns the id."""
    record = records.get(record_id)
    require_owner(account_id, record.get("owner_id") if record else None)
    assert record is not None
    return record


@dataclass(frozen=True)
class MigrationSelection:
    """A preview for a later P02b writer; no browser data is modified here."""

    selected: tuple[Mapping[str, Any], ...]
    browser_delete_ids: tuple[str, ...]
    remaining_ids: tuple[str, ...]


def select_guest_records(
    records: Iterable[Mapping[str, Any]], *, selected_ids: Iterable[str],
    consent: bool, health_consent: bool = False,
) -> MigrationSelection:
    """Only marked records move. Health records need a second affirmative consent.

    Forgotten preferences retain their ``forgotten`` flag and do not become active again.
    P02b must commit account writes before deleting these ids from the browser.
    """
    items = tuple(records)
    ids = [item.get("id") for item in items]
    if any(not isinstance(item_id, str) or not item_id for item_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("Invalid guest record ids")
    wanted = set(selected_ids)
    if any(not isinstance(item_id, str) for item_id in wanted) or not wanted.issubset(ids):
        raise ValueError("Unknown guest record")
    if not consent and wanted:
        raise PermissionError("Taşıma için izin gerekli.")
    chosen = tuple(item for item in items if item["id"] in wanted)
    if any(item.get("kind") == "health" for item in chosen) and not health_consent:
        raise PermissionError("Sağlık kaydı için ayrı izin gerekli.")
    selected = tuple(dict(item) for item in chosen)
    return MigrationSelection(selected, tuple(item["id"] for item in selected),
                              tuple(item["id"] for item in items if item["id"] not in wanted))
