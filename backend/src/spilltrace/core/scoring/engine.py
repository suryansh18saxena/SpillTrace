"""Aggregation and ranking (FR-015, FR-016, SCORE-007, SCORE-008).

The engine is a pure function of its inputs: no clock, no database, no randomness, no
network.  That is not tidiness for its own sake — an attribution that cannot be
reproduced from its recorded inputs is not evidence, and NFR-005/AC-07 require that
re-running the same case yields the same result.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from spilltrace.core.enums import DataProvenance
from spilltrace.core.provenance import combine_provenance
from spilltrace.core.scoring.discrimination import apply_cap, assess
from spilltrace.core.scoring.factors import (
    DEFAULT_DISTANCE_SCALE_KM,
    DEFAULT_DWELL_SATURATION_MINUTES,
    DEFAULT_TIME_TOLERANCE_HOURS,
    derive_ais_subscores,
    score_ais_reliability,
    score_heading_match,
    score_origin_proximity,
    score_speed_match,
    score_time_match,
    score_trajectory_match,
)
from spilltrace.core.scoring.inputs import (
    OriginContext,
    SpillContext,
    TrackContext,
    VesselContext,
)
from spilltrace.core.scoring.model import (
    DEFAULT_WEIGHTS,
    Attribution,
    FactorKey,
    FactorScore,
    ScoringWeights,
    VesselRef,
)

#: The PRD asks the MVP demo to show at least three ranked candidates (MVP-08).  It is
#: a demo target, not a guarantee about reality — see :func:`shortfall_note` and AD-29.
MINIMUM_DEMO_CANDIDATES: int = 3

#: Ranking comparisons are quantised to this many decimals before sorting.  Two
#: candidates whose scores differ only by float noise must fall to the documented
#: tie-break, not to whichever way the last bit happened to round.
RANKING_PRECISION: int = 9


def score_candidate(
    spill: SpillContext,
    origin: OriginContext,
    vessel: VesselContext,
    track: TrackContext,
    weights: ScoringWeights = DEFAULT_WEIGHTS,
    *,
    distance_scale_km: float = DEFAULT_DISTANCE_SCALE_KM,
    time_tolerance_hours: float = DEFAULT_TIME_TOLERANCE_HOURS,
    dwell_saturation_minutes: float = DEFAULT_DWELL_SATURATION_MINUTES,
) -> Attribution:
    """Score one candidate vessel across all six PRD factors.

    The weights are validated first: an attribution produced under weights that do not
    sum to 1.0 would carry a final score on a different scale from the one its own
    confidence band assumes, and it would be persisted looking perfectly normal.

    ``data_provenance`` is combined across every input, so a result that used any
    synthetic input can never be displayed as a real-world observation (CON-009).
    """
    weights.validate()

    subscores = derive_ais_subscores(track)
    track_statistics = {
        "position_count": track.observed_position_count,
        "rejected_count": track.rejected_count,
        "expected_position_count": track.expected_position_count,
        "gap_count": track.gap_count,
        "max_gap_minutes": track.max_gap_minutes,
        "total_gap_minutes": track.total_gap_minutes,
    }

    factors: list[FactorScore] = [
        score_origin_proximity(
            origin=origin,
            track=track,
            weight=weights.origin_proximity,
            distance_scale_km=distance_scale_km,
        ),
        score_time_match(
            origin=origin,
            track=track,
            weight=weights.time_match,
            tolerance_hours=time_tolerance_hours,
        ),
        score_trajectory_match(
            origin=origin,
            track=track,
            weight=weights.trajectory_match,
            dwell_saturation_minutes=dwell_saturation_minutes,
            distance_scale_km=distance_scale_km,
        ),
        score_heading_match(spill=spill, origin=origin, track=track, weight=weights.heading_match),
        score_speed_match(track=track, weight=weights.speed_match),
        score_ais_reliability(
            coverage=subscores.coverage,
            continuity=subscores.continuity,
            density=subscores.density,
            cleanliness=subscores.cleanliness,
            identity=subscores.identity,
            weight=weights.ais_reliability,
            track_statistics=track_statistics,
        ),
    ]

    provenance = combine_provenance(
        spill.data_provenance,
        origin.data_provenance,
        vessel.data_provenance,
        track.data_provenance,
    )
    return Attribution.build(
        vessel_ref=VesselRef(
            mmsi=vessel.mmsi, name=vessel.name, imo=vessel.imo, ship_type=vessel.ship_type
        ),
        factors=factors,
        weights=weights,
        data_provenance=DataProvenance(provenance),
    )


def _ranking_key(attribution: Attribution) -> tuple[float, float, float, int]:
    """Deterministic sort key: score, then the two strongest factors, then MMSI.

    Negated because the sort is ascending.  The tie-break chain is documented, total and
    stable:

    1. higher ``final_score``;
    2. higher ``origin_proximity`` — the heaviest factor, so on a tie it is the most
       informative discriminator;
    3. higher ``ais_reliability`` — prefer the candidate we can actually see, which is
       the honest direction: better data, not worse, breaks the tie;
    4. lower MMSI — an arbitrary but *stable* final step, so identical inputs always
       produce identical output rather than depending on dict or query ordering.

    MMSI is unique per vessel, so the chain is total: no two distinct candidates can
    compare equal, and the sort therefore does not depend on input order at all.
    """
    return (
        -round(attribution.final_score, RANKING_PRECISION),
        -round(attribution.factor_score(FactorKey.ORIGIN_PROXIMITY), RANKING_PRECISION),
        -round(attribution.factor_score(FactorKey.AIS_RELIABILITY), RANKING_PRECISION),
        attribution.vessel_ref.mmsi,
    )


def rank_candidates(
    attributions: Sequence[Attribution], *, origin_confidence: float | None = None
) -> list[Attribution]:
    """Rank candidates by final score, highest first, and stamp ``rank`` from 1.

    **The list is never padded.**  If two candidates were found, two are returned; if
    none were, the answer is an empty list.  Inventing a third to satisfy the MVP's
    "at least 3 candidates" line would be manufacturing evidence, which is the one thing
    this system must not do (AD-29, ambiguity A-10).  Use :func:`shortfall_note` to tell
    the analyst that the list is short and why.

    Returns new objects; the inputs are untouched.
    """
    ordered = sorted(attributions, key=_ranking_key)
    ranked = [attribution.with_rank(index) for index, attribution in enumerate(ordered, start=1)]

    # A region that cannot separate the candidates must not label them all HIGH.
    # Scores are untouched; only the at-a-glance summary is prevented from
    # over-claiming, and the reason travels with the result.
    check = assess(ranked, origin_confidence=origin_confidence)
    if check.cap is not None:
        ranked = [
            replace(
                attribution,
                confidence_label=apply_cap(attribution.confidence_label, check.cap),
                discrimination_note=check.reason,
            )
            for attribution in ranked
        ]
    return ranked


def shortfall_note(candidate_count: int) -> str | None:
    """An honest sentence when fewer than three candidates were found, else ``None``."""
    if candidate_count >= MINIMUM_DEMO_CANDIDATES:
        return None
    if candidate_count == 0:
        return (
            "No candidate vessels met the spatial and temporal correlation criteria for "
            "this origin region. AIS coverage is not complete, so this may mean no "
            "vessel was there or that no vessel there was observed."
        )
    return (
        f"Only {candidate_count} candidate vessel(s) met the correlation criteria. The "
        f"list is reported as found and has not been padded; AIS coverage is not "
        f"complete, so more vessels may have been present than were observed."
    )


__all__ = [
    "MINIMUM_DEMO_CANDIDATES",
    "RANKING_PRECISION",
    "rank_candidates",
    "score_candidate",
    "shortfall_note",
]
