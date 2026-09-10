"""Per-factor behaviour: boundaries, monotonicity and missing data (P19-002…P19-007).

The engine tests in ``test_scoring.py`` check the model as a whole.  These check each
factor in isolation, because a factor that is wrong at its own boundary can still look
plausible once it has been diluted by five others.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from spilltrace.core.geometry import destination_point
from spilltrace.core.scoring.factors import (
    AIS_SUB_WEIGHTS,
    DEFAULT_DISTANCE_SCALE_KM,
    HEADING_CEILING,
    HEADING_FLOOR,
    INSUFFICIENT_DATA_SCORE,
    NEARBY_CEILING,
    REGION_BOUNDARY_SCORE,
    SPEED_PLATEAU_MAX_KNOTS,
    SPEED_PLATEAU_MIN_KNOTS,
    derive_ais_subscores,
    score_ais_reliability,
    score_heading_match,
    score_origin_proximity,
    score_speed_match,
    score_time_match,
    score_trajectory_match,
    speed_plausibility,
)
from spilltrace.core.scoring.inputs import (
    OriginContext,
    SpillContext,
    TrackContext,
    TrackSample,
)
from spilltrace.core.scoring.model import FactorKey

# --------------------------------------------------------------------------- fixtures
CENTRE_LON = 72.50
CENTRE_LAT = 18.50
HALF = 0.10  # ~11 km, so the region is ~22 km across
SOUTH_EDGE_LAT = CENTRE_LAT - HALF
WINDOW_START = datetime(2026, 8, 1, 17, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 8, 1, 20, 0, tzinfo=UTC)


def square(lon: float, lat: float, half: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon - half, lat - half],
                [lon + half, lat - half],
                [lon + half, lat + half],
                [lon - half, lat + half],
                [lon - half, lat - half],
            ]
        ],
    }


REGION = square(CENTRE_LON, CENTRE_LAT, HALF)
CONTOURS = [
    (0.50, square(CENTRE_LON, CENTRE_LAT, 0.10)),
    (0.80, square(CENTRE_LON, CENTRE_LAT, 0.06)),
    (0.95, square(CENTRE_LON, CENTRE_LAT, 0.03)),
]


def origin(**kwargs) -> OriginContext:
    defaults = {
        "region_geojson": REGION,
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
    }
    defaults.update(kwargs)
    return OriginContext(**defaults)


def point_south_of_region(distance_km: float) -> tuple[float, float]:
    """A position ``distance_km`` due south of the region's southern edge."""
    return destination_point(CENTRE_LON, SOUTH_EDGE_LAT, 180.0, distance_km * 1000.0)


def one_position(lon: float, lat: float, **kwargs) -> TrackContext:
    sample = TrackSample(timestamp=WINDOW_START, lon=lon, lat=lat, **kwargs)
    return TrackContext(samples=(sample,))


def crossing_track(
    start: datetime = WINDOW_START,
    *,
    step_minutes: int = 15,
    count: int = 11,
    sog: float | None = 6.0,
) -> TrackContext:
    """West-to-east straight through the middle of the region."""
    samples = tuple(
        TrackSample(
            timestamp=start + timedelta(minutes=step_minutes * i),
            lon=72.35 + 0.03 * i,
            lat=CENTRE_LAT,
            sog_knots=sog,
            cog_deg=90.0,
            heading_deg=90.0,
        )
        for i in range(count)
    )
    return TrackContext(samples=samples)


# ============================================================ SCORE-001 proximity
def test_origin_proximity_at_the_region_boundary_is_the_boundary_score():
    """Distance 0 with no contours: inside the region, depth unknown."""
    lon, lat = point_south_of_region(0.0)
    factor = score_origin_proximity(origin=origin(), track=one_position(lon, lat))
    assert factor.score == pytest.approx(REGION_BOUNDARY_SCORE, abs=1e-6)
    assert factor.evidence["closest_approach_km"] == pytest.approx(0.0, abs=1e-3)
    assert factor.evidence["inside_origin_region"] is True


