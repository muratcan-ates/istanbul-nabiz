"""Tests for the proactive alert engine (epic E2).

Three things are being proved here, in order of how much they matter:

1. **No false alarms.** Every rule stays silent when the number it needs is missing. A
   pushed alert that fires because İBB was unreachable teaches the user to ignore alerts.
2. **Privacy is structural.** The last section proves, by capturing every log record and by
   forbidding writes, that a subscription's coordinates never reach a log line or a file.
   That is the property ``docs/privacy.md`` promises, tested rather than asserted.
3. **Thresholds and dedupe keys behave.** Boundaries fire, dedupe keys are stable across
   evaluations and move when the news moves.
"""

from __future__ import annotations

import builtins
import datetime as dt
import logging
import pathlib
import re

import pytest

from ibb_mcp.models import (
    AirQualityReading,
    AirQualityStation,
    MetroLineStatus,
    ParkingLot,
    Provenance,
    TrafficIndexPoint,
    utcnow,
)
from ibb_mcp.sources.base import SourceContext
from nabiz.alerts.engine import (
    MAX_COOLDOWN_S,
    MIN_COOLDOWN_S,
    build_context,
    check_alerts,
    describe_subscription,
    evaluate_subscription,
    parse_subscription,
)
from nabiz.alerts.rules import (
    AirQualityObservation,
    AirQualityRule,
    AlertContext,
    BunchingObservation,
    BusBunchingRule,
    MetroDisruptionRule,
    MetroObservation,
    ParkingFillingRule,
    ParkingObservation,
    TrafficObservation,
    TrafficRule,
)

ALERTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "src" / "nabiz" / "alerts"

# Coordinates used only by the privacy tests. Distinctive on purpose: if any of these digit
# strings shows up in a log record or a file, something leaked.
SECRET_LAT = 40.9123
SECRET_LON = 29.1876
SECRET_LABEL = "Evim - Kartal Yakacık"


def prov(source: str = "test", *, minutes_ago: float = 3.0) -> Provenance:
    return Provenance(
        source=source,
        source_url=f"https://example.invalid/{source}",
        reported_at=utcnow() - dt.timedelta(minutes=minutes_ago),
    )


def lot(park_id: int = 100, *, capacity: int | None = 200, empty: int | None = 10, is_open: bool | None = True) -> ParkingLot:
    return ParkingLot(park_id=park_id, name=f"Test Otoparkı {park_id}", capacity=capacity, empty=empty, is_open=is_open)


def parking_ctx(*lots: ParkingLot) -> AlertContext:
    provenance = prov("ispark")
    return AlertContext(parking={item.park_id: ParkingObservation(lot=item, provenance=provenance) for item in lots})


def metro_ctx(*statuses: MetroLineStatus) -> AlertContext:
    return AlertContext(metro=MetroObservation(statuses=tuple(statuses), provenance=prov("metro_status")))


def notice(line: str = "M4", description: str = "Arıza nedeniyle seferler aksamaktadır.") -> MetroLineStatus:
    return MetroLineStatus(line_id=4, line_name=line, description=description, updated_at=utcnow() - dt.timedelta(minutes=8))


def aq_ctx(
    *,
    index: float | None = 120.0,
    pm10: float | None = 88.4,
    dominant: str = "PM10",
    place_key: str = "home",
    label: str = "Kartal",
    reading: bool = True,
) -> AlertContext:
    station = AirQualityStation(station_id="abc", name="Kartal", lat=40.9, lon=29.19, distance_km=1.4)
    measurement = (
        AirQualityReading(read_time=utcnow() - dt.timedelta(minutes=20), pm10=pm10, aqi_index=index, dominant=dominant)
        if reading
        else None
    )
    return AlertContext(
        air_quality={
            place_key: AirQualityObservation(
                place_key=place_key,
                place_label=label,
                station=station,
                reading=measurement,
                provenance=prov("aq_readings"),
            )
        }
    )


def traffic_ctx(index: int | None) -> AlertContext:
    point = TrafficIndexPoint(index=index, at=utcnow() - dt.timedelta(minutes=5)) if index is not None else None
    return AlertContext(traffic=TrafficObservation(point=point, provenance=prov("traffic")))


