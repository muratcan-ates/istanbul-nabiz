"""Typical car-park occupancy by weekday class and hour, from our own snapshots.

İSPARK publishes *now* and nothing else: no history, no "usually". So "bu otoparkta bu
saatte genelde ne kadar yer olur?" cannot be answered by calling İBB at all — it can only
be answered from the snapshot series this project collects itself
(``data/lake/ispark_snapshot/``). This module turns that series into a profile and,
crucially, decides when the profile is too thin to speak.

Three design points are worth defending, because each of them is a place where it would
have been easier to invent a number:

**Why a weekday *class* and not a weekday.** Keying on all seven days needs seven times
the history for the same confidence, and six of those keys would say nothing useful for
weeks. In İstanbul the parking demand curve has three shapes, not seven: Monday–Friday is
the commute-and-office curve; **Saturday is its own animal** — the shopping and errand day,
when a çarşı or AVM lot can be fuller at 15:00 than any weekday; Sunday is the quiet day,
with the mosque-and-family peak around midday rather than a morning rush. Collapsing
Monday–Friday into one class trades a little resolution for five times the samples per
cell, which is the right trade while the history is measured in days.

**Why a sample floor.** A median of one reading is that reading wearing a statistic's hat.
See :data:`MIN_SAMPLES`.

**Why a span floor.** A sample floor alone is not enough, and this is the subtle part. The
collector writes roughly six snapshots an hour, so a *single afternoon* hands one cell six
samples — six views of one Tuesday, which look exactly like a pattern to a naive count and
are nothing of the kind. Because a cell buckets by hour-of-day, the elapsed time between
its first and last sample can only exceed one hour if **more than one date contributed**.
The 2-hour span floor in :data:`MIN_SPAN_HOURS` is therefore, in practice, the rule "this
cell must have been seen on more than one day", expressed in a unit that stays meaningful
if the collection cadence ever changes. Every cell carries its span so a caller can see it.

Nothing here fabricates: a cell that fails any guard returns ``available: False`` with a
Turkish reason, and the reason distinguishes "no observations", "too few", "one day only"
and "the lot was closed every time we looked".
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import pathlib
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ibb_mcp.config import Settings
from ibb_mcp.models import ISTANBUL_TZ, utcnow

log = logging.getLogger("ibb_mcp.occupancy")

#: Serialisation version. Bumped when the on-disk shape changes incompatibly, so a stale
#: ``occupancy_profile.json`` from an older build is rejected rather than misread.
SCHEMA = "nabiz.occupancy_profile/1"

#: Minimum observations in a (park, weekday class, hour) cell before a median is reported.
#:
#: Three is the smallest count at which a median is a *choice* rather than an average of
#: the only two numbers present, and the smallest at which an interquartile range is
#: bounded by real data on both sides. It is deliberately low: the honest guard against
#: "one afternoon looks like a pattern" is :data:`MIN_SPAN_HOURS`, not this, because at the
#: collector's ~6-snapshots-per-hour cadence three samples is half an hour of one day.
#: Raising this number would only make the profile quieter, not more trustworthy.
MIN_SAMPLES = 3

#: Minimum elapsed time between a cell's first and last sample. A cell holds one hour of
#: the clock, so anything above one hour proves at least two separate dates contributed.
#: Two hours is that boundary with room for clock skew and a shifted collection cadence.
MIN_SPAN_HOURS = 2.0

WEEKDAY_TR = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]

#: Human-readable Turkish name for each weekday class, used in the coverage note.
CLASS_TR = {
    "weekday": "hafta içi",
    "saturday": "cumartesi",
    "sunday": "pazar",
}

#: Filename under the reference directory. Committed to the repo: it is small, derived,
#: and a fresh clone should be able to answer "genelde" without running the collector.
PROFILE_FILENAME = "occupancy_profile.json"


def weekday_class(moment: dt.datetime) -> str:
    """Which demand curve a moment belongs to — see the module docstring for why three."""
    weekday = moment.weekday()
    if weekday == 5:
        return "saturday"
    if weekday == 6:
        return "sunday"
    return "weekday"


def to_istanbul(moment: dt.datetime) -> dt.datetime:
    """Interpret a moment in İstanbul local time.

    A naive datetime is taken to be local wall-clock time, because every caller of
    :meth:`OccupancyProfile.lookup` is answering a question a person asked about a clock on
    a wall ("saat 18:00'de"). An aware datetime is converted. Türkiye is a fixed UTC+3 with
    no DST since 2016, so this conversion never straddles a fold.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=ISTANBUL_TZ)
    return moment.astimezone(ISTANBUL_TZ)


