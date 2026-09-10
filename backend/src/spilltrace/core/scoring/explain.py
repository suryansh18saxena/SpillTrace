"""Plain-language explanations for each scored factor (SCORE-007, MVP-09).

Two rules shape everything in this module.

**Show the numbers.**  An explanation that says "the vessel was close to the origin" is
not evidence; one that says "closest approach 1.4 km at 18:20Z, inside the
80th-percentile contour" can be checked, argued with, and thrown out by an analyst.
Every sentence here carries the concrete measurement it is derived from.

**Describe, never accuse.**  These strings are read by investigators and printed in the
evidence report, so they say what was measured and what it does *not* establish.
:func:`safe` re-checks every string against ``FORBIDDEN_PHRASES`` before it leaves the
module, so a careless edit fails loudly instead of shipping (CON-001, CON-003, AC-13).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from spilltrace.core.disclaimers import contains_forbidden_language
from spilltrace.core.errors import ValidationError
from spilltrace.core.scoring.inputs import as_utc
from spilltrace.core.scoring.model import FACTOR_LABELS, FactorKey


def safe(text: str) -> str:
    """Return ``text``, or raise if it contains language the product forbids.

    A guard, not a filter: it never rewrites, because silently editing an explanation
    would hide the mistake instead of fixing it.
    """
    found = contains_forbidden_language(text)
    if found:
        raise ValidationError(
            f"Generated explanation contains forbidden language: {', '.join(found)}.",
            field="explanation",
            phrases=found,
        )
    if not text.strip():
        raise ValidationError("Generated explanation is empty.", field="explanation")
    return text


# --------------------------------------------------------------------------- formatting
def fmt_time(moment: datetime | str | None) -> str:
    """UTC minute precision — the resolution an analyst actually reasons at.

    Accepts an ISO-8601 string as well as a datetime, because the evidence dicts hold
    timestamps as ISO strings so they survive a round trip through JSONB unchanged.
    """
    if moment is None:
        return "unknown time"
    if isinstance(moment, str):
        try:
            parsed = datetime.fromisoformat(moment)
        except ValueError:
            return moment
        return as_utc(parsed).strftime("%Y-%m-%dT%H:%MZ")
    return as_utc(moment).strftime("%Y-%m-%dT%H:%MZ")


def fmt_km(value: float | None) -> str:
    if value is None:
        return "unknown distance"
    if value < 10:
        return f"{value:.1f} km"
    return f"{value:,.0f} km"


def fmt_hours(value: float | None) -> str:
    if value is None:
        return "unknown duration"
    if value < 1.0:
        return f"{value * 60:.0f} min"
    return f"{value:.1f} h"


def fmt_pct(fraction: float | None) -> str:
    if fraction is None:
        return "unknown"
    return f"{fraction * 100:.0f}%"


def fmt_deg(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.0f}°"


def fmt_score(value: float | None) -> str:
    if value is None:
        return "not measurable"
    return f"{value:.2f}"


# --------------------------------------------------------------------------- factors
def explain_origin_proximity(evidence: dict[str, Any]) -> str:
    """How close the track came to the origin probability region, and when."""
    closest = evidence.get("closest_approach_km")
    when = fmt_time(evidence.get("closest_approach_time"))
    percentile = evidence.get("contour_percentile")
    scale = evidence.get("distance_scale_km")

    if percentile is not None:
        where = f"inside the {percentile:.0f}th-percentile contour"
    elif evidence.get("inside_origin_region"):
        where = (
            "inside the origin probability region, but no probability contours were "
            "supplied, so the score is held at the region-boundary value"
        )
    else:
        where = f"outside the region, decaying over a {scale:,.0f} km scale"

    return safe(
        f"Closest approach to the origin probability region was {fmt_km(closest)} at "
        f"{when}, {where}. The origin region is a drift-derived probability region, "
        f"not an exact discharge position."
    )


def explain_time_match(evidence: dict[str, Any]) -> str:
    """How much of the inferred discharge window the vessel's track overlaps."""
    overlap = evidence.get("overlap_hours", 0.0)
    tolerance = evidence.get("tolerance_hours", 0.0)
    shoulder = evidence.get("shoulder_hours", 0.0)

    head = (
        f"The track ran from {fmt_time(evidence.get('presence_start'))} to "
        f"{fmt_time(evidence.get('presence_end'))}; the inferred discharge window is "
        f"{fmt_time(evidence.get('window_start'))} to "
        f"{fmt_time(evidence.get('window_end'))}."
    )
    if overlap > 0:
        body = (
            f" They overlap by {fmt_hours(overlap)}, which is "
            f"{fmt_pct(evidence.get('overlap_fraction'))} of the shorter of the two "
            f"intervals."
        )
    elif shoulder > 0:
        body = (
            f" They do not overlap, but {fmt_hours(shoulder)} of the track falls within "
            f"the {fmt_hours(tolerance)} tolerance either side of the window and scores "
            f"at half credit."
        )
    else:
        separation = evidence.get("separation_hours")
        body = (
            f" They do not overlap; the track is {fmt_hours(separation)} away from the "
            f"window, beyond the {fmt_hours(tolerance)} tolerance."
        )
    return safe(head + body + " The window itself is inferred from reverse drift, not observed.")


