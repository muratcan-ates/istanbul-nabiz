import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nabiz.console.ms_oauth import MemoryTokenStore
from nabiz.console.plan_store import PlanStore
from nabiz.console.plans_api import plans_routes


def payload(operation_id="op-save", **changes):
    return {
        "title": "Sergi", "starts_at": "2026-10-03", "ends_at": "2026-10-04", "all_day": True,
        "time_zone": "Europe/Istanbul", "place": "Kadıköy", "source_url": None, "source_date": None,
        "conversation_id": "chat-1", "operation_id": operation_id, "consent": True, **changes,
    }


def app_for(tmp_path):
    app = FastAPI()
    app.include_router(plans_routes)
    app.state.plan_store = PlanStore(tmp_path / "plans.sqlite3")
    app.state.plan_principal = lambda request: request.headers.get("x-test-principal")
    return app


def test_api_consent_owner_replay_and_saturday_edit(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app, headers={"x-test-principal": "owner"}) as client:
        assert client.post("/api/plans", json=payload(consent=False)).status_code == 400
        assert client.post("/api/plans", json=payload(sensitive=True)).status_code == 400
        first = client.post("/api/plans", json=payload()).json()
        assert first["result"] == "saved_nabiz"
        assert first["message"] == "Nabız'a kaydedildi"
        plan_id = first["plan"]["id"]
        assert client.post("/api/plans", json=payload()).json()["plan"]["id"] == plan_id
        assert client.post("/api/plans", json=payload(title="Başka")).status_code == 409
        changed = client.patch(
            f"/api/plans/{plan_id}",
            json=payload("op-saturday", starts_at="2026-10-10", ends_at="2026-10-11"),
        ).json()
        assert changed["plan"]["id"] == plan_id
        assert changed["plan"]["starts_at"] == "2026-10-10"
        assert len(client.get("/api/plans").json()["plans"]) == 1
    with TestClient(app, headers={"x-test-principal": "other"}) as client:
        assert client.get(f"/api/plans/{plan_id}").status_code == 404
        assert client.get("/api/plans").json()["plans"] == []
    with TestClient(app) as client:
        assert client.get("/api/plans").status_code == 503


def test_outlook_denied_and_disabled_do_not_erase_nabiz(tmp_path, monkeypatch):
    app = app_for(tmp_path)
    monkeypatch.delenv("NABIZ_MS_CLIENT_ID", raising=False)
    monkeypatch.delenv("NABIZ_MS_REDIRECT_URI", raising=False)
    with TestClient(app, headers={"x-test-principal": "owner"}) as client:
        plan_id = client.post("/api/plans", json=payload()).json()["plan"]["id"]
        disabled = client.post(f"/api/plans/{plan_id}/outlook", json={"operation_id": "op-graph", "consent": True}).json()
        assert disabled["message"] == "Outlook bağlantısı kapalı"
        assert disabled["result"] == "outlook_failed"
        assert len(client.get("/api/plans").json()["plans"]) == 1
        monkeypatch.setenv("NABIZ_MS_CLIENT_ID", "fake-client")
        monkeypatch.setenv("NABIZ_MS_REDIRECT_URI", "http://localhost/callback")
        vault = MemoryTokenStore()
        vault.put("owner", "fake-token")
        app.state.plan_tokens = vault
        app.state.plan_graph_client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403)))
        denied = client.post(f"/api/plans/{plan_id}/outlook", json={"operation_id": "op-graph-2", "consent": True}).json()
        assert denied["message"] == "Outlook'a eklenemedi"
        assert denied["result"] == "outlook_failed"
        assert len(client.get("/api/plans").json()["plans"]) == 1
        app.state.plan_graph_client.close()


def test_unbound_principal_does_not_create_database(tmp_path, monkeypatch):
    database = tmp_path / "must-not-exist.sqlite3"
    monkeypatch.setenv("NABIZ_PLAN_DB_PATH", str(database))
    app = FastAPI()
    app.include_router(plans_routes)
    with TestClient(app) as client:
        assert client.get("/api/plans").status_code == 503
        assert client.post("/api/plans", json=payload()).status_code == 503
    assert not database.exists()
