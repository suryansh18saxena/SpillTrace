"""Look-alike verification.

The properties that matter: a physical impossibility must not be out-voted by
circumstantial evidence, missing evidence must not be read as evidence against, and
every verdict must carry a readable explanation free of prejudicial language.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import MultiPolygon, Point

from spilltrace.core.disclaimers import contains_forbidden_language
from spilltrace.core.enums import VerificationStatus
from spilltrace.core.lookalike import extract_features, verify_detection
from spilltrace.core.lookalike.classifier import build_classifier
from spilltrace.core.lookalike.features import (
    backscatter_features,
    border_gradient,
    geometric_features,
)
from spilltrace.core.lookalike.rules import DEFAULT_RULES, RuleSet
from spilltrace.demo.slick import probability_grid, synthetic_slick

SLICK = synthetic_slick(
    centre=(69.42, 22.44), length_km=42.0, width_km=2.6, bearing_deg=118.0, seed=42
)
GRID, _ = probability_grid(SLICK, seed=42)
ROUND_PATCH = MultiPolygon([Point(69.42, 22.44).buffer(0.08)])


def features_for(
    geometry=SLICK,
    *,
    wind: float | None = 5.4,
    slick_db: float = -22.0,
    bg_db: float = -9.5,
    grid=GRID,
):
    rng = np.random.default_rng(11)
    return extract_features(
        geometry,
        probability_grid=grid,
        slick_values_db=rng.normal(slick_db, 1.1, 4000),
        background_values_db=rng.normal(bg_db, 2.4, 8000),
        wind_speed_ms=wind,
        wind_direction_deg=232.0,
        wind_source="TEST",
    )


class TestRuleWeights:
    def test_weights_sum_to_one(self) -> None:
        f = features_for()
        assert sum(rule(f).weight for rule in DEFAULT_RULES) == pytest.approx(1.0)

    def test_every_rule_produces_a_message(self) -> None:
        for result in RuleSet().evaluate(features_for()):
            assert result.message.strip()
            assert -1.0 <= result.evidence <= 1.0


class TestWindGate:
    @pytest.mark.parametrize("wind", [0.0, 1.0, 1.99])
    def test_glassy_sea_is_rejected(self, wind: float) -> None:
        # Below ~2 m/s there are no Bragg waves for oil to damp, so a dark patch cannot
        # be attributed to oil however convincing its shape and contrast.
        outcome = verify_detection(features_for(wind=wind))
        assert outcome.status is VerificationStatus.FALSE_POSITIVE

    @pytest.mark.parametrize("wind", [12.5, 18.0])
    def test_high_wind_is_rejected(self, wind: float) -> None:
        assert verify_detection(features_for(wind=wind)).status is (
            VerificationStatus.FALSE_POSITIVE
        )

    @pytest.mark.parametrize("wind", [4.0, 5.4, 7.0, 9.9])
    def test_the_operational_window_is_accepted(self, wind: float) -> None:
        assert verify_detection(features_for(wind=wind)).status is VerificationStatus.VERIFIED

    def test_a_veto_is_not_outvoted_by_favourable_evidence(self) -> None:
        # Identical geometry and contrast, only the wind differs.
        good = verify_detection(features_for(wind=5.4))
        glassy = verify_detection(features_for(wind=1.0))
        assert good.status is VerificationStatus.VERIFIED
        assert glassy.status is VerificationStatus.FALSE_POSITIVE
        assert "glassy" in glassy.explanation.lower()


class TestContrast:
    def test_no_contrast_is_decisive(self) -> None:
        # A feature barely darker than the sea is not a dark feature at all.
        outcome = verify_detection(features_for(slick_db=-11.0, bg_db=-9.5))
        assert outcome.status is VerificationStatus.FALSE_POSITIVE

    def test_strong_contrast_supports_oil(self) -> None:
        assert verify_detection(features_for(slick_db=-24.0)).status is (
            VerificationStatus.VERIFIED
        )


class TestUncertainty:
    def test_missing_wind_produces_uncertain_not_rejection(self) -> None:
        # Absence of evidence must not be scored as evidence of absence.
        outcome = verify_detection(extract_features(SLICK, probability_grid=GRID))
        assert outcome.status is VerificationStatus.UNCERTAIN
        assert outcome.coverage < 0.45
        assert "could not be applied" in outcome.explanation

    def test_ambiguous_feature_is_uncertain(self) -> None:
        outcome = verify_detection(features_for(geometry=ROUND_PATCH, wind=3.0, slick_db=-12.5))
        assert outcome.status is VerificationStatus.UNCERTAIN

    def test_confidence_never_reaches_certainty(self) -> None:
        for wind in (1.0, 3.0, 5.4, 8.0, 14.0):
            assert 0.0 < verify_detection(features_for(wind=wind)).confidence < 1.0


class TestExplanations:
    def test_no_prejudicial_language(self) -> None:
        for wind in (1.0, 3.0, 5.4, 11.0, 14.0):
            outcome = verify_detection(features_for(wind=wind))
            assert contains_forbidden_language(outcome.explanation) == []

    def test_explanation_names_the_limits_of_the_method(self) -> None:
        outcome = verify_detection(features_for())
        assert "biogenic" in outcome.explanation.lower()

    def test_explanation_reports_coverage(self) -> None:
        assert "% of the available checks" in verify_detection(features_for()).explanation


class TestFeatures:
    def test_elongated_slick_scores_higher_complexity_than_a_disc(self) -> None:
        slick = geometric_features(SLICK)
        disc = geometric_features(ROUND_PATCH)
        assert slick["complexity"] > disc["complexity"]
        assert slick["elongation"] > disc["elongation"]
        assert disc["complexity"] == pytest.approx(1.0, abs=0.05)

    def test_contrast_is_positive_when_the_slick_is_darker(self) -> None:
        rng = np.random.default_rng(3)
        result = backscatter_features(rng.normal(-22.0, 1.0, 2000), rng.normal(-9.0, 2.0, 2000))
        assert result["contrast_db"] == pytest.approx(13.0, abs=0.5)

    def test_uniform_slick_has_lower_relative_variance(self) -> None:
        rng = np.random.default_rng(5)
        uniform = backscatter_features(rng.normal(-22.0, 0.5, 4000), rng.normal(-9.0, 3.0, 4000))
        variable = backscatter_features(rng.normal(-22.0, 4.0, 4000), rng.normal(-9.0, 3.0, 4000))
        assert uniform["power_to_mean_ratio"] < variable["power_to_mean_ratio"]

    def test_empty_samples_yield_no_features(self) -> None:
        assert backscatter_features(np.array([]), np.array([])) == {}

    def test_border_gradient_needs_a_transition_band(self) -> None:
        flat = np.zeros((20, 20))
        assert border_gradient(flat)["gradient_mean"] == 0.0
        assert border_gradient(GRID)["gradient_mean"] > 0.0

    def test_features_serialise(self) -> None:
        payload = features_for().to_dict()
        assert payload["wind_speed_ms"] == 5.4
        assert payload["area_km2"] > 0


class TestClassifierHook:
    def test_disabled_by_default(self) -> None:
        assert build_classifier(None) is None
        assert build_classifier("none") is None

    def test_unknown_classifier_fails_loudly(self) -> None:
        with pytest.raises(NotImplementedError, match="Train and evaluate one"):
            build_classifier("mystery-net")


class TestDeterminism:
    def test_same_features_give_the_same_verdict(self) -> None:
        a, b = verify_detection(features_for()), verify_detection(features_for())
        assert (a.status, a.confidence, a.evidence_score) == (
            b.status,
            b.confidence,
            b.evidence_score,
        )
