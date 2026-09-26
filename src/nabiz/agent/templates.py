"""The agent's deterministic answers: one template per tool, filled only from its payload.

This is the no-model path of :class:`~nabiz.agent.agent.NabizAgent` (keyword routing to one
tool, then one of these templates), split out of ``agent.py`` so the agent's module stays
within its size budget. Nothing here calls a tool or a model.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from nabiz.agent.minutes import METHOD_TR, shown_minutes

CONFIDENCE_TR = {"high": "yüksek", "medium": "orta", "low": "düşük"}


def _num(value: Any, digits: int = 1) -> str:
    """Format a number the Turkish way. Only ever called on values from a tool payload."""
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.{digits}f}".replace(".", ",")
    return str(int(value)) if isinstance(value, float) else str(value)


# --------------------------------------------------------------------------------------
# Deterministic templates. Turkish only, by design: this is the no-quota fallback for a
# Turkish city demo, and a hand-written English branch for every phrase would double the
# surface without adding a single fact. An English question gets one English line saying
# the templated fallback answers in Turkish, so the language rule is broken openly rather
# than silently. Every number printed below is read straight out of the tool payload —
# nothing is derived — so a rendered answer passes the same faithfulness check the model's
# prose has to pass.
# --------------------------------------------------------------------------------------
ATTRIBUTION_LINE = "Kaynak: İBB Açık Veri (CC BY 4.0) · resmî bir servis değildir."
EN_PREFACE = "(No language model is configured, so this fallback answers in Turkish.)"
DETERMINISTIC_NOTE = {
    "tr": "LLM yapılandırılmadığı için deterministic mod kullanıldı: soru anahtar kelimeyle tek bir araca yönlendirildi.",
    "en": "No LLM configured, so deterministic mode answered: the question was keyword-routed to a single tool.",
}
NO_DATA = {"tr": "Bu soruya verecek veri bulunamadı.", "en": "No data available for this question."}
NEED_PLACE = {
    "tr": "Hangi semt ya da ilçe için bakayım? (örnek: Taksim, Kadıköy, Beşiktaş)",
    "en": "Which district should I look at? (for example Taksim, Kadıköy, Beşiktaş)",
}
OUT_OF_SCOPE = {
    "tr": "Bu soruyu elimdeki verilerle yanıtlayamıyorum. Otopark, otobüs, metro, trafik, "
    "hava kalitesi ve veri tazeliği sorabilirsin. "
    "153 Çözüm Merkezi'ne bağlanabilir ya da ilgili resmî sayfaya gidebilirsin.",
    "en": "I cannot answer that from the data I have. Ask about parking, buses, metro, "
    "traffic, air quality or data freshness. "
    "You can call İBB's 153 Solution Centre or go to the relevant official page.",
}
#: The two answers for a question routed to no tool, by :meth:`NabizAgent.route`'s reason.
UNROUTED = {"place": NEED_PLACE, "scope": OUT_OF_SCOPE}
#: İBB's call-centre number, which :data:`OUT_OF_SCOPE` names: a phone line, not a reading,
#: so the numeric check takes it as a source rather than flag it as invented.
HELP_NUMBERS = (153,)
_YES_NO = {True: "var", False: "yok"}


def _r_parking(d: dict[str, Any]) -> list[str]:
    parks = d.get("parks") or []
    if not parks:
        return [f"{d.get('near')} çevresinde boş yeri olan otopark bulunamadı."]
    lines = [f"{d.get('near')} çevresinde {_num(d.get('radius_km'))} km içinde {d.get('count')} otopark bulundu:"]
    for park in parks[:3]:
        bits = [str(park.get("name", ""))]
        if park.get("empty") is not None:
            bits.append(f"{park['empty']} boş yer")
        if park.get("capacity"):
            bits.append(f"{park['capacity']} kapasite")
        if park.get("distance_km") is not None:
            bits.append(f"{_num(park['distance_km'])} km")
        if park.get("tariff"):
            bits.append(str(park["tariff"]))
        lines.append("• " + " · ".join(bits))
    return lines


def _r_arrivals(d: dict[str, Any]) -> list[str]:
    """One whole minute per estimate ("7 dk", "1 dk"), or "tarifeye göre" with no number."""
    stop = (d.get("stop") or {}).get("name") or (d.get("stop") or {}).get("stop_code", "")
    line_code = d.get("line_code", "")
    arrivals = d.get("arrivals") or []
    if not arrivals:
        return [f"{line_code} hattında {stop} durağına yaklaşan araç görünmüyor."]
    lines = [f"{line_code} hattının {stop} durağına tahmini varışı (TAHMİNDİR, resmî İETT bilgisi değildir):"]
    for arrival in arrivals:
        shown = arrival.get("shown") or shown_minutes(arrival.get("eta_minutes"), arrival.get("method"), stale=False)[1]
        bits = [shown]
        if arrival.get("stops_away") is not None and shown.endswith(" dk"):
            bits.append(f"{arrival['stops_away']} durak uzakta")
        method = METHOD_TR.get(str(arrival.get("method")))
        if method and method != shown:
            bits.append(method)
        if arrival.get("confidence") in CONFIDENCE_TR:
            bits.append(f"güven: {CONFIDENCE_TR[arrival['confidence']]}")
        lines.append("• " + " · ".join(bits))
    return lines


def _r_equipment(d: dict[str, Any]) -> list[str]:
    """İBB's fault record for a station or a line. A lift is never said to work: at most "arıza yok"."""
    station = d.get("station") or {}
    lines = [str(station["text"])] if station.get("text") else []
    records = d.get("records") or []
    if not station and d.get("available"):
        lines.append(f"İBB kaydında {d.get('count')} ekipman kullanılamıyor olarak listeli.")
    lines += [f"• {row.get('text')}" for row in records[:5] if row.get("text")]
    if d.get("disclaimer"):
        lines.append(str(d["disclaimer"]))
    return lines


