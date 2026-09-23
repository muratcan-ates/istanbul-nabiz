"""Weekday × hour baseline for the İstanbul traffic index — "is this worse than usual?".

The route advisor says a lot about driving that it cannot prove: how fast a car moves at a
given index, how long a bridge queue is, how long parking takes. All of that is assumption.
The one driving claim it can stand behind is **"the index right now is N, and at this hour
on this weekday it has measured M"** — because İBB's ``TrafficIndexHistory`` endpoint hands
us the history to compute M from. This module computes it and nothing else; ``plan_journey``
reports it as a reading beside the drive estimate and ``traffic_index`` beside the live value.

Three decisions here are load-bearing, and each of them is a place where guessing would have
been easier:

**İstanbul local time decides the bucket.** ``TrafficIndexPoint.at`` is UTC; Türkiye is a
fixed UTC+3. Bucketing on the UTC clock would file the 19:00 evening peak under 16:00 and,
around midnight, under the *wrong weekday* entirely — a Saturday-night reading landing in
Saturday's daytime profile. Every bucket key is therefore derived from
``at.astimezone(ISTANBUL_TZ)``.

**Median, not mean.** A cell holds a handful of samples. One accident on the Boğaziçi Köprüsü
takes the index to 90 for an evening; a mean carries that evening into the baseline for weeks
and quietly makes every later comparison read "lighter than usual". The median lets the
outlier be an outlier.

**A cell below :data:`MIN_SAMPLES` says nothing.** Not an interpolation from the neighbouring
hour (a different question), not the whole-week average (a different question), not the single
reading we happen to have wearing a statistic's hat. ``typical`` returns ``None``, the band is
``"unknown"`` and the description states how many observations exist and how many are needed.
A baseline is the one thing in this project that must never be invented: it is the yardstick
everything else is measured against, so a fabricated yardstick corrupts every verdict built on
it — including the ones that look well-sourced.

Pure arithmetic: no network, no disk, no source objects. Feed it
``TrafficSource.index_history(days=28, period="H")`` output, or synthetic points in a test.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ibb_mcp.models import TrafficIndexPoint, to_istanbul

#: Minimum observations in a (weekday, hour) cell before its median may be called "typical".
#: Three matches the floor used by :mod:`ibb_mcp.occupancy`; it is
#: the smallest count at which a median is a *choice* between values rather than the midpoint of
#: the only two we have. With hourly points, three samples means three separate weeks fed the
#: cell, so — unlike the parking profile, where six snapshots can all come from one afternoon —
#: no extra "more than one day" guard is needed here.
MIN_SAMPLES = 3

#: A full week of hourly cells. ``coverage()`` is reported against this.
CELLS_PER_WEEK = 7 * 24

#: Half-width of the "this is just a normal hour" band, as a fraction of the typical value.
#:
#: **This is an assumption, not a measurement.** At the index levels where a commute decision is
#: actually made (roughly 40–60), ±10% is ±4–6 points — about the spread a cell of three to eight
#: samples shows anyway, so anything inside it is noise and should be reported as normal. It is
#: deliberately wider than the precision of the index (1 point) and narrower than one step of
#: :func:`ibb_mcp.models.describe_traffic` (20 points).
TYPICAL_RATIO_MARGIN = 0.10

#: Half-width of the "a person would notice this" band. **Also an assumption.** ±25% is 10–15
#: points at commute levels, more than half of a 20-point ``describe_traffic`` step — a change
#: large enough that the qualitative label is on the edge of moving too. Below it we say
#: "heavier"; at or beyond it, "much heavier".
STRONG_RATIO_MARGIN = 0.25

#: Ratios are unstable when the baseline is tiny: at 04:00 a typical of 4 makes an index of 8
#: "twice as heavy", which is true and useless — both readings mean empty roads. A reading must
#: differ from the baseline by at least this many index points before it may leave the "typical"
#: band at all. **An assumption**, chosen as the smallest gap that is not plausibly rounding or
#: the five-minute jitter of the published index.
MIN_ABSOLUTE_DELTA = 3.0

#: The band used when there is no measured baseline to compare against.
BAND_UNKNOWN = "unknown"

#: Every band :func:`compare_to_typical` can return, ordered lightest → heaviest.
BANDS = ("much_lighter", "lighter", "typical", "heavier", "much_heavier", BAND_UNKNOWN)

# Defined locally rather than imported, matching ibb_mcp.occupancy, so this
# module stays free of imports that pull in settings or the filesystem.
WEEKDAY_TR = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
WEEKDAY_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_BAND_TR = {
    "much_lighter": "olağandan belirgin biçimde akıcı",
    "lighter": "olağandan daha akıcı",
    "typical": "olağan seviyede",
    "heavier": "olağandan daha yoğun",
    "much_heavier": "olağandan belirgin biçimde yoğun",
}

_BAND_EN = {
    "much_lighter": "much lighter than usual",
    "lighter": "lighter than usual",
    "typical": "about as usual",
    "heavier": "heavier than usual",
    "much_heavier": "much heavier than usual",
}


def cell_for(moment: dt.datetime) -> tuple[int, int]:
    """The ``(weekday, hour)`` cell a moment belongs to, in İstanbul local time.

    ``weekday`` is 0 = Monday, matching :meth:`datetime.datetime.weekday` and ``WEEKDAY_TR``.
    """
    local = to_istanbul(moment)
    return local.weekday(), local.hour


def _tr_number(value: float, digits: int = 1) -> str:
    """Format a number the Turkish way — decimal comma, no thousands separator needed here."""
    return f"{value:.{digits}f}".replace(".", ",")


def _tr_signed(value: float, digits: int = 1) -> str:
    """A signed number, Turkish decimal comma kept — "+18,5" rather than "+18.5"."""
    return f"{value:+.{digits}f}".replace(".", ",")


def _window_tr(weekday: int, hour: int) -> str:
    return f"{WEEKDAY_TR[weekday % 7]} {hour % 24:02d}:00"


def _window_en(weekday: int, hour: int) -> str:
    return f"{WEEKDAY_EN[weekday % 7]} at {hour % 24:02d}:00"


@dataclass(frozen=True)
class TrafficBaseline:
    """What the index has actually measured, per weekday and hour of the day.

    ``cells`` holds only the medians that cleared ``min_samples``, so anything read straight out
    of it is reportable. ``counts`` holds *every* observed cell, thin ones included, which is
    what lets a refusal say "1 gözlem, en az 3 gerekiyor" instead of "no data".

    ``sample_count`` counts the points that landed in a cell, which is smaller than the input
    whenever points arrive with no timestamp or a non-positive index (see :func:`build_baseline`).
    """

    cells: Mapping[tuple[int, int], float] = field(default_factory=dict)
    counts: Mapping[tuple[int, int], int] = field(default_factory=dict)
    days_covered: int = 0
    sample_count: int = 0
    #: The floor the cells were built with; :meth:`typical` and :func:`compare_to_typical` honour it.
    min_samples: int = MIN_SAMPLES

    def typical(self, weekday: int, hour: int) -> float | None:
        """Median index for this cell, or ``None`` when too few observations back it.

        An hour we have never seen and an hour we have seen twice both return ``None``: the
        caller is meant to say "bilmiyorum", and the difference between the two is available in
        ``counts`` for the wording, not for a number.
        """
        cell = (int(weekday), int(hour))
        if self.counts.get(cell, 0) < self.min_samples:
            return None
        return self.cells.get(cell)

    def samples_at(self, weekday: int, hour: int) -> int:
        """How many observations sit behind a cell, including cells too thin to report."""
        return int(self.counts.get((int(weekday), int(hour)), 0))

    def coverage(self) -> float:
        """Fraction of the week's 168 cells that have a reportable median.

        Cells that exist but fall below ``min_samples`` deliberately do not count: coverage is
        "how much of the week can I speak about", not "how much of the week have I glimpsed".
        """
        return len(self.cells) / CELLS_PER_WEEK


@dataclass(frozen=True)
class TrafficComparison:
    """One current reading held against its measured baseline.

    Every numeric field is ``None`` together: either there is a baseline for this hour and the
    delta, ratio and band all describe it, or there is not and the descriptions say so.
    """

    index: int
    typical: float | None
    delta: float | None
    ratio: float | None
    band: str
    samples: int
    description_tr: str
    description_en: str

    @property
    def available(self) -> bool:
        """False when no measured baseline backed this comparison — the ``unknown`` band."""
        return self.band != BAND_UNKNOWN


def build_baseline(
    points: Sequence[TrafficIndexPoint],
    *,
    min_samples: int = MIN_SAMPLES,
    before: dt.datetime | None = None,
) -> TrafficBaseline:
    """Fold a series of hourly index readings into a weekday × hour median baseline.

    Feed it ``TrafficSource.index_history(days=28, period="H")``; 28 days is four samples per
    cell, one above the floor, which is why that window is the one worth asking for. The
    charter records the endpoint serving 30 days hourly (docs/NABIZ.md, verified 2026-09-08).

    Three kinds of point are skipped rather than bucketed:

    * ``at is None`` — an unparseable timestamp cannot be filed under an hour, and filing it
      under "now" would put a reading from any hour into the current one.
    * ``index <= 0`` — the published index runs 1–99, and ``TrafficIndexPoint.from_raw`` emits 0
      when the field is missing or unparseable. That zero is an absence, not a quiet city, and
      averaging absences into a median drags the baseline down and makes live traffic look
      permanently worse than usual.
    * ``at >= before``, when ``before`` is given. The history endpoint's newest point *is* the
      reading being judged; left in, it votes in its own baseline — one of four or five
      samples in its cell — and pulls "typical" towards "now". Pass the start of the window
      you want excluded (the tool layer passes 24 hours before the newest point).

    All are silent in the result except through ``sample_count``, which is the number of points
    that survived.
    """
    floor = max(1, int(min_samples))
    buckets: dict[tuple[int, int], list[int]] = {}
    dates: set[dt.date] = set()

    for point in points:
        if point.at is None or point.index is None or point.index <= 0:
            continue
        if before is not None and point.at >= before:
            continue
        local = to_istanbul(point.at)
        buckets.setdefault((local.weekday(), local.hour), []).append(point.index)
        dates.add(local.date())

    counts = {cell: len(values) for cell, values in buckets.items()}
    cells = {cell: round(statistics.median(values), 1) for cell, values in buckets.items() if len(values) >= floor}
    return TrafficBaseline(
        cells=cells,
        counts=counts,
        days_covered=len(dates),
        sample_count=sum(counts.values()),
        min_samples=floor,
    )


def band_for(ratio: float, delta: float) -> str:
    """Which of the five bands a ratio falls in, with the small-baseline guard applied first.

    The cuts are :data:`TYPICAL_RATIO_MARGIN` and :data:`STRONG_RATIO_MARGIN`, and
    :data:`MIN_ABSOLUTE_DELTA` overrides both — all three are assumptions documented where they
    are defined, not values measured from İstanbul traffic. They decide wording only: ``ratio``
    and ``delta`` travel beside the band so a reader can disagree with the cuts and still use the
    numbers.
    """
    if abs(delta) < MIN_ABSOLUTE_DELTA:
        return "typical"
    if ratio <= 1.0 - STRONG_RATIO_MARGIN:
        return "much_lighter"
    if ratio <= 1.0 - TYPICAL_RATIO_MARGIN:
        return "lighter"
    if ratio < 1.0 + TYPICAL_RATIO_MARGIN:
        return "typical"
    if ratio < 1.0 + STRONG_RATIO_MARGIN:
        return "heavier"
    return "much_heavier"


def compare_to_typical(
    index: int,
    moment: dt.datetime,
    baseline: TrafficBaseline,
    *,
    min_samples: int = MIN_SAMPLES,
) -> TrafficComparison:
    """Hold one reading against the baseline for its İstanbul weekday and hour.

    ``moment`` is when the reading was taken (aware, or naive meaning İstanbul local time), not
    when the question was asked — pass ``TrafficIndexPoint.at``, so a cached five-minute-old
    reading is compared against the hour it belongs to rather than the hour it is read out in.

    ``min_samples`` can only *tighten* the floor the baseline was built with: a caller asking for
    fewer samples than the medians were computed from cannot be served, because those medians
    were never stored. The stricter of the two wins.

    Returns a comparison whose band is ``"unknown"`` whenever the hour has no measured baseline.
    That is a legitimate, common answer in the first weeks of collection, and it is the one the
    agent must relay verbatim instead of reaching for the city-wide average.
    """
    weekday, hour = cell_for(moment)
    reading = int(index)
    floor = max(int(min_samples), baseline.min_samples)
    samples = baseline.samples_at(weekday, hour)
    typical = baseline.typical(weekday, hour) if samples >= floor else None

    if typical is None:
        tr, en = _describe_unknown(reading, weekday, hour, samples, floor)
        return TrafficComparison(
            index=reading,
            typical=None,
            delta=None,
            ratio=None,
            band=BAND_UNKNOWN,
            samples=samples,
            description_tr=tr,
            description_en=en,
        )

    if typical <= 0:
        # Only reachable from a hand-built baseline: build_baseline drops non-positive readings.
        # A ratio against zero is undefined and a ratio against a negative is nonsense, so refuse
        # rather than emit an infinity dressed as a verdict.
        tr, en = _describe_unusable(reading, weekday, hour, typical, samples)
        return TrafficComparison(
            index=reading,
            typical=None,
            delta=None,
            ratio=None,
            band=BAND_UNKNOWN,
            samples=samples,
            description_tr=tr,
            description_en=en,
        )

    delta = round(reading - typical, 1)
    ratio = round(reading / typical, 3)
    band = band_for(ratio, delta)
    tr, en = _describe_known(reading, weekday, hour, typical, delta, ratio, band, samples)
    return TrafficComparison(
        index=reading,
        typical=typical,
        delta=delta,
        ratio=ratio,
        band=band,
        samples=samples,
        description_tr=tr,
        description_en=en,
    )


def _describe_known(  # noqa: PLR0913 - debt, ratcheted in scripts/architecture_baseline.json
    index: int,
    weekday: int,
    hour: int,
    typical: float,
    delta: float,
    ratio: float,
    band: str,
    samples: int,
) -> tuple[str, str]:
    """One sentence per language, carrying every number the verdict rests on.

    No ``str.title()`` anywhere: it lowercases the Turkish dotted İ into an ASCII i and turns
    "İstanbul" into "Istanbul". The weekday names are written capitalised in ``WEEKDAY_TR``
    instead, which is also how they are spelled in running Turkish text.
    """
    tr = (
        f"{_window_tr(weekday, hour)} için trafik indeksi {index}; bu saatte ölçülen olağan seviye "
        f"{_tr_number(typical)} ({samples} gözlem). Fark {_tr_signed(delta)} puan, oran {_tr_number(ratio, 2)}: "
        f"{_BAND_TR[band]}."
    )
    en = (
        f"Traffic index {index} on {_window_en(weekday, hour)}; the measured norm for this hour is "
        f"{typical:.1f} from {samples} samples. Difference {delta:+.1f} points, ratio {ratio:.2f}: "
        f"{_BAND_EN[band]}."
    )
    return tr, en


def _describe_unknown(index: int, weekday: int, hour: int, samples: int, floor: int) -> tuple[str, str]:
    """The refusal. It names the reading, the samples we have and the samples we need."""
    tr = (
        f"{_window_tr(weekday, hour)} için trafik indeksi {index}, ancak bu saate ait ölçülmüş bir olağan "
        f"seviye yok ({samples} gözlem, en az {floor} gerekiyor). Trafiğin her zamankinden yoğun olup "
        "olmadığını söyleyemeyiz; olağan seviye İBB'nin saatlik trafik geçmişinden hesaplanıyor ve okunan "
        "geçmişte bu gün ve saat için yeterli gözlem yok."
    )
    en = (
        f"Traffic index {index} on {_window_en(weekday, hour)}, but this hour has no measured norm yet "
        f"({samples} samples, at least {floor} needed). Whether traffic is heavier than usual cannot be "
        "stated; the norm is computed from İBB's own hourly traffic history, and the history read holds "
        "too few readings for this weekday and hour."
    )
    return tr, en


def _describe_unusable(index: int, weekday: int, hour: int, typical: float, samples: int) -> tuple[str, str]:
    """The other refusal: a stored baseline that is not a valid 1–99 index."""
    tr = (
        f"{_window_tr(weekday, hour)} için trafik indeksi {index}; bu saat için kayıtlı olağan seviye "
        f"({_tr_number(typical)}, {samples} gözlem) geçerli bir indeks değil, bu yüzden karşılaştırma yapılmadı."
    )
    en = (
        f"Traffic index {index} on {_window_en(weekday, hour)}; the stored norm for this hour "
        f"({typical:.1f} from {samples} samples) is not a valid index, so no comparison was made."
    )
    return tr, en