def subscription(**overrides) -> dict:
    """A full, valid subscription — the shape the browser keeps in localStorage."""
    base = {
        "version": 1,
        "places": [{"key": "home", "label": SECRET_LABEL, "lat": SECRET_LAT, "lon": SECRET_LON}],
        "rules": [
            {"kind": "metro_disruption", "lines": ["M4"]},
            {"kind": "parking_filling", "park_ids": [100], "threshold_pct": 85},
            {"kind": "air_quality", "place": "home", "aqi_threshold": 100},
            {"kind": "traffic", "threshold_index": 60},
        ],
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------------------
# 1. metro
# --------------------------------------------------------------------------------------
def test_metro_rule_fires_for_a_watched_line() -> None:
    alert = MetroDisruptionRule(lines=("M4",)).evaluate(metro_ctx(notice("M4")))
    assert alert is not None
    assert alert.severity == "warning"
    assert "M4" in alert.message_tr
    assert "aksaklık" in alert.message_tr
    assert "Arıza nedeniyle seferler aksamaktadır." in alert.message_tr
    assert "disruption" in alert.message_en.lower()
    assert alert.citations and all(citation.provenance.source_url for citation in alert.citations)


def test_metro_rule_is_silent_for_a_line_the_user_does_not_watch() -> None:
    assert MetroDisruptionRule(lines=("M4",)).evaluate(metro_ctx(notice("M7"))) is None


def test_metro_rule_is_silent_when_no_line_has_a_notice() -> None:
    # An empty response is the documented "bildirilmiş aksaklık yok" — not an alert.
    assert MetroDisruptionRule(lines=("M4",)).evaluate(metro_ctx()) is None


def test_metro_rule_is_silent_when_the_service_could_not_be_read() -> None:
    # ctx.metro is None: unknown, not "fine" and not "broken". Absent data never fires.
    assert MetroDisruptionRule(lines=("M4",)).evaluate(AlertContext()) is None


def test_metro_line_matching_ignores_case_and_turkish_folding() -> None:
    assert MetroDisruptionRule(lines=("m4",)).evaluate(metro_ctx(notice("M4"))) is not None


def test_metro_dedupe_key_is_stable_and_follows_the_notice_text() -> None:
    rule = MetroDisruptionRule(lines=("M4",))
    first = rule.evaluate(metro_ctx(notice("M4")))
    second = rule.evaluate(metro_ctx(notice("M4")))
    changed = rule.evaluate(metro_ctx(notice("M4", "Çalışma tamamlandı, seferler normale döndü.")))
    assert first.dedupe_key == second.dedupe_key  # same news, one notification
    assert changed.dedupe_key != first.dedupe_key  # new news gets through the cooldown
    assert "utcnow" not in first.dedupe_key and not re.search(r"20\d\d", first.dedupe_key)


# --------------------------------------------------------------------------------------
# 2. parking
# --------------------------------------------------------------------------------------
def test_parking_rule_fires_exactly_at_the_threshold() -> None:
    # 200 capacity, 30 free -> 85.0% occupancy, the boundary itself.
    alert = ParkingFillingRule(park_ids=(100,), threshold_pct=85).evaluate(parking_ctx(lot(empty=30)))
    assert alert is not None
    assert "%85 dolu" in alert.message_tr
    assert "(200 yerin 30 tanesi boş)" in alert.message_tr
    assert alert.severity == "warning"


def test_parking_rule_is_silent_one_space_below_the_threshold() -> None:
    # 31 free -> 84.5%, just under. The boundary must not be fuzzy.
    assert ParkingFillingRule(park_ids=(100,), threshold_pct=85).evaluate(parking_ctx(lot(empty=31))) is None


def test_parking_rule_skips_a_lot_with_no_capacity_figure() -> None:
    assert ParkingFillingRule(park_ids=(100,)).evaluate(parking_ctx(lot(capacity=None, empty=None))) is None


def test_parking_rule_skips_a_lot_that_is_not_reported_open() -> None:
    # A closed car park is not news about filling up, and "unknown" counts as not open.
    assert ParkingFillingRule(park_ids=(100,)).evaluate(parking_ctx(lot(empty=0, is_open=False))) is None
    assert ParkingFillingRule(park_ids=(100,)).evaluate(parking_ctx(lot(empty=0, is_open=None))) is None


def test_parking_rule_is_silent_when_the_watched_lot_is_absent_from_the_snapshot() -> None:
    assert ParkingFillingRule(park_ids=(999,)).evaluate(parking_ctx(lot(100, empty=0))) is None


def test_parking_escalation_to_critical_changes_the_dedupe_key() -> None:
    rule = ParkingFillingRule(park_ids=(100,), threshold_pct=85)
    warning = rule.evaluate(parking_ctx(lot(empty=30)))
    critical = rule.evaluate(parking_ctx(lot(empty=0)))
    assert warning.severity == "warning" and critical.severity == "critical"
    # Different keys, so the user hears about "full" even inside the earlier cooldown.
    assert warning.dedupe_key != critical.dedupe_key
    assert rule.evaluate(parking_ctx(lot(empty=0))).dedupe_key == critical.dedupe_key


def test_parking_citations_cover_every_number_in_the_message() -> None:
    alert = ParkingFillingRule(park_ids=(100,), threshold_pct=85).evaluate(parking_ctx(lot(empty=30)))
    labels = {citation.label for citation in alert.citations}
    assert labels == {"Test Otoparkı 100 doluluk", "Test Otoparkı 100 boş yer"}
    assert [citation.value for citation in alert.citations] == [85.0, 30]
    assert len(alert.provenance) == len(alert.citations)
    assert all(p.source == "ispark" for p in alert.provenance)


# --------------------------------------------------------------------------------------
# 3. air quality
# --------------------------------------------------------------------------------------
def test_air_quality_fires_above_the_threshold_with_the_turkish_band() -> None:
    alert = AirQualityRule(place="home", aqi_threshold=100).evaluate(aq_ctx(index=120))
    assert alert is not None
    assert "Kartal çevresinde hava kalitesi indeksi 120" in alert.message_tr
    assert "Hassas gruplar için sağlıksız" in alert.message_tr
    assert "Sağlık tavsiyesi değildir." in alert.message_tr
    assert "Not health advice." in alert.message_en
    assert alert.severity == "warning"


def test_air_quality_boundary_fires_at_the_threshold_and_not_below() -> None:
    rule = AirQualityRule(place="home", aqi_threshold=100)
    assert rule.evaluate(aq_ctx(index=100)) is not None
    assert rule.evaluate(aq_ctx(index=99.9)) is None


def test_air_quality_is_silent_without_a_reading_or_an_index() -> None:
    rule = AirQualityRule(place="home", aqi_threshold=50)
    assert rule.evaluate(aq_ctx(reading=False)) is None
    assert rule.evaluate(aq_ctx(index=None)) is None
    assert rule.evaluate(AlertContext()) is None  # station never resolved
    assert rule.evaluate(aq_ctx(place_key="work")) is None  # a different place's reading


def test_air_quality_message_says_the_pm10_index_is_a_24_hour_mean() -> None:
    # Verified İBB fact: AQIIndex for PM10 is a rolling 24-hour mean, so the alert must not
    # be read as an instantaneous value.
    pm10_alert = AirQualityRule(place="home", aqi_threshold=100).evaluate(aq_ctx(index=140, dominant="PM10"))
    o3_alert = AirQualityRule(place="home", aqi_threshold=100).evaluate(aq_ctx(index=140, dominant="O3"))
    assert "24 saatlik yürüyen ortalamadır" in pm10_alert.message_tr
    assert "rolling 24-hour mean" in pm10_alert.message_en
    assert "24 saatlik" not in o3_alert.message_tr


def test_air_quality_dedupe_key_tracks_the_band_not_the_exact_index() -> None:
    rule = AirQualityRule(place="home", aqi_threshold=100)
    first = rule.evaluate(aq_ctx(index=120))
    wobble = rule.evaluate(aq_ctx(index=133))  # same band: one notification
    worse = rule.evaluate(aq_ctx(index=180))  # next band up: a new notification
    assert first.dedupe_key == wobble.dedupe_key == "air:home:unhealthy_sensitive"
    assert worse.dedupe_key == "air:home:unhealthy"
    assert worse.severity == "critical"


# --------------------------------------------------------------------------------------
# 4. traffic
# --------------------------------------------------------------------------------------
def test_traffic_rule_fires_at_the_threshold_and_names_the_band() -> None:
    alert = TrafficRule(threshold_index=60).evaluate(traffic_ctx(60))
    assert alert is not None
    assert "trafik yoğunluk indeksi 60 (yoğun)" in alert.message_tr
    assert "(busy)" in alert.message_en
    assert alert.citations[0].value == 60
    assert alert.severity == "warning"


def test_traffic_rule_is_silent_below_the_threshold_and_without_a_reading() -> None:
    assert TrafficRule(threshold_index=60).evaluate(traffic_ctx(59)) is None
    assert TrafficRule(threshold_index=60).evaluate(traffic_ctx(None)) is None
    assert TrafficRule(threshold_index=60).evaluate(AlertContext()) is None


def test_traffic_gridlock_is_critical() -> None:
    alert = TrafficRule(threshold_index=60, critical_index=80).evaluate(traffic_ctx(85))
    assert alert.severity == "critical"
    assert "kilitli" in alert.message_tr


# --------------------------------------------------------------------------------------
# 5. bus bunching (optional rule)
# --------------------------------------------------------------------------------------
def bunching_ctx(**overrides) -> AlertContext:
    fields = {
        "line_code": "500T",
        "bunched": True,
        "hour": 18,
        "label": "kümelenme var",
        "headway_cv": 0.72,
        "median_headway_min": 9.0,
        "samples": 41,
        "window_note": "Ölçüm penceresi: 2 gün, 30.5 saatlik gözlem.",
        "provenance": prov("nabiz_reliability"),
    }
    fields.update(overrides)
    return AlertContext(bunching={"500T": BunchingObservation(**fields)})


def test_bus_bunching_fires_and_says_it_is_a_history_figure() -> None:
    alert = BusBunchingRule(line="500t").evaluate(bunching_ctx())
    assert alert is not None
    assert "500T hattında saat 18 civarında ölçülen sefer aralıkları düzensiz" in alert.message_tr
    assert "ortanca aralık 9 dk" in alert.message_tr
    assert "canlı bir arıza bildirimi değildir" in alert.message_tr  # honest about what it is
    assert "Ölçüm penceresi: 2 gün" in alert.message_tr
    assert alert.dedupe_key == "bunching:500T:18"
    assert {c.label for c in alert.citations} == {"Ortanca sefer aralığı", "Aralık değişkenliği (cv)", "Gözlem sayısı"}


def test_bus_bunching_is_silent_without_data_or_provenance() -> None:
    rule = BusBunchingRule(line="500T")
    assert rule.evaluate(AlertContext()) is None  # nothing measured
    assert rule.evaluate(bunching_ctx(bunched=False)) is None  # measured and regular
    # A number we cannot attribute is a number we do not say.
    assert rule.evaluate(bunching_ctx(provenance=None)) is None
    assert rule.evaluate(bunching_ctx(samples=0)) is None


async def test_bunching_context_is_built_from_the_real_reliability_table(
    monkeypatch: pytest.MonkeyPatch, ctx: SourceContext
) -> None:
    """Drive the adapter against ``ibb_mcp.reliability`` itself, when that module is present.

    It is written on another branch, so the test skips rather than fails when it is absent —
    but while it exists, this proves our adapter speaks its real vocabulary.
    """
    reliability = pytest.importorskip("ibb_mcp.reliability")
    table = reliability.ReliabilityTable(
        cells=[
            reliability.LineHourStats(
                line_code="500T",
                hour=dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).hour,
                available=True,
                samples=41,
                vehicles_seen=6,
                median_headway_min=9.0,
                headway_cv=0.72,
                bunching_label=reliability.LABEL_BUNCHED,
            )
        ],
        observed_from=utcnow() - dt.timedelta(days=2),
        observed_to=utcnow() - dt.timedelta(minutes=30),
        days_covered=["2026-09-11", "2026-09-12"],
    )
    monkeypatch.setattr("nabiz.alerts.engine._reliability_table", lambda: (table, None))
    payload = subscription(rules=[{"kind": "bus_bunching", "line": "500T"}])
    result = await check_alerts(ctx, payload)
    assert result["alert_count"] == 1
    alert = result["alerts"][0]
    assert alert["kind"] == "bus_bunching"
    assert "kümelenme var" in alert["message_tr"]
    assert "(bunched)" in alert["message_en"]  # the Turkish verdict is translated, not pasted
    citation = alert["citations"][0]
    assert citation["provenance"]["source"] == "nabiz_reliability"
    # The citation goes to every client: it must name the file, not this machine's home dir.
    assert citation["provenance"]["source_url"] == "local:data/reference/line_reliability.json"
    assert "/Users/" not in citation["provenance"]["source_url"]


