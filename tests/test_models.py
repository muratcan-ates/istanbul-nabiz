"""Contract tests for :mod:`ibb_mcp.models`.

The parsing helpers are the only place that knows how mangled İBB's payloads are
(numbers as strings, Turkish decimals, coordinates with thousands separators,
double-encoded text, four different timestamp shapes). Everything downstream trusts
them, so they are tested against the real recorded responses in ``tests/fixtures/``
rather than against hand-written samples.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from ibb_mcp.models import (
    ISTANBUL_TZ,
    LAT_RANGE,
    LON_RANGE,
    AirQualityReading,
    AirQualityStation,
    BusPosition,
    MetroLineStatus,
    MetroStation,
    ParkingLot,
    PlannedDeparture,
    Provenance,
    TrafficIndexPoint,
    aqi_band,
    day_type_for,
    demojibake,
    describe_traffic,
    haversine_km,
    parse_ibb_datetime,
    parse_number,
    parse_wkt_point,
    repair_coordinate,
    utcnow,
)

UTC = dt.UTC


def assert_in_istanbul(lat: float | None, lon: float | None) -> None:
    assert lat is not None and lon is not None
    assert LAT_RANGE[0] <= lat <= LAT_RANGE[1], f"latitude {lat} outside İstanbul"
    assert LON_RANGE[0] <= lon <= LON_RANGE[1], f"longitude {lon} outside İstanbul"


# ---------------------------------------------------------------------------------
# parse_number
# ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (5, 5.0),
        (-3, -3.0),
        (5.5, 5.5),
        ("5", 5.0),
        ("5.5", 5.5),
        (" 7 ", 7.0),
        ("0", 0.0),
        ("1029", 1029.0),          # İSPARK capacity arrives as a bare string
        ("15", 15.0),              # İETT "Hiz"
        ("1.234,5", 1234.5),       # Turkish thousands + decimal comma
        ("1.234.567,89", 1234567.89),
        ("12,5", 12.5),            # decimal comma, no thousands separator
        ("3500.0", 3500.0),
        ("", None),
        ("   ", None),
        (None, None),
        ("abc", None),
        ("12,5,6", None),
        ("--", None),
    ],
)
def test_parse_number(raw: object, expected: float | None) -> None:
    assert parse_number(raw) == expected


def test_parse_number_treats_a_lone_dot_as_an_english_decimal() -> None:
    """Documented ambiguity: without a comma we cannot tell "1.234" from 1234."""
    assert parse_number("1.234") == 1.234


# ---------------------------------------------------------------------------------
# repair_coordinate
# ---------------------------------------------------------------------------------
def test_repair_coordinate_fixes_the_gtfs_thousands_separators() -> None:
    # Real row from data/reference/gtfs/stops.csv (stop_code 100001).
    assert repair_coordinate("410.191.700.005.564", "lat") == pytest.approx(41.0191700005564)
    assert repair_coordinate("286.843.529.999.755", "lon") == pytest.approx(28.6843529999755)


@pytest.mark.parametrize(
    ("raw", "kind", "expected"),
    [
        ("41.0246", "lat", 41.0246),      # İSPARK sends coordinates as clean strings
        ("29.0915", "lon", 29.0915),
        (41.0246, "lat", 41.0246),        # already a float
        (29.0915, "lon", 29.0915),
        ("4.101.917", "lat", 41.01917),
        ("40.83712", "lat", 40.83712),    # İETT live position
    ],
)
def test_repair_coordinate_passes_through_clean_values(raw: object, kind: str, expected: float) -> None:
    assert repair_coordinate(raw, kind) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        (None, "lat"),
        ("", "lat"),
        ("   ", "lon"),
        ("junk", "lat"),
        ("50.0", "lat"),            # plausible number, wrong city
        (0.0, "lat"),
        ("999.999.999", "lat"),     # survives repair as 99.99…, still absurd
        ("28.6843", "lat"),         # a longitude handed in as a latitude
        (41.0246, "lon"),           # …and the reverse
    ],
)
def test_repair_coordinate_rejects_out_of_range_and_garbage(raw: object, kind: str) -> None:
    assert repair_coordinate(raw, kind) is None


# ---------------------------------------------------------------------------------
# demojibake
# ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("KADIKÃ–Y", "KADIKÖY"),
        ("KADIKÃ–Y - KÄ°RAZLITEPE", "KADIKÖY - KİRAZLITEPE"),  # real routes.csv row
        ("KADIKÖY", "KADIKÖY"),                                # already clean, untouched
        ("TUZLA ŞİFA MAHALLESİ - 4. LEVENT METRO", "TUZLA ŞİFA MAHALLESİ - 4. LEVENT METRO"),
        ("4.LEVENT METRO", "4.LEVENT METRO"),
        ("", ""),
        (None, None),
    ],
)
def test_demojibake(raw: str | None, expected: str | None) -> None:
    assert demojibake(raw) == expected


# ---------------------------------------------------------------------------------
# parse_wkt_point
# ---------------------------------------------------------------------------------
def test_parse_wkt_point_returns_lat_lon_from_lon_lat_input() -> None:
    """WKT is (lon lat); we return (lat, lon). Getting this backwards moves stations
    into the Black Sea, so the order is asserted explicitly."""
    lat, lon = parse_wkt_point("POINT (29.0245 41.1000)")
    assert lat == 41.1000
    assert lon == 29.0245
    assert lat > lon  # in İstanbul latitude is always the larger of the two


def test_parse_wkt_point_on_a_real_air_quality_station(load_fixture) -> None:
    maslak = load_fixture("aq_stations")[0]
    lat, lon = parse_wkt_point(maslak["Location"])
    assert maslak["Name"] == "Maslak"
    assert lat == pytest.approx(41.1000, abs=0.001)
    assert lon == pytest.approx(29.0245, abs=0.001)
    assert_in_istanbul(lat, lon)


@pytest.mark.parametrize("raw", [None, "", "LINESTRING (1 2)", "POINT", "not wkt at all"])
def test_parse_wkt_point_rejects_non_points(raw: str | None) -> None:
    assert parse_wkt_point(raw) == (None, None)


# ---------------------------------------------------------------------------------
# parse_ibb_datetime
# ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # İSPARK ParkDetay.updateDate
        ("08.09.2026 09:05:16", dt.datetime(2026, 9, 8, 6, 5, 16, tzinfo=UTC)),
        # İETT son_konum_zamani
        ("2026-09-08 09:08:53", dt.datetime(2026, 9, 8, 6, 8, 53, tzinfo=UTC)),
        # Metro UpdateDate (ISO with milliseconds)
        ("2026-07-27T09:27:37.103", dt.datetime(2026, 7, 27, 6, 27, 37, 103000, tzinfo=UTC)),
        # Traffic TrafficIndexDate (ISO, no fraction)
        ("2026-09-08T09:00:00", dt.datetime(2026, 9, 8, 6, 0, 0, tzinfo=UTC)),
    ],
)
def test_parse_ibb_datetime_all_four_formats(raw: str, expected: dt.datetime) -> None:
    parsed = parse_ibb_datetime(raw)
    assert parsed == expected


@pytest.mark.parametrize(
    "raw",
    ["08.09.2026 09:05:16", "2026-09-08 09:08:53", "2026-07-27T09:27:37.103", "2026-09-08T09:00:00", "09:08:55"],
)
def test_parse_ibb_datetime_is_always_aware_utc(raw: str) -> None:
    parsed = parse_ibb_datetime(raw)
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == dt.timedelta(0)


def test_parse_ibb_datetime_shifts_naive_istanbul_input_by_three_hours() -> None:
    """İBB timestamps are naive Istanbul local time (UTC+3, no DST since 2016)."""
    parsed = parse_ibb_datetime("2026-09-08 09:08:53")
    assert parsed is not None
    assert parsed.hour == 6  # 09:08 in İstanbul is 06:08 UTC
    assert parsed.astimezone(ISTANBUL_TZ).hour == 9
    naive_local = dt.datetime(2026, 9, 8, 9, 8, 53)
    assert parsed.replace(tzinfo=None) == naive_local - dt.timedelta(hours=3)


def test_parse_ibb_datetime_bare_clock_time_lands_on_today() -> None:
    """İETT's fleet feed sends only ``HH:MM:SS``; it means today, İstanbul time."""
    parsed = parse_ibb_datetime("09:08:55")
    assert parsed is not None
    local = parsed.astimezone(ISTANBUL_TZ)
    assert (local.hour, local.minute, local.second) == (9, 8, 55)
    assert local.date() == dt.datetime.now(ISTANBUL_TZ).date()
    assert parsed.utcoffset() == dt.timedelta(0)


