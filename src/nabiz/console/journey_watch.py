"""Validated journey inputs and a deterministic, source-bounded impact summary."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import threading
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from typing import Any

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.text import fold_tr, normalize_tr
from nabiz.console.accounts import DEVICE_FOLLOW_LIMIT
from nabiz.console.pii_guard import mask_labels
from nabiz.console.step_free import CONSOLE_SUPPORTED_NEEDS

DEVICE_LIMIT = DEVICE_FOLLOW_LIMIT
ACCOUNT_LIMIT = 5
MAX_PLACE_CHARS = 60
NEEDS = CONSOLE_SUPPORTED_NEEDS
LEVELS = ("affected", "unverified", "clear")
PATH_ENV = "NABIZ_JOURNEY_WATCH_DB_PATH"
DEFAULT_DB = "data/accounts/journey_watch.sqlite"
TTL_DAYS = 90

# These values come from `ibb_mcp.accessibility`; the console consumes them through the
# `Nabiz.accessible_journey` result so this module stays on the console side of the layer seam.
_EQUIPMENT_DATA_UNAVAILABLE = "equipment_data_unavailable"
_STALE_DATA = "stale_data"
_NO_ALTERNATIVE = "no_alternative_found"

_ID = re.compile(r"^[a-z0-9-]{1,24}$")
_TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_COORDINATE = re.compile(r"\d{1,3}[.,]\d{2,}\D{1,3}\d{1,3}[.,]\d{2,}")
_STATION_FAILURE = re.compile(r"^(.+?) istasyonundaki asansör")
_ROUTE_REASONS = {
    "unknown_origin": "Başlangıç yeri metro istasyonlarıyla eşleşmedi.",
    "unknown_destination": "Varış yeri metro istasyonlarıyla eşleşmedi.",
    "no_station_near_origin": "Başlangıç noktasının yakınında metro istasyonu bulunamadı.",
    "no_station_near_destination": "Varış noktasının yakınında metro istasyonu bulunamadı.",
    "disconnected": "Bu iki nokta arasında doğrulanabilir bir raylı sistem bağlantısı bulunamadı.",
}


@dataclass(frozen=True)
class Journey:
    id: str
    origin: str
    destination: str
    time: str | None
    needs: tuple[str, ...]

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "from": self.origin, "to": self.destination,
                "time": self.time, "needs": list(self.needs)}


@dataclass
class _Findings:
    reasons: list[dict[str, Any]]
    affected: set[str]
    fingerprint: set[str]
    lines: set[str]
    uncertainty: list[str]
    comparable: bool = True


def _place(raw: Mapping[str, Any], key: str, label: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{label} alanına bir istasyon ya da yer adı yazın.")
    clean = " ".join(value.split())
    if not 2 <= len(clean) <= MAX_PLACE_CHARS:
        raise ValueError(f"{label} 2 ile {MAX_PLACE_CHARS} karakter arasında olmalı.")
    if _COORDINATE.search(clean):
        raise ValueError("Kayıt bir konum olamaz; istasyon ya da yer adı yazın.")
    if mask_labels(clean)[1]:
        raise ValueError("Yer adında kişisel bilgi olamaz.")
    return clean


def _journey_time(raw: Mapping[str, Any]) -> str | None:
    value = raw.get("time")
    if value in (None, ""):
        return None
    if isinstance(value, str) and _TIME.fullmatch(value):
        return value
    raise ValueError("Saat 24 saat biçiminde olmalı, örneğin 08:30.")


def _journey_needs(raw: Mapping[str, Any]) -> tuple[str, ...]:
    values = raw.get("needs")
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("En az bir yolculuk tercihi seçin.")
    if any(not isinstance(need, str) or need not in NEEDS for need in values):
        raise ValueError("Yolculuk tercihlerinden biri desteklenmiyor.")
    needs = tuple(values)
    if len(set(needs)) != len(needs):
        raise ValueError("Aynı yolculuk tercihini iki kez seçemezsiniz.")
    return needs


def _journey_id(raw: Mapping[str, Any], origin: str, destination: str, time: str | None, needs: tuple[str, ...]) -> str:
    value = raw.get("id")
    if value is None:
        seed = json.dumps([origin, destination, time, needs], ensure_ascii=False, separators=(",", ":"))
        return "j-" + hashlib.sha256(seed.encode()).hexdigest()[:12]
    if isinstance(value, str) and _ID.fullmatch(value):
        return value
    raise ValueError("Yolculuk kimliği geçersiz.")


def journey_from(raw: Mapping[str, Any]) -> Journey:
    """Validate all client fields again before names reach a source call."""
    if not isinstance(raw, Mapping):
        raise ValueError("Yolculuk bilgisi geçersiz. Alanları yeniden kontrol edin.")
    origin, destination = _place(raw, "from", "Başlangıç"), _place(raw, "to", "Varış")
    if fold_tr(origin) == fold_tr(destination):
        raise ValueError("Başlangıç ve varış aynı olamaz.")
    time, needs = _journey_time(raw), _journey_needs(raw)
    return Journey(_journey_id(raw, origin, destination, time, needs), origin, destination, time, needs)


def _stamp(value: Any) -> str | None:
    if isinstance(value, dt.datetime):
        return value.isoformat()
    return value if isinstance(value, str) and value else None


def _route_key(reason: str) -> str:
    return next((f"route:{code}" for code, text in _ROUTE_REASONS.items() if text == reason), "route:unavailable")


def _reason(
    key: str,
    kind: str,
    text: str,
    source: str,
    observed_at: str | None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    details = details or {}
    return {"key": key, "kind": kind, "text": text, "station": details.get("station"),
            "line": details.get("line"), "informational": details.get("informational", False),
            "source": source, "observed_at": observed_at}


def _unverified_route(reason: str, uncertainty: list[str], plan_time: str) -> _Findings:
    source = "İBB metro arızalı ekipman kaydı"
    text = reason or "Yolculuk kaynağı şu an doğrulanamadı."
    return _Findings([_reason(_route_key(reason), "route", text, source, plan_time)],
                     set(), set(), set(), [*uncertainty, "route_unverified"], comparable=False)


def _failed_plan(journey: Journey, plan: Mapping[str, Any], plan_time: str) -> _Findings:
    reason = plan.get("reason") if isinstance(plan.get("reason"), str) else ""
    uncertainty = [code for code in plan.get("uncertainty", []) if isinstance(code, str)]
    unknown = (_EQUIPMENT_DATA_UNAVAILABLE in uncertainty or _STALE_DATA in uncertainty
               or reason in _ROUTE_REASONS.values() or "Metro istasyon verisi okunamadı" in reason)
    if unknown:
        return _unverified_route(reason, uncertainty, plan_time)
    match = _STATION_FAILURE.search(reason)
    route_lift_unknown = reason == "Güzergâhtaki asansör durumları doğrulanamadı." and _NO_ALTERNATIVE in uncertainty
    if match or route_lift_unknown:
        station = match.group(1).strip() if match else None
        key = f"lift:{fold_tr(station)}" if station else "route:no_alternative"
        finding = _reason(key, "lift", reason, "İBB metro arızalı ekipman kaydı", plan_time,
                          {"station": station, "informational": journey.needs == ("slow_walk",)})
        affected = {"step_free"} if "step_free" in journey.needs else set()
        return _Findings([finding], affected, {key}, set(), uncertainty)
    return _unverified_route(reason, uncertainty, plan_time)


def _available_plan(journey: Journey, plan: Mapping[str, Any], plan_time: str) -> _Findings:
    findings = _Findings([], set(), set(), set(), [code for code in plan.get("uncertainty", []) if isinstance(code, str)])
    source = "İBB metro arızalı ekipman kaydı"
    informational = journey.needs == ("slow_walk",)
    for item in plan.get("alternatives_used") or []:
        if not isinstance(item, Mapping):
            continue
        station = str(item.get("avoided_station") or "").strip()
        if not station:
            continue
        key = f"lift:{fold_tr(station)}"
        text = str(item.get("reason") or f"{station} istasyonu güzergâhta atlandı.")
        findings.reasons.append(_reason(key, "lift", text, source, plan_time,
                                         {"station": station, "informational": informational}))
        findings.fingerprint.add(key)
        if "step_free" in journey.needs:
            findings.affected.add("step_free")
    for step in plan.get("steps") or []:
        if isinstance(step, Mapping) and step.get("kind") == "ride" and isinstance(step.get("line"), str):
            line = step["line"].strip().upper()
            if line:
                findings.lines.add(line)
    return findings


def _add_notices(findings: _Findings, journey: Journey, notices: Sequence[Mapping[str, Any]] | None) -> None:
    if notices is None:
        findings.comparable = False
        findings.uncertainty.append("metro_notices_unavailable")
        return
    for notice in notices:
        if not isinstance(notice, Mapping) or notice.get("is_active") is False:
            continue
        line = str(notice.get("line_name") or "").strip().upper()
        description = " ".join(str(notice.get("description") or "").split())
        if not line or line not in findings.lines or not description:
            continue
        summary = hashlib.sha256(normalize_tr(description).encode()).hexdigest()[:12]
        key = f"notice:{line}:{summary}"
        findings.fingerprint.add(key)
        findings.reasons.append(_reason(key, "notice", f"{line}: {description}", "Metro İstanbul duyurusu",
                                         _stamp(notice.get("updated_at")), {"line": line}))
        findings.affected.update(journey.needs)


def _alternative_view(
    journey: Journey,
    plan: Mapping[str, Any],
    alternative: Mapping[str, Any] | None,
    affected: set[str],
) -> dict[str, Any] | None:
    if not plan.get("available") or not plan.get("alternatives_used"):
        return None
    plan_alt = plan.get("alternative_used") or (plan.get("alternatives_used") or [None])[0]
    if not isinstance(plan_alt, Mapping) or not plan_alt.get("station"):
        return None
    approved = False
    approved_text = None
    if alternative and affected and "step_free" in journey.needs:
        source_alt = alternative.get("alternative") if isinstance(alternative.get("alternative"), Mapping) else alternative
        source_station = str(source_alt.get("station") or "") if isinstance(source_alt, Mapping) else ""
        matches = isinstance(source_alt, Mapping) and fold_tr(source_station) == fold_tr(str(plan_alt.get("station")))
        approved = matches and alternative.get("operator_approved") is True
        approved_text = alternative.get("approved_text") if approved else None
    return {"station": plan_alt.get("station"), "line": plan_alt.get("line"),
            "extra_minutes": plan.get("extra_minutes"), "reason": plan_alt.get("reason"),
            "operator_approved": approved, "approved_text": approved_text}


def _level_and_headline(journey: Journey, findings: _Findings) -> tuple[str, str]:
    if findings.affected:
        return "affected", f"Kayıtlı yolculuğunuz etkileniyor: {journey.origin} → {journey.destination}."
    if not findings.comparable:
        return "unverified", f"Kayıtlı yolculuğunuz doğrulanamadı: {journey.origin} → {journey.destination}."
    if journey.needs == ("slow_walk",) and findings.reasons:
        return "clear", "Yolculuk kaydında yalnız asansör bilgisi var; az yürüme ölçülmedi."
    return "clear", "Kayıtlı yolculuğunuzu etkileyen bir kayıt yok."


def _time_note(journey_time: str | None) -> str | None:
    if not journey_time:
        return None
    shown = journey_time.replace(":", ".")
    return f"Yolculuk saatiniz {shown}. Bu kontrol şu anki kayda göredir; {shown}'daki durumu tahmin etmez."


def impact(
    journey: Journey,
    plan: Mapping[str, Any],
    notices: Sequence[Mapping[str, Any]] | None,
    *,
    alternative: Mapping[str, Any] | None,
    checked_at: str,
) -> dict[str, Any]:
    """Combine only route, lift and Metro notice evidence; this function performs no I/O."""
    plan_time = _stamp(plan.get("observed_at")) or checked_at
    findings = _failed_plan(journey, plan, plan_time) if not plan.get("available") else _available_plan(journey, plan, plan_time)
    _add_notices(findings, journey, notices)
    if _STALE_DATA in findings.uncertainty or _EQUIPMENT_DATA_UNAVAILABLE in findings.uncertainty:
        findings.comparable = False
    level, headline = _level_and_headline(journey, findings)
    if level == "clear":
        findings.reasons.append(_reason(
            "route:no_reported_impact", "route",
            "İBB kaydında arıza olmaması asansörün çalıştığını kesin olarak kanıtlamaz.",
            "İBB metro arızalı ekipman kaydı", plan_time, {"informational": True}))
    comparable = findings.comparable and level != "unverified"
    return {"id": journey.id, "level": level, "from": journey.origin, "to": journey.destination,
            "time": journey.time, "needs": list(journey.needs), "headline": headline,
            "affected_needs": sorted(findings.affected), "reasons": findings.reasons,
            "alternative": _alternative_view(journey, plan, alternative, findings.affected),
            "lines": sorted(findings.lines), "fingerprint": sorted(findings.fingerprint) if comparable else [],
            "comparable": comparable, "time_note": _time_note(journey.time),
            "uncertainty": list(dict.fromkeys(findings.uncertainty)),
            "disclaimer": plan.get("disclaimer") or "Asansör bilgisi İBB'nin arıza kaydına dayanır.",
            "provenance": None, "notices_observed_at": checked_at if notices is not None else None,
            "checked_at": checked_at, "error": None}


def changed(previous_fingerprint: Sequence[str] | None, result: Mapping[str, Any]) -> dict[str, list[str]]:
    """Return stable new and resolved keys; unreadable sources never resolve a prior cause."""
    if result.get("comparable") is not True:
        return {"new": [], "resolved": []}
    previous = set(previous_fingerprint or ())
    current = {key for key in result.get("fingerprint", []) if isinstance(key, str)}
    return {"new": sorted(current - previous), "resolved": sorted(previous - current)}


def journeys_path(env: Mapping[str, str] | None = None) -> pathlib.Path:
    values = os.environ if env is None else env
    raw = values.get(PATH_ENV, "").strip()
    return pathlib.Path(raw) if raw else REPO_ROOT / DEFAULT_DB


_SCHEMA = """CREATE TABLE IF NOT EXISTS journey_watch (
    id TEXT NOT NULL, account_id TEXT NOT NULL, created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
    expires_at TEXT NOT NULL, consent_version TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (account_id, id)
);
CREATE INDEX IF NOT EXISTS journey_watch_account ON journey_watch (account_id, created_at);
CREATE INDEX IF NOT EXISTS journey_watch_expiry ON journey_watch (expires_at);"""


class JourneyStore:
    """Opt-in account rows with one 90-day inactive lifetime and no device identifiers."""

    def __init__(self, path: str | pathlib.Path | None = None, *, clock: Any = None) -> None:
        self.path = pathlib.Path(path) if path is not None else journeys_path()
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)
        self.purge()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def now(self) -> dt.datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.UTC)
        return value.astimezone(dt.UTC)

    def purge(self) -> int:
        now = self.now().isoformat()
        with self._lock, closing(self._connect()) as conn:
            return conn.execute("DELETE FROM journey_watch WHERE expires_at <= ?", (now,)).rowcount

    def items(self, account_id: str) -> list[dict[str, Any]]:
        self.purge()
        now = self.now().isoformat()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "UPDATE journey_watch SET last_seen_at = ?, expires_at = ? WHERE account_id = ?",
                (now, (self.now() + dt.timedelta(days=TTL_DAYS)).isoformat(), account_id),
            )
            rows = conn.execute(
                "SELECT * FROM journey_watch WHERE account_id = ? AND expires_at > ? ORDER BY created_at, id",
                (account_id, now),
            ).fetchall()
        return [self._row(row) for row in rows]

    def save(self, account_id: str, journey: Journey, *, consent_version: str) -> dict[str, Any]:
        self.purge()
        now = self.now()
        data = {**journey.public(), "last": None, "choice": None}
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute(
                "SELECT 1 FROM journey_watch WHERE id = ? AND account_id = ?", (journey.id, account_id)
            ).fetchone()
            count = conn.execute("SELECT count(*) FROM journey_watch WHERE account_id = ?", (account_id,)).fetchone()[0]
            if not exists and count >= ACCOUNT_LIMIT:
                conn.execute("ROLLBACK")
                raise ValueError("Hesabınızda en çok 5 yolculuk saklayabilirsiniz.")
            if exists:
                row = conn.execute(
                    "SELECT data FROM journey_watch WHERE id = ? AND account_id = ?", (journey.id, account_id)
                ).fetchone()
                previous = json.loads(row["data"])
                data.update({key: previous.get(key) for key in ("last", "choice")})
            conn.execute(
                "INSERT INTO journey_watch VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(account_id, id) DO UPDATE SET last_seen_at=excluded.last_seen_at, "
                "expires_at=excluded.expires_at, consent_version=excluded.consent_version, data=excluded.data",
                (
                    journey.id,
                    account_id,
                    now.isoformat(),
                    now.isoformat(),
                    (now + dt.timedelta(days=TTL_DAYS)).isoformat(),
                    consent_version,
                    json.dumps(data, ensure_ascii=False),
                ),
            )
            conn.execute("COMMIT")
        return data

    def delete(self, account_id: str, journey_id: str) -> bool:
        self.purge()
        with self._lock, closing(self._connect()) as conn:
            cursor = conn.execute("DELETE FROM journey_watch WHERE id = ? AND account_id = ?", (journey_id, account_id))
            return cursor.rowcount > 0

    def update_check(self, account_id: str, journey_id: str, result: Mapping[str, Any]) -> dict[str, list[str]]:
        self.purge()
        now = self.now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT data FROM journey_watch WHERE id = ? AND account_id = ?", (journey_id, account_id)
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return {"new": [], "resolved": []}
            data = json.loads(row["data"])
            previous = data.get("last") or {}
            diff = changed(previous.get("fingerprint"), result)
            data["last"] = {key: result.get(key) for key in ("level", "fingerprint", "checked_at", "comparable")}
            conn.execute(
                "UPDATE journey_watch SET data = ?, last_seen_at = ?, expires_at = ? WHERE id = ? AND account_id = ?",
                (
                    json.dumps(data, ensure_ascii=False),
                    now.isoformat(),
                    (now + dt.timedelta(days=TTL_DAYS)).isoformat(),
                    journey_id,
                    account_id,
                ),
            )
            conn.execute("COMMIT")
            return diff

    def delete_account(self, account_id: str) -> int:
        with self._lock, closing(self._connect()) as conn:
            return conn.execute("DELETE FROM journey_watch WHERE account_id = ?", (account_id,)).rowcount

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "created_at": row["created_at"], "last_seen_at": row["last_seen_at"],
                "expires_at": row["expires_at"], "consent_version": row["consent_version"],
                **json.loads(row["data"])}
