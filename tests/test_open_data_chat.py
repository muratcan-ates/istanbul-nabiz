"""The open-data catalogue in the product: the rule path's routing and answer, the chat card, ``/api/datasets``.

The catalogue is built from the synthetic CKAN fixture into a temporary file and named through
``NABIZ_IBB_CATALOG``; no test reaches İBB or a model.
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator

import httpx
import pytest
from conftest import offline_settings, refuse_network
from fastapi.testclient import TestClient
from test_console_chat import ask, client_for
from test_ibb_catalog import write_catalog

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.agent.agent import NabizAgent
from nabiz.agent.open_data_route import asks_for_datasets, dataset_route
from nabiz.console.open_data_api import CATALOG_MISSING

OTOPARK = "İBB'nin otopark verisi var mı?"


@pytest.fixture(scope="module")
def nabiz() -> Iterator[Nabiz]:
    yield Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)), cache=TTLCache(), settings=offline_settings()
        )
    )


@pytest.fixture
def catalog(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    path = write_catalog(tmp_path)
    monkeypatch.setenv("NABIZ_IBB_CATALOG", str(path))
    return path


# -- routing ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (OTOPARK, ("ibb_datasets_search", {"query": OTOPARK})),
        ("Mobilite kategorisinde hangi veri setleri var?",
         ("ibb_datasets_search", {"query": "Mobilite kategorisinde hangi veri setleri var?", "category": "Mobilite"})),
        ("Does İBB publish open data on bike-share stations?",
         ("ibb_datasets_search", {"query": "Does İBB publish open data on bike-share stations?"})),
        ("Enerji verisi var mı?", ("ibb_datasets_search", {"query": "Enerji verisi var mı?"})),
    ],
)  # fmt: skip
def test_a_question_about_data_goes_to_the_catalogue(nabiz: Nabiz, question: str, expected: tuple) -> None:
    assert NabizAgent(nabiz, config=llm.LlmConfig()).route(question) == expected


@pytest.mark.parametrize(
    ("question", "tool"),
    [
        ("Kadıköy'de otopark var mı?", "ispark_find_parking"),
        ("Veri ne kadar güncel?", "city_freshness"),
        ("Trafik şu an nasıl?", "traffic_index"),
        ("İBB Açık Veri Portalında yayımlanmayan bir veri setini nasıl talep edebilirim?", ""),
    ],
)
def test_other_questions_keep_their_route(nabiz: Nabiz, question: str, tool: str) -> None:
    assert NabizAgent(nabiz, config=llm.LlmConfig()).route(question)[0] == tool


def test_a_data_request_is_a_service_question() -> None:
    assert asks_for_datasets("acik veri portalindan veri talebi") is False
    assert dataset_route("kadikoy de otopark var mi", "Kadıköy'de otopark var mı?") is None


# -- the rule path's answer ---------------------------------------------------------------
async def test_the_rule_answer_lists_datasets_with_link_and_update(nabiz: Nabiz, catalog: pathlib.Path) -> None:
    answer = await NabizAgent(nabiz, config=llm.LlmConfig()).ask(OTOPARK)
    assert answer.tool_names == ["ibb_datasets_search"]
    assert "İBB Açık Veri'de bulduğum veri setleri" in answer.text
    assert "https://data.ibb.gov.tr/dataset/ispark-otopark-bilgileri" in answer.text
    assert "son güncelleme 20.09.2026" in answer.text
    assert answer.faithfulness is not None and answer.faithfulness.passed, answer.faithfulness.unsupported_texts


async def test_without_a_catalogue_the_rule_answer_says_so(nabiz: Nabiz) -> None:
    answer = await NabizAgent(nabiz, config=llm.LlmConfig()).ask(OTOPARK)
    assert "kaydı bu sunucuda yok" in answer.text and "make capture-catalog" in answer.text
    assert "data.ibb.gov.tr/dataset/" not in answer.text


# -- the chat card ------------------------------------------------------------------------
def test_the_chat_cites_every_dataset_it_names(nabiz: Nabiz, catalog: pathlib.Path) -> None:
    with client_for(nabiz, llm.LlmConfig()) as chat:
        stream, final = ask(chat, OTOPARK)
    assert ("tool", {"name": "ibb_datasets_search", "status": "start"}) in stream
    assert final["author"] == "kural" and final["mode"] == "answer"
    datasets = [item for item in final["citations"] if item.get("title")]
    assert datasets[0] == {
        "source": "ibb_catalog",
        "title": "İSPARK Otopark Bilgileri",
        "institution": "İSPARK A.Ş.",
        "url": "https://data.ibb.gov.tr/dataset/ispark-otopark-bilgileri",
        "source_updated_at": "2026-09-20T08:15:00+00:00",
        "fetched_at": "2026-09-26T09:00:00+00:00",
    }
    envelope = next(item for item in final["citations"] if not item.get("title"))
    assert envelope["mode"] == "recorded"  # a catalogue copy is never "canlı"


# -- GET /api/datasets --------------------------------------------------------------------
def client(nabiz: Nabiz) -> TestClient:
    return client_for(nabiz, llm.LlmConfig())


def test_the_page_search_answers_from_the_catalogue(nabiz: Nabiz, catalog: pathlib.Path) -> None:
    body = client(nabiz).get("/api/datasets", params={"q": "otopark"}).json()
    names = [hit["name"] for hit in body["datasets"]]
    assert names[:2] == ["ispark-otopark-bilgileri", "mevcut-otopark-sayilari-ve-kapasiteleri"]
    assert body["catalog"]["synthetic"] is True and "SENTETİK" in body["note"]
    assert body["provenance"]["mode"] == "recorded" and body["provenance"]["observed_at"] == "2026-09-26T09:00:00+00:00"
    assert len(body["categories"]) == 9


def test_a_category_chip_lists_that_category(nabiz: Nabiz, catalog: pathlib.Path) -> None:
    body = client(nabiz).get("/api/datasets", params={"category": "Çevre"}).json()
    assert body["mode"] == "category" and {hit["name"] for hit in body["datasets"]} == {
        "istanbul-barajlari-gunluk-doluluk-oranlari", "parklar-ve-yesil-alanlar",
    }  # fmt: skip


def test_no_catalogue_is_a_503_the_page_can_show(nabiz: Nabiz) -> None:
    response = client(nabiz).get("/api/datasets", params={"q": "otopark"})
    assert response.status_code == 503
    assert response.json() == {"error": "catalog_missing", "message": CATALOG_MISSING}


def test_a_bad_category_is_a_400(nabiz: Nabiz, catalog: pathlib.Path) -> None:
    response = client(nabiz).get("/api/datasets", params={"category": "Spor"})
    assert response.status_code == 400 and "Mobilite" in response.json()["message"]
