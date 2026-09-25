"""nexus_core.ledger: every entry seals the one before it, and tampering shows."""

from __future__ import annotations

import datetime as dt
import pathlib
import sqlite3
import threading

import pytest
from nexus_helpers import T0, Clock

from nexus_core.ledger import DEFAULT_PATH, GENESIS, PATH_ENV, EntryKind, Ledger, default_path


def ledger(tmp_path: pathlib.Path, clock: Clock | None = None) -> Ledger:
    return Ledger(tmp_path / "nexus.db", clock=clock or Clock())


def fill(book: Ledger) -> None:
    book.append(EntryKind.SIGNAL, actor="kaynak: Metro İstanbul", detail={"n": 1}, signal_id="s1", entity_id="e1")
    book.append(EntryKind.ROUTED, actor="yönlendirici", detail={"path": "arena"}, signal_id="s1", entity_id="e1")
    book.append(EntryKind.SIGNAL, actor="kaynak: Metro İstanbul", detail={"n": 2}, signal_id="s2", entity_id="e2")
    book.append(EntryKind.APPROVAL, actor="Simüle operatör (op-1)", detail={"reason": "Kanıt taze"}, signal_id="s1")


def tamper(path: pathlib.Path, sql: str) -> None:
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(sql)
    conn.close()


def test_entries_chain_from_the_genesis_hash(tmp_path: pathlib.Path) -> None:
    book = ledger(tmp_path)
    fill(book)
    entries = book.entries()
    assert [e.id for e in entries] == [1, 2, 3, 4]
    assert entries[0].prev_hash == GENESIS
    assert all(later.prev_hash == earlier.hash for earlier, later in zip(entries, entries[1:], strict=False))
    result = book.verify()
    assert result.ok and result.entries == 4 and result.head == entries[-1].hash and result.first_bad_id is None


def test_an_empty_ledger_verifies(tmp_path: pathlib.Path) -> None:
    result = ledger(tmp_path).verify()
    assert result.ok and result.entries == 0 and result.head == GENESIS


def test_an_edited_detail_breaks_the_chain_at_that_entry(tmp_path: pathlib.Path) -> None:
    book = ledger(tmp_path)
    fill(book)
    tamper(book.path, """UPDATE entries SET detail = '{"reason":"onaylandı"}' WHERE id = 4""")
    result = book.verify()
    assert not result.ok and result.first_bad_id == 4 and "content" in result.problem
    assert book.trace("s1").hash_ok is False


def test_an_edited_actor_or_time_is_caught_too(tmp_path: pathlib.Path) -> None:
    book = ledger(tmp_path)
    fill(book)
    tamper(book.path, "UPDATE entries SET actor = 'model' WHERE id = 2")
    assert book.verify().first_bad_id == 2
    tamper(book.path, "UPDATE entries SET actor = 'yönlendirici', at = '2026-01-01T00:00:00+00:00' WHERE id = 2")
    assert book.verify().first_bad_id == 2


def test_a_deleted_entry_is_missing(tmp_path: pathlib.Path) -> None:
    book = ledger(tmp_path)
    fill(book)
    tamper(book.path, "DELETE FROM entries WHERE id = 2")
    result = book.verify()
    assert not result.ok and result.first_bad_id == 3 and "missing" in result.problem


def test_a_rehashed_forgery_still_breaks_the_next_link(tmp_path: pathlib.Path) -> None:
    """Rewriting one entry and its own hash is not enough: the next entry sealed the old hash."""
    book = ledger(tmp_path)
    fill(book)
    tamper(book.path, "UPDATE entries SET hash = 'f' || substr(hash, 2) WHERE id = 2")
    assert book.verify().first_bad_id == 2


def test_trace_is_one_signal_in_order(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    book = ledger(tmp_path, clock)
    fill(book)
    trace = book.trace("s1")
    assert [s.kind for s in trace.steps] == ["signal_received", "routed", "approval"]
    assert [s.entry_id for s in trace.steps] == [1, 2, 4] and trace.hash_ok
    assert trace.steps[2].actor == "Simüle operatör (op-1)" and trace.steps[2].detail == {"reason": "Kanıt taze"}
    assert trace.steps[0].at == T0


def test_entries_filter_by_signal_entity_and_kind(tmp_path: pathlib.Path) -> None:
    book = ledger(tmp_path)
    fill(book)
    assert [e.id for e in book.entries(entity_id="e1")] == [1, 2]
    assert [e.id for e in book.entries(kinds=[EntryKind.SIGNAL])] == [1, 3]
    assert [e.id for e in book.entries(signal_id="s1", kinds=["approval"])] == [4]
    assert book.has_signal("s2") and not book.has_signal("s9")
    assert book.entries(kinds=[]) == []


def test_the_ledger_persists_across_instances(tmp_path: pathlib.Path) -> None:
    fill(ledger(tmp_path))
    again = ledger(tmp_path)
    assert again.verify().entries == 4
    again.append(EntryKind.ROUTED, actor="yönlendirici", detail={}, signal_id="s2")
    assert again.verify().ok and again.verify().entries == 5


def test_concurrent_appends_never_share_a_chain_position(tmp_path: pathlib.Path) -> None:
    book = ledger(tmp_path)

    def worker(n: int) -> None:
        for i in range(10):
            book.append(EntryKind.SIGNAL, actor="kaynak", detail={"worker": n, "i": i}, signal_id=f"s{n}-{i}")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    result = book.verify()
    assert result.ok and result.entries == 80


def test_the_default_path_and_its_override(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PATH_ENV, raising=False)
    assert default_path() == DEFAULT_PATH == pathlib.Path("data/nexus/nexus.db")
    target = tmp_path / "deep" / "dir" / "ledger.db"
    monkeypatch.setenv(PATH_ENV, str(target))
    book = Ledger(clock=Clock())
    assert book.path == target and target.exists()


def test_times_are_utc_iso_from_the_clock(tmp_path: pathlib.Path) -> None:
    clock = Clock(dt.datetime(2026, 9, 25, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=3))))
    entry = ledger(tmp_path, clock).append(EntryKind.SIGNAL, actor="kaynak", detail={}, signal_id="s")
    assert entry.at == T0 and entry.at.tzinfo is not None


def test_details_keep_turkish_text_exactly(tmp_path: pathlib.Path) -> None:
    book = ledger(tmp_path)
    book.append(EntryKind.APPROVAL, actor="Simüle operatör", detail={"reason": "Şişhane asansörü İBB kaydında arızasız"})
    assert book.entries()[0].detail["reason"] == "Şişhane asansörü İBB kaydında arızasız" and book.verify().ok
