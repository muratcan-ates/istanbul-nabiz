"""Turkish text folding: one definition, and every call site that relies on it.

Until 2026-09-23 there were three public ``normalize_tr`` functions (``ibb_mcp.gtfs``,
``ibb_mcp.sources.metro``, ``ibb_mcp.sources.places``) and which fold a caller got depended
on the module it happened to import. Two of them turned out to be the same function
written twice. Checked on 2026-09-23 against the laptop's full İETT GTFS export (gitignored,
so not re-runnable from a clone): over its 15 386 stop names and the short and long names of
its 9 274 routes, the gazetteer's 276 names and districts, and the recorded 248 metro and 28
air-quality stations, the gtfs and places copies returned the same key for every string.
They differ only on letters with no ASCII skeleton (``ß``, ``Ø``, ``æ``), which the gtfs copy
dropped and the one kept here keeps; no İstanbul name in that data has one. The metro copy
is genuinely different: it keeps punctuation, because its station search ranks a hit on the
real spelling above one that only matched once punctuation was squashed. That behaviour now
has its own name, :func:`ibb_mcp.text.fold_tr`.

The tables below were written against the three old copies before they were replaced, so
they pin exactly what each caller used to get. The call-site tests after them pin the
behaviour a user sees, on real Turkish input: dotted and dotless i, ş, ğ, circumflexes,
punctuation, "Mah.", shouted and lower-case spellings.
"""

from __future__ import annotations

import pytest
from conftest import offline_settings

from ibb_mcp.gtfs import get_index
from ibb_mcp.sources.airquality import AirQualitySource
from ibb_mcp.sources.metro import MetroSource
from ibb_mcp.sources.places import PlaceIndex
from ibb_mcp.text import (
    LOOSE_RANK_PENALTY,
    fold_tr,
    normalize_tr,
    rank_match,
    rank_match_loose,
    squash_punctuation,
)

#: (input, normalize_tr, fold_tr). The middle column is what the old gtfs and places copies
#: both returned; the last is what the old metro copy returned.
TABLE = [
    ("Şişli-Mecidiyeköy", "sisli mecidiyekoy", "sisli-mecidiyekoy"),
    ("SISLI-MECIDIYEKOY", "sisli mecidiyekoy", "sisli-mecidiyekoy"),
    ("İSTİKLAL CADDESİ", "istiklal caddesi", "istiklal caddesi"),
    ("Kadıköy, iskele", "kadikoy iskele", "kadikoy, iskele"),
    ("KADIKÖY İSKELE", "kadikoy iskele", "kadikoy iskele"),
    ("Ataşehir Mah.", "atasehir mah", "atasehir mah."),
    ("Beşiktaş Mah. (Sinanpaşa)", "besiktas mah sinanpasa", "besiktas mah. (sinanpasa)"),
    ("4.Levent", "4 levent", "4.levent"),
    ("4. Levent", "4 levent", "4. levent"),
    ("50.Yıl-Baştabya", "50 yil bastabya", "50.yil-bastabya"),
    ("Boğaziçi Ü./Hisarüstü", "bogazici u hisarustu", "bogazici u./hisarustu"),
    ("ĞÜŞİÖÇ ğüşıöç", "gusioc gusioc", "gusioc gusioc"),
    ("Işık", "isik", "isik"),
    ("IĞDIR", "igdir", "igdir"),
    # "İ" typed as I + COMBINING DOT ABOVE, as some keyboards and copy-pastes deliver it.
    ("İstanbul", "istanbul", "istanbul"),
    ("Âşıklar Tepesi", "asiklar tepesi", "asiklar tepesi"),
    ("  çift   boşluk  ", "cift bosluk", "cift bosluk"),
    ("D-100", "d 100", "d-100"),
    ("M4", "m4", "m4"),
    ("m 4", "m 4", "m 4"),
    ("500T", "500t", "500t"),
    ("Yenikapı\tAktarma\nMerkezi", "yenikapi aktarma merkezi", "yenikapi aktarma merkezi"),
    ("Hastane - Adliye", "hastane adliye", "hastane - adliye"),
    ("ŞİFA SONDURAK", "sifa sondurak", "sifa sondurak"),
    ("Kavacık Köprüsü", "kavacik koprusu", "kavacik koprusu"),
    ("", "", ""),
]


@pytest.mark.parametrize(("text", "words", "_spelling"), TABLE)
def test_normalize_tr_folds_case_letters_diacritics_and_punctuation(text: str, words: str, _spelling: str) -> None:
    assert normalize_tr(text) == words


@pytest.mark.parametrize(("text", "_words", "spelling"), TABLE)
def test_fold_tr_keeps_the_punctuation_of_the_real_spelling(text: str, _words: str, spelling: str) -> None:
    assert fold_tr(text) == spelling


def test_none_folds_to_the_empty_key() -> None:
    assert normalize_tr(None) == "" and fold_tr(None) == ""


