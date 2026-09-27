"""Journey validation, deterministic impact rules, and the optional account store."""

from __future__ import annotations

import datetime as dt

import pytest

from ibb_mcp import accessibility
from nabiz.console.journey_watch import NEEDS, JourneyStore, changed, impact, journey_from


def journey(*, needs: list[str] | None = None):
    return journey_from(
        {
            "id": "j1",
            "from": "Kadıköy",
            "to": "Levent",
            "time": "08:30",
            "needs": needs or ["step_free"],
        }
    )


def test_console_needs_stay_aligned_with_the_accessibility_source() -> None:
    assert NEEDS == accessibility.SUPPORTED_NEEDS


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"from": "41.0123,29.0123", "to": "Levent", "needs": ["step_free"]}, "konum"),
        ({"from": "kadikoy", "to": "Kadıköy", "needs": ["step_free"]}, "aynı"),
        ({"from": "Kadıköy", "to": "Levent", "time": "25:90", "needs": ["step_free"]}, "Saat"),
        ({"from": "Kadıköy", "to": "Levent", "needs": ["stroller"]}, "desteklenmiyor"),
    ],
)
def test_journey_input_rejects_invalid_location_identity_time_and_needs(raw, message) -> None:
    """`journey_from` owns place checks; accessibility.SUPPORTED_NEEDS owns need validation."""
    value = {"id": "j1", "time": None, **raw}
    with pytest.raises(ValueError, match=message):
        journey_from(value)


def test_journey_input_rejects_personal_data_and_normalizes_spaces() -> None:
    phone = "0532 " + "123 45 67"
    with pytest.raises(ValueError, match="kişisel bilgi"):
        journey_from({"id": "j1", "from": phone, "to": "Levent", "needs": ["step_free"]})
    item = journey_from({"id": "j1", "from": "  Kadıköy   İskele ", "to": " Levent ", "needs": ["step_free"]})
    assert item.origin == "Kadıköy İskele" and item.destination == "Levent"


def test_missing_id_is_stable_for_the_same_valid_input() -> None:
    raw = {"from": "Kadıköy", "to": "Levent", "needs": ["step_free"]}
    assert journey_from(raw).id == journey_from(raw).id


def test_unavailable_equipment_never_becomes_clear() -> None:
    item = journey()
    # `plan_accessible_journey` adds EQUIPMENT_DATA_UNAVAILABLE in `_read_sources`.
    result = impact(
        item,
        {
            "available": False,
            "reason": "Asansör verisi okunamadı; erişilebilirlik doğrulanamadı.",
            "uncertainty": [accessibility.EQUIPMENT_DATA_UNAVAILABLE],
        },
        [],
        alternative=None,
        checked_at="2026-09-27T05:00:00+00:00",
    )
    assert result["level"] == "unverified" and result["comparable"] is False


def test_blocked_step_free_route_is_affected_and_has_no_invented_alternative() -> None:
    item = journey()
    # `_finish_route` returns this station reason when no path avoids the unverified lift.
    result = impact(
        item,
        {
            "available": False,
            "reason": "Sirkeci istasyonundaki asansör durumu doğrulanamadı ve bu istasyonu atlayan bir alternatif bulunamadı.",
            "uncertainty": [accessibility.NO_ALTERNATIVE],
        },
        [],
        alternative=None,
        checked_at="2026-09-27T05:00:00+00:00",
    )
    assert result["level"] == "affected"
    assert result["affected_needs"] == ["step_free"]
    assert result["alternative"] is None
    assert result["fingerprint"] == ["lift:sirkeci"]


def test_unverified_lift_route_without_station_name_is_affected_only_with_no_alternative_code() -> None:
    item = journey()
    # `_finish_route`'s bounded retry returns a route-wide lift reason with NO_ALTERNATIVE.
    result = impact(
        item,
        {
            "available": False,
            "reason": "Güzergâhtaki asansör durumları doğrulanamadı.",
            "uncertainty": [accessibility.NO_ALTERNATIVE],
        },
        [],
        alternative=None,
        checked_at="2026-09-27T05:00:00+00:00",
    )
    assert result["level"] == "affected" and result["alternative"] is None


def test_planner_alternative_is_used_but_operator_approval_must_match_it() -> None:
    item = journey()
    plan = {
        "available": True,
        "steps": [{"kind": "ride", "line": "M2"}],
        "extra_minutes": 4,
        "alternative_used": {"station": "Gayrettepe", "line": "M2", "reason": "İstasyonda asansör kaydı."},
        "alternatives_used": [
            {
                "station": "Gayrettepe",
                "line": "M2",
                "avoided_station": "Taksim",
                "reason": "Taksim istasyonundaki asansör durumu doğrulanamadı.",
            }
        ],
    }
    approval = {
        "alternative": {"station": "Gayrettepe", "line": "M2", "extra_minutes": 4},
        "operator_approved": True,
        "approved_text": "Onaylı yönlendirme metni.",
    }
    result = impact(item, plan, [], alternative=approval, checked_at="2026-09-27T05:00:00+00:00")
    assert result["level"] == "affected"
    assert result["alternative"] == {
        "station": "Gayrettepe",
        "line": "M2",
        "extra_minutes": 4,
        "reason": "İstasyonda asansör kaydı.",
        "operator_approved": True,
        "approved_text": "Onaylı yönlendirme metni.",
    }
    mismatch = {**approval, "alternative": {"station": "Sisli", "line": "M2"}}
    unapproved = impact(item, plan, [], alternative=mismatch, checked_at="2026-09-27T05:00:00+00:00")
    assert unapproved["alternative"]["operator_approved"] is False
    assert unapproved["alternative"]["approved_text"] is None


