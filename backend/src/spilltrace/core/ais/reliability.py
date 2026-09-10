"""The AIS reliability factor (SCORE-006, resolving PRD ambiguity A-03).

The PRD names ``ais_reliability`` as one of six weighted evidence factors but never
defines it, so this module defines it: five sub-scores in [0, 1], combined with the
weights published in ``docs/AIS_PIPELINE.md`` §6.

Every sub-score answers the same question from a different angle — *how much of this
vessel did we actually see, and how much of what we saw can we trust?*  All five move
in the same direction, and that direction is the point.  A vessel with sparse AIS gets
a **lower** score, never a higher one.  The opposite arrangement — reading absence as
concealment, and concealment as involvement — is exactly the inference CON-002 forbids,
and it is an easy one to build by accident: a "went dark" bonus feels intuitive and is
unfalsifiable, because a vessel that transmitted nothing cannot produce the evidence
that would clear it.

Each sub-score carries a plain-language explanation, because a number an analyst cannot
interrogate is a number they will either over-trust or ignore.
"""

from __future__ import annotations

from dataclasses import dataclass

from spilltrace.core.ais.constants import (
    DARK_PERIOD_MINUTES,
    EXPECTED_REPORTS_PER_HOUR,
    IDENTITY_FIELDS,
    RELIABILITY_WEIGHT_CLEANLINESS,
    RELIABILITY_WEIGHT_CONTINUITY,
    RELIABILITY_WEIGHT_COVERAGE,
    RELIABILITY_WEIGHT_DENSITY,
    RELIABILITY_WEIGHT_IDENTITY,
    SCORE_DECIMALS,
    SUSPICIOUS_GAP_MINUTES,
)
from spilltrace.core.disclaimers import AIS_GAP_DISCLAIMER
from spilltrace.core.ports import AISMessage


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass(frozen=True, slots=True)
class SubScore:
    """One component of the reliability factor, with its reasoning attached."""

    name: str
    value: float
    weight: float
    explanation: str

    @property
    def contribution(self) -> float:
        """What this component adds to the total, for a per-row audit trail."""
        return round(self.value * self.weight, SCORE_DECIMALS)


@dataclass(frozen=True, slots=True)
class ReliabilityBreakdown:
    """The five sub-scores, their weighted total, and why each came out as it did.

    The breakdown is returned rather than a bare float so the evidence report can show
    *which* weakness lowered a vessel's reliability.  "0.41" tells an analyst nothing;
    "we saw 12% of the expected reports and the longest gap was 14 hours" tells them
    whether to go and find another data source.
    """

    coverage: SubScore
    continuity: SubScore
    density: SubScore
    cleanliness: SubScore
    identity: SubScore
    total: float

    @property
    def sub_scores(self) -> tuple[SubScore, ...]:
        """In weight order, which is also the order the specification lists them."""
        return (self.coverage, self.continuity, self.density, self.cleanliness, self.identity)

    def explanations(self) -> list[str]:
        return [f"{score.name}: {score.explanation}" for score in self.sub_scores]

    def as_dict(self) -> dict[str, float]:
        return {score.name: score.value for score in self.sub_scores} | {"total": self.total}


def identity_completeness(
    *,
    imo: int | None = None,
    name: str | None = None,
    callsign: str | None = None,
    ship_type: int | None = None,
    length_m: float | None = None,
    width_m: float | None = None,
) -> float:
    """Fraction of {IMO, name, callsign, type, dimensions} that is actually known.

    Dimensions count only when **both** length and width are present: half a hull is not
    an identification.  Blank and whitespace-only strings count as absent because AIS
    pads static text to a fixed width, so " " is what an unset name looks like on the
    wire (AD-21).

    This measures how confidently a track can be tied to a *vessel*, not to an MMSI.
    MMSIs are reassigned and trivially spoofed (AD-25), so a track with an IMO, a name
    and a callsign supports an identification that a bare MMSI does not.
    """
    present = 0
    if imo is not None:
        present += 1
    if name is not None and name.strip():
        present += 1
    if callsign is not None and callsign.strip():
        present += 1
    if ship_type is not None:
        present += 1
    if length_m is not None and width_m is not None:
        present += 1
    return present / len(IDENTITY_FIELDS)


def identity_completeness_of(message: AISMessage) -> float:
    """``identity_completeness`` for a static-data message."""
    return identity_completeness(
        imo=message.imo,
        name=message.name,
        callsign=message.callsign,
        ship_type=message.ship_type,
        length_m=message.length_m,
        width_m=message.width_m,
    )