def explain_trajectory_match(evidence: dict[str, Any]) -> str:
    """Whether the path entered, left or crossed the region, or only passed nearby."""
    relation = str(evidence.get("relation", "unknown"))
    dwell = evidence.get("dwell_minutes", 0.0)
    inside = evidence.get("positions_inside", 0)
    considered = evidence.get("positions_considered", 0)
    entries = evidence.get("entries", 0)
    exits = evidence.get("exits", 0)
    min_km = evidence.get("min_distance_km")

    phrases = {
        "crossed": "entered and then left the origin probability region",
        "entered": "entered the origin probability region and was still inside at the "
        "end of the track",
        "left": "started inside the origin probability region and left it",
        "inside_throughout": "stayed inside the origin probability region for the whole track",
        "passed_nearby": "did not enter the origin probability region, passing nearby",
        "distant": "did not approach the origin probability region",
    }
    what = phrases.get(relation, "could not be classified against the origin region")

    if inside:
        detail = (
            f" It spent {fmt_hours(dwell / 60.0)} inside ({inside} of {considered} "
            f"positions; {entries} entry/entries, {exits} exit(s))."
        )
    else:
        detail = (
            f" Minimum distance to the region was {fmt_km(min_km)} across {considered} positions."
        )
    return safe(
        f"The track {what}.{detail} Passing through an origin region is a reason to "
        f"look closer, not a finding in itself."
    )


def explain_heading_match(evidence: dict[str, Any]) -> str:
    """Course near the closest approach against the origin bearing and slick axis."""
    course = evidence.get("course_deg")
    source = {
        "cog": "course over ground",
        "heading": "reported heading",
        "derived": "course derived from consecutive positions",
    }.get(str(evidence.get("course_source")), "course")

    parts = [
        f"Near the closest approach at {fmt_time(evidence.get('closest_approach_time'))} "
        f"the {source} was {fmt_deg(course)}."
    ]
    if evidence.get("bearing_to_origin_deg") is not None:
        parts.append(
            f"The bearing from the vessel to the origin region was "
            f"{fmt_deg(evidence.get('bearing_to_origin_deg'))} — a difference of "
            f"{fmt_deg(evidence.get('bearing_difference_deg'))}."
        )
    if evidence.get("slick_axis_deg") is not None:
        parts.append(
            f"The slick's principal axis lies at "
            f"{fmt_deg(evidence.get('slick_axis_deg'))} — a difference of "
            f"{fmt_deg(evidence.get('axis_difference_deg'))}."
        )
    parts.append(
        "Heading agreement is weak evidence: a discharge can occur on any heading, so "
        f"this factor is deliberately confined to "
        f"{fmt_score(evidence.get('floor'))}-{fmt_score(evidence.get('ceiling'))} and "
        "can neither carry a case nor clear a vessel on its own."
    )
    return safe(" ".join(parts))


