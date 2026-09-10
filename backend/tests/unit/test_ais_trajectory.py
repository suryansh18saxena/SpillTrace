"""Trajectory construction, statistics, interpolation and closest approach (FR-013).

The recurring theme in these tests is refusal: a line is never drawn across time we did
not observe, and a position is never invented inside a gap.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from spilltrace.core.ais.clean import CleanedPosition, clean_track
from spilltrace.core.ais.constants import SEGMENT_GAP_MINUTES
from spilltrace.core.ais.trajectory import (
    build_trajectories,
    closest_approach,
    interpolate_position,
)
from spilltrace.core.enums import AISQualityFlag
from spilltrace.core.geometry import EARTH_RADIUS_M, geodesic_distance_m
from spilltrace.core.ports import AISMessage

START = datetime(2026, 8, 1, 6, 0, 0, tzinfo=UTC)
NOW = START + timedelta(days=1)
MMSI = 419001234
BASE_LAT = 22.0
BASE_LON = 69.0
METRES_PER_DEGREE = math.radians(1.0) * EARTH_RADIUS_M


def north(metres: float) -> float:
    return BASE_LAT + metres / METRES_PER_DEGREE


def message(
    *,
    minutes: float,
    lat: float = BASE_LAT,
    lon: float = BASE_LON,
    sog: float | None = 5.0,
    mmsi: int = MMSI,
) -> AISMessage:
    return AISMessage(
        mmsi=mmsi,
        timestamp=START + timedelta(minutes=minutes),
        latitude=lat,
        longitude=lon,
        message_type="PositionReport",
        source="test",
        sog_knots=sog,
    )


def raw_position(*, minutes: float, lat: float, lon: float) -> CleanedPosition:
    """A ``CleanedPosition`` built directly, for geometry the cleaner would reject."""
    return CleanedPosition(message=message(minutes=minutes, lat=lat, lon=lon))


def steady_track(count: int, *, interval_minutes: float, step_m: float = 300.0) -> list[AISMessage]:
    return [
        message(minutes=index * interval_minutes, lat=north(index * step_m))
        for index in range(count)
    ]


# --------------------------------------------------------------------------- splitting
def test_a_continuous_track_is_a_single_segment() -> None:
    cleaned = clean_track(steady_track(10, interval_minutes=2.0), now=NOW)
    (segment,) = build_trajectories(cleaned)

    assert segment.position_count == 10
    assert len(segment.geometry) == 10
    assert segment.mmsi == MMSI


def test_geometry_is_longitude_first() -> None:
    """GeoJSON and PostGIS order, deliberately the opposite of AISStream's bboxes."""
    cleaned = clean_track(steady_track(3, interval_minutes=2.0), now=NOW)
    (segment,) = build_trajectories(cleaned)
    assert segment.geometry[0] == (BASE_LON, BASE_LAT)


def test_a_gap_of_exactly_the_segment_threshold_splits_the_track() -> None:
    """30 minutes is the boundary, and the boundary belongs to the split (AD-24)."""
    messages = [
        message(minutes=0),
        message(minutes=2, lat=north(300)),
        message(minutes=32, lat=north(600)),
        message(minutes=34, lat=north(900)),
    ]
    segments = build_trajectories(clean_track(messages, now=NOW))
    assert [segment.position_count for segment in segments] == [2, 2]


def test_a_gap_just_under_the_threshold_does_not_split() -> None:
    messages = [
        message(minutes=0),
        message(minutes=29.9, lat=north(300)),
    ]
    segments = build_trajectories(clean_track(messages, now=NOW))
    assert len(segments) == 1
    assert segments[0].gap_count == 1


def test_the_split_threshold_is_configurable() -> None:
    messages = [message(minutes=0), message(minutes=45, lat=north(300))]
    cleaned = clean_track(messages, now=NOW)
    assert len(build_trajectories(cleaned)) == 2
    assert len(build_trajectories(cleaned, segment_gap_minutes=60.0)) == 1


def test_rejected_positions_never_shape_the_line() -> None:
    """They remain in the record as evidence, but a bad fix must not bend the geometry."""
    messages = [
        message(minutes=0),
        message(minutes=2, lat=0.0, lon=0.0),
        message(minutes=4, lat=north(600)),
    ]
    cleaned = clean_track(messages, now=NOW)
    (segment,) = build_trajectories(cleaned)

    assert segment.position_count == 2
    assert (0.0, 0.0) not in segment.geometry
    assert any(not position.is_valid for position in cleaned)


