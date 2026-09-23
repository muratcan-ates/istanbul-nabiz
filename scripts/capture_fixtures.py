#!/usr/bin/env python3
"""Capture real İBB API responses as test fixtures.

Politeness rules (see PLAN.md 4.1):
  * >= 7 s between calls to api.ibb.gov.tr (gateway 503s after ~15 rapid calls)
  * at most 3 calls to the İETT SOAP service (documented 100 requests/hour)

Privacy rule (NOTICE.md, DECISIONS.md §7):
  * the İETT fleet feed ships every bus's number plate (``Plaka``); the repository is
    public, so each plate is swapped for a synthetic ``00 XX 001``, ``00 XX 002``, ...
    before anything is written. Province code 00 does not exist, so a fixture plate can
    never be a real vehicle, and a CI guardrail can require the ``00 `` prefix.

Run once; fixtures land in tests/fixtures/ and a report in tests/fixtures/_capture_report.json.
"""

from __future__ import annotations

import html
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
FIX.mkdir(parents=True, exist_ok=True)

GATEWAY_GAP_S = 7.0
TIMEOUT_S = 60
UA = "istanbul-nabiz/0.1 (+https://github.com/muratcan-ates/istanbul-nabiz) open-data client"

report: list[dict] = []
_last_gateway_call = 0.0

#: Real plate -> synthetic plate for this run. One table for the whole capture so the
#: same bus gets the same stand-in in the ``.soap.xml`` and in the ``.json`` cut from it
#: (``test_http_cache`` asserts the two agree record for record).
_synthetic_plates: dict[str, str] = {}

#: Words that make a field a plate field. Matched per word of the key, so a renamed
#: upstream field (``AracPlaka``, ``plate_no``) is still scrubbed while ``template`` and
#: ``boilerplate`` are left alone.
_PLATE_WORDS = {"plaka", "plate", "plates", "numberplate"}
_KEY_WORDS = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")

#: Any string-valued key in raw JSON (``"Plaka":"..."``), in the HTML-escaped JSON some
#: SOAP bodies use (``&quot;Plaka&quot;:&quot;...``), and any plain XML element
#: (``<Plaka>...</Plaka>``). ``swap`` decides per key whether the value is a plate.
_KEYED_VALUE = re.compile(
    r'(?P<head>(?:"|&quot;)(?P<key>[A-Za-z_]+)(?:"|&quot;)\s*:\s*(?:"|&quot;))(?P<value>[^"&<]*)'
    r"|(?P<open><(?P<tag>[A-Za-z_]+)>)(?P<xml>[^<]*)(?=</)"
)

#: What a Turkish plate looks like when it turns up somewhere unexpected: two digits,
#: one to three letters, two to five digits. The lookarounds keep ISO timestamps
#: (``2026-09-05T09:00``) out; ``00`` is our own synthetic prefix.
_PLATE_SHAPED = re.compile(r"(?<![\d-])(?!00 )\d{2} ?[A-ZÇĞİÖŞÜ]{1,3} ?\d{2,5}(?![\d:])")


def is_plate_key(key: str) -> bool:
    return any(word.lower() in _PLATE_WORDS for word in _KEY_WORDS.findall(key))


def synthetic_plate(real: str) -> str:
    """Stable stand-in for ``real`` within this run; already-synthetic or empty values pass."""
    if not real or real.startswith("00 "):
        return real
    return _synthetic_plates.setdefault(real, f"00 XX {len(_synthetic_plates) + 1:03d}")


def scrub_plates_in_text(text: str) -> str:
    """Swap every plate value in a raw response body, before any byte of it is written."""

    def swap(m: re.Match[str]) -> str:
        if m.group("head") is not None:
            return m.group("head") + synthetic_plate(m.group("value")) if is_plate_key(m.group("key")) else m.group(0)
        return m.group("open") + synthetic_plate(m.group("xml")) if is_plate_key(m.group("tag")) else m.group(0)

    return _KEYED_VALUE.sub(swap, text)


def scrub_plates(value: object) -> object:
    """Same swap on parsed JSON, for payloads whose plates were escaped past the text pass."""
    if isinstance(value, list):
        return [scrub_plates(item) for item in value]
    if isinstance(value, dict):
        return {
            key: synthetic_plate(item) if isinstance(item, str) and is_plate_key(key) else scrub_plates(item)
            for key, item in value.items()
        }
    return value


