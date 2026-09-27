"""Whole-token place matching, intent fallback and shadow regression tests.

The eval schema in this file is local to the place guard, not run_eval.py:
{"id": str, "lang": "tr"|"en", "journey": "U01-yeradi", "question": str,
 "expected_place": str|None, "expected_reason": str, "expected_fallback": str|None,
 "notes": str}.
"""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import pytest

from ibb_mcp.text import normalize_tr
from ibb_mcp.tools import Nabiz
from nabiz.agent import LlmConfig, NabizAgent
from nabiz.agent.place_guard import (
    COMMON_WORD_PLACES,
    REASONS,
    SUFFIXES,
    explain,
    fallback_tool,
    find_place,
    find_places,
    intents,
    split_needs,
)

ROOT = Path(__file__).resolve().parents[1]
EVAL_PATH = ROOT / "eval" / "journeys.yeradi.jsonl"


def _place_names() -> list[str]:
    with (ROOT / "data" / "reference" / "places.csv").open(encoding="utf-8", newline="") as handle:
        return [row["name"].strip() for row in csv.DictReader(handle) if row.get("name", "").strip()]


#: Account and ferry questions E48's official path answers before any routing (``official_intent``).
#: ``tests/test_resmi_yol.py`` forbids them in ``eval/journeys*.jsonl``, so their place checks live here.
OFFICIAL_PATH_ROWS = [
    {"id": case[0], "lang": case[1], "question": case[2], "expected_place": case[3], "expected_reason": case[4],
     "expected_fallback": case[5]}
    for case in (
        ('yeradi-tr-02', 'tr', 'Faturamı ödemek için hangi sayfaya bakayım?', None, 'inside_word', 'ibb_services_search'),
        ('yeradi-tr-05', 'tr', 'Kabataş Adalar vapuru saatleri', 'Kabataş', 'intent_schedule', 'ibb_services_search'),
        ('yeradi-tr-30', 'tr', 'Kabataş vapurunun kalkış saatleri nedir?', 'Kabataş', 'intent_schedule', 'ibb_services_search'),
        ('yeradi-tr-34', 'tr', 'Vapur seferi saat kaçta kalkıyor?', None, 'intent_schedule', 'ibb_services_search'),
        ('yeradi-tr-38', 'tr', 'Rami faturamı öder mi?', 'Rami', 'intent_billing', 'ibb_services_search'),
        ('yeradi-tr-39', 'tr', "Kadıköy'de vapur saatleri nerede yazar?", 'Kadıköy', 'place_ok', 'places_resolve'),
        ('yeradi-en-03', 'en', 'Kabataş ferry timetable', 'Kabataş', 'intent_schedule', 'ibb_services_search'),
        ('yeradi-en-09', 'en', 'Could I pay my bill in Taksim?', 'Taksim', 'intent_billing', 'ibb_services_search'),
        ('yeradi-en-14', 'en', 'Cancel my subscription at Rami', 'Rami', 'intent_billing', 'ibb_services_search'),
        ('yeradi-en-18', 'en', 'Do ferries have a timetable?', None, 'intent_schedule', 'ibb_services_search'),
        ('yeradi-en-21', 'en', 'Where can I learn the Kabataş ferry departure time?', 'Kabataş', 'intent_schedule',
         'ibb_services_search'),
    )
]


def _eval_rows() -> list[dict]:
    return [json.loads(line) for line in EVAL_PATH.read_text(encoding="utf-8").splitlines() if line.strip()] + OFFICIAL_PATH_ROWS


@pytest.fixture
def route_agent(ctx) -> NabizAgent:
    return NabizAgent(Nabiz(ctx), config=LlmConfig(), system_prompt="test prompt")


@pytest.mark.parametrize("row", _eval_rows(), ids=lambda row: row["id"])
def test_eval_case_has_the_declared_place_reason_and_fallback(row: dict) -> None:
    actual = explain(row["question"], _place_names())
    assert actual["place"] == row["expected_place"]
    assert actual["reason"] == row["expected_reason"]
    assert actual["fallback"] == row["expected_fallback"]


def test_suffixes_and_common_word_places_are_explicit_and_in_the_gazetteer() -> None:
    names = {normalize_tr(name) for name in _place_names()}
    assert isinstance(SUFFIXES, tuple)
    assert isinstance(COMMON_WORD_PLACES, frozenset)
    required = {
        "a", "e", "ya", "ye", "i", "u", "yi", "yu", "in", "un", "nin", "nun", "da", "de", "ta", "te",
        "dan", "den", "tan", "ten", "daki", "deki", "taki", "teki", "la", "le", "yla", "yle",
    }
    assert required <= set(SUFFIXES)
    assert names >= COMMON_WORD_PLACES


