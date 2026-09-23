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


def test_a_pooled_rate_names_the_lines_it_was_measured_on() -> None:
    """The committed profile pools 500T alone; "measured across all lines" would be false."""
    assert sample_profile().pooled_lines == ("500T",)
    assert sample_profile().pooled_rate_qualifier() == "yalnızca 500T hattında ölçülen"
    # A line refused its own cell still fed the pool; bucket cells and the global are not lines.
    wider = EtaProfile(
        lines={"500T": Cell(230.0, 503)},
        overall=Cell(228.0, 540),
        refused={"22": 12, "22|night": 4, "34AS|midday": 3, "global": 0},
    )
    assert wider.pooled_lines == ("22", "500T")
    assert wider.pooled_rate_qualifier() == "ölçülen 2 hattan (22, 500T) havuzlanan"


def test_the_tool_sentence_for_a_pooled_rate_never_claims_every_line() -> None:
    from ibb_mcp.eta_profile import RateChoice

    profile = sample_profile()
    seconds, provenance = profile.seconds_per_stop_for("22", at(13))
    sentence = RateChoice(seconds, provenance, "calibrated", "test", profile.pooled_rate_qualifier()).sentence_tr()
    assert "500T" in sentence and "tüm hatlar" not in sentence
    assert sentence.endswith("(global, n=503).")


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
        cells={"500T|midday": Cell(250.0, 342, mae_minutes=11.52, baseline_mae_minutes=18.2, max_stops_away=25)},
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
    assert reloaded.cells["500T|midday"].max_stops_away == 25
    # an older file without the field must still load rather than raising
    assert reloaded.lines["500T"].max_stops_away is None
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


# -- what the tools serve (DECISIONS #18) ---------------------------------------------
#
# Held out, the calibrated profile scored 35.82 min MAE against 10.18 for the untuned
# 120 s/stop (eval/results/eta.md). The tools therefore serve the untuned default, and the
# profile only when an operator asks for it.


@pytest.fixture
def written_profile(tmp_path, monkeypatch):
    """The sample profile on disk, where ``profile_path`` looks (``NABIZ_ETA_PROFILE``)."""
    path = tmp_path / "eta_profile.json"
    save_profile(sample_profile(), path=path)
    monkeypatch.setenv("NABIZ_ETA_PROFILE", str(path))
    return path


def mode_settings(mode: str):
    """Offline test settings with ``eta_profile_mode`` set."""
    import dataclasses

    from conftest import offline_settings

    return dataclasses.replace(offline_settings(), eta_profile_mode=mode)


def test_the_default_mode_serves_the_untuned_rate_without_reading_the_profile(written_profile, monkeypatch) -> None:
    from ibb_mcp import eta_profile

    def refuse(*args, **kwargs):
        raise AssertionError("the default mode must not read the profile")

    monkeypatch.setattr(eta_profile, "load_profile", refuse)
    choice = eta_profile.served_rate("500T", at(13), mode_settings("default"))
    assert (choice.seconds_per_stop, choice.source, choice.mode) == (DEFAULT_SECONDS_PER_STOP, "default", "default")
    assert "35.82" in choice.reason and "10.18" in choice.reason and "eval/results/eta.md" in choice.reason
    assert choice.as_speed_profile() is None, "the engine keeps its own default"


def test_settings_default_to_the_untuned_rate(monkeypatch) -> None:
    from ibb_mcp.config import Settings

    monkeypatch.delenv("NABIZ_ETA_PROFILE_MODE", raising=False)
    assert Settings().eta_profile_mode == "default"
    assert Settings.from_env().eta_profile_mode == "default"
    monkeypatch.setenv("NABIZ_ETA_PROFILE_MODE", "calibrated")
    assert Settings.from_env().eta_profile_mode == "calibrated"


def test_the_calibrated_mode_is_an_explicit_opt_in(written_profile) -> None:
    from ibb_mcp.eta_profile import served_rate

    choice = served_rate("500T", at(13), mode_settings("calibrated"))
    assert (choice.seconds_per_stop, choice.source, choice.mode) == (250.0, "line+bucket, n=342", "calibrated")
    assert "NABIZ_ETA_PROFILE_MODE=calibrated" in choice.reason
    speed = choice.as_speed_profile()
    assert speed is not None and speed.get("500T_G_D0") == 250.0


def test_a_calibrated_mode_without_a_profile_says_so_without_a_path(tmp_path, monkeypatch) -> None:
    from ibb_mcp.eta_profile import served_rate

    monkeypatch.setenv("NABIZ_ETA_PROFILE", str(tmp_path / "missing.json"))
    choice = served_rate("500T", at(13), mode_settings("calibrated"))
    assert (choice.seconds_per_stop, choice.source, choice.mode) == (DEFAULT_SECONDS_PER_STOP, "default", "calibrated")
    assert "missing or unreadable" in choice.reason
    assert str(tmp_path) not in choice.reason, "a local path would name this machine's user"