async def test_bunching_reports_why_it_is_unavailable_instead_of_firing(
    ctx: SourceContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silence must come with a reason, whether the module, the table or the cell is missing."""
    payload = subscription(rules=[{"kind": "bus_bunching", "line": "500T"}])

    monkeypatch.setattr("nabiz.alerts.engine.reliability_module", lambda: None)
    no_module = await check_alerts(ctx, payload)
    assert no_module["alerts"] == []
    assert "modül" in no_module["unavailable"]["reliability"]
    monkeypatch.undo()

    monkeypatch.setattr("nabiz.alerts.engine._reliability_table", lambda: (None, "Tablo henüz üretilmedi."))
    no_table = await check_alerts(ctx, payload)
    assert no_table["alerts"] == []
    assert no_table["unavailable"]["reliability"] == "Tablo henüz üretilmedi."


async def test_a_cell_the_reliability_module_refuses_to_score_produces_no_alert(
    ctx: SourceContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``available: False`` means "not measurable", never "no bunching" — and never an alert."""
    reliability = pytest.importorskip("ibb_mcp.reliability")
    hour = dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).hour
    table = reliability.ReliabilityTable(
        cells=[
            reliability.LineHourStats(
                line_code="500T",
                hour=hour,
                available=False,
                samples=3,
                reason="3 sefer aralığı ölçülebildi, en az 12 gerekiyor.",
            )
        ]
    )
    monkeypatch.setattr("nabiz.alerts.engine._reliability_table", lambda: (table, None))
    result = await check_alerts(ctx, subscription(rules=[{"kind": "bus_bunching", "line": "500T"}]))
    assert result["alerts"] == []
    assert "düzenlilik verisi yok" in result["unavailable"]["reliability"]


