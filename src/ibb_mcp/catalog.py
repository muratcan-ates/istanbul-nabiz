"""The İBB Open Data catalogue, read from one local file: what data İBB publishes, and where.

``data.ibb.gov.tr`` is a CKAN portal. ``scripts/capture_ibb_catalog.py`` (``make capture-catalog``,
owner only) reads its ``package_search`` in at most three calls and writes the slimmed result to
``data/reference/ibb_catalog.json``; everything here reads that file and nothing else. So a
question about which datasets exist never reaches İBB: the answer is as old as the capture, and it
says so (``catalog.captured_at_utc``).

The file is gitignored (the portal's own metadata, re-made on demand). Without it every function
here reports the gap instead of an empty result, because "no dataset matched" and "we have no
catalogue" are different answers. ``NABIZ_IBB_CATALOG`` points at another file: the tests and the
offline smoke use a synthetic one, which carries ``meta.synthetic: true`` and says so in every answer.

Search is a Turkish-folded token match over title, tags, publisher, categories, description and
resource names, weighted in that order. It is deliberately simple: 557-odd records, one process,
no index to build.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import pathlib
import threading
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ibb_mcp.config import PORTAL, reference_path
from ibb_mcp.models import Provenance, ToolResult
from ibb_mcp.text import looks_like_instruction, normalize_tr

log = logging.getLogger("ibb_mcp.catalog")

CATALOG_FILE = "ibb_catalog.json"
SUMMARY_FILE = "ibb_catalog_summary.json"
SEARCH_URL = f"{PORTAL}/api/3/action/package_search"
DATASETS_URL = f"{PORTAL}/dataset"
SCHEMA_VERSION = 1
#: Characters of a dataset's description kept in the file, and shown in an answer.
NOTES_KEPT = 600
SUMMARY_SHOWN = 240
MAX_LIMIT = 20
#: The portal's nine categories (CKAN groups), as the portal titles them.
CATEGORIES = (
    "Bilgi ve İletişim Teknolojileri", "Enerji", "Ekonomi", "Güvenlik", "Mobilite", "Çevre", "İnsan", "Yönetişim", "Yaşam",
)  # fmt: skip
_CATEGORY_KEYS = {normalize_tr(name): name for name in CATEGORIES}

MISSING_NOTE = (
    "İBB Açık Veri kataloğunun yerel kaydı bu sunucuda yok; katalog henüz kaydedilmedi (sunucu sahibi "
    "`make capture-catalog` ile kaydeder). Veri setlerine https://data.ibb.gov.tr adresinden bakılabilir."
)
SYNTHETIC_NOTE = "Bu katalog SENTETİK bir test kaydıdır; veri setleri gerçek İBB kaydı değildir."

#: Folded words that ask *about* data rather than name a subject: "İBB'nin otopark verisi var mı?"
#: searches for "otopark". Turkish and English, since both reach the search.
_GENERIC = """
    ibb ibbnin nin nun in un n de da te ta deki daki mi mu var yok hangi hangileri ne neler nedir nerede nasil
    bir ve veya ile icin hakkinda ilgili olan bana goster listele liste listesi bul ara arar acik portal portali
    portalinda portaldaki veri verisi verileri verisini verilerini veriler veriseti verisetleri seti setleri setler
    setinde istanbul istanbulun istanbuldaki belediye belediyesi buyuksehir kac tane mevcut
    data dataset datasets open is are there any the of about for on what which do does have has you a an
    """
GENERIC_WORDS = frozenset(_GENERIC.split())
_WEIGHTS = (("title", 3.0), ("tags", 2.5), ("organization", 2.0), ("categories", 1.5), ("notes", 1.0), ("resources", 1.0))


# --------------------------------------------------------------------------------------
# The capture side: CKAN package -> the record this project keeps
# --------------------------------------------------------------------------------------
def _utc_iso(value: Any) -> str | None:
    """CKAN writes naive UTC timestamps; keep them as explicit UTC so a browser cannot read them as local."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    moment = moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(dt.UTC).replace(microsecond=0).isoformat()


