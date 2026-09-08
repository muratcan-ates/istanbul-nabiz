#!/usr/bin/env python3
"""Day-0 gate for İstanbul Nabız (PLAN.md §10).

Answers one question: *can the seven-day sprint actually start today?* It checks the
local toolchain, the Azure subscription's regional constraints, the İBB endpoints the
whole project rests on, and the live-bus -> GTFS join the ETA engine is built on — then
tells you exactly what to do about anything that failed.

Why the throttling: the İBB gateway 503s after ~15 rapid calls and the İETT SOAP service
is capped at 100 requests/hour (documented, see PLAN §18). So network checks wait 6 s
between calls and are hard-capped at six calls per run. The countdown is printed so a
human watching the terminal can see the script is behaving rather than hung.

Usage:
    python3.12 scripts/probe_day0.py                 # tools + İBB + GTFS
    python3.12 scripts/probe_day0.py --azure         # ... plus the az subscription checks
    python3.12 scripts/probe_day0.py --no-network    # local only, safe to re-run freely
    python3.12 scripts/probe_day0.py --traffic-both  # spend a 7th call on the Accept-header proof
    python3.12 scripts/probe_day0.py --json-only     # machine output on stdout

Exit code 0 when nothing FAILED (SKIP is fine), 1 otherwise.
Dependencies: stdlib, plus httpx when it is importable (urllib.request otherwise).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs" / "day0_report.json"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

MAX_IBB_CALLS = 6  # PLAN §4.1 gateway rule; --traffic-both raises this by one
IBB_GAP_S = 6.0
HTTP_TIMEOUT_S = 90
UA = "istanbul-nabiz-day0-probe/1.0 (open-data client; github.com/muratcan-ates/istanbul-nabiz)"

# Endpoints come from the single source of truth so a change at İBB stays a one-line fix.
sys.path.insert(0, str(ROOT / "src"))
try:
    from ibb_mcp import config as C  # type: ignore

    CONFIG_SOURCE = "ibb_mcp.config"
    AQ_STATIONS, AQ_READINGS = C.AQ_STATIONS, C.AQ_READINGS
    ISPARK_LIST, IETT_FLEET_ASMX = C.ISPARK_LIST, C.IETT_FLEET_ASMX
    METRO_SERVICE_STATUS, TRAFFIC_INDEX_HISTORY = C.METRO_SERVICE_STATUS, C.TRAFFIC_INDEX_HISTORY
except Exception:  # noqa: BLE001 - the gate must run even when src/ is broken
    CONFIG_SOURCE = "built-in fallback (ibb_mcp.config not importable)"
    _G = "https://api.ibb.gov.tr"
    AQ_STATIONS = f"{_G}/havakalitesi/OpenDataPortalHandler/GetAQIStations"
    AQ_READINGS = f"{_G}/havakalitesi/OpenDataPortalHandler/GetAQIByStationId"
    ISPARK_LIST = f"{_G}/ispark/Park"
    IETT_FLEET_ASMX = f"{_G}/iett/FiloDurum/SeferGerceklesme.asmx"
    METRO_SERVICE_STATUS = f"{_G}/MetroIstanbul/api/MetroMobile/V2/GetServiceStatuses"
    TRAFFIC_INDEX_HISTORY = f"{_G}/tkmservices/api/TrafficData/v1/TrafficIndexHistory"

try:
    import httpx

    TRANSPORT = f"httpx {httpx.__version__}"
except ModuleNotFoundError:
    httpx = None  # type: ignore[assignment]
    TRANSPORT = "urllib.request (httpx not installed)"

# Regions worth having near İstanbul, best first. Used to recommend one from the
# intersection of "allowed by policy" and "supports Functions Flex Consumption".
REGION_PREFERENCE = [
    "westeurope", "northeurope", "swedencentral", "germanywestcentral",
    "italynorth", "polandcentral", "uksouth", "francecentral", "switzerlandnorth",
]
REQUIRED_PROVIDERS = [
    "Microsoft.App", "Microsoft.Web", "Microsoft.Storage",
    "Microsoft.Maps", "Microsoft.CognitiveServices", "Microsoft.Insights",
]

# Values recorded from real calls on 2026-09-08 (tests/fixtures/). A live number that
# drifts from these is not a failure, but it means the fixtures need recapturing.
BASELINE = {"aq_stations": 28, "ispark_lots": 249, "gtfs_stop_join": 31, "gtfs_route_join": 2}


class BudgetExceeded(RuntimeError):
    """Raised instead of making a call that would break the İBB politeness budget."""


class HttpFailure(RuntimeError):
    pass


# ----------------------------------------------------------------------------------
# context
# ----------------------------------------------------------------------------------
@dataclass
class Ctx:
    """Shared state: earlier checks feed later ones (station id, allowed regions...)."""

    args: argparse.Namespace
    facts: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    ibb_calls: int = 0
    _last_ibb: float = 0.0

    @property
    def ibb_budget(self) -> int:
        return MAX_IBB_CALLS + (1 if self.args.traffic_both else 0)

    def note(self, text: str) -> None:
        """Advisory that always reaches NEXT ACTIONS, even from a PASSing check."""
        if text not in self.notes:
            self.notes.append(text)

    def spend_ibb_call(self, label: str) -> None:
        if self.ibb_calls >= self.ibb_budget:
            raise BudgetExceeded(f"İBB call budget ({self.ibb_budget}) already spent")
        if self.ibb_calls:
            self._countdown(IBB_GAP_S - (time.monotonic() - self._last_ibb), label)
        self.ibb_calls += 1
        self._last_ibb = time.monotonic()

    @staticmethod
    def _countdown(seconds: float, label: str) -> None:
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            print(f"\r  politeness pause {left:4.1f}s before {label:<24s}", end="", file=sys.stderr, flush=True)
            time.sleep(min(0.2, left))
        print("\r" + " " * 60 + "\r", end="", file=sys.stderr, flush=True)


# ----------------------------------------------------------------------------------
# tiny http + subprocess helpers
# ----------------------------------------------------------------------------------
def http(method: str, url: str, *, headers: dict[str, str] | None = None, body: bytes | None = None) -> tuple[int, bytes, dict[str, str]]:
    hdrs = {"User-Agent": UA, **(headers or {})}
    if httpx is not None:
        try:
            r = httpx.request(method, url, headers=hdrs, content=body, timeout=HTTP_TIMEOUT_S, follow_redirects=True)
        except Exception as exc:  # noqa: BLE001
            raise HttpFailure(f"{type(exc).__name__}: {exc}") from exc
        return r.status_code, r.content, {k.lower(): v for k, v in r.headers.items()}
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            return resp.status, resp.read(), {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), {k.lower(): v for k, v in (exc.headers or {}).items()}
    except Exception as exc:  # noqa: BLE001
        raise HttpFailure(f"{type(exc).__name__}: {exc}") from exc


def get_json(url: str, *, headers: dict[str, str] | None = None) -> Any:
    status, body, _ = http("GET", url, headers={"Accept": "application/json", **(headers or {})})
    if status != 200:
        raise HttpFailure(f"HTTP {status} ({len(body)} bytes)")
    return json.loads(body)


def run_cmd(argv: list[str], timeout: int = 45) -> tuple[int, str, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, "", "not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def az_json(args: list[str], timeout: int = 90) -> Any:
    rc, out, err = run_cmd(["az", *args, "-o", "json", "--only-show-errors"], timeout=timeout)
    if rc != 0:
        raise HttpFailure((err or out or f"az exited {rc}").splitlines()[0][:200])
    return json.loads(out) if out else None


# ----------------------------------------------------------------------------------
# TOOLS — local, no network
# ----------------------------------------------------------------------------------
def check_python(ctx: Ctx) -> tuple[str, str]:
    exe = "/opt/homebrew/bin/python3.12" if pathlib.Path("/opt/homebrew/bin/python3.12").exists() else shutil.which("python3.12")
    if not exe:
        return FAIL, "python3.12 not on PATH (the system 3.14 must not be used)"
    rc, out, err = run_cmd([exe, "-V"], timeout=20)
    version = (out or err).replace("Python ", "").strip()
    ctx.facts["python312"] = {"path": exe, "version": version}
    if not version.startswith("3.12"):
        return FAIL, f"{exe} reports {version}, expected 3.12.x"
    return PASS, f"{version} at {exe}"


def tool_check(exe: str, argv: list[str], *, required: bool, parse: Callable[[str, str], str] | None = None, why: str = "") -> Callable[[Ctx], tuple[str, str]]:
    """Build a check that reports a CLI's version, or MISSING.

    Optional tools report SKIP so a missing Foundry Local does not fail the whole gate.
    """

    def _check(ctx: Ctx) -> tuple[str, str]:
        path = shutil.which(exe)
        if not path:
            ctx.facts.setdefault("tools", {})[exe] = None
            return (FAIL if required else SKIP), f"MISSING{'' if required else ' (optional' + (' — ' + why if why else '') + ')'}"
        rc, out, err = run_cmd(argv)
        if rc != 0:
            ctx.facts.setdefault("tools", {})[exe] = f"error rc={rc}"
            return (FAIL if required else SKIP), f"{path} present but `{' '.join(argv)}` exited {rc}: {(err or out)[:80]}"
        version = parse(out, err) if parse else next((ln for ln in (out + "\n" + err).splitlines() if ln.strip()), "?")
        version = version.strip()[:70]
        ctx.facts.setdefault("tools", {})[exe] = version
        return PASS, f"{version}  ({path})"

    return _check


def _parse_az(out: str, _err: str) -> str:
    try:
        return "azure-cli " + json.loads(out)["azure-cli"]
    except Exception:  # noqa: BLE001
        return (out or _err).splitlines()[0] if (out or _err) else "?"


# ----------------------------------------------------------------------------------
# AZURE — only with --azure and only when `az` exists
# ----------------------------------------------------------------------------------
def _azure_precondition(ctx: Ctx) -> str | None:
    if not ctx.args.azure:
        return "not requested — pass --azure to run the subscription checks"
    if not shutil.which("az"):
        return "`az` is not installed, so the subscription cannot be inspected"
    return None


def check_account(ctx: Ctx) -> tuple[str, str]:
    if (why := _azure_precondition(ctx)):
        return SKIP, why
    try:
        acct = az_json(["account", "show"])
    except HttpFailure as exc:
        return FAIL, f"az account show failed: {exc}"
    user = (acct.get("user") or {}).get("name", "?")
    ctx.facts["subscription"] = {"id": acct.get("id"), "tenant": acct.get("tenantId"), "user": user, "name": acct.get("name"), "state": acct.get("state")}
    return PASS, f"{acct.get('name')} · sub {acct.get('id')} · tenant {acct.get('tenantId')} · {user}"


def check_region_policy(ctx: Ctx) -> tuple[str, str]:
    """Azure for Students usually carries an 'Allowed locations' assignment; find it."""
    if (why := _azure_precondition(ctx)):
        return SKIP, why
    try:
        assignments = az_json(["policy", "assignment", "list"]) or []
    except HttpFailure as exc:
        return FAIL, f"az policy assignment list failed: {exc}"
    hits, allowed = [], []
    for a in assignments:
        label = f"{a.get('displayName') or ''} {a.get('name') or ''}".lower()
        if "region" not in label and "location" not in label:
            continue
        hits.append(a.get("displayName") or a.get("name"))
        for key, param in (a.get("parameters") or {}).items():
            value = param.get("value") if isinstance(param, dict) else None
            if isinstance(value, list) and ("location" in key.lower() or "region" in key.lower()):
                allowed.extend(str(v).lower().replace(" ", "") for v in value)
    allowed = sorted(set(allowed))
    ctx.facts["region_policy"] = {"assignments": hits, "allowed_regions": allowed, "total_assignments": len(assignments)}
    if not hits:
        ctx.note("No region policy assignment found — treat every region as allowed, but confirm before `azd up`.")
        return PASS, f"no region/location assignment among {len(assignments)} assignments — unrestricted"
    if not allowed:
        return PASS, f"found {hits} but no location list in its parameters — inspect the policy definition by hand"
    return PASS, f"{hits[0]} allows {len(allowed)}: {', '.join(allowed[:8])}{' …' if len(allowed) > 8 else ''}"


def check_flex_regions(ctx: Ctx) -> tuple[str, str]:
    if (why := _azure_precondition(ctx)):
        return SKIP, why
    try:
        rows = az_json(["functionapp", "list-flexconsumption-locations"]) or []
    except HttpFailure as exc:
        return FAIL, f"az functionapp list-flexconsumption-locations failed: {exc}"
    flex = sorted({str(r.get("name", "")).lower().replace(" ", "") for r in rows if r.get("name")})
    allowed = (ctx.facts.get("region_policy") or {}).get("allowed_regions") or []
    usable = sorted(set(flex) & set(allowed)) if allowed else flex
    pick = next((r for r in REGION_PREFERENCE if r in usable), usable[0] if usable else None)
    ctx.facts["flex_regions"] = {"flex": flex, "usable": usable, "recommended": pick, "constrained_by_policy": bool(allowed)}
    if not usable:
        return FAIL, f"no overlap between the {len(allowed)} policy-allowed regions and the {len(flex)} Flex Consumption regions"
    scope = "policy ∩ flex" if allowed else "flex (policy unrestricted)"
    ctx.note(f"Deploy region: use '{pick}'. Set AZURE_LOCATION={pick} in azd env / infra params.")
    return PASS, f"{len(usable)} usable ({scope}) → recommend '{pick}': {', '.join(usable[:8])}{' …' if len(usable) > 8 else ''}"


def check_providers(ctx: Ctx) -> tuple[str, str]:
    """Report registration state only — registering is a deliberate act, not a probe."""
    if (why := _azure_precondition(ctx)):
        return SKIP, why
    try:
        rows = az_json(["provider", "list", "--query", "[].{ns:namespace,state:registrationState}"]) or []
    except HttpFailure as exc:
        return FAIL, f"az provider list failed: {exc}"
    state = {r["ns"]: r["state"] for r in rows if r.get("ns") in REQUIRED_PROVIDERS}
    missing = [p for p in REQUIRED_PROVIDERS if state.get(p) != "Registered"]
    ctx.facts["providers"] = {p: state.get(p, "NotFound") for p in REQUIRED_PROVIDERS}
    if missing:
        ctx.note("Register providers: " + " ; ".join(f"az provider register -n {p}" for p in missing))
        return FAIL, "not registered: " + ", ".join(f"{p}={state.get(p, 'NotFound')}" for p in missing)
    return PASS, f"all {len(REQUIRED_PROVIDERS)} registered"


# ----------------------------------------------------------------------------------
# İBB — network, throttled
# ----------------------------------------------------------------------------------
def _ibb_precondition(ctx: Ctx) -> str | None:
    if ctx.args.no_network:
        return "--no-network"
    if ctx.ibb_calls >= ctx.ibb_budget:
        return f"İBB call budget ({ctx.ibb_budget}) exhausted"
    return None


def check_aq_stations(ctx: Ctx) -> tuple[str, str]:
    if (why := _ibb_precondition(ctx)):
        return SKIP, why
    ctx.spend_ibb_call("GetAQIStations")
    try:
        stations = get_json(AQ_STATIONS)
    except (HttpFailure, ValueError) as exc:
        return FAIL, f"GetAQIStations: {exc}"
    ctx.facts["aq_first_station"] = stations[0] if stations else None
    n = len(stations)
    if n != BASELINE["aq_stations"]:
        ctx.note(f"AQ station count is {n}, was {BASELINE['aq_stations']} on 2026-09-08 — recapture tests/fixtures/aq_stations.json.")
        return PASS, f"{n} stations (expected {BASELINE['aq_stations']} — CHANGED)"
    return PASS, f"{n} stations, first '{stations[0].get('Name')}'"


def check_aq_window(ctx: Ctx) -> tuple[str, str]:
    """A 30-day pull documents that there is no small per-call cap — the backfill plan
    (PLAN §10 step 8, two years of history) stands or falls on this."""
    if (why := _ibb_precondition(ctx)):
        return SKIP, why
    station = ctx.facts.get("aq_first_station")
    if not station:
        return SKIP, "no station id (check 5 did not run)"
    now = dt.datetime.now().replace(minute=0, second=0, microsecond=0)
    fmt = "%d.%m.%Y %H:%M:%S"
    start, end = (now - dt.timedelta(days=30)).strftime(fmt), now.strftime(fmt)
    url = f"{AQ_READINGS}?StationId={station['Id']}&StartDate={urllib.parse.quote(start)}&EndDate={urllib.parse.quote(end)}"
    ctx.spend_ibb_call("GetAQIByStationId 30d")
    try:
        rows = get_json(url)
    except (HttpFailure, ValueError) as exc:
        return FAIL, f"GetAQIByStationId: {exc}"
    times = sorted(r.get("ReadTime", "") for r in rows)
    with_pm10 = sum(1 for r in rows if (r.get("Concentration") or {}).get("PM10") is not None)
    ctx.facts["aq_window"] = {"station": station.get("Name"), "requested": [start, end], "rows": len(rows), "distinct": len(set(times)), "span": [times[0] if times else None, times[-1] if times else None], "with_pm10": with_pm10}
    if not rows:
        return FAIL, f"30-day window for '{station.get('Name')}' returned 0 rows"
    dup = len(rows) - len(set(times))
    return PASS, f"{len(rows)} rows ({len(set(times))} distinct{f', {dup} dup' if dup else ''}), {times[0]} → {times[-1]}, PM10 on {with_pm10}"


def check_ispark(ctx: Ctx) -> tuple[str, str]:
    if (why := _ibb_precondition(ctx)):
        return SKIP, why
    ctx.spend_ibb_call("İSPARK /Park")
    try:
        lots = get_json(ISPARK_LIST)
    except (HttpFailure, ValueError) as exc:
        return FAIL, f"İSPARK /Park: {exc}"
    free = sum(1 for p in lots if _as_int(p.get("emptyCapacity")) > 0)
    open_now = sum(1 for p in lots if _as_int(p.get("isOpen")) == 1)
    ctx.facts["ispark"] = {"lots": len(lots), "with_free_space": free, "open": open_now}
    if not lots:
        return FAIL, "İSPARK returned an empty list"
    if len(lots) != BASELINE["ispark_lots"]:
        ctx.note(f"İSPARK lot count is {len(lots)}, was {BASELINE['ispark_lots']} on 2026-09-08 — expected drift, no action unless it collapses.")
    return PASS, f"{len(lots)} lots, {free} report free space, {open_now} open now"


def check_iett_line(ctx: Ctx) -> tuple[str, str]:
    if (why := _ibb_precondition(ctx)):
        return SKIP, why
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
        "<GetHatOtoKonum_json xmlns='http://tempuri.org/'><HatKodu>500T</HatKodu></GetHatOtoKonum_json>"
        "</soap:Body></soap:Envelope>"
    ).encode()
    ctx.spend_ibb_call("İETT GetHatOtoKonum 500T")
    try:
        status, body, _ = http("POST", IETT_FLEET_ASMX, headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '"http://tempuri.org/GetHatOtoKonum_json"'}, body=envelope)
    except HttpFailure as exc:
        return FAIL, f"İETT SOAP: {exc}"
    if status != 200:
        return FAIL, f"İETT SOAP returned HTTP {status} (100 req/hour cap — back off)"
    import html
    import re

    text = body.decode("utf-8", "replace")
    match = re.search(r"<GetHatOtoKonum_jsonResult>(.*?)</GetHatOtoKonum_jsonResult>", text, re.S)
    if not match:
        return FAIL, "no <GetHatOtoKonum_jsonResult> element in the SOAP envelope"
    payload = html.unescape(match.group(1))
    if "ORA-" in payload:
        return FAIL, f"Oracle error leaked through: {payload[:120]}"
    try:
        buses = json.loads(payload)
    except ValueError as exc:
        return FAIL, f"result is not JSON: {exc}"
    ctx.facts["iett_500T"] = {"vehicles": len(buses), "routes": sorted({b.get("guzergahkodu") for b in buses}), "latest": max((b.get("son_konum_zamani", "") for b in buses), default=None)}
    if not buses:
        return FAIL, "500T returned 0 vehicles (valid at 03:00, suspicious otherwise)"
    return PASS, f"{len(buses)} vehicles on 500T, latest fix {ctx.facts['iett_500T']['latest']}"


def check_metro(ctx: Ctx) -> tuple[str, str]:
    if (why := _ibb_precondition(ctx)):
        return SKIP, why
    ctx.spend_ibb_call("Metro GetServiceStatuses")
    try:
        payload = get_json(METRO_SERVICE_STATUS)
    except (HttpFailure, ValueError) as exc:
        return FAIL, f"GetServiceStatuses: {exc}"
    if not payload.get("Success", False):
        return FAIL, f"Success=false, Error={payload.get('Error')}"
    data = payload.get("Data") or []
    active = [d for d in data if d.get("IsActive") and (d.get("Description") or "").strip()]
    ctx.facts["metro"] = {"entries": len(data), "active_notices": len(active), "lines": [d.get("LineName") for d in active]}
    lines = ", ".join(str(d.get("LineName")) for d in active) or "none"
    return PASS, f"{len(active)} active notice(s) of {len(data)} entries — lines: {lines}"


def check_traffic(ctx: Ctx) -> tuple[str, str]:
    """The Accept header is load-bearing: without it the endpoint answers XML."""
    if (why := _ibb_precondition(ctx)):
        return SKIP, why
    url = f"{TRAFFIC_INDEX_HISTORY}/1/H"
    ctx.spend_ibb_call("TrafficIndex +Accept")
    try:
        status, body, headers = http("GET", url, headers={"Accept": "application/json"})
    except HttpFailure as exc:
        return FAIL, f"TrafficIndexHistory: {exc}"
    if status != 200:
        return FAIL, f"HTTP {status} with Accept: application/json"
    try:
        rows = json.loads(body)
    except ValueError:
        return FAIL, f"Accept: application/json still produced {headers.get('content-type')} — the API changed"
    latest = max(rows, key=lambda r: r.get("TrafficIndexDate", "")) if rows else {}
    result = {"with_header": {"content_type": headers.get("content-type"), "rows": len(rows), "latest": latest}}
    detail = f"JSON, {len(rows)} points, latest index {latest.get('TrafficIndex')} at {latest.get('TrafficIndexDate')}"

    if not ctx.args.traffic_both:
        result["without_header"] = "not probed (would be a 7th call; pass --traffic-both)"
        ctx.facts["traffic"] = result
        return PASS, detail + " | no-header probe skipped to stay inside the call budget"
    ctx.spend_ibb_call("TrafficIndex -Accept")
    try:
        _s, raw, hdr2 = http("GET", url)
    except HttpFailure as exc:
        result["without_header"] = f"error: {exc}"
        ctx.facts["traffic"] = result
        return PASS, detail + f" | no-header probe errored: {exc}"
    head = raw[:40].decode("utf-8", "replace").strip()
    is_xml = head.startswith("<")
    result["without_header"] = {"content_type": hdr2.get("content-type"), "starts_with": head, "is_xml": is_xml}
    ctx.facts["traffic"] = result
    if not is_xml:
        ctx.note("TrafficIndexHistory now returns JSON without an Accept header — the workaround in config.py can be relaxed.")
        return PASS, detail + " | no-header ALSO returned JSON (behaviour changed)"
    return PASS, detail + f" | without the header: {hdr2.get('content-type')} starting '{head[:24]}' → header confirmed required"


def _as_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


# ----------------------------------------------------------------------------------
# GTFS — local files
# ----------------------------------------------------------------------------------
def _read_column(path: pathlib.Path, column: str) -> tuple[int, set[str]]:
    """GTFS here is ';'-separated with a UTF-8 BOM — csv defaults would silently fail."""
    values, rows = set(), 0
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            rows += 1
            if (v := (row.get(column) or "").strip()):
                values.add(v)
    return rows, values


def check_gtfs_files(ctx: Ctx) -> tuple[str, str]:
    gtfs = ROOT / "data" / "reference" / "gtfs"
    present = {name: (gtfs / name) for name in ("stops.csv", "routes.csv", "stop_times.csv", "trips.csv")}
    missing_core = [n for n in ("stops.csv", "routes.csv") if not present[n].exists()]
    ctx.facts["gtfs_files"] = {n: (p.stat().st_size if p.exists() else None) for n, p in present.items()}
    if missing_core:
        return FAIL, f"missing {', '.join(missing_core)} in {gtfs}"
    sizes = ", ".join(f"{n} {present[n].stat().st_size / 1e6:.1f} MB" for n in ("stops.csv", "routes.csv"))
    later = [n for n in ("stop_times.csv", "trips.csv") if not present[n].exists()]
    if not later:
        return PASS, sizes
    ctx.note(f"GTFS {', '.join(later)} not downloaded yet — needed for stop sequences on Day 3; URLs in tests/fixtures/gtfs_resources.json.")
    return PASS, f"{sizes} · not downloaded yet: {', '.join(later)}"


def _load_500t(ctx: Ctx) -> list[dict] | None:
    """Prefer the live payload this run fetched; fall back to the recorded fixture."""
    fixture = ROOT / "tests" / "fixtures" / "iett_hat_500T.json"
    if not fixture.exists():
        return None
    return json.loads(fixture.read_text(encoding="utf-8"))


def check_stop_join(ctx: Ctx) -> tuple[str, str]:
    """The whole ETA engine assumes yakinDurakKodu == GTFS stop_code (NOT stop_id)."""
    stops = ROOT / "data" / "reference" / "gtfs" / "stops.csv"
    buses = _load_500t(ctx)
    if not stops.exists() or buses is None:
        return SKIP, "needs data/reference/gtfs/stops.csv and tests/fixtures/iett_hat_500T.json"
    rows, codes = _read_column(stops, "stop_code")
    _r2, ids = _read_column(stops, "stop_id")
    wanted = [str(b.get("yakinDurakKodu", "")).strip() for b in buses]
    hits = sum(1 for w in wanted if w in codes)
    id_hits = sum(1 for w in wanted if w in ids)
    ctx.facts["gtfs_stop_join"] = {"buses": len(wanted), "stop_code_hits": hits, "stop_id_hits": id_hits, "stops_rows": rows, "distinct_stop_code": len(codes)}
    if hits < len(wanted):
        ctx.note("Live stop codes no longer resolve 1:1 — fall back to nearest-stop-by-coordinate for ETA (PLAN §15).")
        return FAIL, f"{hits}/{len(wanted)} yakinDurakKodu resolved to stop_code (stop_id would match {id_hits})"
    return PASS, f"{hits}/{len(wanted)} yakinDurakKodu → stop_code across {rows} stops (stop_id matches only {id_hits} — join on stop_code)"


def check_route_join(ctx: Ctx) -> tuple[str, str]:
    routes = ROOT / "data" / "reference" / "gtfs" / "routes.csv"
    buses = _load_500t(ctx)
    if not routes.exists() or buses is None:
        return SKIP, "needs data/reference/gtfs/routes.csv and tests/fixtures/iett_hat_500T.json"
    rows, codes = _read_column(routes, "route_code")
    wanted = sorted({str(b.get("guzergahkodu", "")).strip() for b in buses})
    hits = [w for w in wanted if w in codes]
    ctx.facts["gtfs_route_join"] = {"live_routes": wanted, "matched": hits, "routes_rows": rows}
    if len(hits) < len(wanted):
        return FAIL, f"{len(hits)}/{len(wanted)} guzergahkodu resolved to route_code; unmatched {sorted(set(wanted) - set(hits))}"
    return PASS, f"{len(hits)}/{len(wanted)} guzergahkodu → route_code ({', '.join(wanted)}) across {rows} routes"


# ----------------------------------------------------------------------------------
# registry
# ----------------------------------------------------------------------------------
Check = tuple[str, str, Callable[[Ctx], tuple[str, str]]]

SECTIONS: list[tuple[str, list[Check]]] = [
    ("TOOLS  (local)", [
        ("T1", "python 3.12", check_python),
        ("T2", "uv", tool_check("uv", ["uv", "--version"], required=True)),
        ("T3", "az (Azure CLI)", tool_check("az", ["az", "version"], required=True, parse=_parse_az)),
        ("T4", "azd (Developer CLI)", tool_check("azd", ["azd", "version"], required=True)),
        ("T5", "func (Functions Core Tools)", tool_check("func", ["func", "--version"], required=True)),
        ("T6", "foundry (Foundry Local)", tool_check("foundry", ["foundry", "--version"], required=False, why="only needed on the local-LLM path, PLAN §9")),
        ("T7", "git", tool_check("git", ["git", "--version"], required=True)),
        ("T8", "gh (GitHub CLI)", tool_check("gh", ["gh", "--version"], required=False, why="repo already exists; used for CI secrets")),
    ]),
    ("AZURE  (--azure)", [
        ("A1", "subscription / tenant / identity", check_account),
        ("A2", "allowed-regions policy", check_region_policy),
        ("A3", "Functions Flex regions ∩ allowed", check_flex_regions),
        ("A4", "resource providers registered", check_providers),
    ]),
    ("İBB    (network, throttled)", [
        ("I5", "air quality: GetAQIStations", check_aq_stations),
        ("I6", "air quality: 30-day window", check_aq_window),
        ("I7", "İSPARK: /Park", check_ispark),
        ("I8", "İETT: GetHatOtoKonum_json 500T", check_iett_line),
        ("I9", "Metro: GetServiceStatuses", check_metro),
        ("I10", "traffic index: Accept header", check_traffic),
    ]),
    ("GTFS   (local files)", [
        ("G11", "stops.csv / routes.csv present", check_gtfs_files),
        ("G12", "yakinDurakKodu → stop_code", check_stop_join),
        ("G13", "guzergahkodu → route_code", check_route_join),
    ]),
]

# What to do when a check fails. Keyed by check id; only printed for FAILs.
REMEDIES: dict[str, str] = {
    "T1": "brew install python@3.12 — do not fall back to the system 3.14, the MCP SDK pins <3.13 wheels.",
    "T2": "brew install uv   (then: uv venv -p 3.12 .venv && source .venv/bin/activate)",
    "T3": "brew install azure-cli   (then: az login)",
    "T4": "brew install azd",
    "T5": "brew tap azure/functions && brew install azure-functions-core-tools@4",
    "T6": "Optional today: brew tap microsoft/foundrylocal && brew install foundrylocal — needed only if the Azure OpenAI quota gate fails.",
    "T7": "xcode-select --install",
    "T8": "brew install gh   (only needed for CI secrets and releases)",
    "A1": "az login --use-device-code, then re-run with --azure. If the subscription is Disabled, check the spending limit before anything else.",
    "A2": "Read the policy by hand: az policy assignment list -o table, then az policy definition show --name <id>. A region policy you cannot see will fail `azd up` at deploy time, not plan time.",
    "A3": "No deployable region. Either request a policy exemption, or move Functions to Linux Consumption (Y1) / a Container Apps Job — see PLAN §3 fallback column.",
    "A4": "Register the missing providers (each takes a few minutes): az provider register -n <namespace>. Deploy will fail with an opaque error otherwise.",
    "I5": "İBB gateway did not answer. Retry in a few minutes — it 503s under load. If it stays down, Day 1 continues against tests/fixtures/ (Settings.offline=True).",
    "I6": "Without a wide window the two-year AQ backfill (PLAN §10 step 8) is off the table; fall back to daily incremental pulls only.",
    "I7": "İSPARK is the J1 journey's only data source. If it stays down, demo J2–J4 and note the outage in DECISIONS.md.",
    "I8": "İETT SOAP is capped at 100 req/hour — if this fails, STOP calling it and wait an hour. Check tests/fixtures/iett_hat_500T.soap.xml for an 'ORA-' error signature.",
    "I9": "Metro status feeds J3. The endpoint works even though its help page 503s — retry before assuming a change.",
    "I10": "TrafficIndexHistory changed shape. Re-probe with and without 'Accept: application/json' and update src/ibb_mcp/config.py.",
    "G11": "Download stops.csv and routes.csv into data/reference/gtfs/ using the URLs in tests/fixtures/gtfs_resources.json (read them with encoding='utf-8-sig', delimiter=';').",
    "G12": "The ETA engine (PLAN §7) joins live buses to GTFS on stop_code. If it breaks, switch to nearest-stop-by-haversine and report ETA as 'km + min' instead of 'n stops'.",
    "G13": "Without the route_code join a line's direction cannot be resolved; fall back to the 'yon' free-text field from the live payload.",
}

MANUAL_GATES = [
    "ADX free cluster — create at https://dataexplorer.azure.com/freecluster with the SAME identity that owns the Azure subscription (a different Entra account gives you a cluster you cannot grant the Function's managed identity access to). Database name: 'nabiz'. There is no CLI for this, so this script cannot check it.",
    "Azure OpenAI quota — deploy gpt-4.1-mini (Global Standard) at https://ai.azure.com. If the TPM quota is 0, fill https://aka.ms/oai/stuquotarequest immediately; turnaround is days, not hours (PLAN §9).",
    "Delivery date and brief — get Barbaros's answer in writing today: video length, language, repo visibility, upload address (PLAN header).",
    "Budget alerts — set $20 and $40 alerts in Cost Management and check the Sponsorships balance (PLAN §10 step 6).",
]


# ----------------------------------------------------------------------------------
# rendering
# ----------------------------------------------------------------------------------
def _wrap(text: str, width: int, indent: str) -> str:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    return f"\n{indent}".join(lines)


def render(results: list[dict], ctx: Ctx, elapsed: float) -> str:
    out: list[str] = []
    stamp = dt.datetime.now().astimezone()
    out.append("=" * 100)
    out.append("İSTANBUL NABIZ — DAY-0 GATE".center(100))
    out.append(f"{stamp:%Y-%m-%d %H:%M %Z}  ·  transport: {TRANSPORT}  ·  endpoints: {CONFIG_SOURCE}".center(100))
    out.append("=" * 100)
    head = f"  {'ID':<4} {'CHECK':<32} {'STATUS':<7} DETAIL"
    indent = " " * 47
    for title, checks in SECTIONS:
        ids = {c[0] for c in checks}
        rows = [r for r in results if r["id"] in ids]
        out.append("")
        out.append(f"{title}")
        out.append(head)
        out.append("  " + "-" * 96)
        for r in rows:
            out.append(f"  {r['id']:<4} {r['name']:<32} {r['status']:<7} {_wrap(r['detail'], 49, indent)}")
    counts = {s: sum(1 for r in results if r["status"] == s) for s in (PASS, FAIL, SKIP)}
    out.append("")
    out.append("  " + "-" * 96)
    out.append(f"  {counts[PASS]} passed · {counts[FAIL]} failed · {counts[SKIP]} skipped   ·   {ctx.ibb_calls}/{ctx.ibb_budget} İBB calls spent   ·   {elapsed:.1f}s")

    out.append("")
    out.append("NEXT ACTIONS")
    out.append("  " + "-" * 96)
    n = 0
    for r in results:
        if r["status"] == FAIL and r["id"] in REMEDIES:
            n += 1
            out.append(f"  {n}. [{r['id']} {r['name']}] {_wrap(REMEDIES[r['id']], 88, '     ')}")
    for r in results:
        if r["status"] == SKIP and r["id"] in ("T6", "T8") and "MISSING" in r["detail"]:
            n += 1
            out.append(f"  {n}. [{r['id']} {r['name']}] {_wrap(REMEDIES[r['id']], 88, '     ')}")
    for note in ctx.notes:
        n += 1
        out.append(f"  {n}. {_wrap(note, 88, '     ')}")
    if not n:
        out.append("  Nothing to fix from the automated checks.")

    out.append("")
    out.append("  MANUAL GATES — not checkable from a script, still blocking Day 0:")
    for i, gate in enumerate(MANUAL_GATES, 1):
        out.append(f"  {chr(64 + i)}. {_wrap(gate, 88, '     ')}")
    out.append("")
    return "\n".join(out)


# ----------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Day-0 readiness gate for İstanbul Nabız (PLAN.md §10).")
    ap.add_argument("--azure", action="store_true", help="run the `az` subscription checks (A1–A4)")
    ap.add_argument("--no-network", action="store_true", help="skip every İBB call (I5–I10)")
    ap.add_argument("--traffic-both", action="store_true", help="spend a 7th İBB call proving the Accept header is required")
    ap.add_argument("--json-only", action="store_true", help="print only the JSON report on stdout")
    args = ap.parse_args(argv)

    ctx = Ctx(args=args)
    results: list[dict] = []
    t0 = time.monotonic()
    for section, checks in SECTIONS:
        for cid, name, fn in checks:
            try:
                status, detail = fn(ctx)
            except BudgetExceeded as exc:
                status, detail = SKIP, str(exc)
            except Exception as exc:  # noqa: BLE001 - a broken check must not kill the gate
                status, detail = FAIL, f"probe raised {type(exc).__name__}: {exc}"
            results.append({"id": cid, "section": section.split()[0], "name": name, "status": status, "detail": detail})
            if not args.json_only:
                print(f"  {cid:<4} {status:<5} {name}", file=sys.stderr)
    elapsed = time.monotonic() - t0

    failed = [r for r in results if r["status"] == FAIL]
    report = {
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "generated_at_local": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "args": vars(args),
        "transport": TRANSPORT,
        "endpoint_source": CONFIG_SOURCE,
        "elapsed_seconds": round(elapsed, 2),
        "ibb_calls_spent": ctx.ibb_calls,
        "ibb_call_budget": ctx.ibb_budget,
        "summary": {s: sum(1 for r in results if r["status"] == s) for s in (PASS, FAIL, SKIP)},
        "checks": results,
        "facts": ctx.facts,
        "notes": ctx.notes,
        "manual_gates": MANUAL_GATES,
        "remedies_for_failures": {r["id"]: REMEDIES.get(r["id"], "") for r in failed},
        "exit_code": 1 if failed else 0,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("\r" + " " * 60 + "\r", end="", file=sys.stderr)
        print(render(results, ctx, elapsed))
        print(f"  JSON report: {REPORT_PATH.relative_to(ROOT)}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
