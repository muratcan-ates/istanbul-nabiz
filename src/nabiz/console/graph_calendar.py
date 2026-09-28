"""Personal Outlook event creation with bounded, idempotent uncertainty handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from nabiz.console.plan_store import TIME_ZONE

GRAPH_EVENTS = "https://graph.microsoft.com/v1.0/me/events"


@dataclass(frozen=True)
class GraphResult:
    result: str
    message: str
    event_id: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {"result": self.result, "message": self.message, "event_id": self.event_id}


def _payload(plan: dict[str, Any], operation_id: str) -> dict[str, Any]:
    start = plan["starts_at"]
    end = plan["ends_at"]
    if plan["all_day"]:
        start += "T00:00:00"
        end += "T00:00:00"
    payload: dict[str, Any] = {
        "subject": plan["title"],
        "start": {"dateTime": start, "timeZone": TIME_ZONE},
        "end": {"dateTime": end, "timeZone": TIME_ZONE},
        "isAllDay": plan["all_day"],
        "transactionId": operation_id,
        "attendees": [],
    }
    if plan["place"]:
        payload["location"] = {"displayName": plan["place"]}
    return payload


class GraphCalendar:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def add(self, plan: dict[str, Any], operation_id: str, access_token: str) -> GraphResult:
        if not access_token:
            return GraphResult("outlook_failed", "Outlook bağlantısı kapalı")
        payload = _payload(plan, operation_id)
        headers = {"Authorization": f"Bearer {access_token}"}
        uncertain = False
        for attempt in range(2):
            try:
                response = self.client.post(GRAPH_EVENTS, json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError):
                uncertain = True
                if attempt == 0:
                    continue
                return GraphResult("outlook_verifying", "Outlook işlemi doğrulanıyor")
            if response.status_code in (408, 429, 500, 502, 503, 504):
                uncertain = True
                if attempt == 0:
                    continue
                return GraphResult("outlook_verifying", "Outlook işlemi doğrulanıyor")
            return _settled_response(response, uncertain)
        return GraphResult("outlook_verifying", "Outlook işlemi doğrulanıyor")


def _settled_response(response: httpx.Response, uncertain: bool) -> GraphResult:
    if response.status_code in (200, 201):
        return _confirmed(response)
    if uncertain:
        return GraphResult("outlook_verifying", "Outlook işlemi doğrulanıyor")
    return GraphResult("outlook_failed", "Outlook'a eklenemedi")


def _confirmed(response: httpx.Response) -> GraphResult:
    try:
        event_id = response.json().get("id")
    except ValueError:
        event_id = None
    if isinstance(event_id, str) and event_id:
        return GraphResult("outlook_added", "Outlook'a eklendi", event_id)
    return GraphResult("outlook_verifying", "Outlook işlemi doğrulanıyor")