def test_a_single_fix_is_recorded_with_no_geometry_rather_than_dropped() -> None:
    """ "We saw this vessel once" is a real observation; silently losing it is not."""
    messages = [message(minutes=0), message(minutes=120, lat=north(300))]
    segments = build_trajectories(clean_track(messages, now=NOW))

    assert len(segments) == 2
    for segment in segments:
        assert segment.position_count == 1
        assert segment.geometry == []
        assert segment.to_linestring() is None
        assert segment.distance_km == 0.0
        assert segment.is_single_point
        assert AISQualityFlag.SINGLE_POINT_SEGMENT in segment.quality_flags
        assert segment.coverage_ratio == 0.0
        assert segment.quality_score == 0.0


def test_mixing_two_vessels_fails_loudly() -> None:
    cleaned = clean_track([message(minutes=0)], now=NOW) + clean_track(
        [message(minutes=1, mmsi=232001234)], now=NOW
    )
    with pytest.raises(ValueError, match="one vessel"):
        build_trajectories(cleaned)


def test_no_valid_positions_gives_no_trajectory() -> None:
    assert build_trajectories([]) == []
    assert build_trajectories(clean_track([message(minutes=0, lat=0.0, lon=0.0)], now=NOW)) == []


# --------------------------------------------------------------------------- statistics
def test_distance_is_geodesic_and_duration_is_real_time() -> None:
    cleaned = clean_track(steady_track(5, interval_minutes=2.0, step_m=1000.0), now=NOW)
    (segment,) = build_trajectories(cleaned)

    expected_km = (
        sum(
            geodesic_distance_m(
                BASE_LON, north(index * 1000.0), BASE_LON, north((index + 1) * 1000.0)
            )
            for index in range(4)
        )
        / 1000.0
    )
    assert segment.distance_km == pytest.approx(expected_km, rel=1e-6)
    # ~4 km: the test helper steps in *spherical* metres while the statistic is
    # ellipsoidal, and that 0.4% disagreement is exactly why the production code uses
    # a geodesic length rather than a radius-and-a-multiplication.
    assert segment.distance_km == pytest.approx(4.0, rel=1e-2)
    assert segment.duration_hours == pytest.approx(8 / 60)


def test_speed_statistics_come_from_reported_values() -> None:
    messages = [
        message(minutes=0, sog=4.0),
        message(minutes=2, lat=north(300), sog=8.0),
        message(minutes=4, lat=north(600), sog=None),
    ]
    (segment,) = build_trajectories(clean_track(messages, now=NOW))

    assert segment.mean_sog_knots == pytest.approx(6.0)
    assert segment.max_sog_knots == pytest.approx(8.0)


def test_speed_statistics_are_none_when_nothing_reported_a_speed() -> None:
    messages = [message(minutes=index * 2, lat=north(index * 300), sog=None) for index in range(3)]
    (segment,) = build_trajectories(clean_track(messages, now=NOW))
    assert segment.mean_sog_knots is None
    assert segment.max_sog_knots is None


def test_coverage_ratio_is_clamped_and_falls_with_sparsity() -> None:
    dense = build_trajectories(clean_track(steady_track(20, interval_minutes=1.0), now=NOW))[0]
    sparse = build_trajectories(
        clean_track(steady_track(5, interval_minutes=10.0, step_m=1000.0), now=NOW)
    )[0]

    assert dense.coverage_ratio == 1.0
    assert sparse.coverage_ratio == pytest.approx(5 / (40 * 60 / 180))
    assert 0.0 < sparse.coverage_ratio < 1.0
    assert sparse.quality_score < dense.quality_score


def test_gap_statistics_are_recorded_for_intervals_inside_a_segment() -> None:
    messages = [
        message(minutes=0),
        message(minutes=1, lat=north(150)),
        message(minutes=21, lat=north(300)),
        message(minutes=22, lat=north(450)),
    ]
    (segment,) = build_trajectories(clean_track(messages, now=NOW))

    assert segment.gap_count == 1
    assert segment.max_gap_minutes == pytest.approx(20.0)
    assert segment.total_gap_minutes == pytest.approx(20.0)
    assert all(gap.duration_minutes < SEGMENT_GAP_MINUTES for gap in segment.gaps)


def test_position_flags_propagate_to_the_segment() -> None:
    messages = [
        message(minutes=0, sog=10.0),
        AISMessage(
            mmsi=MMSI,
            timestamp=START + timedelta(minutes=1),
            latitude=north(300),
            longitude=BASE_LON,
            message_type="PositionReport",
            source="test",
            sog_knots=10.0,
            cog_deg=180.0,
        ),
    ]
    (segment,) = build_trajectories(clean_track(messages, now=NOW))
    assert AISQualityFlag.COG_INCONSISTENT in segment.quality_flags


