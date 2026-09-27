"""Stateless notice assembly and privacy-safe calendar reminders."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from ibb_mcp.models import ISTANBUL_TZ
from nabiz.console.cards import display_text
from nabiz.console.digest import public_url
from nabiz.console.email_sender import NOT_OFFICIAL
from nabiz.console.follow import Topic
from nabiz.console.follow_eval import INDEX_MISSING, NO_STATION, rules_for
from nabiz.console.ics import CalendarEvent

log = logging.getLogger("nabiz.console.notices_center")
NoticeKind = Literal["notice", "fault", "measured", "page", "request", "report"]
DateKind = Literal["source", "read", "measured", "page", "sent", "answered"]
CalendarKind = Literal["reminder", "expiry"]
SOURCE_ORDER = {"topic": 0, "request": 1, "report": 2}


def _moment(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


def _latest(values: Sequence[tuple[Any, DateKind]]) -> tuple[dt.datetime, DateKind] | None:
    parsed = [(moment, kind) for raw, kind in values if (moment := _moment(raw)) is not None]
    return max(parsed, key=lambda pair: pair[0]) if parsed else None


def notice_id(source: str, ref_key: str, item_key: str, status: str) -> str:
    """A deterministic opaque id: data dates are excluded, state changes are included."""
    raw = json.dumps([source, ref_key, item_key, status], ensure_ascii=False, separators=(",", ":"))
    return "n_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class Notice:
    id: str
    source: Literal["topic", "request", "report"]
    ref_index: int
    kind: NoticeKind
    label: str | None
    text_tr: str | None
    text_en: str | None
    status: str | None
    severity: str | None
    recorded_at: dt.datetime | None
    date_kind: DateKind | None
    expires_at: dt.datetime | None
    open: bool
    calendar: CalendarKind | None
    simulated: bool
    ref_key: str
    item_key: str
    topic_kind: str | None = None
    topic_value: str | None = None

    def public(self) -> dict[str, Any]:
        """Return exactly the citizen notice contract; internal ids and topic values stay private."""
        return {
            "id": self.id,
            "source": self.source,
            "ref_index": self.ref_index,
            "kind": self.kind,
            "label": self.label,
            "text_tr": self.text_tr,
            "text_en": self.text_en,
            "status": self.status,
            "severity": self.severity,
            "recorded_at": _iso(self.recorded_at),
            "date_kind": self.date_kind,
            "expires_at": _iso(self.expires_at),
            "open": self.open,
            "calendar": self.calendar,
            "simulated": self.simulated,
        }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _citation_date(alert: Mapping[str, Any], kind: str) -> tuple[dt.datetime, DateKind] | None:
    citations = alert.get("citations")
    if not isinstance(citations, list):
        return None
    reported: list[tuple[Any, DateKind]] = []
    observed: list[tuple[Any, DateKind]] = []
    for citation in citations:
        provenance = _mapping(_mapping(citation).get("provenance"))
        reported.append((provenance.get("reported_at"), "source"))
        observed.append((provenance.get("observed_at"), "measured" if kind == "measured" else "read"))
    return _latest(reported) or _latest(observed)


def _unavailable(topic: Topic, index: int, sentence: str) -> dict[str, Any]:
    return {"source": "topic", "ref_index": index, "label": topic.label, "text_tr": display_text(sentence)}


async def topic_notices(nabiz: Any, topic: Topic, index: int) -> tuple[list[Notice], dict[str, Any] | None]:
    """Read one followed topic through the shared facade; failures remain unavailable, never resolved."""
    try:
        if topic.kind == "station":
            try:
                await nabiz.metro_station_info(name=topic.value)
            except ValueError:
                return [], _unavailable(topic, index, NO_STATION)
        if topic.kind == "knowledge":
            result = await nabiz.ibb_services_search(query=topic.value, limit=5)
            data = _mapping(result.data)
            if _mapping(data.get("evidence")).get("level") == "index_missing":
                return [], _unavailable(topic, index, INDEX_MISSING)
            return _page_notices(data.get("hits", []), topic, index)
        result = await nabiz.check_alerts({"rules": rules_for(topic)})
        data = _mapping(result.data)
    except Exception as exc:  # noqa: BLE001 - a failed source is distinct from a clean read
        log.warning("notices source unavailable: %s", type(exc).__name__)
        return [], _unavailable(topic, index, "Kaynak şu an okunamadı; değişiklik kontrol edilemedi.")
    unavailable = _mapping(data.get("unavailable"))
    if unavailable:
        return [], _unavailable(topic, index, " ".join(str(value) for value in unavailable.values()))
    items: list[Notice] = []
    alerts = data.get("alerts")
    if not isinstance(alerts, list):
        return items, None
    for alert_raw in alerts:
        alert = _mapping(alert_raw)
        key = str(alert.get("dedupe_key") or "")
        kind = _alert_kind(key)
        if kind is None:
            continue
        dated = _citation_date(alert, kind)
        recorded, date_kind = dated if dated else (None, None)
        active = kind in {"notice", "fault"}
        items.append(
            Notice(
                id=notice_id("topic", topic.key, key, "active"),
                source="topic",
                ref_index=index,
                kind=kind,
                label=display_text(topic.label),
                text_tr=display_text(str(alert.get("message_tr") or "")),
                text_en=display_text(str(alert.get("message_en") or alert.get("message_tr") or "")),
                status=None,
                severity=str(alert.get("severity") or "warning"),
                recorded_at=recorded,
                date_kind=date_kind,
                expires_at=None,
                open=active,
                calendar="reminder" if active else None,
                simulated=False,
                ref_key=topic.key,
                item_key=key,
                topic_kind=topic.kind,
                topic_value=topic.value,
            )
        )
    return items, None


def _alert_kind(key: str) -> NoticeKind | None:
    if key.startswith("metro:"):
        return "notice"
    if key.startswith("lift:"):
        return "fault"
    if key.startswith("bunching:"):
        return "measured"
    return None


def _page_notices(hits: Any, topic: Topic, index: int) -> tuple[list[Notice], dict[str, Any] | None]:
    if not isinstance(hits, list):
        return [], None
    items: list[Notice] = []
    for hit_raw in hits:
        hit = _mapping(hit_raw)
        url = str(hit.get("url") or "")
        if not url:
            continue
        updated = _moment(hit.get("source_updated_at"))
        fetched = _moment(hit.get("fetched_at"))
        recorded = updated or fetched
        date_kind: DateKind | None = "page" if updated else "read" if fetched else None
        title = display_text(str(hit.get("title") or url))
        key = f"{url}|{title}|{_iso(updated) or ''}"
        items.append(
            Notice(
                id=notice_id("topic", topic.key, key, "active"),
                source="topic",
                ref_index=index,
                kind="page",
                label=title,
                text_tr=display_text(f"Yeni kaynak: {title}"),
                text_en=display_text(f"New source: {title}"),
                status=None,
                severity=None,
                recorded_at=recorded,
                date_kind=date_kind,
                expires_at=None,
                open=False,
                calendar=None,
                simulated=False,
                ref_key=topic.key,
                item_key=url,
                topic_kind=topic.kind,
                topic_value=topic.value,
            )
        )
    return items, None


def request_notice(view: Mapping[str, Any], index: int, now: dt.datetime) -> Notice:
    """Build a request item without retaining its question, reply, operator, or code in public fields."""
    status = str(view.get("status") or "waiting")
    reply = _mapping(view.get("reply"))
    answered = status == "answered"
    recorded = _moment(reply.get("answered_at")) if answered else _moment(view.get("created_at"))
    expiry = _moment(view.get("expires_at"))
    calendar: CalendarKind | None = "expiry" if answered and expiry and expiry - dt.timedelta(hours=24) > now else None
    if not answered:
        calendar = "reminder"
    code = str(view.get("code") or "")
    return Notice(
        id=notice_id("request", code, code, status),
        source="request",
        ref_index=index,
        kind="request",
        label=None,
        text_tr=None,
        text_en=None,
        status=status,
        severity=None,
        recorded_at=recorded,
        date_kind="answered" if answered else "sent",
        expires_at=expiry,
        open=not answered,
        calendar=calendar,
        simulated=True,
        ref_key=code,
        item_key=code,
    )


def report_notice(view: Mapping[str, Any], index: int) -> Notice:
    """Build a citizen-safe report outcome; DECISIONS #54 keeps server timestamps out."""
    status = str(view.get("status") or "waiting")
    code = str(view.get("code") or "")
    active = status == "waiting"
    return Notice(
        id=notice_id("report", code, code, status),
        source="report",
        ref_index=index,
        kind="report",
        label=display_text(str(view.get("station") or "Asansör bildirimi")),
        text_tr=display_text(str(view.get("text") or "")),
        text_en=None,
        status=status,
        severity=None,
        recorded_at=None,
        date_kind=None,
        expires_at=None,
        open=active,
        calendar="reminder" if active else None,
        simulated=True,
        ref_key=code,
        item_key=code,
    )