def test_common_word_exceptions_each_have_a_source_row() -> None:
    expected = {
        "bebek", "moda", "mobil", "huzur", "kilise", "meclis", "vatan", "carsi", "cakmak", "fener",
        "yildiz", "kartal", "levent", "fatih", "otogar",
    }
    assert expected == COMMON_WORD_PLACES


def test_g1_whole_tokens_suffixes_softening_and_common_words() -> None:
    names = _place_names()
    assert find_place("İSKİ faturamı nereden sorgular ve öderim?", names) is None
    assert find_place("Rami nerede?", names).name == "Rami"
    assert [match.name for match in find_places("Rami nerede, bebek arabasıyla metroya binebilir miyim?", names)] == ["Rami"]
    assert [match.name for match in find_places("Rami nerede ve bebek arabasıyla metroya binebilir miyim?", names)] == ["Rami"]
    assert find_place("Kadıköyden Moda'ya", names).name == "Kadıköy"
    assert find_place("Bebek arabasıyla metroya binebilir miyim?", names) is None
    assert find_place("Bebek'istanbul hakkında konuşalım", names) is None
    assert find_place("Bebek'te otopark var mı?", names).name == "Bebek"
    assert find_place("Bebeğe nasıl giderim?", names).suffix == "e"
    match = find_place("Taksim Meydanı'nda otopark var mı?", names)
    assert match.name == "Taksim Meydanı" and match.suffix == "nda"
    assert find_place("Levent metro", names).name == "Levent"
    assert find_place("Fatih Bey'e ulaşmak istiyorum", names) is None
    assert find_place("Fatih'te hava nasıl?", names).name == "Fatih"


def test_g2_service_intents_beat_the_coordinate_fallback() -> None:
    names = _place_names()
    billing = explain("İSKİ faturamı nereden sorgular ve öderim?", names)
    assert billing == {
        "place": None,
        "reason": "inside_word",
        "intents": ["billing"],
        "fallback": "ibb_services_search",
    }
    schedule = explain("Kabataş Adalar vapuru saatleri", names)
    assert schedule["place"] == "Kabataş"
    assert schedule["intents"] == ["schedule"]
    assert schedule["fallback"] == "ibb_services_search"
    assert fallback_tool("Kabataş nerede, vapur saatleri?", find_place("Kabataş nerede, vapur saatleri?", names)) == (
        "places_resolve", {"query": "Kabataş"}
    )
    assert fallback_tool("Rami nerede?", find_place("Rami nerede?", names)) == ("places_resolve", {"query": "Rami"})
    assert "billing" not in intents("Odun alabilir miyim?")
    assert intents("Somewhere is my bill") == frozenset({"billing"})
    assert fallback_tool("Somewhere is my bill", None) == (
        "ibb_services_search", {"query": "Somewhere is my bill"}
    )
    assert set(REASONS) == {
        "place_ok", "inside_word", "common_word_no_cue", "intent_billing", "intent_schedule", "intent_procedure", "no_place",
    }


def test_find_places_returns_non_overlapping_names_in_question_order() -> None:
    matches = find_places("Kadıköyden Moda'ya", _place_names())
    assert [match.name for match in matches] == ["Kadıköy", "Moda"]
    assert [match.suffix for match in matches] == ["den", "ya"]


def test_find_places_prefers_the_long_name_at_an_overlapping_position() -> None:
    matches = find_places("Taksim Meydanı'nda otopark var mı?", _place_names())
    assert [match.name for match in matches] == ["Taksim Meydanı"]


def test_find_place_keeps_the_longest_match_even_when_it_starts_later() -> None:
    match = find_place("Taksim'den Taksim Meydanı'na", _place_names())
    assert match.name == "Taksim Meydanı"


def test_split_needs_keeps_place_specific_fallbacks() -> None:
    parts = split_needs("Kabataş vapuru saatleri ve Kadıköy'de otopark", _place_names())
    assert len(parts) == 2
    assert parts[0]["place"] == "Kabataş"
    assert "schedule" in parts[0]["intents"] and parts[0]["fallback"] == "ibb_services_search"
    assert parts[1]["place"] == "Kadıköy"
    assert parts[1]["intents"] == [] and parts[1]["fallback"] == "places_resolve"


