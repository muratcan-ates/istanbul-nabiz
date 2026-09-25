"""Metro İstanbul: lifts, escalators and moving walkways out of service.

Two endpoints, first read on 2026-09-24 (the project's research notes, kept outside this
repository, record what each returned that day):

* ``GetFaultyEquipments`` (GET): a count per equipment group. That day it counted only the
  records of type "Arıza": 10 lifts, where the detail list had 14 unusable ones (10 Arıza, 4
  Revizyon). So the summary is never the answer; it is only compared with the detail list,
  and a disagreement becomes the uncertainty code :data:`SUMMARY_DETAIL_MISMATCH`.
* ``GetFaultyEquipmentDetails`` (POST, body ``{"EquipmentGroupName": <group>}``): one record
  per unusable piece of equipment, with ``Code``, ``Group``, ``LineId``, ``LineName``,
  ``StationId``, ``StationName``, ``Location``, ``Type``, ``Date`` and ``Description``. Any
  other body, an empty one included, is answered with a server error, so bodies are built
  only by :func:`details_body`.

What a record does and does not say:

* Every type seen (Arıza, Revizyon, Çalıştırılmıyor) means the equipment cannot be used; a
  type this module does not know is kept as ``unknown`` with :data:`UNKNOWN_STATUS_TYPE`,
  never dropped and never read as usable.
* ``Date`` is undocumented. It may be when the fault began or when service should resume.
  It is passed on as "İBB kaydındaki tarih" with :data:`DATE_SEMANTICS_UNKNOWN` and is never
  used as a return-to-service date.
* A lift missing from the list is not proven usable: the list is what İBB recorded. Text
  built here says "İBB kaydında arıza yok", never that the equipment works.

The summary's own field names were not recorded on 2026-09-24, only its numbers and the word
"Inactive". :func:`parse_summary` therefore finds a row's group by its value and its counts by
key words, and reports :data:`SUMMARY_UNREADABLE` instead of guessing when a row does not fit.
The first recording (``scripts/capture_metro_equipment.py``) is what confirms it.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import re
from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel

from ibb_mcp.cache import CacheEntry
from ibb_mcp.config import METRO_FAULTY_EQUIPMENT_DETAILS, METRO_FAULTY_EQUIPMENTS
from ibb_mcp.http import UpstreamUnavailable
from ibb_mcp.models import ISTANBUL_TZ, MetroStation, Provenance, parse_ibb_datetime, parse_number
from ibb_mcp.sources.base import SourceContext, make_provenance
from ibb_mcp.text import fold_tr, normalize_tr, squash_punctuation

#: The equipment groups ``GetFaultyEquipmentDetails`` answers for, spelled as the API wants
#: them (verified 2026-09-24). Any other name is refused before a request is built.
EQUIPMENT_GROUPS: tuple[str, ...] = ("Asansör", "Yürüyen Merdiven", "Yürüyen Bant")

#: The group as a stable English key, the one signals and rules compare against.
EQUIPMENT_TYPES: dict[str, str] = {"asansor": "elevator", "yuruyen merdiven": "escalator", "yuruyen bant": "moving_walkway"}

#: İBB's ``Type`` values seen on 2026-09-24, folded, and the class each one is. Every one of
#: them means the equipment is out of use.
STATUS_CLASSES: dict[str, str] = {"ariza": "fault", "revizyon": "revision", "calistirilmiyor": "not_operated"}
STATUS_LABELS: dict[str, str] = {
    "fault": "Arıza",
    "revision": "Revizyon",
    "not_operated": "Çalıştırılmıyor",
    "unknown": "bilinmiyor",
}

#: Recorded responses carry their capture date in the name (``..._20260925.json``).
SUMMARY_FIXTURE_PREFIX = "metro_faulty_equipments_"
DETAILS_FIXTURE_PREFIX = "metro_faulty_equipment_details_"

#: Five minutes, like the line notices. The collector's snapshot every 15 minutes is the history.
EQUIPMENT_TTL = 300.0
#: After this long without a fresh read the answer is "son bilinen durum", not the current one.
#: Three missed collector snapshots [varsayım]; the console may choose its own threshold.
EQUIPMENT_STALE_AFTER_S = 2700

# Uncertainty codes: short, stable, English, one per reason an answer may be wrong.
DATE_SEMANTICS_UNKNOWN = "date_semantics_unknown"
SUMMARY_DETAIL_MISMATCH = "summary_detail_mismatch"
SUMMARY_UNREADABLE = "summary_unreadable"
LOCATION_EMPTY = "location_empty"
UNKNOWN_STATUS_TYPE = "unknown_status_type"
GROUP_UNAVAILABLE = "group_unavailable"
NO_RECORDED_DATA = "no_recorded_data"
STATION_UNMATCHED = "station_unmatched"

DATE_LABEL_TR = "İBB kaydındaki tarih (anlamı belgelenmemiş; dönüş tarihi değildir)"
EQUIPMENT_DISCLAIMER_TR = (
    "Metro İstanbul açık verisinden, İBB Açık Veri Lisansı ile. Listede olmayan bir ekipmanın kullanılabilir "
    "olduğu doğrulanmış değildir: liste yalnız İBB'nin kaydettiğini gösterir. Tarih, İBB kaydındaki tarihtir; "
    "anlamı belgelenmemiştir. Resmî İBB hizmeti değildir."
)

#: Words that name the summary's counts. Only "Inactive" was seen (2026-09-24); see the module docstring.
_INACTIVE_WORDS = ("inactive", "pasif", "arizali")
_ACTIVE_WORDS = ("active", "aktif")
_LINE_CODE = re.compile(r"[a-z0-9]+")


def details_body(group: str) -> dict[str, Any]:
    """The only request body this project sends to ``GetFaultyEquipmentDetails``.

    Validated before anything is sent: a missing or malformed body is answered with a
    server error, and a server error is retried, so an invalid request would cost the
    shared gateway several calls and return nothing.
    """
    if group not in EQUIPMENT_GROUPS:
        raise ValueError(f"Bilinmeyen ekipman grubu: {group!r}. Geçerli gruplar: {', '.join(EQUIPMENT_GROUPS)}.")
    return {"EquipmentGroupName": group}


def resolve_group(text: str | None) -> str | None:
    """A group as the user typed it (``"asansor"``, ``"YÜRÜYEN MERDİVEN"``) in the API's spelling."""
    if text is None or not text.strip():
        return None
    wanted = normalize_tr(text)
    for group in EQUIPMENT_GROUPS:
        if normalize_tr(group) == wanted:
            return group
    raise ValueError(f"Bilinmeyen ekipman grubu: {text!r}. Geçerli gruplar: {', '.join(EQUIPMENT_GROUPS)}.")