def sort_notices(items: Sequence[Notice]) -> list[Notice]:
    """Newest dated record first, followed by undated items in source and reference order."""
    return sorted(
        items,
        key=lambda item: (
            item.recorded_at is None,
            -(item.recorded_at.timestamp()) if item.recorded_at else 0,
            SOURCE_ORDER[item.source],
            item.ref_index,
        ),
    )


def _date_label(notice: Notice, lang: str) -> str:
    moment = notice.recorded_at.astimezone(ISTANBUL_TZ).strftime("%d.%m.%Y %H:%M") if notice.recorded_at else ""
    labels = {
        ("source", "tr"): "İBB kaydı",
        ("source", "en"): "İBB record",
        ("read", "tr"): "Nabız okuması",
        ("read", "en"): "Read by Nabız",
        ("measured", "tr"): "ölçüldü",
        ("measured", "en"): "measured",
        ("page", "tr"): "kaynak tarihi",
        ("page", "en"): "source date",
        ("sent", "tr"): "gönderildi",
        ("sent", "en"): "sent",
        ("answered", "tr"): "yanıtlandı",
        ("answered", "en"): "answered",
    }
    if not notice.date_kind or not moment:
        return "tarih yok" if lang == "tr" else "no date"
    return f"{labels[(notice.date_kind, lang)]} · {moment}"


