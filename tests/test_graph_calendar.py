import httpx

from nabiz.console.graph_calendar import GRAPH_EVENTS, GraphCalendar
from nabiz.console.plan_store import TIME_ZONE


def plan():
    return {"title": "Sergi", "starts_at": "2026-10-03", "ends_at": "2026-10-04", "all_day": True, "place": "Kadıköy"}


def test_graph_confirmed_personal_all_day_event():
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == GRAPH_EVENTS
        assert request.method == "POST"
        data = __import__("json").loads(request.content)
        assert data["transactionId"] == "op-1"
        assert data["attendees"] == []
        assert data["start"] == {"dateTime": "2026-10-03T00:00:00", "timeZone": TIME_ZONE}
        return httpx.Response(201, json={"id": "graph-1"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = GraphCalendar(client).add(plan(), "op-1", "fake-token")
    assert result.result == "outlook_added"
    assert result.event_id == "graph-1"
    assert len(calls) == 1


def test_graph_403_and_uncertain_retries_same_transaction():
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403))) as client:
        assert GraphCalendar(client).add(plan(), "op", "fake").message == "Outlook'a eklenemedi"
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("uncertain")

    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        result = GraphCalendar(client).add(plan(), "op", "fake")
    assert result.result == "outlook_verifying"
    assert len(calls) == 2
    assert calls[0].content == calls[1].content


def test_graph_without_provider_id_never_claims_success():
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(201, json={}))) as client:
        assert GraphCalendar(client).add(plan(), "op", "fake").result == "outlook_verifying"


def test_graph_denial_after_uncertain_response_stays_unverified():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("uncertain")
        return httpx.Response(403)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert GraphCalendar(client).add(plan(), "op", "fake").result == "outlook_verifying"