@pytest.mark.parametrize("raw", [None, "", "   ", "garbage", "2026-13-45 99:99:99", "08/09/2026 09:05:16"])
def test_parse_ibb_datetime_rejects_unparseable(raw: str | None) -> None:
    assert parse_ibb_datetime(raw) is None


# ---------------------------------------------------------------------------------
# haversine_km
# ---------------------------------------------------------------------------------
def test_haversine_taksim_to_kadikoy() -> None:
    taksim_lat, taksim_lon = 41.0370, 28.9857
    kadikoy_lat, kadikoy_lon = 40.9903, 29.0270
    distance = haversine_km(taksim_lat, taksim_lon, kadikoy_lat, kadikoy_lon)
    assert 5.0 <= distance <= 7.0, f"Taksim–Kadıköy should be 5–7 km, got {distance:.2f}"


def test_haversine_is_zero_for_the_same_point_and_symmetric() -> None:
    assert haversine_km(41.0, 29.0, 41.0, 29.0) == pytest.approx(0.0, abs=1e-9)
    there = haversine_km(41.0370, 28.9857, 40.9903, 29.0270)
    back = haversine_km(40.9903, 29.0270, 41.0370, 28.9857)
    assert there == pytest.approx(back)


def test_haversine_one_degree_of_latitude_is_about_111_km() -> None:
    assert haversine_km(41.0, 29.0, 42.0, 29.0) == pytest.approx(111.2, abs=0.5)