def _text(value: Any, limit: int | None = None) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].rstrip() if limit is not None and len(text) > limit else text


def slim_package(package: Mapping[str, Any]) -> dict[str, Any]:
    """The fields of one CKAN package this project keeps; the description cut to :data:`NOTES_KEPT` characters."""
    organization = package.get("organization") or {}
    resources = [
        {
            "name": _text(resource.get("name")),
            "format": _text(resource.get("format")).upper(),
            "url": _text(resource.get("url")),
            "last_modified": _utc_iso(resource.get("last_modified") or resource.get("metadata_modified")),
            "datastore_active": bool(resource.get("datastore_active")),
        }
        for resource in package.get("resources") or []
        if isinstance(resource, Mapping)
    ]
    return {
        "name": _text(package.get("name")),
        "title": _text(package.get("title")) or _text(package.get("name")),
        "notes": _text(package.get("notes"), NOTES_KEPT),
        "organization": _text(organization.get("title") if isinstance(organization, Mapping) else ""),
        "groups": [_text(group.get("title") or group.get("display_name")) for group in package.get("groups") or []],
        "tags": [_text(tag.get("display_name") or tag.get("name")) for tag in package.get("tags") or []],
        "license_title": _text(package.get("license_title")),
        "metadata_modified": _utc_iso(package.get("metadata_modified")),
        "num_resources": int(package.get("num_resources") or len(resources)),
        "resources": resources,
    }


def build_catalog(
    packages: Iterable[Mapping[str, Any]], *, captured_at: dt.datetime, count_reported: int | None, calls: int
) -> dict[str, Any]:
    """The catalogue file's content: the slimmed packages, each once, and how they were read."""
    seen: dict[str, dict[str, Any]] = {}
    for package in packages:
        record = slim_package(package)
        if record["name"]:
            seen.setdefault(record["name"], record)
    datasets = sorted(seen.values(), key=lambda record: record["name"])
    return {
        "meta": {
            "schema": SCHEMA_VERSION,
            "source": SEARCH_URL,
            "captured_at_utc": captured_at.astimezone(dt.UTC).replace(microsecond=0).isoformat(),
            "count_reported": count_reported,
            "count_captured": len(datasets),
            "calls": calls,
            "license": "İBB Açık Veri Lisansı (CC BY 4.0)",
        },
        "datasets": datasets,
    }


def summarize(catalog: Mapping[str, Any], *, recent: int = 30) -> dict[str, Any]:
    """Counts by category, format and publisher, and the most recently updated datasets."""
    datasets = list(catalog.get("datasets") or [])
    categories: Counter[str] = Counter()
    formats: Counter[str] = Counter()
    organizations: Counter[str] = Counter()
    for record in datasets:
        categories.update(record.get("groups") or ["(kategorisiz)"])
        formats.update({resource["format"] for resource in record.get("resources") or [] if resource.get("format")})
        organizations[record.get("organization") or "(kurum yok)"] += 1
    newest = sorted(datasets, key=lambda record: record.get("metadata_modified") or "", reverse=True)[:recent]
    return {
        "captured_at_utc": (catalog.get("meta") or {}).get("captured_at_utc"),
        "datasets": len(datasets),
        "resources": sum(len(record.get("resources") or []) for record in datasets),
        "datastore_datasets": sum(
            1 for record in datasets if any(resource.get("datastore_active") for resource in record.get("resources") or [])
        ),
        "by_category": dict(categories.most_common()),
        "by_format": dict(formats.most_common()),
        "by_organization": dict(organizations.most_common()),
        "recently_updated": [
            {key: record.get(key) for key in ("name", "title", "organization", "metadata_modified")} for record in newest
        ],
    }


