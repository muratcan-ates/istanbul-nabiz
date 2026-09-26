from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ibb_mcp.config import REPO_ROOT
from nabiz.console import agency_router
from nabiz.console.agency_api import agency_routes
from nabiz.console.agency_router import load_agencies, route

DATA = REPO_ROOT / "data" / "agencies.json"
SOURCES = REPO_ROOT / "data" / "knowledge" / "sources.txt"
STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
CASES = [
    ("Su kesintisi ne zaman biter?", "iski", False, None),
    ("Sular kesik, kime yazayım?", "iski", False, None),
    ("Su faturamı nereden öderim?", "iski", False, None),
    ("Kanalizasyon taştı", "iski", False, None),
    ("İSKİ'ye nasıl ulaşırım?", "iski", False, None),
    ("Evde suyum akmıyor", "iski", False, None),
    ("Doğalgaz aboneliği nasıl açılır?", "igdas", False, None),
    ("Doğal gaz kesildi", "igdas", False, None),
    ("Gaz faturası nereden ödenir?", "igdas", False, None),
    ("İGDAŞ müşteri hizmetleri", "igdas", False, None),
    ("Gazım kesildi", "igdas", False, None),
    ("Otobüs geç geldi, kime söylerim?", "iett", False, None),
    ("Metrobüs neden bu kadar kalabalık?", "iett", False, None),
    ("İETT kayıp eşya bürosu nerede?", "iett", False, None),
    ("500T otobüsü nereden geçiyor?", "iett", False, None),
    ("Otobüs şoförünü şikâyet etmek istiyorum", "iett", False, None),
    ("Metro seferleri kaçta başlıyor?", "metro", False, None),
    ("M4 metrosunda asansör arızası", "metro", False, None),
    ("Tramvay neden durdu?", "metro", False, None),
    ("Teleferik çalışıyor mu?", "metro", False, None),
    ("Metro İstanbul'a nasıl yazarım?", "metro", False, None),
    ("Otopark ücreti ne kadar?", "ispark", False, None),
    ("İSPARK aboneliği", "ispark", False, None),
    ("Kadıköy'de park yeri var mı?", "ispark", False, None),
    ("Otoparkta aracım çekildi", "ispark", False, None),
    ("Vapur seferleri iptal mi?", "sehir_hatlari", False, None),
    ("Şehir Hatları yaz tarifesi", "sehir_hatlari", False, None),
    ("Kadıköy vapuru kaçta?", "sehir_hatlari", False, None),
    ("İstanbulkart'ım kayboldu", "istanbulkart", False, None),
    ("Akbil nereden dolar?", "istanbulkart", False, None),
    ("İstanbul Kart başvurusu", "istanbulkart", False, None),
    ("Nikâh başvurusu nereye yapılır?", "ilce", True, None),
    ("Nikah salonu rezervasyonu", "ilce", True, None),
    ("Kadıköy'de nikâh işlemleri", "ilce", False, "Kadıköy"),
    ("Üsküdar'da evlendirme dairesi", "ilce", False, "Üsküdar"),
    ("Emlak vergisi nereye ödenir?", "ilce", True, None),
    ("Çöp toplama saatleri", "ilce", True, None),
    ("Eyüp'te nikâh", "ilce", False, "Eyüpsultan"),
    ("İBB'ye bir sorunu nasıl bildirebilirim?", "cozum_153", False, None),
    ("Şikâyet etmek istiyorum", "cozum_153", False, None),
    ("Çözüm Merkezi'ne nasıl ulaşırım?", "cozum_153", False, None),
    ("Kaldırımdaki çukuru ihbar etmek istiyorum", "cozum_153", False, None),
    ("Sosyal yardım başvurusu nereden yapılır?", "ibb", False, None),
    ("Kreş başvurusu", "ibb", False, None),
    ("İsmek kursları", "ibb", False, None),
    ("Elektrik kesintisi var", None, False, None),
    ("Marmaray seferleri", None, False, None),
    ("Bugün hava nasıl?", None, False, None),
    ("Yangın var!", None, False, None),
    ("Annem düştü kalkamıyor", None, False, None),
]


def client() -> TestClient:
    app = FastAPI()
    app.include_router(agency_routes)
    return TestClient(app)


@pytest.mark.parametrize("question, agency, district_needed, district", CASES)
def test_fifty_questions_route_to_the_expected_agency(question, agency, district_needed, district):
    result = route(question)
    assert (result.agency, result.district_needed, result.district) == (agency, district_needed, district)


def test_emergency_questions_get_no_agency():
    for question in ("Gaz kokusu var", "Doğalgaz kaçağı var", "Binada çatlak var"):
        result = route(question)
        assert result.emergency and result.agency is None and result.url is None
    assert route("Gaz faturası nereden ödenir?").agency == "igdas"
    assert not route("Gaz faturası nereden ödenir?").emergency


def test_every_agency_url_is_in_sources_txt():
    rows = SOURCES.read_text(encoding="utf-8").splitlines()
    urls = {line.split("\t", 1)[0] for line in rows if line and not line.startswith("#")}
    body = DATA.read_text(encoding="utf-8")
    data = json.loads(body)
    assert {item["url"] for item in data["agencies"]} <= urls
    assert data["district_office"]["url"] is None
    assert {url.rstrip("\"',}") for url in re.findall(r"https?://\S+", body)} <= urls


def test_route_never_invents_a_url():
    urls = {item["url"] for item in json.loads(DATA.read_text(encoding="utf-8"))["agencies"]}
    cases = [(question, district) for question, _, _, district in CASES]
    cases.extend(("Nikah", city) for city in ("Kadıköy", "Üsküdar", "Eyüp"))
    for question, district in cases:
        result = route(question, district)
        assert result.url is None or result.url in urls
        if result.agency == "ilce":
            assert result.url is None


