from __future__ import annotations

import datetime as dt
import pathlib
import re

import pytest

from ibb_mcp.eta import estimate_arrivals
from ibb_mcp.eta_profile import (
    HIGH_WITHIN_5_MIN_SHARE,
    MEASURED_ERROR,
    MEDIUM_WITHIN_5_MIN_SHARE,
    MIN_MEASURED_SAMPLES,
    confidence_ceiling,
)
from ibb_mcp.models import ISTANBUL_TZ, BusPosition, Stop


def test_the_bands_match_the_committed_report() -> None:
    report = pathlib.Path(__file__).parents[1] / "eval/results/eta.md"
    rows = re.findall(r"\| `([^`]+)` \| (\d+) \| ([\d.]+) \| [\d.]+% \| ([\d.]+)% \|", report.read_text())
    measured = {method: (int(samples), float(mae), float(within_5) / 100) for method, samples, mae, within_5 in rows}

    assert set(measured) == set(MEASURED_ERROR)
    for method, (samples, mae, within_5) in measured.items():
        record = MEASURED_ERROR[method]
        assert record.samples == samples
        assert record.mae_minutes == mae
        assert record.within_5_min_share == pytest.approx(within_5)
        expected = (
            "low" if samples < MIN_MEASURED_SAMPLES
            else "high" if within_5 >= HIGH_WITHIN_5_MIN_SHARE
            else "medium" if within_5 >= MEDIUM_WITHIN_5_MIN_SHARE
            else "low"
        )
        assert confidence_ceiling(method) == expected


def test_no_estimate_exceeds_the_measured_ceiling() -> None:
    class FakeSequence:
        stop_codes = ("A", "B", "C", "D")

    now = dt.datetime(2026, 9, 24, 14, 30, tzinfo=ISTANBUL_TZ)
    bus = BusPosition(
        door_no="C-479", line_code="500T", route_code="500T_G_D0", nearest_stop_code="C", reported_at=now
    )
    arrivals, _ = estimate_arrivals(
        buses=[bus], target=Stop(stop_code="D", name="Target"),
        sequences={"500T_G_D0": FakeSequence()}, now=now,
    )

    assert arrivals[0].confidence == confidence_ceiling("stop_sequence")


def test_an_unmeasured_method_is_low() -> None:
    assert confidence_ceiling("schedule") == "low"
    assert confidence_ceiling("not_measured") == "low"