def explain_speed_match(evidence: dict[str, Any]) -> str:
    """Observed speed against the documented plausibility curve."""
    low = evidence.get("plateau_min_knots")
    high = evidence.get("plateau_max_knots")
    steadiness = evidence.get("steadiness")

    head = (
        f"Median speed over ground was "
        f"{fmt_score(evidence.get('median_sog_knots'))} kn across "
        f"{evidence.get('sample_count', 0)} positions "
        f"(range {fmt_score(evidence.get('min_sog_knots'))}-"
        f"{fmt_score(evidence.get('max_sog_knots'))} kn)."
    )
    curve = (
        f" A steady {low:.0f}-{high:.0f} kn transit is the most plausible speed for a "
        f"discharge that leaves an elongated slick, giving a plausibility of "
        f"{fmt_score(evidence.get('plausibility'))}."
    )
    if steadiness is None:
        steady = (
            " Speed steadiness could not be assessed from a single position, so only "
            "the plausibility curve was used."
        )
    else:
        steady = (
            f" Speed varied by {fmt_score(evidence.get('sog_spread_knots'))} kn "
            f"(steadiness {fmt_score(steadiness)})."
        )
    return safe(
        head
        + curve
        + steady
        + " This is a documented plausibility curve, not a calibrated model, and it says"
        " nothing about intent."
    )


def explain_ais_reliability(evidence: dict[str, Any]) -> str:
    """How well the vessel could be seen — never how suspicious it is."""
    weights = evidence.get("sub_weights", {})
    parts = []
    for name in ("coverage", "continuity", "density", "cleanliness", "identity"):
        parts.append(f"{name} {fmt_score(evidence.get(name))} (x{weights.get(name, 0):.2f})")
    body = ", ".join(parts)

    gap = evidence.get("max_gap_minutes")
    gap_text = ""
    if gap:
        gap_text = (
            f" The longest reporting gap was {fmt_hours(float(gap) / 60.0)} across "
            f"{evidence.get('gap_count', 0)} gap(s)."
        )
    unmeasured = evidence.get("unmeasured") or []
    missing_text = ""
    if unmeasured:
        missing_text = (
            f" Not measurable from the supplied track: {', '.join(sorted(unmeasured))} — "
            f"scored conservatively low rather than assumed good."
        )
    return safe(
        f"AIS reliability combines {body} from {evidence.get('position_count', 0)} "
        f"retained and {evidence.get('rejected_count', 0)} rejected positions."
        + gap_text
        + missing_text
        + " A gap in AIS reporting lowers confidence in this track; it is not an "
        "indication of misconduct, and it can never raise a vessel's score."
    )


def explain_insufficient(key: FactorKey, reason: str) -> str:
    """Explanation used when a factor could not be measured at all."""
    label = FACTOR_LABELS[key].lower()
    return safe(
        f"{FACTOR_LABELS[key]}: {reason} This factor could not be measured, so it is "
        f"held at a low placeholder value to record the absence of a measurement — not "
        f"a measurement of absence. Read the {label} score here as 'unknown', and treat "
        f"the final score as correspondingly less informative."
    )


#: Dispatch table used by the factor functions.
EXPLAINERS = {
    FactorKey.ORIGIN_PROXIMITY: explain_origin_proximity,
    FactorKey.TIME_MATCH: explain_time_match,
    FactorKey.TRAJECTORY_MATCH: explain_trajectory_match,
    FactorKey.HEADING_MATCH: explain_heading_match,
    FactorKey.SPEED_MATCH: explain_speed_match,
    FactorKey.AIS_RELIABILITY: explain_ais_reliability,
}


def explain_factor(key: FactorKey, evidence: dict[str, Any]) -> str:
    """Explain one factor from its evidence dict."""
    return EXPLAINERS[key](evidence)


__all__ = [
    "EXPLAINERS",
    "explain_ais_reliability",
    "explain_factor",
    "explain_heading_match",
    "explain_insufficient",
    "explain_origin_proximity",
    "explain_speed_match",
    "explain_time_match",
    "explain_trajectory_match",
    "fmt_deg",
    "fmt_hours",
    "fmt_km",
    "fmt_pct",
    "fmt_score",
    "fmt_time",
    "safe",
]
