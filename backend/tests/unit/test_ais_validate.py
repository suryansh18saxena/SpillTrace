"""Field-level AIS validation: sentinels, MMSI classes, Go timestamps, coordinates.

Every case here is one specific way a real AIS feed lies, and the assertion is that the
lie becomes ``None`` or a flag rather than a number in the evidence base.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from spilltrace.core.ais.constants import (
    DIMENSION_AB_SENTINEL_M,
    DIMENSION_CD_SENTINEL_M,
    ROT_AIS_SCALE,
)
from spilltrace.core.ais.validate import (
    MMSIClass,
    classify_mmsi,
    decode_rate_of_turn,
    ensure_utc,
    is_attributable_vessel_mmsi,
    mmsi_mid,
    normalise_dimension,
    normalise_eta,
    normalise_sentinels,
    parse_aisstream_timestamp,
    validate_coordinates,
    validate_mmsi,
    validate_timestamp,
)
from spilltrace.core.enums import AISQualityFlag
from spilltrace.core.errors import ValidationError

NOW = datetime(2026, 8, 1, 18, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- sentinels
@pytest.mark.parametrize(
    ("field_name", "sentinel"),
    [
        ("sog_knots", 102.2),
        ("sog_knots", 102.3),
        ("sog_knots", 1023.0),
        ("cog_deg", 360.0),
        ("cog_deg", 3600.0),
        ("heading_deg", 511),
        ("latitude", 91.0),
        ("latitude", -91.0),
        ("longitude", 181.0),
        ("longitude", -181.0),
        ("rot", -128),
        ("second_of_minute", 60),
        ("second_of_minute", 63),
        ("ship_type", 0),
        ("ship_type", 100),
        ("dimension_a_m", 511.0),
        ("dimension_b_m", 511.0),
        ("dimension_c_m", 63.0),
        ("dimension_d_m", 63.0),
    ],
)
def test_every_documented_sentinel_becomes_none(field_name: str, sentinel: float) -> None:
    """docs/AIS_PIPELINE.md §2: a sentinel must become NULL, never a number."""
    normalised = normalise_sentinels(**{field_name: sentinel})
    # The raw rate-of-turn field is stored under its own name to keep it distinct from
    # the (UNCERTAIN) decoded value beside it.
    attribute = "rot_raw" if field_name == "rot" else field_name
    assert getattr(normalised, attribute) is None
    assert field_name in normalised.dropped


@pytest.mark.parametrize(
    ("month", "day", "hour", "minute"),
    [(0, 5, 6, 30), (7, 0, 6, 30), (7, 5, 24, 30), (7, 5, 6, 60)],
)
def test_eta_sentinels_clear_only_the_field_that_is_unset(
    month: int, day: int, hour: int, minute: int
) -> None:
    """ETA fields are transmitted independently, so one unset field must not void the rest."""
    eta = normalise_eta(month=month, day=day, hour=hour, minute=minute)
    unset = [value for value in (eta.month, eta.day, eta.hour, eta.minute) if value is None]
    assert len(unset) == 1
    assert not eta.is_complete


def test_real_values_survive_normalisation() -> None:
    normalised = normalise_sentinels(
        latitude=22.5,
        longitude=69.1,
        sog_knots=12.4,
        cog_deg=87.5,
        heading_deg=88,
        rot=0,
        second_of_minute=42,
        ship_type=80,
        dimension_a_m=100.0,
        dimension_b_m=50.0,
        dimension_c_m=10.0,
        dimension_d_m=12.0,
    )
    assert normalised.latitude == 22.5
    assert normalised.sog_knots == 12.4
    assert normalised.ship_type == 80
    assert normalised.length_m == 150.0
    assert normalised.width_m == 22.0
    assert normalised.dropped == ()


def test_nan_is_treated_as_absent_not_as_a_measurement() -> None:
    """NaN compares False against every threshold, so it must be caught before them."""
    normalised = normalise_sentinels(sog_knots=math.nan, latitude=math.inf)
    assert normalised.sog_knots is None
    assert normalised.latitude is None


def test_partial_dimensions_do_not_produce_a_hull_size() -> None:
    normalised = normalise_sentinels(dimension_a_m=100.0, dimension_b_m=DIMENSION_AB_SENTINEL_M)
    assert normalised.length_m is None


def test_dimension_sentinel_is_a_bound_not_a_measurement() -> None:
    assert normalise_dimension(510.0, sentinel=DIMENSION_AB_SENTINEL_M) == 510.0
    assert normalise_dimension(DIMENSION_AB_SENTINEL_M, sentinel=DIMENSION_AB_SENTINEL_M) is None
    assert normalise_dimension(62.0, sentinel=DIMENSION_CD_SENTINEL_M) == 62.0
    assert normalise_dimension(DIMENSION_CD_SENTINEL_M, sentinel=DIMENSION_CD_SENTINEL_M) is None


# --------------------------------------------------------------------------- ROT
def test_decode_rate_of_turn_inverts_the_published_encoding() -> None:
    """``ROT_AIS = 4.733·√(ROT_sensor)`` inverts to ``sign(x)·(x/4.733)²``."""
    assert decode_rate_of_turn(ROT_AIS_SCALE) == pytest.approx(1.0)
    assert decode_rate_of_turn(-ROT_AIS_SCALE) == pytest.approx(-1.0)
    assert decode_rate_of_turn(0) == 0.0
    assert decode_rate_of_turn(10 * ROT_AIS_SCALE) == pytest.approx(100.0)


def test_decode_rate_of_turn_rejects_unavailable_and_saturated_values() -> None:
    assert decode_rate_of_turn(-128) is None
    assert decode_rate_of_turn(127) is None
    assert decode_rate_of_turn(-127) is None
    assert decode_rate_of_turn(None) is None


def test_rate_of_turn_uncertainty_is_documented_where_it_is_decoded() -> None:
    """AD-22: the units are UNCERTAIN, so the caveat must travel with the function."""
    docstring = decode_rate_of_turn.__doc__ or ""
    assert "UNCERTAIN" in docstring
    assert "never used in scoring" in docstring


# --------------------------------------------------------------------------- MMSI
@pytest.mark.parametrize(
    ("mmsi", "expected"),
    [
        (419001234, MMSIClass.SHIP),
        (232001234, MMSIClass.SHIP),
        (41900123, MMSIClass.GROUP_OF_SHIPS),
        (2419001, MMSIClass.COAST_STATION),
        (111419001, MMSIClass.SAR_AIRCRAFT),
        (994190123, MMSIClass.AID_TO_NAVIGATION),
        (984190123, MMSIClass.AUXILIARY_CRAFT),
        (970123456, MMSIClass.SART),
        (972123456, MMSIClass.MOB),
        (974123456, MMSIClass.EPIRB),
        (841900123, MMSIClass.DIVER_RADIO),
        (123456789, MMSIClass.INVALID),
        (999999999, MMSIClass.INVALID),
        (12345, MMSIClass.INVALID),
        (0, MMSIClass.INVALID),
        (-419001234, MMSIClass.INVALID),
        (1234567890, MMSIClass.INVALID),
        (None, MMSIClass.INVALID),
        ("not-a-number", MMSIClass.INVALID),
    ],
)
def test_classify_mmsi_covers_every_reserved_prefix(mmsi: object, expected: MMSIClass) -> None:
    assert classify_mmsi(mmsi) is expected  # type: ignore[arg-type]


def test_leading_zeros_survive_the_trip_through_an_integer_column() -> None:
    """A coast station stored as an int loses its ``00`` prefix unless it is re-padded."""
    assert classify_mmsi("002419001") is MMSIClass.COAST_STATION
    assert classify_mmsi(2419001) is classify_mmsi("002419001")


def test_only_ship_mmsis_are_attributable() -> None:
    assert is_attributable_vessel_mmsi(419001234) is True
    for non_ship in (2419001, 994190123, 970123456, 841900123, 111419001):
        assert is_attributable_vessel_mmsi(non_ship) is False


def test_validate_mmsi_separates_invalid_from_merely_not_a_ship() -> None:
    """An AtoN is a correct transmission from a thing that is not a vessel, not an error."""
    ok, flags = validate_mmsi(419001234)
    assert ok and flags == []

    ok, flags = validate_mmsi(994190123)
    assert not ok
    assert flags == [AISQualityFlag.NON_SHIP_STATION]

    ok, flags = validate_mmsi(123456789)
    assert not ok
    assert flags == [AISQualityFlag.INVALID_MMSI]


def test_mmsi_mid_reads_the_flag_state_from_the_right_offset() -> None:
    assert mmsi_mid(419001234) == 419
    assert mmsi_mid(2419001) == 241
    assert mmsi_mid(111419001) == 419
    assert mmsi_mid(970123456) is None
    assert mmsi_mid(123456789) is None


# --------------------------------------------------------------------------- timestamps
@pytest.mark.parametrize(
    ("raw", "expected_microsecond"),
    [
        ("2026-08-01 18:20:43 +0000 UTC", 0),
        ("2026-08-01 18:20:43.237 +0000 UTC", 237000),
        ("2026-08-01 18:20:43.237370229 +0000 UTC", 237370),
        ("2026-08-01 18:20:43.2 +0000 UTC", 200000),
        ("2026-08-01 18:20:43.123456789 +0000 UTC", 123456),
    ],
)
def test_go_timestamp_fraction_may_be_any_length(raw: str, expected_microsecond: int) -> None:
    """Go trims trailing zeros, so the fraction is 0-9 digits (AD-21)."""
    parsed = parse_aisstream_timestamp(raw)
    assert parsed == datetime(2026, 8, 1, 18, 20, 43, expected_microsecond, tzinfo=UTC)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_fromisoformat_really_cannot_parse_the_go_format() -> None:
    """The reason this parser exists; if this ever stops raising, simplify the parser."""
    with pytest.raises(ValueError):
        datetime.fromisoformat("2026-08-01 18:20:43.237370229 +0000 UTC")


def test_go_timestamp_variants_and_offsets() -> None:
    assert parse_aisstream_timestamp("2026-08-01T18:20:43Z") == datetime(
        2026, 8, 1, 18, 20, 43, tzinfo=UTC
    )
    # A non-UTC offset is converted, not ignored.
    assert parse_aisstream_timestamp("2026-08-01 23:50:43 +0530 IST") == datetime(
        2026, 8, 1, 18, 20, 43, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "raw",
    ["", "not a time", "2026-08-01", "2026-13-01 18:20:43 +0000 UTC", "26-08-01 18:20:43"],
)
def test_unparseable_timestamps_raise_rather_than_guess(raw: str) -> None:
    with pytest.raises(ValidationError):
        parse_aisstream_timestamp(raw)


def test_validate_timestamp_accepts_a_normal_report() -> None:
    ok, flags = validate_timestamp(NOW - timedelta(minutes=3), now=NOW)
    assert ok and flags == []


def test_validate_timestamp_rejects_the_future_beyond_clock_skew() -> None:
    ok, flags = validate_timestamp(NOW + timedelta(minutes=6), now=NOW)
    assert not ok
    assert flags == [AISQualityFlag.FUTURE_TIMESTAMP]
    # Five minutes of skew is tolerated, so this one is fine.
    assert validate_timestamp(NOW + timedelta(minutes=4), now=NOW)[0]


def test_validate_timestamp_rejects_epoch_zero_and_pre_ais_dates() -> None:
    for bad in (datetime(1970, 1, 1, tzinfo=UTC), datetime(1999, 12, 31, tzinfo=UTC)):
        ok, flags = validate_timestamp(bad, now=NOW)
        assert not ok
        assert flags == [AISQualityFlag.BAD_TIMESTAMP]


def test_naive_timestamps_are_read_as_utc_not_as_local_time() -> None:
    """AIS is UTC-only; assuming anything else would move vessels in time."""
    assert ensure_utc(datetime(2026, 8, 1, 18, 0, 0)) == NOW  # noqa: DTZ001
    ok, _ = validate_timestamp(datetime(2026, 8, 1, 17, 55, 0), now=NOW)  # noqa: DTZ001
    assert ok


# --------------------------------------------------------------------------- position
def test_valid_coordinates_pass_cleanly() -> None:
    ok, flags = validate_coordinates(22.5, 69.1)
    assert ok and flags == []


def test_sentinel_position_is_distinguished_from_a_corrupt_one() -> None:
    """Both are unusable, but 'no fix' and 'garbage' are different stories (§2)."""
    ok, flags = validate_coordinates(91.0, 181.0)
    assert not ok
    assert AISQualityFlag.SENTINEL_POSITION in flags
    assert AISQualityFlag.INVALID_COORDINATE in flags

    ok, flags = validate_coordinates(95.0, 69.1)
    assert not ok
    assert flags == [AISQualityFlag.INVALID_COORDINATE]


def test_null_island_is_rejected_but_the_water_beside_it_is_not() -> None:
    ok, flags = validate_coordinates(0.0, 0.0)
    assert not ok
    assert flags == [AISQualityFlag.NULL_ISLAND]

    ok, flags = validate_coordinates(0.001, 0.001)
    assert ok and flags == []


def test_missing_coordinates_are_invalid_rather_than_zero() -> None:
    for lat, lon in ((None, 69.1), (22.5, None), (math.nan, 69.1)):
        ok, flags = validate_coordinates(lat, lon)
        assert not ok
        assert flags == [AISQualityFlag.INVALID_COORDINATE]
