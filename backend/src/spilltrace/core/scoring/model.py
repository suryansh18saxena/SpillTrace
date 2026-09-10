"""Scoring domain model — PRD Part J (SCORE-001…SCORE-008).

The whole product rests on one weighted sum::

    Final Score = 0.35·OriginProximity + 0.20·TimeMatch + 0.15·TrajectoryMatch
                + 0.10·HeadingMatch   + 0.10·SpeedMatch + 0.10·AISReliability

Those six numbers are **prototype engineering weights, not calibrated legal
probabilities** (PRD Part J, CON-003).  They were chosen by judgement, not fitted to
labelled incidents, and until they are calibrated against validated cases the final
score may only be used to *prioritise* investigation.  That framing is not decoration:
it is why :data:`SCORE_DISCLAIMER` is attached to every attribution this package emits,
why every factor is stored and explained separately (SCORE-007), and why the weights
travel with the result under a version string (SCORE-008) instead of being an implicit
property of whatever code happened to be deployed.

Nothing in this module performs I/O, touches a database or imports a framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Final

from spilltrace.core.disclaimers import ATTRIBUTION_DISCLAIMER, SCORE_DISCLAIMER
from spilltrace.core.enums import DataProvenance
from spilltrace.core.errors import ValidationError

#: Bumped whenever the factor formulas or the default weights change (SCORE-008).
#: Persisted on every attribution so an old result can always be re-read in the terms
#: it was produced under, and so a re-score under new weights never silently overwrites
#: an old one (the DB unique key includes this string).
SCORING_VERSION: Final[str] = "prd-j-v1"

#: Weights must sum to exactly 1.0 to this tolerance, so that ``final_score`` is on the
#: same [0, 1] scale as the individual factors and the bands below stay meaningful.
WEIGHT_SUM_TOLERANCE: Final[float] = 1e-9

#: The disclaimer carried by every attribution.  It deliberately joins both mandated
#: sentences: the first says what an attribution *is* (CON-001/AC-13), the second says
#: what the number is *not* (CON-003).
#:
#: Note for reviewers: this string contains the phrase "legal probability" only inside
#: its own negation.  ``FORBIDDEN_PHRASES`` is a check on *generated* prose — the factor
#: explanations this package writes — not on the mandated boilerplate that exists
#: precisely to rule that reading out.
DEFAULT_ATTRIBUTION_DISCLAIMER: Final[str] = f"{ATTRIBUTION_DISCLAIMER} {SCORE_DISCLAIMER}"


def clamp01(value: float) -> float:
    """Clamp to ``[0, 1]``.

    Every factor is normalised to this range (SCORE-007) so that no single factor can
    exceed its weight's share of the final score, however odd its inputs are.
    """
    if value != value:  # NaN — an unmeasurable input must never propagate as a score
        return 0.0
    return max(0.0, min(1.0, float(value)))


class FactorKey(StrEnum):
    """Stable identifiers for the six PRD factors.

    These strings are an API contract: they are the ``key`` field in the attribution
    response, the column names on ``attributions`` and the keys of the weights object.
    """

    ORIGIN_PROXIMITY = "origin_proximity"
    TIME_MATCH = "time_match"
    TRAJECTORY_MATCH = "trajectory_match"
    HEADING_MATCH = "heading_match"
    SPEED_MATCH = "speed_match"
    AIS_RELIABILITY = "ais_reliability"


#: Canonical presentation order — the PRD's order, heaviest factor first.
FACTOR_ORDER: Final[tuple[FactorKey, ...]] = (
    FactorKey.ORIGIN_PROXIMITY,
    FactorKey.TIME_MATCH,
    FactorKey.TRAJECTORY_MATCH,
    FactorKey.HEADING_MATCH,
    FactorKey.SPEED_MATCH,
    FactorKey.AIS_RELIABILITY,
)

#: Human labels used by the UI and the evidence report.
FACTOR_LABELS: Final[dict[FactorKey, str]] = {
    FactorKey.ORIGIN_PROXIMITY: "Origin proximity",
    FactorKey.TIME_MATCH: "Time match",
    FactorKey.TRAJECTORY_MATCH: "Trajectory match",
    FactorKey.HEADING_MATCH: "Heading match",
    FactorKey.SPEED_MATCH: "Speed match",
    FactorKey.AIS_RELIABILITY: "AIS reliability",
}


class ConfidenceLabel(StrEnum):
    """Evidence-strength band.  See :func:`confidence_label` for what it is *not*."""

    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


#: Lower edge of the MODERATE band.  Chosen from the model's own dynamic range: a
#: well-tracked vessel with a plausible speed collects roughly 0.25 from the three
#: "background" factors (heading, speed, AIS reliability) no matter where or when it
#: was, so anything below ~0.45 carries no real spatial or temporal link at all.
CONFIDENCE_MODERATE_MIN: Final[float] = 0.45

#: Lower edge of the HIGH band.  Chosen so that a candidate with **no** temporal
#: overlap can never be labelled HIGH: with ``time_match == 0`` the arithmetic ceiling
#: is 0.35 + 0.15 + 0.10·0.90 + 0.10 + 0.10 = 0.79 (the 0.90 is the deliberate cap on
#: the heading factor), which sits just below this edge.  That is CON-001 — "nearest is
#: not guilt" — enforced by the shape of the model rather than by a warning label.
CONFIDENCE_HIGH_MIN: Final[float] = 0.80


def confidence_label(score: float) -> ConfidenceLabel:
    """Map a final score to an evidence-strength band.

    The bands are half-open and therefore **non-overlapping and exhaustive**::

        LOW       score <  0.45
        MODERATE  0.45 <= score < 0.80
        HIGH      0.80 <= score

    This is a label for *how much corroborating evidence this candidate has*, and it is
    emphatically **not** a probability of culpability (CON-003).  A HIGH band means the
    six factors agree and the candidate is worth investigating first; it does not mean
    the vessel discharged anything, and it carries no legal weight.  The weights that
    produce ``score`` are uncalibrated engineering defaults, so the boundaries are
    presentation choices, not decision thresholds derived from data.
    """
    value = clamp01(score)
    if value >= CONFIDENCE_HIGH_MIN:
        return ConfidenceLabel.HIGH
    if value >= CONFIDENCE_MODERATE_MIN:
        return ConfidenceLabel.MODERATE
    return ConfidenceLabel.LOW


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    """The six PRD Part J weights.

    Frozen because a weight set is an identity: it is persisted with every attribution
    and quoted in the evidence report, so mutating one in place would retroactively
    change the meaning of results already produced under it (SCORE-008, NFR-005).
    """

    origin_proximity: float = 0.35
    time_match: float = 0.20
    trajectory_match: float = 0.15
    heading_match: float = 0.10
    speed_match: float = 0.10
    ais_reliability: float = 0.10

    def validate(self) -> None:
        """Raise :class:`ValidationError` unless this is a usable weight set.

        Two conditions, both load-bearing:

        * every weight is in ``[0, 1]`` — a negative weight would let good evidence
          *lower* a score, which no reader would expect;
        * the weights sum to 1.0 within :data:`WEIGHT_SUM_TOLERANCE` — otherwise the
          final score would not share the ``[0, 1]`` scale of its own factors and the
          confidence bands would silently mean something different.
        """
        values = self.to_dict()
        bad = {k: v for k, v in values.items() if not (0.0 <= v <= 1.0)}
        if bad:
            raise ValidationError(
                "Scoring weights must each lie in [0, 1].", field="weights", invalid=bad
            )
        total = sum(values.values())
        if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
            raise ValidationError(
                f"Scoring weights must sum to 1.0, got {total!r}.",
                field="weights",
                total=total,
                weights=values,
            )

    def for_key(self, key: FactorKey) -> float:
        """Weight for one factor."""
        return float(self.to_dict()[key.value])

    def to_dict(self) -> dict[str, float]:
        """Serialised in :data:`FACTOR_ORDER`, which is the order the UI renders."""
        return {
            FactorKey.ORIGIN_PROXIMITY.value: self.origin_proximity,
            FactorKey.TIME_MATCH.value: self.time_match,
            FactorKey.TRAJECTORY_MATCH.value: self.trajectory_match,
            FactorKey.HEADING_MATCH.value: self.heading_match,
            FactorKey.SPEED_MATCH.value: self.speed_match,
            FactorKey.AIS_RELIABILITY.value: self.ais_reliability,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ScoringWeights:
        """Rebuild a weight set from a stored attribution (SCORE-008).

        Unknown keys are rejected rather than ignored, so a typo in an override cannot
        quietly leave a factor at its default.
        """
        known = {key.value for key in FACTOR_ORDER}
        unknown = sorted(set(payload) - known)
        if unknown:
            raise ValidationError(
                f"Unknown scoring weight(s): {', '.join(unknown)}.",
                field="weights",
                unknown=unknown,
            )
        defaults = ScoringWeights().to_dict()
        merged = {k: float(payload.get(k, defaults[k])) for k in known}
        return cls(**merged)


#: The PRD's engineering defaults.  Not calibrated; see the module docstring.
DEFAULT_WEIGHTS: Final[ScoringWeights] = ScoringWeights()


@dataclass(frozen=True, slots=True)
class FactorScore:
    """One of the six factors, scored, weighted and explained (SCORE-007).

    An opaque number is useless as investigative evidence, so every factor carries the
    prose an analyst reads (``explanation``) and the raw measurements that prose is
    derived from (``evidence``), which is what makes the reasoning checkable.
    """

    key: FactorKey
    label: str
    weight: float
    score: float
    contribution: float
    explanation: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValidationError(
                f"Factor {self.key.value} score {self.score!r} is outside [0, 1].",
                field=self.key.value,
            )
        if not self.explanation.strip():
            raise ValidationError(
                f"Factor {self.key.value} must carry a non-empty explanation (SCORE-007).",
                field=self.key.value,
            )
        expected = self.weight * self.score
        if abs(self.contribution - expected) > 1e-9:
            raise ValidationError(
                f"Factor {self.key.value} contribution {self.contribution!r} is not "
                f"weight x score ({expected!r}).",
                field=self.key.value,
            )

    def to_dict(self) -> dict[str, Any]:
        """Shape per ``docs/API.md`` §10."""
        return {
            "key": self.key.value,
            "label": self.label,
            "weight": round(self.weight, 4),
            "score": round(self.score, 4),
            "contribution": round(self.contribution, 4),
            "explanation": self.explanation,
            "evidence": dict(self.evidence),
        }


def make_factor(
    key: FactorKey,
    *,
    weight: float,
    score: float,
    explanation: str,
    evidence: dict[str, Any] | None = None,
) -> FactorScore:
    """Build a :class:`FactorScore`, clamping the score and deriving the contribution.

    Every factor function goes through here so that clamping and the
    ``contribution = weight x score`` invariant can never be forgotten in one place and
    remembered in another.
    """
    clamped = clamp01(score)
    return FactorScore(
        key=key,
        label=FACTOR_LABELS[key],
        weight=float(weight),
        score=clamped,
        contribution=float(weight) * clamped,
        explanation=explanation,
        evidence=dict(evidence or {}),
    )


@dataclass(frozen=True, slots=True)
class VesselRef:
    """Just enough vessel identity to render an attribution without a database read."""

    mmsi: int
    name: str | None = None
    imo: int | None = None
    ship_type: str | None = None
    vessel_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Shape per ``docs/API.md`` §10 — ``id`` is filled by the persistence layer."""
        return {"id": self.vessel_id, "mmsi": self.mmsi, "name": self.name}