# ---------------------------------------------------------------------------------
# day_type_for
# ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (dt.datetime(2026, 9, 12, 12, 0, tzinfo=ISTANBUL_TZ), "C"),  # Saturday
        (dt.datetime(2026, 9, 13, 12, 0, tzinfo=ISTANBUL_TZ), "P"),  # Sunday
        (dt.datetime(2026, 9, 8, 12, 0, tzinfo=ISTANBUL_TZ), "I"),   # Tuesday
        (dt.datetime(2026, 9, 11, 23, 30, tzinfo=ISTANBUL_TZ), "I"), # Friday night, still weekday
        # 22:00 UTC on Friday is already Saturday in İstanbul; the conversion must happen.
        (dt.datetime(2026, 9, 11, 22, 0, tzinfo=UTC), "C"),
    ],
)
def test_day_type_for(moment: dt.datetime, expected: str) -> None:
    assert day_type_for(moment) == expected


def test_day_type_for_defaults_to_now() -> None:
    assert day_type_for() in {"I", "C", "P"}


# ---------------------------------------------------------------------------------
# aqi_band / describe_traffic
# ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("index", "expected_key"),
    [
        (0, "good"),
        (50, "good"),                  # upper edge of "İyi"
        (50.9, "moderate"),
        (51, "moderate"),
        (100, "moderate"),             # upper edge of "Orta"
        (101, "unhealthy_sensitive"),
        (150, "unhealthy_sensitive"),
        (151, "unhealthy"),
        (200, "unhealthy"),
        (201, "very_unhealthy"),
        (300, "very_unhealthy"),
        (301, "hazardous"),
        (500, "hazardous"),
        (501, "hazardous"),            # above the scale, still the worst band
    ],
)
def test_aqi_band_boundaries(index: float, expected_key: str) -> None:
    band = aqi_band(index)
    assert band is not None
    label, key = band
    assert key == expected_key
    assert label  # every band carries Turkish user-facing text