def _r_metro_status(d: dict[str, Any]) -> list[str]:
    statuses = d.get("lines") or []
    if not statuses:
        return ["Metro hatlarında bildirilmiş bir arıza veya çalışma duyurusu yok."]
    return [f"{d.get('count')} hat için duyuru var:"] + [
        f"• {status.get('line_name') or ''}: {status.get('description') or ''}".strip() for status in statuses[:5]
    ]


def _r_station(d: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for station in (d.get("stations") or [])[:3]:
        head = f"{station.get('name')} ({station.get('line_name')})"
        if station.get("order") is not None:
            head += f", hat sırası {station['order']}"
        lines.append(head)
        facts = []
        if station.get("lifts") is not None:
            facts.append(f"asansör: {station['lifts']}")
        if station.get("escalators") is not None:
            facts.append(f"yürüyen merdiven: {station['escalators']}")
        for key, label in (("wc", "WC"), ("baby_room", "bebek bakım odası"), ("masjid", "mescit")):
            if station.get(key) is not None:
                facts.append(f"{label}: {_YES_NO[bool(station[key])]}")
        if facts:
            lines.append("• " + " · ".join(facts))
    return lines


def _r_air_now(d: dict[str, Any]) -> list[str]:
    station, reading = d.get("station") or {}, d.get("reading") or {}
    lines = [f"{d.get('place')} için en yakın ölçüm istasyonu: {station.get('name')}."]
    facts = []
    if reading.get("aqi_index") is not None:
        band = (d.get("band") or {}).get("label")
        facts.append(f"AQI {_num(reading['aqi_index'])}" + (f" ({band})" if band else ""))
    for key in ("pm10", "so2", "o3", "no2"):
        if reading.get(key) is not None:
            facts.append(f"{key.upper()} {_num(reading[key])} µg/m³")
    if reading.get("dominant"):
        facts.append(f"baskın kirletici: {reading['dominant']}")
    if facts:
        lines.append("• " + " · ".join(facts))
    lines.append(
        "Sağlık tavsiyesi değildir; sağlık kararları için hekiminize ve resmî sağlık otoritelerine başvurun. "
        "İBB API'sinde PM2.5 ölçümü yoktur."
    )
    return lines


def _r_air_forecast(d: dict[str, Any]) -> list[str]:
    if not d.get("available"):
        return [f"{d.get('place')} için saatlik PM10 tahmini üretilemedi."]
    station = (d.get("station") or {}).get("name")
    lines = [f"{d.get('place')} · {station} istasyonu, {d.get('horizon_hours')} saatlik PM10 görünümü:"]
    lines += [f"• {item.get('at')} — PM10 {_num(item.get('pm10'))} µg/m³" for item in (d.get("forecast") or [])[:6]]
    if best := d.get("best_window"):
        lines.append(f"En temiz saat: {best.get('at')} (PM10 {_num(best.get('pm10'))} µg/m³).")
    lines.append("Sağlık tavsiyesi değildir.")
    return lines


def _r_traffic(d: dict[str, Any]) -> list[str]:
    if d.get("index") is not None:
        return [f"İstanbul trafik yoğunluk indeksi: {_num(d['index'])} ({d.get('description')})."]
    lines = [str(d.get("description") or "")]
    if d.get("now") is not None:
        lines.append(f"Şu an: {_num(d['now'])}")
    if d.get("same_hour_yesterday") is not None:
        lines.append(f"Dün aynı saat: {_num(d['same_hour_yesterday'])}")
    return lines


def _r_line_buses(d: dict[str, Any]) -> list[str]:
    directions = ", ".join(d.get("directions") or [])
    head = f"{d.get('line_code')} hattında konum bildiren {d.get('count')} araç var"
    return [
        head + (f" (yönler: {directions})." if directions else "."),
        "Araç plakası paylaşılmaz; araçlar kapı numarasıyla anılır.",
    ]


def _r_stops(d: dict[str, Any]) -> list[str]:
    stops = d.get("stops") or []
    if not stops:
        return [f"'{d.get('query')}' için durak bulunamadı."]
    return [f"'{d.get('query')}' için {d.get('count')} durak:"] + [
        f"• {stop.get('name')} ({stop.get('stop_code')})" for stop in stops[:5]
    ]


def _r_places(d: dict[str, Any]) -> list[str]:
    matches = d.get("matches") or []
    if not matches:
        return [f"'{d.get('query')}' için yer bulunamadı."]
    return [f"• {m.get('label')} — {_num(m.get('lat'), 4)}, {_num(m.get('lon'), 4)}" for m in matches[:3]]


def _r_freshness(d: dict[str, Any]) -> list[str]:
    sources = d.get("sources") or {}
    if not sources:
        return ["Henüz hiçbir kaynak sorgulanmadı."]
    lines = ["Kaynak tazeliği:"]
    for name, entry in list(sources.items())[:8]:
        age = entry.get("data_age_seconds", entry.get("age_seconds")) if isinstance(entry, dict) else None
        detail = entry.get("detail") if isinstance(entry, dict) else entry
        lines.append(f"• {name}: " + (f"veri {_num(age)} saniye önce ölçüldü" if age is not None else str(detail or "")))
    return lines


def _r_generic(d: dict[str, Any]) -> list[str]:
    """Fallback: state availability and let the tool's own note carry the detail."""
    if isinstance(d, dict) and d.get("available") is False:
        return ["Bu bilgi için yeterli veri yok."]
    return ["Araç sonucu aşağıdadır."]


RENDERERS = {
    "ispark_find_parking": _r_parking,
    "metro_equipment_status": _r_equipment,
    "iett_next_arrivals": _r_arrivals,
    "metro_status": _r_metro_status,
    "metro_station_info": _r_station,
    "air_quality_now": _r_air_now,
    "air_quality_forecast": _r_air_forecast,
    "traffic_index": _r_traffic,
    "iett_line_buses": _r_line_buses,
    "iett_stops_search": _r_stops,
    "places_resolve": _r_places,
    "city_freshness": _r_freshness,
}


def recorded_stamp(provenance: dict[str, Any]) -> str | None:
    """``"kayıtlı · 26.09 05:15"``: a recording's own time in İstanbul, never an age that reads live."""
    raw = provenance.get("reported_at") or provenance.get("observed_at")
    if not raw:
        return None
    try:
        moment = dt.datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return f"kayıtlı · {moment.astimezone(dt.timezone(dt.timedelta(hours=3))):%d.%m %H:%M}"


def render_answer(tool: str, payload: dict[str, Any], lang: str, *, recorded: bool = False) -> str:
    """Turn one tool payload into a templated answer carrying its age and attribution.

    ``recorded``: the answer comes from recorded fixtures (offline), so it carries the
    recording's time ("kayıtlı · GG.AA SS:DD") instead of an age that would read as live.
    """
    lines = [EN_PREFACE] if lang == "en" else []
    lines += RENDERERS.get(tool, _r_generic)(payload.get("data") or {})
    if payload.get("note"):
        lines.append(str(payload["note"]))
    stamp = recorded_stamp(payload["provenance"]) if recorded and payload["provenance"].get("age") else None
    if stamp:
        lines.append(f"Veri: {stamp}.")
    elif payload["provenance"].get("age"):  # nothing read: no age line, never "0 sn önce"
        lines.append(f"Verinin yaşı: {payload['provenance']['age']}.")
    lines.append(ATTRIBUTION_LINE)
    return "\n".join(line for line in lines if line)