# --------------------------------------------------------------------------------------
# 6. engine
# --------------------------------------------------------------------------------------
def full_ctx() -> AlertContext:
    """One snapshot in which every rule of :func:`subscription` has something to say."""
    return AlertContext(
        metro=MetroObservation(statuses=(notice("M4"),), provenance=prov("metro_status")),
        parking={100: ParkingObservation(lot=lot(empty=0), provenance=prov("ispark"))},
        air_quality=aq_ctx(index=120).air_quality,
        traffic=TrafficObservation(point=TrafficIndexPoint(index=75, at=utcnow()), provenance=prov("traffic")),
    )


def test_engine_evaluates_a_whole_subscription_worst_first() -> None:
    alerts = evaluate_subscription(subscription(), full_ctx())
    assert [alert.kind for alert in alerts][:1] == ["parking_filling"]  # the only critical one
    assert {alert.kind for alert in alerts} == {"metro_disruption", "parking_filling", "air_quality", "traffic"}
    severities = [alert.severity for alert in alerts]
    assert severities == sorted(severities, key=lambda s: {"critical": 0, "warning": 1, "info": 2}[s])
    assert all(alert.cooldown_seconds >= MIN_COOLDOWN_S for alert in alerts)


def test_engine_drops_keys_the_client_says_it_is_already_sitting_on() -> None:
    alerts = evaluate_subscription(subscription(), full_ctx())
    muted = [alerts[0].dedupe_key]
    remaining = evaluate_subscription(subscription(muted_keys=muted), full_ctx())
    assert len(remaining) == len(alerts) - 1
    assert muted[0] not in {alert.dedupe_key for alert in remaining}