def _parse_ts(value: Any) -> dt.datetime | None:
    """Parse a lake timestamp. Returns ``None`` rather than raising on a malformed row."""
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


@dataclass(frozen=True)
class OccupancyCell:
    """What we have observed for one park, one weekday class, one hour of the day.

    ``median``/``p25``/``p75`` are computed over the *open* samples only: a closed lot
    keeps reporting whatever count it had when it shut, so including those readings would
    describe the shutter, not the demand. ``closed_samples`` keeps the discarded count so a
    lot that is simply closed at this hour can be reported as closed instead of unknown.
    """

    park_id: int
    weekday_class: str
    hour: int
    samples: int
    median: float | None
    p25: float | None
    p75: float | None
    first_seen_utc: dt.datetime | None
    last_seen_utc: dt.datetime | None
    observed_days: int
    closed_samples: int = 0

    @property
    def span_hours(self) -> float:
        """Elapsed time between the first and last observation that fed this cell."""
        if self.first_seen_utc is None or self.last_seen_utc is None:
            return 0.0
        return (self.last_seen_utc - self.first_seen_utc).total_seconds() / 3600.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "park_id": self.park_id,
            "weekday_class": self.weekday_class,
            "hour": self.hour,
            "samples": self.samples,
            "median": self.median,
            "p25": self.p25,
            "p75": self.p75,
            "first_seen_utc": self.first_seen_utc.isoformat() if self.first_seen_utc else None,
            "last_seen_utc": self.last_seen_utc.isoformat() if self.last_seen_utc else None,
            "observed_days": self.observed_days,
            "closed_samples": self.closed_samples,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> OccupancyCell:
        return cls(
            park_id=int(raw["park_id"]),
            weekday_class=str(raw["weekday_class"]),
            hour=int(raw["hour"]),
            samples=int(raw["samples"]),
            median=raw.get("median"),
            p25=raw.get("p25"),
            p75=raw.get("p75"),
            first_seen_utc=_parse_ts(raw.get("first_seen_utc")),
            last_seen_utc=_parse_ts(raw.get("last_seen_utc")),
            observed_days=int(raw.get("observed_days", 0)),
            closed_samples=int(raw.get("closed_samples", 0)),
        )


