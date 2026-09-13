"""Tests for the calibrated seconds-per-stop profile.

Two things are worth testing hard here, because both fail *silently* in production:

* the **fallback chain**. A wrong rate does not raise; it produces a plausible minute that
  is quietly 10 minutes out. Every step of line+bucket -> line -> global -> default is
  pinned, including what each step reports as its provenance, because the tool result
  repeats that string to the user.
* the **bucket boundaries**, especially the night wrap. 'night' is 21:00-05:59 across
  midnight, which is exactly the shape of range check people get wrong, and getting it
  wrong silently swaps a rush-hour rate for a free-road one.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from ibb_mcp.eta_profile import (
    DEFAULT_SECONDS_PER_STOP,
    MAX_SECONDS_PER_STOP,
    MIN_SAMPLES,
    MIN_SECONDS_PER_STOP,
    Cell,
    EtaProfile,
    LineSpeedProfile,
    bucket_for,
    cell_key,
    default_profile,
    load_profile,
    profile_path,
    save_profile,
)
from ibb_mcp.models import ISTANBUL_TZ


def at(hour: int, minute: int = 0) -> dt.datetime:
    """An Istanbul-local moment on the day the profile was calibrated."""
    return dt.datetime(2026, 9, 13, hour, minute, tzinfo=ISTANBUL_TZ)


def sample_profile() -> EtaProfile:
    return EtaProfile(
        cells={"500T|midday": Cell(250.0, 342), "500T|evening": Cell(385.0, 60)},
        lines={"500T": Cell(230.0, 503)},
        overall=Cell(230.0, 503),
    )


# -- buckets ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (5, "night"),
        (6, "morning"),  # first minute of morning
        (9, "morning"),
        (10, "midday"),  # morning ends at 10, exclusive
        (15, "midday"),
        (16, "evening"),
        (20, "evening"),
        (21, "night"),  # evening ends at 21, exclusive
        (23, "night"),
        (0, "night"),  # the wrap: midnight is still night, not "before morning"
        (3, "night"),
    ],
)
def test_bucket_boundaries(hour: int, expected: str) -> None:
    assert bucket_for(at(hour)) == expected
    assert bucket_for(at(hour, 59)) == expected


def test_naive_datetime_is_read_as_istanbul_local() -> None:
    """A server running UTC must not bucket 22:00 Istanbul as evening."""
    naive = dt.datetime(2026, 9, 13, 22, 0)
    assert bucket_for(naive) == "night"


def test_utc_datetime_is_converted_before_bucketing() -> None:
    """18:00 UTC is 21:00 in Istanbul — night, not evening."""
    assert bucket_for(dt.datetime(2026, 9, 13, 18, 0, tzinfo=dt.UTC)) == "night"
    assert bucket_for(dt.datetime(2026, 9, 13, 7, 30, tzinfo=dt.UTC)) == "midday"


def test_bucket_for_defaults_to_now() -> None:
    from ibb_mcp.eta_profile import BUCKETS

    assert bucket_for() in BUCKETS


# -- the fallback chain -------------------------------------------------------------


def test_chain_prefers_the_line_and_bucket_cell() -> None:
    seconds, provenance = sample_profile().seconds_per_stop_for("500T", at(13))
    assert seconds == 250.0
    assert provenance == "line+bucket, n=342"


def test_chain_falls_back_to_the_line_when_the_bucket_has_no_cell() -> None:
    """No morning data has been collected, so 08:00 must borrow the line's pooled rate."""
    seconds, provenance = sample_profile().seconds_per_stop_for("500T", at(8))
    assert bucket_for(at(8)) == "morning"
    assert (seconds, provenance) == (230.0, "line, n=503")


def test_chain_falls_back_to_global_for_an_unmeasured_line() -> None:
    seconds, provenance = sample_profile().seconds_per_stop_for("34AS", at(13))
    assert (seconds, provenance) == (230.0, "global, n=503")