def warn_if_plate_shaped(name: str, text: str) -> None:
    """A plate under a key we did not anticipate still reads like a plate; say so loudly."""
    hits = sorted(set(_PLATE_SHAPED.findall(text)))
    if hits:
        print(f"  ! {name}: plate-shaped values survived the scrub, check before committing: {hits[:5]}")


def _sleep_for_gateway(url: str) -> None:
    global _last_gateway_call
    if "api.ibb.gov.tr" not in url:
        return
    wait = GATEWAY_GAP_S - (time.monotonic() - _last_gateway_call)
    if wait > 0:
        time.sleep(wait)
    _last_gateway_call = time.monotonic()


def fetch(name: str, url: str, *, data: bytes | None = None, headers: dict | None = None) -> bytes | None:
    _sleep_for_gateway(url)
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            body = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        body, status = exc.read(), exc.code
    except Exception as exc:  # noqa: BLE001
        report.append({"name": name, "url": url, "error": repr(exc)})
        print(f"  {name:28s} ERROR {exc!r}")
        return None
    dt = time.monotonic() - t0
    report.append({"name": name, "url": url, "status": status, "bytes": len(body), "seconds": round(dt, 2)})
    print(f"  {name:28s} http={status} bytes={len(body):>9,} {dt:5.2f}s")
    return body if status == 200 else None


def save_json(name: str, body: bytes, *, limit: int | None = None) -> object | None:
    try:
        parsed = scrub_plates(json.loads(body))
    except Exception as exc:  # noqa: BLE001
        raw = scrub_plates_in_text(body.decode("utf-8", "replace"))
        warn_if_plate_shaped(name, raw)
        (FIX / f"{name}.raw").write_text(raw, encoding="utf-8")
        print(f"  ! {name}: not JSON ({exc}); saved raw")
        return None
    trimmed = parsed[:limit] if limit and isinstance(parsed, list) else parsed
    path = FIX / f"{name}.json"
    text = json.dumps(trimmed, ensure_ascii=False, indent=1)
    warn_if_plate_shaped(name, text)
    path.write_text(text, encoding="utf-8")
    n = len(parsed) if isinstance(parsed, list) else 1
    kept = len(trimmed) if isinstance(trimmed, list) else 1
    print(f"    -> {path.name} ({kept}/{n} records)")
    return parsed


def soap(name: str, action: str, body_xml: str, *, limit: int | None = None) -> object | None:
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<soap:Body>{body_xml}</soap:Body></soap:Envelope>"
    ).encode()
    raw = fetch(
        name,
        "https://api.ibb.gov.tr/iett/FiloDurum/SeferGerceklesme.asmx",
        data=envelope,
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"http://tempuri.org/{action}"'},
    )
    if raw is None:
        return None
    # Scrub the whole body first: the .soap.xml keeps only its first 4 KB, and the JSON
    # fixture is extracted from the same text, so both must see the same stand-ins.
    text = scrub_plates_in_text(raw.decode("utf-8", "replace"))
    warn_if_plate_shaped(f"{name}.soap.xml", text[:4000])
    (FIX / f"{name}.soap.xml").write_text(text[:4000], encoding="utf-8")
    match = re.search(rf"<{action}Result>(.*?)</{action}Result>", text, re.S)
    if not match:
        print(f"  ! {name}: no <{action}Result> element")
        return None
    return save_json(name, html.unescape(match.group(1)).encode(), limit=limit)