@dataclass(frozen=True)
class OccupancyProfile:
    """Every cell we have, plus the provenance needed to judge how much to trust it."""

    cells: dict[tuple[int, str, int], OccupancyCell] = field(default_factory=dict)
    parks: dict[int, dict[str, Any]] = field(default_factory=dict)
    built_at_utc: dt.datetime | None = None
    rows_read: int = 0
    first_sample_utc: dt.datetime | None = None
    last_sample_utc: dt.datetime | None = None
    min_samples: int = MIN_SAMPLES
    min_span_hours: float = MIN_SPAN_HOURS

    # -- reading -------------------------------------------------------------------

    def cell(self, park_id: int, weekday_class_: str, hour: int) -> OccupancyCell | None:
        return self.cells.get((int(park_id), weekday_class_, int(hour)))

    def usable_cells(self) -> list[OccupancyCell]:
        """Cells that pass every guard — the ones :meth:`lookup` will actually report."""
        return [cell for cell in self.cells.values() if self._refusal(cell) is None]

    def _refusal(self, cell: OccupancyCell | None) -> str | None:
        """The reason this cell may not be reported, or ``None`` if it may. Turkish."""
        if cell is None or (cell.samples == 0 and cell.closed_samples == 0):
            return "no_observations"
        if cell.samples == 0:
            return "closed"
        if cell.samples < self.min_samples:
            return "too_few_samples"
        if cell.span_hours < self.min_span_hours:
            return "single_window"
        return None

    def lookup(self, park_id: int, at: dt.datetime) -> dict[str, Any]:
        """Typical occupancy for one car park at one moment.

        Returns a dict that always carries ``available``; when it is ``False`` the ``note``
        is a Turkish sentence the agent can relay verbatim. Never guesses, never
        interpolates from a neighbouring hour — a neighbouring hour is a different
        question, and presenting it as this one would be exactly the kind of quiet
        fabrication the provenance rules exist to prevent.
        """
        local = to_istanbul(at)
        klass = weekday_class(local)
        hour = local.hour
        window = f"{WEEKDAY_TR[local.weekday()]} {hour:02d}:00"
        cell = self.cell(park_id, klass, hour)

        base: dict[str, Any] = {
            "park_id": int(park_id),
            "weekday_class": klass,
            "hour": hour,
            "window": window,
            "at_local": local.isoformat(),
            "coverage": self.coverage_note(),
        }
        district = (self.parks.get(int(park_id)) or {}).get("district")
        if district:
            base["district"] = district

        refusal = self._refusal(cell)
        if refusal is not None:
            base.update(
                {
                    "available": False,
                    "reason": refusal,
                    "samples": cell.samples if cell else 0,
                    "observed_days": cell.observed_days if cell else 0,
                    "span_hours": round(cell.span_hours, 2) if cell else 0.0,
                    "note": self._refusal_note(refusal, cell, window, klass),
                }
            )
            return base

        assert cell is not None  # narrowed by _refusal returning None
        base.update(
            {
                "available": True,
                "reason": None,
                "median_occupancy_pct": cell.median,
                "p25_occupancy_pct": cell.p25,
                "p75_occupancy_pct": cell.p75,
                "samples": cell.samples,
                "observed_days": cell.observed_days,
                "span_hours": round(cell.span_hours, 2),
                "closed_samples": cell.closed_samples,
                "note": (
                    f"{window} için {CLASS_TR[klass]} profili: doluluk genelde %{cell.median:.0f} "
                    f"(çeyrekler %{cell.p25:.0f}–%{cell.p75:.0f}). "
                    f"{cell.samples} gözlem, {cell.observed_days} ayrı gün. "
                    "Geçmiş, bu projenin kendi topladığı anlık görüntülerden; İBB otopark geçmişi yayınlamıyor."
                ),
            }
        )
        return base

    def _refusal_note(self, reason: str, cell: OccupancyCell | None, window: str, klass: str) -> str:
        collected = (
            "İBB otopark doluluğunun geçmişini yayınlamıyor; bu profil bu projenin kendi topladığı "
            "anlık görüntülerden oluşuyor ve toplayıcı çalıştıkça dolacak."
        )
        if reason == "closed":
            seen = cell.closed_samples if cell else 0
            return (
                f"{window} için elimizdeki {seen} gözlemin hepsinde otopark kapalı görünüyordu, "
                "bu yüzden bir doluluk ortalaması vermek doğru olmaz."
            )
        if reason == "too_few_samples":
            seen = cell.samples if cell else 0
            return (
                f"{window} ({CLASS_TR[klass]}) için henüz yeterli geçmiş yok "
                f"({seen} gözlem, en az {self.min_samples} gerekiyor). {collected}"
            )
        if reason == "single_window":
            seen = cell.samples if cell else 0
            span = cell.span_hours if cell else 0.0
            return (
                f"{window} ({CLASS_TR[klass]}) için {seen} gözlem var ama hepsi {span:.1f} saatlik tek bir "
                "gözlem penceresinden geliyor — bu bir alışkanlık değil, tek bir gün. "
                "En az iki ayrı gün ölçülmeden 'genelde' demek yanıltıcı olur."
            )
        return f"{window} ({CLASS_TR[klass]}) için hiç gözlem yok. {collected}"

    # -- provenance ----------------------------------------------------------------

    def span_hours(self) -> float:
        """Total wall-clock hours between the oldest and newest snapshot in the profile."""
        if self.first_sample_utc is None or self.last_sample_utc is None:
            return 0.0
        return (self.last_sample_utc - self.first_sample_utc).total_seconds() / 3600.0

    def coverage_note(self) -> str:
        """One Turkish sentence stating how much history the whole profile rests on."""
        if not self.cells:
            return "Profil boş: henüz hiç otopark anlık görüntüsü işlenmedi."
        usable = len(self.usable_cells())
        return (
            f"Profil {self.rows_read} anlık görüntü satırından üretildi; toplam {self.span_hours():.1f} saatlik "
            f"gözlem, {len(self.cells)} hücrenin {usable} tanesi raporlanabilir durumda."
        )

    def coverage(self) -> dict[str, Any]:
        """Machine-readable coverage stats, for the build script and the tool layer."""
        usable = self.usable_cells()
        return {
            "rows_read": self.rows_read,
            "parks_with_any_cell": len({cell.park_id for cell in self.cells.values()}),
            "parks_with_usable_cell": len({cell.park_id for cell in usable}),
            "cells": len(self.cells),
            "cells_meeting_min_samples": sum(1 for cell in self.cells.values() if cell.samples >= self.min_samples),
            "cells_usable": len(usable),
            "observation_span_hours": round(self.span_hours(), 2),
            "first_sample_utc": self.first_sample_utc.isoformat() if self.first_sample_utc else None,
            "last_sample_utc": self.last_sample_utc.isoformat() if self.last_sample_utc else None,
            "min_samples": self.min_samples,
            "min_span_hours": self.min_span_hours,
        }

    # -- serialisation -------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "built_at_utc": (self.built_at_utc or utcnow()).isoformat(),
            "rows_read": self.rows_read,
            "first_sample_utc": self.first_sample_utc.isoformat() if self.first_sample_utc else None,
            "last_sample_utc": self.last_sample_utc.isoformat() if self.last_sample_utc else None,
            "min_samples": self.min_samples,
            "min_span_hours": self.min_span_hours,
            "parks": {str(park_id): meta for park_id, meta in sorted(self.parks.items())},
            "cells": [cell.to_dict() for cell in sorted(self.cells.values(), key=lambda c: (c.park_id, c.weekday_class, c.hour))],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> OccupancyProfile:
        found = raw.get("schema")
        if found != SCHEMA:
            raise ValueError(f"unsupported occupancy profile schema {found!r}, expected {SCHEMA!r}")
        cells = [OccupancyCell.from_dict(item) for item in raw.get("cells", [])]
        return cls(
            cells={(cell.park_id, cell.weekday_class, cell.hour): cell for cell in cells},
            parks={int(park_id): dict(meta) for park_id, meta in (raw.get("parks") or {}).items()},
            built_at_utc=_parse_ts(raw.get("built_at_utc")),
            rows_read=int(raw.get("rows_read", 0)),
            first_sample_utc=_parse_ts(raw.get("first_sample_utc")),
            last_sample_utc=_parse_ts(raw.get("last_sample_utc")),
            min_samples=int(raw.get("min_samples", MIN_SAMPLES)),
            min_span_hours=float(raw.get("min_span_hours", MIN_SPAN_HOURS)),
        )


