"""Reporting gaps — described, never accused (AD-24, CON-002, P17-005).

A gap is an interval in which we received nothing.  That is a statement about *our
reception*, not about a vessel's conduct.  Satellite revisit intervals, terrestrial
receiver range, message collisions in busy waters, antenna faults and ordinary
equipment failures all produce gaps, and they are far more common than concealment.

So this module measures gaps and explains them.  It does not name them.  There is no
``is_suspicious_behaviour`` here and there never will be: even a gap that meets every
published dark-period criterion is not evidence of wrongdoing.  Its only effect on
scoring is through ``ais_reliability``, which it **lowers** — a vessel we saw less of
scores lower, never higher, because a system that rewarded absence of evidence would be
making exactly the inference CON-002 forbids.

Three thresholds, deliberately named apart, because conflating them is how a system
ends up implying wrongdoing from orbital mechanics.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from typing import Protocol, runtime_checkable

from spilltrace.core.ais.constants import (
    DARK_PERIOD_MIN_DISTANCE_FROM_SHORE_NM,
    DARK_PERIOD_MINUTES,
    EXPECTED_REPORT_INTERVAL_MINUTES,
    SEGMENT_GAP_MINUTES,
    SUSPICIOUS_GAP_MINUTES,
)
from spilltrace.core.disclaimers import AIS_GAP_DISCLAIMER
from spilltrace.core.enums import AISQualityFlag


@runtime_checkable
class PositionLike(Protocol):
    """The three fields a gap needs.

    A protocol rather than a concrete type so that raw ``AISMessage`` objects and
    ``CleanedPosition`` objects both work: gap analysis is equally valid before and
    after cleaning, and forcing a conversion would tempt callers to skip one.
    """

    @property
    def timestamp(self) -> datetime: ...

    @property
    def longitude(self) -> float: ...

    @property
    def latitude(self) -> float: ...


class GapClass(StrEnum):
    """How long a gap is, in the vocabulary of AD-24.

    These are duration bands, not judgements.  ``SUSPICIOUS`` is the band's published
    name (``SUSPICIOUS_GAP`` in the specification) and means *worth an analyst's time*
    — it is never scored, and nothing downstream may treat it as an accusation.
    """

    NORMAL = "NORMAL"
    SEGMENT = "SEGMENT"
    SUSPICIOUS = "SUSPICIOUS"
    EXTENDED = "EXTENDED"


@dataclass(frozen=True, slots=True)
class Gap:
    """An interval with no received positions, bounded by the fixes on either side.

    ``note`` travels with the gap wherever it goes.  A duration alone invites the
    reader to supply their own explanation, and the explanations people supply
    unprompted are the ones CON-002 exists to prevent.
    """

    start: datetime
    end: datetime
    duration_minutes: float
    start_lon: float
    start_lat: float
    end_lon: float
    end_lat: float
    classification: GapClass
    note: str
    distance_from_shore_nm: float | None = None


@dataclass(frozen=True, slots=True)
class GapStatistics:
    """The three gap numbers stored with every trajectory."""

    gap_count: int
    max_gap_minutes: float
    total_gap_minutes: float


def classify_gap(gap: Gap, *, distance_from_shore_nm: float | None) -> GapClass:
    """Band a gap by duration, and by distance from shore for the longest band.

    ``EXTENDED`` requires **both** ≥ 12 h and > 50 nm from shore (Global Fishing Watch's
    published criteria).  Below 12 h a gap is not informative at all — one
    sun-synchronous AIS satellite takes roughly that long to re-cover a location, so
    shorter gaps are mostly orbital mechanics.  Nearer than 50 nm the difference between
    terrestrial and satellite reception dominates.

    When the distance from shore is **unknown** the gap is never classified
    ``EXTENDED``.  Half a criterion is not a criterion, and the honest answer to "was
    this vessel far offshore?" when we do not know is not "probably".
    """
    duration = gap.duration_minutes
    if (
        duration >= DARK_PERIOD_MINUTES
        and distance_from_shore_nm is not None
        and distance_from_shore_nm > DARK_PERIOD_MIN_DISTANCE_FROM_SHORE_NM
    ):
        return GapClass.EXTENDED
    if duration >= SUSPICIOUS_GAP_MINUTES:
        return GapClass.SUSPICIOUS
    if duration >= SEGMENT_GAP_MINUTES:
        return GapClass.SEGMENT
    return GapClass.NORMAL


def describe_gap(
    classification: GapClass,
    duration_minutes: float,
    *,
    distance_from_shore_nm: float | None = None,
) -> str:
    """A plain-language note explaining what the gap does and does not mean.

    Every note ends with ``AIS_GAP_DISCLAIMER`` so the caveat cannot be separated from
    the number by a UI, an export or a copy-paste into someone else's report.
    """
    if duration_minutes >= 60.0:
        length = f"{duration_minutes / 60.0:.1f} h"
    else:
        length = f"{duration_minutes:.0f} min"

    if classification is GapClass.EXTENDED:
        where = (
            f" beginning {distance_from_shore_nm:.0f} nm from shore"
            if distance_from_shore_nm is not None
            else ""
        )
        body = (
            f"No positions were received for {length}{where}, which meets the published "
            "12 h / 50 nm criteria for an extended reporting gap. It is recorded because "
            "it limits what can be said about this vessel's movements, and it lowers the "
            "AIS reliability factor — reducing the vessel's score rather than raising it."
        )
    elif classification is GapClass.SUSPICIOUS:
        body = (
            f"No positions were received for {length}. This is long enough to be worth an "
            "analyst's attention, but it is below the 12 h threshold at which a gap "
            "becomes informative at all, and it is not scored."
        )
    elif classification is GapClass.SEGMENT:
        body = (
            f"No positions were received for {length}. The trajectory is split here so "
            "that no line is drawn across an interval we did not observe."
        )
    else:
        body = (
            f"Reporting paused for {length}, longer than the "
            f"{EXPECTED_REPORT_INTERVAL_MINUTES:.0f}-minute Class A floor used for "
            "coverage but well within routine reception variability."
        )
    return f"{body} {AIS_GAP_DISCLAIMER}"


def detect_gaps(
    positions: Sequence[PositionLike],
    *,
    minimum_gap_minutes: float = EXPECTED_REPORT_INTERVAL_MINUTES,
) -> list[Gap]:
    """Find every interval longer than ``minimum_gap_minutes`` between consecutive fixes.

    The default floor is the slowest Class A reporting rate (3 minutes), which is the
    same rate ``coverage_ratio`` expects — so a gap here is exactly "less data than the
    coverage model assumed", and the two statistics can never contradict each other.

    Pass only positions you consider usable: this function has no opinion on validity,
    so feeding it rejected fixes would report gaps in a track that was never there.
    Distance from shore is unknown at detection time, so no gap returned here is
    classified ``EXTENDED``; use :func:`with_shore_distance` once it is known.
    """
    if len(positions) < 2:
        return []

    ordered = sorted(positions, key=lambda position: position.timestamp)
    gaps: list[Gap] = []
    for earlier, later in pairwise(ordered):
        duration_minutes = (later.timestamp - earlier.timestamp).total_seconds() / 60.0
        if duration_minutes <= minimum_gap_minutes:
            continue
        provisional = Gap(
            start=earlier.timestamp,
            end=later.timestamp,
            duration_minutes=duration_minutes,
            start_lon=earlier.longitude,
            start_lat=earlier.latitude,
            end_lon=later.longitude,
            end_lat=later.latitude,
            classification=GapClass.NORMAL,
            note="",
        )
        classification = classify_gap(provisional, distance_from_shore_nm=None)
        gaps.append(
            replace(
                provisional,
                classification=classification,
                note=describe_gap(classification, duration_minutes),
            )
        )
    return gaps


def with_shore_distance(gap: Gap, *, distance_from_shore_nm: float | None) -> Gap:
    """Re-band a gap now that the distance from shore at its start is known.

    Returns a new ``Gap``; the original is untouched, so the un-enriched value and the
    enriched one can both be shown, and nobody has to trust that a mutation happened.
    """
    classification = classify_gap(gap, distance_from_shore_nm=distance_from_shore_nm)
    return replace(
        gap,
        classification=classification,
        distance_from_shore_nm=distance_from_shore_nm,
        note=describe_gap(
            classification,
            gap.duration_minutes,
            distance_from_shore_nm=distance_from_shore_nm,
        ),
    )


def gap_quality_flag(classification: GapClass) -> AISQualityFlag | None:
    """The data-quality flag a gap of this band contributes, if any.

    Both flags describe the *record*, not the vessel: ``REPORTING_GAP`` says our view of
    the track has a hole in it, and ``EXTENDED_REPORTING_GAP`` says the hole is large
    enough to materially limit what may be concluded.
    """
    if classification is GapClass.EXTENDED:
        return AISQualityFlag.EXTENDED_REPORTING_GAP
    if classification is GapClass.SUSPICIOUS:
        return AISQualityFlag.REPORTING_GAP
    return None


def summarise_gaps(gaps: Sequence[Gap]) -> GapStatistics:
    """Count, longest and total gap minutes — the trio stored with a trajectory."""
    if not gaps:
        return GapStatistics(gap_count=0, max_gap_minutes=0.0, total_gap_minutes=0.0)
    durations = [gap.duration_minutes for gap in gaps]
    return GapStatistics(
        gap_count=len(gaps),
        max_gap_minutes=max(durations),
        total_gap_minutes=sum(durations),
    )


__all__ = [
    "Gap",
    "GapClass",
    "GapStatistics",
    "PositionLike",
    "classify_gap",
    "describe_gap",
    "detect_gaps",
    "gap_quality_flag",
    "summarise_gaps",
    "with_shore_distance",
]