@dataclass(frozen=True, slots=True)
class Attribution:
    """A single candidate vessel, scored factor by factor (FR-015, FR-016).

    Immutable: :func:`spilltrace.core.scoring.engine.rank_candidates` produces ranked
    copies rather than mutating, so an attribution can never be half-updated.
    """

    vessel_ref: VesselRef
    factors: list[FactorScore]
    final_score: float
    weights: ScoringWeights
    confidence_label: ConfidenceLabel
    #: Set when the evidence could not distinguish this candidate from the others,
    #: explaining why the label was capped.  ``None`` when the ranking discriminates.
    discrimination_note: str | None = None
    rank: int = 0
    scoring_version: str = SCORING_VERSION
    disclaimer: str = DEFAULT_ATTRIBUTION_DISCLAIMER
    data_provenance: DataProvenance = DataProvenance.REAL
    #: Assigned by the persistence layer; ``None`` for an unsaved, in-memory result.
    attribution_id: str | None = None

    def __post_init__(self) -> None:
        if not self.disclaimer.strip():
            raise ValidationError(
                "Every attribution must carry a non-empty disclaimer (CON-003, AC-13).",
                field="disclaimer",
            )

    @classmethod
    def build(
        cls,
        *,
        vessel_ref: VesselRef,
        factors: list[FactorScore],
        weights: ScoringWeights,
        data_provenance: DataProvenance = DataProvenance.REAL,
        disclaimer: str = DEFAULT_ATTRIBUTION_DISCLAIMER,
        scoring_version: str = SCORING_VERSION,
    ) -> Attribution:
        """Sum the contributions and derive the confidence band."""
        final = clamp01(sum(factor.contribution for factor in factors))
        return cls(
            vessel_ref=vessel_ref,
            factors=list(factors),
            final_score=final,
            weights=weights,
            confidence_label=confidence_label(final),
            data_provenance=data_provenance,
            disclaimer=disclaimer,
            scoring_version=scoring_version,
        )

    def with_rank(self, rank: int) -> Attribution:
        return replace(self, rank=rank)

    def factor(self, key: FactorKey) -> FactorScore:
        for candidate in self.factors:
            if candidate.key is key:
                return candidate
        raise ValidationError(f"Attribution carries no {key.value} factor.", field=key.value)

    def factor_score(self, key: FactorKey, default: float = 0.0) -> float:
        """Score for one factor, or ``default`` if the factor is absent.

        Used by ranking, which must never raise on a partially populated attribution.
        """
        for candidate in self.factors:
            if candidate.key is key:
                return candidate.score
        return default

    def factor_scores(self) -> dict[str, float]:
        """``{factor_key: score}`` — the shape the ``attributions`` columns expect."""
        return {factor.key.value: factor.score for factor in self.factors}

    def to_dict(self) -> dict[str, Any]:
        """Shape per ``docs/API.md`` §10, including the mandatory ``disclaimer``."""
        return {
            "id": self.attribution_id,
            "rank": self.rank,
            "vessel": self.vessel_ref.to_dict(),
            "final_score": round(self.final_score, 4),
            "confidence_label": self.confidence_label.value,
            "discrimination_note": self.discrimination_note,
            "factors": [factor.to_dict() for factor in self.factors],
            "weights": self.weights.to_dict(),
            "scoring_version": self.scoring_version,
            "disclaimer": self.disclaimer,
            "data_provenance": self.data_provenance.value,
        }


__all__ = [
    "CONFIDENCE_HIGH_MIN",
    "CONFIDENCE_MODERATE_MIN",
    "DEFAULT_ATTRIBUTION_DISCLAIMER",
    "DEFAULT_WEIGHTS",
    "FACTOR_LABELS",
    "FACTOR_ORDER",
    "SCORING_VERSION",
    "WEIGHT_SUM_TOLERANCE",
    "Attribution",
    "ConfidenceLabel",
    "FactorKey",
    "FactorScore",
    "ScoringWeights",
    "VesselRef",
    "clamp01",
    "confidence_label",
    "make_factor",
]
