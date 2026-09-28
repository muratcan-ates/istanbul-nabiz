from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from conftest import REPO_ROOT
from test_console_chat import CLOUD, FakeModel, ask, client_for, events, nabiz, reply
from test_knowledge_store import seed_page

from ibb_mcp.knowledge.guardrails import host_allowed
from ibb_mcp.knowledge.store import KnowledgeStore
from ibb_mcp.text import looks_like_instruction, normalize_tr
from nabiz.agent import llm
from nabiz.agent.templates import OUT_OF_SCOPE
from nabiz.console import chat_pipeline, official_path
from nabiz.console.agency_router import agency_for, load_agencies
from nabiz.console.forbidden_terms import find_forbidden
from nabiz.console.official_intent import agency_and_topic, help_topic, intent
from nabiz.console.official_path import select_path
from nabiz.console.policy import names_a_price

__all__ = ["nabiz"]

PATH = REPO_ROOT / "data" / "official_paths.json"
KNOWLEDGE = REPO_ROOT / "data" / "knowledge" / "knowledge.db"


POSITIVE = {
    "account": [
        ("İSKİ faturamı kontrol et", "iski"),
        ("Su faturam ne kadar?", "iski"),
        ("İBB aboneliklerimi listele", "ibb"),
        ("İGDAŞ gaz açma randevusu almak istiyorum", "igdas"),
        ("Doğalgaz borcumu öğrenmek istiyorum", "igdas"),
        ("153 başvurumun durumu ne?", "cozum_153"),
        ("Check my İSKİ water bill", "iski"),
        ("List my İBB subscriptions", "ibb"),
    ],
    "help": [
        ("Hangi İBB yardımını alabilirim?", "sosyal_destek"),
        ("Engelli bireyler için hangi İBB desteklerinden yararlanabilirim?", "engelli"),
        ("What support can I get from İBB?", "sosyal_destek"),
    ],
    "ferry": [
        ("Kabataş Adalar vapuru saatleri", "sehir_hatlari"),
        ("Haliç vapur hattının sefer saatleri nedir?", "sehir_hatlari"),
        ("What time is the ferry from Kabataş to the islands?", "sehir_hatlari"),
    ],
}

NEGATIVE = [
    "İSKİ su aboneliğini iptal etmek için hangi belgeler gerekir?",
    "Doğalgaz faturası nereden ödenir?",
    "153 başvurumu nereden takip ederim?",
    "Kartal bildirimimin durumunu göster.",
    "Elektrik faturamı kontrol et",
    "Kredi kartı borcumu nasıl yapılandırırım?",
    "Su aboneliği başvurusu nasıl yapılır?",
    "Askıda Fatura’dan nasıl destek olurum?",
    "Sosyal yardım için 153 dışında hangi kanallar var?",
    "Şehir Hatları vapurlarında engelli yolcular için hangi hizmetler var?",
    "Deniz taksi nasıl çağrılır?",
    "Kabataş'a nasıl giderim?",
    "Kabataş iskelesinde otopark var mı?",
    "Gece metrosu seferleri saat kaçta başlıyor?",
    "Deniz otobüsü saatleri",
    "Kadıköy'de otopark ve vapur saatleri",
    "Metro hattında arıza var mı?",
    "insanla görüşmek istiyorum",
]

SELF_REVIEW = [
    "Metroda asansör çalışıyor mu?",
    "500T ne zaman gelir?",
    "Taksim'de otopark var mı?",
    "İBB Wi-Fi ağına nasıl bağlanırım?",
    "Metrobüs en son saat kaçta kalkıyor?",
    "Kadıköy'de bisiklet park yeri var mı?",
    "İBB spor tesisleri bugün açık mı?",
    "Otobüste cüzdanımı unuttum, ne yapmalıyım?",
    "İstanbul'da su kesintisi olan mahalleleri nereden görürüm?",
    "İstanbul vapurlarında bisiklet taşımak serbest mi?",
]


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _catalog() -> list[dict]:
    return official_path.load_paths()["paths"]


def _seed_catalog(db_path: Path) -> None:
    store = KnowledgeStore(db_path)
    sources = {
        (source["url"], source["excerpt"])
        for path in _catalog()
        for source in path["sources"]
        if source.get("excerpt")
    }
    for url, excerpt in sorted(sources):
        seed_page(store, excerpt, url=url)


def _ask_lang(client, question: str, lang: str):
    response = client.post("/api/chat", json={"message": question, "needs": [], "history": [], "lang": lang})
    assert response.status_code == 200, response.text
    stream = events(response.text)
    assert stream[-1][0] == "final"
    return stream, stream[-1][1]


