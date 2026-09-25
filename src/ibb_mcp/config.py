"""Endpoint catalogue and runtime settings.

Every URL here was called successfully on 2026-09-08; the recorded responses live in
``tests/fixtures/``. Keeping them in one module means a change at İBB is a one-line fix.
"""

from __future__ import annotations

import logging
import os
import pathlib
from collections.abc import Mapping
from dataclasses import dataclass, field

log = logging.getLogger("ibb_mcp.config")

GATEWAY = "https://api.ibb.gov.tr"
PORTAL = "https://data.ibb.gov.tr"

# --- İSPARK -----------------------------------------------------------------------
ISPARK_LIST = f"{GATEWAY}/ispark/Park"
ISPARK_DETAIL = f"{GATEWAY}/ispark/ParkDetay"

# --- İETT -------------------------------------------------------------------------
IETT_FLEET_ASMX = f"{GATEWAY}/iett/FiloDurum/SeferGerceklesme.asmx"
IETT_SCHEDULE_ASMX = f"{GATEWAY}/iett/UlasimAnaVeri/PlanlananSeferSaati.asmx"
IETT_ACTION_LINE_POSITIONS = "GetHatOtoKonum_json"
IETT_ACTION_FLEET_POSITIONS = "GetFiloAracKonum_json"
IETT_ACTION_SCHEDULE = "GetPlanlananSeferSaati_json"

# --- Metro İstanbul ---------------------------------------------------------------
METRO_BASE = f"{GATEWAY}/MetroIstanbul/api/MetroMobile/V2"
METRO_SERVICE_STATUS = f"{METRO_BASE}/GetServiceStatuses"
METRO_STATIONS = f"{METRO_BASE}/GetStations"
# Faulty lifts, escalators and moving walkways: a GET summary of counts per equipment group,
# and a POST detail list that needs {"EquipmentGroupName": ...} (both first read 2026-09-24).
METRO_FAULTY_EQUIPMENTS = f"{METRO_BASE}/GetFaultyEquipments"
METRO_FAULTY_EQUIPMENT_DETAILS = f"{METRO_BASE}/GetFaultyEquipmentDetails"

# --- Traffic ----------------------------------------------------------------------
# NOTE: returns XML unless Accept: application/json is sent.
TRAFFIC_INDEX_HISTORY = f"{GATEWAY}/tkmservices/api/TrafficData/v1/TrafficIndexHistory"

# --- Air quality ------------------------------------------------------------------
AQ_BASE = f"{GATEWAY}/havakalitesi/OpenDataPortalHandler"
AQ_STATIONS = f"{AQ_BASE}/GetAQIStations"
AQ_READINGS = f"{AQ_BASE}/GetAQIByStationId"