# --------------------------------------------------------------------------------------
# The read side: one file, loaded once per change
# --------------------------------------------------------------------------------------
def catalog_path() -> pathlib.Path:
    """``NABIZ_IBB_CATALOG`` when set, else ``data/reference/ibb_catalog.json``."""
    configured = os.getenv("NABIZ_IBB_CATALOG", "").strip()
    return pathlib.Path(configured).expanduser() if configured else reference_path(CATALOG_FILE)


def _tokens(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(token for value in values for token in normalize_tr(value).split()))


def _squash(values: Iterable[str]) -> str:
    return "".join(normalize_tr(value).replace(" ", "") for value in values)


def _stem_match(query: str, word: str) -> bool:
    """Turkish glues suffixes on: "otoparkları" is "otopark". Short words must match exactly."""
    if len(query) <= 3:
        return query == word
    if word.startswith(query) or (len(word) >= 4 and query.startswith(word)):
        return True
    shared = len(os.path.commonprefix([query, word]))
    return shared >= max(5, min(len(query), len(word)) - 2)


@dataclass(frozen=True)
class _Indexed:
    record: dict[str, Any]
    fields: dict[str, tuple[str, ...]]
    squashed: str
    categories: frozenset[str]

    @classmethod
    def build(cls, record: dict[str, Any]) -> _Indexed:
        resources = [resource.get("name") or "" for resource in record.get("resources") or []]
        fields = {
            "title": _tokens([record.get("title") or "", record.get("name", "").replace("-", " ")]),
            "tags": _tokens(record.get("tags") or []),
            "organization": _tokens([record.get("organization") or ""]),
            "categories": _tokens(record.get("groups") or []),
            "notes": _tokens([record.get("notes") or ""]),
            "resources": _tokens(resources),
        }
        squashed = _squash([record.get("title") or "", *(record.get("tags") or [])])
        return cls(record, fields, squashed, frozenset(normalize_tr(group) for group in record.get("groups") or []))

    def score(self, query_tokens: Iterable[str]) -> tuple[int, float]:
        matched, total = 0, 0.0
        for token in query_tokens:
            best = max(
                (weight for name, weight in _WEIGHTS if any(_stem_match(token, word) for word in self.fields[name])),
                default=0.0,
            )
            if not best and len(token) >= 4 and token in self.squashed:
                best = 1.0
            matched += best > 0
            total += best
        return matched, total


@dataclass(frozen=True)
class Catalog:
    meta: dict[str, Any]
    entries: tuple[_Indexed, ...]

    @property
    def synthetic(self) -> bool:
        return bool(self.meta.get("synthetic"))

    @property
    def captured_at(self) -> dt.datetime | None:
        raw = _utc_iso(self.meta.get("captured_at_utc"))
        return dt.datetime.fromisoformat(raw) if raw else None

    def category_counts(self) -> list[dict[str, Any]]:
        counts = Counter(group for entry in self.entries for group in entry.record.get("groups") or [])
        return [{"name": name, "count": counts.get(name, 0)} for name in CATEGORIES]

    def search(self, query: str, category: str | None = None, limit: int = 5) -> tuple[str, int, list[dict[str, Any]]]:
        """``(mode, total_matches, hits)``: "search" by words, "category" or "overview" (newest first) without any."""
        tokens = [token for token in _tokens([query]) if token not in GENERIC_WORDS]
        pool = [entry for entry in self.entries if category is None or normalize_tr(category) in entry.categories]
        newest = sorted(pool, key=lambda entry: entry.record.get("metadata_modified") or "", reverse=True)
        if not tokens:
            return ("category" if category else "overview"), len(pool), [_hit(entry.record) for entry in newest[:limit]]
        needed = max(1, math.ceil(len(tokens) / 2))
        scored = [(entry, *entry.score(tokens)) for entry in newest]
        found = [item for item in scored if item[1] >= needed]
        found.sort(key=lambda item: (item[1], item[2]), reverse=True)  # stable: newest first among equals
        return "search", len(found), [_hit(entry.record) for entry, _, _ in found[:limit]]


