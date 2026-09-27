from __future__ import annotations

import datetime as dt
import json
import sqlite3

from nabiz.console.poll import (
    CLOSED_KIND,
    DISTRICTS,
    DRAFT_TTL_DAYS,
    MIN_FOR_PERCENT,
    PUBLISHED_KIND,
    TTL_DAYS,
    Draft,
    PollStore,
    clean_poll_text,
    closes_at_for,
    digest_of,
    tally,
    validate_draft,
)
from nexus_core.ledger import Ledger

NOW = dt.datetime(2026, 9, 27, 9, 0, tzinfo=dt.UTC)
DEVICE = "0123456789abcdef0123456789abcdef"
PHONE = "0532 123 45 67"


def draft_for(today: dt.date = NOW.date(), *, question: str = "İstanbul ulaşımı nasıl?") -> Draft:
    draft = validate_draft(
        question, ["Daha iyi", "Aynı"], (today + dt.timedelta(days=1)).isoformat(), {"kind": "all", "district": None}, today=today
    )
    assert isinstance(draft, Draft)
    return draft


def clock_box():
    value = {"now": NOW}
    return value, lambda: value["now"]


def create_and_publish(store: PollStore, ledger: Ledger, draft: Draft | None = None) -> dict:
    proposal = store.create_draft(draft or draft_for(), "Simüle operatör (simule-operator)")
    return store.publish(proposal["id"], proposal["digest"], "Simüle operatör (simule-operator)", ledger)


def test_validation_cleans_text_and_freezes_every_rule_and_sentence() -> None:
    today = NOW.date()
    assert clean_poll_text("  İstanbul\u200b\u2014\n ulaşımı  ") == "İstanbul- ulaşımı"
    assert validate_draft("Kısa?", ["Evet", "Hayır"], "2026-09-28", {"kind": "all"}, today=today) == (
        "Soru en az 8, en çok 140 karakter olmalı."
    )
    assert validate_draft("Soru yeterince uzun", ["Evet"], "2026-09-28", {"kind": "all"}, today=today) == (
        "2 ile 5 arasında seçenek yazın."
    )
    assert validate_draft("Soru yeterince uzun", ["Evet", "Hayır", "x" * 41], "2026-09-28", {"kind": "all"}, today=today) == (
        "Her seçenek en çok 40 karakter olabilir."
    )
    assert validate_draft("Soru yeterince uzun", ["İstanbul", "istanbul"], "2026-09-28", {"kind": "all"}, today=today) == (
        "İki seçenek aynı olamaz."
    )
    pii = validate_draft(f"{PHONE} için hangi saat?", ["Sabah", "Akşam"], "2026-09-28", {"kind": "all"}, today=today)
    assert isinstance(pii, str) and "TELEFON" in pii and PHONE not in pii
    assert validate_draft("Örnek site example.com uygun mu?", ["Evet", "Hayır"], "2026-09-28", {"kind": "all"}, today=today) == (
        "Ankette bağlantı olamaz."
    )
    assert validate_draft("Soru yeterince uzun", ["Evet", "Hayır"], "2026-09-26", {"kind": "all"}, today=today) == (
        "Bitiş günü bugün ile 14 gün sonrası arasında olmalı."
    )
    assert validate_draft("Soru yeterince uzun", ["Evet", "Hayır"], "2026-10-12", {"kind": "all"}, today=today) == (
        "Bitiş günü bugün ile 14 gün sonrası arasında olmalı."
    )
    bad_target = {"kind": "district", "district": "Kadıkoy"}
    assert validate_draft("Soru yeterince uzun", ["Evet", "Hayır"], "2026-09-28", bad_target, today=today) == (
        "İlçe listede yok."
    )
    good_target = {"kind": "district", "district": "Kadıköy"}
    clean = validate_draft("İstanbul\u2013 ulaşımı nasıl?", ["Evet", "Hayır"], "2026-09-28", good_target, today=today)
    assert isinstance(clean, Draft) and clean.question == "İstanbul- ulaşımı nasıl?"
    assert clean.target == {"kind": "district", "district": "Kadıköy"}
    assert len(DISTRICTS) == 39


def test_closes_at_digest_and_percent_threshold_and_largest_remainder() -> None:
    date = dt.date(2026, 9, 28)
    assert closes_at_for(date) == dt.datetime(2026, 9, 28, 20, 59, 59, tzinfo=dt.UTC)
    first = draft_for()
    assert digest_of(first) == digest_of(first)
    assert MIN_FOR_PERCENT == 5
    result = tally({"o1": 2, "o2": 2}, first.options)
    assert result["total"] == 4 and [row["percent"] for row in result["rows"]] == [None, None]
    options = tuple({"key": f"o{index}", "label": str(index)} for index in range(1, 6))
    shares = tally({"o1": 1, "o2": 1, "o3": 1, "o4": 1, "o5": 3}, options)
    assert [row["percent"] for row in shares["rows"]] == [15, 14, 14, 14, 43]
    assert sum(row["percent"] for row in shares["rows"]) == 100


