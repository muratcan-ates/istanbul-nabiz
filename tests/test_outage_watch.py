from __future__ import annotations

import datetime as dt
import json

from nabiz.console.outage_watch import (
    MAX_NOTE,
    PATH_ENV,
    REPEAT_MINUTES,
    TTL_DAYS,
    OutageStore,
    build_history,
    history_for,
    ledger_confirmation,
    ledger_seen,
    normal_district,
    normal_neighbourhood,
    outage_path,
)
from nabiz.console.pii_guard import mask_labels
from nexus_core.ledger import Ledger

TEST_EMAIL = "someone" + "@example.test"


class MutableClock:
    def __init__(self) -> None:
        self.value = dt.datetime(2026, 9, 27, 12, 0, tzinfo=dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.value

    def advance(self, **parts: int) -> None:
        self.value += dt.timedelta(**parts)


def test_paths_district_alias_and_neighbourhood_safety(tmp_path) -> None:
    assert outage_path({PATH_ENV: str(tmp_path / "outage.db")}) == tmp_path / "outage.db"
    assert outage_path({"NEXUS_DB_PATH": str(tmp_path / "nexus.db")}) == tmp_path / "outage_watch.db"
    assert normal_district("kadikoy") == "Kadıköy"
    assert normal_district("Eyüp") == "Eyüpsultan"
    assert normal_district("İstanbul") is None
    assert normal_neighbourhood("Caferağa\u200b") == ("Caferağa", 1)
    assert normal_neighbourhood("CAFERAĞA") == ("Caferağa", 0)
    assert normal_neighbourhood("19 Mayıs") == ("19 Mayıs", 0)
    assert normal_neighbourhood("Caferağa Sokak 3") is None
    assert normal_neighbourhood("Caferağa No. 3") is None
    assert normal_neighbourhood("Caferağa No.27") is None
    assert normal_neighbourhood("555 123 45 67") is None
    assert normal_neighbourhood("a") is None
    assert MAX_NOTE == 280 and REPEAT_MINUTES == 30 and TTL_DAYS == 7


def test_store_repeat_ttl_seen_area_counts_and_ledger_minimisation(tmp_path) -> None:
    clock = MutableClock()
    store = OutageStore(tmp_path / "outage.db", clock=clock)
    ledger = Ledger(tmp_path / "ledger.db", clock=clock)
    masked, count, kinds = mask_labels(TEST_EMAIL)
    row = store.create(
        "Kadıköy", "Caferağa", announced_end="14:00", note_masked=masked, masked_count=count, masked_kinds=kinds, lang="tr"
    )
    expiry = row["expires_at"]
    assert row["status"] == "waiting"
    assert row["confirmations"] == [{"at": clock().isoformat(), "source": "user", "announced_end": "14:00"}]
    assert TEST_EMAIL not in json.dumps(row, ensure_ascii=False)
    assert store.confirm_again(row["code"], announced_end=None) is None
    clock.advance(minutes=REPEAT_MINUTES)
    repeated = store.confirm_again(row["code"], announced_end="15:10")
    assert repeated is not None and repeated["code"] == row["code"]
    assert len(repeated["confirmations"]) == 2 and repeated["expires_at"] == expiry
    ledger_confirmation(ledger, repeated)
    seen = store.mark_seen(row["code"])
    assert seen and seen["status"] == "seen"
    ledger_seen(ledger, seen, "operatör (simüle)")
    assert store.mark_seen(row["code"]) is None
    area = store.area_counts()[0]
    assert (area["district"], area["neighbourhood"], area["waiting"], area["confirmations"]) == ("Kadıköy", "Caferağa", 0, 2)
    entries = ledger.entries(kinds=("outage_confirmation", "outage_seen"))
    assert [entry.kind for entry in entries] == ["outage_confirmation", "outage_seen"]
    serialized = json.dumps([entry.detail for entry in entries], ensure_ascii=False)
    assert TEST_EMAIL not in serialized and masked not in serialized
    assert all(
        set(entry.detail) == {"kind", "code", "district", "neighbourhood", "confirmations", "note_chars"} for entry in entries
    )
    clock.advance(days=TTL_DAYS)
    assert store.get(row["code"]) is None
    assert store.items() == []


def test_history_reads_reordered_headers_splits_neighbourhoods_and_excel_dates() -> None:
    snapshot = {
        "header": ["MAHALLE", "CALISMA YERİ", "ILCE", "KESİNTİ SEBEP", "ARIZA KESİNTİ TARİHİ"],
        "rows": [
            ["CAFERAĞA MAH,OSMANAĞA MAH", "ignored work-site field", "KADIKÖY", "HAT ARIZASI", "45300"],
            ["CAFERAĞA MAH", "ignored again", "Kadıköy", "HAT ARIZASI", "08/01/2024 09:10:00"],
            ["CAFERAĞA MAH", "", "Kadıköy", "VANA ÇALIŞMASI", "01/01/2025"],
        ],
    }
    result = build_history(snapshot)
    area = history_for(result, "kadikoy", "caferağa")
    assert area == {
        "district": "Kadıköy",
        "neighbourhood": "Caferağa",
        "count": 2,
        "causes": [{"text": "HAT ARIZASI", "count": 2}],
    }
    assert history_for(result, "Kadıköy", "Rıhtım") is None
    assert result["areas"][-1]["neighbourhood"] in {"Caferağa", "Osmanağa"}


def test_compact_history_snapshot_keeps_only_area_and_reason_aggregates() -> None:
    from nabiz.console.outage_watch import SOURCES_PATH

    data = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    history = data["history"]
    caferaga = history_for(history, "Kadıköy", "Caferağa")
    assert history["source_records"] == 6410
    assert caferaga and caferaga["count"] == 28
    assert len(caferaga["causes"]) <= 3
    serialized = json.dumps(history, ensure_ascii=False)
    assert "CALISMA YERİ" not in serialized and "GÖNÜLLÜ CAD" not in serialized