def test_classifier_acceptance_table_and_agency_router() -> None:
    for expected, examples in POSITIVE.items():
        for question, agency in examples:
            assert intent(question) == expected, question
            routed = agency_for(question)
            if expected == "help":
                assert routed == "ibb", question
                assert help_topic(question) == agency, question
            else:
                assert routed == agency or (routed is None and agency_and_topic(question)[0] == agency), question
    for question in NEGATIVE:
        assert intent(question) not in {"account", "help"}, question
    assert intent("Deniz otobüsü saatleri") is None
    assert agency_for("Kartal'de çöp konteyneri dolu") == "ilce"
    assert agency_and_topic("Öğrenci kartı vizesi nasıl yapılır?") == ("istanbulkart", "vize")
    assert select_path("Öğrenci kartı vizesi nasıl yapılır?", "fallback")["id"] == "istanbulkart-vize"
    assert select_path("Elektrik aboneliği nasıl yapılır?", "fallback") is None
    assert select_path("Pasaport başvurusu nasıl yapılır?", "fallback") is None


def test_intent_regression_corpus_and_ten_self_review_questions() -> None:
    allowed_ferry = {"k-11", "k-15", "k-ulasim-15"}
    for path in (REPO_ROOT / "eval").glob("journeys*.jsonl"):
        if path.name == "journeys.yardim.jsonl":
            continue
        for row in _rows(path):
            result = intent(row["question"])
            assert result not in {"account", "help"}, (path.name, row.get("id"), row["question"])
            assert result != "ferry" or row.get("id") in allowed_ferry, (path.name, row.get("id"), row["question"])
    for row in _rows(REPO_ROOT / "eval/knowledge_calibration.jsonl"):
        if row.get("group") in {"yardim", "resmi-yol"}:
            continue
        result = intent(row["question"])
        assert result not in {"account", "help"}, (row["id"], row["question"])
        assert result != "ferry" or row["id"] in {"k-11", "k-15"}, (row["id"], row["question"])
    for item in json.loads((REPO_ROOT / "data/knowledge/quick_questions.json").read_text(encoding="utf-8"))["sorular"]:
        if item["kind"] == "official":
            continue
        assert intent(item["soru_tr"]) not in {"account", "help"}, item["id"]
        assert intent(item["soru_tr"]) != "ferry" or item["id"] == "k-ulasim-15", item["id"]
    assert [intent(question) for question in SELF_REVIEW] == [None] * len(SELF_REVIEW)
    assert intent("Su faturam ne kadar?") == "account"
    assert intent("İstanbulkart bakiyem ne kadar?") == "account"
    assert chat_pipeline.early_verdict("İstanbulkart bakiyem ne kadar?", []) == "sensitive"


@pytest.mark.skipif(not KNOWLEDGE.is_file(), reason="the knowledge index is built locally and not committed (CI has none)")
def test_official_path_data_is_cited_safe_and_grounded() -> None:
    paths = _catalog()
    assert len(paths) >= 12
    assert len({path["id"] for path in paths}) == len(paths)
    registry = load_agencies()
    agency_ids = {item["id"] for item in registry["agencies"]}
    agency_urls = {item["url"] for item in registry["agencies"]}
    source_urls = {
        line.split("\t", 1)[0]
        for line in (REPO_ROOT / "data/knowledge/sources.txt").read_text(encoding="utf-8").splitlines()
        if line.startswith("http")
    }
    db = sqlite3.connect(f"file:{KNOWLEDGE}?mode=ro", uri=True)
    for path in paths:
        assert path["agency"] in agency_ids
        assert 2 <= len(path["steps_tr"]) <= 4
        assert len(path["steps_tr"]) == len(path["steps_en"])
        agency = next(item for item in registry["agencies"] if item["id"] == path["agency"])
        for lang in ("tr", "en"):
            steps = path[f"steps_{lang}"]
            path_excerpts = [source["excerpt"] for source in path["sources"] if source.get("excerpt")]
            for step in steps:
                assert len(step) <= 140
                assert not find_forbidden(step), (path["id"], step, find_forbidden(step))
                assert "—" not in step and "–" not in step and "canlı" not in step.lower()
                assert not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b\d{11}\b", step)
                first = normalize_tr(step).split()[0]
                starts_with_action = first in (
                    {"girin", "arayin", "inceleyin", "kullanin", "takip", "belirleyin", "acin", "okuyun", "dogrulayin"}
                    if lang == "tr"
                    else {"open", "call", "read", "use", "check", "track", "identify", "review", "apply", "confirm"}
                )
                assert starts_with_action, (path["id"], lang, step)
                for number in re.findall(r"\d{3,}", step):
                    assert number in {"153", "112"} or any(number in excerpt for excerpt in path_excerpts), (
                        path["id"], step, number
                    )
            for fallback in (False, True):
                lead = official_path._lead(path["kind"], path, agency, lang, fallback=fallback)
                assert not find_forbidden(lead), (path["id"], lead, find_forbidden(lead))
                assert "—" not in lead and "–" not in lead and "canlı" not in lead.lower()
        for source in path["sources"]:
            url = source["url"]
            assert url in source_urls or url in agency_urls, (path["id"], url)
            assert host_allowed(urlsplit(url).hostname or ""), (path["id"], url)
            excerpt = source.get("excerpt")
            if excerpt is None:
                continue
            assert len(excerpt) <= 300, (path["id"], len(excerpt))
            assert not names_a_price(excerpt)
            assert not looks_like_instruction(excerpt)
            assert not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b\d{11}\b", excerpt)
            row = db.execute(
                "SELECT body FROM documents WHERE active=1 AND canonical_url=?", (url,)
            ).fetchone()
            assert row is not None and excerpt in " ".join(row[0].split()), (path["id"], url, "alıntı bulunamadı")
    db.close()
    igdas = json.dumps(next(path for path in paths if path["id"] == "igdas"), ensure_ascii=False)
    assert "187" not in igdas


