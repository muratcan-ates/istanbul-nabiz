"""Tests for the events source — the honest refusal, and the plug point behind it.

Two halves, and the split is the point of epic E3:

1. **The refusal is asserted, not assumed.** With no adapter (the state of the world on
   2026-09-13) every query must come back ``available: False``, carrying a reason and the
   URLs that were checked, with an empty event list and no İBB licence stamp on a payload
   that contains no İBB data.
2. **The adapter contract works**, exercised by a fake feed defined *in this file*.
   ``FakeFeed`` exists so that the day a real feed appears, the filtering and ranking it
   will run through are already tested. Its three events are obvious fiction
   (``fake-1..3``) and must never leave this module — nothing under ``src/`` may contain
   an event record.

The third element is a recorded slice of the one API candidate, :data:`GETACTIVITIES_SAMPLE`,
captured live on 2026-09-13. It is here so the negative finding is reproducible from the
repository rather than from a sentence in a document.
"""

from __future__ import annotations

import datetime as dt

import pytest

from ibb_mcp.http import UpstreamUnavailable
from ibb_mcp.models import ISTANBUL_TZ
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.sources.events import (
    EVIDENCE,
    CandidateEvidence,
    Event,
    EventsFeedAdapter,
    EventsSource,
)

# --------------------------------------------------------------------------------------
# Recorded evidence: three records from GetActivities, captured 2026-09-13.
# `Content` is truncated to its first clause — the field is a 2-4 KB HTML press release
# and its length is not what is being asserted. Nothing else is edited.
# --------------------------------------------------------------------------------------
GETACTIVITIES_SAMPLE: dict = {
    "Success": True,
    "Error": None,
    "Data": [
        {
            "Id": 24,
            "Title": "Metro İstanbul'a Toplumsal Cinsiyet Eşitliği Alanında Bir Ödül de SODEV'den",
            "Content": "<p><strong>İstanbul B&uuml;y&uuml;kşehir Belediyesi (İBB) iştiraklerinden…</strong></p>",
            "Photo": "https://www.metro.istanbul/Content/assets/uploaded/e4076e8e-4887-40bb-ad8a-64e37ab1c214.jpg",
            "StartDate": "2021-11-29T00:00:00.000",
            "Language": "TR",
            "Media": {"Video": None, "Images": []},
        },
        {
            "Id": 141,
            "Title": "29 Mayıs'ta Edirnekapı'dan Saraçhane'ye Yürüyoruz",
            "Content": "<p>İstanbul'un fethinin yıl d&ouml;n&uuml;m&uuml; y&uuml;r&uuml;y&uuml;ş&uuml;…</p>",
            "Photo": "https://www.metro.istanbul/Content/assets/uploaded/ba7f7c22-c8fd-42cb-bb02-fb223470d1da.JPG",
            "StartDate": "2025-11-20T00:00:00.000",
            "Language": "TR",
            "Media": {"Video": None, "Images": []},
        },
        {
            "Id": 167,
            "Title": "Metro İstanbul'da Sömestir Heyecanı: Kayıtlar Başladı",
            "Content": "<p>Sömestir tatilinde &ccedil;ocuklar i&ccedil;in…</p>",
            "Photo": "https://www.metro.istanbul/Content/assets/uploaded/11026508-4e02-486a-9e48-fe4f8fa7f8d7.jpg",
            "StartDate": "2026-02-05T00:00:00.000",
            "Language": "TR",
            "Media": {"Video": None, "Images": []},
        },
    ],
}

#: The day the research ran. Used to show the newest record was already stale by then.
RESEARCH_DAY = dt.date(2026, 9, 13)


# --------------------------------------------------------------------------------------
# A fake feed. Test-only fiction; see the module docstring.
# --------------------------------------------------------------------------------------
def _ist(year: int, month: int, day: int, hour: int) -> dt.datetime:
    """An İstanbul wall-clock time as the UTC instant a feed would publish."""
    return dt.datetime(year, month, day, hour, tzinfo=ISTANBUL_TZ).astimezone(dt.UTC)