def test_engine_skips_unknown_rule_kinds_but_rejects_broken_known_ones() -> None:
    parsed = parse_subscription(subscription(rules=[{"kind": "meteor_shower"}, {"kind": "traffic"}]))
    assert parsed.skipped_kinds == ("meteor_shower",)
    assert len(parsed.rules) == 1
    with pytest.raises(ValueError, match="hat adı"):
        parse_subscription(subscription(rules=[{"kind": "metro_disruption", "lines": []}]))
    with pytest.raises(ValueError, match="threshold_index"):
        parse_subscription(subscription(rules=[{"kind": "traffic", "threshold_index": 500}]))
    with pytest.raises(ValueError, match="tanımlı konumlardan"):
        parse_subscription(subscription(rules=[{"kind": "air_quality", "place": "villa"}]))


def test_engine_rejects_coordinates_outside_istanbul_without_echoing_them() -> None:
    payload = subscription(places=[{"key": "home", "label": "Ankara", "lat": 39.92, "lon": 32.85}])
    with pytest.raises(ValueError) as excinfo:
        parse_subscription(payload)
    message = str(excinfo.value)
    assert "home" in message and "İstanbul" in message
    assert "39.92" not in message and "32.85" not in message  # errors are logged; coords are not


def test_client_supplied_cooldowns_are_clamped_to_a_sane_range() -> None:
    parsed = parse_subscription(
        subscription(
            rules=[
                {"kind": "traffic", "threshold_index": 60, "cooldown_seconds": 1},
                {"kind": "metro_disruption", "lines": ["M4"], "cooldown_seconds": 10_000_000},
            ]
        )
    )
    cooldowns = sorted(rule.cooldown_seconds for rule in parsed.rules)
    assert cooldowns == [MIN_COOLDOWN_S, MAX_COOLDOWN_S]


