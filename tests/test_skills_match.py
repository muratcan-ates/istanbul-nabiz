from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nabiz.console.skills_match import Choices, checklist, load_reference, match, validate_choices

BRANCHES = ["Mesleki ve Teknik Eğitimler", "Güzel Sanatlar"]
BASE = "https://enstitu.ibb.istanbul/portal/"


def write_reference(directory: Path, *, status: str = "alindi") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    programs = [
        ("101", "Microsoft Excel Kullanımı"),
        ("102", "Excel İleri Seviye"),
        ("103", "Aşçı Çırağı"),
        ("104", "Temel Python"),
        ("105", "Seramik Biçimlendirme"),
    ]
    data: dict[str, Any] = {
        "source": "Enstitü İstanbul İSMEK",
        "license": "Lisans belirtilmemiş (İBB kamu sayfası).",
        "retrieved_at": "2026-09-27T00:00:00+00:00",
        "programs_url": BASE + "enstitu_egitimler.aspx",
        "centers_url": BASE + "kursmerkezleri.aspx",
        "apply_url": "https://enstitukayit.ibb.istanbul/",
        "login_sentence": "Üye girişi ve başvuru işlemleriniz için İBB Hesap üzerinden giriş yapabilirsiniz.",
        "branches": BRANCHES,
        "areas": [
            {
                "id": "11",
                "name": "Bilişim Teknolojileri",
                "branch": BRANCHES[0],
                "programs": 153,
                "url": BASE + "egitim_alanlari.aspx?alanId=11",
            },
            {
                "id": "83",
                "name": "Aşçılık",
                "branch": BRANCHES[0],
                "programs": 26,
                "url": BASE + "egitim_alanlari.aspx?alanId=83",
            },
            {"id": "21", "name": "Resim", "branch": BRANCHES[1], "programs": 40, "url": BASE + "egitim_alanlari.aspx?alanId=21"},
        ],
        "districts": ["Kadıköy", "Kartal", "Fatih"],
        "times": ["Hafta içi", "Hafta Sonu"],
        "programs": [{"code": code, "name": name, "url": f"{BASE}egitim_detay.aspx?BransCode={code}"} for code, name in programs],
        "featured": [
            {
                "name": "Microsoft Excel Kullanımı",
                "url": f"{BASE}egitim_detay.aspx?BransCode=101",
                "field": "Bilişim Teknolojileri",
                "hours_text": "30 Saat",
                "kind": "Mesleki Destekleyici Eğitim",
                "modes": ["Uzaktan Eğitim"],
            },
            {
                "name": "Aşçı Çırağı",
                "url": f"{BASE}egitim_detay.aspx?BransCode=103",
                "field": "Aşçılık",
                "hours_text": "190 Saat",
                "kind": "İstihdam Hedefli Mesleki Eğitim",
                "modes": ["Yüz Yüze Eğitim"],
            },
        ],
        "centers": [
            {
                "name": "KADIKÖY MERKEZİ",
                "url": f"{BASE}kurs_icerik.aspx?KursMerkezi=1",
                "district": "KADIKÖY",
                "classrooms": 4,
                "programs": 18,
            },
            {
                "name": "KARTAL MERKEZİ",
                "url": f"{BASE}kurs_icerik.aspx?KursMerkezi=2",
                "district": "KARTAL",
                "classrooms": 3,
                "programs": 12,
            },
            {
                "name": "FATİH MERKEZİ",
                "url": f"{BASE}kurs_icerik.aspx?KursMerkezi=3",
                "district": "FATİH",
                "classrooms": 5,
                "programs": 21,
            },
        ],
        "status": status,
        "reason": None if status == "alindi" else "Önkoşul verisi alınamadı.",
    }
    bio = {
        "source": "İBB Bölgesel İstihdam Ofisleri",
        "title": "İş Ara İş Bul | İstanbul Büyükşehir Belediyesi - Bölgesel İstihdam Ofisleri",
        "url": "https://bio.ibb.istanbul/",
        "status": "veri_alinamadi",
        "reason": "İlanlar HTML'de yok.",
    }
    (directory / "ismek.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (directory / "bio.json").write_text(json.dumps(bio, ensure_ascii=False), encoding="utf-8")
    return directory


@pytest.fixture
def reference_dir(tmp_path: Path) -> Path:
    return write_reference(tmp_path / "source")


def test_keyword_branch_area_mode_district_and_time_are_catalog_bounded(reference_dir: Path) -> None:
    ref = load_reference(reference_dir)
    choices = validate_choices(
        {
            "branch": BRANCHES[0],
            "areas": ["Bilişim Teknolojileri"],
            "keyword": "EXCEL",
            "district": "KADIKÖY",
            "mode": "Uzaktan",
            "time": "Hafta Sonu",
        },
        ref,
    )
    data = match(ref, choices)
    assert data["available"] is True
    assert [item["name"] for item in data["areas"]] == ["Bilişim Teknolojileri"]
    assert data["programs"][0]["name"] == "Microsoft Excel Kullanımı"
    assert {item["from"] for item in data["programs"][0]["reasons"]} == {"choice", "catalog"}
    assert len(data["centers"]) == 1 and data["centers"][0]["name"] == "KADIKÖY MERKEZİ"
    assert "merkezin" not in data["centers"][0]["note"]
    assert data["time_hint"]["from"] == "nabiz" and "Hafta Sonu" in data["time_hint"]["text"]
    assert data["jobs"]["card"]["status"] == "veri_alinamadi"
    assert data["jobs"]["search_terms"] == ["Bilişim Teknolojileri", "EXCEL"]


def test_featured_professional_program_has_its_catalog_kind_reason(reference_dir: Path) -> None:
    ref = load_reference(reference_dir)
    choices = validate_choices({"branch": BRANCHES[0], "keyword": "aşçı"}, ref)
    item = next(item for item in match(ref, choices)["programs"] if item["code"] == "103")
    assert any(item["text"] == "Katalogda türü: İstihdam Hedefli Mesleki Eğitim" for item in item["reasons"])
    assert item["note"] is None


def test_validation_rejects_wrong_branch_too_many_areas_pii_and_long_keyword(reference_dir: Path) -> None:
    ref = load_reference(reference_dir)
    with pytest.raises(ValueError, match="dalda"):
        validate_choices({"branch": BRANCHES[1], "areas": ["Bilişim Teknolojileri"]}, ref)
    with pytest.raises(ValueError, match="üç alan"):
        validate_choices({"areas": ["Bilişim Teknolojileri", "Aşçılık", "Resim", "Başka"]}, ref)
    with pytest.raises(ValueError, match="kişisel bilgi"):
        validate_choices({"keyword": "10000000146"}, ref)
    with pytest.raises(ValueError, match="kişisel bilgi"):
        validate_choices({"keyword": "person@example.com"}, ref)
    with pytest.raises(ValueError, match="40 karakter"):
        validate_choices({"keyword": "a" * 41}, ref)


def test_results_are_stable_reasoned_and_never_claim_a_center_program_pair(reference_dir: Path) -> None:
    ref = load_reference(reference_dir)
    choices = validate_choices({"keyword": "excel", "district": "Kadıköy"}, ref)
    first = match(ref, choices)
    second = match(ref, choices)
    assert first == second
    assert all(item["reasons"] for item in first["programs"])
    assert all(item["url"].startswith(BASE) for item in first["programs"])
    assert all(item["note"] is None or "merkez katalogda yok" in item["note"] for item in first["programs"])
    assert all("hangi eğitimin açıldığı katalogda yok" in item["note"] for item in first["centers"])
    visible = json.dumps(first, ensure_ascii=False).lower()
    assert "uygunsunuz" not in visible and "ücretsiz" not in visible and "başvurunuz alındı" not in visible


def test_missing_or_unavailable_catalog_returns_only_official_links(tmp_path: Path) -> None:
    missing = load_reference(tmp_path / "missing")
    result = match(missing, Choices(keyword="excel"))
    assert result["available"] is False
    assert "programs" not in result
    assert [item["url"] for item in result["official"]] == ["https://enstitu.ibb.istanbul/", "https://bio.ibb.istanbul/"]
    unavailable = load_reference(write_reference(tmp_path / "not-ready", status="veri_alinamadi"))
    assert match(unavailable, Choices())["available"] is False


def test_real_capture_examples_when_the_prerequisite_is_present() -> None:
    path = Path(__file__).resolve().parents[1] / "data" / "reference" / "ismek_bio"
    ref = load_reference(path)
    if not ref.available:
        pytest.skip("önkoşul verisi yok")
    excel = match(ref, validate_choices({"keyword": "excel"}, ref))["programs"]
    assert next(index for index, item in enumerate(excel, start=1) if item["name"] == "Microsoft Excel Kullanımı") <= 3
    chef = match(ref, validate_choices({"branch": "Mesleki ve Teknik Eğitimler", "keyword": "aşçı"}, ref))["programs"]
    item = next(item for item in chef if item["name"] == "Aşçı Çırağı")
    assert any("İstihdam Hedefli Mesleki Eğitim" in reason["text"] for reason in item["reasons"])
    kadikoy = match(ref, validate_choices({"district": "KADIKÖY"}, ref))
    assert kadikoy["centers"]


def test_checklist_has_source_material_and_only_user_owned_steps(reference_dir: Path) -> None:
    ref = load_reference(reference_dir)
    data = checklist(ref, "101")
    assert data is not None
    assert [item["kind"] for item in data["official"]] == ["official", "official"]
    assert data["quote"]["kind"] == "quote" and data["quote"]["retrieved_at"] == ref.data["retrieved_at"]
    assert [item["id"] for item in data["self_steps"]] == ["read_page", "checked_travel", "applied_myself"]
    assert checklist(ref, "999") is None
