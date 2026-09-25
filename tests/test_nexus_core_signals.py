"""nexus_core.signals: a signal knows where it came from and how old it is, in UTC."""

from __future__ import annotations

import datetime as dt

import pytest
from nexus_helpers import T0, make_signal, origin
from pydantic import ValidationError

from nexus_core.signals import SIGNAL_TITLES, Origin, Signal, as_utc


def test_a_signal_id_is_derived_from_what_it_observed() -> None:
    first, again = make_signal(), make_signal()
    later = make_signal(observed_at=T0 + dt.timedelta(minutes=15))
    assert first.signal_id == again.signal_id and first.signal_id.startswith("sig-")
    assert later.signal_id != first.signal_id
    assert make_signal(entity="M2-SISHANE-ASN-02").signal_id != first.signal_id


def test_a_naive_time_is_refused_not_guessed() -> None:
    naive = dt.datetime(2026, 9, 25, 9, 0)
    with pytest.raises(ValueError, match="naive"):
        as_utc(naive)
    with pytest.raises(ValidationError):
        Origin(source="Metro İstanbul", observed_at=naive)
    with pytest.raises(ValidationError):
        Signal(signal_id="s", kind="equipment_fault", entity_id="e", severity="info", observed_at=naive, provenance=origin())


def test_times_are_stored_in_utc() -> None:
    istanbul = dt.timezone(dt.timedelta(hours=3))
    signal = make_signal(observed_at=dt.datetime(2026, 9, 25, 12, 0, tzinfo=istanbul))
    assert signal.observed_at == T0 and signal.observed_at.tzinfo == dt.UTC


def test_provenance_has_the_api_shape_and_the_age_at_the_request() -> None:
    now = T0 + dt.timedelta(minutes=7, seconds=30)
    payload = origin().as_provenance(now)
    assert set(payload) == {"source", "url", "observed_at", "age_s", "mode"}
    assert payload["age_s"] == 450 and payload["mode"] == "live"
    assert payload["observed_at"] == "2026-09-25T09:00:00+00:00"


def test_an_unknown_observation_time_has_no_age() -> None:
    unknown = origin(None, mode="unknown")
    assert unknown.age_s(T0) is None and unknown.as_provenance(T0)["age_s"] is None


def test_an_age_is_never_negative() -> None:
    assert origin(T0 + dt.timedelta(seconds=30)).age_s(T0) == 0


@pytest.mark.parametrize("kind", ["Equipment Fault", "1fault", "equipment-fault", ""])
def test_a_kind_is_a_lower_case_code(kind: str) -> None:
    with pytest.raises(ValidationError):
        make_signal(kind)


def test_unknown_fields_are_refused() -> None:
    data = make_signal().model_dump() | {"profile": {"step_free": True}}
    with pytest.raises(ValidationError):
        Signal.model_validate(data)


def test_titles_are_turkish_and_an_unknown_kind_shows_its_code() -> None:
    assert make_signal().title == SIGNAL_TITLES["equipment_fault"]
    assert make_signal("new_kind").title == "new_kind"


def test_a_signal_round_trips_through_json() -> None:
    signal = make_signal(station="Taksim", extra_minutes=4)
    assert Signal.model_validate_json(signal.model_dump_json()) == signal
