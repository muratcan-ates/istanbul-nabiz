from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from ibb_mcp.knowledge.guardrails import host_allowed

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "capture_ismek_bio.py"


def capture_module():
    spec = importlib.util.spec_from_file_location("e72_capture", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_capture_contract_import_is_bounded_and_never_calls_the_script() -> None:
    capture = capture_module()
    assert len(capture.URLS) <= capture.MAX_REQUESTS == 4
    assert capture.UA == "istanbul-nabiz-ogrenci-projesi/1"
    hosts = [urlsplit(url).hostname or "" for url in capture.URLS.values()]
    assert all(host_allowed(host) for host in hosts)
    assert all("igdas" not in host for host in hosts)
    assert all("enstitukayit" not in host for host in hosts)
    assert capture._requests == 0


def test_small_handwritten_fragments_cover_the_capture_parsers() -> None:
    capture = capture_module()
    select = '<select id="filters"><option value="-1">Seçin</option><option value="11">Bilişim</option></select>'
    assert capture.options(select, "filters") == [("11", "Bilişim")]

    area_page = (
        '<div role="tabpanel" aria-labelledby="meslekiEgitimler-tab"></div>'
        '<a href="egitim_alanlari.aspx?alanId=11">Bilişim<span>153 Eğitim</span></a>'
    )
    assert capture.areas(area_page) == [
        {
            "id": "11",
            "name": "Bilişim",
            "branch": "Mesleki ve Teknik Eğitimler",
            "programs": 153,
            "url": "https://enstitu.ibb.istanbul/portal/egitim_alanlari.aspx?alanId=11",
        }
    ]

    center_page = (
        '<div class="post-thumbnail-content"><a title="KADIKÖY" href="kurs_icerik.aspx?KursMerkezi=1">'
        '<span class="icon-location"></span>Kadıköy</span>4 Derslik 25 Program<div class="info2">'
    )
    centers = capture.centers(center_page)
    assert centers[0]["district"] == "Kadıköy" and centers[0]["classrooms"] == 4 and centers[0]["programs"] == 25

    feature_page = (
        '<div class="ebox"><div class="detay"><a href=\'egitim_detay.aspx?BransCode=1\'>Deneme</a></div>'
        '<div class="info1">Bilişim</div><div class="info2"><span>30 Saat</span>'
        "<span>Mesleki Destekleyici Eğitim</span></div><a title='Uzaktan Eğitim' class='active'></a>"
    )
    featured = capture.featured(feature_page)
    assert featured[0]["name"] == "Deneme" and featured[0]["hours_text"] == "30 Saat"
    assert featured[0]["modes"] == ["Uzaktan Eğitim"]
    sentence = "Üye girişi ve başvuru işlemleriniz için İBB Hesap üzerinden giriş yapabilirsiniz."
    assert capture.login_sentence(f"<p>{sentence}</p>") == sentence


def test_captured_catalog_is_valid_when_prerequisite_files_exist() -> None:
    path = ROOT / "data" / "reference" / "ismek_bio" / "ismek.json"
    if not path.is_file():
        pytest.skip("önkoşul verisi yok")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["status"] == "alindi"
    dt.datetime.fromisoformat(data["retrieved_at"].replace("Z", "+00:00"))
    assert data["license"]
    assert len(data["programs"]) > 100
    assert all(item["url"].startswith("https://enstitu.ibb.istanbul/portal/") for item in data["programs"])
    districts = {item.casefold() for item in data["districts"]}
    assert all((item.get("district") or "").casefold() in districts for item in data["centers"])