def test_early_account_and_help_cards_are_tool_and_model_free(nabiz, tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "official.db"
    _seed_catalog(db_path)
    monkeypatch.setenv("NABIZ_OFFLINE", "1")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(db_path))
    monkeypatch.setenv("NABIZ_KNOWLEDGE_FTS_MIN", "1000")
    fake = FakeModel(reply("This must not be used."))
    monkeypatch.setattr(llm, "chat", fake)
    with client_for(nabiz, CLOUD) as client:
        account_stream, account = ask(client, "İSKİ faturamı kontrol et")
        help_stream, help_card = ask(client, "Hangi İBB yardımını alabilirim?")
        english_stream, english_help = _ask_lang(client, "What support can I get from İBB?", "en")
    for stream, final in ((account_stream, account), (help_stream, help_card), (english_stream, english_help)):
        assert final["mode"] == "answer" and final["author"] == "kural" and final["refused"] is False
        assert final["how"]["tool_calls"] == 0
        assert not any(kind == "tool" for kind, _ in stream)
    assert account["how"]["rule_id"] == "resmi_yol"
    assert "göremez" in account["answer"] and any("185" in step for step in account["steps"])
    assert any(item["url"] == "https://iski.istanbul/" for item in account["citations"])
    assert help_card["how"]["rule_id"] == "yardim"
    assert "karar vermez" in help_card["answer"]
    assert "hak kazan" not in help_card["answer"].lower() and "uygunsunuz" not in help_card["answer"].lower()
    assert any(item["source"] == "local:knowledge" for item in help_card["citations"])
    assert english_help["lang"] == "en" and english_help["how"]["rule_id"] == "yardim"
    assert "does not decide" in english_help["answer"]
    assert any(item.get("quote_lang") == "tr" for item in english_help["citations"])
    assert fake.calls == []


def test_ferry_tries_knowledge_then_uses_official_timetable_without_places(nabiz, tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "ferry.db"
    _seed_catalog(db_path)
    monkeypatch.setenv("NABIZ_OFFLINE", "1")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(db_path))
    monkeypatch.setenv("NABIZ_KNOWLEDGE_FTS_MIN", "1000")
    fake = FakeModel(reply("This must not be used."))
    monkeypatch.setattr(llm, "chat", fake)
    with client_for(nabiz, CLOUD) as client:
        stream, final = ask(client, "Kabataş Adalar vapuru saatleri")
    tools = [data["name"] for kind, data in stream if kind == "tool"]
    assert final["mode"] == "answer" and final["how"]["rule_id"] == "resmi_yol:yedek"
    assert "places_resolve" not in tools
    assert tools == ["ibb_services_search", "ibb_services_search"]
    assert any("sehirhatlari.istanbul/tr/seferler/ic-hatlar" in item["url"] for item in final["citations"])
    assert any("ALO 153" in item.get("quote", "") for item in final["citations"])
    assert fake.calls == []