def test_chain_falls_back_to_the_untuned_default_when_nothing_is_calibrated() -> None:
    seconds, provenance = default_profile().seconds_per_stop_for("500T", at(13))
    assert (seconds, provenance) == (DEFAULT_SECONDS_PER_STOP, "default")
    assert default_profile().is_calibrated is False


def test_line_codes_are_matched_case_and_whitespace_insensitively() -> None:
    """İETT writes the same line as '500T', ' 500t ' and '500t' in different payloads."""
    assert sample_profile().seconds_per_stop_for(" 500t ", at(13))[0] == 250.0
    assert cell_key(" 500t ", "midday") == "500T|midday"


def test_missing_line_code_still_answers() -> None:
    """BusPosition.line_code is optional; the chain must degrade, not raise."""
    seconds, provenance = sample_profile().seconds_per_stop_for(None, at(13))
    assert (seconds, provenance) == (230.0, "global, n=503")


# -- refusing thin cells ------------------------------------------------------------


def test_from_cells_refuses_a_cell_below_min_samples() -> None:
    profile = EtaProfile.from_cells(
        cells={"500T|midday": Cell(250.0, 342), "500T|morning": Cell(600.0, 3)},
        lines={"500T": Cell(230.0, 345)},
        overall=Cell(230.0, 345),
        min_samples=MIN_SAMPLES,
    )
    assert "500T|morning" not in profile.cells
    assert profile.refused == {"500T|morning": 3}
    # and the refused cell's hour falls through to the line rate rather than vanishing
    assert profile.seconds_per_stop_for("500T", at(8)) == (230.0, "line, n=345")


def test_from_cells_keeps_a_cell_exactly_at_min_samples() -> None:
    profile = EtaProfile.from_cells(
        cells={"500T|night": Cell(160.0, MIN_SAMPLES)},
        lines={},
        overall=None,
        min_samples=MIN_SAMPLES,
    )
    assert profile.cells["500T|night"].samples == MIN_SAMPLES
    assert profile.refused == {}


def test_from_cells_refuses_a_thin_global_too() -> None:
    profile = EtaProfile.from_cells(cells={}, lines={}, overall=Cell(400.0, 4), min_samples=MIN_SAMPLES)
    assert profile.overall is None
    assert profile.refused == {"global": 4}
    assert profile.seconds_per_stop_for("500T", at(13)) == (DEFAULT_SECONDS_PER_STOP, "default")


# -- persistence --------------------------------------------------------------------


def test_save_load_round_trip(tmp_path) -> None:
    original = EtaProfile.from_cells(
        cells={"500T|midday": Cell(250.0, 342, mae_minutes=11.52, baseline_mae_minutes=18.2)},
        lines={"500T": Cell(230.0, 503)},
        overall=Cell(230.0, 503),
        generated_at="2026-09-13T15:00:23+00:00",
        note="fitted in a test",
    )
    path = save_profile(original, path=tmp_path / "nested" / "eta_profile.json")
    reloaded = load_profile(path=path)

    assert reloaded.cells["500T|midday"].seconds_per_stop == 250.0
    assert reloaded.cells["500T|midday"].samples == 342
    assert reloaded.cells["500T|midday"].mae_minutes == 11.52
    assert reloaded.lines["500T"].seconds_per_stop == 230.0
    assert reloaded.overall is not None and reloaded.overall.samples == 503
    assert reloaded.generated_at == "2026-09-13T15:00:23+00:00"
    assert reloaded.min_samples == MIN_SAMPLES
    assert reloaded.note == "fitted in a test"
    assert reloaded.seconds_per_stop_for("500T", at(13)) == original.seconds_per_stop_for("500T", at(13))


def test_constant_seconds_defaults_to_zero_and_round_trips(tmp_path) -> None:
    """The constant is a human decision, never a calibrated one — it must not drift in."""
    assert default_profile().constant_seconds == 0.0
    path = save_profile(sample_profile(), path=tmp_path / "p.json")
    assert json.loads(path.read_text(encoding="utf-8"))["constant_seconds"] == 0.0
    assert load_profile(path=path).constant_seconds == 0.0