def test_aqi_band_of_none_is_none() -> None:
    assert aqi_band(None) is None


@pytest.mark.parametrize(
    ("index", "expected"),
    [(1, "akıcı"), (20, "akıcı"), (21, "hafif yoğun"), (40, "hafif yoğun"),
     (41, "yoğun"), (60, "yoğun"), (61, "çok yoğun"), (80, "çok yoğun"), (81, "kilitli"), (99, "kilitli")],
)
def test_describe_traffic(index: int, expected: str) -> None:
    assert describe_traffic(index) == expected


# ---------------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------------
def test_provenance_age_prefers_reported_at_over_observed_at() -> None:
    prov = Provenance(
        source="ispark",
        source_url="https://api.ibb.gov.tr/ispark/Park",
        observed_at=utcnow(),
        reported_at=utcnow() - dt.timedelta(minutes=10),
    )
    assert prov.age_seconds == pytest.approx(600, abs=5)


def test_provenance_age_falls_back_to_observed_at() -> None:
    prov = Provenance(source="metro_status", source_url="x", observed_at=utcnow() - dt.timedelta(seconds=45))
    assert prov.reported_at is None
    assert prov.age_seconds == pytest.approx(45, abs=5)


def test_provenance_age_never_goes_negative() -> None:
    """A clock skew upstream must not produce "-3 dk önce" in the answer."""
    prov = Provenance(source="iett", source_url="x", reported_at=utcnow() + dt.timedelta(minutes=5))
    assert prov.age_seconds == 0.0


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0 sn önce"), (45, "45 sn önce"), (89, "89 sn önce"), (90, "1 dk önce"),
     (600, "10 dk önce"), (5399, "89 dk önce"), (5400, "1.5 saat önce"), (7200, "2.0 saat önce")],
)
def test_provenance_describe_age(seconds: int, expected: str) -> None:
    prov = Provenance(source="x", source_url="x", reported_at=utcnow() - dt.timedelta(seconds=seconds))
    assert prov.describe_age() == expected


def test_provenance_carries_the_ibb_licence_by_default() -> None:
    prov = Provenance(source="ispark", source_url="https://api.ibb.gov.tr/ispark/Park")
    assert "CC BY 4.0" in prov.license
    assert prov.cached is False


# ---------------------------------------------------------------------------------
# İSPARK
# ---------------------------------------------------------------------------------
def test_parking_lot_from_raw_over_the_whole_park_fixture(load_fixture) -> None:
    raw = load_fixture("ispark_park")
    lots = [ParkingLot.from_raw(row) for row in raw]

    assert len(lots) == len(raw)
    assert len(lots) >= 40
    for lot, row in zip(lots, raw, strict=True):
        assert lot.park_id == int(row["parkID"])
        assert lot.name
        assert_in_istanbul(lot.lat, lot.lon)
        assert lot.capacity is None or lot.capacity > 0
        assert lot.empty is not None and lot.empty >= 0
    assert {lot.park_type for lot in lots} <= {"KAPALI OTOPARK", "AÇIK OTOPARK", "YOL ÜSTÜ"}


def test_parking_lot_parses_the_first_park_record(load_fixture) -> None:
    lot = ParkingLot.from_raw(load_fixture("ispark_park")[0])
    assert lot.park_id == 3068
    assert lot.name == "15 Temmuz Şehitler Meydanı Zeminaltı Otoparkı"
    assert lot.lat == pytest.approx(41.0246) and lot.lon == pytest.approx(29.0915)
    assert (lot.capacity, lot.empty) == (1029, 506)
    assert lot.park_type == "KAPALI OTOPARK"
    assert lot.district == "ÜMRANİYE"
    assert lot.free_minutes == 15
    assert lot.is_open is True
    # The Park list carries no detail fields; those only arrive from ParkDetay.
    assert lot.updated_at is None and lot.tariff is None and lot.address is None