def test_origin_proximity_decays_by_one_e_fold_at_the_decay_scale():
    lon, lat = point_south_of_region(DEFAULT_DISTANCE_SCALE_KM)
    factor = score_origin_proximity(origin=origin(), track=one_position(lon, lat))
    assert factor.score == pytest.approx(REGION_BOUNDARY_SCORE * math.exp(-1.0), rel=1e-2)


def test_origin_proximity_is_effectively_zero_at_ten_decay_scales():
    lon, lat = point_south_of_region(10.0 * DEFAULT_DISTANCE_SCALE_KM)
    factor = score_origin_proximity(origin=origin(), track=one_position(lon, lat))
    assert factor.score == pytest.approx(REGION_BOUNDARY_SCORE * math.exp(-10.0), rel=5e-2)
    assert factor.score < 0.001


def test_origin_proximity_is_monotonically_non_increasing_in_distance():
    scores = []
    for distance_km in (0.0, 1.0, 5.0, 12.5, 25.0, 50.0, 100.0, 250.0):
        lon, lat = point_south_of_region(distance_km)
        scores.append(score_origin_proximity(origin=origin(), track=one_position(lon, lat)).score)
    assert scores == sorted(scores, reverse=True)
    assert len(set(scores)) == len(scores)


def test_origin_proximity_rises_with_the_probability_contour_reached():
    """A deeper contour is a stronger statement about where the discharge happened."""
    inner = score_origin_proximity(
        origin=origin(contours=CONTOURS), track=one_position(CENTRE_LON, CENTRE_LAT)
    )
    # 0.02 deg north of centre is inside the 0.80 contour (half 0.06) but outside 0.95.
    middle = score_origin_proximity(
        origin=origin(contours=CONTOURS), track=one_position(CENTRE_LON, CENTRE_LAT + 0.045)
    )
    outer = score_origin_proximity(
        origin=origin(contours=CONTOURS), track=one_position(CENTRE_LON, CENTRE_LAT + 0.08)
    )
    assert inner.evidence["contour_percentile"] == 95
    assert middle.evidence["contour_percentile"] == 80
    assert outer.evidence["contour_percentile"] == 50
    assert inner.score > middle.score > outer.score >= REGION_BOUNDARY_SCORE
    assert inner.score == pytest.approx(REGION_BOUNDARY_SCORE + 0.40 * 0.95)


def test_origin_proximity_without_a_track_is_insufficient_not_zero():
    factor = score_origin_proximity(origin=origin(), track=TrackContext())
    assert factor.score == INSUFFICIENT_DATA_SCORE
    assert factor.evidence["insufficient_data"] is True
    assert "insufficient" in factor.explanation.lower() or "could not be measured" in (
        factor.explanation.lower()
    )


def test_origin_proximity_without_an_origin_region_is_insufficient_not_zero():
    factor = score_origin_proximity(
        origin=OriginContext(region_geojson=None, contours=()),
        track=one_position(CENTRE_LON, CENTRE_LAT),
    )
    assert factor.score == INSUFFICIENT_DATA_SCORE
    assert factor.evidence["insufficient_data"] is True


def test_origin_proximity_falls_back_to_the_outermost_contour_as_the_region():
    factor = score_origin_proximity(
        origin=OriginContext(region_geojson=None, contours=CONTOURS),
        track=one_position(CENTRE_LON, CENTRE_LAT),
    )
    assert factor.evidence["contour_percentile"] == 95
    assert factor.score > REGION_BOUNDARY_SCORE


def test_origin_proximity_survives_malformed_geometry():
    factor = score_origin_proximity(
        origin=OriginContext(region_geojson={"type": "Nonsense", "coordinates": []}),
        track=one_position(CENTRE_LON, CENTRE_LAT),
    )
    assert factor.score == INSUFFICIENT_DATA_SCORE


# ============================================================ SCORE-002 time match
def test_time_match_fully_inside_the_window_scores_one():
    track = crossing_track(WINDOW_START + timedelta(minutes=15), count=11, step_minutes=15)
    factor = score_time_match(origin=origin(), track=track)
    assert factor.score == pytest.approx(1.0)
    assert factor.evidence["overlap_hours"] == pytest.approx(2.5)