def test_every_alert_carries_provenance_for_each_number_it_cites() -> None:
    for alert in evaluate_subscription(subscription(), full_ctx()):
        assert alert.citations, f"{alert.rule_id} cites nothing"
        assert len(alert.provenance) == len(alert.citations)
        for citation in alert.citations:
            assert citation.provenance.source_url.startswith("http")
            assert citation.value is not None


# --------------------------------------------------------------------------------------
# 7. privacy, tested rather than promised
# --------------------------------------------------------------------------------------
class _CaptureHandler(logging.Handler):
    """Collects every record that reaches the root logger during a block."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _captured_text(handler: _CaptureHandler) -> str:
    return "\n".join(f"{record.name} {record.getMessage()} {record.args!r}" for record in handler.records)


def test_evaluation_never_writes_a_coordinate_to_a_log_record() -> None:
    handler = _CaptureHandler()
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        alerts = evaluate_subscription(subscription(), full_ctx())
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)

    assert alerts, "the fixture must produce alerts, otherwise this proves nothing"
    assert handler.records, "no log record captured — the capture itself is broken"
    blob = _captured_text(handler)
    for secret in (str(SECRET_LAT), str(SECRET_LON), SECRET_LABEL, "40.91", "29.18"):
        assert secret not in blob, f"{secret!r} reached a log record: {blob}"


async def test_the_whole_request_path_logs_no_coordinate(ctx: SourceContext) -> None:
    """Not just the pure evaluation: the fetch path (nearest-station search) too.

    ``build_context`` is the only code that ever sees a coordinate, and it hands it to the
    air-quality source. This captures every record produced by the whole call.
    """
    handler = _CaptureHandler()
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        payload = subscription(
            places=[{"key": "home", "label": SECRET_LABEL, "lat": SECRET_LAT, "lon": SECRET_LON}],
            rules=[{"kind": "air_quality", "place": "home", "aqi_threshold": 10}],
        )
        result = await check_alerts(ctx, payload)
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)

    assert result["alert_count"] == 1  # the path really ran end to end
    blob = _captured_text(handler)
    for secret in (str(SECRET_LAT), str(SECRET_LON), SECRET_LABEL, "40.91", "29.18"):
        assert secret not in blob, f"{secret!r} reached a log record: {blob}"


def test_log_summary_of_a_subscription_carries_only_counts() -> None:
    summary = describe_subscription(parse_subscription(subscription()))
    assert summary == "rules=[air_qualityx1, metro_disruptionx1, parking_fillingx1, trafficx1] places=1"
    assert SECRET_LABEL not in summary and "40.9" not in summary


def test_evaluation_writes_nothing_to_disk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The server is stateless by construction: any write attempt fails this test loudly."""
    real_open = builtins.open
    real_path_open = pathlib.Path.open

    def guard(file, mode="r", *args, **kwargs):  # type: ignore[no-untyped-def]
        if any(flag in str(mode) for flag in "wxa+"):
            raise AssertionError(f"alert evaluation tried to write {file!r}")
        return real_open(file, mode, *args, **kwargs)

    def path_guard(self, mode="r", *args, **kwargs):  # type: ignore[no-untyped-def]
        if any(flag in str(mode) for flag in "wxa+"):
            raise AssertionError(f"alert evaluation tried to write {self!r}")
        return real_path_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guard)
    monkeypatch.setattr(pathlib.Path, "open", path_guard)
    monkeypatch.chdir(tmp_path)

    before = set(tmp_path.rglob("*"))
    alerts = evaluate_subscription(subscription(), full_ctx())
    assert alerts
    assert set(tmp_path.rglob("*")) == before


