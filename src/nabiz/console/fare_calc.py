"""Deterministic weekly fare arithmetic over the source-quoted catalogue in fare_sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nabiz.console.fare_sources import DISCLAIMER, NOTICE, load_fare_catalog

TARIFFS = ("tam", "ogrenci", "ogrenci30", "other")
MODES = ("metro", "ferry", "bus", "metrobus", "marmaray", "other")
REQUIRED_PATTERN_FIELDS = {"days_per_week", "round_trip", "tariff", "legs", "within_window", "personalized"}


@dataclass(frozen=True, slots=True)
class FareLeg:
    mode: str
    route: str | None = None


@dataclass(frozen=True, slots=True)
class FarePattern:
    days_per_week: int
    round_trip: bool
    tariff: str
    legs: tuple[FareLeg, ...]
    within_window: bool
    personalized: bool

    @property
    def boardings_per_week(self) -> int:
        return self.days_per_week * (2 if self.round_trip else 1)


def _pattern_field_errors(data: dict[str, Any]) -> list[dict[str, str]]:
    errors = [{"field": key, "code": "unknown"} for key in data if key not in REQUIRED_PATTERN_FIELDS]
    errors.extend({"field": key, "code": "required"} for key in sorted(REQUIRED_PATTERN_FIELDS - data.keys()))
    days = data.get("days_per_week")
    if type(days) is not int or not 1 <= days <= 7:
        errors.append({"field": "days_per_week", "code": "range"})
    for key in ("round_trip", "within_window", "personalized"):
        if type(data.get(key)) is not bool:
            errors.append({"field": key, "code": "type"})
    tariff = data.get("tariff")
    if not isinstance(tariff, str) or tariff not in TARIFFS:
        errors.append({"field": "tariff", "code": "choice"})
    return errors


def _parse_legs(raw_legs: Any, catalog: dict[str, Any]) -> tuple[list[FareLeg], list[dict[str, str]]]:
    if not isinstance(raw_legs, list) or not 1 <= len(raw_legs) <= 4:
        return [], [{"field": "legs", "code": "count"}]
    errors: list[dict[str, str]] = []
    legs: list[FareLeg] = []
    routes = {row.get("id") for row in catalog.get("ferry", {}).get("routes", [])}
    for index, raw_leg in enumerate(raw_legs):
        field = f"legs.{index}"
        if not isinstance(raw_leg, dict) or set(raw_leg) - {"mode", "route"}:
            errors.append({"field": field, "code": "shape"})
            continue
        mode = raw_leg.get("mode")
        route = raw_leg.get("route")
        if not isinstance(mode, str) or mode not in MODES:
            errors.append({"field": f"{field}.mode", "code": "choice"})
            continue
        if mode == "ferry" and (not isinstance(route, str) or len(route) > 80 or route not in routes):
            errors.append({"field": f"{field}.route", "code": "choice"})
            continue
        if mode != "ferry" and route is not None:
            errors.append({"field": f"{field}.route", "code": "unexpected"})
            continue
        legs.append(FareLeg(mode=mode, route=route))
    return legs, errors


def parse_pattern(data: dict[str, Any], catalog: dict[str, Any] | None = None) -> tuple[FarePattern | None, list[dict[str, str]]]:
    """Validate the closed, non-identifying weekly pattern schema."""
    if not isinstance(data, dict):
        return None, [{"field": "pattern", "code": "type"}]
    errors = _pattern_field_errors(data)
    catalog = catalog or load_fare_catalog()
    legs, leg_errors = _parse_legs(data.get("legs"), catalog)
    errors.extend(leg_errors)
    if errors:
        return None, errors
    return FarePattern(
        data["days_per_week"], data["round_trip"], data["tariff"], tuple(legs),
        data["within_window"], data["personalized"],
    ), []


def estimate(pattern: FarePattern, catalog: dict[str, Any]) -> dict[str, Any]:
    """Compute weekly known portions; a missing fare always stays an explicit unknown."""
    if pattern.tariff == "other":
        return {"computed": False, "reason": "other_card", "quotes": _other_quotes(pattern, catalog)}
    boardings = pattern.boardings_per_week
    single = _estimate_single(pattern, catalog, boardings)
    eticket = _estimate_eticket(pattern, catalog, boardings)
    subscription = _estimate_subscription(pattern, catalog, boardings)
    options = [single, eticket, subscription]
    eligible = [row for row in options if row["computed"]]
    complete = all(row["computed"] and row["complete"] for row in options)
    lowest = min(eligible, key=lambda row: row["known_weekly_kurus"]) if complete else None
    rules = catalog["ferry"]["rules"]
    return {
        "computed": True,
        "boardings_per_week": boardings,
        "options": options,
        "lowest": lowest["id"] if lowest else None,
        "lowest_reason": None if lowest else "incomplete",
        "notes": {
            "night_not_counted": rules["night_double"]["quote"],
            "distance_based_refund_not_counted": rules["distance_based"]["quote"],
            "subscription_validity_missing": True,
            "each_boarding_counted": True,
            "park_and_ride_missing": True,
            "senior_65_missing": True,
        },
        "notice": NOTICE,
        "disclaimer": DISCLAIMER,
    }


def _line(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "leg": fields["leg"],
        "mode": fields["mode"],
        "label": fields["label"],
        "source_id": fields["source_id"],
        "column": fields["column"],
        "raw": fields.get("raw"),
        "kurus": fields.get("kurus"),
        "reason": fields.get("reason"),
        "note": fields.get("note"),
        "quote": fields.get("quote"),
        "supports": fields.get("supports", []),
        "section": fields.get("section"),
    }


def _option(option_id: str, computed: bool, lines: list[dict[str, Any]], reason: str | None = None) -> dict[str, Any]:
    unknown = [{"leg": line["leg"], "mode": line["mode"], "reason": line["reason"]}
               for line in lines if line["kurus"] is None]
    known = sum(line["kurus"] for line in lines if line["kurus"] is not None)
    return {"id": option_id, "computed": computed, "reason": reason, "known_weekly_kurus": known,
            "unknown": unknown, "complete": computed and not unknown, "lines": lines}


def _unknown_reason(mode: str) -> str:
    return {"bus": "bus_tariff_unavailable", "metrobus": "bus_tariff_unavailable",
            "marmaray": "marmaray_source_missing", "other": "unknown_mode"}.get(mode, "unknown_mode")


def _single_line(pattern: FarePattern, catalog: dict[str, Any], leg: FareLeg, index: int, boardings: int) -> dict[str, Any]:
    if leg.mode == "metro":
        if index > 0:
            return _line({"leg": index + 1, "mode": leg.mode, "label": "Metro İstanbul", "source_id": "",
                          "column": "", "reason": "metro_transfer_rule_missing"})
        fare = catalog["metro"]["single"]["rows"][pattern.tariff]
        return _line({"leg": index + 1, "mode": leg.mode, "label": fare["label"], "source_id": "metro",
                      "column": fare["label"], "raw": fare["raw"], "kurus": fare["kurus"] * boardings,
                      "quote": fare["quote"], "section": catalog["metro"]["single"]["heading"]})
    if leg.mode == "ferry":
        route = next(row for row in catalog["ferry"]["routes"] if row["id"] == leg.route)
        transfer = index > 0 and pattern.within_window and pattern.personalized
        if transfer:
            transfer_row = catalog["ferry"]["transfers"][min(index - 1, 4)]
            column = catalog["ferry"]["columns"][pattern.tariff]
            fare = transfer_row["fares"][pattern.tariff]
            label = transfer_row["label"]
            quote = transfer_row["quote"]
            section = "Aktarma"
        else:
            column = catalog["ferry"]["columns"][pattern.tariff]
            fare = route["fares"][pattern.tariff]
            label = route["label"]
            quote = route["quote"]
            section = "Merkez Hatlar"
        note = "distance_based_refund_not_counted" if route["distance_based"] else None
        return _line({"leg": index + 1, "mode": leg.mode, "label": label, "source_id": "ferry",
                      "column": column, "raw": fare["raw"], "kurus": fare["kurus"] * boardings,
                      "note": note, "quote": quote, "section": section})
    source_id = "iett" if leg.mode in {"bus", "metrobus"} else ""
    return _line({"leg": index + 1, "mode": leg.mode, "label": _mode_label(leg.mode), "source_id": source_id,
                  "column": "", "reason": _unknown_reason(leg.mode)})


def _mode_label(mode: str) -> str:
    return {"bus": "Otobüs", "metrobus": "Metrobüs", "marmaray": "Marmaray", "other": "Diğer"}.get(mode, mode)


def _estimate_single(pattern: FarePattern, catalog: dict[str, Any], boardings: int) -> dict[str, Any]:
    lines = [_single_line(pattern, catalog, leg, index, boardings) for index, leg in enumerate(pattern.legs)]
    return _option("card_single", True, lines)


def choose_eticket_package(weekly_trips: int, packs: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose the cheapest single pack size repeated enough times to cover a trip count."""
    if type(weekly_trips) is not int or weekly_trips < 1 or not packs:
        raise ValueError("weekly_trips and packs must be positive")
    choices = [( ((weekly_trips + row["passes"] - 1) // row["passes"]) * row["kurus"],
                 (weekly_trips + row["passes"] - 1) // row["passes"], row)
               for row in packs]
    amount, count, pack = min(choices, key=lambda item: (item[0], item[2]["passes"]))
    return {"pack": pack, "count": count, "amount_kurus": amount,
            "unused_passes": count * pack["passes"] - weekly_trips}


def _estimate_eticket(pattern: FarePattern, catalog: dict[str, Any], boardings: int) -> dict[str, Any]:
    lines = []
    metro_legs = [index for index, leg in enumerate(pattern.legs) if leg.mode == "metro"]
    if metro_legs:
        weekly_trips = len(metro_legs) * boardings
        choice = choose_eticket_package(weekly_trips, catalog["metro"]["eticket"]["packs"])
        pack, count, amount = choice["pack"], choice["count"], choice["amount_kurus"]
        lines.append(_line({"leg": 0, "mode": "metro", "label": f"Metro binişleri · {pack['label']} × {count}",
                            "source_id": "metro", "column": pack["label"], "raw": pack["raw"], "kurus": amount,
                            "quote": pack["quote"], "section": catalog["metro"]["eticket"]["heading"]}))
        lines[-1]["extra_passes"] = choice["unused_passes"]
    for index, leg in enumerate(pattern.legs):
        if leg.mode != "metro":
            lines.append(_line({"leg": index + 1, "mode": leg.mode, "label": _mode_label(leg.mode),
                                "source_id": "metro", "column": "", "reason": "eticket_scope_metro_only"}))
    return _option("eticket", True, lines)


def _estimate_subscription(pattern: FarePattern, catalog: dict[str, Any], boardings: int) -> dict[str, Any]:
    pass_row = catalog["metro"]["subscription"]["rows"][pattern.tariff]
    if pass_row["passes"] is None:
        line = _line({"leg": 0, "mode": "metro", "label": pass_row["label"], "source_id": "metro",
                      "column": pass_row["label"], "raw": pass_row["raw"], "reason": "passes_missing",
                      "quote": pass_row["quote"], "section": catalog["metro"]["subscription"]["heading"]})
        return _option("subscription", False, [line], "passes_missing")
    unit_kurus = (pass_row["kurus"] * 2 + pass_row["passes"]) // (2 * pass_row["passes"])
    lines = []
    for index, leg in enumerate(pattern.legs):
        if leg.mode == "metro":
            source = "metro"
            column = pass_row["label"]
            raw = pass_row["raw"]
            line_mode = "metro"
            label = pass_row["label"]
            quote = pass_row["quote"]
            supports = []
        elif leg.mode == "ferry":
            source = "metro"
            column = pass_row["label"]
            raw = pass_row["raw"]
            line_mode = "ferry"
            label = next(row["label"] for row in catalog["ferry"]["routes"] if row["id"] == leg.route)
            quote = pass_row["quote"]
            supports = [{
                "source_id": "ferry",
                "column": "Abonman",
                "quote": catalog["ferry"]["rules"]["subscription_valid"]["quote"],
            }]
        else:
            source = "iett" if leg.mode in {"bus", "metrobus"} else ""
            lines.append(_line({"leg": index + 1, "mode": leg.mode, "label": _mode_label(leg.mode),
                                "source_id": source, "column": "", "reason": "subscription_scope_unknown"}))
            continue
        lines.append(_line({"leg": index + 1, "mode": line_mode, "label": label, "source_id": source,
                            "column": column, "raw": raw, "kurus": unit_kurus * boardings,
                            "note": "each_boarding_counted", "quote": quote, "supports": supports,
                            "section": catalog["metro"]["subscription"]["heading"]}))
    option = _option("subscription", True, lines)
    counted = sum(line["mode"] in {"metro", "ferry"} and line["kurus"] is not None for line in lines) * boardings
    option["weeks_covered"] = round(pass_row["passes"] / counted, 1) if counted else None
    option["pass_shares_kurus"] = unit_kurus
    option["validity_period_missing"] = True
    return option


def _other_quotes(pattern: FarePattern, catalog: dict[str, Any]) -> list[dict[str, Any]]:
    quotes = []
    for row in catalog["metro"]["single"]["other"]:
        quotes.append({"source_id": "metro", "section": catalog["metro"]["single"]["heading"],
                       "column": row["label"], "quote": row["quote"]})
    for leg in pattern.legs:
        if leg.mode != "ferry":
            continue
        route = next(row for row in catalog["ferry"]["routes"] if row["id"] == leg.route)
        quotes.append({"source_id": "ferry", "section": "Merkez Hatlar", "column": "İndirimli (TL)",
                       "label": route["label"], "quote": route["quote"]})
    quotes.append({"source_id": "cards_note", "section": "Seyahat Kartları", "column": "Seyahat Kartları",
                   "quote": catalog["sources"]["cards_note"]["quote"]})
    return quotes
