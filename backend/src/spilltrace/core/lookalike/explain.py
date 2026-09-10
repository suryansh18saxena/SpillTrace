"""Plain-language explanation of a verification verdict.

Written for an analyst who has to defend the conclusion, so it always states what was
checked, what supported the verdict, what argued against it, and what could not be
evaluated at all.
"""

from __future__ import annotations

from spilltrace.core.enums import VerificationStatus
from spilltrace.core.lookalike.rules import RuleResult

_HEADLINE = {
    VerificationStatus.VERIFIED: (
        "The detected feature is consistent with an oil-like surface film."
    ),
    VerificationStatus.UNCERTAIN: (
        "The evidence is mixed: the detected feature may be an oil-like film, but a "
        "natural look-alike cannot be ruled out."
    ),
    VerificationStatus.FALSE_POSITIVE: (
        "The detected feature is more consistent with a natural look-alike than with oil."
    ),
}


def build_explanation(
    status: VerificationStatus,
    evidence: float,
    coverage: float,
    results: list[RuleResult],
) -> str:
    supporting = [r for r in results if r.applicable and r.evidence > 0]
    against = [r for r in results if r.applicable and r.evidence < 0]
    skipped = [r for r in results if not r.applicable]
    vetoes = [r for r in against if r.veto]

    lines: list[str] = [_HEADLINE[status]]

    if vetoes:
        lines.append("Decisive: " + " ".join(r.message for r in vetoes))

    if supporting:
        lines.append(
            "Supporting evidence: "
            + " ".join(r.message for r in sorted(supporting, key=lambda r: -r.weight))
        )
    if [r for r in against if not r.veto]:
        lines.append(
            "Evidence against: "
            + " ".join(
                r.message
                for r in sorted((r for r in against if not r.veto), key=lambda r: -r.weight)
            )
        )
    if skipped:
        lines.append("Not evaluated: " + " ".join(f"{r.label} - {r.message}" for r in skipped))

    lines.append(
        f"Weighted evidence score {evidence:+.2f} on a -1 to +1 scale, from "
        f"{coverage:.0%} of the available checks."
    )
    lines.append(
        "Look-alike verification reduces false positives; it does not by itself "
        "establish that a discharge occurred, and biogenic films in particular remain "
        "difficult to separate from mineral oil in SAR imagery."
    )
    return " ".join(lines)


__all__ = ["build_explanation"]
