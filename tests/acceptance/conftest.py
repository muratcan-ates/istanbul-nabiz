"""One isolated app per acceptance test: every store the stories write lives in the test's own folder."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acceptance.support import BASE_URL, ROOT, build_app, offline_nabiz

#: Every file a story can write, by the variable that moves it (the P00 ones too, so a merged group
#: never writes into data/ from a test).
STORE_PATHS = {
    "NEXUS_DB_PATH": "nexus.db",
    "NABIZ_REQUESTS_DB_PATH": "requests.db",
    "NABIZ_ACCOUNTS_DB": "accounts.sqlite",
    "NABIZ_OUTBOX_DIR": "outbox",
    "NABIZ_CHAT_PAUSE_PATH": "chat-paused.json",
    "NABIZ_PHOTO_REPORTS_DB_PATH": "photo-reports.db",
    "NABIZ_REPORT_TIMELINE_DB_PATH": "report-timeline.db",
    "NABIZ_JOURNEY_WATCH_DB_PATH": "journey-watch.db",
}


@pytest.fixture
def stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name, filename in STORE_PATHS.items():
        monkeypatch.setenv(name, str(tmp_path / filename))
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(ROOT / "tests" / "no-knowledge-index.db"))
    monkeypatch.setenv("NABIZ_CHAT_TURNS_PER_MIN", "10000")
    monkeypatch.delenv("NABIZ_REQUESTS_PER_HOUR", raising=False)
    monkeypatch.delenv("NABIZ_LLM_BASE_URL", raising=False)
    return tmp_path


@pytest.fixture
def client(stores: Path) -> Iterator[TestClient]:
    """The product app without a model: the rules answer, as on the demo laptop when the model is down."""
    with TestClient(build_app(offline_nabiz()), base_url=BASE_URL) as test_client:
        yield test_client