def test_parking_lot_is_open_flag_maps_zero_and_one(load_fixture) -> None:
    raw = load_fixture("ispark_park")
    for row in raw:
        assert ParkingLot.from_raw(row).is_open is bool(row["isOpen"])
    assert any(row["isOpen"] == 0 for row in raw), "fixture should contain at least one closed lot"


def test_parking_lot_occupancy_pct() -> None:
    lot = ParkingLot(park_id=1, name="x", capacity=1029, empty=506)
    assert lot.occupancy_pct == pytest.approx(50.8)
    assert ParkingLot(park_id=1, name="x", capacity=None, empty=5).occupancy_pct is None
    assert ParkingLot(park_id=1, name="x", capacity=100, empty=None).occupancy_pct is None
    assert ParkingLot(park_id=1, name="x", capacity=100, empty=0).occupancy_pct == 100.0


def test_parking_lot_from_parkdetay_fixture(load_fixture) -> None:
    raw = load_fixture("ispark_parkdetay")
    assert isinstance(raw, list) and len(raw) == 1  # ParkDetay always returns a 1-element list
    lot = ParkingLot.from_raw(raw[0])

    assert lot.park_id == 3068
    assert lot.updated_at == dt.datetime(2026, 9, 8, 6, 5, 16, tzinfo=UTC)
    assert lot.monthly_fee == pytest.approx(3500.0)
    assert lot.address == "ÜMRANİYE 15 TEMMUZ ŞEHİTLER MEYDANI"
    # The tariff is free text and is deliberately shown, never parsed.
    assert lot.tariff is not None and lot.tariff.startswith("0-1 Saat : 110,00")
    assert_in_istanbul(lot.lat, lot.lon)
    assert lot.occupancy_pct == pytest.approx(50.8)


# ---------------------------------------------------------------------------------
# İETT — live positions
# ---------------------------------------------------------------------------------
def test_bus_position_from_line_raw_over_the_whole_500t_fixture(load_fixture) -> None:
    raw = load_fixture("iett_hat_500T")
    buses = [BusPosition.from_line_raw(row) for row in raw]

    assert len(buses) == len(raw)
    assert len(buses) >= 31
    for bus in buses:
        assert bus.door_no
        assert_in_istanbul(bus.lat, bus.lon)
        assert bus.line_code == "500T"
        assert bus.reported_at is not None and bus.reported_at.utcoffset() == dt.timedelta(0)
        # The join key into GTFS stops.stop_code; 31/31 matched when this was captured.
        assert bus.nearest_stop_code and bus.nearest_stop_code.isdigit()
    assert {bus.route_code for bus in buses} == {"500T_G_D0", "500T_D_D0"}


def test_bus_position_parses_the_first_500t_record(load_fixture) -> None:
    bus = BusPosition.from_line_raw(load_fixture("iett_hat_500T")[0])
    assert bus.door_no == "C-338"
    assert bus.lat == pytest.approx(40.83712) and bus.lon == pytest.approx(29.36051)
    assert bus.route_code == "500T_G_D0"
    assert bus.line_name == "TUZLA ŞİFA MAHALLESİ - 4. LEVENT METRO"
    assert bus.direction == "4.LEVENT METRO"
    assert bus.nearest_stop_code == "228421"
    assert bus.reported_at == dt.datetime(2026, 9, 8, 6, 8, 53, tzinfo=UTC)
    # A per-line query carries no speed and no operator.
    assert bus.speed_kmh is None and bus.operator is None


def test_bus_position_from_fleet_raw_over_the_whole_fleet_fixture(load_fixture) -> None:
    raw = load_fixture("iett_fleet")
    buses = [BusPosition.from_fleet_raw(row) for row in raw]

    assert len(buses) == len(raw)
    for bus in buses:
        assert bus.door_no
        assert_in_istanbul(bus.lat, bus.lon)
        assert bus.speed_kmh is not None and bus.speed_kmh >= 0
        assert bus.reported_at is not None and bus.reported_at.utcoffset() == dt.timedelta(0)
        # The fleet snapshot says nothing about which line a bus is running.
        assert bus.line_code is None and bus.route_code is None and bus.nearest_stop_code is None


