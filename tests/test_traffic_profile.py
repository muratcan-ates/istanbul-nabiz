"""Tests for the weekday × hour traffic baseline.

The module's whole value is that it refuses to guess, so most of what is asserted here is a
refusal: an hour with two observations must come back as ``unknown``, an empty series must
produce an empty baseline rather than an exception, and a gridlocked evening must not be allowed
to move the median. The one arithmetic trap worth a test of its own is the timezone: Türkiye is
UTC+3, so a reading stamped 22:30Z belongs to the *next* day's 01:00 cell in İstanbul, and a
baseline built on the UTC clock would be three hours — and at the day boundary a whole weekday —
wrong.

All fixtures are synthetic; nothing here touches İBB. The façade tests at the end run the
tool layer sealed off from ``data/lake`` and ``data/reference/gtfs`` (see
``tests/test_tools_extra.py``), over the recorded one-day traffic fixture — which is exactly
why the baseline they see is empty and every comparison must say "unknown".
"""

from __future__ import annotations

import datetime as dt
import pathlib
from typing import Any

import pytest
from test_tools_extra import sealed, sealed_nabiz  # noqa: F401 - ``sealed`` is a fixture used by name

from ibb_mcp.http import UpstreamUnavailable
from ibb_mcp.models import TrafficIndexPoint
from ibb_mcp.sources.traffic import TrafficSource
from ibb_mcp.tools import Nabiz
from ibb_mcp.traffic_profile import (
    CELLS_PER_WEEK,
    MIN_SAMPLES,
    TrafficBaseline,
    build_baseline,
    compare_to_typical,
)

# 2026-09-08 is a Tuesday; every date used below is derived from it so the weekday arithmetic in
# the assertions is checkable by eye.
TUESDAY = dt.date(2026, 9, 8)
MONDAY = 0
TUESDAY_IDX = 1
WEDNESDAY = 2


def point(when: dt.datetime, index: int) -> TrafficIndexPoint:
    return TrafficIndexPoint(index=index, at=when)


def utc(date: dt.date, hour: int, minute: int = 30) -> dt.datetime:
    return dt.datetime(date.year, date.month, date.day, hour, minute, tzinfo=dt.UTC)


def weekly(date: dt.date, hour: int, values: list[int]) -> list[TrafficIndexPoint]:
    """One point per week at the same UTC clock time, oldest first."""
    return [point(utc(date - dt.timedelta(weeks=offset), hour), value) for offset, value in enumerate(values)]


def test_buckets_by_istanbul_local_time_not_utc() -> None:
    """22:30 UTC on a Tuesday is 01:30 Wednesday in İstanbul — the baseline must agree."""
    points = weekly(TUESDAY, 22, [40, 44, 48])

    baseline = build_baseline(points)

    assert (WEDNESDAY, 1) in baseline.cells, "reading should land in the İstanbul cell"
    assert (TUESDAY_IDX, 22) not in baseline.counts, "UTC weekday/hour must not be used as a key"
    assert baseline.typical(WEDNESDAY, 1) == 44.0
    assert baseline.typical(TUESDAY_IDX, 22) is None
    assert baseline.sample_count == 3
    assert baseline.days_covered == 3


def test_comparison_uses_the_istanbul_cell() -> None:
    """The same shift applies on the way back out: a 22:30Z moment reads the Wednesday 01:00 cell."""
    baseline = build_baseline(weekly(TUESDAY, 22, [40, 44, 48]))

    comparison = compare_to_typical(70, utc(TUESDAY, 22), baseline)

    assert comparison.typical == 44.0
    assert comparison.band == "much_heavier"
    assert comparison.samples == 3


def test_naive_moment_is_read_as_istanbul_wall_clock() -> None:
    baseline = build_baseline(weekly(TUESDAY, 22, [40, 44, 48]))

    # 01:30 on Wednesday, written the way a person names a clock.
    comparison = compare_to_typical(44, dt.datetime(2026, 9, 9, 1, 30), baseline)

    assert comparison.typical == 44.0
    assert comparison.band == "typical"