def compute_ais_reliability(
    *,
    coverage_ratio: float,
    max_gap_minutes: float,
    position_count: int,
    window_hours: float,
    total_positions: int,
    rejected_positions: int,
    static_completeness: float,
) -> ReliabilityBreakdown:
    """Combine the five sub-scores into ``ais_reliability`` ∈ [0, 1].

    ``window_hours`` is the *case* window, not the observed track's duration: density
    must measure reports against the period we were looking, or a vessel seen for five
    minutes of a two-day window would score as densely observed.

    Raises ``ValueError`` on impossible inputs (negative counts, more rejections than
    positions).  Silently clamping those would turn a caller's bug into a plausible
    score, and a plausible wrong score is worse than a crash.
    """
    if position_count < 0 or total_positions < 0 or rejected_positions < 0:
        raise ValueError("Position counts cannot be negative.")
    if rejected_positions > total_positions:
        raise ValueError(
            f"rejected_positions ({rejected_positions}) exceeds total_positions "
            f"({total_positions})."
        )
    if window_hours < 0.0 or max_gap_minutes < 0.0:
        raise ValueError("window_hours and max_gap_minutes cannot be negative.")

    coverage_value = _clamp01(coverage_ratio)
    coverage = SubScore(
        name="coverage",
        value=coverage_value,
        weight=RELIABILITY_WEIGHT_COVERAGE,
        explanation=(
            f"We received {coverage_value:.0%} of the position reports a Class A "
            "transponder would have produced at the conservative rate of one every three "
            "minutes. A low figure means thin evidence, which may equally be a reception "
            "limitation on our side."
        ),
    )

    continuity_value = _clamp01(1.0 - min(1.0, max_gap_minutes / DARK_PERIOD_MINUTES))
    continuity_explanation = (
        f"The longest interval without a position was {max_gap_minutes / 60.0:.1f} h, "
        f"measured against the {DARK_PERIOD_MINUTES / 60.0:.0f} h point at which a gap "
        "materially limits what can be said about a vessel's movements."
    )
    if max_gap_minutes >= SUSPICIOUS_GAP_MINUTES:
        continuity_explanation = f"{continuity_explanation} {AIS_GAP_DISCLAIMER}"
    continuity = SubScore(
        name="continuity",
        value=continuity_value,
        weight=RELIABILITY_WEIGHT_CONTINUITY,
        explanation=continuity_explanation,
    )

    expected_for_window = max(1.0, window_hours * EXPECTED_REPORTS_PER_HOUR)
    density_value = _clamp01(position_count / expected_for_window)
    density = SubScore(
        name="density",
        value=density_value,
        weight=RELIABILITY_WEIGHT_DENSITY,
        explanation=(
            f"{position_count} usable positions across a {window_hours:.1f} h window, "
            f"against roughly {expected_for_window:.0f} expected. Density and coverage can "
            "disagree: a vessel seen intensely for one hour of a long window scores well "
            "on coverage and poorly here."
        ),
    )

    if total_positions == 0:
        cleanliness_value = 0.0
        cleanliness_explanation = (
            "No positions were received at all, so there is nothing whose quality could "
            "be assessed. Absence of a vessel from this dataset is not evidence of its "
            "absence from the area."
        )
    else:
        cleanliness_value = _clamp01(1.0 - rejected_positions / total_positions)
        cleanliness_explanation = (
            f"{total_positions - rejected_positions} of {total_positions} received "
            "positions survived validation. Rejections are usually decoder and reception "
            "faults rather than anything the vessel did."
        )
    cleanliness = SubScore(
        name="cleanliness",
        value=cleanliness_value,
        weight=RELIABILITY_WEIGHT_CLEANLINESS,
        explanation=cleanliness_explanation,
    )

    identity_value = _clamp01(static_completeness)
    identity = SubScore(
        name="identity",
        value=identity_value,
        weight=RELIABILITY_WEIGHT_IDENTITY,
        explanation=(
            f"{identity_value:.0%} of the identifying static fields "
            f"({', '.join(IDENTITY_FIELDS)}) were broadcast. MMSI alone is a radio "
            "identifier that is reassigned over time, so an IMO number materially "
            "strengthens an identification."
        ),
    )

    total = round(
        sum(
            score.value * score.weight
            for score in (coverage, continuity, density, cleanliness, identity)
        ),
        SCORE_DECIMALS,
    )
    return ReliabilityBreakdown(
        coverage=coverage,
        continuity=continuity,
        density=density,
        cleanliness=cleanliness,
        identity=identity,
        total=total,
    )


__all__ = [
    "ReliabilityBreakdown",
    "SubScore",
    "compute_ais_reliability",
    "identity_completeness",
    "identity_completeness_of",
]
