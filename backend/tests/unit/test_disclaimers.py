"""Mandated language and non-negotiable invariants (CON-001…CON-003, AC-13, P19-011).

These are the tests that stop the product's ethical constraints from being good
intentions.  They assert three things about every attribution the scorer can produce:

* it carries a non-empty disclaimer saying the result is investigative, not proof;
* none of the prose it generates contains any phrase from ``FORBIDDEN_PHRASES``;
* the weights and the version string it was produced under are recorded with it.

The scenario list below is deliberately broad — including every "insufficient data"
path — because the explanations most likely to over-claim are the ones written for
cases the model could not actually measure.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from spilltrace.core.disclaimers import (
    ATTRIBUTION_DISCLAIMER,
    FORBIDDEN_PHRASES,
    SCORE_DISCLAIMER,
    contains_forbidden_language,
)
from spilltrace.core.errors import ValidationError
from spilltrace.core.geometry import destination_point
from spilltrace.core.scoring.engine import score_candidate, shortfall_note
from spilltrace.core.scoring.explain import explain_insufficient, safe
from spilltrace.core.scoring.inputs import (
    OriginContext,
    SpillContext,
    TrackContext,
    TrackSample,
    VesselContext,
)
from spilltrace.core.scoring.model import (
    CONFIDENCE_HIGH_MIN,
    CONFIDENCE_MODERATE_MIN,
    DEFAULT_ATTRIBUTION_DISCLAIMER,
    DEFAULT_WEIGHTS,
    FACTOR_ORDER,
    SCORING_VERSION,
    WEIGHT_SUM_TOLERANCE,
    ConfidenceLabel,
    FactorKey,
    ScoringWeights,
    confidence_label,
)

CENTRE_LON = 72.50
CENTRE_LAT = 18.50
HALF = 0.10
WINDOW_START = datetime(2026, 8, 1, 17, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 8, 1, 20, 0, tzinfo=UTC)
TRACK_START = datetime(2026, 8, 1, 17, 15, tzinfo=UTC)


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
SLICK = {
    "type": "Polygon",
    "coordinates": [
        [[72.42, 18.495], [72.62, 18.495], [72.62, 18.505], [72.42, 18.505], [72.42, 18.495]]
    ],
}
SPILL = SpillContext(
    detection_time=datetime(2026, 8, 2, 6, 0, tzinfo=UTC),
    centroid_lon=CENTRE_LON,
    centroid_lat=CENTRE_LAT,
    geometry_geojson=SLICK,
)
ORIGIN = OriginContext(
    region_geojson=REGION,
    contours=CONTOURS,
    window_start=WINDOW_START,
    window_end=WINDOW_END,
    origin_confidence=0.72,
)
VESSEL = VesselContext(mmsi=419001234, imo=9123456, name="DEMO CARRIER", ship_type="TANKER")
#: The same spill with no polygon, so the heading factor has no principal axis to use.
SPILL_WITHOUT_GEOMETRY = SpillContext(
    detection_time=datetime(2026, 8, 2, 6, 0, tzinfo=UTC),
    centroid_lon=CENTRE_LON,
    centroid_lat=CENTRE_LAT,
)


def make_track(
    start: datetime = TRACK_START,
    *,
    lon0: float = 72.35,
    lat0: float = CENTRE_LAT,
    dlon: float = 0.03,
    dlat: float = 0.0,
    sog: float | None = 6.0,
    cog: float | None = 90.0,
    count: int = 11,
    **quality,
) -> TrackContext:
    samples = tuple(
        TrackSample(
            timestamp=start + timedelta(minutes=15 * i),
            lon=lon0 + dlon * i,
            lat=lat0 + dlat * i,
            sog_knots=sog,
            cog_deg=cog,
            heading_deg=cog,
        )
        for i in range(count)
    )
    defaults = {
        "position_count": count,
        "expected_position_count": 12,
        "coverage_ratio": 0.95,
        "rejected_count": 0,
        "gap_count": 1,
        "max_gap_minutes": 20.0,
        "total_gap_minutes": 20.0,
        "static_completeness": 1.0,
    }
    defaults.update(quality)
    return TrackContext(samples=samples, **defaults)


FAR_LON, FAR_LAT = destination_point(CENTRE_LON, CENTRE_LAT - HALF, 180.0, 200_000.0)


def every_scenario() -> list[tuple[str, object]]:
    """One attribution per interesting code path, including every degraded one."""
    return [
        ("strong crossing candidate", score_candidate(SPILL, ORIGIN, VESSEL, make_track())),
        (
            "vessel 200 km away",
            score_candidate(
                SPILL,
                ORIGIN,
                VESSEL,
                make_track(lon0=FAR_LON, lat0=FAR_LAT, dlon=0.0, dlat=-0.01, sog=14.0, cog=180.0),
            ),
        ),
        (
            "three days out of window",
            score_candidate(SPILL, ORIGIN, VESSEL, make_track(TRACK_START - timedelta(days=3))),
        ),
        (
            "just outside the window, inside tolerance",
            score_candidate(SPILL, ORIGIN, VESSEL, make_track(WINDOW_END + timedelta(minutes=30))),
        ),
        (
            "fourteen-hour AIS gap",
            score_candidate(
                SPILL,
                ORIGIN,
                VESSEL,
                make_track(coverage_ratio=0.55, position_count=6, max_gap_minutes=840.0),
            ),
        ),
        ("no track at all", score_candidate(SPILL, ORIGIN, VESSEL, TrackContext())),
        (
            "no origin region or window",
            score_candidate(SPILL, OriginContext(), VESSEL, make_track()),
        ),
        (
            "origin region but no contours",
            score_candidate(
                SPILL,
                OriginContext(
                    region_geojson=REGION, window_start=WINDOW_START, window_end=WINDOW_END
                ),
                VESSEL,
                make_track(),
            ),
        ),
        (
            "no reported speed",
            score_candidate(SPILL, ORIGIN, VESSEL, make_track(sog=None)),
        ),
        (
            "single position, no course",
            score_candidate(
                SPILL, ORIGIN, VESSEL, make_track(count=1, cog=None, lon0=FAR_LON, lat0=FAR_LAT)
            ),
        ),
        (
            "stopped vessel",
            score_candidate(SPILL, ORIGIN, VESSEL, make_track(sog=0.0)),
        ),
        (
            "high-speed vessel",
            score_candidate(SPILL, ORIGIN, VESSEL, make_track(sog=22.0)),
        ),
        (
            "slick geometry missing",
            score_candidate(SPILL_WITHOUT_GEOMETRY, ORIGIN, VESSEL, make_track()),
        ),
    ]


# ============================================================ the disclaimer (AC-13)
@pytest.mark.parametrize("label,attribution", every_scenario(), ids=lambda value: str(value)[:40])
def test_every_attribution_carries_a_non_empty_disclaimer(label, attribution):
    payload = attribution.to_dict()
    assert "disclaimer" in payload
    assert isinstance(payload["disclaimer"], str)
    assert payload["disclaimer"].strip(), label


def test_the_disclaimer_is_the_mandated_wording_and_not_something_improvised():
    """Composed from ``core/disclaimers.py`` so the API, UI and report cannot drift."""
    assert f"{ATTRIBUTION_DISCLAIMER} {SCORE_DISCLAIMER}" == DEFAULT_ATTRIBUTION_DISCLAIMER
    assert ATTRIBUTION_DISCLAIMER in DEFAULT_ATTRIBUTION_DISCLAIMER
    assert SCORE_DISCLAIMER in DEFAULT_ATTRIBUTION_DISCLAIMER
    assert "not automatic legal proof" in DEFAULT_ATTRIBUTION_DISCLAIMER
    assert "not a calibrated" in DEFAULT_ATTRIBUTION_DISCLAIMER


def test_the_disclaimer_quotes_the_forbidden_phrase_only_to_negate_it():
    """A deliberate, single exception, asserted so it stays deliberate.

    ``SCORE_DISCLAIMER`` contains "legal probability" inside the sentence that rules
    that reading out (CON-003).  The forbidden-language check applies to *generated*
    prose - the factor explanations - never to the mandated boilerplate, so by default
    it excludes the mandated texts; ``ignore_disclaimers=False`` scans them anyway,
    which is how this test pins the exception down.
    """
    assert contains_forbidden_language(
        DEFAULT_ATTRIBUTION_DISCLAIMER, ignore_disclaimers=False
    ) == ["legal probability"]
    assert "is not a calibrated legal probability" in DEFAULT_ATTRIBUTION_DISCLAIMER
    # And the default scan does not flag our own safeguard.
    assert contains_forbidden_language(DEFAULT_ATTRIBUTION_DISCLAIMER) == []


# ============================================================ generated prose
@pytest.mark.parametrize("label,attribution", every_scenario(), ids=lambda value: str(value)[:40])
def test_no_generated_explanation_uses_forbidden_language(label, attribution):
    for factor in attribution.factors:
        found = contains_forbidden_language(factor.explanation)
        assert found == [], f"{label} / {factor.key.value}: {found}"


@pytest.mark.parametrize("label,attribution", every_scenario(), ids=lambda value: str(value)[:40])
def test_every_factor_is_explained_and_evidenced(label, attribution):
    """SCORE-007 / MVP-09 - an unexplained number is not investigative evidence."""
    assert [factor.key for factor in attribution.factors] == list(FACTOR_ORDER)
    for factor in attribution.factors:
        assert factor.explanation.strip(), f"{label} / {factor.key.value}"
        assert len(factor.explanation) > 40, f"{label} / {factor.key.value}"
        assert isinstance(factor.evidence, dict)
        assert factor.evidence, f"{label} / {factor.key.value}"


def test_insufficient_data_explanations_are_also_clean():
    for key in FACTOR_ORDER:
        text = explain_insufficient(key, "the upstream stage produced nothing to measure.")
        assert contains_forbidden_language(text) == []
        assert "could not be measured" in text


def test_shortfall_notes_are_clean():
    for count in (0, 1, 2):
        note = shortfall_note(count)
        assert note is not None
        assert contains_forbidden_language(note) == []


def test_the_explanation_guard_actually_fires():
    """If the guard did not raise, every other test in this file would be vacuous."""
    for phrase in FORBIDDEN_PHRASES:
        with pytest.raises(ValidationError):
            safe(f"The analysis shows this is a {phrase} beyond doubt.")
    with pytest.raises(ValidationError):
        safe("   ")
    assert safe("Closest approach was 1.4 km at 18:20Z.").startswith("Closest")


# ============================================================ weights & version
def test_the_default_weights_are_the_prd_weights_and_sum_to_one():
    assert DEFAULT_WEIGHTS.to_dict() == {
        "origin_proximity": 0.35,
        "time_match": 0.20,
        "trajectory_match": 0.15,
        "heading_match": 0.10,
        "speed_match": 0.10,
        "ais_reliability": 0.10,
    }
    assert abs(sum(DEFAULT_WEIGHTS.to_dict().values()) - 1.0) <= WEIGHT_SUM_TOLERANCE
    DEFAULT_WEIGHTS.validate()


@pytest.mark.parametrize(
    "weights",
    [
        ScoringWeights(origin_proximity=0.90),
        ScoringWeights(origin_proximity=0.0),
        ScoringWeights(origin_proximity=0.35 + 1e-6),
        ScoringWeights(origin_proximity=-0.05, time_match=0.60),
    ],
)
def test_weights_that_are_not_a_valid_distribution_are_refused(weights):
    with pytest.raises(ValidationError):
        weights.validate()


def test_a_weight_set_round_trips_through_its_serialised_form():
    """SCORE-008 - a stored attribution must be re-readable in its own terms."""
    assert ScoringWeights.from_dict(DEFAULT_WEIGHTS.to_dict()) == DEFAULT_WEIGHTS
    with pytest.raises(ValidationError):
        ScoringWeights.from_dict({"orgin_proximity": 0.35})


def test_the_scoring_version_is_stable():
    """Changing this string is a schema-level event: the DB unique key includes it."""
    assert SCORING_VERSION == "prd-j-v1"
    for _label, attribution in every_scenario():
        assert attribution.scoring_version == SCORING_VERSION
        assert attribution.to_dict()["scoring_version"] == "prd-j-v1"


# ============================================================ API shape (docs/API.md §10)
def test_the_attribution_payload_matches_the_documented_shape():
    payload = score_candidate(SPILL, ORIGIN, VESSEL, make_track()).to_dict()
    assert set(payload) == {
        "id",
        "rank",
        "vessel",
        "final_score",
        "confidence_label",
        "factors",
        "weights",
        "scoring_version",
        "disclaimer",
        "discrimination_note",
        "data_provenance",
    }
    # Null on a ranking that discriminates; a sentence when the labels were capped
    # because the evidence could not separate the candidates (CON-001).
    assert payload["discrimination_note"] is None
    assert set(payload["vessel"]) == {"id", "mmsi", "name"}
    assert set(payload["weights"]) == {key.value for key in FACTOR_ORDER}
    assert payload["confidence_label"] in {"LOW", "MODERATE", "HIGH"}
    assert payload["data_provenance"] in {"REAL", "SYNTHETIC", "MIXED"}
    assert len(payload["factors"]) == 6
    for factor in payload["factors"]:
        assert set(factor) == {
            "key",
            "label",
            "weight",
            "score",
            "contribution",
            "explanation",
            "evidence",
        }
        assert factor["key"] in {key.value for key in FactorKey}
        assert 0.0 <= factor["score"] <= 1.0


# ============================================================ confidence bands (CON-003)
def test_the_confidence_bands_are_non_overlapping_and_exhaustive():
    assert CONFIDENCE_MODERATE_MIN < CONFIDENCE_HIGH_MIN
    boundaries = [
        (0.0, ConfidenceLabel.LOW),
        (CONFIDENCE_MODERATE_MIN - 1e-9, ConfidenceLabel.LOW),
        (CONFIDENCE_MODERATE_MIN, ConfidenceLabel.MODERATE),
        (CONFIDENCE_HIGH_MIN - 1e-9, ConfidenceLabel.MODERATE),
        (CONFIDENCE_HIGH_MIN, ConfidenceLabel.HIGH),
        (1.0, ConfidenceLabel.HIGH),
    ]
    for score, expected in boundaries:
        assert confidence_label(score) is expected, score
    # Exhaustive and clamped at both ends, so no score can fall outside a band.
    assert confidence_label(-5.0) is ConfidenceLabel.LOW
    assert confidence_label(5.0) is ConfidenceLabel.HIGH
    assert {confidence_label(value / 1000.0) for value in range(0, 1001)} == set(ConfidenceLabel)