def test_bus_position_parses_the_first_fleet_record(load_fixture) -> None:
    bus = BusPosition.from_fleet_raw(load_fixture("iett_fleet")[0])
    assert bus.door_no == "A-001"
    assert bus.lat == pytest.approx(41.13926) and bus.lon == pytest.approx(29.05611)
    assert bus.speed_kmh == pytest.approx(15.0)
    assert bus.operator == "İstanbul Halk Ulaşım Tic.A.Ş"
    local = bus.reported_at.astimezone(ISTANBUL_TZ)
    assert (local.hour, local.minute, local.second) == (9, 8, 55)


def test_fleet_parsing_never_exposes_the_number_plate(load_fixture) -> None:
    """Privacy guarantee from NOTICE.md: bus plates are dropped at parse time.

    The İETT fleet feed ships ``Plaka`` for every vehicle. It must not reach the model,
    the lake or an API response — the door number is the only vehicle identifier we use.
    """
    raw = load_fixture("iett_fleet")
    plates = [row["Plaka"] for row in raw if row.get("Plaka")]
    assert plates, "fixture must actually contain plates, otherwise this test proves nothing"

    # No field, on the class or on an instance, is a plate.
    assert "plate" not in BusPosition.model_fields
    assert not [name for name in BusPosition.model_fields if "plaka" in name.lower() or "plate" in name.lower()]

    for row in raw:
        plate = row["Plaka"]
        bus = BusPosition.from_fleet_raw(row)
        dumped = bus.model_dump()
        assert "plate" not in dumped and "plaka" not in {key.lower() for key in dumped}
        serialised = json.dumps(dumped, default=str, ensure_ascii=False)
        assert plate not in serialised
        assert plate.replace(" ", "") not in serialised.replace(" ", "")
        assert plate not in bus.model_dump_json()


# ---------------------------------------------------------------------------------
# İETT — planned departures
# ---------------------------------------------------------------------------------
def test_planned_departure_over_the_whole_fixture(load_fixture) -> None:
    raw = load_fixture("iett_planlanan")
    departures = [PlannedDeparture.from_raw(row) for row in raw]

    assert len(departures) == len(raw)
    assert len(departures) >= 40
    for departure in departures:
        assert departure.line_code == "500T"
        assert departure.day_type in {"I", "C", "P"}
        assert departure.direction in {"D", "G"}
        assert departure.departure_time is not None
        hours, minutes = departure.departure_time.split(":")
        assert 0 <= int(hours) <= 29 and 0 <= int(minutes) <= 59


def test_planned_departure_parses_the_first_record(load_fixture) -> None:
    departure = PlannedDeparture.from_raw(load_fixture("iett_planlanan")[0])
    assert departure.line_code == "500T"
    assert departure.route_code == "500T_D_D0"
    assert departure.line_name == "TUZLA ŞİFA MAHALLESİ - CEVİZLİBAĞ"
    assert departure.direction == "D"
    assert departure.day_type == "C"          # Cumartesi
    assert departure.departure_time == "05:50"
    assert departure.service_type == "ÖHO"


def test_planned_departure_tolerates_missing_optional_fields() -> None:
    departure = PlannedDeparture.from_raw(
        {"SHATKODU": "500T", "SGUZERAH": None, "HATADI": None, "SYON": "G",
         "SGUNTIPI": "I", "GUZERGAH_ISARETI": None, "SSERVISTIPI": None, "DT": "06:10"}
    )
    assert departure.line_code == "500T"
    assert departure.route_code is None and departure.line_name is None and departure.service_type is None
    assert departure.departure_time == "06:10"


# ---------------------------------------------------------------------------------
# Metro İstanbul
# ---------------------------------------------------------------------------------
def test_metro_status_fixture_shape(load_fixture) -> None:
    payload = load_fixture("metro_status")
    assert payload["Success"] is True and payload["Error"] is None
    assert isinstance(payload["Data"], list) and payload["Data"]


