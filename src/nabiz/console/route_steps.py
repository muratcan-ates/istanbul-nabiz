"""Shape the recorded accessible-journey result into concise, speakable route cards."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from nabiz.agent.templates import recorded_stamp

DISCLAIMER = (
    "Adımlar raylı sistem grafiğinden ve İBB asansör kaydından çıkarıldı; sokak navigasyonu değildir. "
    "Süreler mesafe modeline dayanan tahmindir, tarife değildir. Kayıtta arıza olmaması asansörün çalıştığını kanıtlamaz."
)
DISCLAIMER_EN = (
    "Steps come from the rail graph and İBB lift record; this is not street navigation. Times are estimates "
    "based on a distance model, not a timetable. No fault in the record does not prove a lift is working."
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def lift_sentence(status: str | None, station: str, lang: str) -> str:
    """Say only what the lift record establishes for this station."""
    if status == "working":
        return (
            f"{station} için İBB kaydında asansör arızası yok."
            if lang == "tr"
            else f"No lift fault for {station} in İBB's record."
        )
    if status == "out_of_service":
        return (
            f"İBB kaydına göre {station} istasyonunda asansör kullanılamıyor."
            if lang == "tr"
            else f"According to İBB's record, the lift at {station} station is unavailable."
        )
    if status == "unknown":
        return (
            f"{station} için asansör durumu doğrulanamadı."
            if lang == "tr"
            else f"The lift status for {station} could not be verified."
        )
    return ""


def _ride_groups(steps: Sequence[Mapping[str, Any]]) -> list[tuple[int, int]]:
    groups: list[tuple[int, int]] = []
    index = 0
    while index < len(steps):
        if steps[index].get("kind") != "ride":
            index += 1
            continue
        end = index + 1
        line = _text(steps[index].get("line"))
        while end < len(steps) and steps[end].get("kind") == "ride" and _text(steps[end].get("line")) == line:
            end += 1
        groups.append((index, end))
        index = end
    return groups


def _card_text(kind: str, step: Mapping[str, Any], lang: str, route: Mapping[str, Any]) -> tuple[str, str, str]:
    start = _text(route.get("start"))
    end = _text(route.get("end"))
    destination = _text(route.get("destination"))
    stops = int(route.get("stops") or 0)
    minutes = int(route.get("minutes") or 0)
    next_stop = _text(route.get("next_stop"))
    line = _text(step.get("line"))
    if kind == "ride":
        if lang == "tr":
            title = f"{line} ile {end} istasyonuna gidin"
            detail = f"{start} istasyonunda binin. {stops} durak, yaklaşık {minutes} dk."
            detail += (
                " İlk durakta inin."
                if stops == 1
                else f" Sıradaki durak {next_stop} olmalı; yönü böyle doğrulayabilirsiniz."
            )
        else:
            title = f"Take {line} to {end} station"
            noun = "stop" if stops == 1 else "stops"
            detail = f"Board at {start} station. {stops} {noun}, about {minutes} min."
            detail += (
                " Get off at the first stop."
                if stops == 1
                else f" The next stop should be {next_stop}; use it to check the direction."
            )
        return title, detail, "train"
    if kind == "transfer":
        station = _text(step.get("at_station"))
        return (
            (f"{station} istasyonunda {line} hattına aktarma yapın", f"Yaklaşık {minutes} dk.", "arrows-exchange")
            if lang == "tr"
            else (f"Change to {line} at {station} station", f"About {minutes} min.", "arrows-exchange")
        )
    if start and end:
        return (
            (
                f"{start} istasyonundan {end} istasyonuna yürüyün",
                f"Yaklaşık {minutes} dk. Aktarma yürüyüşü; kuş uçuşu tahmin.", "walk",
            )
            if lang == "tr"
            else (
                f"Walk from {start} station to {end} station",
                f"About {minutes} min. Transfer walk; straight-line estimate.", "walk",
            )
        )
    if end:
        return (
            (
                f"{end} istasyonuna yürüyün",
                f"Yaklaşık {minutes} dk. Kuş uçuşu tahmin; sokak tarifi değildir.", "walk",
            )
            if lang == "tr"
            else (
                f"Walk to {end} station",
                f"About {minutes} min. Straight-line estimate; not street directions.", "walk",
            )
        )
    station = start or end
    return (
        (
            f"{station} istasyonundan çıkın",
            f"Varış noktası {destination}: yaklaşık {minutes} dk yürüyüş. "
            "Kuş uçuşu tahmin; sokak tarifi değildir.",
            "walk",
        )
        if lang == "tr"
        else (
            f"Leave {station} station",
            f"Your destination {destination} is about {minutes} min on foot. "
            "Straight-line estimate; not street directions.",
            "walk",
        )
    )


def _speech(number: int, title: str, detail: str, lift_text: str, lang: str) -> str:
    joined = f"{title}. {detail} {lift_text}".strip()
    if lang == "tr":
        joined = joined.replace(" dk", " dakika")
        return f"Adım {number}. {joined}"
    return f"Step {number}. {joined.replace(' min', ' minutes')}"


def _ride_data(steps: Sequence[Mapping[str, Any]], start: int, end: int) -> dict[str, Any]:
    group = steps[start:end]
    return {
        "step": group[0], "kind": "ride", "end_index": end,
        "start": _text(group[0].get("from_station")), "end": _text(group[-1].get("to_station")),
        "lift_station": _text(group[-1].get("to_station")), "stops": len(group),
        "minutes": sum(max(0, int(item.get("minutes") or 0)) for item in group),
        "next_stop": _text(group[0].get("to_station")),
        "between": [_text(item.get("to_station")) for item in group[:-1] if _text(item.get("to_station"))],
    }


def _walk_data(
    steps: Sequence[Mapping[str, Any]], index: int, first_ride: int, last_ride: int,
) -> dict[str, Any] | None:
    if first_ride < 0:
        return None
    step = steps[index]
    minutes = max(0, int(step.get("minutes") or 0))
    start = end = lift_station = ""
    if index < first_ride:
        end = _text(steps[first_ride].get("from_station"))
    elif index > last_ride:
        start = _text(steps[last_ride].get("to_station"))
    else:
        previous = next((steps[pos] for pos in range(index - 1, -1, -1) if steps[pos].get("kind") == "ride"), {})
        following = next((steps[pos] for pos in range(index + 1, len(steps)) if steps[pos].get("kind") == "ride"), {})
        start = _text(previous.get("to_station"))
        end = _text(following.get("from_station"))
        lift_station = start
    if minutes == 0 and (index < first_ride or index > last_ride):
        return None
    return {
        "step": step, "kind": "walk", "end_index": index + 1,
        "start": start, "end": end, "lift_station": lift_station,
        "minutes": minutes, "stops": 0, "between": [], "next_stop": "",
    }


def _transfer_data(step: Mapping[str, Any], index: int) -> dict[str, Any]:
    station = _text(step.get("at_station"))
    return {
        "step": step, "kind": "transfer", "end_index": index + 1,
        "start": station, "end": station, "lift_station": station,
        "minutes": max(0, int(step.get("minutes") or 0)), "stops": 0, "between": [], "next_stop": "",
    }


def _make_card(route: Mapping[str, Any], destination: str, lang: str, number: int) -> dict[str, Any]:
    kind = _text(route.get("kind"))
    step = route["step"]
    title, detail, icon_name = _card_text(kind, step, lang, {
        "start": route.get("start"), "end": route.get("end"), "destination": destination,
        "stops": route.get("stops"), "minutes": route.get("minutes"), "next_stop": route.get("next_stop"),
    })
    status = _text(step.get("lift_status")) or None
    lift_station = _text(route.get("lift_station"))
    lift_text = lift_sentence(status, lift_station, lang) if status and lift_station else ""
    card = {
        "n": number, "kind": kind, "icon": icon_name, "title": title, "detail": detail,
        "lift_status": status, "lift_text": lift_text, "minutes": route.get("minutes"),
        "stops": route.get("stops"), "between": route.get("between"),
        "speech": _speech(number, title, detail, lift_text, lang),
    }
    if kind == "ride":
        card["next_stop"] = route.get("next_stop")
    map_links = step.get("map_links")
    if kind == "walk" and isinstance(map_links, Mapping):
        card["map_links"] = map_links
    return card


def step_cards(steps: Sequence[Mapping[str, Any]], destination: str, lang: str) -> list[dict[str, Any]]:
    """Group consecutive rides on one line and format source steps without parsing prose."""
    source = [step for step in steps if isinstance(step, Mapping)]
    groups = _ride_groups(source)
    first_ride = groups[0][0] if groups else -1
    last_ride = groups[-1][1] - 1 if groups else -1
    group_ends = {start: end for start, end in groups}
    covered = {index for start, end in groups for index in range(start + 1, end)}
    cards: list[dict[str, Any]] = []
    index = 0
    while index < len(source):
        step = source[index]
        kind = _text(step.get("kind"))
        if kind == "ride" and index not in covered:
            route = _ride_data(source, index, group_ends[index])
        elif kind == "walk":
            route = _walk_data(source, index, first_ride, last_ride)
        elif kind == "transfer":
            route = _transfer_data(step, index)
        else:
            route = None
        if route:
            cards.append(_make_card(route, destination, lang, len(cards) + 1))
            index = int(route["end_index"])
        else:
            index += 1
    return cards


def english_reason(reason: str) -> str:
    """Translate known route failures without exposing Turkish copy on the English surface."""
    text = reason.casefold()
    if "için bir yer bulamadım" in text or "metro istasyonlarıyla eşleşmedi" in text or "yakınında metro istasyonu" in text:
        return "A place could not be found near a rail station."
    if "asansör durumu doğrulanamadı ve" in text or "durumları doğrulanamadı" in text:
        return "A lift on this route could not be verified and no route bypassing it was found."
    if "asansör verisi okunamadı" in text or "equipment data" in text:
        return "The lift record could not be read."
    if "raylı" in text or "bağlantı" in text or "yol yok" in text:
        return "No verifiable rail connection was found."
    if "bulunamadı" in text or "eşleşmedi" in text:
        return "A place could not be found near a rail station."
    return "A step-free route could not be verified."


def freshness(provenance: Mapping[str, Any] | None, lang: str) -> dict[str, str]:
    """Use recorded timestamps as recorded; live input is labelled by age, never as live."""
    source = dict(provenance or {})
    mode = _text(source.get("mode")) or "unknown"
    if mode == "recorded":
        stamp = recorded_stamp(source)
        text = stamp.replace("kayıtlı", "recorded", 1) if lang == "en" and stamp else stamp
        text = text or ("recorded time unknown" if lang == "en" else "kayıt zamanı bilinmiyor")
    elif mode == "live" and source.get("age_s") is not None and 0 <= float(source["age_s"]) < 7200:
        minutes = int(float(source["age_s"]) // 60)
        text = f"updated · {minutes} min ago" if lang == "en" else f"güncel · {minutes} dk önce"
    else:
        text = "data age unknown" if lang == "en" else "veri yaşı bilinmiyor"
    return {"mode": mode, "text": text}


def route_view(body: Mapping[str, Any], lang: str) -> dict[str, Any]:
    """Return the bilingual route-card contract for a recorded accessible-journey response."""
    available = body.get("available") is True
    origin = _text(body.get("from"))
    destination = _text(body.get("to"))
    raw_steps = body.get("steps") if isinstance(body.get("steps"), list) else []
    cards = step_cards(raw_steps, destination, lang) if available else []
    extra_uncertainty = [
        "unknown_step_kind" for step in raw_steps
        if isinstance(step, Mapping) and _text(step.get("kind")) not in {"walk", "ride", "transfer"}
    ]
    uncertainty = list(dict.fromkeys([*(body.get("uncertainty") or []), *extra_uncertainty]))
    total = sum(card["minutes"] for card in cards)
    reason = None
    if not available:
        source_reason = _text(body.get("reason"))
        reason = source_reason if lang == "tr" else english_reason(source_reason)
    notes: list[str] = []
    alternative = body.get("alternative_used")
    if isinstance(alternative, Mapping):
        station = _text(alternative.get("station"))
        avoided = _text(alternative.get("avoided_station"))
        extra = body.get("extra_minutes")
        if lang == "tr":
            notes.append(
                f"Asansör kaydı nedeniyle {avoided} yerine {station} istasyonu kullanıldı; "
                f"tahmini ek süre {extra} dk."
            )
        else:
            notes.append(
                f"The route uses {station} instead of {avoided} because of the lift record; "
                f"estimated extra time: {extra} min."
            )
    provenance = body.get("provenance") if isinstance(body.get("provenance"), Mapping) else {}
    result: dict[str, Any] = {
        "available": available, "from": origin, "to": destination, "lang": lang, "sample": False,
        "summary": (
            f"{origin} → {destination} · yaklaşık {total} dk"
            if available and lang == "tr"
            else f"{origin} → {destination} · about {total} min" if available else None
        ),
        "total_minutes": total if available else None, "cards": cards, "notes": notes,
        "reason": reason,
        "disclaimer": DISCLAIMER if lang == "tr" else DISCLAIMER_EN,
        "freshness": freshness(provenance, lang), "provenance": dict(provenance), "uncertainty": uncertainty,
    }
    return result