def test_thin_cell_is_unknown_not_guessed() -> None:
    """Two observations is below MIN_SAMPLES, so there is no 'typical' to report."""
    baseline = build_baseline(weekly(TUESDAY, 6, [55, 57]))

    assert baseline.typical(TUESDAY_IDX, 9) is None
    assert baseline.samples_at(TUESDAY_IDX, 9) == 2
    assert baseline.cells == {}

    comparison = compare_to_typical(90, utc(TUESDAY, 6), baseline)

    assert comparison.typical is None
    assert comparison.delta is None
    assert comparison.ratio is None
    assert comparison.band == "unknown"
    assert comparison.available is False
    assert comparison.samples == 2
    assert "2 gözlem" in comparison.description_tr
    assert f"en az {MIN_SAMPLES}" in comparison.description_tr
    assert "2 samples" in comparison.description_en


def test_unseen_cell_is_unknown_with_zero_samples() -> None:
    baseline = build_baseline(weekly(TUESDAY, 6, [55, 57, 59]))

    comparison = compare_to_typical(60, utc(TUESDAY, 15), baseline)

    assert comparison.band == "unknown"
    assert comparison.samples == 0
    assert comparison.description_tr.strip() != ""


def test_stricter_min_samples_can_only_tighten_the_floor() -> None:
    baseline = build_baseline(weekly(TUESDAY, 6, [55, 57, 59]))

    assert compare_to_typical(60, utc(TUESDAY, 6), baseline).typical == 57.0
    assert compare_to_typical(60, utc(TUESDAY, 6), baseline, min_samples=5).band == "unknown"
    # A looser floor cannot resurrect medians that were never stored, but must not raise either.
    assert compare_to_typical(60, utc(TUESDAY, 6), baseline, min_samples=1).typical == 57.0


def test_median_not_mean() -> None:
    """One gridlocked evening must not move the baseline: median 40, mean would be 54.75."""
    baseline = build_baseline(weekly(TUESDAY, 15, [40, 40, 40, 99]))

    assert baseline.typical(TUESDAY_IDX, 18) == 40.0
    assert baseline.samples_at(TUESDAY_IDX, 18) == 4


@pytest.mark.parametrize(
    ("index", "expected"),
    [
        (30, "much_lighter"),
        (43, "lighter"),
        (50, "typical"),
        (52, "typical"),
        (58, "heavier"),
        (70, "much_heavier"),
    ],
)
def test_every_band_is_reachable(index: int, expected: str) -> None:
    baseline = build_baseline(weekly(TUESDAY, 15, [50, 50, 50, 50]))

    comparison = compare_to_typical(index, utc(TUESDAY, 15), baseline)

    assert comparison.typical == 50.0
    assert comparison.band == expected


def test_small_baseline_needs_an_absolute_gap_before_leaving_typical() -> None:
    """At 04:00 a typical of 4 makes an index of 6 'half again as heavy' — and still empty roads."""
    baseline = build_baseline(weekly(TUESDAY, 1, [4, 4, 4]))

    comparison = compare_to_typical(6, utc(TUESDAY, 1), baseline)

    assert comparison.ratio == 1.5
    assert comparison.band == "typical"


def test_coverage_is_the_filled_fraction_of_168_cells() -> None:
    points = weekly(TUESDAY, 6, [50, 52, 54]) + weekly(TUESDAY, 7, [60, 62, 64]) + weekly(TUESDAY, 8, [70, 72])

    baseline = build_baseline(points)

    assert CELLS_PER_WEEK == 168
    assert len(baseline.cells) == 2, "the two-sample cell is not reportable"
    assert len(baseline.counts) == 3, "but it is still counted"
    assert baseline.coverage() == pytest.approx(2 / 168)
    assert build_baseline([]).coverage() == 0.0


def test_empty_input_produces_an_empty_baseline_and_an_unknown_comparison() -> None:
    baseline = build_baseline([])

    assert baseline.cells == {}
    assert baseline.counts == {}
    assert baseline.days_covered == 0
    assert baseline.sample_count == 0

    comparison = compare_to_typical(55, utc(TUESDAY, 15), baseline)

    assert comparison.band == "unknown"
    assert comparison.typical is None
    assert comparison.index == 55
    assert comparison.description_tr.strip() != ""
    assert comparison.description_en.strip() != ""