def _hit(record: dict[str, Any]) -> dict[str, Any]:
    """One dataset as an answer shows it. A description that talks to a model is not passed on."""
    notes = record.get("notes") or ""
    formats = sorted({resource["format"] for resource in record.get("resources") or [] if resource.get("format")})
    return {
        "name": record["name"],
        "title": record.get("title") or record["name"],
        "organization": record.get("organization") or None,
        "categories": list(record.get("groups") or []),
        "formats": formats,
        "last_updated": record.get("metadata_modified"),
        "url": f"{DATASETS_URL}/{record['name']}",
        "license": record.get("license_title") or None,
        "resources": record.get("num_resources", len(record.get("resources") or [])),
        "datastore": any(resource.get("datastore_active") for resource in record.get("resources") or []),
        "summary": None if looks_like_instruction(notes) else (_text(notes, SUMMARY_SHOWN) or None),
    }


_lock = threading.Lock()
_loaded: dict[pathlib.Path, tuple[float, Catalog | None]] = {}


def load_catalog(path: pathlib.Path | None = None) -> Catalog | None:
    """The catalogue at ``path`` (default :func:`catalog_path`), re-read only when the file changes.

    ``None`` when there is no file or it cannot be read as a catalogue; the reason goes to the log,
    the caller says "no catalogue".
    """
    path = path or catalog_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    with _lock:
        cached = _loaded.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        records = [record for record in raw["datasets"] if isinstance(record, dict) and record.get("name")]
        catalog: Catalog | None = Catalog(dict(raw.get("meta") or {}), tuple(_Indexed.build(record) for record in records))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("catalogue unreadable: %s", type(exc).__name__)
        catalog = None
    with _lock:
        _loaded[path] = (mtime, catalog)
    return catalog


def check_category(category: str | None) -> str | None:
    """The portal's own title for ``category`` (case and Turkish letters folded), or a ValueError naming the nine."""
    if category is None or not category.strip():
        return None
    name = _CATEGORY_KEYS.get(normalize_tr(category))
    if name is None:
        raise ValueError("Kategori şunlardan biri olmalı: " + ", ".join(CATEGORIES) + ".")
    return name


def search_catalog(query: str, category: str | None = None, limit: int = 5, *, path: pathlib.Path | None = None) -> ToolResult:
    """The ``ibb_datasets_search`` tool: datasets on the İBB portal matching ``query``, from the local catalogue."""
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError("Arama metni en fazla 200 karakter olmalı.")
    if not 1 <= int(limit) <= MAX_LIMIT:
        raise ValueError(f"limit 1 ile {MAX_LIMIT} arasında olmalı.")
    category = check_category(category)
    catalog = load_catalog(path)
    data: dict[str, Any] = {"query": query, "category": category}
    if catalog is None:
        data.update(catalog={"available": False}, mode="missing", count=0, total_matches=0, datasets=[])
        provenance = Provenance(source="ibb_catalog", source_url=DATASETS_URL, observed_at=None)
        return ToolResult(data=data, provenance=provenance, note=MISSING_NOTE)
    mode, total, hits = catalog.search(query, category, int(limit))
    data.update(
        catalog={
            "available": True,
            "datasets": len(catalog.entries),
            "captured_at_utc": catalog.meta.get("captured_at_utc"),
            "synthetic": catalog.synthetic,
        },
        mode=mode,
        count=len(hits),
        total_matches=total,
        datasets=hits,
        categories=catalog.category_counts(),
    )
    notes = [SYNTHETIC_NOTE] if catalog.synthetic else []
    if mode == "search" and not hits:
        notes.append("Katalogda bu sözcüklerle eşleşen veri seti bulunamadı; başka bir sözcük ya da kategori deneyin.")
    provenance = Provenance(source="ibb_catalog", source_url=DATASETS_URL, observed_at=catalog.captured_at)
    return ToolResult(data=data, provenance=provenance, note=" ".join(notes) or None)