def group_slug(group: str) -> str:
    """``"Yürüyen Merdiven"`` -> ``"yuruyen_merdiven"``: the group's part of a fixture name."""
    return normalize_tr(group).replace(" ", "_")


def summary_fixture_name(stamp: str) -> str:
    """Recorded ``GetFaultyEquipments`` answer; ``stamp`` is the capture date, ``YYYYMMDD``."""
    return f"{SUMMARY_FIXTURE_PREFIX}{stamp}"


def details_fixture_name(group: str, stamp: str) -> str:
    """Recorded ``GetFaultyEquipmentDetails`` answer for one group, dated like the summary."""
    return f"{DETAILS_FIXTURE_PREFIX}{group_slug(group)}_{stamp}"


def latest_fixture(fixtures_dir: pathlib.Path, prefix: str) -> str | None:
    """The newest recording whose name is ``prefix`` plus an eight-digit date, or ``None``."""
    stamps = sorted(
        path.stem[len(prefix) :]
        for path in fixtures_dir.glob(f"{prefix}*.json")
        if path.stem[len(prefix) :].isdigit() and len(path.stem) == len(prefix) + 8
    )
    return f"{prefix}{stamps[-1]}" if stamps else None


def line_key(name: str | None) -> str:
    """``"M2 Yenikapı-Hacıosman"`` and ``"m2"`` -> ``"M2"``: the leading code two feeds agree on."""
    match = _LINE_CODE.match(fold_tr(name))
    return match.group(0).upper() if match else ""