def test_quality_score_and_coverage_stay_inside_the_unit_interval() -> None:
    for interval in (0.5, 2.0, 12.0, 25.0):
        cleaned = clean_track(steady_track(6, interval_minutes=interval, step_m=100.0), now=NOW)
        for segment in build_trajectories(cleaned):
            assert 0.0 <= segment.coverage_ratio <= 1.0
            assert 0.0 <= segment.quality_score <= 1.0


# --------------------------------------------------------------------------- interpolation
def test_interpolation_lands_between_the_bracketing_fixes() -> None:
    cleaned = clean_track([message(minutes=0), message(minutes=10, lat=north(1000.0))], now=NOW)
    (segment,) = build_trajectories(cleaned)

    result = interpolate_position(segment, START + timedelta(minutes=5))
    assert result is not None
    longitude, latitude = result
    assert longitude == pytest.approx(BASE_LON)
    assert latitude == pytest.approx(north(500.0), abs=1e-9)


def test_interpolation_at_a_reported_fix_returns_that_fix() -> None:
    cleaned = clean_track(steady_track(3, interval_minutes=5.0), now=NOW)
    (segment,) = build_trajectories(cleaned)

    assert interpolate_position(segment, START) == pytest.approx((BASE_LON, BASE_LAT))
    assert interpolate_position(segment, START + timedelta(minutes=10)) == pytest.approx(
        (BASE_LON, north(600.0))
    )


def test_interpolation_outside_the_segment_window_is_refused() -> None:
    cleaned = clean_track(steady_track(3, interval_minutes=5.0), now=NOW)
    (segment,) = build_trajectories(cleaned)

    assert interpolate_position(segment, START - timedelta(minutes=1)) is None
    assert interpolate_position(segment, START + timedelta(minutes=11)) is None


def test_interpolation_refuses_to_cross_a_gap() -> None:
    """A position invented inside a gap would reach correlation as an observation."""
    messages = [message(minutes=0), message(minutes=60, lat=north(1000.0))]
    # A deliberately loose split threshold keeps the hour-long hole inside one segment.
    (segment,) = build_trajectories(clean_track(messages, now=NOW), segment_gap_minutes=120.0)

    assert segment.position_count == 2
    assert interpolate_position(segment, START + timedelta(minutes=30)) is None


def test_interpolation_on_a_single_fix_answers_only_for_that_instant() -> None:
    (segment,) = build_trajectories(clean_track([message(minutes=0)], now=NOW))
    assert interpolate_position(segment, START) == (BASE_LON, BASE_LAT)
    assert interpolate_position(segment, START + timedelta(seconds=1)) is None


def test_interpolation_crosses_the_antimeridian_the_short_way() -> None:
    """Without the ±360° correction the vessel appears to sprint round the planet."""
    positions = [
        raw_position(minutes=0, lat=60.0, lon=179.9),
        raw_position(minutes=18, lat=60.0, lon=-179.9),
    ]
    (segment,) = build_trajectories(positions)

    result = interpolate_position(segment, START + timedelta(minutes=9))
    assert result is not None
    longitude, latitude = result
    assert abs(abs(longitude) - 180.0) < 1e-6
    assert latitude == pytest.approx(60.0)


# --------------------------------------------------------------------------- proximity
def test_closest_approach_looks_along_the_leg_not_only_at_the_fixes() -> None:
    """With fixes minutes apart the true closest approach usually falls between them.

    Reporting the nearest reported fix instead would overstate the distance — the wrong
    direction to be wrong in when the question is how close a vessel came to a slick.
    """
    positions = [
        raw_position(minutes=0, lat=BASE_LAT, lon=BASE_LON),
        raw_position(minutes=10, lat=north(1000.0), lon=BASE_LON),
    ]
    (segment,) = build_trajectories(positions)

    east_offset_deg = 500.0 / (METRES_PER_DEGREE * math.cos(math.radians(BASE_LAT)))
    target_lon = BASE_LON + east_offset_deg
    target_lat = north(500.0)

    distance_km, when = closest_approach(segment, target_lon, target_lat)

    assert distance_km == pytest.approx(0.5, abs=0.01)
    # Better than either endpoint, which are ~707 m away.
    assert distance_km < 0.7
    assert abs((when - (START + timedelta(minutes=5))).total_seconds()) < 5


def test_closest_approach_on_a_single_fix_uses_that_fix() -> None:
    (segment,) = build_trajectories(clean_track([message(minutes=0)], now=NOW))
    distance_km, when = closest_approach(segment, BASE_LON, north(1000.0))

    assert distance_km == pytest.approx(1.0, rel=1e-2)
    assert when == START


def test_closest_approach_needs_a_position() -> None:
    (segment,) = build_trajectories(clean_track([message(minutes=0)], now=NOW))
    empty = replace(segment, positions=[])
    with pytest.raises(ValueError, match="at least one position"):
        closest_approach(empty, BASE_LON, BASE_LAT)