def test_split_needs_copies_shared_constraints_to_every_part() -> None:
    parts = split_needs("Akşam boşum, az yürürüm; Beşiktaş'ta kurs ve oraya ulaşım", _place_names())
    assert len(parts) == 3
    assert parts[1]["place"] == "Beşiktaş"
    assert all({"aksam", "az yuruyorum"} <= set(part["constraints"]) for part in parts)


def test_split_needs_accepts_english_and_turkish_conjunctions() -> None:
    names = _place_names()
    assert len(split_needs("Rami and Moda", names)) == 2
    assert len(split_needs("Rami bir de Moda", names)) == 2
    assert len(split_needs("Rami, Moda", names)) == 2


def test_split_needs_returns_one_part_without_a_separator() -> None:
    parts = split_needs("Rami nerede?", _place_names())
    assert len(parts) == 1 and parts[0]["place"] == "Rami"


def test_place_guard_imports_no_upper_layers_or_network_clients() -> None:
    source = (ROOT / "src" / "nabiz" / "agent" / "place_guard.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported |= {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(name.startswith(("ibb_mcp.sources", "nabiz.console", "nabiz.web")) for name in imported)
    assert not any(name == "socket" or name.startswith(("urllib", "httpx")) for name in imported)


# Route inputs are literal copies of the five source test files named in E64.
SHADOW_ROUTE_QUESTIONS = (
    ("tests/test_faithfulness.py", "Taksim'de hangi otoparkta yer var?"),
    ("tests/test_faithfulness.py", "M4'te arıza var mı?"),
    ("tests/test_faithfulness.py", "Kartal istasyonunda asansör var mı?"),
    ("tests/test_faithfulness.py", "Kartal istasyonunda asansör çalışıyor mu?"),
    ("tests/test_faithfulness.py", "Kartal istasyonunda WC var mı?"),
    ("tests/test_faithfulness.py", "Beşiktaş'ta hava kalitesi nasıl?"),
    ("tests/test_faithfulness.py", "Beşiktaş'ta koşu için hava ne zaman uygun?"),
    ("tests/test_faithfulness.py", "Şu an trafik nasıl?"),
    ("tests/test_faithfulness.py", "Verinin yaşı ne kadar?"),
    ("tests/test_faithfulness.py", "hava kalitesi nasıl?"),
    ("tests/test_faithfulness.py", "M4'te arıza var mı?"),
    ("tests/test_faithfulness.py", "M4te arıza var mı?"),
    ("tests/test_faithfulness.py", "M4ün durumu ne?"),
    ("tests/test_faithfulness.py", "500T 4. Levent metro durağına ne zaman gelir?"),
    ("tests/test_faithfulness.py", "Havalimanına nasıl giderim?"),
    ("tests/test_faithfulness.py", "Havalimanında ne var?"),
    ("tests/test_faithfulness.py", "Havaalanına gidiyorum"),
    ("tests/test_faithfulness.py", "500T otobüsü 4. Levent durağına ne zaman gelir?"),
    ("tests/test_faithfulness.py", "500T hattı Şifa durağına kaç dakika sonra gelir?"),
    ("tests/test_faithfulness.py", "500T 4. Levent metro durağına ne zaman gelir?"),
    ("tests/test_faithfulness.py", "Verinin yaşı ne kadar?"),
    ("tests/test_faithfulness.py", "Veri ne kadar güncel?"),
    ("tests/test_faithfulness.py", "Bu veri güncel mi?"),
    ("tests/test_metro_route.py", "Gece metrosu hangi günler çalışıyor?"),
    ("tests/test_metro_route.py", "Gece metrosu seferleri saat kaçta başlıyor?"),
    ("tests/test_metro_route.py", "M4 24 saat açık mı?"),
    ("tests/test_metro_route.py", "Metro hafta sonu çalışıyor mu?"),
    ("tests/test_metro_route.py", "Metroya evcil hayvanla binebilir miyim?"),
    ("tests/test_metro_route.py", "Metro İstanbul'a şikâyet nasıl iletilir?"),
    ("tests/test_metro_route.py", "Metro istasyonlarında erişilebilirlik hizmetleri neler?"),
    ("tests/test_metro_route.py", "M2'nin son seferi kaçta?"),
    ("tests/test_metro_route.py", "M2 metro hattında arıza var mı?"),
    ("tests/test_metro_route.py", "Metro çalışıyor mu?"),
    ("tests/test_metro_route.py", "M4'te arıza var mı?"),
    ("tests/test_metro_route.py", "Marmaray'da aksaklık var mı?"),
    ("tests/test_i18n.py", "When does the 500T bus arrive at Kartal?"),
    ("tests/test_i18n.py", "What facilities does Kartal station have?"),
    ("tests/test_i18n.py", "Which car parks near Taksim have space?"),
    ("tests/test_i18n.py", "What is the air quality in Taksim?"),
    ("tests/test_open_data_chat.py", "İBB'nin otopark verisi var mı?"),
    ("tests/test_open_data_chat.py", "Mobilite kategorisinde hangi veri setleri var?"),
    ("tests/test_open_data_chat.py", "Does İBB publish open data on bike-share stations?"),
    ("tests/test_open_data_chat.py", "Enerji verisi var mı?"),
    ("tests/test_open_data_chat.py", "Kadıköy'de otopark var mı?"),
    ("tests/test_open_data_chat.py", "Veri ne kadar güncel?"),
    ("tests/test_open_data_chat.py", "Trafik şu an nasıl?"),
    ("tests/test_open_data_chat.py", "İBB Açık Veri Portalında yayımlanmayan bir veri setini nasıl talep edebilirim?"),
    ("tests/test_quick_api.py", "500T 4. Levent metro durağına ne zaman gelir?"),
    ("tests/test_quick_api.py", "When does the 500T arrive at 4. Levent Metro stop?"),
    ("tests/test_quick_api.py", "Yenikapı istasyonunda merdivensiz bir yol var mı?"),
    ("tests/test_quick_api.py", "Can I travel step-free through Yenikapı station?"),
    ("tests/test_quick_api.py", "Taksim'e 20 dakika sonra varıyorum, yakınında hangi otoparkta yer var?"),
    ("tests/test_quick_api.py", "Which car parks near Taksim have free spaces?"),
    ("tests/test_quick_api.py", "M4'te arıza veya çalışma var mı?"),
    ("tests/test_quick_api.py", "Is there a disruption on the M4 line?"),
    ("tests/test_quick_api.py", "Vapur sefer saatlerini nereden öğrenirim?"),
    ("tests/test_quick_api.py", "İstanbulkart Plus nedir, nasıl başvurulur?"),
    ("tests/test_quick_api.py", "QR ile ulaşımda nasıl ödeme yaparım?"),
    ("tests/test_quick_api.py", "İstanbul Senin’de hangi faturaları ödeyebilirim?"),
    ("tests/test_quick_api.py", "Askıda Fatura’dan nasıl destek olurum?"),
    ("tests/test_quick_api.py", "Sosyal yardım için 153 dışında hangi kanallar var?"),
    ("tests/test_quick_api.py", "153’e nasıl başvuru yaparım?"),
    ("tests/test_quick_api.py", "153 başvurumu nereden takip ederim?"),
    ("tests/test_quick_api.py", "İstanbul Senin’den şikâyet oluşturabilir miyim?"),
    ("tests/test_quick_api.py", "153’e WhatsApp’tan yazabilir miyim?"),
)

# Old substring matches that were false place detections, or newly valid softened forms.
EXPECTED_DIFFERENCES = {
    "Mobilite kategorisinde hangi veri setleri var?": ("Mobil", None, "Mobil sözcüğü Mobilite kelimesinin içinde kalıyor."),
    "İSKİ faturamı nereden sorgular ve öderim?": ("Rami", None, "Rami yalnız faturamı kelimesinin içinde geçiyor."),
    "Faturamı ödemek için hangi sayfaya bakayım?": ("Rami", None, "Rami yalnız faturamı kelimesinin içinde geçiyor."),
    "Bebek arabasıyla metroya binebilir miyim?": ("Bebek", None, "Bebek burada bebek arabası anlamında kullanılıyor."),
    "Bebek'istanbul hakkında konuşalım": ("Bebek", None, "Bilinmeyen apostrof devamı yer eki ipucu sayılmaz."),
    "Rami nerede, bebek arabasıyla metroya binebilir miyim?": (
        "Bebek", "Rami", "Nerede ipucu başka parçadaki bebek sözcüğünü yer yapmaz."
    ),
    "Rami nerede ve bebek arabasıyla metroya binebilir miyim?": (
        "Bebek", "Rami", "Nerede ipucu bağlaçtan sonraki sözcüğü yer yapmaz."
    ),
    "Bebekler için metro uygun mu?": ("Bebek", None, "Çoğul ek yer adı eki değildir."),
    "Yıldızlı bir gökyüzü görmek istiyorum": ("Yıldız", None, "Türetme eki yer adı eki değildir."),
    "Fatih Bey'e ulaşmak istiyorum": ("Fatih", None, "Hitap edilen kişi, bir yer ipucu vermiyor."),
    "Moda dergisi önerir misin?": ("Moda", None, "Moda sözcüğü dergi konusudur."),
    "Huzur arıyorum": ("Huzur", None, "Huzur sıradan sözcüktür ve yer ipucu yoktur."),
    "Kilise mimarisi hakkında bilgi verir misin?": ("Kilise", None, "Kilise sıradan sözcüktür ve yer ipucu yoktur."),
    "Meclis kararları nasıl yayımlanıyor?": ("Meclis", None, "Meclis sıradan sözcüktür ve yer ipucu yoktur."),
    "Vatan borcu nasıl ödenir?": ("Vatan", None, "Vatan sıradan sözcüktür ve yer ipucu yoktur."),
    "Fatih Bey için randevu alabilir miyim?": ("Fatih", None, "Kişi adı yer sorusu oluşturmuyor."),
    "Fener ışığı söndü": ("Fener", None, "Fener sıradan sözcüktür ve yer ipucu yoktur."),
    "Kartal kuşları göç ediyor": ("Kartal", None, "Kartal burada kuş anlamında kullanılıyor."),
    "Çakmak ateşi nasıl yanar?": ("Çakmak", None, "Çakmak sıradan sözcüktür ve yer ipucu yoktur."),
    "Mobil cihazım çalışmıyor": ("Mobil", None, "Mobil burada sıfattır ve yer ipucu yoktur."),
    "Otogarlar hafta sonu açık mı?": ("Otogar", None, "Çoğul ek yer adı eki değildir."),
    "Yildizli means starry in Turkish": ("Yıldız", None, "İngilizce açıklamadaki türetme ekli sözcük yer değildir."),
}
EXPECTED_ADDITIONS = {
    "Bebeğe nasıl giderim?": (None, "Bebek", "Ünsüz yumuşaması ve ünlüyle başlayan yer eki."),
    "Çakmağa otobüsle nasıl giderim?": (None, "Çakmak", "Ünsüz yumuşaması ve ünlüyle başlayan yer eki."),
}


def _shadow_cases() -> list[tuple[str, str]]:
    cases = list(SHADOW_ROUTE_QUESTIONS)
    # E64 asks for every question in every journeys JSONL. The file contents are
    # read as data, and no test module is imported to collect route inputs.
    for path in sorted((ROOT / "eval").glob("journeys*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            question = row.get("question")
            if question:
                cases.append((f"{path.name}:{row.get('id', 'no-id')}", question))
    cases.extend((f"OFFICIAL_PATH_ROWS:{row['id']}", row["question"]) for row in OFFICIAL_PATH_ROWS)
    return cases


def test_g3_shadow_regression_only_records_reviewed_differences(route_agent: NabizAgent) -> None:
    names = [place.name for place in route_agent.nabiz.places.places]
    observed_differences: set[str] = set()
    observed_additions: set[str] = set()
    unexpected: list[tuple[str, str, str | None, str | None]] = []
    if not hasattr(route_agent, "_find_place"):
        pytest.skip("agent.py already routes through place_guard (E64 wired); the shadow has nothing to compare")
    for source, question in _shadow_cases():
        old = route_agent._find_place(question)
        match = find_place(question, names)
        new = match.name if match else None
        if old == new:
            continue
        if question in EXPECTED_DIFFERENCES:
            expected_old, expected_new, _reason = EXPECTED_DIFFERENCES[question]
            observed_differences.add(question)
            if (old, new) != (expected_old, expected_new):
                unexpected.append((source, question, old, new))
        elif question in EXPECTED_ADDITIONS:
            expected_old, expected_new, _reason = EXPECTED_ADDITIONS[question]
            observed_additions.add(question)
            if (old, new) != (expected_old, expected_new):
                unexpected.append((source, question, old, new))
        else:
            unexpected.append((source, question, old, new))
    assert not unexpected, f"Unreviewed place changes: {unexpected}"
    assert observed_differences == set(EXPECTED_DIFFERENCES)
    assert observed_additions == set(EXPECTED_ADDITIONS)
