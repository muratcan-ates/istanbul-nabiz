from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_skills_match import write_reference

from nabiz.console import skills_match
from nabiz.console.skills_api import skills_routes


def client() -> TestClient:
    app = FastAPI()
    app.include_router(skills_routes)
    return TestClient(app)


def use_data(monkeypatch, path: Path) -> None:
    monkeypatch.setenv("NABIZ_SKILLS_DATA_DIR", str(path))
    skills_match._read_reference.cache_clear()


def test_options_match_and_checklist_routes_are_read_only(tmp_path: Path, monkeypatch, caplog) -> None:
    directory = write_reference(tmp_path / "reference")
    use_data(monkeypatch, directory)
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    response = client().get("/api/skills/options")
    assert response.status_code == 200
    options = response.json()
    assert options["available"] is True and options["call"] == "153"
    assert len(options["areas"]) == 3 and options["jobs_status"]["status"] == "veri_alinamadi"

    matched = client().post(
        "/api/skills/match",
        json={"branch": "Mesleki ve Teknik Eğitimler", "areas": ["Bilişim Teknolojileri"], "keyword": "excel"},
    )
    assert matched.status_code == 200 and matched.headers["cache-control"] == "no-store"
    assert matched.json()["programs"][0]["name"] == "Microsoft Excel Kullanımı"
    checklist = client().get("/api/skills/checklist?code=101")
    assert checklist.status_code == 200 and checklist.json()["code"] == "101"
    missing = client().get("/api/skills/checklist?code=999")
    assert missing.status_code == 404
    assert sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")) == before
    assert caplog.records == []


def test_match_rejects_invalid_input_oversize_and_personal_data_without_logging(tmp_path: Path, monkeypatch, caplog) -> None:
    directory = write_reference(tmp_path / "reference")
    use_data(monkeypatch, directory)
    api = client()
    wrong = api.post("/api/skills/match", json={"branch": "unknown"})
    assert wrong.status_code == 400 and wrong.json()["error"] == "bad_request"
    personal = api.post("/api/skills/match", json={"keyword": "person@example.com"})
    assert personal.status_code == 400 and "kişisel bilgi" in personal.json()["message"]
    too_large = api.post("/api/skills/match", content=b"x" * 2049, headers={"Content-Type": "application/json"})
    assert too_large.status_code == 413
    malformed = api.post("/api/skills/match", content=b"not-json", headers={"Content-Type": "application/json"})
    assert malformed.status_code == 400
    log_text = " ".join(record.getMessage() for record in caplog.records)
    assert "person@example.com" not in log_text


def test_unavailable_catalog_is_a_successful_honest_response(tmp_path: Path, monkeypatch) -> None:
    use_data(monkeypatch, tmp_path / "empty")
    api = client()
    options = api.get("/api/skills/options")
    assert options.status_code == 200 and options.json()["available"] is False
    matched = api.post("/api/skills/match", json={"keyword": "excel"})
    assert matched.status_code == 200 and matched.json()["available"] is False
    assert matched.headers["cache-control"] == "no-store"
    assert len(matched.json()["official"]) == 2 and "programs" not in matched.json()