def test_time_match_half_overlapping_scores_one_half():
    """Two-hour track, one hour of it inside a three-hour window, no shoulder credit."""
    track = crossing_track(WINDOW_END - timedelta(hours=1), count=9, step_minutes=15)
    factor = score_time_match(origin=origin(), track=track, tolerance_hours=0.0)
    assert factor.score == pytest.approx(0.5)


def test_time_match_fully_outside_the_window_scores_a_measured_zero():
    """Three days out is a measurement, not missing data, so 0.0 is correct."""
    track = crossing_track(WINDOW_START - timedelta(days=3))
    factor = score_time_match(origin=origin(), track=track)
    assert factor.score == 0.0
    assert factor.evidence.get("insufficient_data") is None
    assert factor.evidence["separation_hours"] > 60


def test_time_match_tolerance_shoulder_gives_partial_credit():
    """Just outside the window but inside the tolerance is worth something, not nothing."""
    track = crossing_track(WINDOW_END + timedelta(minutes=30), count=5, step_minutes=15)
    with_tolerance = score_time_match(origin=origin(), track=track, tolerance_hours=2.0)
    without_tolerance = score_time_match(origin=origin(), track=track, tolerance_hours=0.0)
    assert without_tolerance.score == 0.0
    assert 0.0 < with_tolerance.score < 1.0
    assert with_tolerance.evidence["shoulder_hours"] > 0


def test_time_match_is_monotonic_as_the_track_slides_into_the_window():
    scores = []
    for offset_hours in (-12, -6, -3, -2, -1, 0):
        track = crossing_track(
            WINDOW_START + timedelta(hours=offset_hours), count=5, step_minutes=15
        )
        scores.append(score_time_match(origin=origin(), track=track, tolerance_hours=0.0).score)
    assert scores == sorted(scores)
    assert scores[0] == 0.0
    assert scores[-1] == pytest.approx(1.0)


def test_time_match_without_a_window_is_insufficient_not_zero():
    factor = score_time_match(origin=OriginContext(region_geojson=REGION), track=crossing_track())
    assert factor.score == INSUFFICIENT_DATA_SCORE
    assert factor.evidence["insufficient_data"] is True


def test_time_match_without_a_track_is_insufficient_not_zero():
    factor = score_time_match(origin=origin(), track=TrackContext())
    assert factor.score == INSUFFICIENT_DATA_SCORE


# ============================================================ SCORE-003 trajectory
def test_trajectory_match_crossing_with_a_long_dwell_saturates():
    factor = score_trajectory_match(origin=origin(), track=crossing_track())
    assert factor.evidence["relation"] == "crossed"
    assert factor.evidence["entries"] == 1
    assert factor.evidence["exits"] == 1
    assert factor.evidence["dwell_minutes"] >= 60.0
    assert factor.score == pytest.approx(1.0)


def test_trajectory_match_rises_with_dwell_time():
    scores = []
    for step_minutes in (1, 3, 6, 10, 15):
        factor = score_trajectory_match(
            origin=origin(), track=crossing_track(step_minutes=step_minutes)
        )
        scores.append(factor.score)
    assert scores == sorted(scores)
    assert scores[0] < scores[-1]


def test_trajectory_match_distinguishes_crossing_from_passing_nearby():
    crossed = score_trajectory_match(origin=origin(), track=crossing_track())
    lon, lat = point_south_of_region(3.0)
    nearby = score_trajectory_match(origin=origin(), track=one_position(lon, lat))
    assert nearby.evidence["relation"] == "passed_nearby"
    assert nearby.score < NEARBY_CEILING < crossed.score


def test_trajectory_match_decays_with_distance_when_the_region_was_never_entered():
    scores = []
    for distance_km in (1.0, 5.0, 25.0, 100.0):
        lon, lat = point_south_of_region(distance_km)
        scores.append(score_trajectory_match(origin=origin(), track=one_position(lon, lat)).score)
    assert scores == sorted(scores, reverse=True)
    assert scores[-1] < 0.01


