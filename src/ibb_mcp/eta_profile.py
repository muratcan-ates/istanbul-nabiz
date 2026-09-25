"""Measured seconds-per-stop for the arrival estimator, per line and time of day.

``eta.py`` turns "the bus is N stops away" into minutes by multiplying N by a
seconds-per-stop rate. Until now that rate was one hand-picked constant (120 s/stop,
PLAN.md section 7) applied to every line at every hour. Measured against the 500 resolved
stop-sequence predictions in the lake on 2026-09-13 it was wrong in a specific, correctable
direction: **MAE 16.8 minutes with a bias of -16.6 minutes** — we told riders the bus was
coming far earlier than it did. (The -11.7 quoted in the commit that added this module was
over all resolved predictions, the distance method included, and is not re-derived here;
this module can only move the stop-sequence ones, so that is the population it is measured
against.) A single re-fitted rate,
235 s/stop, cuts the MAE to 12.4, and the per-bucket rates here cut it to 11.2 — both
**in-sample**: fitted and scored on the same 500 rows, so they describe the fit, not the
accuracy a rider will see. The held-out figure is the next-but-one paragraph's. This module
holds the fitted rates and the rule for choosing one.

**Why a rate and not a rate plus a constant.** The best-fitting straight line through the
data wants an 11.5-minute constant on top of 150 s/stop (MAE 10.2). Part of that constant
is real (dwell time, the run-up before the first stop boundary) and part of it is the
measurement itself: arrivals are observed on a 3-minute collector tick and
``yakinDurakKodu`` is *nearest* stop rather than a stop event, which is worth roughly half
a tick. A number that big cannot be told apart from an artefact with one day of data, and
baking it in would make every short-hop ETA (1-2 stops away) absurdly pessimistic. So the
constant is kept as a separate, clearly named field that **defaults to zero** and is never
written by the calibration script; only the rate is calibrated.

**Why four coarse buckets rather than per-hour.** Held out one clock hour at a time —
train on every other hour, predict the hour never seen — the four-bucket profile scores
MAE 11.70 against 12.92 for both a per-hour profile and a single per-line rate. A per-hour
cell cannot help an hour it has no rows for, and with one day of collection every hour has
exactly one sample of itself, so a per-hour fit is indistinguishable from fitting that
afternoon's traffic. (A plain random 5-fold split *flatters* per-hour cells — 10.9 against
11.3 — because two predictions made in the same hour about the same buses are not
independent draws. That split is the wrong test.) Coarse buckets let neighbouring hours
inform each other, which is what makes 06:00-10:00 answerable at all: no morning data has
been collected yet.

**What the numbers are measured on.** ``scripts/calibrate_eta.py`` pairs predictions to
observed arrivals exactly as ``eta_report.score`` does, and additionally discards anything
predicted in the final 90 minutes of collection: those rows are right-censored — only the
journeys fast enough to have already finished are visible. Cut at the moment the committed
profile was built, keeping them would have fitted the evening rate on 101 rows instead of 57
and pulled it from 445 to 75 s/stop.

Re-derived on 2026-09-23 from the lake, read-only and cut at the committed profile's
``generated_at``: 500 resolved rows; MAE 16.83 and bias -16.58 at 120 s/stop; 12.37 at
235 s/stop; 11.16 with the bucket rates; 11.70 against 12.92 held out one clock hour at a
time; the constant-plus-rate fit at 11.5 min + 150 s/stop, MAE 10.19. The random 5-fold
figures (10.9 / 11.3) were not re-run.

The fallback chain is line+bucket -> line -> global -> the built-in 120 s/stop default, and
:meth:`EtaProfile.seconds_per_stop_for` returns **which** of those produced the number, so
a tool result can say where its rate came from instead of presenting a fitted number and a
hard-coded one as if they were the same thing.

**What the tools serve (DECISIONS #18).** Held out, the fit does not transfer. Replayed on
the 523 stop-sequence predictions made after the profile was frozen, at stops it was never
fitted on, the calibrated rates scored a mean absolute error of 35.82 minutes against 10.18
for the untuned 120 s/stop (``eval/results/eta.md``, "Held-out replay"; the replay is
``scripts/eta_holdout.py``). Seconds per stop is a property of a stretch of road, and a rate
fitted at two stops says nothing about a third. So ``iett_next_arrivals`` and the bus leg of
``plan_journey`` serve the estimator with the better held-out score, the untuned default,
through :func:`served_rate`; the calibrated profile is used only when an operator sets
``NABIZ_ETA_PROFILE_MODE=calibrated``, for research, and the diagnostics say which rate was
used and why. This module and the committed profile stay, because the calibration is how
the next, better-evidenced fit will be made and judged.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
from dataclasses import dataclass, field
from typing import Any

from ibb_mcp.config import reference_path
from ibb_mcp.models import ISTANBUL_TZ
from ibb_mcp.reference import parse_once


@dataclass(frozen=True)
class MeasuredError:
    """Accuracy measured for one arrival method in the committed report."""

    method: str
    samples: int
    mae_minutes: float
    within_5_min_share: float
    measured_on: str
    report: str


MEASURED_ERROR = {
    "stop_sequence": MeasuredError(
        "stop_sequence", 1240, 12.74, 0.274, "2026-09-23", "eval/results/eta.md"
    ),
    "distance": MeasuredError(
        "distance", 111, 15.16, 0.261, "2026-09-23", "eval/results/eta.md"
    ),
}
HIGH_WITHIN_5_MIN_SHARE = 0.80
MEDIUM_WITHIN_5_MIN_SHARE = 0.50
MIN_MEASURED_SAMPLES = 100


def confidence_ceiling(method: str) -> str:
    """Cap confidence using measured five-minute accuracy, never extrapolation.

    High requires at least 80% of measured results within five minutes; medium requires
    at least 50%. The collector samples every three minutes, so even a perfect prediction
    can show about 1.5 minutes of mean absolute error from observation timing alone. The
    five-minute band leaves room for that measurement floor while still requiring a useful
    share of predictions to be close. Methods with fewer than 100 samples remain low.
    """
    measured = MEASURED_ERROR.get(method)
    if measured is None or measured.samples < MIN_MEASURED_SAMPLES:
        return "low"
    if measured.within_5_min_share >= HIGH_WITHIN_5_MIN_SHARE:
        return "high"
    if measured.within_5_min_share >= MEDIUM_WITHIN_5_MIN_SHARE:
        return "medium"
    return "low"


def confidence_basis_tr(method: str) -> str:
    """Short Turkish explanation tied to the measured method sample."""
    measured = MEASURED_ERROR.get(method)
    if measured is None:
        return "Bu yöntem için ölçüm yok; güven düzeyi düşük."
    mae = f"{measured.mae_minutes:.1f}".replace(".", ",")
    share = round(measured.within_5_min_share * 100)
    return (
        f"Bu yöntemin ölçülen hatası: n={measured.samples} tahminde ortalama {mae} dk, "
        f"%{share}'si 5 dk içinde ({measured.measured_on})"
    )

#: PLAN.md section 7's day-one guess. Still the answer when nothing has been measured.
DEFAULT_SECONDS_PER_STOP = 120.0

#: Rows a cell needs before its fitted rate is trusted. Chosen from 5-fold cross-validation
#: over the 2026-09-13 sample: out-of-sample MAE is flat between 10 and 40 (11.2-11.3 min)
#: and degrades above it (11.6 at 60, 12.3 at 80, as real cells start being thrown away).
#: 20 sits in the flat region with room to spare — enough that a cell cannot be carried by
#: a handful of predictions about one bus, small enough to keep the 57-row evening cell.
MIN_SAMPLES = 20

#: Rates outside this band are not believable for an İstanbul bus and almost certainly mean
#: the paired sample is junk rather than that the line is slow. The search range is
#: deliberately *wide*: an earlier ad-hoc scan capped at 90 s/stop, hit its own ceiling and
#: concluded no rate could beat the default — the exact opposite of what the data says.
MIN_SECONDS_PER_STOP = 30.0
MAX_SECONDS_PER_STOP = 600.0

PROFILE_FILENAME = "eta_profile.json"
SCHEMA_VERSION = 1

#: The two values of ``Settings.eta_profile_mode`` (``NABIZ_ETA_PROFILE_MODE``).
MODE_DEFAULT = "default"
MODE_CALIBRATED = "calibrated"
PROFILE_MODES: tuple[str, ...] = (MODE_DEFAULT, MODE_CALIBRATED)

#: Why the default mode serves the untuned rate. It reaches every client in the arrival
#: diagnostics, so it carries its numbers and the file they come from, and no path of this
#: machine's.
DEFAULT_MODE_REASON = (
    "untuned 120 s/stop, served by default: on 523 held-out predictions at stops the calibration "
    "never saw, the calibrated profile scored 35.82 min MAE against 10.18 min for 120 s/stop "
    "(eval/results/eta.md, DECISIONS #18)"
)
CALIBRATED_MODE_REASON = (
    "calibrated profile, requested with NABIZ_ETA_PROFILE_MODE=calibrated for research; held out it "
    "scored worse than the untuned default (eval/results/eta.md, DECISIONS #18)"
)
#: The Turkish rate sentence when the untuned default is served on purpose. Not "no
#: measurement yet": 500T has been measured, and the measurement did worse held out.
DEFAULT_RATE_SENTENCE_TR = (
    "Durak başına süre kalibre edilmemiş varsayılan orandır (120 sn); ölçülen oranlar, "
    "ölçülmedikleri duraklarda daha büyük hata verdiği için kullanılmıyor."
)

#: Half-open local-time bands, in order; anything they do not cover is 'night'.
_BUCKET_BANDS: tuple[tuple[int, int, str], ...] = (
    (6, 10, "morning"),
    (10, 16, "midday"),
    (16, 21, "evening"),
)
NIGHT = "night"
BUCKETS: tuple[str, ...] = ("morning", "midday", "evening", NIGHT)


def bucket_for(at: dt.datetime | None = None) -> str:
    """Which time-of-day bucket a moment falls in, by **İstanbul** local hour.

    A naive datetime is read as Istanbul local time — the same convention
    ``eta._as_aware`` and ``models.parse_ibb_datetime`` use — because the alternative is
    that an Azure container running UTC silently buckets 21:30 Istanbul traffic as evening
    rush and picks a rate three hours out of date.

    'night' is the wrap-around bucket (21:00-05:59), so it is defined as "none of the
    others" rather than as a range; a range would need two comparisons and would be the
    obvious place to get midnight wrong.
    """
    moment = at if at is not None else dt.datetime.now(ISTANBUL_TZ)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ISTANBUL_TZ)
    hour = moment.astimezone(ISTANBUL_TZ).hour
    for start, end, name in _BUCKET_BANDS:
        if start <= hour < end:
            return name
    return NIGHT


def cell_key(line_code: str, bucket: str) -> str:
    """Key for one (line, bucket) cell. Line codes are upper-cased: İETT writes '500t'."""
    return f"{(line_code or '').strip().upper()}|{bucket}"


def profile_path(settings: Any | None = None) -> pathlib.Path:
    """Where the calibrated profile lives.

    ``Settings`` has no field for this, so the path is resolved defensively: a
    ``settings.eta_profile_path`` if a caller's settings object carries one, else
    ``NABIZ_ETA_PROFILE``, else ``data/reference/`` through
    :func:`ibb_mcp.config.reference_path`. That last step matters in the container image:
    an installed package has no checkout beside it, and without the packaged copy the tool
    would silently fall back to the untuned rate.
    """
    configured = getattr(settings, "eta_profile_path", None)
    if configured:
        return pathlib.Path(configured)
    from_env = os.getenv("NABIZ_ETA_PROFILE")
    if from_env:
        return pathlib.Path(from_env)
    return reference_path(PROFILE_FILENAME)


@dataclass(frozen=True)
class Cell:
    """One fitted rate plus the evidence for it.

    ``samples`` travels with the rate everywhere, because "235 s/stop" and "235 s/stop
    from 500 paired arrivals" are different claims and only the second one is worth
    putting in front of a user.
    """

    seconds_per_stop: float
    samples: int
    mae_minutes: float | None = None
    baseline_mae_minutes: float | None = None
    #: The largest ``stops_away`` this cell was actually fitted on. A rate fitted entirely
    #: on 1-3 stop hops carries whatever dwell and measurement offset those short hops have
    #: baked into its slope; multiplying it by 20 stops extrapolates far past the evidence.
    #: Recorded so a consumer can tell that it is extrapolating instead of guessing.
    max_stops_away: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"seconds_per_stop": round(self.seconds_per_stop, 1), "samples": self.samples}
        if self.mae_minutes is not None:
            out["mae_minutes"] = round(self.mae_minutes, 2)
        if self.baseline_mae_minutes is not None:
            out["baseline_mae_minutes"] = round(self.baseline_mae_minutes, 2)
        if self.max_stops_away is not None:
            out["max_stops_away"] = self.max_stops_away
        return out

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Cell:
        max_stops = raw.get("max_stops_away")
        return cls(
            seconds_per_stop=float(raw["seconds_per_stop"]),
            samples=int(raw.get("samples", 0)),
            mae_minutes=_opt_float(raw.get("mae_minutes")),
            baseline_mae_minutes=_opt_float(raw.get("baseline_mae_minutes")),
            max_stops_away=None if max_stops is None else int(max_stops),
        )


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


class LineSpeedProfile(dict):
    """A ``speed_profile`` mapping for :func:`ibb_mcp.eta.estimate_arrivals`, for one line.

    ``estimate_arrivals`` keys ``speed_profile`` by **route_code** (a line has several
    route variants — 500T alone has both directions plus short workings), while a
    calibration cell is per **line**: splitting 500 samples across 2 876 route variants
    would leave every cell below :data:`MIN_SAMPLES`. Both call sites — the
    ``iett_next_arrivals`` tool and the collector — estimate one line per call, so every
    ``route_code`` the engine looks up inside a call belongs to the line this profile was
    built for, and they all share its rate. Hence the lookup ignores the key.

    It subclasses ``dict`` rather than implementing ``Mapping`` because ``eta._Ctx`` guards
    with ``if profile and ...``: an empty mapping is falsy and would be skipped silently.
    The one stored entry keeps it truthy and keeps ``repr`` honest in diagnostics.
    """

    def __init__(self, seconds_per_stop: float, provenance: str) -> None:
        super().__init__({"*": float(seconds_per_stop)})
        self.seconds_per_stop = float(seconds_per_stop)
        self.provenance = provenance

    def get(self, key: Any = None, default: Any = None) -> float:  # noqa: ARG002 - key is deliberately ignored
        return self.seconds_per_stop

    def __missing__(self, key: Any) -> float:
        return self.seconds_per_stop


@dataclass(frozen=True)
class EtaProfile:
    """Calibrated seconds-per-stop rates and the fallback chain that selects one."""

    cells: dict[str, Cell] = field(default_factory=dict)
    lines: dict[str, Cell] = field(default_factory=dict)
    overall: Cell | None = None
    #: Fitted separately, deliberately **not** calibrated, documented at module top.
    #: A non-zero value here is a decision a human made, not one this project measured.
    constant_seconds: float = 0.0
    default_seconds_per_stop: float = DEFAULT_SECONDS_PER_STOP
    min_samples: int = MIN_SAMPLES
    generated_at: str | None = None
    #: Cells the calibration refused to write, key -> how many rows it had. Kept in the
    #: file so the next person can see what was nearly there instead of re-deriving it.
    refused: dict[str, int] = field(default_factory=dict)
    source: str = "built-in default"
    note: str | None = None

    @property
    def is_calibrated(self) -> bool:
        return bool(self.cells or self.lines or self.overall)

    @property
    def calibrated_lines(self) -> tuple[str, ...]:
        return tuple(sorted(self.lines))

    @property
    def pooled_lines(self) -> tuple[str, ...]:
        """Every line whose rows fed the pooled ("global") rate.

        A line refused its own cell for having too few rows still contributed those rows to
        the pool, so the refused line keys count too; bucket cells (``LINE|bucket``) and the
        refused global are not lines.
        """
        refused_lines = {key for key in self.refused if "|" not in key and key != "global"}
        return tuple(sorted(set(self.lines) | refused_lines))

    def pooled_rate_qualifier(self) -> str:
        """Turkish words that go before "oran" to say which lines a pooled rate was measured on.

        The committed profile pools exactly one line, 500T, and the old wording, "tüm
        hatlardan ölçülen genel oran", told users of every other line that all lines had been
        measured. The agent repeats this text verbatim, so it names the lines instead.
        """
        lines = self.pooled_lines
        if len(lines) == 1:
            return f"yalnızca {lines[0]} hattında ölçülen"
        if lines:
            return f"ölçülen {len(lines)} hattan ({', '.join(lines)}) havuzlanan"
        return "ölçülen hatlardan havuzlanan"

    def seconds_per_stop_for(self, line_code: str | None, at: dt.datetime | None = None) -> tuple[float, str]:
        """The rate to use, and where it came from.

        The provenance half is not decoration: ``iett_next_arrivals`` has to be able to
        say "this line, this time of day, 342 measured arrivals" or "no measurement for
        this line, using the untuned default", and those two answers deserve different
        wording from the agent.
        """
        line = (line_code or "").strip().upper()
        bucket = bucket_for(at)
        cell = self.cells.get(cell_key(line, bucket))
        if cell is not None:
            return cell.seconds_per_stop, f"line+bucket, n={cell.samples}"
        cell = self.lines.get(line)
        if cell is not None:
            return cell.seconds_per_stop, f"line, n={cell.samples}"
        if self.overall is not None:
            return self.overall.seconds_per_stop, f"global, n={self.overall.samples}"
        return self.default_seconds_per_stop, "default"

    def as_speed_profile(self, line_code: str | None, at: dt.datetime | None = None) -> LineSpeedProfile:
        """The rate wrapped for ``estimate_arrivals(speed_profile=...)``. See :class:`LineSpeedProfile`."""
        seconds, provenance = self.seconds_per_stop_for(line_code, at)
        return LineSpeedProfile(seconds, provenance)

    # -- persistence ---------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": self.generated_at,
            "min_samples": self.min_samples,
            "default_seconds_per_stop": self.default_seconds_per_stop,
            "constant_seconds": self.constant_seconds,
            "overall": self.overall.to_dict() if self.overall else None,
            "lines": {key: value.to_dict() for key, value in sorted(self.lines.items())},
            "cells": {key: value.to_dict() for key, value in sorted(self.cells.items())},
            "refused": dict(sorted(self.refused.items())),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any], *, source: str = "dict") -> EtaProfile:
        overall = raw.get("overall")
        return cls(
            cells={key: Cell.from_dict(value) for key, value in (raw.get("cells") or {}).items()},
            lines={key: Cell.from_dict(value) for key, value in (raw.get("lines") or {}).items()},
            overall=Cell.from_dict(overall) if overall else None,
            constant_seconds=float(raw.get("constant_seconds") or 0.0),
            default_seconds_per_stop=float(raw.get("default_seconds_per_stop") or DEFAULT_SECONDS_PER_STOP),
            min_samples=int(raw.get("min_samples") or MIN_SAMPLES),
            generated_at=raw.get("generated_at"),
            refused={key: int(value) for key, value in (raw.get("refused") or {}).items()},
            source=source,
            note=raw.get("note"),
        )

    @classmethod
    def from_cells(
        cls,
        *,
        cells: dict[str, Cell],
        lines: dict[str, Cell],
        overall: Cell | None,
        min_samples: int = MIN_SAMPLES,
        generated_at: str | None = None,
        note: str | None = None,
    ) -> EtaProfile:
        """Build a profile, dropping every cell that has fewer than ``min_samples`` rows.

        The refusal lives here rather than in the calibration script so that "a thin cell
        never reaches the engine" is a property of the profile type itself, testable
        without running a fit, and impossible for a second caller to forget.
        """
        refused: dict[str, int] = {}
        kept_cells: dict[str, Cell] = {}
        kept_lines: dict[str, Cell] = {}
        for source_map, kept in ((cells, kept_cells), (lines, kept_lines)):
            for key, cell in source_map.items():
                if cell.samples >= min_samples:
                    kept[key] = cell
                else:
                    refused[key] = cell.samples
        if overall is not None and overall.samples < min_samples:
            refused["global"] = overall.samples
            overall = None
        return cls(
            cells=kept_cells,
            lines=kept_lines,
            overall=overall,
            min_samples=min_samples,
            generated_at=generated_at,
            refused=refused,
            source="calibration",
            note=note,
        )


def default_profile(note: str | None = None, *, source: str = "built-in default") -> EtaProfile:
    """The uncalibrated profile: 120 s/stop for everything, and a note saying why."""
    return EtaProfile(source=source, note=note)


def _profile_from_json(raw: Any, source: str) -> EtaProfile:
    if not isinstance(raw, dict):
        raise TypeError(f"expected a JSON object, got {type(raw).__name__}")
    return EtaProfile.from_dict(raw, source=source)


def load_profile(settings: Any | None = None, *, path: pathlib.Path | None = None) -> EtaProfile:
    """Read the calibrated profile, or fall back to the untuned default **loudly**.

    A missing or unreadable file must never break arrival estimates — the engine worked
    before this module existed and has to keep working on a checkout with no
    ``data/reference/eta_profile.json`` (it is git-ignored along with the rest of the
    lake). But it must not fail *quietly* either: the returned profile carries a note
    naming the path it wanted, so the absence shows up in diagnostics instead of being
    mistaken for a measured 120 s/stop. Parsed once per file version
    (:func:`ibb_mcp.reference.parse_once`); a fallback is re-checked on the next call.
    """
    target = path or profile_path(settings)
    try:
        return parse_once(target, lambda raw: _profile_from_json(raw, str(target)), kind="eta_profile")
    except FileNotFoundError:
        return default_profile(
            f"eta_profile_not_found_at_{target}_using_untuned_{DEFAULT_SECONDS_PER_STOP:.0f}s_per_stop"
        )
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return default_profile(f"eta_profile_unreadable_at_{target}_{type(exc).__name__}_using_untuned_default")
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        # AttributeError too: a list where a mapping belongs fails in from_dict as one, and a
        # malformed file must cost the calibration, never the arrival estimate.
        return default_profile(f"eta_profile_malformed_at_{target}_{type(exc).__name__}_using_untuned_default")


# --------------------------------------------------------------------------------------
# which rate the tools serve
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RateChoice:
    """The seconds-per-stop rate one arrival estimate uses, with where it came from and why.

    ``source`` is the rung of the fallback chain (``"default"``, ``"line+bucket, n=57"``,
    ...); ``mode`` and ``reason`` say whether the calibrated profile was consulted at all.
    ``iett_next_arrivals`` puts all three in its diagnostics, because "120 s/stop because
    nothing was measured" and "120 s/stop because the measurement did not transfer" are
    different statements.
    """

    seconds_per_stop: float
    source: str
    mode: str
    reason: str
    #: Turkish words naming the lines a pooled rate was measured on; only meaningful when
    #: ``source`` starts with ``global``. See :meth:`EtaProfile.pooled_rate_qualifier`.
    pooled_qualifier: str = "ölçülen hatlardan havuzlanan"

    def as_speed_profile(self) -> LineSpeedProfile | None:
        """For ``estimate_arrivals(speed_profile=...)``; ``None`` leaves the engine on its own default."""
        return LineSpeedProfile(self.seconds_per_stop, self.source) if self.mode == MODE_CALIBRATED else None

    def sentence_tr(self) -> str:
        """Where the rate came from, in the Turkish the agent repeats verbatim, never overstated.

        "global" pools the lines the calibration measured, which today is 500T alone
        (:meth:`EtaProfile.pooled_rate_qualifier` names them): "measured for this line" or
        "measured across all lines" would claim a measurement nobody made. In the default mode
        the profile is not consulted at all, which is a choice, not an absence, and is worded
        as one.
        """
        if self.mode == MODE_DEFAULT:
            return DEFAULT_RATE_SENTENCE_TR
        if self.source == "default":
            return "Bu hat için henüz ölçüm yok; kalibre edilmemiş varsayılan kullanılıyor."
        if self.source.startswith("global"):
            return f"Bu hat için ayrı ölçüm yok; durak başına süre {self.pooled_qualifier} orandan geliyor ({self.source})."
        return f"Durak başına süre bu hat için ölçülmüş veriden geliyor ({self.source})."


def serving_mode(settings: Any | None = None) -> tuple[str, str | None]:
    """The configured mode, and a problem to report when the value was not one of :data:`PROFILE_MODES`.

    Anything unrecognised serves the default. A typo in a container setting must not switch
    every rider onto the rate that scored worse, and it must not stop the server either.
    """
    raw = getattr(settings, "eta_profile_mode", None)
    if raw is None:
        raw = os.getenv("NABIZ_ETA_PROFILE_MODE", MODE_DEFAULT)
    mode = str(raw).strip().lower() or MODE_DEFAULT
    if mode in PROFILE_MODES:
        return mode, None
    return MODE_DEFAULT, f"NABIZ_ETA_PROFILE_MODE={str(raw)[:32]!r} is not one of {', '.join(PROFILE_MODES)}"


def served_rate(line_code: str | None, at: dt.datetime | None = None, settings: Any | None = None) -> RateChoice:
    """The rate the tools serve for ``line_code`` at ``at``: the untuned default unless opted in.

    In the default mode the profile file is not even read, so an arrival estimate costs no
    file access and cannot pick up a fitted rate by accident. In the calibrated mode the
    profile's fallback chain applies as before; a missing or unreadable profile falls back
    to the default and says so, without the path (it would name this machine's user).
    """
    mode, problem = serving_mode(settings)
    if mode == MODE_DEFAULT:
        reason = DEFAULT_MODE_REASON if problem is None else f"{problem}; {DEFAULT_MODE_REASON}"
        return RateChoice(DEFAULT_SECONDS_PER_STOP, "default", MODE_DEFAULT, reason)
    profile = load_profile(settings)
    seconds, source = profile.seconds_per_stop_for(line_code, at)
    reason = CALIBRATED_MODE_REASON
    if not profile.is_calibrated:
        reason = f"{reason}; the profile is missing or unreadable, so the untuned default is used"
    return RateChoice(seconds, source, MODE_CALIBRATED, reason, profile.pooled_rate_qualifier())


def save_profile(profile: EtaProfile, *, settings: Any | None = None, path: pathlib.Path | None = None) -> pathlib.Path:
    """Write the profile as JSON and return where it landed."""
    target = path or profile_path(settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(profile.to_dict(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return target