@pytest.mark.xfail(
    raises=AttributeError,
    reason=(
        "models.MetroLineStatus.from_raw assumes LineColor is a string, but the live "
        "GetServiceStatuses payload returns {'Color_R','Color_G','Color_B'}. "
        "Owner of models.py must guard the field; this test flips to XPASS when fixed."
    ),
)
def test_metro_line_status_over_the_whole_fixture(load_fixture) -> None:
    raw = load_fixture("metro_status")["Data"]
    statuses = [MetroLineStatus.from_raw(row) for row in raw]

    assert len(statuses) == len(raw)
    for status in statuses:
        assert status.line_name
        assert status.description
        assert status.updated_at is not None and status.updated_at.utcoffset() == dt.timedelta(0)


def test_metro_line_status_parses_the_live_disruption(load_fixture) -> None:
    raw = dict(load_fixture("metro_status")["Data"][0])
    raw.pop("LineColor")  # see the xfail above: the colour object breaks from_raw today
    status = MetroLineStatus.from_raw(raw)

    assert status.line_id == 7
    assert status.line_name == "M7"
    assert status.is_active is True
    assert status.description is not None and "Onarım çalışması" in status.description
    assert status.updated_at == dt.datetime(2026, 7, 27, 6, 27, 37, 103000, tzinfo=UTC)


def test_metro_station_over_the_whole_fixture(load_fixture) -> None:
    raw = load_fixture("metro_stations")["Data"]
    stations = [MetroStation.from_raw(row) for row in raw]

    assert len(stations) == len(raw)
    assert len(stations) >= 248
    for station in stations:
        assert station.station_id is not None
        assert station.name
        assert station.line_name
        assert station.order is not None and station.order >= 1
        assert station.lifts is not None and station.lifts >= 0
        assert station.escalators is not None and station.escalators >= 0
        if station.lat is not None or station.lon is not None:
            assert_in_istanbul(station.lat, station.lon)

    located = [s for s in stations if s.lat is not None]
    assert len(located) >= len(stations) - 5  # three M5 stations ship null coordinates
    assert {"M2", "M4", "M7", "T1"} <= {s.line_name for s in stations}


def test_metro_station_prefers_the_display_description_over_the_uppercase_name(load_fixture) -> None:
    raw = load_fixture("metro_stations")["Data"][0]
    assert raw["Name"] == "YENIKAPI" and raw["Description"] == "Yenikapı"
    station = MetroStation.from_raw(raw)
    assert station.name == "Yenikapı"  # the nice form is what a user sees
    assert station.station_id == 20
    assert station.line_name == "M2"
    assert station.order == 1
    assert station.escalators == 14 and station.lifts == 4
    assert station.wc is True and station.baby_room is False and station.masjid is False
    assert_in_istanbul(station.lat, station.lon)


def test_metro_station_accessibility_for_kartal(load_fixture) -> None:
    """J3 in the plan: "M4'te arıza var mı? Kartal'da asansör var mı?"."""
    stations = [MetroStation.from_raw(row) for row in load_fixture("metro_stations")["Data"]]
    kartal = next(s for s in stations if s.name == "Kartal" and s.line_name == "M4")
    assert kartal.lifts == 5
    assert kartal.step_free is True


def test_metro_station_step_free_is_none_when_lift_data_is_missing() -> None:
    assert MetroStation.from_raw({"Id": 1, "Description": "X", "DetailInfo": {}}).step_free is None
    assert MetroStation.from_raw({"Id": 1, "Description": "X", "DetailInfo": {"Lift": 0}}).step_free is False


# ---------------------------------------------------------------------------------
# Traffic index
# ---------------------------------------------------------------------------------
def test_traffic_index_over_the_whole_fixture(load_fixture) -> None:
    raw = load_fixture("traffic_index_1h")
    points = [TrafficIndexPoint.from_raw(row) for row in raw]

    assert len(points) == len(raw)
    assert len(points) >= 24  # a 24 hour window at hourly resolution
    for point in points:
        assert 1 <= point.index <= 99  # İBB documents the index as 1–99
        assert point.at is not None and point.at.utcoffset() == dt.timedelta(0)
        assert describe_traffic(point.index)