def test_trajectory_match_classifies_entering_leaving_and_staying():
    samples = crossing_track().samples
    entered = TrackContext(samples=samples[:6])  # starts outside, ends inside
    left = TrackContext(samples=samples[4:])  # starts inside, ends outside
    inside = TrackContext(samples=samples[3:8])  # never leaves
    assert score_trajectory_match(origin=origin(), track=entered).evidence["relation"] == (
        "entered"
    )
    assert score_trajectory_match(origin=origin(), track=left).evidence["relation"] == "left"
    assert score_trajectory_match(origin=origin(), track=inside).evidence["relation"] == (
        "inside_throughout"
    )


def test_trajectory_match_with_no_track_or_no_region_is_insufficient():
    assert (
        score_trajectory_match(origin=origin(), track=TrackContext()).score
        == INSUFFICIENT_DATA_SCORE
    )
    assert (
        score_trajectory_match(
            origin=OriginContext(window_start=WINDOW_START), track=crossing_track()
        ).score
        == INSUFFICIENT_DATA_SCORE
    )


# ============================================================ SCORE-004 heading
def spill_without_axis() -> SpillContext:
    return SpillContext(detection_time=WINDOW_END, centroid_lon=CENTRE_LON, centroid_lat=CENTRE_LAT)


def heading_score(course_deg: float, **spill_kwargs) -> float:
    lon, lat = point_south_of_region(20.0)  # due south, so the origin bears 000
    spill = SpillContext(
        detection_time=WINDOW_END,
        centroid_lon=CENTRE_LON,
        centroid_lat=CENTRE_LAT,
        **spill_kwargs,
    )
    factor = score_heading_match(
        spill=spill, origin=origin(), track=one_position(lon, lat, cog_deg=course_deg)
    )
    return factor.score


def test_heading_match_is_confined_to_its_documented_band():
    """Weak evidence must not be able to carry a case or clear a vessel."""
    assert heading_score(0.0) == pytest.approx(HEADING_CEILING, abs=1e-3)
    assert heading_score(180.0) == pytest.approx(HEADING_FLOOR, abs=1e-3)
    for course in range(0, 360, 15):
        assert HEADING_FLOOR <= heading_score(float(course)) <= HEADING_CEILING


def test_heading_match_decreases_with_angular_difference():
    scores = [heading_score(float(difference)) for difference in (0, 30, 60, 90, 120, 150, 180)]
    assert scores == sorted(scores, reverse=True)


def test_heading_match_uses_the_slick_axis_as_corroboration():
    """The axis is a line, not a direction: 90 deg and 270 deg agree with it equally."""
    along = heading_score(90.0, principal_axis_deg=90.0)
    against = heading_score(270.0, principal_axis_deg=90.0)
    across = heading_score(90.0, principal_axis_deg=0.0)
    assert along == pytest.approx(against)
    assert along > across


def test_heading_match_derives_a_course_when_none_is_reported():
    samples = (
        TrackSample(timestamp=WINDOW_START, lon=CENTRE_LON, lat=CENTRE_LAT - 0.3),
        TrackSample(
            timestamp=WINDOW_START + timedelta(minutes=15), lon=CENTRE_LON, lat=CENTRE_LAT - 0.28
        ),
    )
    factor = score_heading_match(
        spill=spill_without_axis(), origin=origin(), track=TrackContext(samples=samples)
    )
    assert factor.evidence["course_source"] == "derived"
    assert factor.score > HEADING_FLOOR


def test_heading_match_without_any_course_is_insufficient_not_zero():
    lon, lat = point_south_of_region(20.0)
    factor = score_heading_match(
        spill=spill_without_axis(), origin=origin(), track=one_position(lon, lat)
    )
    assert factor.score == INSUFFICIENT_DATA_SCORE
    assert factor.evidence["insufficient_data"] is True


def test_heading_match_without_a_track_is_insufficient_not_zero():
    factor = score_heading_match(spill=spill_without_axis(), origin=origin(), track=TrackContext())
    assert factor.score == INSUFFICIENT_DATA_SCORE


# ============================================================ SCORE-005 speed
def test_speed_plausibility_curve_has_the_documented_shape():
    assert speed_plausibility(0.0) == pytest.approx(0.55)
    assert speed_plausibility(SPEED_PLATEAU_MIN_KNOTS) == pytest.approx(1.0)
    assert speed_plausibility(8.0) == pytest.approx(1.0)
    assert speed_plausibility(SPEED_PLATEAU_MAX_KNOTS) == pytest.approx(1.0)
    assert speed_plausibility(20.0) == pytest.approx(0.30)
    assert speed_plausibility(35.0) == pytest.approx(0.30)


