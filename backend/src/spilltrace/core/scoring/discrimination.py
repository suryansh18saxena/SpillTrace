"""Does the evidence actually distinguish these candidates from one another?

A reverse-drift run on a large, diffuse detection can produce an origin region that
contains a dozen vessels. Every one of them then scores ~0.96 on origin proximity, and
the ranking dutifully labels them all HIGH.

That output is arithmetically correct and editorially false. "Thirteen vessels are strong
candidates" is not a finding; it is the system reporting that it could not tell them
apart, in language that says the opposite. Naming thirteen vessels as strong candidates
is thirteen times the harm of naming one, and CON-001 exists precisely to stop this.

So before labels are attached, the ranking is checked for *discriminative power*: if the
dominant factor cannot separate the field, the labels are capped and the reason is stated
in the output. The underlying scores are never altered — an analyst still sees the real
numbers, and the report still shows the full breakdown. Only the summary label, the part
a reader takes at a glance, is prevented from over-claiming.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from spilltrace.core.scoring.model import ConfidenceLabel, FactorKey

#: Scores within this of each other are treated as indistinguishable. Chosen well above
#: float noise and below any difference an analyst could act on.
TIE_TOLERANCE = 0.02

#: More candidates than this sharing the top origin-proximity score means the region is
#: not localising anything. Three is the PRD's own "at least 3 candidates" figure: a
#: region that cannot get below it has not narrowed the field at all.
MAX_UNDISCRIMINATED_TOP = 3

#: Below this, the drift run did not concentrate its particles well enough for any
#: candidate derived from it to be called strong evidence.
MIN_ORIGIN_CONFIDENCE_FOR_HIGH = 0.60


@dataclass(frozen=True, slots=True)
class DiscriminationCheck:
    """The verdict, and the sentence explaining it to the reader."""

    cap: ConfidenceLabel | None
    reason: str | None
    tied_at_top: int
    origin_confidence: float | None

    @property
    def is_discriminating(self) -> bool:
        return self.cap is None


def _origin_scores(attributions: Sequence[object]) -> list[float]:
    scores: list[float] = []
    for attribution in attributions:
        for factor in getattr(attribution, "factors", ()):
            if factor.key is FactorKey.ORIGIN_PROXIMITY:
                scores.append(float(factor.score))
                break
    return scores


def assess(
    attributions: Sequence[object], *, origin_confidence: float | None = None
) -> DiscriminationCheck:
    """Decide whether these candidates are actually distinguishable.

    Two independent ways the evidence can fail to discriminate:

    1. **The region does not localise.** Many candidates share the top origin-proximity
       score, so being "in the origin region" says nothing about which of them matters.
    2. **The back-track did not converge.** A low ``origin_confidence`` means the
       particle cloud stayed diffuse, so the region itself is weak evidence regardless of
       how many vessels are in it.
    """
    scores = _origin_scores(attributions)
    tied = 0
    if scores:
        top = max(scores)
        tied = sum(1 for value in scores if top - value <= TIE_TOLERANCE)

    if tied > MAX_UNDISCRIMINATED_TOP:
        return DiscriminationCheck(
            cap=ConfidenceLabel.MODERATE,
            reason=(
                f"{tied} candidate vessels share effectively the same origin-proximity "
                "score, so the origin region does not distinguish between them. Evidence "
                "strength is capped at MODERATE for every candidate: the region is "
                "consistent with all of them, which is not the same as supporting any "
                "one of them. Narrowing the detection or the drift parameters would "
                "sharpen this."
            ),
            tied_at_top=tied,
            origin_confidence=origin_confidence,
        )

    if origin_confidence is not None and origin_confidence < MIN_ORIGIN_CONFIDENCE_FOR_HIGH:
        return DiscriminationCheck(
            cap=ConfidenceLabel.MODERATE,
            reason=(
                f"The reverse-drift run reported an origin confidence of "
                f"{origin_confidence:.2f}: the back-tracked particles stayed diffuse "
                "rather than converging on a compact area. Evidence strength is capped "
                "at MODERATE because the region every candidate is being measured "
                "against is itself weakly constrained."
            ),
            tied_at_top=tied,
            origin_confidence=origin_confidence,
        )

    return DiscriminationCheck(
        cap=None, reason=None, tied_at_top=tied, origin_confidence=origin_confidence
    )


def apply_cap(label: ConfidenceLabel, cap: ConfidenceLabel | None) -> ConfidenceLabel:
    """Lower ``label`` to ``cap`` when a cap applies.  Never raises a label."""
    if cap is None:
        return label
    order = {ConfidenceLabel.LOW: 0, ConfidenceLabel.MODERATE: 1, ConfidenceLabel.HIGH: 2}
    return label if order[label] <= order[cap] else cap


__all__ = [
    "MAX_UNDISCRIMINATED_TOP",
    "MIN_ORIGIN_CONFIDENCE_FOR_HIGH",
    "TIE_TOLERANCE",
    "DiscriminationCheck",
    "apply_cap",
    "assess",
]