def station_key(name: str | None) -> str:
    """Station names compared the way the station search compares them: folded, punctuation gone."""
    return squash_punctuation(fold_tr(name))


def unwrap(payload: Any, *, source: str) -> list[Any]:
    """The rows of a Metro answer: ``{Success, Error, Data}`` like the other V2 calls, or a bare list.

    ``Success: false`` is a failure, not an empty list. Its ``Error`` text is not repeated: on
    this API an error can carry server internals, and the message reaches logs and answers.
    """
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise UpstreamUnavailable(f"{source}: beklenmeyen yanıt tipi {type(payload).__name__}", source=source)
    if payload.get("Success") is False:
        raise UpstreamUnavailable(f"{source}: servis hata bildirdi (Success=false)", source=source)
    data = payload.get("Data")
    if data is None:
        return []
    if not isinstance(data, list):
        raise UpstreamUnavailable(f"{source}: Data listesi bekleniyordu", source=source)
    return data


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip() or None


def _int(value: Any) -> int | None:
    number = parse_number(value)
    return None if number is None else int(number)


def _parse_date(raw: str | None) -> dt.datetime | None:
    """İBB's usual timestamp shapes, then a bare date (midnight in İstanbul)."""
    if raw is None:
        return None
    moment = parse_ibb_datetime(raw)
    if moment is not None:
        return moment
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(raw[:10], fmt).replace(tzinfo=ISTANBUL_TZ).astimezone(dt.UTC)
        except ValueError:
            continue
    return None


class EquipmentRecord(BaseModel):
    """One unusable lift, escalator or moving walkway, as ``GetFaultyEquipmentDetails`` lists it."""

    code: str | None = None
    group: str | None = None
    equipment_type: str = "unknown"
    line_id: int | None = None
    line_name: str | None = None
    station_id: int | None = None
    station_name: str | None = None
    location: str | None = None
    status_type: str | None = None
    status_class: str = "unknown"
    ibb_date_raw: str | None = None
    ibb_date: dt.datetime | None = None
    description: str | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any], *, group: str | None = None) -> EquipmentRecord:
        record_group = _text(raw.get("Group")) or group
        status_type = _text(raw.get("Type"))
        date_raw = _text(raw.get("Date"))
        return cls(
            code=_text(raw.get("Code")),
            group=record_group,
            equipment_type=EQUIPMENT_TYPES.get(normalize_tr(record_group), "unknown"),
            line_id=_int(raw.get("LineId")),
            line_name=_text(raw.get("LineName")),
            station_id=_int(raw.get("StationId")),
            station_name=_text(raw.get("StationName")),
            location=_text(raw.get("Location")),
            status_type=status_type,
            status_class=STATUS_CLASSES.get(normalize_tr(status_type), "unknown"),
            ibb_date_raw=date_raw,
            ibb_date=_parse_date(date_raw),
            description=_text(raw.get("Description")),
        )

    @property
    def status_label(self) -> str:
        """İBB's own word for the type when it sent one; ``bilinmiyor`` otherwise."""
        return self.status_type or STATUS_LABELS["unknown"]

    @property
    def outage_id(self) -> str:
        """Stable across snapshots of one ongoing outage: the equipment and İBB's date for it."""
        who = self.code or f"{station_key(self.station_name)}|{line_key(self.line_name)}|{self.equipment_type}"
        return f"{who}@{self.ibb_date_raw or 'tarihsiz'}"

    def uncertainty(self) -> list[str]:
        codes: list[str] = []
        if self.ibb_date_raw is not None:
            codes.append(DATE_SEMANTICS_UNKNOWN)
        if self.location is None:
            codes.append(LOCATION_EMPTY)
        if self.status_class == "unknown":
            codes.append(UNKNOWN_STATUS_TYPE)
        return codes

    def describe(self) -> str:
        """One Turkish line for a card. Says what İBB recorded, never that something works."""
        where = self.station_name or "Bilinmeyen istasyon"
        if self.line_name:
            where = f"{where} ({self.line_name})"
        what = self.group.lower() if self.group else "ekipman"
        sentence = f"{where}: {what} kullanılamıyor, İBB kaydındaki durum: {self.status_label}."
        if self.ibb_date is not None:
            sentence += f" İBB kaydındaki tarih: {self.ibb_date.astimezone(ISTANBUL_TZ):%d.%m.%Y}."
        return sentence