def test_load_with_a_missing_file_returns_the_default_and_says_so_loudly(tmp_path) -> None:
    missing = tmp_path / "absent.json"
    profile = load_profile(path=missing)
    assert profile.is_calibrated is False
    assert profile.seconds_per_stop_for("500T", at(13)) == (DEFAULT_SECONDS_PER_STOP, "default")
    assert profile.note is not None
    assert "absent.json" in profile.note  # the note names the path it wanted


def test_load_with_unreadable_content_falls_back_instead_of_raising(tmp_path) -> None:
    """A half-written profile must not take arrival estimates down with it."""
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    profile = load_profile(path=broken)
    assert profile.is_calibrated is False
    assert profile.note is not None and "unreadable" in profile.note

    wrong_shape = tmp_path / "list.json"
    wrong_shape.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_profile(path=wrong_shape).is_calibrated is False


def test_profile_path_prefers_settings_then_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NABIZ_ETA_PROFILE", str(tmp_path / "from_env.json"))
    assert profile_path(None).name == "from_env.json"

    class FakeSettings:
        eta_profile_path = tmp_path / "from_settings.json"

    assert profile_path(FakeSettings()).name == "from_settings.json"

    monkeypatch.delenv("NABIZ_ETA_PROFILE")
    assert profile_path(None).name == "eta_profile.json"


def test_the_committed_profile_is_sane_if_present() -> None:
    """Guard the artefact itself: a garbage rate in the repo is worse than no profile."""
    path = profile_path(None)
    if not path.exists():  # pragma: no cover - a fresh checkout before the first calibration
        pytest.skip("no calibrated profile in this checkout")
    profile = load_profile(path=path)
    assert profile.is_calibrated
    assert profile.constant_seconds == 0.0
    for key, cell in {**profile.cells, **profile.lines}.items():
        assert cell.samples >= profile.min_samples, key
        assert MIN_SECONDS_PER_STOP <= cell.seconds_per_stop <= MAX_SECONDS_PER_STOP, key


# -- the shape the engine consumes --------------------------------------------------


def test_speed_profile_resolves_every_route_variant_of_the_line() -> None:
    """``estimate_arrivals`` keys by route_code; a line's variants all share its rate."""
    mapping = sample_profile().as_speed_profile("500T", at(13))
    assert isinstance(mapping, LineSpeedProfile)
    assert bool(mapping) is True  # eta._Ctx skips a falsy profile
    assert mapping.get("500T_G_D0") == 250.0
    assert mapping.get("500T_D_D0") == 250.0
    assert mapping["anything"] == 250.0
    assert mapping.provenance == "line+bucket, n=342"


def test_engine_uses_the_calibrated_rate() -> None:
    """End-to-end through the estimator: three stops away at 250 s/stop is 12.5 minutes."""
    from ibb_mcp.eta import estimate_arrivals
    from ibb_mcp.models import BusPosition, Stop

    class FakeSequence:
        stop_codes = ("100", "200", "300", "400")

    now = at(13)
    bus = BusPosition(door_no="C-479", line_code="500T", route_code="500T_G_D0", nearest_stop_code="100",
                      reported_at=now)
    target = Stop(stop_code="400", name="4.LEVENT METRO")

    arrivals, _ = estimate_arrivals(
        buses=[bus],
        target=target,
        sequences={"500T_G_D0": FakeSequence()},
        speed_profile=sample_profile().as_speed_profile("500T", now),
        now=now,
    )
    assert len(arrivals) == 1
    assert arrivals[0].stops_away == 3
    assert arrivals[0].eta_minutes == pytest.approx(3 * 250 / 60.0, abs=0.05)

    # ...and without a profile the engine still answers with its untuned default.
    plain, _ = estimate_arrivals(
        buses=[bus], target=target, sequences={"500T_G_D0": FakeSequence()}, now=now
    )
    assert plain[0].eta_minutes == pytest.approx(3 * DEFAULT_SECONDS_PER_STOP / 60.0, abs=0.05)