def test_speed_plausibility_is_monotonic_on_each_side_of_the_plateau():
    rising = [speed_plausibility(v) for v in (0.0, 1.0, 2.0, 3.0, 4.0)]
    falling = [speed_plausibility(v) for v in (12.0, 14.0, 16.0, 18.0, 20.0)]
    assert rising == sorted(rising)
    assert falling == sorted(falling, reverse=True)


def test_speed_plausibility_never_reaches_zero():
    """A discharge is physically possible at any speed; the curve ranks, it never rules out."""
    assert all(speed_plausibility(float(v)) > 0.0 for v in range(0, 60))


def test_speed_match_prefers_steady_transit_over_erratic_manoeuvring():
    steady = crossing_track(sog=6.0)
    erratic_samples = tuple(
        TrackSample(
            timestamp=sample.timestamp,
            lon=sample.lon,
            lat=sample.lat,
            sog_knots=[1.0, 11.0][index % 2],
            cog_deg=sample.cog_deg,
        )
        for index, sample in enumerate(steady.samples)
    )
    erratic = TrackContext(samples=erratic_samples)
    assert score_speed_match(track=steady).score == pytest.approx(1.0)
    assert score_speed_match(track=erratic).score < score_speed_match(track=steady).score


def test_speed_match_drops_steadiness_rather_than_assuming_it_for_one_position():
    factor = score_speed_match(track=one_position(CENTRE_LON, CENTRE_LAT, sog_knots=6.0))
    assert factor.evidence["steadiness"] is None
    assert factor.score == pytest.approx(1.0)


def test_speed_match_without_any_reported_speed_is_insufficient_not_zero():
    factor = score_speed_match(track=crossing_track(sog=None))
    assert factor.score == INSUFFICIENT_DATA_SCORE
    assert factor.evidence["insufficient_data"] is True


# ============================================================ SCORE-006 AIS reliability
def test_ais_reliability_uses_the_documented_sub_weights():
    assert AIS_SUB_WEIGHTS == {
        "coverage": 0.30,
        "continuity": 0.25,
        "density": 0.20,
        "cleanliness": 0.15,
        "identity": 0.10,
    }
    assert sum(AIS_SUB_WEIGHTS.values()) == pytest.approx(1.0)
    perfect = score_ais_reliability(
        coverage=1.0, continuity=1.0, density=1.0, cleanliness=1.0, identity=1.0
    )
    absent = score_ais_reliability(
        coverage=0.0, continuity=0.0, density=0.0, cleanliness=0.0, identity=0.0
    )
    coverage_only = score_ais_reliability(
        coverage=1.0, continuity=0.0, density=0.0, cleanliness=0.0, identity=0.0
    )
    assert perfect.score == pytest.approx(1.0)
    assert absent.score == pytest.approx(0.0)
    assert coverage_only.score == pytest.approx(0.30)


def test_ais_reliability_is_monotonic_in_every_sub_score():
    base = {
        "coverage": 0.5,
        "continuity": 0.5,
        "density": 0.5,
        "cleanliness": 0.5,
        "identity": 0.5,
    }
    baseline = score_ais_reliability(**base).score
    for name in base:
        better = score_ais_reliability(**{**base, name: 0.9})
        worse = score_ais_reliability(**{**base, name: 0.1})
        assert worse.score < baseline < better.score


def test_unmeasured_sub_scores_are_not_credited_as_good():
    partial = score_ais_reliability(coverage=1.0)
    assert partial.score < 1.0
    assert set(partial.evidence["unmeasured"]) == {
        "continuity",
        "density",
        "cleanliness",
        "identity",
    }
    assert partial.score == pytest.approx(0.30 + 0.70 * INSUFFICIENT_DATA_SCORE)


def test_ais_reliability_with_nothing_measurable_is_insufficient_not_zero():
    factor = score_ais_reliability()
    assert factor.score == INSUFFICIENT_DATA_SCORE
    assert factor.evidence["insufficient_data"] is True