@pytest.mark.parametrize(("text", "_words", "spelling"), TABLE)
def test_the_two_folds_differ_only_in_punctuation(text: str, _words: str, spelling: str) -> None:
    """Squashed, the two keys are the same: the loose pass of the station search relies on it."""
    assert squash_punctuation(normalize_tr(text)) == squash_punctuation(fold_tr(text))


def test_rank_match_orders_exact_prefix_substring() -> None:
    assert rank_match("levent", "levent") == 0
    assert rank_match("lev", "levent") == 1
    assert rank_match("vent", "levent") == 2
    assert rank_match("taksim", "levent") is None
    assert rank_match("", "levent") is None


def test_a_loose_match_always_ranks_below_a_real_one() -> None:
    query = fold_tr("4. Levent")
    assert rank_match_loose(query, squash_punctuation(query), "4.LEVENT") == 0 + LOOSE_RANK_PENALTY
    assert rank_match_loose(fold_tr("4.Levent"), "4levent", "4.LEVENT") == 0


# --------------------------------------------------------------------------------------
# call sites, as a user meets them
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("query", "first"),
    [
        ("sisli", "Şişli"),
        ("ŞİŞLİ", "Şişli"),
        ("Kadıköy, iskele", "Kadıköy İskele"),
        ("kadikoy", "Kadıköy İskele"),  # through the alias table, which is keyed by the folded form
        ("USKUDAR", "Üsküdar İskele"),
        ("Taksim Meydanı", "Taksim Meydanı"),
    ],
)
def test_the_gazetteer_finds_a_place_however_it_is_typed(query: str, first: str) -> None:
    assert PlaceIndex.load(offline_settings()).resolve(query, limit=3)[0].name == first


def test_a_place_label_names_its_district_only_when_it_differs() -> None:
    index = PlaceIndex.load(offline_settings())
    district = next(place for place in index.places if place.kind == "district" and place.name == "Şişli")
    assert district.label == "Şişli"


@pytest.mark.parametrize("query", ["Kavacık Köprüsü", "kavacik koprusu", "KAVACIK KÖPRÜSÜ"])
def test_a_stop_search_ignores_case_and_turkish_letters(query: str) -> None:
    stops = get_index(offline_settings()).search_stops(query, limit=3)
    assert [stop.stop_code for stop in stops] == ["220641", "220642"]


def test_a_stop_search_prefers_the_exact_name() -> None:
    index = get_index(offline_settings())
    assert index.search_stops("şifa", limit=1)[0].stop_code == "116301"
    assert [stop.stop_code for stop in index.search_stops("ŞİFA SONDURAK", limit=3)] == ["401351"]


@pytest.mark.parametrize("code", ["500T", "500t", " 500T "])
def test_a_line_code_is_found_whatever_its_case(code: str) -> None:
    assert len(get_index(offline_settings()).routes_for_short_name(code)) == 27


@pytest.mark.parametrize(
    ("query", "first"),
    [
        ("sisli", ("Şişli-Mecidiyeköy", "M2")),
        ("SISLI MECIDIYEKOY", ("Şişli-Mecidiyeköy", "M2")),
        ("4. Levent", ("4.Levent", "M2")),
        ("Hastane Adliye", ("Hastane-Adliye", "M4")),
        ("yenikapi", ("Yenikapı", "M1A")),
        # Two stations, two spellings: the one the user typed exactly comes first. This is
        # the one behaviour the punctuation-keeping fold exists for.
        ("Boğaziçi Ü.-Hisarüstü", ("Boğaziçi Ü.-Hisarüstü", "M6")),
        ("Boğaziçi Ü./Hisarüstü", ("Boğaziçi Ü./Hisarüstü", "F4")),
    ],
)
async def test_a_metro_station_is_found_however_it_is_typed(ctx, query: str, first: tuple[str, str]) -> None:
    found = await MetroSource(ctx).find_station(query)
    assert (found[0].name, found[0].line_name) == first


async def test_every_line_of_an_interchange_is_returned(ctx) -> None:
    found = await MetroSource(ctx).find_station("yenikapi")
    assert [station.line_name for station in found[:3]] == ["M1A", "M1B", "M2"]


async def test_a_dotless_i_is_not_silently_matched_to_nothing_in_particular(ctx) -> None:
    assert await MetroSource(ctx).find_station("ısparta") == []


@pytest.mark.parametrize(("line", "found"), [("M7", True), ("m7", True), ("m 7", False), ("M4", False)])
async def test_a_line_notice_matches_the_line_code_in_any_case(ctx, line: str, found: bool) -> None:
    """``"m 7"`` is *not* ``M7``: the fold keeps spaces, and nothing has asked for more."""
    assert (await MetroSource(ctx).line_status(line) is not None) is found


@pytest.mark.parametrize(
    ("query", "station"),
    [("Kadıköy", "Kadıköy"), ("kadikoy", "Kadıköy"), ("sariyer", "Sarıyer"), ("SARIYER", "Sarıyer"), ("üsküdar", "Üsküdar 1")],
)
async def test_an_air_quality_station_is_found_by_name_or_district(ctx, query: str, station: str) -> None:
    found = await AirQualitySource(ctx).find_station(query)
    assert found is not None and found.name == station
