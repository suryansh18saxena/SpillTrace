"""The six PRD Part J factors (SCORE-001…SCORE-006).

One function per factor.  Each one:

* documents its formula and *why* the formula has that shape;
* is monotonic in the obvious direction (the one exception, the speed plausibility
  curve, says so in its own docstring and is monotonic on each side of its plateau);
* is clamped to ``[0, 1]`` by :func:`~spilltrace.core.scoring.model.make_factor`;
* degrades to a low-but-non-zero placeholder with an explicit "insufficient data"
  explanation when an input is missing, rather than crashing or scoring a hard 0.

That last rule matters more than it looks.  A 0.0 is a *measurement*: "this vessel was
demonstrably not there during the window".  A missing input is not a measurement at all,
and recording it as 0.0 would let absent data masquerade as exculpatory or, aggregated
over several factors, as incriminating.  :data:`INSUFFICIENT_DATA_SCORE` is deliberately
distinguishable from both 0 and any real score, and the explanation always says which
input was missing.

All geodesy comes from :mod:`spilltrace.core.geometry` — no distance is ever computed in
degrees.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from spilltrace.core.errors import InvalidGeometryError
from spilltrace.core.geometry import (
    angular_difference_deg,
    geodesic_distance_m,
    initial_bearing_deg,
    parse_geojson_geometry,
    point_to_geometry_distance_km,
)
from spilltrace.core.scoring.explain import (
    explain_ais_reliability,
    explain_heading_match,
    explain_insufficient,
    explain_origin_proximity,
    explain_speed_match,
    explain_time_match,
    explain_trajectory_match,
)
from spilltrace.core.scoring.inputs import (
    AISSubScores,
    OriginContext,
    SpillContext,
    TrackContext,
    TrackSample,
    as_utc,
)
from spilltrace.core.scoring.model import DEFAULT_WEIGHTS, FactorKey, FactorScore, make_factor

# --------------------------------------------------------------------------- constants

#: Placeholder score for a factor that could not be measured.  Low, because an
#: unmeasured factor is not evidence; non-zero, because zero would be a claim.
INSUFFICIENT_DATA_SCORE: float = 0.10

#: e-folding distance for the proximity decay.  25 km is roughly the distance a slick
#: drifts in 6-12 h under typical Arabian Sea forcing, so a vessel further away than a
#: few multiples of it is unlikely to be connected to this origin region.
DEFAULT_DISTANCE_SCALE_KM: float = 25.0

#: Score at the origin-region boundary, and the ceiling of the outside-the-region decay.
#: Inside the region the score is lifted above this by the probability contour reached.
REGION_BOUNDARY_SCORE: float = 0.60
#: Span from the boundary score to 1.0, allocated across the probability contours.
CONTOUR_SPAN: float = 1.0 - REGION_BOUNDARY_SCORE

#: Temporal tolerance either side of the inferred discharge window, matching the
#: correlation stage default (``docs/AIS_PIPELINE.md`` §7).
DEFAULT_TIME_TOLERANCE_HOURS: float = 2.0
#: Credit given to track time that falls in the tolerance shoulder rather than the
#: window proper.  Half, because the window edges are themselves inferred.
SHOULDER_CREDIT: float = 0.5
#: Floor on the overlap denominator, so a very short track or a near-instantaneous
#: window cannot divide by ~0 and manufacture a perfect score.
MIN_INTERVAL_HOURS: float = 0.25

#: Dwell inside the origin region at which the trajectory factor saturates.  An hour is
#: long enough to distinguish a deliberate transit through the region from a track that
#: happens to clip its corner.
DEFAULT_DWELL_SATURATION_MINUTES: float = 60.0
#: Base scores by how the track relates to the origin region.
TRAJECTORY_BASE_SCORES: dict[str, float] = {
    "crossed": 0.85,
    "entered": 0.70,
    "left": 0.70,
    "inside_throughout": 0.75,
}
#: Ceiling for a track that never entered the region, decayed by distance.
NEARBY_CEILING: float = 0.40

#: The heading factor is confined to this band.  See :func:`score_heading_match`.
HEADING_FLOOR: float = 0.25
HEADING_CEILING: float = 0.90
#: Share of the heading factor given to the vessel→origin bearing rather than to the
#: slick's principal axis.  The bearing is the more direct comparison; the axis is
#: corroboration and cannot dominate.
HEADING_BEARING_SHARE: float = 0.60

#: Plateau of maximum speed plausibility, in knots.
SPEED_PLATEAU_MIN_KNOTS: float = 4.0
SPEED_PLATEAU_MAX_KNOTS: float = 12.0
#: Plausibility of a stopped vessel and of a fast one.  Neither is zero: a discharge is
#: physically possible at any speed, so the curve expresses relative plausibility only.
SPEED_STOPPED_PLAUSIBILITY: float = 0.55
SPEED_FAST_PLAUSIBILITY: float = 0.30
#: Speed at which the fast-end decay bottoms out.
SPEED_FAST_KNOTS: float = 20.0
#: Speed spread (population standard deviation) at which steadiness reaches zero.
STEADINESS_SCALE_KNOTS: float = 6.0
#: Share of the speed factor given to the plausibility curve rather than to steadiness.
SPEED_PLAUSIBILITY_SHARE: float = 0.75

#: SCORE-006 sub-weights (``docs/AIS_PIPELINE.md`` §6, ambiguity A-03).
AIS_SUB_WEIGHTS: dict[str, float] = {
    "coverage": 0.30,
    "continuity": 0.25,
    "density": 0.20,
    "cleanliness": 0.15,
    "identity": 0.10,
}
#: The dark-period threshold in minutes; continuity reaches zero here (AD-24).
DARK_PERIOD_MINUTES: float = 720.0


# --------------------------------------------------------------------------- helpers
def _geometry(payload: dict[str, Any] | None) -> BaseGeometry | None:
    """Parse GeoJSON, returning ``None`` instead of raising.

    A malformed origin region must degrade this vessel's score to "not measurable", not
    abort the scoring of an entire case.
    """
    if not payload:
        return None
    try:
        geometry = parse_geojson_geometry(payload)
    except InvalidGeometryError:
        return None
    return None if geometry.is_empty else geometry


def _ordered(track: TrackContext) -> list[TrackSample]:
    """Samples oldest-first, in UTC.  Sorted defensively so caller order is irrelevant."""
    return sorted(track.samples, key=lambda sample: as_utc(sample.timestamp))


def _sorted_contours(origin: OriginContext) -> list[tuple[float, BaseGeometry]]:
    """Probability contours, highest probability first, malformed ones dropped."""
    parsed: list[tuple[float, BaseGeometry]] = []
    for probability, payload in origin.contours:
        geometry = _geometry(payload)
        if geometry is not None:
            parsed.append((float(probability), geometry))
    parsed.sort(key=lambda item: item[0], reverse=True)
    return parsed


def _origin_region(origin: OriginContext) -> BaseGeometry | None:
    """The region to measure against.

    Falls back to the lowest-probability contour when no explicit region was supplied,
    since that contour *is* the outer envelope of the drift result.
    """
    region = _geometry(origin.region_geojson)
    if region is not None:
        return region
    contours = _sorted_contours(origin)
    return contours[-1][1] if contours else None


def _closest_approach(
    samples: list[TrackSample], region: BaseGeometry
) -> tuple[int, float, list[float]]:
    """``(index, distance_km, all_distances)`` of the nearest position to ``region``.

    Ties resolve to the earliest position, which keeps the reported closest-approach
    time deterministic for a vessel that sits inside the region for many samples.
    """
    distances = [point_to_geometry_distance_km(Point(s.lon, s.lat), region) for s in samples]
    best = min(range(len(distances)), key=lambda i: (distances[i], i))
    return best, distances[best], distances


def _insufficient(key: FactorKey, weight: float, reason: str, **evidence: Any) -> FactorScore:
    """A factor that could not be measured."""
    return make_factor(
        key,
        weight=weight,
        score=INSUFFICIENT_DATA_SCORE,
        explanation=explain_insufficient(key, reason),
        evidence={"insufficient_data": True, "reason": reason, **evidence},
    )


def _hours_between(start: datetime, end: datetime) -> float:
    return (as_utc(end) - as_utc(start)).total_seconds() / 3600.0


def _overlap_hours(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> float:
    """Length of the intersection of two closed intervals, in hours (0 if disjoint)."""
    start = max(as_utc(a_start), as_utc(b_start))
    end = min(as_utc(a_end), as_utc(b_end))
    return max(0.0, (end - start).total_seconds() / 3600.0)


# --------------------------------------------------------------------------- SCORE-001
def score_origin_proximity(
    *,
    origin: OriginContext,
    track: TrackContext,
    weight: float = DEFAULT_WEIGHTS.origin_proximity,
    distance_scale_km: float = DEFAULT_DISTANCE_SCALE_KM,
) -> FactorScore:
    """SCORE-001 — how close the track came to the high-probability origin area.

    Formula, in two continuous regimes that meet at the region boundary::

        inside, contour probability p reached   →  0.60 + 0.40·p
        outside, minimum geodesic distance d    →  0.60·exp(-d / scale)

    * Reaching the innermost contour (p → 1) scores ~1.0; reaching only an outer
      contour scores proportionally less, because a low-probability contour is a weaker
      statement about where the discharge happened.
    * Being inside the region with **no** contours supplied scores exactly 0.60 — the
      boundary value.  This is deliberately conservative: without contours we know the
      vessel was in the region but nothing about how deep, and inventing a probability
      would be fabricating drift-model output the drift model never produced (CON-008).
    * Outside, the score decays exponentially with an e-folding length of
      ``distance_scale_km``: 0.60 at the boundary, 0.22 at one scale, ~0 at ten.
      Exponential rather than linear because "20 km versus 25 km" barely changes an
      investigator's judgement, while "0.5 km versus 5 km" changes it a lot.

    Monotonic: non-increasing in ``d``, non-decreasing in ``p``.
    """
    samples = _ordered(track)
    if not samples:
        return _insufficient(
            FactorKey.ORIGIN_PROXIMITY,
            weight,
            "no AIS positions were supplied for this vessel.",
            distance_scale_km=distance_scale_km,
        )

    region = _origin_region(origin)
    if region is None:
        return _insufficient(
            FactorKey.ORIGIN_PROXIMITY,
            weight,
            "the reverse-drift stage produced no origin probability region to measure against.",
            distance_scale_km=distance_scale_km,
        )

    index, closest_km, _ = _closest_approach(samples, region)
    inside = closest_km <= 0.0

    contour_probability: float | None = None
    for probability, geometry in _sorted_contours(origin):
        if any(geometry.covers(Point(s.lon, s.lat)) for s in samples):
            contour_probability = probability
            break

    if contour_probability is not None:
        score = REGION_BOUNDARY_SCORE + CONTOUR_SPAN * max(0.0, min(1.0, contour_probability))
    elif inside:
        score = REGION_BOUNDARY_SCORE
    else:
        score = REGION_BOUNDARY_SCORE * math.exp(-closest_km / max(distance_scale_km, 1e-9))

    evidence: dict[str, Any] = {
        "closest_approach_km": round(closest_km, 3),
        "closest_approach_time": as_utc(samples[index].timestamp).isoformat(),
        "inside_origin_region": inside,
        "contour_probability": contour_probability,
        "contour_percentile": (
            None if contour_probability is None else round(contour_probability * 100)
        ),
        "distance_scale_km": distance_scale_km,
        "positions_considered": len(samples),
        "origin_confidence": origin.origin_confidence,
    }
    return make_factor(
        FactorKey.ORIGIN_PROXIMITY,
        weight=weight,
        score=score,
        explanation=explain_origin_proximity(evidence),
        evidence=evidence,
    )


# --------------------------------------------------------------------------- SCORE-002
def score_time_match(
    *,
    origin: OriginContext,
    track: TrackContext,
    weight: float = DEFAULT_WEIGHTS.time_match,
    tolerance_hours: float = DEFAULT_TIME_TOLERANCE_HOURS,
) -> FactorScore:
    """SCORE-002 — was the vessel present during the inferred discharge window?

    Formula::

        inner   = |presence ∩ [w0, w1]|                      hours
        outer   = |presence ∩ [w0-tol, w1+tol]| - inner      hours
        denom   = max(min(|window|, |presence|), 0.25 h)
        score   = clamp01((inner + 0.5·outer) / denom)

    * The denominator is the **shorter** of the two intervals, so a 10-minute track
      lying wholly inside a 6-hour window scores 1.0 rather than 0.03.  Being present
      for part of the window is the evidence; being present for *all* of it is not
      required, and penalising a short track would penalise sparse AIS coverage rather
      than the vessel's behaviour.
    * The shoulder gives half credit for time within ``tolerance_hours`` of the window.
      The window is inferred from reverse drift (ambiguity A-02), so its edges are soft;
      a hard cut-off would turn a modelling artefact into an alibi.
    * A vessel demonstrably outside the window and its shoulder scores a true 0.0.  That
      is a measurement, and it is what stops "nearest" from becoming "guilty" (CON-001).

    Monotonic: non-decreasing in the overlap.
    """
    samples = _ordered(track)
    if not samples:
        return _insufficient(
            FactorKey.TIME_MATCH,
            weight,
            "no AIS positions were supplied for this vessel.",
            tolerance_hours=tolerance_hours,
        )
    if origin.window_start is None or origin.window_end is None:
        return _insufficient(
            FactorKey.TIME_MATCH,
            weight,
            "the reverse-drift stage inferred no discharge time window.",
            tolerance_hours=tolerance_hours,
        )

    window_start, window_end = as_utc(origin.window_start), as_utc(origin.window_end)
    if window_end < window_start:
        window_start, window_end = window_end, window_start
    presence_start = as_utc(samples[0].timestamp)
    presence_end = as_utc(samples[-1].timestamp)

    tolerance = max(0.0, tolerance_hours)
    shoulder = timedelta(hours=tolerance)
    inner = _overlap_hours(presence_start, presence_end, window_start, window_end)
    tolerant = _overlap_hours(
        presence_start, presence_end, window_start - shoulder, window_end + shoulder
    )
    outer = max(0.0, tolerant - inner)

    window_hours = _hours_between(window_start, window_end)
    presence_hours = _hours_between(presence_start, presence_end)
    denominator = max(min(window_hours, presence_hours), MIN_INTERVAL_HOURS)
    score = (inner + SHOULDER_CREDIT * outer) / denominator

    if inner > 0 or outer > 0:
        separation: float | None = 0.0
    elif presence_end < window_start:
        separation = _hours_between(presence_end, window_start)
    else:
        separation = _hours_between(window_end, presence_start)

    evidence: dict[str, Any] = {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "window_hours": round(window_hours, 3),
        "presence_start": presence_start.isoformat(),
        "presence_end": presence_end.isoformat(),
        "presence_hours": round(presence_hours, 3),
        "overlap_hours": round(inner, 3),
        "shoulder_hours": round(outer, 3),
        "overlap_fraction": round(min(1.0, inner / denominator), 4),
        "tolerance_hours": tolerance,
        "separation_hours": None if separation is None else round(separation, 3),
        "positions_considered": len(samples),
    }
    return make_factor(
        FactorKey.TIME_MATCH,
        weight=weight,
        score=score,
        explanation=explain_time_match(evidence),
        evidence=evidence,
    )


# --------------------------------------------------------------------------- SCORE-003
def score_trajectory_match(
    *,
    origin: OriginContext,
    track: TrackContext,
    weight: float = DEFAULT_WEIGHTS.trajectory_match,
    dwell_saturation_minutes: float = DEFAULT_DWELL_SATURATION_MINUTES,
    distance_scale_km: float = DEFAULT_DISTANCE_SCALE_KM,
) -> FactorScore:
    """SCORE-003 — is the *path* consistent with entering and leaving the origin?

    This is what separates a vessel that transited the origin region from one that
    merely happened to be in the neighbourhood — the distinction the proximity factor
    alone cannot make, because a single close position and a two-hour transit through
    the middle of the region produce the same closest approach.

    Formula::

        relation = crossed | entered | left | inside_throughout | passed_nearby | distant
        base     = 0.85 | 0.70 | 0.70 | 0.75          (relations that entered)
                 = 0.40·exp(-d / scale)               (relations that did not)
        dwell    = min(1, dwell_minutes / saturation)
        score    = base + (1 - base)·dwell            (entered relations only)

    * ``crossed`` scores highest because an entry *and* an exit is the pattern a
      discharge-during-transit leaves; ``entered``/``left`` see only half of it;
      ``inside_throughout`` is strong spatial evidence but says nothing about a
      transit, so it sits between the two.
    * Dwell is integrated along the track as a linear midpoint approximation: each
      consecutive pair contributes its duration times the fraction of its two endpoints
      inside the region.
    * A track that never entered is capped at 0.40 and decays with distance, so
      "passed 3 km away" can never out-score "went through the middle".

    The caller is expected to supply the case-window track (``docs/AIS_PIPELINE.md`` §7).
    This factor deliberately does not re-check timing — that is SCORE-002's job, and
    double-counting time here would silently reweight the PRD model.

    Monotonic: non-decreasing in dwell, non-increasing in distance for tracks that never
    entered the region.
    """
    samples = _ordered(track)
    if not samples:
        return _insufficient(
            FactorKey.TRAJECTORY_MATCH,
            weight,
            "no AIS positions were supplied for this vessel.",
        )
    region = _origin_region(origin)
    if region is None:
        return _insufficient(
            FactorKey.TRAJECTORY_MATCH,
            weight,
            "the reverse-drift stage produced no origin probability region to measure against.",
        )

    _, min_km, distances = _closest_approach(samples, region)
    inside_flags = [distance <= 0.0 for distance in distances]
    inside_count = sum(inside_flags)

    entries = sum(1 for a, b in pairwise(inside_flags) if (not a) and b)
    exits = sum(1 for a, b in pairwise(inside_flags) if a and not b)

    # Dwell is integrated as a linear midpoint approximation: each consecutive pair
    # contributes its duration weighted by the fraction of its endpoints inside.
    dwell_minutes = 0.0
    for (sample_a, inside_a), (sample_b, inside_b) in pairwise(
        list(zip(samples, inside_flags, strict=True))
    ):
        minutes = _hours_between(sample_a.timestamp, sample_b.timestamp) * 60.0
        dwell_minutes += minutes * ((int(inside_a) + int(inside_b)) / 2.0)

    if inside_count == 0:
        relation = "passed_nearby" if min_km <= distance_scale_km else "distant"
        score = NEARBY_CEILING * math.exp(-min_km / max(distance_scale_km, 1e-9))
    else:
        if all(inside_flags):
            relation = "inside_throughout"
        elif entries and exits:
            relation = "crossed"
        elif entries:
            relation = "entered"
        else:
            relation = "left"
        base = TRAJECTORY_BASE_SCORES[relation]
        dwell_fraction = min(1.0, dwell_minutes / max(dwell_saturation_minutes, 1e-9))
        score = base + (1.0 - base) * dwell_fraction

    evidence: dict[str, Any] = {
        "relation": relation,
        "dwell_minutes": round(dwell_minutes, 2),
        "dwell_saturation_minutes": dwell_saturation_minutes,
        "positions_inside": inside_count,
        "positions_considered": len(samples),
        "entries": entries,
        "exits": exits,
        "min_distance_km": round(min_km, 3),
        "distance_scale_km": distance_scale_km,
    }
    return make_factor(
        FactorKey.TRAJECTORY_MATCH,
        weight=weight,
        score=score,
        explanation=explain_trajectory_match(evidence),
        evidence=evidence,
    )


# --------------------------------------------------------------------------- SCORE-004
def _principal_axis_deg(geometry: BaseGeometry | None) -> float | None:
    """Bearing of the long axis of a slick, in ``[0, 180)``.

    Taken from the minimum rotated rectangle: for the elongated slicks a discharge
    during transit produces, its long side is a good proxy for the direction the vessel
    was moving when the oil was laid down.  Returns ``None`` for geometries too
    degenerate to have an axis.
    """
    if geometry is None or geometry.is_empty:
        return None
    try:
        rectangle = geometry.minimum_rotated_rectangle
        coords = list(rectangle.exterior.coords)
    except (AttributeError, ValueError):
        return None
    if len(coords) < 3:
        return None

    longest: tuple[float, tuple[float, float], tuple[float, float]] | None = None
    for start, end in pairwise(coords):
        length = geodesic_distance_m(start[0], start[1], end[0], end[1])
        if longest is None or length > longest[0]:
            longest = (length, (start[0], start[1]), (end[0], end[1]))
    if longest is None or longest[0] <= 0.0:
        return None
    bearing = initial_bearing_deg(longest[1][0], longest[1][1], longest[2][0], longest[2][1])
    return bearing % 180.0


def score_heading_match(
    *,
    spill: SpillContext,
    origin: OriginContext,
    track: TrackContext,
    weight: float = DEFAULT_WEIGHTS.heading_match,
) -> FactorScore:
    """SCORE-004 — is the vessel's course compatible with the origin and the slick?

    **This is weak evidence and the implementation is shaped to keep it weak.**  A
    discharge can be made on any heading; a vessel steaming directly away from the
    origin region can have discharged a minute earlier.  The factor therefore reports
    *compatibility*, never inconsistency-as-exoneration, and is compressed into
    ``[0.25, 0.90]`` rather than ``[0, 1]``:

    * the floor of 0.25 means an "unhelpful" heading cannot be read as clearing a
      vessel, and
    * the ceiling of 0.90 means a perfectly aligned heading cannot substitute for the
      spatial and temporal evidence.  It is also what makes ``CONFIDENCE_HIGH_MIN``
      unreachable without a temporal match — see
      :func:`~spilltrace.core.scoring.model.confidence_label`.

    Formula::

        bearing_alignment = 1 - Δ(course, bearing to origin) / 180
        axis_alignment    = 1 - Δ(course, slick axis, mod 180) / 90
        raw               = 0.60·bearing_alignment + 0.40·axis_alignment
        score             = 0.25 + 0.65·raw

    The axis comparison is modulo 180° because a slick's principal axis is a line, not a
    direction: a vessel laying oil along it could have been travelling either way.

    Monotonic: non-increasing in each angular difference.
    """
    samples = _ordered(track)
    if not samples:
        return _insufficient(
            FactorKey.HEADING_MATCH, weight, "no AIS positions were supplied for this vessel."
        )

    region = _origin_region(origin)
    if region is not None:
        index, _, _ = _closest_approach(samples, region)
        reference = region.centroid
        reference_lon, reference_lat = float(reference.x), float(reference.y)
        reference_name = "origin region"
    else:
        reference_lon, reference_lat = spill.centroid_lon, spill.centroid_lat
        distances = [
            geodesic_distance_m(s.lon, s.lat, reference_lon, reference_lat) for s in samples
        ]
        index = min(range(len(distances)), key=lambda i: (distances[i], i))
        reference_name = "slick centroid"

    sample = samples[index]
    course, course_source = _course_at(samples, index)
    if course is None:
        return _insufficient(
            FactorKey.HEADING_MATCH,
            weight,
            "neither course over ground nor heading was reported, and the track is too "
            "short to derive a course from consecutive positions.",
            closest_approach_time=as_utc(sample.timestamp).isoformat(),
        )

    separation_m = geodesic_distance_m(sample.lon, sample.lat, reference_lon, reference_lat)
    bearing: float | None = None
    bearing_difference: float | None = None
    if separation_m > 1.0:
        bearing = initial_bearing_deg(sample.lon, sample.lat, reference_lon, reference_lat)
        bearing_difference = angular_difference_deg(course, bearing)

    axis = spill.principal_axis_deg
    if axis is None:
        axis = _principal_axis_deg(_geometry(spill.geometry_geojson))
    axis_difference: float | None = None
    if axis is not None:
        axis_difference = min(
            angular_difference_deg(course, axis), angular_difference_deg(course, axis + 180.0)
        )

    terms: list[tuple[float, float]] = []
    if bearing_difference is not None:
        terms.append((HEADING_BEARING_SHARE, 1.0 - bearing_difference / 180.0))
    if axis_difference is not None:
        terms.append((1.0 - HEADING_BEARING_SHARE, 1.0 - axis_difference / 90.0))
    if not terms:
        return _insufficient(
            FactorKey.HEADING_MATCH,
            weight,
            "the vessel sat on the reference position, so no bearing could be computed, "
            "and the slick geometry has no usable principal axis.",
            course_deg=round(course, 1),
        )

    total_share = sum(share for share, _ in terms)
    raw = sum(share * value for share, value in terms) / total_share
    score = HEADING_FLOOR + (HEADING_CEILING - HEADING_FLOOR) * max(0.0, min(1.0, raw))

    evidence: dict[str, Any] = {
        "course_deg": round(course, 1),
        "course_source": course_source,
        "reference": reference_name,
        "bearing_to_origin_deg": None if bearing is None else round(bearing, 1),
        "bearing_difference_deg": (
            None if bearing_difference is None else round(bearing_difference, 1)
        ),
        "slick_axis_deg": None if axis is None else round(axis, 1),
        "axis_difference_deg": None if axis_difference is None else round(axis_difference, 1),
        "closest_approach_time": as_utc(sample.timestamp).isoformat(),
        "floor": HEADING_FLOOR,
        "ceiling": HEADING_CEILING,
        "weak_evidence": True,
    }
    return make_factor(
        FactorKey.HEADING_MATCH,
        weight=weight,
        score=score,
        explanation=explain_heading_match(evidence),
        evidence=evidence,
    )


def _course_at(samples: list[TrackSample], index: int) -> tuple[float | None, str]:
    """Best available course at ``index``: reported COG, then heading, then derived."""
    sample = samples[index]
    if sample.cog_deg is not None:
        return sample.cog_deg % 360.0, "cog"
    if sample.heading_deg is not None:
        return sample.heading_deg % 360.0, "heading"
    if index > 0:
        previous = samples[index - 1]
        if (previous.lon, previous.lat) != (sample.lon, sample.lat):
            return initial_bearing_deg(previous.lon, previous.lat, sample.lon, sample.lat), (
                "derived"
            )
    if index + 1 < len(samples):
        following = samples[index + 1]
        if (following.lon, following.lat) != (sample.lon, sample.lat):
            return initial_bearing_deg(sample.lon, sample.lat, following.lon, following.lat), (
                "derived"
            )
    return None, "unavailable"


# --------------------------------------------------------------------------- SCORE-005
def speed_plausibility(sog_knots: float) -> float:
    """Plausibility of ``sog_knots`` for a discharge event, in ``[0, 1]``.

    A piecewise-linear curve, and an engineering judgement rather than a fitted model::

        0 kn                → 0.55   stopped: a discharge would pool, not streak
        0 → 4 kn            → rises to 1.00
        4 → 12 kn           → 1.00   the plateau: normal laden transit speed, the
                                     regime that produces the long thin slicks SAR
                                     detects
        12 → 20 kn          → falls to 0.30
        ≥ 20 kn             → 0.30   high-speed running: still possible, just less
                                     consistent with a slick of this shape

    Nothing here is a claim about intent, and no speed scores zero: the curve ranks
    consistency with the *observed slick*, and every speed remains physically possible.

    Not globally monotonic by design — it is a plausibility band with a plateau — but
    monotonic increasing below the plateau and decreasing above it.
    """
    speed = max(0.0, float(sog_knots))
    if speed <= 0.0:
        return SPEED_STOPPED_PLAUSIBILITY
    if speed < SPEED_PLATEAU_MIN_KNOTS:
        rise = (1.0 - SPEED_STOPPED_PLAUSIBILITY) * (speed / SPEED_PLATEAU_MIN_KNOTS)
        return SPEED_STOPPED_PLAUSIBILITY + rise
    if speed <= SPEED_PLATEAU_MAX_KNOTS:
        return 1.0
    if speed >= SPEED_FAST_KNOTS:
        return SPEED_FAST_PLAUSIBILITY
    span = SPEED_FAST_KNOTS - SPEED_PLATEAU_MAX_KNOTS
    fall = (1.0 - SPEED_FAST_PLAUSIBILITY) * ((speed - SPEED_PLATEAU_MAX_KNOTS) / span)
    return 1.0 - fall


def score_speed_match(
    *,
    track: TrackContext,
    weight: float = DEFAULT_WEIGHTS.speed_match,
) -> FactorScore:
    """SCORE-005 — is the observed speed plausible for a discharge event?

    Formula::

        plausibility = speed_plausibility(median SOG)
        steadiness   = 1 - min(1, stdev(SOG) / 6 kn)
        score        = 0.75·plausibility + 0.25·steadiness

    The median is used rather than the mean so one bad SOG report cannot move the
    result.  Steadiness is included because a slick laid during a steady transit and a
    vessel manoeuvring are different pictures — but it is only a quarter of the factor,
    and with a single position it is dropped entirely rather than assumed perfect, which
    would reward a sparse track.

    This is a plausibility curve, **not** an inference about intent, and it cannot
    distinguish a discharge from ordinary steaming.

    Monotonic in steadiness; see :func:`speed_plausibility` for the speed curve's shape.
    """
    speeds = [s.sog_knots for s in _ordered(track) if s.sog_knots is not None]
    if not speeds:
        return _insufficient(
            FactorKey.SPEED_MATCH,
            weight,
            "no speed-over-ground values were reported on this track.",
        )

    median = statistics.median(speeds)
    plausibility = speed_plausibility(median)
    steadiness: float | None = None
    spread = 0.0
    score = plausibility
    if len(speeds) >= 2:
        spread = statistics.pstdev(speeds)
        measured_steadiness = 1.0 - min(1.0, spread / STEADINESS_SCALE_KNOTS)
        steadiness = measured_steadiness
        score = (
            SPEED_PLAUSIBILITY_SHARE * plausibility
            + (1.0 - SPEED_PLAUSIBILITY_SHARE) * measured_steadiness
        )

    evidence: dict[str, Any] = {
        "median_sog_knots": round(median, 2),
        "min_sog_knots": round(min(speeds), 2),
        "max_sog_knots": round(max(speeds), 2),
        "sog_spread_knots": round(spread, 2),
        "sample_count": len(speeds),
        "plausibility": round(plausibility, 4),
        "steadiness": None if steadiness is None else round(steadiness, 4),
        "plateau_min_knots": SPEED_PLATEAU_MIN_KNOTS,
        "plateau_max_knots": SPEED_PLATEAU_MAX_KNOTS,
    }
    return make_factor(
        FactorKey.SPEED_MATCH,
        weight=weight,
        score=score,
        explanation=explain_speed_match(evidence),
        evidence=evidence,
    )


# --------------------------------------------------------------------------- SCORE-006
def derive_ais_subscores(track: TrackContext) -> AISSubScores:
    """Compute the five SCORE-006 sub-scores from a track (``AIS_PIPELINE.md`` §6).

    Anything that cannot be computed from what the caller supplied is left ``None``
    rather than defaulted to 1.0 — assuming perfect AIS quality because we were not told
    otherwise would inflate every score in the case.
    """
    observed = track.observed_position_count
    expected = track.expected_position_count
    notes: list[str] = []

    coverage = track.coverage_ratio
    if coverage is None and expected:
        coverage = observed / expected
    if coverage is None:
        notes.append("coverage: no coverage ratio or expected position count supplied")
    else:
        coverage = max(0.0, min(1.0, coverage))

    if observed >= 2 or track.max_gap_minutes > 0:
        continuity: float | None = 1.0 - min(1.0, track.max_gap_minutes / DARK_PERIOD_MINUTES)
    else:
        continuity = None
        notes.append("continuity: fewer than two positions and no gap statistics")

    if expected:
        density: float | None = min(1.0, observed / expected)
    else:
        density = None
        notes.append("density: no expected position count for the window")

    total = observed + track.rejected_count
    if total > 0:
        cleanliness: float | None = 1.0 - (track.rejected_count / total)
    else:
        cleanliness = None
        notes.append("cleanliness: no positions at all, retained or rejected")

    identity = track.static_completeness
    if identity is None:
        notes.append("identity: no static-data completeness supplied")
    else:
        identity = max(0.0, min(1.0, identity))

    return AISSubScores(
        coverage=coverage,
        continuity=continuity,
        density=density,
        cleanliness=cleanliness,
        identity=identity,
        notes=notes,
    )


def score_ais_reliability(
    *,
    coverage: float | None = None,
    continuity: float | None = None,
    density: float | None = None,
    cleanliness: float | None = None,
    identity: float | None = None,
    weight: float = DEFAULT_WEIGHTS.ais_reliability,
    track_statistics: dict[str, Any] | None = None,
) -> FactorScore:
    """SCORE-006 — how complete and clean is this vessel's AIS history?

    Formula (``docs/AIS_PIPELINE.md`` §6, resolving ambiguity A-03)::

        score = 0.30·coverage + 0.25·continuity + 0.20·density
              + 0.15·cleanliness + 0.10·identity

    Sub-scores that could not be measured are substituted with
    :data:`INSUFFICIENT_DATA_SCORE` and named in the explanation, so a vessel is never
    credited for data nobody checked.

    An AIS gap is **not** evidence of wrongdoing (CON-002).  It lowers ``continuity``,
    ``coverage`` and ``density``, which lowers this factor, which *reduces* the vessel's
    final score.  The arithmetic runs in exactly one direction: sparse or gappy AIS can
    only ever cost a vessel points, never earn it any.  Gaps have mundane causes —
    satellite revisit intervals, terrestrial receiver coverage, message collisions in
    busy waters, equipment faults — and "it went dark, therefore it did it" is precisely
    the inference this system refuses to make.
    """
    provided = {
        "coverage": coverage,
        "continuity": continuity,
        "density": density,
        "cleanliness": cleanliness,
        "identity": identity,
    }
    if all(value is None for value in provided.values()):
        return _insufficient(
            FactorKey.AIS_RELIABILITY,
            weight,
            "no AIS quality statistics were available for this vessel.",
            sub_weights=dict(AIS_SUB_WEIGHTS),
            **(track_statistics or {}),
        )

    unmeasured = sorted(name for name, value in provided.items() if value is None)
    score = 0.0
    for name, sub_weight in AIS_SUB_WEIGHTS.items():
        value = provided[name]
        effective = INSUFFICIENT_DATA_SCORE if value is None else max(0.0, min(1.0, value))
        score += sub_weight * effective

    evidence: dict[str, Any] = {
        **{name: (None if v is None else round(v, 4)) for name, v in provided.items()},
        "sub_weights": dict(AIS_SUB_WEIGHTS),
        "unmeasured": unmeasured,
        **(track_statistics or {}),
    }
    return make_factor(
        FactorKey.AIS_RELIABILITY,
        weight=weight,
        score=score,
        explanation=explain_ais_reliability(evidence),
        evidence=evidence,
    )


__all__ = [
    "AIS_SUB_WEIGHTS",
    "DARK_PERIOD_MINUTES",
    "DEFAULT_DISTANCE_SCALE_KM",
    "DEFAULT_DWELL_SATURATION_MINUTES",
    "DEFAULT_TIME_TOLERANCE_HOURS",
    "HEADING_CEILING",
    "HEADING_FLOOR",
    "INSUFFICIENT_DATA_SCORE",
    "NEARBY_CEILING",
    "REGION_BOUNDARY_SCORE",
    "SPEED_PLATEAU_MAX_KNOTS",
    "SPEED_PLATEAU_MIN_KNOTS",
    "TRAJECTORY_BASE_SCORES",
    "derive_ais_subscores",
    "score_ais_reliability",
    "score_heading_match",
    "score_origin_proximity",
    "score_speed_match",
    "score_time_match",
    "score_trajectory_match",
    "speed_plausibility",
]