# --- Open data portal -------------------------------------------------------------
GTFS_PACKAGE = f"{PORTAL}/api/3/action/package_show?id=iett-gtfs-verisi"
LICENSE_URL = f"{PORTAL}/license"
ATTRIBUTION = (
    "Kamu sektörü bilgilerini içerir — İBB Açık Veri Portalı, "
    "İBB Açık Veri Lisansı (CC BY 4.0)."
)
ATTRIBUTION_EN = (
    "Contains public sector information from the İstanbul Metropolitan Municipality "
    "Open Data Portal, licensed under the İBB Open Data Licence (CC BY 4.0)."
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Where a built wheel carries the committed reference files (pyproject.toml,
#: ``[tool.hatch.build.targets.wheel.force-include]``). Only an installed package has it.
PACKAGE_DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"


def display_path(path: pathlib.Path | str) -> str:
    """A path as it may appear in a log line: repo-relative, or its file name alone.

    Startup logs end up pasted into issues, docs and eval reports. An absolute path would
    carry the machine's user name with it, so only the part that means something to
    another checkout is printed. String work only; the file need not exist.
    """
    absolute = pathlib.Path(os.path.abspath(path))
    try:
        return absolute.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return absolute.name


def reference_path(
    name: str, *, checkout_root: pathlib.Path = REPO_ROOT, package_dir: pathlib.Path = PACKAGE_DATA_DIR
) -> pathlib.Path:
    """A committed file under ``data/reference/``, wherever this code is running from.

    In a checkout (or an editable install) that is the repository's own directory. In an
    installed wheel ``REPO_ROOT`` resolves to somewhere under site-packages where no
    ``data/`` exists, so the copy the wheel carries is used instead: without it,
    ``uvx --from git+… ibb-mcp`` would start happily and resolve no place at all. The
    checkout wins whenever it exists, so an edited places.csv is read without reinstalling.
    """
    checkout = checkout_root / "data" / "reference" / name
    packaged = package_dir / name
    return packaged if not checkout.exists() and packaged.exists() else checkout


@dataclass(frozen=True)
class Settings:
    """Runtime configuration, all overridable by environment variable."""

    gtfs_dir: pathlib.Path = REPO_ROOT / "data" / "reference" / "gtfs"
    places_csv: pathlib.Path = reference_path("places.csv")
    fixtures_dir: pathlib.Path = REPO_ROOT / "tests" / "fixtures"
    #: When set, sources read from ``tests/fixtures`` instead of the network. Used by the
    #: test suite and by ``--offline`` demo runs.
    offline: bool = False
    default_radius_km: float = 1.5
    max_results: int = 5
    #: Which seconds-per-stop rate arrival estimates use (``NABIZ_ETA_PROFILE_MODE``):
    #: ``default``, the untuned 120 s/stop, or ``calibrated``, the fitted profile, for
    #: research only. The default is the one with the better held-out score; the numbers
    #: and the rule for reading this value are in :mod:`ibb_mcp.eta_profile` (DECISIONS #18).
    eta_profile_mode: str = "default"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            gtfs_dir=pathlib.Path(os.getenv("NABIZ_GTFS_DIR", str(cls.gtfs_dir))),
            places_csv=pathlib.Path(os.getenv("NABIZ_PLACES_CSV", str(cls.places_csv))),
            fixtures_dir=pathlib.Path(os.getenv("NABIZ_FIXTURES_DIR", str(cls.fixtures_dir))),
            offline=os.getenv("NABIZ_OFFLINE", "").lower() in {"1", "true", "yes"},
            default_radius_km=float(os.getenv("NABIZ_RADIUS_KM", "1.5")),
            max_results=int(os.getenv("NABIZ_MAX_RESULTS", "5")),
            eta_profile_mode=os.getenv("NABIZ_ETA_PROFILE_MODE", cls.eta_profile_mode),
        )


@dataclass(frozen=True)
class HardeningConfig:
    """How the public streamable-HTTP endpoint protects the shared İBB budget from its callers.

    :mod:`ibb_mcp.http` protects İBB *from us*; this protects that budget *from our own
    callers*: with public ingress there is otherwise nothing between a script with a
    ``for`` loop and the gateway allowance every user of this project shares. It has no
    effect on stdio, where the one caller is the person who started the process.

    The defaults matter more than the knobs: this is read from the environment of a
    container nobody will tune, so an unset variable must leave the server where we would
    have put it anyway — open to read, because the data is open, but not cheap to abuse.
    """

    #: Accepted API keys (``NABIZ_API_KEYS``, comma-separated). Empty means no key is
    #: asked for, which is the honest default for open data; the per-client budget below
    #: applies either way. Kept out of ``repr`` so a logged config never prints a secret.
    api_keys: tuple[str, ...] = field(default=(), repr=False)
    #: Tokens a fresh client may spend at once. Tool prices are ``ibb_mcp.server.TOOL_COSTS``.
    burst: int = 30
    #: Sustained refill. 12 a minute is one arrival estimate (13 tokens) a little over
    #: once a minute: more than a person asking questions needs, far less than a loop wants.
    refill_per_minute: float = 12.0
    #: Upper bound on remembered clients; see ``ibb_mcp.server.ClientLimiter``.
    max_clients: int = 1024
    #: Browser origins allowed to call the endpoint. Empty emits no CORS header at all,
    #: which leaves the browser's same-origin rule in force.
    cors_origins: tuple[str, ...] = ()
    #: How many reverse proxies in front of the server append to ``X-Forwarded-For``.
    #: 0 trusts only the socket peer. Behind Container Apps ingress, which appends the
    #: caller's address, it should be 1, or every caller shares the proxy's address and so
    #: one bucket. That the ingress is exactly one hop is not verified here: nothing has been
    #: deployed yet, so confirm it on the first deploy (docs/deploy.md).
    trusted_proxy_hops: int = 0

    @property
    def refill_per_second(self) -> float:
        return self.refill_per_minute / 60.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> HardeningConfig:
        """Read the configuration; ``env`` is injectable so tests need no process environment.

        A malformed number falls back to its default with a warning instead of raising: a
        typo in a Container Apps setting must not stop the server booting, because a
        server that does not boot protects nothing.
        """
        source: Mapping[str, str] = os.environ if env is None else env
        return cls(
            api_keys=_split_csv(source.get("NABIZ_API_KEYS", "")),
            burst=_number(source, "NABIZ_MCP_RATE_BURST", cls.burst),
            refill_per_minute=_number(source, "NABIZ_MCP_RATE_PER_MINUTE", cls.refill_per_minute),
            max_clients=_number(source, "NABIZ_MCP_MAX_CLIENTS", cls.max_clients),
            cors_origins=_split_csv(source.get("NABIZ_MCP_CORS_ORIGINS", "")),
            trusted_proxy_hops=_number(source, "NABIZ_MCP_TRUSTED_PROXY_HOPS", cls.trusted_proxy_hops, allow_zero=True),
        )


def _split_csv(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _number[N: (int, float)](source: Mapping[str, str], name: str, default: N, *, allow_zero: bool = False) -> N:
    """One numeric setting of the default's type: positive, or non-negative with ``allow_zero``."""
    raw = (source.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = type(default)(raw)
    except ValueError:
        value = None
    # `value == value` is False only for NaN, which float() accepts and no comparison rejects.
    if value is None or value != value or value == float("inf") or value < 0 or (value == 0 and not allow_zero):
        log.warning("%s=%r is not a valid value; using the default %r", name, raw, default)
        return default
    return value


SOURCE_URLS = {
    "ispark": ISPARK_LIST,
    "iett_line": IETT_FLEET_ASMX,
    "iett_fleet": IETT_FLEET_ASMX,
    "iett_schedule": IETT_SCHEDULE_ASMX,
    "metro_status": METRO_SERVICE_STATUS,
    "metro_stations": METRO_STATIONS,
    "metro_equipment_summary": METRO_FAULTY_EQUIPMENTS,
    "metro_equipment": METRO_FAULTY_EQUIPMENT_DETAILS,
    "traffic": TRAFFIC_INDEX_HISTORY,
    "aq_stations": AQ_STATIONS,
    "aq_readings": AQ_READINGS,
    "gtfs": GTFS_PACKAGE,
}
