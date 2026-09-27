"""Story 3: a photo, an example operator, the result back on the citizen's code (docs/acceptance/HIKAYE-3.md).

The base already closes the loop with text: a request with consent gets one code, the example
operator reads it behind the token and replies, and the citizen reads the reply on the same code.
The photo report, its timeline and the no-store headers on the operator's refusals come with P00 G2.
"""

from __future__ import annotations

import base64
import struct
import zlib

import httpx
import pytest
from fastapi.testclient import TestClient
from test_console_chat import FakeModel

from acceptance.support import BASE_URL, CLOUD, OPERATOR, after, build_app, offline_nabiz
from nabiz.agent import llm

PHONE = "0532 123 45 67"
SIMULATED = "resmî İBB hizmeti değildir"
GERMAN = "Wo kann ich meine Istanbulkart aufladen?"


def _png(width: int = 2, height: int = 2) -> bytes:
    """A real, tiny PNG (RGB, no metadata chunk), built here so no binary file is committed."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def _photo_body(photo: bytes, *, place: str = "Kadıköy", consent: bool = True) -> dict[str, object]:
    return {
        "photo": base64.b64encode(photo).decode("ascii"),
        "category": "pavement",
        "description": f"Kaldırım taşı kırık, telefonum {PHONE}",
        "place": {"kind": "district", "name": place},
        "lang": "tr",
        "consent": consent,
    }


# ---- the base: the loop with text ---------------------------------------------------------------------


def test_one_code_carries_the_request_to_the_operator_and_the_reply_back(client: TestClient) -> None:
    """Steps 3 to 8: consent, one code, the masked text in the queue, a person's reply on the same code."""
    text = f"Kartal'da kaldırım kırık, telefonum {PHONE}"
    created = client.post("/api/requests", json={"text": text, "lang": "tr", "consent": True})
    assert created.status_code == 201, created.text
    assert created.headers.get("cache-control") == "no-store"
    card = created.json()
    code = card["code"]
    assert card["status"] == "waiting" and PHONE not in card["question"] and "[TELEFON]" in card["question"]
    assert SIMULATED in card["simulated"] and "112" in card["note"]

    queue = client.get("/api/console/requests", headers=OPERATOR).json()
    assert [item["code"] for item in queue["items"]] == [code]
    assert PHONE not in str(queue), "the operator sees the masked text only"

    reply = "Ekip bilgilendirildi; simüle yanıt."
    sent = client.post(f"/api/console/requests/{code}/reply", headers=OPERATOR, json={"text_tr": reply})
    assert sent.status_code == 200, sent.text

    back = client.get(f"/api/requests/{code}").json()
    assert back["status"] == "answered" and back["reply"]["text"] == reply
    assert back["reply"]["label"] == "Bu yanıt bir İBB çalışanı tarafından yazıldı."
    assert SIMULATED in back["simulated"], "the example operator is never presented as İBB's service"


def test_a_restart_keeps_the_request_and_its_reply(stores: object) -> None:
    """Criterion 12: the demo laptop restarts between rehearsals; the citizen's code still opens the same card."""
    with TestClient(build_app(offline_nabiz()), base_url=BASE_URL) as first:
        created = first.post("/api/requests", json={"text": "Kartal'da kaldırım kırık", "lang": "tr", "consent": True})
        code = created.json()["code"]
        first.post(f"/api/console/requests/{code}/reply", headers=OPERATOR, json={"text_tr": "Simüle yanıt."})
    with TestClient(build_app(offline_nabiz()), base_url=BASE_URL) as second:
        card = second.get(f"/api/requests/{code}").json()
    assert card["status"] == "answered" and card["reply"]["text"] == "Simüle yanıt."


def test_no_consent_no_record(client: TestClient) -> None:
    """Step 2 (permission refused): without the box ticked nothing is kept, not even a code."""
    refused = client.post("/api/requests", json={"text": "Kartal'da kaldırım kırık", "lang": "tr", "consent": False})
    assert refused.status_code == 400 and refused.json()["error"] == "consent_required"
    assert client.get("/api/console/requests", headers=OPERATOR).json()["items"] == []


def test_the_operator_door_is_shut_without_the_token(client: TestClient) -> None:
    """Criterion 8's access split: a citizen reads their code; only the operator reads the queue or replies."""
    client.post("/api/requests", json={"text": "Kartal'da kaldırım kırık", "lang": "tr", "consent": True})
    for method, path in (("GET", "/api/console/requests"), ("POST", "/api/console/requests/AAAAAAAA/reply")):
        response = client.request(method, path, json={"text_tr": "x"})
        assert response.status_code == 401 and response.json()["error"] == "unauthorized"
        assert "kaldırım" not in response.text


def test_a_guessed_code_opens_nothing(client: TestClient) -> None:
    client.post("/api/requests", json={"text": "Kartal'da kaldırım kırık", "lang": "tr", "consent": True})
    response = client.get("/api/requests/ZZZZZZZZ")
    assert response.status_code == 404 and "kaldırım" not in response.text


