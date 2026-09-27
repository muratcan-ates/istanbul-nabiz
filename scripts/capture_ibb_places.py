"""E79 prerequisite: four İBB open data place lists as slim JSON (data/reference/ibb_places/<category>.json).

Stdlib only; robots.txt + the catalog's four download URLs, 10 s apart (Crawl-Delay: 10), never /api/.
Keeps name, district, address, lat, lon; drops every other column. A failed category is written as "veri_alinamadi".
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import urlsplit

UA, HOST, DELAY_S, MAX_BYTES, MAX_FILE = "istanbul-nabiz-ogrenci-projesi/1", "data.ibb.gov.tr", 10, 30_000_000, 1_500_000
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reference" / "ibb_places"
LAT, LON = (40.7, 41.7), (27.9, 29.95)  # same box as ibb_mcp.models LAT_RANGE / LON_RANGE
LICENSE, LICENSE_URL = "İBB Açık Veri Lisansı", "https://data.ibb.gov.tr/license"
#: category -> (dataset, title, dataset id, resource id, file, resource last_modified in the 26 Sep 2026 catalog)
SOURCES = {
    "halk_ekmek": ("istanbul-halk-ekmek-bufe-konumlari-veri-seti", "İstanbul Halk Ekmek Büfelerinin Konumları Veri Seti",
                   "bfb0d3b2-dedb-4efe-a767-34d6d14ee2e0", "c94de59a-6f4e-4cf3-90d2-2aeb33b2489f",
                   "ihe-bufe-konumlar_2025.xlsx", "2026-02-10T11:19:59+00:00"),
    "kent_lokantasi": ("kent-lokantalari-konumlari", "Kent Lokantaları Konumları", "8f9c7ad2-9fc2-4f7a-ad59-a8c6fc9a2489",
                       "1e4ffc84-f727-4c38-be17-31149bea1452", "kent-lokantalar-lokasyon.xlsx", "2026-04-03T12:51:02+00:00"),
    "sosyal_tesis": ("sosyal-tesis-konumlari", "Sosyal Tesis Konumları", "6e9b0cf3-d756-4301-8c5e-a6e3a223ed6d",
                     "87517b4e-28b5-478f-a0ba-27291cf17b69", "ibb-sosyal-tesis-konumlar.xlsx", "2026-04-06T08:28:16+00:00"),
    "wifi": ("ibb-wi-fi-lokasyon", "IMM WiFi Location Data (ibbWiFi Lokasyonları)", "e6810baa-4f41-489d-8d97-42a957fcae49",
             "5d0a0b1e-9e56-4038-b966-7d3e7b46f882", "ibb_wifi_location.csv", "2023-03-15T21:11:55+00:00"),
}
FIELDS = {  # folded header names, first match wins
    "lat": ("enlem", "latitude", "lat", "y"), "lon": ("boylam", "longitude", "lon", "lng", "long", "x"),
    "coord": ("koordinat", "koordinatlar", "konum", "geometry", "geom", "wkt"),
    "district": ("ilce", "ilceadi", "district"), "address": ("adres", "address", "acikadres", "mahalle", "mahalleadi"),
    "name": ("ad", "adi", "isim", "name", "bufeadi", "tesisadi", "lokantaadi", "lokasyonadi", "lokasyon", "tesis",
             "subeadi", "konumadi", "alanadi", "mekanadi", "location"),
}
PII = re.compile(r"@|(?<!\d)\d{11}(?!\d)|(?:\+?90|0)\s*5\d{2}\s*\d{3}\s*\d{2}\s*\d{2}")
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_requests = 0


def fold(text: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).translate(str.maketrans("çğıöşüÇĞİÖŞÜI", "cgiosucgiosui")).lower())


def fetch(url: str) -> tuple[int, bytes, dict]:
    global _requests
    if urlsplit(url).hostname != HOST or "/api/" in url:
        sys.exit(f"DUR: izin verilmeyen adres {url}")
    if _requests:
        time.sleep(DELAY_S)  # robots.txt Crawl-Delay: 10
    _requests += 1
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as resp:
            body = resp.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES or urlsplit(resp.geturl()).hostname != HOST:
                return 0, b"", {"error": "dosya çok büyük ya da başka hosta yönlendi"}
            return resp.status, body, {"last_modified": resp.headers.get("Last-Modified")}
    except urllib.error.HTTPError as exc:
        return exc.code, b"", {}
    except (urllib.error.URLError, TimeoutError) as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            sys.exit("DUR: sertifika hatası; betiği .venv/bin/python ile koşun.")
        return 0, b"", {"error": str(exc)[:160]}


def robots() -> urllib.robotparser.RobotFileParser:
    sys.path.insert(0, str(ROOT / "src"))
    from ibb_mcp.knowledge.guardrails import host_allowed

    if not host_allowed(HOST):
        sys.exit(f"DUR: {HOST} allowlist'te değil.")
    status, body, _ = fetch(f"https://{HOST}/robots.txt")
    if status != 200:
        sys.exit(f"DUR: robots.txt {status}; indirme yapılmadı.")
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(body.decode("utf-8", "replace").splitlines())
    if (parser.crawl_delay(UA) or 0) > DELAY_S:
        sys.exit(f"DUR: Crawl-Delay {parser.crawl_delay(UA)} sn oldu; kural değişti, Claude'a haber verin.")
    return parser


def xlsx_rows(body: bytes) -> list[list[str]]:
    book, shared, rows = zipfile.ZipFile(io.BytesIO(body)), [], []
    if "xl/sharedStrings.xml" in book.namelist():
        strings = ET.fromstring(book.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in si.iter(M + "t")) for si in strings.iter(M + "si")]
    sheet = sorted(n for n in book.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))[0]
    for row in ET.fromstring(book.read(sheet)).iter(M + "row"):
        cells = {}
        for index, cell in enumerate(row.iter(M + "c")):
            ref, value = re.match(r"[A-Z]+", cell.get("r", "")), cell.find(M + "v")
            col = sum((ord(ch) - 64) * 26**i for i, ch in enumerate(reversed(ref.group(0)))) - 1 if ref else index
            text = value.text or "" if value is not None else ""
            cells[col] = shared[int(text)] if cell.get("t") == "s" and text else text
            if cell.get("t") == "inlineStr":
                cells[col] = "".join(t.text or "" for t in cell.iter(M + "t"))
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return rows


def csv_rows(body: bytes) -> list[list[str]]:
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = body.decode("cp1254", "replace")
    delimiter = max(",;\t|", key=(text.splitlines() or [""])[0].count)
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter) if any(c.strip() for c in row)]


def columns(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    names = {n for group in FIELDS.values() for n in group}
    start = max(range(min(10, len(rows))), key=lambda i: sum(fold(c) in names for c in rows[i]), default=0)
    folded, found = [fold(h) for h in (rows[start] if rows else [])], {}
    for field, candidates in FIELDS.items():
        hit = next((folded.index(n) for n in candidates if n in folded), None)
        if hit is not None and hit not in found.values():
            found[field] = hit
    if "lat" in found and "lon" not in found:  # Kent Lokantası / Sosyal Tesis files say "Latitude" twice
        twin = [i for i, h in enumerate(folded) if h == folded[found["lat"]] and i != found["lat"]]
        if twin:
            found["lon"] = twin[0]  # place() accepts either order inside the Istanbul box
    person = ("ilce", "mahalle", "bayi", "sahib", "isletmeci", "yetkili", "sorumlu")  # never a person's name column
    guess = [i for i, h in enumerate(folded) if h.endswith("adi") and not any(p in h for p in person)]
    return start, found | ({"name": guess[0]} if "name" not in found and guess else {})


def number(text: str) -> float | None:
    text = str(text).strip().replace(" ", "")
    try:
        return float(text.replace(",", ".") if text.count(",") == 1 and "." not in text else text)
    except ValueError:
        return None


def descale(value: float) -> float:
    """41012345 or 4101234567 (a degree written without its decimal point) back to 41.012345."""
    while abs(value) > 180:
        value /= 10
    return value


def place(row: list[str], cols: dict[str, int]) -> tuple[float, float] | str:
    cell = lambda f: row[cols[f]] if f in cols and cols[f] < len(row) else ""  # noqa: E731
    pair = [number(cell("lat")), number(cell("lon"))] if "lat" in cols and "lon" in cols else \
        ([number(n) for n in re.findall(r"-?\d+(?:[.,]\d+)?", cell("coord"))] + [None, None])[:2]
    if None in pair:
        return "no_coordinate"
    pair = [descale(v) for v in pair]
    for lat, lon in (pair, pair[::-1]):  # a swapped pair (or WKT "POINT (lon lat)") is accepted
        if LAT[0] <= lat <= LAT[1] and LON[0] <= lon <= LON[1]:
            return round(lat, 5), round(lon, 5)
    return "outside_istanbul"


def slim(rows: list[list[str]], cols: dict[str, int]) -> tuple[list[list], dict[str, int]]:
    stats, out, seen = {"no_coordinate": 0, "outside_istanbul": 0, "pii_blanked": 0, "duplicate": 0}, [], set()
    for row in rows:
        where = place(row, cols)
        if isinstance(where, str):
            stats[where] += 1
            continue
        texts = [" ".join(str(row[cols[f]]).split())[:n] if f in cols and cols[f] < len(row) else ""
                 for f, n in (("name", 120), ("district", 40), ("address", 200))]
        stats["pii_blanked"] += sum(bool(PII.search(t)) for t in texts)
        texts = ["" if PII.search(t) else t for t in texts]
        key = (texts[0].casefold(), *where)
        stats["duplicate"] += key in seen
        if texts[0] and key not in seen:
            seen.add(key)
            out.append([*texts, *where])
    return out, stats


def capture(category: str, parser: urllib.robotparser.RobotFileParser) -> dict:
    dataset, title, dataset_id, resource_id, file, modified = SOURCES[category]
    url = f"https://{HOST}/dataset/{dataset_id}/resource/{resource_id}/download/{file}"
    record = {"schema": 1, "category": category, "title": title, "dataset_url": f"https://{HOST}/dataset/{dataset}",
              "resource_url": url, "resource_format": file.rsplit(".", 1)[1].upper(), "resource_last_modified": modified,
              "license": LICENSE, "license_url": LICENSE_URL, "columns": ["name", "district", "address", "lat", "lon"],
              "rows": [], "count": 0}
    fail = lambda reason: record | {"status": "veri_alinamadi", "reason": reason}  # noqa: E731
    if not parser.can_fetch(UA, url):
        return fail("robots.txt bu adrese izin vermiyor")
    status, body, meta = fetch(url)
    record |= {"captured_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "http_status": status,
               "http_last_modified": meta.get("last_modified")}
    if status != 200 or not body:
        return fail(f"indirilemedi (HTTP {status}) {meta.get('error') or ''}".strip())
    try:
        table = xlsx_rows(body) if file.endswith(".xlsx") else csv_rows(body)
    except (zipfile.BadZipFile, ET.ParseError, IndexError, KeyError, ValueError) as exc:
        return fail(f"dosya okunamadı ({type(exc).__name__})")
    start, cols = columns(table)
    header = table[start] if table else []
    record |= {"sha256": hashlib.sha256(body).hexdigest(), "bytes_raw": len(body), "header": header,
               "columns_used": {k: header[v] for k, v in cols.items()}, "rows_in_file": max(0, len(table) - start - 1)}
    if "name" not in cols or not ({"lat", "lon"} <= cols.keys() or "coord" in cols):
        return fail("sütunlar tanınmadı; başlık satırı 'header' alanında")
    rows, stats = slim(table[start + 1:], cols)
    record |= {"rows": rows, "count": len(rows), "dropped": stats}
    if len(json.dumps(rows, ensure_ascii=False)) > MAX_FILE:
        record |= {"rows": [[n, d, "", la, lo] for n, d, _, la, lo in rows], "slimmed": "adres atıldı (1,5 MB üstü)"}
    if not rows:  # show the raw coordinate cells (facility locations, no personal data) so the next fix is not a guess
        where = sorted({cols[f] for f in ("lat", "lon", "coord") if f in cols})
        raw = [[r[i] if i < len(r) else "" for i in where] for r in table[start + 1:start + 4]]
        return fail("İstanbul kutusunda koordinatlı satır yok") | {"raw_sample": raw}
    return record | {"status": "alindi", "reason": None}


def main() -> None:
    parser = robots()
    OUT.mkdir(parents=True, exist_ok=True)
    for category in SOURCES:
        record, path = capture(category, parser), OUT / f"{category}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        reason = f"; {record['reason']}" if record.get("reason") else ""
        print(f"{category}: {record['status']}; {record['count']} nokta; {path.stat().st_size // 1024} KB{reason}")
        sample = [row[0] for row in record["rows"][:3]]
        raw = f"; ham koordinat {record['raw_sample']}" if record.get("raw_sample") else ""
        print(f"  sütunlar {record.get('columns_used')}; atılan {record.get('dropped')}; örnek {sample}{raw}")
    print(f"istek: {_requests} (robots.txt + 4 indirme), aralarda {DELAY_S} sn")


if __name__ == "__main__":
    main()
