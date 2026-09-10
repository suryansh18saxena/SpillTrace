"""The discrimination guard (CON-001).

The failure this prevents is not a crash. It is a ranking that labels thirteen vessels
HIGH because the origin region contains all of them, presenting "we could not tell them
apart" as "these are all strong candidates".
"""

from __future__ import annotations

import pytest

from spilltrace.core.enums import DataProvenance
from spilltrace.core.scoring import DEFAULT_WEIGHTS, rank_candidates
from spilltrace.core.scoring.discrimination import (
    MAX_UNDISCRIMINATED_TOP,
    MIN_ORIGIN_CONFIDENCE_FOR_HIGH,
    apply_cap,
    assess,
)
from spilltrace.core.scoring.model import (
    Attribution,
    ConfidenceLabel,
    FactorKey,
    FactorScore,
    VesselRef,
    confidence_label,
)


def factor(key: FactorKey, score: float) -> FactorScore:
    weight = getattr(DEFAULT_WEIGHTS, key.value)
    return FactorScore(
        key=key,
        label=key.value.replace("_", " ").title(),
        weight=weight,
        score=score,
        contribution=weight * score,
        explanation=f"{key.value} scored {score:.2f}.",
        evidence={},
    )


def candidate(mmsi: int, *, origin: float, final: float = 0.95) -> Attribution:
    factors = [
        factor(FactorKey.ORIGIN_PROXIMITY, origin),
        factor(FactorKey.TIME_MATCH, 1.0),
        factor(FactorKey.TRAJECTORY_MATCH, 1.0),
        factor(FactorKey.HEADING_MATCH, 0.85),
        factor(FactorKey.SPEED_MATCH, 0.95),
        factor(FactorKey.AIS_RELIABILITY, 0.82),
    ]
    return Attribution(
        vessel_ref=VesselRef(mmsi=mmsi, name=f"VESSEL {mmsi}"),
        factors=factors,
        final_score=final,
        rank=0,
        weights=DEFAULT_WEIGHTS,
        scoring_version="prd-j-v1",
        confidence_label=confidence_label(final),
        data_provenance=DataProvenance.SYNTHETIC,
    )


class TestAssess:
    def test_a_discriminating_field_is_not_capped(self) -> None:
        # Three candidates with clearly separated origin proximity.
        result = assess(
            [candidate(1, origin=0.96), candidate(2, origin=0.60), candidate(3, origin=0.30)],
            origin_confidence=0.85,
        )
        assert result.is_discriminating
        assert result.cap is None
        assert result.reason is None

    def test_too_many_tied_at_the_top_caps_the_labels(self) -> None:
        # The real-path failure: a big diffuse region containing everyone.
        tied = [candidate(i, origin=0.96) for i in range(1, 14)]
        result = assess(tied, origin_confidence=0.85)
        assert result.cap is ConfidenceLabel.MODERATE
        assert result.tied_at_top == 13
        assert "does not distinguish between them" in (result.reason or "")

    def test_exactly_the_threshold_is_still_allowed(self) -> None:
        tied = [candidate(i, origin=0.96) for i in range(MAX_UNDISCRIMINATED_TOP)]
        assert assess(tied, origin_confidence=0.9).cap is None

    def test_one_over_the_threshold_is_capped(self) -> None:
        tied = [candidate(i, origin=0.96) for i in range(MAX_UNDISCRIMINATED_TOP + 1)]
        assert assess(tied, origin_confidence=0.9).cap is ConfidenceLabel.MODERATE

    def test_a_diffuse_origin_caps_even_a_separated_field(self) -> None:
        separated = [candidate(1, origin=0.96), candidate(2, origin=0.40)]
        result = assess(separated, origin_confidence=MIN_ORIGIN_CONFIDENCE_FOR_HIGH - 0.01)
        assert result.cap is ConfidenceLabel.MODERATE
        assert "diffuse" in (result.reason or "")

    def test_a_well_constrained_origin_does_not_cap(self) -> None:
        separated = [candidate(1, origin=0.96), candidate(2, origin=0.40)]
        assert assess(separated, origin_confidence=0.9).cap is None

    def test_unknown_origin_confidence_does_not_cap_on_its_own(self) -> None:
        separated = [candidate(1, origin=0.96), candidate(2, origin=0.40)]
        assert assess(separated, origin_confidence=None).cap is None

    def test_scores_within_tolerance_count_as_tied(self) -> None:
        near = [candidate(i, origin=0.96 - i * 0.001) for i in range(6)]
        assert assess(near, origin_confidence=0.9).tied_at_top == 6

    def test_an_empty_field_is_trivially_discriminating(self) -> None:
        assert assess([], origin_confidence=0.9).is_discriminating


