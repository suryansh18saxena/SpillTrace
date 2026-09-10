"""Vessel attribution scoring — PRD Part J (SCORE-001…SCORE-008).

    Final Score = 0.35·OriginProximity + 0.20·TimeMatch + 0.15·TrajectoryMatch
                + 0.10·HeadingMatch   + 0.10·SpeedMatch + 0.10·AISReliability

Those weights are **prototype engineering defaults, not calibrated legal
probabilities** (CON-003).  A score ranks candidates for investigation; it does not
establish that any vessel did anything.

Layout: :mod:`~spilltrace.core.scoring.model` holds the weights, factor keys and the
result objects; :mod:`~spilltrace.core.scoring.inputs` holds the pure data the scorer
consumes; :mod:`~spilltrace.core.scoring.factors` holds one function per factor;
:mod:`~spilltrace.core.scoring.explain` writes the analyst-facing prose; and
:mod:`~spilltrace.core.scoring.engine` aggregates and ranks.  Nothing here performs
I/O or imports a framework.
"""

from __future__ import annotations

from spilltrace.core.scoring.discrimination import DiscriminationCheck, assess
from spilltrace.core.scoring.engine import (
    MINIMUM_DEMO_CANDIDATES,
    rank_candidates,
    score_candidate,
    shortfall_note,
)
from spilltrace.core.scoring.factors import (
    AIS_SUB_WEIGHTS,
    DEFAULT_DISTANCE_SCALE_KM,
    DEFAULT_DWELL_SATURATION_MINUTES,
    DEFAULT_TIME_TOLERANCE_HOURS,
    INSUFFICIENT_DATA_SCORE,
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
    AISSubScores,
    OriginContext,
    SpillContext,
    TrackContext,
    TrackSample,
    VesselContext,
)
from spilltrace.core.scoring.model import (
    DEFAULT_ATTRIBUTION_DISCLAIMER,
    DEFAULT_WEIGHTS,
    FACTOR_ORDER,
    SCORING_VERSION,
    Attribution,
    ConfidenceLabel,
    FactorKey,
    FactorScore,
    ScoringWeights,
    VesselRef,
    confidence_label,
)

__all__ = [
    "AIS_SUB_WEIGHTS",
    "DEFAULT_ATTRIBUTION_DISCLAIMER",
    "DEFAULT_DISTANCE_SCALE_KM",
    "DEFAULT_DWELL_SATURATION_MINUTES",
    "DEFAULT_TIME_TOLERANCE_HOURS",
    "DEFAULT_WEIGHTS",
    "FACTOR_ORDER",
    "INSUFFICIENT_DATA_SCORE",
    "MINIMUM_DEMO_CANDIDATES",
    "SCORING_VERSION",
    "AISSubScores",
    "Attribution",
    "ConfidenceLabel",
    "DiscriminationCheck",
    "FactorKey",
    "FactorScore",
    "OriginContext",
    "ScoringWeights",
    "SpillContext",
    "TrackContext",
    "TrackSample",
    "VesselContext",
    "VesselRef",
    "assess",
    "confidence_label",
    "derive_ais_subscores",
    "rank_candidates",
    "score_ais_reliability",
    "score_candidate",
    "score_heading_match",
    "score_origin_proximity",
    "score_speed_match",
    "score_time_match",
    "score_trajectory_match",
    "shortfall_note",
    "speed_plausibility",
]