def test_derive_continuity_falls_to_zero_at_the_dark_period_threshold():
    """720 min is the dark-period threshold (AD-24); it lowers confidence, nothing more."""
    expectations = {0.0: 1.0, 180.0: 0.75, 360.0: 0.5, 720.0: 0.0, 1440.0: 0.0}
    for gap_minutes, expected in expectations.items():
        track = TrackContext(
            samples=crossing_track().samples,
            max_gap_minutes=gap_minutes,
            expected_position_count=12,
            coverage_ratio=0.9,
            static_completeness=1.0,
        )
        assert derive_ais_subscores(track).continuity == pytest.approx(expected)


def test_derive_ais_subscores_leaves_unknown_components_none():
    """Assuming perfect AIS because nobody told us otherwise would inflate every score."""
    subscores = derive_ais_subscores(TrackContext(samples=crossing_track().samples))
    assert subscores.coverage is None
    assert subscores.density is None
    assert subscores.identity is None
    assert subscores.cleanliness == pytest.approx(1.0)
    assert subscores.notes


def test_a_gap_can_only_ever_lower_the_ais_factor():
    """CON-002: a gap reduces confidence; it never raises suspicion."""
    clean = TrackContext(
        samples=crossing_track().samples,
        position_count=11,
        expected_position_count=12,
        coverage_ratio=0.95,
        max_gap_minutes=20.0,
        static_completeness=1.0,
    )
    gapped = TrackContext(
        samples=crossing_track().samples,
        position_count=6,
        expected_position_count=12,
        coverage_ratio=0.55,
        max_gap_minutes=14 * 60.0,
        static_completeness=1.0,
    )
    clean_score = score_ais_reliability(**derive_ais_subscores(clean).as_dict()).score
    gapped_score = score_ais_reliability(**derive_ais_subscores(gapped).as_dict()).score
    assert gapped_score < clean_score


# ============================================================ shared invariants
def test_every_factor_is_clamped_and_explained():
    factors = [
        score_origin_proximity(origin=origin(contours=CONTOURS), track=crossing_track()),
        score_time_match(origin=origin(), track=crossing_track()),
        score_trajectory_match(origin=origin(), track=crossing_track()),
        score_heading_match(spill=spill_without_axis(), origin=origin(), track=crossing_track()),
        score_speed_match(track=crossing_track()),
        score_ais_reliability(**derive_ais_subscores(crossing_track()).as_dict()),
    ]
    assert {factor.key for factor in factors} == set(FactorKey)
    for factor in factors:
        assert 0.0 <= factor.score <= 1.0
        assert factor.contribution == pytest.approx(factor.weight * factor.score)
        assert factor.explanation.strip()
        assert factor.evidence


def test_track_context_can_be_built_from_raw_tuples():
    """The adapter-facing shortcut: ``(timestamp, lon, lat, sog, cog, heading)`` rows."""
    track = TrackContext.from_tuples(
        [
            (WINDOW_START, 72.35, CENTRE_LAT, 6.0, 90.0, 90.0),
            (WINDOW_START + timedelta(minutes=15), 72.50, CENTRE_LAT, 6.0, 90.0),
            (WINDOW_START + timedelta(minutes=30), 72.65, CENTRE_LAT),
        ],
        expected_position_count=3,
    )
    assert track.observed_position_count == 3
    assert track.samples[1].heading_deg is None
    assert track.samples[2].sog_knots is None
    assert score_trajectory_match(origin=origin(), track=track).evidence["relation"] == "crossed"


def test_naive_timestamps_are_read_as_utc_rather_than_refused():
    """Every timestamp in this system is UTC; refusing to score over a missing tzinfo
    would be a worse failure than assuming it."""
    aware = score_time_match(
        origin=origin(), track=crossing_track(WINDOW_START + timedelta(minutes=15))
    )
    naive = score_time_match(
        origin=OriginContext(
            region_geojson=REGION,
            window_start=WINDOW_START.replace(tzinfo=None),
            window_end=WINDOW_END.replace(tzinfo=None),
        ),
        track=crossing_track((WINDOW_START + timedelta(minutes=15)).replace(tzinfo=None)),
    )
    assert naive.score == pytest.approx(aware.score)
