"""Scoring engine: golden cases, the PRD's non-goals, determinism (P19-008, P19-012).

The golden cases check that the model says sensible things.  The adversarial cases
check that it refuses to say the two things the PRD explicitly forbids: that the nearest
vessel is the culprit (CON-001) and that going dark is evidence of anything (CON-002).
Those two are the point of the whole exercise, so they are asserted on ordering and on
scores, not on prose.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import permutations

import pytest

from spilltrace.core.enums import DataProvenance
from spilltrace.core.errors import ValidationError
from spilltrace.core.geometry import destination_point
from spilltrace.core.scoring.engine import (
    rank_candidates,
    score_candidate,
    shortfall_note,
)
from spilltrace.core.scoring.factors import HEADING_CEILING, INSUFFICIENT_DATA_SCORE
from spilltrace.core.scoring.inputs import (
    OriginContext,
    SpillContext,
    TrackContext,
    TrackSample,
    VesselContext,
)
from spilltrace.core.scoring.model import (
    CONFIDENCE_HIGH_MIN,
    DEFAULT_WEIGHTS,
    FACTOR_ORDER,
    Attribution,
    ConfidenceLabel,
    FactorKey,
    ScoringWeights,
    VesselRef,
    make_factor,
)

# --------------------------------------------------------------------------- scenario
# A slick off the Maharashtra coast, detected the morning after an overnight discharge.
CENTRE_LON = 72.50
CENTRE_LAT = 18.50
HALF = 0.10
SOUTH_EDGE_LAT = CENTRE_LAT - HALF
WINDOW_START = datetime(2026, 8, 1, 17, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 8, 1, 20, 0, tzinfo=UTC)
TRACK_START = datetime(2026, 8, 1, 17, 15, tzinfo=UTC)
DETECTION_TIME = datetime(2026, 8, 2, 6, 0, tzinfo=UTC)


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
#: An east-west slick, so a vessel steaming 090 lies along its principal axis.
SLICK = {
    "type": "Polygon",
    "coordinates": [
        [
            [72.42, 18.495],
            [72.62, 18.495],
            [72.62, 18.505],
            [72.42, 18.505],
            [72.42, 18.495],
        ]
    ],
}

SPILL = SpillContext(
    detection_time=DETECTION_TIME,
    centroid_lon=CENTRE_LON,
    centroid_lat=CENTRE_LAT,
    geometry_geojson=SLICK,
    data_provenance=DataProvenance.SYNTHETIC,
)
ORIGIN = OriginContext(
    region_geojson=REGION,
    contours=CONTOURS,
    window_start=WINDOW_START,
    window_end=WINDOW_END,
    origin_confidence=0.72,
    data_provenance=DataProvenance.SYNTHETIC,
)

GOOD_AIS = {
    "position_count": 11,
    "expected_position_count": 12,
    "coverage_ratio": 0.95,
    "rejected_count": 0,
    "gap_count": 1,
    "max_gap_minutes": 20.0,
    "total_gap_minutes": 20.0,
    "static_completeness": 1.0,
}


def track(
    start: datetime,
    *,
    lon0: float,
    lat0: float,
    dlon: float = 0.0,
    dlat: float = 0.0,
    sog: float | None = 6.0,
    cog: float | None = 90.0,
    count: int = 11,
    step_minutes: int = 15,
    **quality,
) -> TrackContext:
    samples = tuple(
        TrackSample(
            timestamp=start + timedelta(minutes=step_minutes * i),
            lon=lon0 + dlon * i,
            lat=lat0 + dlat * i,
            sog_knots=sog,
            cog_deg=cog,
            heading_deg=cog,
        )
        for i in range(count)
    )
    return TrackContext(
        samples=samples, data_provenance=DataProvenance.SYNTHETIC, **{**GOOD_AIS, **quality}
    )


def vessel(mmsi: int, name: str) -> VesselContext:
    return VesselContext(
        mmsi=mmsi,
        imo=9000000 + (mmsi % 1000),
        name=f"{name} (SYNTHETIC)",
        ship_type="TANKER",
        data_provenance=DataProvenance.SYNTHETIC,
    )


def crossing_candidate(start: datetime = TRACK_START, mmsi: int = 419001234, **quality):
    """Straight west-to-east through the middle of the origin region."""
    return score_candidate(
        SPILL,
        ORIGIN,
        vessel(mmsi, "DEMO CARRIER"),
        track(start, lon0=72.35, lat0=CENTRE_LAT, dlon=0.03, **quality),
    )


# ============================================================ golden cases
def test_a_strong_candidate_scores_high():
    """Inside the innermost contour, inside the window, clean AIS."""
    attribution = crossing_candidate()
    assert attribution.final_score > 0.90
    assert attribution.confidence_label is ConfidenceLabel.HIGH
    assert attribution.factor(FactorKey.ORIGIN_PROXIMITY).evidence["contour_percentile"] == 95
    assert attribution.factor(FactorKey.TIME_MATCH).score == pytest.approx(1.0)
    assert attribution.factor(FactorKey.TRAJECTORY_MATCH).evidence["relation"] == "crossed"
    assert attribution.scoring_version == "prd-j-v1"


def test_a_vessel_two_hundred_kilometres_away_scores_low():
    """Present during the window, but nowhere near the origin region."""
    far_lon, far_lat = destination_point(CENTRE_LON, SOUTH_EDGE_LAT, 180.0, 200_000.0)
    attribution = score_candidate(
        SPILL,
        ORIGIN,
        vessel(419009999, "DISTANT TRADER"),
        track(TRACK_START, lon0=far_lon, lat0=far_lat, dlat=-0.01, sog=14.0, cog=180.0),
    )
    assert attribution.final_score < 0.45
    assert attribution.confidence_label is ConfidenceLabel.LOW
    assert attribution.factor(FactorKey.ORIGIN_PROXIMITY).score < 0.01
    assert attribution.factor(FactorKey.TRAJECTORY_MATCH).evidence["relation"] == "distant"
    # Its residual score comes entirely from being observable during the window and
    # from ordinary seamanship, which is exactly why CON-003 forbids reading a score
    # as a probability of anything.
    assert attribution.factor(FactorKey.TIME_MATCH).score == pytest.approx(1.0)


def test_a_vessel_present_in_space_but_three_days_out_of_the_window_loses_the_time_weight():
    """Same track, shifted three days: it forfeits exactly the time-match weight."""
    present = crossing_candidate()
    out_of_window = crossing_candidate(TRACK_START - timedelta(days=3), mmsi=419001235)

    assert out_of_window.factor(FactorKey.TIME_MATCH).score == 0.0
    assert out_of_window.final_score == pytest.approx(
        present.final_score - DEFAULT_WEIGHTS.time_match, abs=1e-9
    )
    assert out_of_window.confidence_label is not ConfidenceLabel.HIGH
    assert rank_candidates([out_of_window, present])[0].vessel_ref.mmsi == 419001234


def test_no_candidate_without_temporal_overlap_can_ever_be_labelled_high():
    """A structural guarantee, not a warning label (CON-001).

    With ``time_match == 0`` the arithmetic ceiling of the model is below the HIGH band,
    because the heading factor is itself capped at 0.90.  So "nearest" can never reach
    the top band on spatial evidence alone.
    """
    ceiling_without_time = (
        DEFAULT_WEIGHTS.origin_proximity * 1.0
        + DEFAULT_WEIGHTS.time_match * 0.0
        + DEFAULT_WEIGHTS.trajectory_match * 1.0
        + DEFAULT_WEIGHTS.heading_match * HEADING_CEILING
        + DEFAULT_WEIGHTS.speed_match * 1.0
        + DEFAULT_WEIGHTS.ais_reliability * 1.0
    )
    assert ceiling_without_time < CONFIDENCE_HIGH_MIN


# ============================================================ adversarial: CON-001
def passing_candidate(start: datetime, distance_km: float, mmsi: int) -> Attribution:
    """A track running west-to-east ``distance_km`` south of the origin region."""
    _, lat = destination_point(CENTRE_LON, SOUTH_EDGE_LAT, 180.0, distance_km * 1000.0)
    return score_candidate(
        SPILL,
        ORIGIN,
        vessel(mmsi, "PASSING VESSEL"),
        track(start, lon0=72.44, lat0=lat, dlon=0.02, sog=8.0),
    )


def test_nearest_is_not_guilty():
    """CON-001 — the closest vessel must lose to a further, temporally compatible one.

    ``nearest`` passes 0.5 km from the origin region; ``timely`` passes 6 km away.  On
    distance alone the ranking would be the wrong way round, and this assertion is the
    thing that would fail if anybody ever reweighted the model towards proximity.
    """
    nearest = passing_candidate(TRACK_START - timedelta(days=3), 0.5, 419002001)
    timely = passing_candidate(TRACK_START, 6.0, 419002002)

    nearest_km = nearest.factor(FactorKey.ORIGIN_PROXIMITY).evidence["closest_approach_km"]
    timely_km = timely.factor(FactorKey.ORIGIN_PROXIMITY).evidence["closest_approach_km"]
    assert nearest_km < timely_km
    assert nearest.factor(FactorKey.ORIGIN_PROXIMITY).score > (
        timely.factor(FactorKey.ORIGIN_PROXIMITY).score
    )

    assert timely.final_score > nearest.final_score
    ranked = rank_candidates([nearest, timely])
    assert [candidate.vessel_ref.mmsi for candidate in ranked] == [419002002, 419002001]
    assert ranked[0].rank == 1


# ============================================================ adversarial: CON-002
def test_an_ais_gap_lowers_the_score_and_never_raises_it():
    """CON-002 — two identical vessels; one has a 14-hour reporting gap.

    Only the AIS quality statistics differ, so any change in the final score can only
    have come from SCORE-006.  It must go down.
    """
    clean = crossing_candidate(mmsi=419003001)
    gapped = crossing_candidate(
        mmsi=419003002,
        position_count=6,
        coverage_ratio=0.55,
        gap_count=2,
        max_gap_minutes=14 * 60.0,
        total_gap_minutes=14 * 60.0 + 20.0,
    )

    assert gapped.factor(FactorKey.AIS_RELIABILITY).score < (
        clean.factor(FactorKey.AIS_RELIABILITY).score
    )
    assert gapped.factor(FactorKey.AIS_RELIABILITY).evidence["continuity"] == pytest.approx(0.0)
    assert gapped.final_score < clean.final_score

    for key in FACTOR_ORDER:
        if key is not FactorKey.AIS_RELIABILITY:
            assert gapped.factor(key).score == clean.factor(key).score, key

    assert rank_candidates([gapped, clean])[0].vessel_ref.mmsi == 419003001


# ============================================================ determinism
def test_scoring_the_same_inputs_twice_is_identical():
    first = crossing_candidate()
    second = crossing_candidate()
    assert first.to_dict() == second.to_dict()
    assert first.final_score == second.final_score


def test_ranking_is_stable_under_input_shuffling():
    candidates = [
        crossing_candidate(mmsi=419004001),
        passing_candidate(TRACK_START, 6.0, 419004002),
        passing_candidate(TRACK_START - timedelta(days=3), 0.5, 419004003),
        crossing_candidate(TRACK_START - timedelta(days=3), mmsi=419004004),
    ]
    expected = [candidate.vessel_ref.mmsi for candidate in rank_candidates(candidates)]
    for ordering in permutations(candidates):
        assert [c.vessel_ref.mmsi for c in rank_candidates(list(ordering))] == expected


def synthetic_attribution(mmsi: int, **scores: float) -> Attribution:
    factors = [
        make_factor(
            key,
            weight=DEFAULT_WEIGHTS.for_key(key),
            score=scores.get(key.value, 0.0),
            explanation=f"Synthetic test value for {key.value}.",
        )
        for key in FACTOR_ORDER
    ]
    return Attribution.build(
        vessel_ref=VesselRef(mmsi=mmsi, name=f"TEST {mmsi}"),
        factors=factors,
        weights=DEFAULT_WEIGHTS,
    )


def test_ties_break_on_origin_proximity_then_reliability_then_mmsi():
    # Equal final scores (0.38), different origin proximity.
    stronger_proximity = synthetic_attribution(555, origin_proximity=0.8, time_match=0.5)
    weaker_proximity = synthetic_attribution(
        111, origin_proximity=0.4, time_match=1.0, trajectory_match=0.4 / 1.5
    )
    assert stronger_proximity.final_score == pytest.approx(weaker_proximity.final_score)
    ranked = rank_candidates([weaker_proximity, stronger_proximity])
    assert [candidate.vessel_ref.mmsi for candidate in ranked] == [555, 111]

    # Equal final score and equal proximity, different AIS reliability.
    better_ais = synthetic_attribution(777, origin_proximity=0.5, ais_reliability=0.9)
    worse_ais = synthetic_attribution(
        222, origin_proximity=0.5, ais_reliability=0.3, time_match=0.3
    )
    assert better_ais.final_score == pytest.approx(worse_ais.final_score)
    assert [c.vessel_ref.mmsi for c in rank_candidates([worse_ais, better_ais])] == [777, 222]

    # Identical in every scored respect: MMSI ascending, so the order is still stable.
    low = synthetic_attribution(101, origin_proximity=0.5)
    high = synthetic_attribution(999, origin_proximity=0.5)
    assert [c.vessel_ref.mmsi for c in rank_candidates([high, low])] == [101, 999]


def test_ranks_are_assigned_from_one_and_inputs_are_untouched():
    candidates = [
        crossing_candidate(mmsi=419005001),
        passing_candidate(TRACK_START, 6.0, 419005002),
    ]
    ranked = rank_candidates(candidates)
    assert [candidate.rank for candidate in ranked] == [1, 2]
    assert all(candidate.rank == 0 for candidate in candidates)


# ============================================================ never pad the list
def test_the_candidate_list_is_never_padded():
    """AD-29 / ambiguity A-10 — reality is reported as found, even when it is thin."""
    assert rank_candidates([]) == []
    assert len(rank_candidates([crossing_candidate()])) == 1
    two = [crossing_candidate(mmsi=419006001), crossing_candidate(mmsi=419006002)]
    assert len(rank_candidates(two)) == 2

    assert shortfall_note(0) is not None
    assert shortfall_note(2) is not None
    assert shortfall_note(3) is None
    assert "not been padded" in shortfall_note(2)


# ============================================================ missing data
def test_a_vessel_with_no_track_at_all_degrades_gracefully():
    attribution = score_candidate(SPILL, ORIGIN, vessel(419007001, "NO TRACK"), TrackContext())
    assert attribution.final_score == pytest.approx(INSUFFICIENT_DATA_SCORE)
    assert attribution.confidence_label is ConfidenceLabel.LOW
    for key in FACTOR_ORDER:
        factor = attribution.factor(key)
        assert factor.score == INSUFFICIENT_DATA_SCORE
        assert factor.evidence["insufficient_data"] is True
        assert factor.explanation.strip()


def test_a_missing_heading_only_degrades_the_heading_factor():
    with_heading = crossing_candidate(mmsi=419007002)
    without_heading = score_candidate(
        SPILL,
        ORIGIN,
        vessel(419007003, "NO HEADING"),
        track(TRACK_START, lon0=72.35, lat0=CENTRE_LAT, dlon=0.03, cog=None),
    )
    # A course can still be derived from consecutive positions, so this degrades to a
    # measured value rather than to "unknown" - but it must never crash.
    assert without_heading.factor(FactorKey.HEADING_MATCH).evidence["course_source"] == "derived"
    for key in (FactorKey.ORIGIN_PROXIMITY, FactorKey.TIME_MATCH, FactorKey.SPEED_MATCH):
        assert without_heading.factor(key).score == with_heading.factor(key).score


def test_an_origin_with_no_contours_still_scores():
    bare = OriginContext(
        region_geojson=REGION, contours=(), window_start=WINDOW_START, window_end=WINDOW_END
    )
    attribution = score_candidate(
        SPILL,
        bare,
        vessel(419007004, "NO CONTOURS"),
        track(TRACK_START, lon0=72.35, lat0=CENTRE_LAT, dlon=0.03),
    )
    proximity = attribution.factor(FactorKey.ORIGIN_PROXIMITY)
    assert proximity.evidence["contour_percentile"] is None
    assert proximity.evidence["inside_origin_region"] is True
    assert 0.0 < proximity.score < 1.0
    assert attribution.final_score < crossing_candidate().final_score


def test_an_origin_with_nothing_at_all_scores_every_spatial_factor_as_unmeasured():
    attribution = score_candidate(
        SPILL,
        OriginContext(),
        vessel(419007005, "NO ORIGIN"),
        track(TRACK_START, lon0=72.35, lat0=CENTRE_LAT, dlon=0.03),
    )
    for key in (FactorKey.ORIGIN_PROXIMITY, FactorKey.TIME_MATCH, FactorKey.TRAJECTORY_MATCH):
        assert attribution.factor(key).score == INSUFFICIENT_DATA_SCORE
    # Speed is a property of the track alone, so it is still measurable.
    assert attribution.factor(FactorKey.SPEED_MATCH).score == pytest.approx(1.0)


def test_out_of_order_samples_do_not_change_the_result():
    ordered = crossing_candidate(mmsi=419007006)
    forwards = track(TRACK_START, lon0=72.35, lat0=CENTRE_LAT, dlon=0.03)
    shuffled = TrackContext(
        samples=tuple(reversed(forwards.samples)),
        data_provenance=DataProvenance.SYNTHETIC,
        **GOOD_AIS,
    )
    reversed_result = score_candidate(SPILL, ORIGIN, vessel(419007006, "DEMO CARRIER"), shuffled)
    assert reversed_result.final_score == pytest.approx(ordered.final_score)


# ============================================================ weights & provenance
def test_the_final_score_is_the_sum_of_the_contributions():
    attribution = crossing_candidate()
    assert attribution.final_score == pytest.approx(
        sum(factor.contribution for factor in attribution.factors)
    )
    assert [factor.key for factor in attribution.factors] == list(FACTOR_ORDER)


def test_custom_weights_are_honoured_and_persisted_with_the_result():
    """SCORE-008 - weights are configurable, and travel with the attribution."""
    proximity_heavy = ScoringWeights(
        origin_proximity=0.50,
        time_match=0.20,
        trajectory_match=0.10,
        heading_match=0.05,
        speed_match=0.05,
        ais_reliability=0.10,
    )
    attribution = score_candidate(
        SPILL,
        ORIGIN,
        vessel(419008001, "WEIGHTED"),
        track(TRACK_START, lon0=72.35, lat0=CENTRE_LAT, dlon=0.03),
        proximity_heavy,
    )
    assert attribution.weights == proximity_heavy
    assert attribution.to_dict()["weights"]["origin_proximity"] == 0.50
    assert attribution.factor(FactorKey.ORIGIN_PROXIMITY).weight == 0.50


def test_weights_that_do_not_sum_to_one_are_refused_before_anything_is_scored():
    broken = ScoringWeights(origin_proximity=0.90)
    with pytest.raises(ValidationError):
        score_candidate(
            SPILL,
            ORIGIN,
            vessel(419008002, "BROKEN"),
            track(TRACK_START, lon0=72.35, lat0=CENTRE_LAT, dlon=0.03),
            broken,
        )


def test_synthetic_inputs_propagate_to_the_attribution():
    """CON-009 - a result built from synthetic data can never look like an observation."""
    assert crossing_candidate().data_provenance is DataProvenance.SYNTHETIC


def test_factor_scores_map_onto_the_database_columns():
    scores = crossing_candidate().factor_scores()
    assert set(scores) == {key.value for key in FACTOR_ORDER}
    assert all(0.0 <= value <= 1.0 for value in scores.values())