def test_an_emergency_goes_to_112_and_never_waits_in_the_queue(client: TestClient) -> None:
    response = client.post("/api/requests", json={"text": "Yangın var, binada duman", "lang": "tr", "consent": True})
    assert response.status_code == 200 and response.json()["emergency"] is True and response.json()["tel"] == "112"
    assert client.get("/api/console/requests", headers=OPERATOR).json()["items"] == []


def test_a_model_outage_keeps_the_original_text_and_says_there_is_no_translation(
    stores: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 10 (an outage): the translation model is down; the request still arrives, labelled honestly."""
    monkeypatch.setattr(llm, "chat", FakeModel(*(httpx.ConnectError("model down") for _ in range(3))))
    with TestClient(build_app(offline_nabiz(), config=CLOUD), base_url=BASE_URL) as client:
        created = client.post("/api/requests", json={"text": GERMAN, "lang": "auto", "consent": True})
        assert created.status_code == 201, created.text
        item = client.get("/api/console/requests", headers=OPERATOR).json()["items"][0]
    assert "Çeviri şu an yok" in created.json()["translation_note"]
    assert item["translation"]["status"] == "failed" and item["turkish"] is None
    assert item["original"] == GERMAN


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Criterion 3: the request mask (pii_guard) hides identity numbers, phones and e-mail, not a health "
        "condition; 'Diyabetim var' reaches the operator's queue as written."
    ),
)
def test_a_health_detail_the_operator_does_not_need_is_not_passed_on(client: TestClient) -> None:
    text = "Diyabetim var ve tekerlekli sandalye kullanıyorum, Kadıköy kütüphanesine rampa var mı?"
    created = client.post("/api/requests", json={"text": text, "lang": "tr", "consent": True})
    assert created.status_code == 201, created.text
    queue = client.get("/api/console/requests", headers=OPERATOR).json()
    assert "diyabet" not in str(queue).casefold()


# ---- P00 G2: the photo report, its timeline, the operator's no-store refusals ------------------------------


@after("G2", "/api/photo-reports", "POST")
def test_a_photo_report_needs_consent_and_gets_one_code_without_the_photo(client: TestClient) -> None:
    refused = client.post("/api/photo-reports", json=_photo_body(_png(), consent=False))
    assert refused.status_code == 400 and refused.json()["error"] == "consent_required"
    created = client.post("/api/photo-reports", json=_photo_body(_png()))
    assert created.status_code == 201, created.text
    assert created.headers.get("cache-control") == "no-store"
    card = created.json()
    assert PHONE not in created.text and card["masked_count"] >= 1, "the description is masked"
    assert "photo" not in card and "base64" not in created.text, "the citizen's card never carries the photo"
    again = client.get(f"/api/photo-reports/{card['code']}")
    assert again.status_code == 200 and again.json()["code"] == card["code"], "one code, read back"
    assert client.delete(f"/api/photo-reports/{card['code']}").json() == {"deleted": True}
    assert client.get(f"/api/photo-reports/{card['code']}").status_code == 404, "deleted means gone"


@after("G2", "/api/photo-reports", "POST")
def test_a_wrong_place_is_refused_then_the_corrected_one_is_taken(client: TestClient) -> None:
    """Step 5 (correction): an unknown place is not guessed; the corrected district is accepted."""
    wrong = client.post("/api/photo-reports", json=_photo_body(_png(), place="Atlantis"))
    assert wrong.status_code == 400 and wrong.json()["error"] == "unknown_place"
    right = client.post("/api/photo-reports", json=_photo_body(_png(), place="kadıköy"))
    assert right.status_code == 201 and right.json()["place"] == {"kind": "district", "name": "Kadıköy"}


@after("G2", "/api/photo-reports", "POST")
def test_an_unsupported_file_is_refused_with_a_plain_reason(client: TestClient) -> None:
    gif = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00"
    gif += b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    response = client.post("/api/photo-reports", json=_photo_body(gif))
    assert response.status_code == 415 and response.json()["error"] == "bad_type"
    assert client.get("/api/console/photo-reports", headers=OPERATOR).json()["items"] == []


@after("G2", "/api/photo-reports", "POST")
def test_operator_refusals_are_not_cached(client: TestClient) -> None:
    for path in ("/api/console/photo-reports", "/api/console/requests", "/api/console/queue"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.headers.get("cache-control") == "no-store", path


@after("G2", "/api/report/timeline/{code}")
def test_the_timeline_opens_only_a_real_code(client: TestClient) -> None:
    invalid = client.get("/api/report/timeline/not-a-code")
    assert invalid.status_code in {404, 422, 503}
    unknown = client.get("/api/report/timeline/ZZZZZZZZ")
    assert unknown.status_code in {404, 503} and "history" not in unknown.text