def test_unusable_points_are_skipped_not_bucketed() -> None:
    """A missing timestamp cannot be filed under an hour; a 0 index is an absence, not a quiet city."""
    points = [
        *weekly(TUESDAY, 15, [50, 52, 54]),
        TrafficIndexPoint(index=55, at=None),
        point(utc(TUESDAY, 15, minute=5), 0),
    ]

    baseline = build_baseline(points)

    assert baseline.sample_count == 3
    assert baseline.typical(TUESDAY_IDX, 18) == 52.0


def test_descriptions_carry_the_numbers_behind_the_verdict() -> None:
    baseline = build_baseline(weekly(TUESDAY, 15, [50, 50, 50, 50]))

    comparison = compare_to_typical(72, utc(TUESDAY, 15), baseline)

    tr, en = comparison.description_tr, comparison.description_en
    assert tr.strip() and en.strip()
    # The reading, the baseline it is measured against, and the sample count behind that baseline.
    assert "72" in tr and "72" in en
    assert "50,0" in tr and "50.0" in en
    assert "4 gözlem" in tr and "4 samples" in en
    assert "+22,0" in tr and "+22.0" in en
    assert "Salı" in tr and "Tuesday" in en, "Turkish dotted İ/ı must survive intact"
    assert "olağandan belirgin biçimde yoğun" in tr
    assert "much heavier than usual" in en


def test_unknown_descriptions_state_the_reading_and_the_shortfall() -> None:
    baseline = build_baseline(weekly(TUESDAY, 15, [50, 50]))

    comparison = compare_to_typical(72, utc(TUESDAY, 15), baseline)

    assert "72" in comparison.description_tr and "72" in comparison.description_en
    assert "Salı 18:00" in comparison.description_tr
    assert "Tuesday at 18:00" in comparison.description_en
    assert "söyleyemeyiz" in comparison.description_tr


def test_hand_built_baseline_with_a_non_index_median_is_refused() -> None:
    """build_baseline never stores one, but a caller could; a ratio against 0 is not a verdict."""
    baseline = TrafficBaseline(
        cells={(TUESDAY_IDX, 18): 0.0},
        counts={(TUESDAY_IDX, 18): 5},
        days_covered=5,
        sample_count=5,
    )

    comparison = compare_to_typical(60, utc(TUESDAY, 15), baseline)

    assert comparison.band == "unknown"
    assert comparison.ratio is None
    assert "geçerli bir indeks değil" in comparison.description_tr
    assert "not a valid index" in comparison.description_en


def test_weekday_indices_follow_datetime_convention() -> None:
    """0 = Monday, so a Monday reading lands in row 0 — the same convention WEEKDAY_TR uses."""
    monday = TUESDAY - dt.timedelta(days=1)
    baseline = build_baseline(weekly(monday, 6, [30, 32, 34]))

    assert baseline.typical(MONDAY, 9) == 32.0
    assert "Pazartesi 09:00" in compare_to_typical(32, utc(monday, 6), baseline).description_tr


def test_points_at_or_after_the_cutoff_do_not_vote() -> None:
    """The reading being judged must not sit inside its own baseline."""
    history = weekly(TUESDAY, 15, [40, 40, 40])
    judged = point(utc(TUESDAY + dt.timedelta(weeks=1), 15), 90)

    with_it = build_baseline([*history, judged])
    without_it = build_baseline([*history, judged], before=utc(TUESDAY + dt.timedelta(weeks=1), 14))

    assert with_it.samples_at(TUESDAY_IDX, 18) == 4
    assert without_it.samples_at(TUESDAY_IDX, 18) == 3
    assert without_it.typical(TUESDAY_IDX, 18) == 40.0
    assert compare_to_typical(90, judged.at, without_it).band == "much_heavier"


# --------------------------------------------------------------------------------------
# the tool layer: one history read, reused, and honest when it is thin or missing
# --------------------------------------------------------------------------------------
@pytest.fixture
def nabiz(sealed: list[str], tmp_path: pathlib.Path) -> Nabiz:  # noqa: F811 - the imported fixture, requested by name
    return sealed_nabiz(tmp_path)