class FakeFeed:
    """Minimal :class:`EventsFeedAdapter` implementation, with a call counter."""

    name = "fake_feed"
    source_url = "https://example.invalid/fake-events"
    license = "test fixture — not real data"

    def __init__(self, events: list[Event] | None = None, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error
        self.events = events if events is not None else _fake_events()

    async def fetch(self) -> list[Event]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.events


def _fake_events() -> list[Event]:
    return [
        Event(
            event_id="fake-1",
            title="Akşam Konseri",
            start=_ist(2026, 9, 20, 20),
            venue="Sahne A",
            district="Kadıköy",
            lat=40.9903,
            lon=29.0270,
            category="konser",
        ),
        Event(
            event_id="fake-2",
            title="Fotoğraf Sergisi",
            start=_ist(2026, 9, 21, 11),
            venue="Galeri B",
            district="Beşiktaş",
            lat=41.0430,
            lon=29.0060,
            category="sergi",
        ),
        Event(
            event_id="fake-3",
            title="Şiir Atölyesi",
            start=_ist(2026, 9, 20, 15),
            venue="Merkez C",
            district="Kadıköy",
            category="atölye",
        ),  # deliberately has no coordinates
    ]


@pytest.fixture
def feed() -> FakeFeed:
    return FakeFeed()


# --------------------------------------------------------------------------------------
# 1. The refusal (no adapter — today's state of the world)
# --------------------------------------------------------------------------------------
async def test_search_refuses_without_adapter(ctx: SourceContext) -> None:
    source = EventsSource(ctx)
    assert source.available is False

    payload, provenance = await source.search()

    assert payload["available"] is False
    assert payload["events"] == []
    assert "yayınlamıyor" in payload["reason"]
    assert payload["checked_on"] == "2026-09-13"
    assert provenance.source == "events"
    assert provenance.source_url.startswith("https://data.ibb.gov.tr/")


async def test_refusal_does_not_claim_the_ibb_licence(ctx: SourceContext) -> None:
    """A payload with no İBB data in it must not be stamped with İBB's open-data licence."""
    _, provenance = await EventsSource(ctx).search()
    assert "CC BY" not in provenance.license
    assert provenance.license == "n/a — veri döndürülmedi"


async def test_near_refuses_without_adapter(ctx: SourceContext) -> None:
    payload, _ = await EventsSource(ctx).near(41.0082, 28.9784)
    assert payload["available"] is False
    assert payload["events"] == []


def test_availability_reports_the_refusal(ctx: SourceContext) -> None:
    assert EventsSource(ctx).availability()["available"] is False


async def test_refusal_carries_checkable_evidence(ctx: SourceContext) -> None:
    """The 'no' must be falsifiable: every claim ships with a URL and a date."""
    payload, _ = await EventsSource(ctx).search()
    evidence = payload["evidence"]

    assert len(evidence) >= 5
    for item in evidence:
        assert item["url"].startswith("https://")
        assert item["checked_on"] == "2026-09-13"
        assert item["detail"]

    urls = " ".join(item["url"] for item in evidence)
    assert "GetActivities" in urls  # the only API candidate
    assert "kultur.istanbul" in urls  # the real calendar, closed licence
    assert "istanbulsenin" in urls  # the super-app


def test_every_evidence_entry_is_a_model() -> None:
    assert all(isinstance(item, CandidateEvidence) for item in EVIDENCE)


async def test_refusal_suggests_where_a_human_should_look(ctx: SourceContext) -> None:
    payload, _ = await EventsSource(ctx).search()
    assert "kultur.istanbul" in payload["reason"]
    assert "docs/events_research.md" in payload["what_would_unblock_it"]


# --------------------------------------------------------------------------------------
# 2. Why the one API candidate was rejected — asserted against the recorded capture
# --------------------------------------------------------------------------------------
def test_getactivities_capture_has_no_event_fields() -> None:
    """GetActivities carries none of the fields an event recommendation needs."""
    records = GETACTIVITIES_SAMPLE["Data"]
    fields = {key for record in records for key in record}
    assert fields == {"Id", "Title", "Content", "Photo", "StartDate", "Language", "Media"}

    for absent in ("Venue", "Location", "District", "Latitude", "Longitude", "EndDate", "Category", "Price"):
        assert absent not in fields


def test_getactivities_capture_is_backward_looking_and_stale() -> None:
    """No future-dated record, and the newest one was already seven months old."""
    starts = [dt.date.fromisoformat(r["StartDate"][:10]) for r in GETACTIVITIES_SAMPLE["Data"]]
    assert all(start < RESEARCH_DAY for start in starts)
    assert (RESEARCH_DAY - max(starts)).days > 180


def test_getactivities_startdate_is_a_publication_date() -> None:
    """The clincher: a record stamped 2025-11-20 describes an event held on 29 May.

    That single row rules the feed out as a calendar — the timestamp does not date the
    event, so no date filter over it could ever be honest.
    """
    record = next(r for r in GETACTIVITIES_SAMPLE["Data"] if r["Id"] == 141)
    assert record["StartDate"].startswith("2025-11-20")
    assert "29 Mayıs" in record["Title"]


# --------------------------------------------------------------------------------------
# 3. The plug point: a real feed drops in without touching EventsSource
# --------------------------------------------------------------------------------------
def test_fake_feed_satisfies_the_adapter_protocol(feed: FakeFeed) -> None:
    assert isinstance(feed, EventsFeedAdapter)


async def test_search_with_adapter_returns_events_in_time_order(ctx: SourceContext, feed: FakeFeed) -> None:
    payload, provenance = await EventsSource(ctx, adapter=feed).search(limit=10)

    assert payload["available"] is True
    assert payload["matched"] == 3
    assert [e["event_id"] for e in payload["events"]] == ["fake-3", "fake-1", "fake-2"]
    assert provenance.source == "events:fake_feed"
    assert provenance.source_url == "https://example.invalid/fake-events"
    assert provenance.license == "test fixture — not real data"


async def test_search_filters_by_istanbul_calendar_day(ctx: SourceContext, feed: FakeFeed) -> None:
    """'20 Eylül' means the İstanbul day, not the UTC one — the 20:00 concert is UTC 17:00."""
    payload, _ = await EventsSource(ctx, adapter=feed).search(
        date_from=dt.date(2026, 9, 20), date_to=dt.date(2026, 9, 20)
    )
    assert {e["event_id"] for e in payload["events"]} == {"fake-1", "fake-3"}


async def test_search_folds_turkish_when_filtering(ctx: SourceContext, feed: FakeFeed) -> None:
    payload, _ = await EventsSource(ctx, adapter=feed).search(district="kadikoy")
    assert {e["event_id"] for e in payload["events"]} == {"fake-1", "fake-3"}

    payload, _ = await EventsSource(ctx, adapter=feed).search(category="ATÖLYE")
    assert [e["event_id"] for e in payload["events"]] == ["fake-3"]

    payload, _ = await EventsSource(ctx, adapter=feed).search(query="sergi")
    assert [e["event_id"] for e in payload["events"]] == ["fake-2"]


async def test_search_reports_an_empty_match_without_pretending_it_failed(ctx: SourceContext, feed: FakeFeed) -> None:
    payload, _ = await EventsSource(ctx, adapter=feed).search(district="Silivri")
    assert payload["available"] is True
    assert payload["events"] == []
    assert payload["note"] == "Ölçütlere uyan etkinlik bulunamadı."


async def test_search_honours_the_limit(ctx: SourceContext, feed: FakeFeed) -> None:
    payload, _ = await EventsSource(ctx, adapter=feed).search(limit=1)
    assert payload["returned"] == 1
    assert payload["matched"] == 3
    assert len(payload["events"]) == 1


async def test_near_ranks_by_distance_and_drops_events_without_coordinates(
    ctx: SourceContext, feed: FakeFeed
) -> None:
    # Kadıköy iskele; the concert is ~600 m away, the Beşiktaş sergi is across the water.
    payload, _ = await EventsSource(ctx, adapter=feed).near(40.9920, 29.0240, radius_km=2.0)

    assert [e["event_id"] for e in payload["events"]] == ["fake-1"]
    assert payload["events"][0]["distance_km"] < 0.5
    # fake-3 has no coordinate: excluded, and said so rather than silently dropped.
    assert payload["without_coordinates"] == 1
    assert payload["radius_km"] == 2.0


async def test_near_widens_to_include_the_other_shore(ctx: SourceContext, feed: FakeFeed) -> None:
    payload, _ = await EventsSource(ctx, adapter=feed).near(40.9920, 29.0240, radius_km=10.0, limit=10)
    assert [e["event_id"] for e in payload["events"]] == ["fake-1", "fake-2"]


async def test_two_queries_cost_one_upstream_fetch(ctx: SourceContext, feed: FakeFeed) -> None:
    """The cache rule applies to a future feed as it does to every other source."""
    source = EventsSource(ctx, adapter=feed)
    await source.search()
    await source.near(40.9920, 29.0240)
    assert feed.calls == 1


async def test_adapter_failure_propagates_instead_of_reading_as_no_events(ctx: SourceContext) -> None:
    """An outage must not be rendered as 'bugün etkinlik yok'."""
    broken = FakeFeed(error=UpstreamUnavailable("feed down", source="events"))
    with pytest.raises(UpstreamUnavailable):
        await EventsSource(ctx, adapter=broken).search()


async def test_no_event_data_ships_in_the_source_module() -> None:
    """Guard the module's central promise: src/ contains no event records."""
    import inspect

    import ibb_mcp.sources.events as module

    text = inspect.getsource(module)
    assert "fake-1" not in text
    assert not [
        obj
        for obj in vars(module).values()
        if isinstance(obj, Event) or (isinstance(obj, list | tuple) and any(isinstance(x, Event) for x in obj))
    ]