def calendar_event(notice: Notice, *, now: dt.datetime, lang: str) -> CalendarEvent | None:
    """Create a future reminder for an open record or a reply one day before expiry."""
    if notice.calendar == "reminder":
        local = now.astimezone(ISTANBUL_TZ) + dt.timedelta(days=1)
        start = dt.datetime.combine(local.date(), dt.time(9), tzinfo=ISTANBUL_TZ).astimezone(dt.UTC)
    elif notice.calendar == "expiry" and notice.expires_at:
        start = notice.expires_at - dt.timedelta(hours=24)
        if start <= now:
            return None
    else:
        return None
    kind = notice.calendar
    uid_digest = hashlib.sha256(f"{notice.id}|{kind}|{start:%Y%m%d}".encode()).hexdigest()[:24]
    summary, description = _event_copy(notice, start, lang)
    return CalendarEvent(
        uid=f"{uid_digest}@istanbul-nabiz",
        start=start,
        minutes=15,
        summary=display_text(summary),
        description=display_text(description),
        url=f"{public_url()}/#guncellemeler",
    )


def _event_copy(notice: Notice, start: dt.datetime, lang: str) -> tuple[str, str]:
    english = lang == "en"
    if notice.source == "topic":
        return _topic_event_copy(notice, english)
    if notice.source == "request":
        return _request_event_copy(notice, start, english)
    summary = "Nabız reminder: your lift report" if english else "Nabız hatırlatıcısı: asansör bildiriminiz"
    body = (
        "Your report is waiting for a simulated operator decision. "
        "See its result on the device where you sent it. Official records: 153."
        if english
        else "Bildiriminiz simüle operatörün kararını bekliyor. "
        "Sonucu bildirimi gönderdiğiniz cihazda görebilirsiniz. Resmî kayıt için 153."
    )
    return summary, f"{body} {NOT_OFFICIAL}"


def _topic_event_copy(notice: Notice, english: bool) -> tuple[str, str]:
    value = display_text(notice.topic_value or "")
    if notice.topic_kind == "station":
        subject = f"{value} station" if english else f"{value} istasyonu"
    else:
        subject = f"line {value}" if english else f"{value} hattı"
    summary = f"Nabız reminder: {subject}" if english else f"Nabız hatırlatıcısı: {subject}"
    sentence = (notice.text_en if english else notice.text_tr) or notice.text_tr or ""
    date = _date_label(notice, "en" if english else "tr")
    lead = (
        "Reminder: the record's next change is unknown."
        if english
        else "Bu bir hatırlatıcıdır; kaydın ne zaman değişeceği bilinmiyor."
    )
    source = (
        "Data from the İBB Open Data Portal (İBB Open Data License)."
        if english
        else "Veriler İBB Açık Veri Portalı kaynaklıdır (İBB Açık Veri Lisansı)."
    )
    footer = "Not an official İBB service; İstanbul Nabız is an independent student project." if english else NOT_OFFICIAL
    return summary, f"{date}: {sentence} {lead} {source} {footer}"


def _request_event_copy(notice: Notice, start: dt.datetime, english: bool) -> tuple[str, str]:
    event_date = notice.expires_at if notice.calendar == "expiry" and notice.expires_at else start
    when = event_date.astimezone(ISTANBUL_TZ).strftime("%d.%m.%Y %H:%M")
    if notice.calendar == "expiry":
        summary = "Nabız: your operator reply is deleted tomorrow" if english else "Nabız: operatör yanıtınız yarın silinir"
        if english:
            body = (
                f"Your operator reply will be deleted from Nabız on {when} after its 30-day retention period. "
                "Read it on the device where you sent the request."
            )
        else:
            body = (
                f"Operatör yanıtınız 30 günlük saklama süresi dolunca, {when} tarihinde Nabız'dan silinir. "
                "Yanıtı talebi gönderdiğiniz cihazda okuyabilirsiniz."
            )
    else:
        summary = "Nabız reminder: your operator request" if english else "Nabız hatırlatıcısı: operatör talebiniz"
        if english:
            body = (
                f"Your operator request was sent on {when} and is waiting for a reply. "
                "The reply appears on its card on the device where you sent it. In an emergency, call 112."
            )
        else:
            body = (
                f"Operatör talebiniz {when} tarihinde gönderildi ve yanıt bekliyor. "
                "Yanıt, talebi gönderdiğiniz cihazdaki kartta görünür. Acil bir durumda 112'yi arayın."
            )
    footer = NOT_OFFICIAL if not english else "Not an official İBB service; İstanbul Nabız is an independent student project."
    return summary, f"{body} {footer}"