def test_traffic_index_parses_the_newest_point(load_fixture) -> None:
    point = TrafficIndexPoint.from_raw(load_fixture("traffic_index_1h")[0])
    assert point.index == 60
    assert point.at == dt.datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
    assert describe_traffic(point.index) == "yoğun"


def test_traffic_index_points_are_ordered_newest_first(load_fixture) -> None:
    points = [TrafficIndexPoint.from_raw(row) for row in load_fixture("traffic_index_1h")]
    times = [p.at for p in points]
    assert times == sorted(times, reverse=True)


# ---------------------------------------------------------------------------------
# Air quality
# ---------------------------------------------------------------------------------
def test_air_quality_stations_over_the_whole_fixture(load_fixture) -> None:
    raw = load_fixture("aq_stations")
    stations = [AirQualityStation.from_raw(row) for row in raw]

    assert len(stations) == len(raw)
    assert len(stations) == 28  # İBB publishes 28 AQI stations
    for station in stations:
        assert len(station.station_id) == 36  # GUID
        assert station.name
        assert_in_istanbul(station.lat, station.lon)
    assert len({s.station_id for s in stations}) == len(stations)


def test_air_quality_station_parses_maslak(load_fixture) -> None:
    station = AirQualityStation.from_raw(load_fixture("aq_stations")[0])
    assert station.station_id == "6b7a9840-1e13-4045-a79d-0f881c4852ad"
    assert station.name == "Maslak"
    assert station.address is not None and "Sarıyer" in station.address
    assert station.lat == pytest.approx(41.1000, abs=0.001)
    assert station.lon == pytest.approx(29.0245, abs=0.001)


def test_air_quality_readings_over_the_whole_fixture(load_fixture) -> None:
    raw = load_fixture("aq_readings")
    readings = [AirQualityReading.from_raw(row) for row in raw]

    assert len(readings) == len(raw)
    assert len(readings) >= 72  # three days, hourly
    for reading in readings:
        assert reading.read_time is not None and reading.read_time.utcoffset() == dt.timedelta(0)
        assert reading.pm10 is not None and reading.pm10 >= 0
        assert reading.aqi_index is not None
        assert aqi_band(reading.aqi_index) is not None
    # The endpoint's EndDate is inclusive, so callers dedupe on (station, ReadTime);
    # within one window the timestamps are already unique.
    assert len({r.read_time for r in readings}) == len(readings)


def test_air_quality_reading_parses_the_first_hour(load_fixture) -> None:
    reading = AirQualityReading.from_raw(load_fixture("aq_readings")[0])
    assert reading.read_time == dt.datetime(2026, 9, 5, 6, 0, tzinfo=UTC)
    assert reading.pm10 == pytest.approx(47.3)
    assert reading.so2 == pytest.approx(3.0)
    assert reading.o3 == pytest.approx(26.2)
    assert reading.no2 == pytest.approx(24.4)
    assert reading.co is None  # CO is routinely null in this feed
    assert reading.aqi_index == pytest.approx(19.0)
    assert reading.dominant == "PM10"
    assert reading.color == "#13a261"
    assert aqi_band(reading.aqi_index) == ("İyi", "good")


def test_air_quality_index_lags_hourly_pm10(load_fixture) -> None:
    """İBB computes the PM10 sub-index over a rolling 24-hour mean.

    Anything that needs an hour-by-hour signal must read ``pm10``, not ``aqi_index``;
    this test pins the discrepancy so nobody "fixes" the forecast by using the index.
    """
    readings = [AirQualityReading.from_raw(row) for row in load_fixture("aq_readings")]
    worst = max(readings, key=lambda r: r.pm10 or 0.0)
    assert worst.pm10 is not None and worst.aqi_index is not None
    assert worst.aqi_index < worst.pm10


def test_air_quality_reading_handles_a_missing_payload() -> None:
    reading = AirQualityReading.from_raw({"ReadTime": None, "Concentration": None, "AQI": None})
    assert reading.read_time is None
    assert reading.pm10 is None and reading.aqi_index is None and reading.dominant is None