async def test_traffic_now_says_there_is_no_norm_yet_on_one_day_of_history(
    nabiz: Nabiz, sealed: list[str]  # noqa: F811 - the imported fixture, requested by name
) -> None:
    result = await nabiz.traffic_index("now")
    typical = result.data["typical"]

    assert result.data["index"] == 60  # the recorded fixture's newest point
    assert typical["available"] is False
    assert typical["band"] == "unknown" and typical["typical_index"] is None
    assert typical["samples"] == 0
    assert "en az 3 gerekiyor" in typical["description"]
    assert sealed == []


async def test_the_usual_level_cites_the_history_read_it_came_from(nabiz: Nabiz) -> None:
    """typical_index and delta come from TrafficIndexHistory/28/H, not from the live 1/H read
    the envelope cites, so they carry their own source and age."""
    result = await nabiz.traffic_index("now")
    stamp = result.data["typical"]["provenance"]

    assert stamp["source"] == "traffic"
    assert stamp["source_url"].endswith("/28/H")
    assert stamp["observed_at"] and isinstance(stamp["age_seconds"], float)
    assert not result.provenance.source_url.endswith("/28/H")


async def test_the_baseline_is_read_once_and_reused(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, str]] = []
    real = TrafficSource.index_history

    async def counting(self: TrafficSource, days: int = 1, period: str = "H") -> Any:
        calls.append((days, period))
        return await real(self, days=days, period=period)

    monkeypatch.setattr(TrafficSource, "index_history", counting)
    first = await nabiz.traffic_baseline()
    second = await nabiz.traffic_baseline()
    await nabiz.traffic_index("now")

    assert first is second
    assert calls.count((28, "H")) == 1


async def test_an_unreadable_history_is_said_and_not_retried_at_once(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []
    real = TrafficSource.index_history

    async def failing_history(self: TrafficSource, days: int = 1, period: str = "H") -> Any:
        if days == 28:
            attempts.append(days)
            raise UpstreamUnavailable("trafik geçmişi yanıt vermedi", source="traffic")
        return await real(self, days=days, period=period)

    monkeypatch.setattr(TrafficSource, "index_history", failing_history)
    result = await nabiz.traffic_index("now")
    await nabiz.traffic_index("now")

    assert result.data["index"] == 60, "a missing baseline must not cost the live reading"
    assert result.data["typical"] == {
        "available": False,
        "description": "İBB trafik geçmişi okunamadı; bu saatin olağan seviyesiyle karşılaştırma yapılamadı.",
    }
    assert attempts == [28]


async def test_a_measured_norm_reaches_the_tool_with_its_numbers(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    """Four earlier Tuesdays at 09:00 read 40; the recorded Tuesday 09:00 reading is 60."""
    fixture_now = dt.datetime(2026, 9, 8, 6, 0, tzinfo=dt.UTC)  # 09:00 İstanbul, the fixture's newest point
    history = [point(fixture_now - dt.timedelta(weeks=weeks), 40) for weeks in (1, 2, 3, 4)]
    real = TrafficSource.index_history

    async def four_weeks(self: TrafficSource, days: int = 1, period: str = "H") -> Any:
        points, provenance = await real(self, days=1, period="H")
        return (history + points if days == 28 else points), provenance

    monkeypatch.setattr(TrafficSource, "index_history", four_weeks)
    typical = (await nabiz.traffic_index("now")).data["typical"]

    assert typical["available"] is True
    assert typical["typical_index"] == 40.0
    assert typical["delta"] == 20.0
    assert typical["band"] == "much_heavier"
    assert typical["samples"] == 4
    assert "Salı 09:00" in typical["description"]


async def test_plan_journey_carries_the_comparison_as_a_reading(nabiz: Nabiz, sealed: list[str]) -> None:  # noqa: F811
    """Through the façade, sealed: the reading is there, and it says the norm is unknown."""
    journey = await nabiz.plan_journey(origin="Taksim", destination="Kadıköy")
    reading = next(r for r in journey.data["readings"] if r["key"] == "traffic_typical")

    assert reading["value"] == "bilinmiyor"
    assert "en az 3 gerekiyor" in reading["detail"]
    assert sealed == []