def test_districts_are_39_and_cover_places_csv():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    assert len(data["districts"]) == len(set(data["districts"])) == 39
    aliases = {alias: canonical for alias, canonical in data["district_aliases"].items()}
    with (REPO_ROOT / "data" / "reference" / "places.csv").open(encoding="utf-8", newline="") as handle:
        places = {row["district"] for row in csv.DictReader(handle) if row["district"]}
    assert {aliases.get(name, name) for name in places} <= set(data["districts"])


def test_district_parameter_and_alias():
    result = route("Nikâh başvurusu", district="kadıköy")
    assert (result.district, result.district_needed, result.name) == ("Kadıköy", False, "Kadıköy Belediyesi")
    assert route("Nikâh", district="Eyüp").district == "Eyüpsultan"
    unknown = route("Nikâh", district="Narnia")
    assert unknown.district_needed and unknown.district is None
    assert unknown.text == "Bu ilçe adını tanımadım; listeden seçin."


def test_api_returns_the_route_shape():
    response = client().get("/api/agency", params={"q": "Su kesintisi"})
    assert response.status_code == 200
    body = response.json()
    expected = {"agency", "name", "url", "district_needed", "district", "matched", "text", "emergency", "call", "districts"}
    assert set(body) == expected
    assert body["agency"] == "iski" and body["call"] == "153" and body["districts"] == []
    assert len(client().get("/api/agency", params={"q": "Nikah"}).json()["districts"]) == 39


def test_api_rejects_long_and_empty_input():
    api = client()
    assert api.get("/api/agency", params={"q": "a" * 301}).status_code == 422
    assert api.get("/api/agency", params={"q": ""}).status_code == 422
    assert api.get("/api/agency", params={"q": "a" * 300}).status_code == 200
    assert api.get("/api/agency", params={"q": "Nikah", "district": "x" * 41}).status_code == 422


def test_api_503_when_agency_data_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("NABIZ_AGENCIES_PATH", raising=False)
    monkeypatch.setattr(agency_router, "AGENCIES_PATH", tmp_path / "yok.json")
    load_agencies.cache_clear()
    try:
        missing = client().get("/api/agency", params={"q": "Su kesintisi"})
        assert missing.status_code == 503 and missing.json()["error"] == "agency_data_missing"
        monkeypatch.setenv("NABIZ_AGENCIES_PATH", str(DATA))
        load_agencies.cache_clear()
        assert client().get("/api/agency", params={"q": "Su kesintisi"}).status_code == 200
    finally:
        load_agencies.cache_clear()


def test_router_uses_no_model_or_network():
    for path in (REPO_ROOT / "src/nabiz/console/agency_router.py", REPO_ROOT / "src/nabiz/console/agency_api.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert all(term not in text for term in ("llm", "openai", "httpx", "nabiz.agent"))


def test_card_strings_are_honest():
    paths = (STATIC / "js/agency.js", STATIC / "css/agency.css", DATA)
    forbidden = ("İBB onaylı", "iletildi", "oluşturuldu", "—", "–")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert all(term not in text for term in forbidden)
        assert not re.search(r"\bETA\b", text)
    js = paths[0].read_text(encoding="utf-8")
    css = paths[1].read_text(encoding="utf-8")
    assert "#chat-submit" in js and "aria-disabled" in js
    assert "ilçedesin?" not in js and "senin yerine" not in js
    assert "Ben İstanbul şehir bilgi asistanıyım ve yapay zekâ kullanıyorum. Resmî karar veren bir görevli değilim." not in js
    assert "skor" not in js.lower() and "puan" not in js.lower()
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(", css)


def node_json(tmp_path: Path, modules: dict[str, str], body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    imports = "\n".join(f"import * as {name} from {json.dumps((STATIC / path).as_uri())};" for name, path in modules.items())
    harness = tmp_path / "agency_harness.mjs"
    harness.write_text(f"{imports}\n{body}\n", encoding="utf-8")
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_agency_card_renders_link_call_and_district_picker(tmp_path):
    rendered = node_json(
        tmp_path,
        {"agency": "js/agency.js"},
        "const data = {agency:'iski', name:'İSKİ', url:'https://iski.istanbul/', "
        "text:`Bu, İSKİ'nin işi.`, matched:'su', district_needed:false};"
        "const district = {agency:'ilce', name:'İlçe belediyesi', url:null, text:'Hangi ilçedesiniz?', "
        "matched:'nikah', district_needed:true, districts:Array.from({length:39},(_,i)=>'İlçe '+i)};"
        "const out = {card:agency.agencyCard(data,'x'), noCall:agency.agencyCard(data,'x',false), "
        "district:agency.agencyCard(district,'d'), show:agency.shouldShow({agency:null}), "
        "emergency:agency.shouldShow({agency:'iski',emergency:true})};"
        "console.log(JSON.stringify(out));",
    )
    assert 'https://iski.istanbul/' in rendered["card"]
    assert 'rel="noopener noreferrer"' in rendered["card"] and 'tel:153' in rendered["card"]
    assert 'tel:153' not in rendered["noCall"] and '<form' not in rendered["card"]
    assert rendered["district"].count("<option") == 39
    assert 'list="agency-districts-' in rendered["district"] and '<label for="agency-district-' in rendered["district"]
    assert 'href="http' not in rendered["district"]
    assert rendered["show"] is False and rendered["emergency"] is False
