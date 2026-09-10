"""Cleaning rules, each exercised with a crafted pathological track (FR-012, AD-23).

The tracks are built in metres and converted to degrees, so every threshold in the
assertions is the physical one from the specification rather than a magic coordinate.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from spilltrace.core.ais.clean import CleanedPosition, clean_track, cleaning_summary
from spilltrace.core.disclaimers import contains_forbidden_language
from spilltrace.core.enums import AISQualityFlag
from spilltrace.core.geometry import EARTH_RADIUS_M
from spilltrace.core.ports import AISMessage

START = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
NOW = START + timedelta(hours=1)
MMSI = 419001234
BASE_LAT = 22.0
BASE_LON = 69.0

#: Metres per degree of latitude — the same Earth the production code uses.
METRES_PER_DEGREE = math.radians(1.0) * EARTH_RADIUS_M


def north(metres: float) -> float:
    """Latitude ``metres`` north of the base position."""
    return BASE_LAT + metres / METRES_PER_DEGREE


def message(
    *,
    seconds: float = 0.0,
    lat: float = BASE_LAT,
    lon: float = BASE_LON,
    sog: float | None = 5.0,
    cog: float | None = None,
    mmsi: int = MMSI,
) -> AISMessage:
    return AISMessage(
        mmsi=mmsi,
        timestamp=START + timedelta(seconds=seconds),
        latitude=lat,
        longitude=lon,
        message_type="PositionReport",
        source="test",
        sog_knots=sog,
        cog_deg=cog,
    )


def flags_of(position: CleanedPosition) -> set[AISQualityFlag]:
    return set(position.flags)


# --------------------------------------------------------------------------- evidence
def test_rejected_positions_are_kept_with_a_reason() -> None:
    """Cleaning annotates; it never deletes.  A missing row is a missing explanation."""
    messages = [
        message(seconds=0),
        message(seconds=60, lat=0.0, lon=0.0),
        message(seconds=120, lat=north(300)),
    ]
    cleaned = clean_track(messages, now=NOW)

    assert len(cleaned) == len(messages)
    assert [position.message for position in cleaned] == messages
    rejected = cleaned[1]
    assert rejected.is_valid is False
    assert rejected.rejection_reason is not None
    assert AISQualityFlag.NULL_ISLAND in rejected.flags


def test_no_rejection_reason_reads_as_an_accusation() -> None:
    """CON-002: the cleaner describes data faults, it does not attribute conduct."""
    messages = [
        message(seconds=0),
        message(seconds=1, lat=0.0, lon=0.0),
        message(seconds=2, sog=90.0),
        message(seconds=3, lat=north(50_000)),
        message(seconds=4, lat=91.0),
    ]
    for position in clean_track(messages, now=NOW):
        if position.rejection_reason is not None:
            assert contains_forbidden_language(position.rejection_reason) == []


# --------------------------------------------------------------------------- dedup
def test_exact_duplicates_keep_the_first_and_flag_the_rest() -> None:
    messages = [message(seconds=0), message(seconds=0), message(seconds=0)]
    cleaned = clean_track(messages, now=NOW)

    assert cleaned[0].is_valid is True
    assert [position.is_valid for position in cleaned[1:]] == [False, False]
    assert all(AISQualityFlag.DUPLICATE in position.flags for position in cleaned[1:])


def test_sub_second_repeats_are_duplicates() -> None:
    """``time_utc`` is server *receipt* time, so sub-second differences are noise (AD-21)."""
    messages = [message(seconds=0.0), message(seconds=0.4)]
    cleaned = clean_track(messages, now=NOW)
    assert cleaned[1].is_valid is False
    assert AISQualityFlag.DUPLICATE in cleaned[1].flags


def test_positions_differing_below_the_rounding_resolution_are_duplicates() -> None:
    """Five decimals is ~1 m: finer than AIS accuracy, so a difference there is noise."""
    messages = [message(seconds=0, lat=22.000001), message(seconds=0, lat=22.000002)]
    assert clean_track(messages, now=NOW)[1].is_valid is False


def test_a_genuinely_later_report_at_the_same_place_is_not_a_duplicate() -> None:
    messages = [message(seconds=0), message(seconds=300)]
    cleaned = clean_track(messages, now=NOW)
    assert all(position.is_valid for position in cleaned)


# --------------------------------------------------------------------------- position
@pytest.mark.parametrize(
    ("lat", "lon", "expected"),
    [
        (0.0, 0.0, AISQualityFlag.NULL_ISLAND),
        (91.0, 69.0, AISQualityFlag.SENTINEL_POSITION),
        (95.0, 69.0, AISQualityFlag.INVALID_COORDINATE),
        (22.0, 200.0, AISQualityFlag.INVALID_COORDINATE),
    ],
)
def test_coordinate_rule(lat: float, lon: float, expected: AISQualityFlag) -> None:
    cleaned = clean_track([message(lat=lat, lon=lon)], now=NOW)
    assert cleaned[0].is_valid is False
    assert expected in cleaned[0].flags


# --------------------------------------------------------------------------- time
def test_future_timestamps_are_rejected_beyond_the_skew_allowance() -> None:
    cleaned = clean_track([message(seconds=3600 + 360)], now=NOW)
    assert cleaned[0].is_valid is False
    assert AISQualityFlag.FUTURE_TIMESTAMP in cleaned[0].flags


def test_epoch_zero_is_rejected() -> None:
    stale = AISMessage(
        mmsi=MMSI,
        timestamp=datetime(1970, 1, 1, tzinfo=UTC),
        latitude=BASE_LAT,
        longitude=BASE_LON,
        message_type="PositionReport",
        source="test",
    )
    cleaned = clean_track([stale], now=NOW)
    assert cleaned[0].is_valid is False
    assert AISQualityFlag.BAD_TIMESTAMP in cleaned[0].flags


def test_output_is_ordered_by_time_regardless_of_arrival_order() -> None:
    messages = [message(seconds=120), message(seconds=0), message(seconds=60)]
    cleaned = clean_track(messages, now=NOW)
    timestamps = [position.timestamp for position in cleaned]
    assert timestamps == sorted(timestamps)


# --------------------------------------------------------------------------- speed
def test_reported_speed_above_thirty_knots_is_implausible_for_a_surface_vessel() -> None:
    cleaned = clean_track([message(sog=45.0)], now=NOW)
    assert cleaned[0].is_valid is False
    assert AISQualityFlag.IMPLAUSIBLE_SOG in cleaned[0].flags


def test_thirty_knots_exactly_is_still_a_plausible_speed() -> None:
    assert clean_track([message(sog=30.0)], now=NOW)[0].is_valid is True


def test_implied_speed_uses_a_separate_higher_threshold() -> None:
    """AD-23: 30 kn reported and 40 kn implied are different failure modes.

    50 km in a minute is ~1600 kn — impossible — while every reported speed in the
    track is a perfectly ordinary 5 kn, so only the derived rule can catch it.
    """
    messages = [
        message(seconds=0),
        message(seconds=60, lat=north(50_000)),
        message(seconds=120, lat=north(300)),
    ]
    cleaned = clean_track(messages, now=NOW)

    assert AISQualityFlag.IMPOSSIBLE_JUMP in cleaned[1].flags
    assert cleaned[1].is_valid is False
    assert AISQualityFlag.IMPLAUSIBLE_SOG not in cleaned[1].flags


def test_the_fix_after_a_jump_is_compared_with_the_last_valid_one() -> None:
    """Otherwise a single bad fix would drag its innocent successor down with it."""
    messages = [
        message(seconds=0),
        message(seconds=60, lat=north(50_000)),
        message(seconds=120, lat=north(300)),
    ]
    cleaned = clean_track(messages, now=NOW)
    assert cleaned[2].is_valid is True
    assert cleaned[2].flags == []


def test_two_positions_sharing_one_instant_cannot_be_two_places() -> None:
    """A documented 2025 spoofing typology — flagged, never silently averaged."""
    messages = [message(seconds=0), message(seconds=0, lat=north(5_000))]
    cleaned = clean_track(messages, now=NOW)
    assert cleaned[1].is_valid is False
    assert AISQualityFlag.IMPOSSIBLE_JUMP in cleaned[1].flags


# --------------------------------------------------------------------------- kinematics
def test_two_consecutive_violations_identify_one_bad_fix() -> None:
    """The two-segment rule (AD-23), which is the whole point of the kinematic check.

    900 m in 60 s is only 29 kn, so the implied-speed rule lets it through; but at the
    5 kn the vessel reports, only ~293 m is reachable.  The leg *out* of the suspect fix
    is impossible too, and that pair of violations is the signature of a bad position.
    """
    messages = [
        message(seconds=0, lat=BASE_LAT, sog=5.0),
        message(seconds=60, lat=north(900), sog=5.0),
        message(seconds=120, lat=north(300), sog=5.0),
    ]
    cleaned = clean_track(messages, now=NOW)

    assert cleaned[1].is_valid is False
    assert AISQualityFlag.KINEMATIC_OUTLIER in cleaned[1].flags
    assert AISQualityFlag.IMPOSSIBLE_JUMP not in cleaned[1].flags
    # The surrounding real fixes survive untouched.
    assert cleaned[0].is_valid is True
    assert cleaned[2].is_valid is True


def test_a_single_violated_segment_is_a_manoeuvre_and_is_kept() -> None:
    """The mirror image of the test above, and the reason naive correction is wrong.

    Identical first leg — 900 m in 60 s against a 5 kn previous report — but the vessel
    then continues consistently at the 28 kn it now reports.  One violated segment is a
    manoeuvre or a stale speed field, not a bad fix, and deleting it would destroy a
    real course change.
    """
    messages = [
        message(seconds=0, lat=BASE_LAT, sog=5.0),
        message(seconds=60, lat=north(900), sog=28.0),
        message(seconds=120, lat=north(1764), sog=28.0),
    ]
    cleaned = clean_track(messages, now=NOW)

    assert cleaned[1].is_valid is True
    assert AISQualityFlag.KINEMATIC_OUTLIER not in cleaned[1].flags
    assert all(position.is_valid for position in cleaned)


def test_the_final_fix_is_never_rejected_kinematically() -> None:
    """With no following segment the two-segment signature cannot be distinguished.

    The implied-speed rule remains the backstop for gross errors; guessing here would
    reject the most recent position of every track that ends mid-manoeuvre.
    """
    messages = [
        message(seconds=0, lat=BASE_LAT, sog=5.0),
        message(seconds=60, lat=north(150), sog=5.0),
        message(seconds=120, lat=north(1_050), sog=5.0),
    ]
    cleaned = clean_track(messages, now=NOW)
    assert cleaned[2].is_valid is True


def test_a_steady_track_is_left_entirely_alone() -> None:
    messages = [message(seconds=index * 60, lat=north(index * 154), sog=5.0) for index in range(6)]
    cleaned = clean_track(messages, now=NOW)
    assert all(position.is_valid for position in cleaned)
    assert all(position.flags == [] for position in cleaned)


# --------------------------------------------------------------------------- COG
def test_course_contradicting_the_bearing_is_flagged_but_not_rejected() -> None:
    """The COG *field* is discredited, not the fix: the vessel was still somewhere."""
    messages = [
        message(seconds=0, sog=10.0, cog=0.0),
        message(seconds=60, lat=north(300), sog=10.0, cog=180.0),
    ]
    cleaned = clean_track(messages, now=NOW)

    assert cleaned[1].is_valid is True
    assert AISQualityFlag.COG_INCONSISTENT in cleaned[1].flags


def test_course_agreeing_with_the_bearing_is_not_flagged() -> None:
    messages = [
        message(seconds=0, sog=10.0, cog=0.0),
        message(seconds=60, lat=north(300), sog=10.0, cog=3.0),
    ]
    assert flags_of(clean_track(messages, now=NOW)[1]) == set()


def test_a_near_stationary_vessel_is_not_judged_on_its_course() -> None:
    """Below 1 kn the bearing between fixes is noise, so comparing it says nothing."""
    messages = [
        message(seconds=0, sog=0.2, cog=0.0),
        message(seconds=60, lat=north(300), sog=0.2, cog=180.0),
    ]
    assert AISQualityFlag.COG_INCONSISTENT not in clean_track(messages, now=NOW)[1].flags


# --------------------------------------------------------------------------- contract
def test_cleaning_is_deterministic() -> None:
    messages = [
        message(seconds=0),
        message(seconds=0),
        message(seconds=60, lat=north(50_000)),
        message(seconds=120, lat=north(300), sog=45.0),
        message(seconds=180, lat=0.0, lon=0.0),
    ]
    first = clean_track(messages, now=NOW)
    second = clean_track(messages, now=NOW)

    def fingerprint(positions: list[CleanedPosition]) -> list[tuple[object, ...]]:
        return [
            (
                position.timestamp,
                position.is_valid,
                tuple(position.flags),
                position.rejection_reason,
            )
            for position in positions
        ]

    assert fingerprint(first) == fingerprint(second)


def test_mixing_two_vessels_fails_loudly() -> None:
    """Comparing one ship's position against another's produces plausible nonsense."""
    with pytest.raises(ValueError, match="one vessel"):
        clean_track([message(), message(mmsi=232001234)], now=NOW)


def test_empty_input_is_empty_output() -> None:
    assert clean_track([], now=NOW) == []


def test_cleaning_summary_counts_what_was_lost() -> None:
    """CON-007: a thin track must be distinguishable from a noisy feed."""
    messages = [
        message(seconds=0),
        message(seconds=0),
        message(seconds=60, lat=0.0, lon=0.0),
        message(seconds=120, lat=north(300)),
    ]
    summary = cleaning_summary(clean_track(messages, now=NOW))

    assert summary["total"] == 4
    assert summary["valid"] == 2
    assert summary["rejected"] == 2
    assert summary[AISQualityFlag.DUPLICATE.value] == 1
    assert summary[AISQualityFlag.NULL_ISLAND.value] == 1
