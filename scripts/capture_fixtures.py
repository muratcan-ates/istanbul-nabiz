#!/usr/bin/env python3
"""Capture real İBB API responses as test fixtures.

Politeness rules (see PLAN.md 4.1):
  * >= 7 s between calls to api.ibb.gov.tr (gateway 503s after ~15 rapid calls)
  * at most 3 calls to the İETT SOAP service (documented 100 requests/hour)

Run once; fixtures land in tests/fixtures/ and a report in tests/fixtures/_capture_report.json.
"""

from __future__ import annotations

import gzip
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
UA = "istanbul-nabiz/0.1 (open-data client; contact: github.com/muratcanates)"

report: list[dict] = []
_last_gateway_call = 0.0


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
        parsed = json.loads(body)
    except Exception as exc:  # noqa: BLE001
        (FIX / f"{name}.raw").write_bytes(body)
        print(f"  ! {name}: not JSON ({exc}); saved raw")
        return None
    trimmed = parsed[:limit] if limit and isinstance(parsed, list) else parsed
    path = FIX / f"{name}.json"
    path.write_text(json.dumps(trimmed, ensure_ascii=False, indent=1), encoding="utf-8")
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
    text = raw.decode("utf-8", "replace")
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
    soap("iett_hat_500T", "GetHatOtoKonum_json", "<GetHatOtoKonum_json xmlns='http://tempuri.org/'><HatKodu>500T</HatKodu></GetHatOtoKonum_json>")
    soap("iett_fleet", "GetFiloAracKonum_json", "<GetFiloAracKonum_json xmlns='http://tempuri.org/' />", limit=60)

    print("İETT planlanan sefer (shape unverified in PLAN 4.1)")
    plan_env = "<GetPlanlananSeferSaati_json xmlns='http://tempuri.org/'><HatKodu>500T</HatKodu></GetPlanlananSeferSaati_json>"
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
        text = raw.decode("utf-8", "replace")
        (FIX / "iett_planlanan.soap.xml").write_text(text[:4000], encoding="utf-8")
        m = re.search(r"<GetPlanlananSeferSaati_jsonResult>(.*?)</GetPlanlananSeferSaati_jsonResult>", text, re.S)
        if m:
            save_json("iett_planlanan", html.unescape(m.group(1)).encode(), limit=40)
        else:
            print("  ! no result element; check WSDL parameter name")

    print("Metro İstanbul")
    save_json("metro_status", fetch("metro_status", "https://api.ibb.gov.tr/MetroIstanbul/api/MetroMobile/V2/GetServiceStatuses") or b"{}")
    save_json("metro_stations", fetch("metro_stations", "https://api.ibb.gov.tr/MetroIstanbul/api/MetroMobile/V2/GetStations") or b"{}")

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
    stations = save_json("aq_stations", fetch("aq_stations", "https://api.ibb.gov.tr/havakalitesi/OpenDataPortalHandler/GetAQIStations") or b"[]")
    if isinstance(stations, list) and stations:
        sid = stations[0]["Id"]
        end = time.strftime("%d.%m.%Y %H:00:00")
        start = time.strftime("%d.%m.%Y %H:00:00", time.localtime(time.time() - 3 * 86400))
        url = (
            "https://api.ibb.gov.tr/havakalitesi/OpenDataPortalHandler/GetAQIByStationId"
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