@pytest.mark.parametrize("raw", ["Calibrated", "calibrated ", "CALIBRATED"])
def test_the_mode_is_read_case_and_space_insensitively(written_profile, raw: str) -> None:
    from ibb_mcp.eta_profile import served_rate

    assert served_rate("500T", at(13), mode_settings(raw)).mode == "calibrated"


def test_an_unknown_mode_serves_the_default_and_names_the_typo(written_profile) -> None:
    from ibb_mcp.eta_profile import served_rate

    choice = served_rate("500T", at(13), mode_settings("calibrate"))
    assert (choice.seconds_per_stop, choice.mode) == (DEFAULT_SECONDS_PER_STOP, "default")
    assert "'calibrate'" in choice.reason and "35.82" in choice.reason


def test_the_default_disclaimer_says_the_measurement_is_withheld_not_missing() -> None:
    from ibb_mcp.eta_profile import DEFAULT_RATE_SENTENCE_TR, RateChoice

    withheld = RateChoice(DEFAULT_SECONDS_PER_STOP, "default", "default", "test").sentence_tr()
    assert withheld == DEFAULT_RATE_SENTENCE_TR
    assert "ölçüm yok" not in withheld, "500T was measured; the rate is withheld, not absent"
    assert "kalibre edilmemiş" in withheld
    missing = RateChoice(DEFAULT_SECONDS_PER_STOP, "default", "calibrated", "test").sentence_tr()
    assert "henüz ölçüm yok" in missing, "in the calibrated mode, a line with no cell really has no measurement"


def test_a_profile_of_the_wrong_shape_falls_back_instead_of_failing_the_estimate(tmp_path) -> None:
    wrong = tmp_path / "eta_profile.json"
    wrong.write_text(json.dumps({"cells": [1, 2], "lines": {}}), encoding="utf-8")
    profile = load_profile(path=wrong)
    assert profile.is_calibrated is False and "malformed" in (profile.note or "")


def test_the_journey_bus_leg_makes_the_same_choice(written_profile) -> None:
    from ibb_mcp.routing import DEFAULT_PARAMS, DEFAULT_RATE_DETAIL, MEASURED_RATE_CAVEAT, seconds_per_stop_for

    assert seconds_per_stop_for("500T", at(13), mode_settings("default")) == (
        DEFAULT_PARAMS.bus_seconds_per_stop,
        DEFAULT_RATE_DETAIL,
    )
    seconds, detail = seconds_per_stop_for("500T", at(13), mode_settings("calibrated"))
    assert seconds == 250.0 and "line+bucket, n=342" in detail and MEASURED_RATE_CAVEAT in detail


async def test_the_arrival_tool_reports_which_rate_it_used_and_why(ctx, written_profile) -> None:
    """Through the tool: the diagnostics carry the mode, the rung, the rate and the reason."""
    import dataclasses

    from ibb_mcp.eta_profile import DEFAULT_RATE_SENTENCE_TR
    from ibb_mcp.tools import Nabiz

    served = await Nabiz(ctx).iett_next_arrivals(line_code="500T", stop="220641", limit=3)
    diagnostics = served.data["diagnostics"]
    assert (diagnostics["rate_mode"], diagnostics["rate_source"], diagnostics["seconds_per_stop"]) == (
        "default",
        "default",
        DEFAULT_SECONDS_PER_STOP,
    )
    assert "35.82" in diagnostics["rate_reason"]
    assert served.data["disclaimer"].endswith(DEFAULT_RATE_SENTENCE_TR)

    research = dataclasses.replace(ctx, settings=mode_settings("calibrated"))
    opted_in = await Nabiz(research).iett_next_arrivals(line_code="500T", stop="220641", limit=3)
    assert opted_in.data["diagnostics"]["rate_mode"] == "calibrated"
    assert opted_in.data["diagnostics"]["rate_source"].startswith(("line+bucket", "line,"))
    assert "ölçülmüş veriden" in opted_in.data["disclaimer"]


def test_the_default_the_diagnostics_report_is_the_engines_own() -> None:
    """In the default mode the engine runs on ``EtaParams.seconds_per_stop``; the diagnostics
    report ``DEFAULT_SECONDS_PER_STOP``. Two constants, so they are pinned equal here."""
    from ibb_mcp.eta import EtaParams

    assert EtaParams().seconds_per_stop == DEFAULT_SECONDS_PER_STOP