class GroupSummary(BaseModel):
    """One row of ``GetFaultyEquipments`` beside what the detail list says for the same group."""

    group: str
    active: int | None = None
    inactive: int | None = None
    detail_count: int | None = None
    detail_by_type: dict[str, int] = {}
    consistent: bool | None = None


def _count_for(row: dict[str, Any], words: tuple[str, ...], *, exclude: tuple[str, ...] = ()) -> int | None:
    for key, value in row.items():
        folded = normalize_tr(str(key)).replace(" ", "")
        if any(word in folded for word in words) and not any(word in folded for word in exclude):
            number = _int(value)
            if number is not None:
                return number
    return None


def parse_summary(rows: Iterable[Any]) -> list[GroupSummary]:
    """Rows whose group is one of :data:`EQUIPMENT_GROUPS` and whose unusable count can be found."""
    wanted = {normalize_tr(group): group for group in EQUIPMENT_GROUPS}
    found: list[GroupSummary] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        group = next((wanted[normalize_tr(v)] for v in row.values() if isinstance(v, str) and normalize_tr(v) in wanted), None)
        inactive = _count_for(row, _INACTIVE_WORDS)
        if group is None or inactive is None:
            continue
        found.append(GroupSummary(group=group, active=_count_for(row, _ACTIVE_WORDS, exclude=_INACTIVE_WORDS), inactive=inactive))
    return found


class EquipmentSnapshot(BaseModel):
    """Every group read at one moment, the summary beside it, and why it may be wrong."""

    records: list[EquipmentRecord] = []
    summary: list[GroupSummary] = []
    groups_read: list[str] = []
    groups_missing: list[str] = []
    uncertainty: list[str] = []

    @property
    def available(self) -> bool:
        return bool(self.groups_read)


def compare_summary(summary: list[GroupSummary], records: Sequence[EquipmentRecord], groups_read: Sequence[str]) -> bool:
    """Fill each summary row's detail counts; ``True`` when any read group disagrees."""
    mismatch = False
    for row in summary:
        if row.group not in groups_read:
            continue
        in_group = [r for r in records if r.group == row.group]
        by_type: dict[str, int] = {}
        for record in in_group:
            by_type[record.status_label] = by_type.get(record.status_label, 0) + 1
        row.detail_count, row.detail_by_type = len(in_group), by_type
        row.consistent = row.inactive == len(in_group)
        mismatch = mismatch or not row.consistent
    return mismatch


def match_station(record: EquipmentRecord, stations: Sequence[MetroStation]) -> MetroStation | None:
    """The ``GetStations`` platform a record is about, or ``None``.

    By id when the record's line and station ids name a platform whose name agrees; the two
    lists come from one API, but that the ids share one space is not documented, so an id
    whose name disagrees is not trusted. Otherwise by folded name on the same line.
    """
    name, line = station_key(record.station_name), line_key(record.line_name)
    for station in stations:
        same_id = record.station_id is not None and station.station_id == record.station_id
        if same_id and (not name or station_key(station.name) == name):
            return station
    for station in stations:
        if name and station_key(station.name) == name and (not line or line_key(station.line_name) == line):
            return station
    return None