def main() -> int:
    print("İSPARK")
    parks = save_json("ispark_park", fetch("ispark_park", "https://api.ibb.gov.tr/ispark/Park") or b"[]", limit=40)
    park_id = None
    if isinstance(parks, list) and parks:
        with_free = [p for p in parks if str(p.get("emptyCapacity", "0")) not in ("0", "", "None")]
        park_id = (with_free or parks)[0].get("parkID")
    if park_id:
        save_json("ispark_parkdetay", fetch("ispark_parkdetay", f"https://api.ibb.gov.tr/ispark/ParkDetay?id={park_id}") or b"[]")

    print("İETT (max 3 SOAP calls)")
    soap(
        "iett_hat_500T",
        "GetHatOtoKonum_json",
        "<GetHatOtoKonum_json xmlns='http://tempuri.org/'><HatKodu>500T</HatKodu></GetHatOtoKonum_json>",
    )
    soap(
        "iett_fleet",
        "GetFiloAracKonum_json",
        "<GetFiloAracKonum_json xmlns='http://tempuri.org/' />",
        limit=60,
    )

    print("İETT planlanan sefer (shape unverified in PLAN 4.1)")
    plan_env = (
        "<GetPlanlananSeferSaati_json xmlns='http://tempuri.org/'>"
        "<HatKodu>500T</HatKodu></GetPlanlananSeferSaati_json>"
    )
    raw = fetch(
        "iett_planlanan",
        "https://api.ibb.gov.tr/iett/UlasimAnaVeri/PlanlananSeferSaati.asmx",
        data=(
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            f"<soap:Body>{plan_env}</soap:Body></soap:Envelope>"
        ).encode(),
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '"http://tempuri.org/GetPlanlananSeferSaati_json"'},
    )
    if raw:
        text = scrub_plates_in_text(raw.decode("utf-8", "replace"))
        warn_if_plate_shaped("iett_planlanan.soap.xml", text[:4000])
        (FIX / "iett_planlanan.soap.xml").write_text(text[:4000], encoding="utf-8")
        m = re.search(r"<GetPlanlananSeferSaati_jsonResult>(.*?)</GetPlanlananSeferSaati_jsonResult>", text, re.S)
        if m:
            save_json("iett_planlanan", html.unescape(m.group(1)).encode(), limit=40)
        else:
            print("  ! no result element; check WSDL parameter name")

    print("Metro İstanbul")
    metro_base = "https://api.ibb.gov.tr/MetroIstanbul/api/MetroMobile/V2"
    save_json("metro_status", fetch("metro_status", f"{metro_base}/GetServiceStatuses") or b"{}")
    save_json("metro_stations", fetch("metro_stations", f"{metro_base}/GetStations") or b"{}")

    print("Trafik indeksi (Accept: application/json şart, yoksa XML döner)")
    save_json(
        "traffic_index_1h",
        fetch(
            "traffic_index_1h",
            "https://api.ibb.gov.tr/tkmservices/api/TrafficData/v1/TrafficIndexHistory/1/H",
            headers={"Accept": "application/json"},
        )
        or b"[]",
    )

    print("Hava kalitesi")
    aq_base = "https://api.ibb.gov.tr/havakalitesi/OpenDataPortalHandler"
    stations = save_json("aq_stations", fetch("aq_stations", f"{aq_base}/GetAQIStations") or b"[]")
    if isinstance(stations, list) and stations:
        sid = stations[0]["Id"]
        end = time.strftime("%d.%m.%Y %H:00:00")
        start = time.strftime("%d.%m.%Y %H:00:00", time.localtime(time.time() - 3 * 86400))
        url = (
            f"{aq_base}/GetAQIByStationId"
            f"?StationId={sid}&StartDate={urllib.parse.quote(start)}&EndDate={urllib.parse.quote(end)}"
        )
        save_json("aq_readings", fetch("aq_readings", url) or b"[]")

    print("GTFS resource URLs (CKAN, separate host)")
    pkg = fetch("gtfs_package", "https://data.ibb.gov.tr/api/3/action/package_show?id=iett-gtfs-verisi")
    if pkg:
        meta = json.loads(pkg)
        resources = [
            {"name": r.get("name"), "format": r.get("format"), "size": r.get("size"), "url": r.get("url")}
            for r in meta.get("result", {}).get("resources", [])
        ]
        (FIX / "gtfs_resources.json").write_text(json.dumps(resources, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"    -> gtfs_resources.json ({len(resources)} resources)")

    (FIX / "_capture_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for r in report if r.get("status") == 200)
    print(f"\n{ok}/{len(report)} calls returned HTTP 200 -> tests/fixtures/_capture_report.json")
    return 0


if __name__ == "__main__":
    import urllib.parse  # noqa: E402  (used in main)

    sys.exit(main())