class TestApplyCap:
    @pytest.mark.parametrize(
        ("label", "cap", "expected"),
        [
            (ConfidenceLabel.HIGH, ConfidenceLabel.MODERATE, ConfidenceLabel.MODERATE),
            (ConfidenceLabel.MODERATE, ConfidenceLabel.MODERATE, ConfidenceLabel.MODERATE),
            (ConfidenceLabel.LOW, ConfidenceLabel.MODERATE, ConfidenceLabel.LOW),
            (ConfidenceLabel.HIGH, None, ConfidenceLabel.HIGH),
            (ConfidenceLabel.LOW, ConfidenceLabel.LOW, ConfidenceLabel.LOW),
        ],
    )
    def test_capping_only_lowers(self, label, cap, expected) -> None:
        assert apply_cap(label, cap) is expected

    def test_a_cap_never_promotes(self) -> None:
        assert apply_cap(ConfidenceLabel.LOW, ConfidenceLabel.HIGH) is ConfidenceLabel.LOW


class TestRankingIntegration:
    def test_ranking_caps_labels_when_the_region_does_not_discriminate(self) -> None:
        tied = [candidate(i, origin=0.96) for i in range(1, 14)]
        ranked = rank_candidates(tied, origin_confidence=0.85)
        assert all(a.confidence_label is not ConfidenceLabel.HIGH for a in ranked)
        assert all(a.discrimination_note for a in ranked)

    def test_ranking_leaves_a_discriminating_field_alone(self) -> None:
        field = [
            candidate(1, origin=0.96, final=0.95),
            candidate(2, origin=0.55, final=0.70),
            candidate(3, origin=0.20, final=0.40),
        ]
        ranked = rank_candidates(field, origin_confidence=0.88)
        assert ranked[0].confidence_label is ConfidenceLabel.HIGH
        assert all(a.discrimination_note is None for a in ranked)

    def test_the_underlying_scores_are_never_altered(self) -> None:
        # Capping is editorial, not arithmetic: an analyst must still see the real number.
        tied = [candidate(i, origin=0.96, final=0.9546) for i in range(1, 14)]
        ranked = rank_candidates(tied, origin_confidence=0.85)
        assert all(a.final_score == pytest.approx(0.9546) for a in ranked)
        for attribution in ranked:
            origin = next(f for f in attribution.factors if f.key is FactorKey.ORIGIN_PROXIMITY)
            assert origin.score == pytest.approx(0.96)

    def test_the_reason_reaches_the_serialised_output(self) -> None:
        tied = [candidate(i, origin=0.96) for i in range(1, 14)]
        payload = rank_candidates(tied, origin_confidence=0.85)[0].to_dict()
        assert payload["confidence_label"] == "MODERATE"
        assert payload["discrimination_note"]

    def test_ranking_order_is_unchanged_by_capping(self) -> None:
        field = [candidate(i, origin=0.96, final=1.0 - i * 0.001) for i in range(1, 14)]
        ranked = rank_candidates(field, origin_confidence=0.85)
        assert [a.vessel_ref.mmsi for a in ranked] == list(range(1, 14))
        assert [a.rank for a in ranked] == list(range(1, 14))

    def test_default_call_without_origin_confidence_still_works(self) -> None:
        field = [candidate(1, origin=0.96), candidate(2, origin=0.4)]
        assert rank_candidates(field)[0].rank == 1
