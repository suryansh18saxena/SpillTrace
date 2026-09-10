"""The verification engine.

Combines rule evidence into a three-class verdict with a confidence and a written
explanation.  Two design choices worth stating:

* **Vetoes are not out-voted.**  If the wind was below 2 m/s there were no Bragg waves
  to damp, so no amount of shape or contrast evidence can make the detection oil.  A
  purely additive score would let five weak positives override a physical impossibility.
* **Missing evidence lowers confidence, it does not lower the score.**  A rule that
  could not run is excluded from the weighted mean and reduces the coverage term, so an
  under-evidenced detection lands in UNCERTAIN rather than being pushed towards
  FALSE_POSITIVE by its own silence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spilltrace.core.enums import VerificationStatus
from spilltrace.core.lookalike.features import SlickFeatures
from spilltrace.core.lookalike.rules import RuleResult, RuleSet

#: Weighted evidence above this is VERIFIED, below the lower bound is FALSE_POSITIVE.
VERIFIED_THRESHOLD = 0.35
FALSE_POSITIVE_THRESHOLD = -0.25

#: Below this fraction of rule weight actually evaluated, the verdict is UNCERTAIN
#: regardless of which way the evidence points.
MIN_EVIDENCE_COVERAGE = 0.45


@dataclass(slots=True)
class VerificationOutcome:
    status: VerificationStatus
    confidence: float
    evidence_score: float
    coverage: float
    rules: list[RuleResult]
    explanation: str
    classifier_name: str | None = None
    classifier_score: float | None = None
    features: SlickFeatures | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "verification_confidence": round(self.confidence, 4),
            "evidence_score": round(self.evidence_score, 4),
            "evidence_coverage": round(self.coverage, 4),
            "rules": [r.to_dict() for r in self.rules],
            "explanation": self.explanation,
            "classifier_name": self.classifier_name,
            "classifier_score": self.classifier_score,
            "notes": self.notes,
        }


def verify_detection(
    features: SlickFeatures,
    *,
    ruleset: RuleSet | None = None,
    classifier: Any | None = None,
) -> VerificationOutcome:
    results = (ruleset or RuleSet()).evaluate(features)

    applicable = [r for r in results if r.applicable]
    total_weight = sum(r.weight for r in results)
    applied_weight = sum(r.weight for r in applicable)
    coverage = applied_weight / total_weight if total_weight else 0.0

    evidence = (
        sum(r.evidence * r.weight for r in applicable) / applied_weight if applied_weight else 0.0
    )

    notes: list[str] = []
    classifier_name: str | None = None
    classifier_score: float | None = None
    if classifier is not None:
        classifier_score = float(classifier.predict(features))
        classifier_name = getattr(classifier, "name", type(classifier).__name__)
        # The classifier contributes but never dominates: it is an optional adjunct to a
        # transparent rule set, not a replacement for one.
        evidence = 0.75 * evidence + 0.25 * (classifier_score * 2.0 - 1.0)
        notes.append(
            f"An optional classifier ({classifier_name}) contributed 25% of the evidence "
            f"score, with output {classifier_score:.3f}."
        )

    vetoes = [r for r in applicable if r.veto and r.evidence < 0]
    if vetoes:
        status = VerificationStatus.FALSE_POSITIVE
        confidence = min(0.95, 0.55 + 0.35 * min(1.0, abs(min(r.evidence for r in vetoes))))
        notes.append(
            "A physical precondition for SAR oil detection was not met, which overrides "
            "the remaining evidence."
        )
    elif coverage < MIN_EVIDENCE_COVERAGE:
        status = VerificationStatus.UNCERTAIN
        confidence = round(0.30 + 0.25 * coverage, 4)
        notes.append(
            f"Only {coverage:.0%} of the verification evidence could be evaluated, so the "
            "result is reported as uncertain rather than confirmed either way."
        )
    elif evidence >= VERIFIED_THRESHOLD:
        status = VerificationStatus.VERIFIED
        confidence = _confidence_from(evidence, coverage, VERIFIED_THRESHOLD)
    elif evidence <= FALSE_POSITIVE_THRESHOLD:
        status = VerificationStatus.FALSE_POSITIVE
        confidence = _confidence_from(-evidence, coverage, -FALSE_POSITIVE_THRESHOLD)
    else:
        status = VerificationStatus.UNCERTAIN
        confidence = round(0.35 + 0.3 * coverage, 4)

    from spilltrace.core.lookalike.explain import build_explanation

    return VerificationOutcome(
        status=status,
        confidence=round(min(0.98, max(0.05, confidence)), 4),
        evidence_score=evidence,
        coverage=coverage,
        rules=results,
        explanation=build_explanation(status, evidence, coverage, results),
        classifier_name=classifier_name,
        classifier_score=classifier_score,
        features=features,
        notes=notes,
    )


def _confidence_from(magnitude: float, coverage: float, threshold: float) -> float:
    """Confidence grows with how decisively the threshold was cleared, and with coverage.

    Capped below 1.0 on purpose: no rule engine over these features can be certain, and
    a displayed 100% would misrepresent that.
    """
    margin = min(1.0, max(0.0, (magnitude - threshold) / max(1e-6, 1.0 - threshold)))
    return round(0.5 + 0.35 * margin + 0.13 * coverage, 4)


__all__ = [
    "FALSE_POSITIVE_THRESHOLD",
    "MIN_EVIDENCE_COVERAGE",
    "VERIFIED_THRESHOLD",
    "VerificationOutcome",
    "verify_detection",
]
