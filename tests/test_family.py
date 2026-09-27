"""E52 family storage: offline SQLite tests with a controllable clock."""

from __future__ import annotations

import datetime as dt
import itertools
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from test_pii_guard import POSITIVES, TCKN

from nabiz.console.accounts import AccountStore
from nabiz.console.family import (
    CODE_ALPHABET,
    CODE_LENGTH,
    FAMILY_MAX_MEMBERS,
    FAMILY_STOP_LIMIT,
    JOIN_FAILS_PER_DAY,
    FamilyError,
    FamilyStore,
    clean_display_name,
    clean_stop,
    format_code,
    new_family_code,
    normalize_code,
)

FAMILY_TABLES = (
    "family_groups",
    "family_members",
    "family_requests",
    "family_shared_follows",
    "family_shared_stops",
    "family_attempts",
)


class MutableClock:
    def __init__(self) -> None:
        self.value = dt.datetime(2026, 9, 26, 12, 0, tzinfo=dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.value


@pytest.fixture
def stores(tmp_path: Path):
    clock = MutableClock()
    accounts = AccountStore(tmp_path / "accounts.sqlite", clock=clock)
    family = FamilyStore(accounts, clock=clock)
    yield accounts, family, clock
    family.close()
    accounts.close()


def make_account(accounts: AccountStore, name: str):
    return accounts.create(email=f"{name}@example.com", provider="google", consent=True)[0]


def add_member(accounts: AccountStore, family: FamilyStore, owner_id: str, name: str):
    account = make_account(accounts, name)
    code = family.view(owner_id)["family"]["code"]["code"]
    family.request_join(account.id, code, name.title(), True)
    request = family.view(owner_id)["family"]["requests"][0]
    family.decide(owner_id, request["id"], True)
    return account


def count_tables(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as db:
        return {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in FAMILY_TABLES}


def unknown_code(code: str) -> str:
    return next("".join(chars) for chars in itertools.product(CODE_ALPHABET, repeat=CODE_LENGTH) if "".join(chars) != code)


def family_error(code: str, operation: Any) -> FamilyError:
    with pytest.raises(FamilyError) as caught:
        operation()
    assert caught.value.code == code
    return caught.value


def test_code_helpers_keep_spoken_codes_inside_the_declared_alphabet() -> None:
    assert len(CODE_ALPHABET) == 21
    assert normalize_code("7km 4tp") == "7KM4TP"
    assert normalize_code("7KM-4TP") == "7KM4TP"
    assert normalize_code("7KM4T") is None
    assert normalize_code("0OI1LS") is None
    assert normalize_code("ÇĞİÖŞÜ") is None
    assert format_code("7KM4TP") == "7KM 4TP"
    assert all(len(new_family_code()) == CODE_LENGTH for _ in range(200))
    assert all(set(new_family_code()) <= set(CODE_ALPHABET) for _ in range(200))


def test_names_stops_and_personal_data_are_validated() -> None:
    assert clean_display_name("  Anne   Can  ") == "Anne Can"
    assert clean_display_name("A​da") == "Ada"
    phone = next(value for value, masked in POSITIVES if masked == "[TELEFON]")
    for value in ("", "x" * 25, "anne@example.com", phone, TCKN):
        with pytest.raises(ValueError):
            clean_display_name(value)
    assert clean_stop("m2", "Şişli-Mecidiyeköy") == ("M2", "Şişli-Mecidiyeköy")
    for line, stop in (("", "Şişli"), ("M 2", "Şişli"), ("M2", ""), ("M2", "0555 000 00 01")):
        with pytest.raises(ValueError):
            clean_stop(line, stop)
    assert FAMILY_STOP_LIMIT == 6


def test_missing_consent_writes_no_family_rows(stores) -> None:
    accounts, family, _ = stores
    owner, joiner = make_account(accounts, "owner"), make_account(accounts, "joiner")
    family_error("consent_required", lambda: family.create_code(owner.id, "Anne", False))
    family_error("consent_required", lambda: family.request_join(joiner.id, "7KM4TP", "Can", False))
    assert set(count_tables(accounts.path).values()) == {0}


def test_two_sided_join_and_views_never_expose_another_account(stores) -> None:
    accounts, family, _ = stores
    owner, joiner = make_account(accounts, "owner"), make_account(accounts, "joiner")
    created = family.create_code(owner.id, "Anne", True)
    code = created["family"]["code"]["code"]
    family_error("code_not_found", lambda: family.request_join(joiner.id, unknown_code(code), "Can", True))
    accepted = family.request_join(joiner.id, code, "Can", True)
    owner_view = family.view(owner.id)
    assert accepted["check"] == owner_view["family"]["requests"][0]["check"]
    pending = family.view(joiner.id)
    assert pending["state"] == "pending" and pending["family"] is None
    assert "Anne" not in json.dumps(pending, ensure_ascii=False)
    request = owner_view["family"]["requests"][0]
    family.decide(owner.id, request["id"], True)
    owner_view, joiner_view = family.view(owner.id), family.view(joiner.id)
    assert owner_view["family"]["count"] == joiner_view["family"]["count"] == 2
    for view, other in ((owner_view, joiner), (joiner_view, owner)):
        encoded = json.dumps(view, ensure_ascii=False)
        assert other.email not in encoded
        assert other.id not in encoded
        assert all(key not in encoded for key in ('"account_id"', '"email"', '"token"', '"tier"', '"consent_at"'))


def test_code_expiry_renewal_and_old_request_cleanup(stores) -> None:
    accounts, family, clock = stores
    owner, joiner = make_account(accounts, "owner"), make_account(accounts, "joiner")
    original = family.create_code(owner.id, "Anne", True)["family"]["code"]["code"]
    family.request_join(joiner.id, original, "Can", True)
    clock.value += dt.timedelta(hours=25)
    first_error = family_error("code_not_found", lambda: family.request_join(joiner.id, original, "Can", True))
    renewed = family.renew_code(owner.id)["family"]["code"]["code"]
    assert renewed != original
    second_error = family_error(
        "code_not_found", lambda: family.request_join(make_account(accounts, "other").id, original, "Ece", True)
    )
    assert first_error.message == second_error.message
    assert family.view(owner.id)["family"]["requests"], "renewal leaves pending requests intact"
    clock.value += dt.timedelta(days=8)
    assert family.purge() == 1
    assert family.view(owner.id)["family"]["requests"] == []


def test_bad_code_attempts_are_persisted_limited_and_reset_on_new_day(stores) -> None:
    accounts, family, clock = stores
    owner, joiner = make_account(accounts, "owner"), make_account(accounts, "joiner")
    code = family.create_code(owner.id, "Anne", True)["family"]["code"]["code"]
    wrong = unknown_code(code)
    for _ in range(JOIN_FAILS_PER_DAY):
        family_error("code_not_found", lambda: family.request_join(joiner.id, wrong, "Can", True))
    family_error("too_many_attempts", lambda: family.request_join(joiner.id, code, "Can", True))
    clock.value += dt.timedelta(hours=13)
    assert family.request_join(joiner.id, code, "Can", True)["check"].isdigit()


def test_family_limits_permissions_and_pending_request_rules(stores) -> None:
    accounts, family, _ = stores
    owner = make_account(accounts, "owner")
    code = family.create_code(owner.id, "Anne", True)["family"]["code"]["code"]
    family_error("own_code", lambda: family.request_join(owner.id, code, "Anne", True))
    pending = make_account(accounts, "pending")
    family.request_join(pending.id, code, "Can", True)
    family_error("request_pending", lambda: family.request_join(pending.id, code, "Can", True))
    family_error("request_pending", lambda: family.create_code(pending.id, "Can", True))
    first = family.view(owner.id)["family"]["requests"][0]
    family.decide(owner.id, first["id"], True)
    family_error("already_in_family", lambda: family.create_code(pending.id, "Can", True))
    family_error("not_owner", lambda: family.decide(pending.id, "missing", True))
    family_error("not_owner", lambda: family.remove_member(pending.id, first["id"]))

    queued = []
    for number in range(5):
        person = make_account(accounts, f"member{number}")
        family.request_join(person.id, code, f"Üye {number}", True)
        request_id = next(
            item["id"] for item in family.view(owner.id)["family"]["requests"] if item["display_name"] == f"Üye {number}"
        )
        queued.append((person, request_id))
        if number < 3:
            family.decide(owner.id, queued[-1][1], True)
    assert family.view(owner.id)["family"]["count"] == FAMILY_MAX_MEMBERS - 1
    family.decide(owner.id, queued[3][1], True)
    family_error("family_full", lambda: family.decide(owner.id, queued[4][1], True))
    extra = make_account(accounts, "extra")
    family_error("family_full", lambda: family.request_join(extra.id, code, "Ece", True))


def test_shares_are_explicit_owned_and_cascade_with_follow_deletion(stores) -> None:
    accounts, family, _ = stores
    owner = make_account(accounts, "owner")
    family.create_code(owner.id, "Anne", True)
    member = add_member(accounts, family, owner.id, "member")
    own = accounts.add_follow(member.id, kind="metro_line", value="M2", label="M2 hattı")
    hidden = accounts.add_follow(member.id, kind="station", value="Etiler", label="Etiler asansörü")
    other = accounts.add_follow(owner.id, kind="metro_line", value="M4", label="M4 hattı")
    family_error("share_invalid", lambda: family.set_shares(member.id, [other["id"]], []))
    family.set_shares(member.id, [own["id"]], [{"line": "m2", "stop": "Şişli-Mecidiyeköy"}])
    shared = family.view(owner.id)["family"]["members"][1]["shares"]
    assert [item["label"] for item in shared["follows"]] == ["M2 hattı"]
    assert shared["stops"] == [{"line": "M2", "stop": "Şişli-Mecidiyeköy"}]
    assert hidden["id"] not in json.dumps(shared)
    family_error(
        "share_invalid",
        lambda: family.set_shares(member.id, [], [{"line": "M2", "stop": f"Durak {n}"} for n in range(7)]),
    )
    accounts.remove_follow(member.id, own["id"])
    after_remove = family.view(owner.id)["family"]["members"][1]["shares"]
    assert after_remove == {"follows": [], "stops": [{"line": "M2", "stop": "Şişli-Mecidiyeköy"}]}


def test_owner_removal_clears_membership_and_every_share(stores) -> None:
    accounts, family, _ = stores
    owner = make_account(accounts, "owner")
    family.create_code(owner.id, "Anne", True)
    member = add_member(accounts, family, owner.id, "member")
    follow = accounts.add_follow(member.id, kind="metro_line", value="M2", label="M2 hattı")
    family.set_shares(member.id, [follow["id"]], [{"line": "M2", "stop": "Şişli"}])
    member_id = next(row["id"] for row in family.view(owner.id)["family"]["members"] if not row["is_me"])
    removed = family.remove_member(owner.id, member_id)
    assert removed["family"]["count"] == 1
    assert family.view(member.id)["state"] == "none"
    with sqlite3.connect(accounts.path) as db:
        assert db.execute("SELECT COUNT(*) FROM family_shared_follows WHERE member_id = ?", (member_id,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM family_shared_stops WHERE member_id = ?", (member_id,)).fetchone()[0] == 0


def test_leave_dissolve_delete_and_inactivity_remove_related_rows(stores) -> None:
    accounts, family, clock = stores
    owner = make_account(accounts, "owner")
    family.create_code(owner.id, "Anne", True)
    member = add_member(accounts, family, owner.id, "member")
    follow = accounts.add_follow(member.id, kind="metro_line", value="M2", label="M2 hattı")
    family.set_shares(member.id, [follow["id"]], [{"line": "M2", "stop": "Şişli"}])
    member_id = next(item["id"] for item in family.view(owner.id)["family"]["members"] if not item["is_me"])
    assert family.leave(member.id)["dissolved"] is False
    assert family.view(owner.id)["family"]["members"][0]["id"] != member_id
    with sqlite3.connect(accounts.path) as db:
        assert db.execute("SELECT COUNT(*) FROM family_shared_follows WHERE member_id = ?", (member_id,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM family_shared_stops WHERE member_id = ?", (member_id,)).fetchone()[0] == 0

    family.leave(owner.id)
    assert set(count_tables(accounts.path).values()) == {0}

    owner2 = make_account(accounts, "owner2")
    family.create_code(owner2.id, "Anne", True)
    add_member(accounts, family, owner2.id, "member2")
    family.leave(owner2.id)
    assert set(count_tables(accounts.path).values()) == {0}

    owner3 = make_account(accounts, "owner3")
    family.create_code(owner3.id, "Anne", True)
    member3 = add_member(accounts, family, owner3.id, "member3")
    family.set_shares(member3.id, [], [{"line": "M2", "stop": "Şişli"}])
    assert accounts.delete(owner3.id)
    assert set(count_tables(accounts.path).values()) == {0}

    owner4 = make_account(accounts, "owner4")
    family.create_code(owner4.id, "Anne", True)
    member4 = add_member(accounts, family, owner4.id, "member4")
    family.set_shares(member4.id, [], [{"line": "M2", "stop": "Şişli"}])
    with accounts._tx() as db:
        db.execute("UPDATE accounts SET last_seen_on = '2020-01-01' WHERE id = ?", (owner4.id,))
    assert owner4.id in accounts.purge_inactive(days=1)
    assert set(count_tables(accounts.path).values()) == {0}
    clock.value += dt.timedelta(minutes=1)
