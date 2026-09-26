"""Regression cases for deterministic institution routing."""

from __future__ import annotations

import json

import pytest
from test_agency_router import CASES

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.text import normalize_tr
from nabiz.console.agency_router import LINE_CONTEXT, METRO_LINE_CODES, RULES, AgencyKeywordRule, route

FIXES = [
    ("Metrobüs durağında lağım kokusu var", "iett", "iski", None),
    ("Sokakta lağım kokusu var", None, "iski", None),
    ("Otobüs durağında lağım taştı", "iett", "iski", None),
    ("Lağım patladı", None, "iski", None),
    ("Lağımdan fare çıkıyor", None, "iski", None),
    ("Foseptik taştı", None, "iski", None),
    ("Otopark önünde lağım kokusu", "ispark", "iski", None),
    ("Vapur iskelesinde lağım kokusu", "sehir_hatlari", "iski", None),
    ("Metro istasyonunda lağım kokusu", "metro", "iski", None),
    ("Yürüyen merdiven çalışmıyor", None, "metro", None),
    ("Yürüyen merdiven bozuk", None, "metro", None),
    ("Yürüyen bant arızalı", None, "metro", None),
    ("Taksim istasyonunda yürüyen bant çalışmıyor", None, "metro", None),
    ("M2 istasyonunda asansör çalışmıyor", None, "metro", None),
    ("M4 yürüyen merdiven çalışmıyor", None, "metro", None),
    ("M1 hattında arıza var", None, "metro", None),
    ("Kadıköy M4'te asansör bozuk", None, "metro", None),
    ("Otobüs durağının yanında çöp var", "iett", "ilce", True),
    ("Sokağımdaki çöp toplanmadı", None, "ilce", True),
    ("Çöp kamyonu gelmedi", None, "ilce", True),
    ("Çöplerim toplanmıyor", None, "ilce", True),
    ("Deniz otobüsü seferleri iptal mi?", "iett", None, None),
    # DECISIONS #45, closed: litter in a rail station, on a ferry or at a pier goes to its operator, not the district.
    ("Metro istasyonunda çöp birikmiş", "ilce", "metro", None),
    ("Metroda çöp var", "ilce", "metro", None),
    ("Tramvay durağında çöp birikmiş", "ilce", "metro", None),
    ("Tramvayda çöp var", "ilce", "metro", None),
    ("Vapurda çöp var", "ilce", "sehir_hatlari", None),
    ("İskelede çöp birikmiş", "ilce", "sehir_hatlari", None),
    ("Kadıköy iskelesinde çöpler toplanmamış", "ilce", "sehir_hatlari", None),
]

KEEPS = [
    ("Metrobüs durağında asansör çalışmıyor", "iett"),
    ("Metrobüs üst geçidinde yürüyen merdiven arızalı", "iett"),
    ("Metrobüs durağında çöp birikmiş", "iett"),
    ("Metrobüste çöp var", "iett"),
    ("Lağım gibi kokuyor", "iski"),
    ("Metrobüste klima çalışmıyor", "iett"),
    ("İSPARK otoparkında lağım kokusu", "ispark"),
    ("Metro İstanbul'a lağım kokusunu bildirmek istiyorum", "metro"),
    ("Kanalizasyon kokusu var", "iski"),
    ("Tramvay durağında bilet makinesi bozuk", "metro"),
    ("Üsküdar Marmaray asansörü bozuk", None),
    ("Marmaray istasyonunda yürüyen merdiven çalışmıyor", None),
    ("Alışveriş merkezinde yürüyen merdiven bozuk", None),
    ("100 m2 daire için emlak vergisi nereye ödenir?", "ilce"),
    ("Yolda çukur var", None),
    ("Sokak lambası yanmıyor", None),
    ("Elektrik kesintisi var", None),
    ("Otobüs şoförü kaba davrandı", "iett"),
    ("İstanbulkart yükleme yapılamıyor", "istanbulkart"),
    ("Doğalgaz kesintisi var", "igdas"),
]


@pytest.mark.parametrize("question,today_agency,expected_agency,expected_district_needed", FIXES)
def test_fixes_route_to_the_right_agency(question, today_agency, expected_agency, expected_district_needed):
    result = route(question)
    assert result.agency == expected_agency
    if expected_district_needed is not None:
        assert result.district_needed is expected_district_needed


def test_a_named_district_answers_the_litter_question():
    result = route("Kadıköy'de sokağımdaki çöp toplanmadı")
    assert (result.agency, result.district, result.district_needed) == ("ilce", "Kadıköy", False)


@pytest.mark.parametrize("question,expected_agency", KEEPS)
def test_keeps_stay_where_they_were(question, expected_agency):
    assert route(question).agency == expected_agency


def test_existing_cases_are_untouched():
    for question, expected_agency, expected_district_needed, expected_district in CASES:
        result = route(question)
        assert (result.agency, result.district_needed, result.district) == (
            expected_agency,
            expected_district_needed,
            expected_district,
        ), question


def test_line_codes_match_the_metro_station_list():
    fixture_path = REPO_ROOT / "tests" / "fixtures" / "metro_stations.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture_codes = {row["LineName"].lower() for row in fixture["Data"]}
    assert set(METRO_LINE_CODES) == fixture_codes | {"m1"}


def test_a_line_code_needs_a_transit_word():
    assert route("100 m2 daire için emlak vergisi nereye ödenir?").agency == "ilce"
    assert route("100 m2 dairede arıza var").agency is None
    assert route("Faturamda 30 m3 görünüyor, sayaç arızalı mı?").agency is None
    assert route("M2 istasyonunda asansör çalışmıyor").agency == "metro"


def test_unless_vetoes_only_its_own_rule():
    assert route("Marmaray istasyonunda yürüyen merdiven çalışmıyor").agency is None
    assert route("Metro istasyonunda yürüyen merdiven bozuk").agency == "metro"


def test_emergency_still_wins():
    result = route("Metrobüs durağında gaz kokusu var")
    assert result.emergency is True
    assert result.agency is None


def test_the_matched_word_is_reported():
    assert route(FIXES[0][0]).matched == "lagim"
    assert route(FIXES[9][0]).matched == "yuruyen merdiven"


def test_every_fix_text_is_a_known_agency():
    agencies_path = REPO_ROOT / "data" / "agencies.json"
    agency_ids = {item["id"] for item in json.loads(agencies_path.read_text(encoding="utf-8"))["agencies"]}
    allowed = agency_ids | {"ilce", None}
    assert all(expected in allowed for _, _, expected, _ in FIXES)


def test_rules_stay_plain_data():
    assert all(isinstance(rule, AgencyKeywordRule) for rule in RULES)
    assert all(normalize_tr(value) == value for value in LINE_CONTEXT)
    assert all(normalize_tr(value) == value for rule in RULES for value in (*rule.unless, *rule.context))