def test_store_separates_votes_enforces_one_per_device_and_ledger_has_no_device_data(tmp_path) -> None:
    now, clock = clock_box()
    ledger = Ledger(tmp_path / "nexus.db", clock=clock)
    store = PollStore(tmp_path / "polls.db", clock=clock, ledger=ledger)
    active = create_and_publish(store, ledger)
    assert store.vote(active["id"], DEVICE, "o1") == "ok"
    assert store.vote(active["id"], DEVICE, "o2") == "already"
    assert store.vote(active["id"], "fedcba9876543210fedcba9876543210", "o2") == "ok"
    result = store.results(active["id"])
    assert result and result["total"] == 2
    with sqlite3.connect(tmp_path / "polls.db") as conn:
        voters = [row[1] for row in conn.execute("SELECT poll_id, voter FROM poll_voters")]
        tally_columns = [row[1] for row in conn.execute("PRAGMA table_info(poll_tallies)")]
        voter_columns = [row[1] for row in conn.execute("PRAGMA table_info(poll_voters)")]
    assert len(voters) == 2 and all(len(key) == 32 for key in voters)
    assert voter_columns == ["poll_id", "voter"]
    assert tally_columns == ["poll_id", "choice", "count"]
    assert "device" not in " ".join(voter_columns + tally_columns)
    closed = store.close(active["id"], f"Gerekçe, {PHONE}", "Simüle operatör (simule-operator)", ledger)
    assert closed["status"] == "closed"
    assert ledger.verify().ok
    entries = ledger.entries(entity_id=f"poll:{active['id']}")
    assert [entry.kind for entry in entries] == [PUBLISHED_KIND, CLOSED_KIND]
    assert all(entry.actor.startswith("Simüle operatör") for entry in entries)
    assert entries[0].detail["sha256"] == active["digest"]
    assert entries[1].detail["reason"].endswith("[TELEFON]")
    assert PHONE not in json.dumps([entry.detail for entry in entries], ensure_ascii=False)
    joined = json.dumps([entry.detail for entry in ledger.entries()], ensure_ascii=False)
    assert DEVICE not in joined and all(key not in joined for key in voters)
    assert '"salt"' not in joined and '"address"' not in joined


def test_voter_hash_is_poll_salted_and_draft_replacement_is_single(tmp_path) -> None:
    now, clock = clock_box()
    ledger = Ledger(tmp_path / "nexus.db", clock=clock)
    store = PollStore(tmp_path / "polls.db", clock=clock, ledger=ledger)
    old = store.create_draft(draft_for(), "operator")
    replacement = store.create_draft(draft_for(question="Başka bir şehir sorusu?"), "operator")
    assert store.get(old["id"]) is None
    assert store.current()["draft"]["id"] == replacement["id"]
    first = store.publish(replacement["id"], replacement["digest"], "operator", ledger)
    assert store.vote(first["id"], DEVICE, "o1") == "ok"
    first_voter = (
        sqlite3.connect(tmp_path / "polls.db")
        .execute("SELECT voter FROM poll_voters WHERE poll_id = ?", (first["id"],))
        .fetchone()[0]
    )
    store.close(first["id"], "Süre dolmadan bitirme", "operator", ledger)
    second = create_and_publish(store, ledger, draft_for(question="İkinci şehir sorusu?"))
    assert store.vote(second["id"], DEVICE, "o1") == "ok"
    second_voter = (
        sqlite3.connect(tmp_path / "polls.db")
        .execute("SELECT voter FROM poll_voters WHERE poll_id = ?", (second["id"],))
        .fetchone()[0]
    )
    assert first_voter != second_voter


def test_expiry_closes_once_and_ttl_removes_all_three_tables(tmp_path) -> None:
    box, clock = clock_box()
    ledger = Ledger(tmp_path / "nexus.db", clock=clock)
    store = PollStore(tmp_path / "polls.db", clock=clock, ledger=ledger)
    active = create_and_publish(store, ledger)
    box["now"] = dt.datetime.fromisoformat(active["closes_at"]) + dt.timedelta(seconds=1)
    assert store.active() is None and store.active() is None
    expired_entries = [entry for entry in ledger.entries(entity_id=f"poll:{active['id']}") if entry.kind == CLOSED_KIND]
    assert len(expired_entries) == 1
    assert expired_entries[0].detail["how"] == "time"
    assert expired_entries[0].actor == "sistem (süre doldu)"
    assert store.get(active["id"])["status"] == "closed"
    assert store.last_closed()["id"] == active["id"]
    assert store.last_closed()["results"]["total"] == 0
    assert ledger.verify().ok
    box["now"] += dt.timedelta(days=TTL_DAYS)
    assert store.purge() == 1
    with sqlite3.connect(tmp_path / "polls.db") as conn:
        assert [
            conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "polls",
                "poll_voters",
                "poll_tallies",
            )
        ] == [0, 0, 0]
    assert DRAFT_TTL_DAYS == 7


def test_pii_rejection_never_persists_the_matched_value(tmp_path) -> None:
    text = f"{PHONE} ile ilgili soru nasıl sorulur?"
    rejection = validate_draft(text, ["Evet", "Hayır"], "2026-09-28", {"kind": "all"}, today=NOW.date())
    assert isinstance(rejection, str) and PHONE not in rejection
    store = PollStore(tmp_path / "polls.db")
    assert store.current() == {"draft": None, "active": None}
    assert PHONE.encode() not in (tmp_path / "polls.db").read_bytes()