class MetroEquipmentSource:
    """Reads both endpoints through the shared client and cache; offline, the newest recordings."""

    def __init__(self, ctx: SourceContext) -> None:
        self.ctx = ctx

    async def _load(self, prefix: str, fetch) -> list[Any] | None:
        """Rows from the network, or offline from the newest recording; ``None`` when none exists."""
        if self.ctx.settings.offline:
            name = latest_fixture(self.ctx.settings.fixtures_dir, prefix)
            return None if name is None else unwrap(self.ctx.load_fixture(name), source=name)
        return await fetch()

    async def summary_rows(self) -> tuple[list[Any] | None, CacheEntry[Any]]:
        async def fetch() -> list[Any]:
            payload = await self.ctx.client.get_json(METRO_FAULTY_EQUIPMENTS, source="metro_equipment_summary")
            return unwrap(payload, source="metro_equipment_summary")

        async def load() -> list[Any] | None:
            return await self._load(SUMMARY_FIXTURE_PREFIX, fetch)

        return await self.ctx.cached("metro:equipment:summary", load, source="metro_equipment_summary", ttl=EQUIPMENT_TTL)

    async def detail_rows(self, group: str) -> tuple[list[Any] | None, CacheEntry[Any]]:
        body = details_body(group)  # refuses an unknown group before anything is cached or sent

        async def fetch() -> list[Any]:
            payload = await self.ctx.client.post_json(METRO_FAULTY_EQUIPMENT_DETAILS, source="metro_equipment", body=body)
            return unwrap(payload, source="metro_equipment")

        async def load() -> list[Any] | None:
            return await self._load(f"{DETAILS_FIXTURE_PREFIX}{group_slug(group)}_", fetch)

        key = f"metro:equipment:{group_slug(group)}"
        return await self.ctx.cached(key, load, source="metro_equipment", ttl=EQUIPMENT_TTL)

    async def snapshot(self, groups: Sequence[str] = EQUIPMENT_GROUPS) -> tuple[EquipmentSnapshot, Provenance]:
        """Read the summary and each group's details, keeping whatever could be read."""
        snap = EquipmentSnapshot()
        entries: list[CacheEntry[Any]] = []
        for group in groups:
            try:
                rows, entry = await self.detail_rows(group)
            except UpstreamUnavailable:
                snap.groups_missing.append(group)
                continue
            if rows is None:
                snap.groups_missing.append(group)
                continue
            entries.append(entry)
            snap.groups_read.append(group)
            snap.records += [EquipmentRecord.from_raw(row, group=group) for row in rows if isinstance(row, dict)]
        if not snap.groups_read:
            if not self.ctx.settings.offline:
                raise UpstreamUnavailable("metro_equipment: hiçbir ekipman grubu okunamadı", source="metro_equipment")
            # Offline with nothing recorded: an honest "no data", which the cache keeps like any answer.
            snap.uncertainty.append(NO_RECORDED_DATA)
            return snap, _snapshot_provenance(entries)
        if snap.groups_missing:
            snap.uncertainty.append(GROUP_UNAVAILABLE)
        await self._attach_summary(snap)
        for record in snap.records:
            snap.uncertainty += [code for code in record.uncertainty() if code not in snap.uncertainty]
        return snap, _snapshot_provenance(entries)

    async def _attach_summary(self, snap: EquipmentSnapshot) -> None:
        try:
            rows, _ = await self.summary_rows()
        except UpstreamUnavailable:
            rows = None
        snap.summary = parse_summary(rows or [])
        if not snap.summary:
            snap.uncertainty.append(SUMMARY_UNREADABLE)
        elif compare_summary(snap.summary, snap.records, snap.groups_read):
            snap.uncertainty.append(SUMMARY_DETAIL_MISMATCH)


def _snapshot_provenance(entries: Sequence[CacheEntry[Any]]) -> Provenance:
    """The oldest read among the groups dates the answer; any stale group marks it stale."""
    if not entries:
        return make_provenance("metro_equipment", url=METRO_FAULTY_EQUIPMENT_DETAILS)
    oldest = min(entries, key=lambda entry: entry.observed_at_utc)
    provenance = make_provenance("metro_equipment", entry=oldest, url=METRO_FAULTY_EQUIPMENT_DETAILS)
    if any(not entry.fresh for entry in entries):
        provenance = provenance.model_copy(update={"cached": True})
    return provenance