def build_profile(
    rows: Iterable[Mapping[str, Any]],
    *,
    min_samples: int = MIN_SAMPLES,
    min_span_hours: float = MIN_SPAN_HOURS,
) -> OccupancyProfile:
    """Aggregate ``ispark_snapshot`` lake rows into a profile.

    Every observed cell is kept, including ones too thin to report, so :meth:`lookup` can
    answer "2 gözlem var, 3 gerekiyor" instead of the less useful "hiç gözlem yok".
    Malformed rows (no timestamp, no park id, no percentage) are skipped silently — the
    lake is append-only bronze and a single bad line must not lose a day of history.
    """
    buckets: dict[tuple[int, str, int], list[tuple[dt.datetime, float | None, bool]]] = {}
    parks: dict[int, dict[str, Any]] = {}
    rows_read = 0
    first_sample: dt.datetime | None = None
    last_sample: dt.datetime | None = None

    for row in rows:
        stamp = _parse_ts(row.get("ts_utc") or row.get("snapshot_ts_utc"))
        park_raw = row.get("park_id")
        if stamp is None or park_raw is None:
            continue
        try:
            park_id = int(park_raw)
        except (TypeError, ValueError):
            continue
        occupancy = row.get("occupancy_pct")
        occupancy = float(occupancy) if isinstance(occupancy, int | float) else None
        # is_open missing is treated as open: the field arrived later than the first
        # snapshots, and assuming "closed" would silently delete that early history.
        is_open = row.get("is_open") is not False

        rows_read += 1
        first_sample = stamp if first_sample is None or stamp < first_sample else first_sample
        last_sample = stamp if last_sample is None or stamp > last_sample else last_sample

        local = stamp.astimezone(ISTANBUL_TZ)
        key = (park_id, weekday_class(local), local.hour)
        buckets.setdefault(key, []).append((stamp, occupancy, is_open))

        meta = parks.setdefault(park_id, {})
        if row.get("district"):
            meta["district"] = row["district"]
        if row.get("capacity"):
            meta["capacity"] = row["capacity"]

    cells: dict[tuple[int, str, int], OccupancyCell] = {}
    for (park_id, klass, hour), observations in buckets.items():
        open_values = [value for _, value, is_open in observations if is_open and value is not None]
        closed_count = sum(1 for _, _, is_open in observations if not is_open)
        stamps = [stamp for stamp, value, is_open in observations if is_open and value is not None]
        median = p25 = p75 = None
        if open_values:
            median = round(statistics.median(open_values), 1)
            if len(open_values) >= 2:
                # "inclusive" keeps the quartiles inside the observed range, which matters
                # when a cell holds three readings: the default "exclusive" method would
                # extrapolate past the smallest and largest values we ever saw.
                quartiles = statistics.quantiles(open_values, n=4, method="inclusive")
                p25, p75 = round(quartiles[0], 1), round(quartiles[2], 1)
            else:
                p25 = p75 = median
        cells[(park_id, klass, hour)] = OccupancyCell(
            park_id=park_id,
            weekday_class=klass,
            hour=hour,
            samples=len(open_values),
            median=median,
            p25=p25,
            p75=p75,
            first_seen_utc=min(stamps) if stamps else None,
            last_seen_utc=max(stamps) if stamps else None,
            observed_days=len({stamp.astimezone(ISTANBUL_TZ).date() for stamp in stamps}),
            closed_samples=closed_count,
        )

    return OccupancyProfile(
        cells=cells,
        parks=parks,
        built_at_utc=utcnow(),
        rows_read=rows_read,
        first_sample_utc=first_sample,
        last_sample_utc=last_sample,
        min_samples=min_samples,
        min_span_hours=min_span_hours,
    )


