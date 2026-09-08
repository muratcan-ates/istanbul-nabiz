"""Endpoint catalogue and runtime settings.

Every URL here was called successfully on 2026-09-08; the recorded responses live in
``tests/fixtures/``. Keeping them in one module means a change at İBB is a one-line fix.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass

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


@dataclass(frozen=True)
class Settings:
    """Runtime configuration, all overridable by environment variable."""

    gtfs_dir: pathlib.Path = REPO_ROOT / "data" / "reference" / "gtfs"
    places_csv: pathlib.Path = REPO_ROOT / "data" / "reference" / "places.csv"
    fixtures_dir: pathlib.Path = REPO_ROOT / "tests" / "fixtures"
    #: When set, sources read from ``tests/fixtures`` instead of the network. Used by the
    #: test suite and by ``--offline`` demo runs.
    offline: bool = False
    default_radius_km: float = 1.5
    max_results: int = 5

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            gtfs_dir=pathlib.Path(os.getenv("NABIZ_GTFS_DIR", str(cls.gtfs_dir))),
            places_csv=pathlib.Path(os.getenv("NABIZ_PLACES_CSV", str(cls.places_csv))),
            fixtures_dir=pathlib.Path(os.getenv("NABIZ_FIXTURES_DIR", str(cls.fixtures_dir))),
            offline=os.getenv("NABIZ_OFFLINE", "").lower() in {"1", "true", "yes"},
            default_radius_km=float(os.getenv("NABIZ_RADIUS_KM", "1.5")),
            max_results=int(os.getenv("NABIZ_MAX_RESULTS", "5")),
        )


SOURCE_URLS = {
    "ispark": ISPARK_LIST,
    "iett_line": IETT_FLEET_ASMX,
    "iett_fleet": IETT_FLEET_ASMX,
    "iett_schedule": IETT_SCHEDULE_ASMX,
    "metro_status": METRO_SERVICE_STATUS,
    "metro_stations": METRO_STATIONS,
    "traffic": TRAFFIC_INDEX_HISTORY,
    "aq_stations": AQ_STATIONS,
    "aq_readings": AQ_READINGS,
    "gtfs": GTFS_PACKAGE,
}
