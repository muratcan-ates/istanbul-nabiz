#!/usr/bin/env python3
"""Rebuild ``data/reference/places.csv``, the gazetteer behind ``places_resolve``.

Sources, in order of trust:

1. Metro İstanbul stations — 217 named points with coordinates, the densest public
   gazetteer İBB publishes.
2. Air-quality stations — 28 points, named after the district they sit in.
3. İSPARK district centroids — the mean position of the car parks in each district,
   which is a decent proxy for "the middle of Beşiktaş".
4. A short hand-written landmark list for the names people actually say out loud
   ("Taksim", "Kadıköy İskele") that none of the machine sources contain.

Run: ``.venv/bin/python scripts/build_places.py``
"""

from __future__ import annotations

import csv
import json
import pathlib
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from ibb_mcp.models import parse_wkt_point, repair_coordinate  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
OUT = ROOT / "data" / "reference" / "places.csv"

# Turkish title case: "ŞİŞLİ" -> "Şişli". str.title() decomposes the dotted capital İ
# into "İ" + combining dot, producing "Şi̇şli̇", so the mapping is done explicitly.
_LOWER = str.maketrans({"I": "ı", "İ": "i", "Ş": "ş", "Ğ": "ğ", "Ü": "ü", "Ö": "ö", "Ç": "ç"})
_UPPER = str.maketrans({"ı": "I", "i": "İ", "ş": "Ş", "ğ": "Ğ", "ü": "Ü", "ö": "Ö", "ç": "Ç"})


def tr_title(text: str) -> str:
    words = []
    for word in text.strip().split():
        lowered = word.translate(_LOWER).lower()
        words.append(lowered[:1].translate(_UPPER).upper() + lowered[1:] if lowered else "")
    return " ".join(words)


LANDMARKS = [
    ("Taksim Meydanı", 41.0370, 28.9850, "Beyoğlu"),
    ("Sultanahmet", 41.0055, 28.9769, "Fatih"),
    ("Galata Kulesi", 41.0256, 28.9744, "Beyoğlu"),
    ("Kadıköy İskele", 40.9908, 29.0233, "Kadıköy"),
    ("Beşiktaş İskele", 41.0422, 29.0053, "Beşiktaş"),
    ("Üsküdar İskele", 41.0256, 29.0152, "Üsküdar"),
    ("Eminönü", 41.0175, 28.9707, "Fatih"),
    ("Bakırköy Çarşı", 40.9800, 28.8720, "Bakırköy"),
    ("Maslak", 41.1100, 29.0200, "Sarıyer"),
    ("Levent", 41.0820, 29.0100, "Beşiktaş"),
    ("Ataşehir", 40.9920, 29.1270, "Ataşehir"),
    ("Bebek", 41.0770, 29.0430, "Beşiktaş"),
    ("Moda", 40.9810, 29.0260, "Kadıköy"),
    ("Nişantaşı", 41.0480, 28.9940, "Şişli"),
    ("Ortaköy", 41.0475, 29.0270, "Beşiktaş"),
]


def main() -> int:
    rows: dict[tuple[str, str], dict] = {}

    def add(name: str | None, lat: float | None, lon: float | None, kind: str, district: str = "") -> None:
        name = (name or "").strip()
        if not name or lat is None or lon is None:
            return
        rows.setdefault(
            (name.casefold(), kind),
            {"name": name, "lat": round(float(lat), 6), "lon": round(float(lon), 6), "kind": kind, "district": district.strip()},
        )

    for station in json.loads((FIXTURES / "metro_stations.json").read_text(encoding="utf-8"))["Data"]:
        detail = station.get("DetailInfo") or {}
        add(
            station.get("Description") or station.get("Name"),
            repair_coordinate(detail.get("Latitude"), "lat"),
            repair_coordinate(detail.get("Longitude"), "lon"),
            "metro_station",
        )

    for station in json.loads((FIXTURES / "aq_stations.json").read_text(encoding="utf-8")):
        lat, lon = parse_wkt_point(station.get("Location"))
        add(station.get("Name"), lat, lon, "aq_station")

    by_district: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for lot in json.loads((FIXTURES / "ispark_park.json").read_text(encoding="utf-8")):
        lat = repair_coordinate(lot.get("lat"), "lat")
        lon = repair_coordinate(lot.get("lng"), "lon")
        if lat and lon and lot.get("district"):
            by_district[tr_title(lot["district"])].append((lat, lon))
    for district, points in by_district.items():
        add(district, sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points), "district", district)

    for name, lat, lon, district in LANDMARKS:
        add(name, lat, lon, "landmark", district)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["name", "lat", "lon", "kind", "district"])
        writer.writeheader()
        for row in sorted(rows.values(), key=lambda r: (r["kind"], r["name"])):
            writer.writerow(row)

    print(f"{len(rows)} places -> {OUT.relative_to(ROOT)}")
    print(dict(Counter(r["kind"] for r in rows.values())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