def profile_path(settings: Settings | None = None) -> pathlib.Path:
    """Where the profile lives.

    Derived from ``settings.places_csv``'s directory rather than hard-coded, so a test (or
    a deployment with a mounted reference volume) that redirects the reference directory
    redirects this too. ``NABIZ_OCCUPANCY_PROFILE`` overrides both.
    """
    override = os.getenv("NABIZ_OCCUPANCY_PROFILE")
    if override:
        return pathlib.Path(override)
    settings = settings or Settings.from_env()
    return settings.places_csv.parent / PROFILE_FILENAME


def save_profile(profile: OccupancyProfile, path: pathlib.Path | None = None, *, settings: Settings | None = None) -> pathlib.Path:
    """Write the profile as JSON and return where it went."""
    target = path or profile_path(settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Compact separators: this is a generated artefact of a few thousand cells that is
    # committed to a public repo, and indentation would roughly double it for no reader.
    target.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return target


#: Parsed profiles keyed by path, invalidated by (mtime, size). The file is read on the
#: request path, so re-parsing a few thousand cells per question would be a silly cost.
_CACHE: dict[str, tuple[tuple[float, int], OccupancyProfile]] = {}


def load_profile(settings: Settings | None = None, path: pathlib.Path | None = None) -> OccupancyProfile | None:
    """Load the profile, or ``None`` when it has not been built yet.

    Returning ``None`` rather than raising is deliberate: "we have not collected this yet"
    is a normal state of this project, not an error, and the caller turns it into an
    ``available: False`` answer. A file that exists but is corrupt *is* an error worth
    seeing, so it is logged and also returns ``None`` rather than taking a tool down.
    """
    target = path or profile_path(settings)
    try:
        stat = target.stat()
    except OSError:
        return None

    fingerprint = (stat.st_mtime, stat.st_size)
    cached = _CACHE.get(str(target))
    if cached is not None and cached[0] == fingerprint:
        return cached[1]

    try:
        profile = OccupancyProfile.from_dict(json.loads(target.read_text(encoding="utf-8")))
    except (ValueError, KeyError, TypeError) as exc:
        log.warning("occupancy profile at %s is unreadable: %r", target, exc)
        return None

    _CACHE[str(target)] = (fingerprint, profile)
    return profile


def lookup(
    park_id: int,
    at: dt.datetime,
    *,
    settings: Settings | None = None,
    profile: OccupancyProfile | None = None,
) -> dict[str, Any]:
    """Answer "bu otoparkta bu saatte genelde ne kadar yer olur?" for one park.

    This is the entry point the tool layer calls. ``at`` may be naive (read as İstanbul
    wall-clock) or aware. When no profile has been built the answer is ``available: False``
    with a note saying how to build one, never a guess.
    """
    profile = profile if profile is not None else load_profile(settings)
    if profile is None:
        local = to_istanbul(at)
        return {
            "available": False,
            "reason": "no_profile",
            "park_id": int(park_id),
            "weekday_class": weekday_class(local),
            "hour": local.hour,
            "window": f"{WEEKDAY_TR[local.weekday()]} {local.hour:02d}:00",
            "at_local": local.isoformat(),
            "samples": 0,
            "observed_days": 0,
            "span_hours": 0.0,
            "coverage": "Doluluk profili henüz üretilmedi.",
            "note": (
                "Geçmişe dayalı doluluk profili henüz oluşturulmadı "
                f"({PROFILE_FILENAME} yok). Toplanan anlık görüntülerden üretmek için "
                "scripts/build_profiles.py çalıştırılmalı."
            ),
        }
    return profile.lookup(park_id, at)