def test_unknown_transactions_fall_back_and_r06_stays_first(nabiz, tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "fallback.db"
    _seed_catalog(db_path)
    monkeypatch.setenv("NABIZ_OFFLINE", "1")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(db_path))
    monkeypatch.setenv("NABIZ_KNOWLEDGE_FTS_MIN", "1000")
    with client_for(nabiz, llm.LlmConfig()) as client:
        _, cancellation = ask(client, "İSKİ abonelik iptali nasıl yapılır?")
        _, student = ask(client, "Öğrenci kartı vizesi nasıl yapılır?")
        _, sensitive = ask(client, "İstanbulkart bakiyem ne kadar?")
        _, electricity = ask(client, "Elektrik aboneliği nasıl yapılır?")
        _, passport = ask(client, "Pasaport başvurusu nasıl yapılır?")
    assert cancellation["mode"] == student["mode"] == "answer"
    assert cancellation["how"]["rule_id"] == student["how"]["rule_id"] == "resmi_yol:yedek"
    assert any("İSKİ E-ŞUBE" in item.get("quote", "") for item in cancellation["citations"])
    assert any("istanbulkart.istanbul" in item["url"] for item in student["citations"])
    assert sensitive["refused"] is True and sensitive["how"]["rule_id"] == "refusal"
    assert electricity["mode"] == passport["mode"] == "unknown"
    assert electricity["how"]["rule_id"] == passport["how"]["rule_id"] == "knowledge"


def test_missing_index_stays_uncovered_but_account_route_is_unquoted(nabiz, tmp_path, monkeypatch) -> None:
    missing = tmp_path / "missing.db"
    monkeypatch.setenv("NABIZ_OFFLINE", "1")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(missing))
    monkeypatch.delenv("NABIZ_KNOWLEDGE_FTS_MIN", raising=False)
    with client_for(nabiz, llm.LlmConfig()) as client:
        _, account = ask(client, "İSKİ faturamı kontrol et")
        _, service = ask(client, "Su aboneliği başvurusu nasıl yapılır?")
        _, electricity = ask(client, "Elektrik aboneliği nasıl yapılır?")
        _, passport = ask(client, "Pasaport başvurusu nasıl yapılır?")
    assert account["how"]["rule_id"] == "resmi_yol" and account["citations"]
    assert not any(item["source"] == "local:knowledge" for item in account["citations"])
    assert service["answer"] == OUT_OF_SCOPE.get("tr")
    assert electricity["how"]["rule_id"] not in {"resmi_yol", "yardim", "resmi_yol:yedek"}
    assert passport["how"]["rule_id"] not in {"resmi_yol", "yardim", "resmi_yol:yedek"}


def test_yardim_journey_file_replays_all_fourteen_rows(nabiz, tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "journeys.db"
    _seed_catalog(db_path)
    monkeypatch.setenv("NABIZ_OFFLINE", "1")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(db_path))
    monkeypatch.setenv("NABIZ_KNOWLEDGE_FTS_MIN", "1000")
    for row in _rows(REPO_ROOT / "eval/journeys.yardim.jsonl"):
        with client_for(nabiz, llm.LlmConfig()) as client:
            stream, final = _ask_lang(client, row["question"], row["lang"])
        expected = row["expect"]
        for key in ("mode", "lang"):
            if key in expected:
                assert final[key] == expected[key], row["id"]
        if row["id"] == "yr-08":
            assert final["how"]["rule_id"] in {"knowledge", "resmi_yol:yedek"}
            assert not any(data.get("name") == "places_resolve" for kind, data in stream if kind == "tool")
        elif "rule_id" in expected:
            assert final["how"]["rule_id"] == expected["rule_id"], row["id"]
        if expected.get("cites_host"):
            assert any(expected["cites_host"] in urlsplit(item["url"]).hostname for item in final["citations"])
        text = " ".join([final["answer"], *(final["steps"] or [])]).lower()
        assert all(term.lower() not in text for term in expected.get("must_not_contain", [])), row["id"]
        if "not_rule_id" in expected:
            assert final["how"]["rule_id"] not in expected["not_rule_id"], row["id"]
    assert len(_rows(REPO_ROOT / "eval/journeys.yardim.jsonl")) == 14


def test_readonly_index_does_not_change_the_database(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "readonly.db"
    _seed_catalog(db_path)
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(db_path))
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    from nabiz.console.official_path import readonly_index

    store, embedder = readonly_index()
    assert store is not None and embedder is None
    assert store.current_document("https://iski.istanbul/iletisim/alo-185/") is not None
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before


def test_an_official_path_verdict_still_gets_the_model_emergency_check(nabiz, tmp_path, monkeypatch) -> None:
    """A help or account question can carry an emergency the keyword rule misses; the model check still runs."""
    from nabiz.console import chat as chat_module

    seen: list[str] = []

    async def emergency(message, config, guard):
        seen.append(message)
        return {"lang": "tr", "hazard": None}

    monkeypatch.setenv("NABIZ_OFFLINE", "1")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(tmp_path / "missing.db"))
    monkeypatch.setattr(chat_module, "model_emergency", emergency)
    with client_for(nabiz, llm.LlmConfig()) as client:
        _, final = ask(client, "Hangi İBB yardımını alabilirim?")
    assert seen and final["mode"] == "redirect" and final["emergency"] is True