def test_alert_sources_contain_no_logging_call_that_could_carry_a_location() -> None:
    """Static guard: grep our own code for a log call mentioning a coordinate or a place."""
    forbidden = re.compile(r"\b(lat|lon|latitude|longitude|coord\w*|place|places|label)\b", re.IGNORECASE)
    calls = 0
    for path in sorted(ALERTS_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"log\.[a-z]+\((?:[^()]|\([^()]*\))*\)", source):
            calls += 1
            assert not forbidden.search(match.group(0)), f"{path.name}: {match.group(0)}"
    # The engine does log — a counts-only debug line — so this grep has something to inspect.
    assert calls >= 1, "expected to have inspected at least one log call"
    assert "log.debug(" in (ALERTS_DIR / "engine.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------
# 8. end to end against recorded İBB fixtures (no network: see tests/conftest.py)
# --------------------------------------------------------------------------------------
async def test_build_context_and_check_alerts_against_recorded_data(ctx: SourceContext) -> None:
    payload = subscription(
        places=[{"key": "home", "label": "Maslak", "lat": 41.1001, "lon": 29.0245}],
        rules=[
            {"kind": "metro_disruption", "lines": ["M7"]},
            {"kind": "parking_filling", "park_ids": [2338], "threshold_pct": 85},
            {"kind": "air_quality", "place": "home", "aqi_threshold": 20},
            {"kind": "traffic", "threshold_index": 60},
        ],
    )
    alert_ctx = await build_context(ctx, payload)
    assert alert_ctx.metro is not None and alert_ctx.metro.statuses
    assert 2338 in alert_ctx.parking
    assert alert_ctx.air_quality["home"].station.name == "Maslak"
    assert alert_ctx.traffic is not None and alert_ctx.traffic.point is not None

    result = await check_alerts(ctx, payload)
    kinds = {alert["kind"] for alert in result["alerts"]}
    assert kinds == {"metro_disruption", "parking_filling", "air_quality", "traffic"}
    assert result["alert_count"] == 4
    assert result["cooldown_policy"]["enforced_by"] == "client"
    assert result["privacy"]["stored_server_side"] == "none"
    parking_alert = next(a for a in result["alerts"] if a["kind"] == "parking_filling")
    assert parking_alert["severity"] == "critical"  # 19 Mayıs Açık: 65 capacity, 0 free
    assert "%100 dolu" in parking_alert["message_tr"]


async def test_check_alerts_reports_an_unreadable_source_instead_of_staying_silent(
    ctx: SourceContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ibb_mcp.http import UpstreamUnavailable
    from ibb_mcp.sources.metro import MetroSource

    async def boom(self):  # type: ignore[no-untyped-def]
        raise UpstreamUnavailable("metro down", source="metro_status")

    monkeypatch.setattr(MetroSource, "service_status", boom)
    result = await check_alerts(ctx, subscription(rules=[{"kind": "metro_disruption", "lines": ["M7"]}]))
    assert result["alerts"] == []
    assert "metro_status" in result["unavailable"]