def test_notice_on_a_ride_line_affects_every_requested_need() -> None:
    item = journey(needs=["slow_walk"])
    result = impact(
        item,
        {"available": True, "steps": [{"kind": "ride", "line": "M7"}], "uncertainty": []},
        [{"line_name": "M7", "description": "Seferler aktarmalı yapılıyor.", "updated_at": "2026-09-26T08:00:00Z"}],
        alternative=None,
        checked_at="2026-09-27T05:00:00+00:00",
    )
    assert result["level"] == "affected" and result["affected_needs"] == ["slow_walk"]
    assert result["reasons"][0]["kind"] == "notice"
    assert result["reasons"][0]["source"] == "Metro İstanbul duyurusu"
    assert result["reasons"][0]["observed_at"] == "2026-09-26T08:00:00Z"


def test_slow_walk_does_not_turn_lift_only_evidence_into_an_impact() -> None:
    item = journey(needs=["slow_walk"])
    # `check_needs` accepts slow_walk, while `_finish_route` still inspects lifts for every need.
    result = impact(
        item,
        {
            "available": True,
            "steps": [{"kind": "ride", "line": "M2"}],
            "extra_minutes": 4,
            "alternative_used": {"station": "Gayrettepe", "line": "M2"},
            "alternatives_used": [
                {
                    "station": "Gayrettepe",
                    "line": "M2",
                    "avoided_station": "Taksim",
                    "reason": "Taksim istasyonundaki asansör durumu doğrulanamadı.",
                }
            ],
        },
        [],
        alternative=None,
        checked_at="2026-09-27T05:00:00+00:00",
    )
    assert result["level"] == "clear"
    assert result["reasons"][0]["informational"] is True
    assert result["alternative"]["extra_minutes"] == 4
    assert "az yürüme ölçülmedi" in result["headline"]


def test_unreadable_notice_source_is_unverified_and_has_no_fingerprint() -> None:
    result = impact(
        journey(),
        {"available": True, "steps": [{"kind": "ride", "line": "M2"}]},
        None,
        alternative=None,
        checked_at="2026-09-27T05:00:00+00:00",
    )
    assert result["level"] == "unverified" and result["fingerprint"] == []
    assert "sorun yok" not in result["headline"].casefold()


def test_clear_has_the_lift_record_caveat_and_turkish_clock_note() -> None:
    result = impact(
        journey(),
        {"available": True, "steps": [{"kind": "ride", "line": "M2"}], "uncertainty": []},
        [],
        alternative=None,
        checked_at="2026-09-27T05:00:00+00:00",
    )
    assert result["level"] == "clear"
    assert "kesin olarak kanıtlamaz" in result["reasons"][0]["text"]
    assert result["time_note"] == ("Yolculuk saatiniz 08.30. Bu kontrol şu anki kayda göredir; 08.30'daki durumu tahmin etmez.")


def test_changed_reports_stable_additions_and_resolutions_but_not_unknowns() -> None:
    result = {"comparable": True, "fingerprint": ["lift:sirkeci", "notice:m7:hash"]}
    assert changed(["lift:sirkeci", "notice:m2:old"], result) == {
        "new": ["notice:m7:hash"],
        "resolved": ["notice:m2:old"],
    }
    assert changed(["lift:sirkeci"], {"comparable": False, "fingerprint": []}) == {"new": [], "resolved": []}


def test_account_store_is_isolated_expires_after_inactivity_and_deletes_account_rows(tmp_path) -> None:
    now = [dt.datetime(2026, 9, 27, tzinfo=dt.UTC)]
    store = JourneyStore(tmp_path / "journeys.sqlite", clock=lambda: now[0])
    item = journey()
    store.save("account-a", item, consent_version="v1")
    store.save("account-b", item, consent_version="v1")
    assert len(store.items("account-a")) == len(store.items("account-b")) == 1
    store.delete("account-a", item.id)
    assert store.items("account-a") == [] and len(store.items("account-b")) == 1
    now[0] += dt.timedelta(days=91)
    assert store.items("account-b") == []
    store.save("account-b", item, consent_version="v1")
    assert store.delete_account("account-b") == 1
    assert store.items("account-b") == []
