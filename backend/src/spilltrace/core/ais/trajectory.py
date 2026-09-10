"""Trajectory construction and statistics (FR-013, P17-008…P17-009).

A trajectory is a claim about where a vessel *was*, so it may only be drawn across time
we actually observed.  That single rule produces everything here: tracks are split
wherever reporting stopped for ``SEGMENT_GAP``, a segment holding one fix yields no
geometry at all, and interpolation refuses to invent a position inside a gap.

The alternative — one long line from the first fix to the last — looks better on a map
and is a fabrication.  It would also put a vessel inside an origin region it may never
have entered, which is precisely the error the correlation stage must not make.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise

from shapely.geometry import LineString

from spilltrace.core.ais.clean import CleanedPosition
from spilltrace.core.ais.constants import (
    EXPECTED_REPORT_INTERVAL_MINUTES,
    EXPECTED_REPORT_INTERVAL_SECONDS,
    SCORE_DECIMALS,
    SEGMENT_GAP_MINUTES,
    SEGMENT_QUALITY_WEIGHT_CLEANLINESS,
    SEGMENT_QUALITY_WEIGHT_CONTINUITY,
    SEGMENT_QUALITY_WEIGHT_COVERAGE,
)
from spilltrace.core.ais.gaps import Gap, detect_gaps, gap_quality_flag, summarise_gaps
from spilltrace.core.ais.validate import ensure_utc
from spilltrace.core.enums import AISQualityFlag
from spilltrace.core.geometry import EARTH_RADIUS_M, geodesic_distance_m, geodesic_length_km

#: Metres per degree of latitude, derived from the shared Earth radius rather than
#: hard-coded, so there is one Earth in this codebase and not two.
_METRES_PER_DEGREE: float = math.radians(1.0) * EARTH_RADIUS_M


@dataclass(frozen=True, slots=True)
class TrajectorySegment:
    """One continuous run of positions, with the statistics stored alongside it.

    ``geometry`` is ``(lon, lat)`` in EPSG:4326 — longitude first, matching GeoJSON and
    PostGIS, and deliberately the opposite order from AISStream's bounding boxes, which
    are latitude-first (AD-21).  Mixing the two is the single most common bug in this
    domain, so the order is stated wherever the coordinates appear.

    ``positions`` is kept so that interpolation and closest-approach work from the
    fixes themselves rather than from a simplified line, and so every statistic can be
    traced back to the observations that produced it.
    """

    mmsi: int
    start_time: datetime
    end_time: datetime
    geometry: list[tuple[float, float]]
    positions: list[CleanedPosition]
    position_count: int
    distance_km: float
    duration_hours: float
    mean_sog_knots: float | None
    max_sog_knots: float | None
    gap_count: int
    max_gap_minutes: float
    total_gap_minutes: float
    coverage_ratio: float
    quality_score: float
    quality_flags: list[AISQualityFlag] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    segment_gap_minutes: float = SEGMENT_GAP_MINUTES

    @property
    def is_single_point(self) -> bool:
        return self.position_count < 2

    def to_linestring(self) -> LineString | None:
        """A shapely ``LineString``, or ``None`` for a single-point segment.

        ``None`` rather than a degenerate one-point line: PostGIS would accept the
        degenerate geometry and every spatial query downstream would then silently treat
        a lone fix as a track.
        """
        if len(self.geometry) < 2:
            return None
        return LineString(self.geometry)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _expected_positions(duration_seconds: float) -> float:
    """How many reports a Class A transponder owes us over this interval.

    Floored at the slowest Class A rate (one per 3 minutes) rather than the 2-10 s
    under-way rate: expecting the under-way rate would make every satellite-received
    track look catastrophically sparse, turning normal reception into an apparent data
    fault and dragging honest vessels' reliability down for it.
    """
    return max(1.0, duration_seconds / EXPECTED_REPORT_INTERVAL_SECONDS)


def _segment_quality(
    *,
    coverage_ratio: float,
    max_gap_minutes: float,
    positions: Sequence[CleanedPosition],
    segment_gap_minutes: float,
) -> float:
    """Score this segment's geometry in [0, 1].

    Distinct from the vessel-level ``ais_reliability`` (SCORE-006): this asks "how much
    do we trust the shape of this line?", not "how much of this vessel did we see?".
    Continuity is measured against the segment threshold because, by construction, no
    gap inside a segment can exceed it — the score therefore says how close the segment
    came to being split, which is the honest local question.
    """
    continuity = 1.0 - _clamp01(max_gap_minutes / segment_gap_minutes)
    unflagged = sum(1 for position in positions if not position.flags)
    cleanliness = unflagged / len(positions) if positions else 0.0
    score = (
        SEGMENT_QUALITY_WEIGHT_COVERAGE * coverage_ratio
        + SEGMENT_QUALITY_WEIGHT_CONTINUITY * continuity
        + SEGMENT_QUALITY_WEIGHT_CLEANLINESS * cleanliness
    )
    return round(_clamp01(score), SCORE_DECIMALS)


def _collect_flags(
    positions: Sequence[CleanedPosition], gaps: Sequence[Gap]
) -> list[AISQualityFlag]:
    """Every flag present in the segment, in enum declaration order.

    Declaration order rather than first-seen order so that two runs over the same data
    produce byte-identical rows; a stored artifact that reorders itself is not evidence.
    """
    present: set[AISQualityFlag] = set()
    for position in positions:
        present.update(position.flags)
    for gap in gaps:
        flag = gap_quality_flag(gap.classification)
        if flag is not None:
            present.add(flag)
    if len(positions) < 2:
        present.add(AISQualityFlag.SINGLE_POINT_SEGMENT)
    return [flag for flag in AISQualityFlag if flag in present]


def _build_segment(
    positions: list[CleanedPosition], *, segment_gap_minutes: float
) -> TrajectorySegment:
    start_time = positions[0].timestamp
    end_time = positions[-1].timestamp
    duration_seconds = (end_time - start_time).total_seconds()

    # A single fix produces no line: there is nothing between two points to draw.
    coordinates: list[tuple[float, float]] = (
        [(position.longitude, position.latitude) for position in positions]
        if len(positions) >= 2
        else []
    )
    distance_km = geodesic_length_km(LineString(coordinates)) if coordinates else 0.0

    speeds = [position.sog_knots for position in positions if position.sog_knots is not None]
    gaps = detect_gaps(positions, minimum_gap_minutes=EXPECTED_REPORT_INTERVAL_MINUTES)
    statistics = summarise_gaps(gaps)

    if len(positions) < 2:
        # One fix covers an instant, not a window; claiming full coverage of a
        # zero-length interval would make the sparsest possible track look perfect.
        coverage_ratio = 0.0
        quality_score = 0.0
    else:
        coverage_ratio = round(
            _clamp01(len(positions) / _expected_positions(duration_seconds)), SCORE_DECIMALS
        )
        quality_score = _segment_quality(
            coverage_ratio=coverage_ratio,
            max_gap_minutes=statistics.max_gap_minutes,
            positions=positions,
            segment_gap_minutes=segment_gap_minutes,
        )

    return TrajectorySegment(
        mmsi=positions[0].mmsi,
        start_time=start_time,
        end_time=end_time,
        geometry=coordinates,
        positions=list(positions),
        position_count=len(positions),
        distance_km=round(distance_km, 6),
        duration_hours=duration_seconds / 3600.0,
        mean_sog_knots=(sum(speeds) / len(speeds)) if speeds else None,
        max_sog_knots=max(speeds) if speeds else None,
        gap_count=statistics.gap_count,
        max_gap_minutes=statistics.max_gap_minutes,
        total_gap_minutes=statistics.total_gap_minutes,
        coverage_ratio=coverage_ratio,
        quality_score=quality_score,
        quality_flags=_collect_flags(positions, gaps),
        gaps=list(gaps),
        segment_gap_minutes=segment_gap_minutes,
    )


def build_trajectories(
    cleaned_positions: Sequence[CleanedPosition],
    *,
    segment_gap_minutes: float = SEGMENT_GAP_MINUTES,
) -> list[TrajectorySegment]:
    """Split one vessel's cleaned positions into continuous segments.

    Only valid positions shape a trajectory — a rejected fix stays in the record as
    evidence but must not bend the line — and the split happens at the first interval of
    ``segment_gap_minutes`` or more, matching :func:`classify_gap` exactly so the two can
    never disagree about where a segment ends.

    Segments holding a single position are returned with empty geometry and the
    ``SINGLE_POINT_SEGMENT`` flag rather than dropped: "we saw this vessel once" is a
    real observation, and discarding it would quietly shrink the evidence base.
    """
    usable = [position for position in cleaned_positions if position.is_valid]
    if not usable:
        return []

    distinct_mmsi = {position.mmsi for position in usable}
    if len(distinct_mmsi) > 1:
        raise ValueError(
            f"build_trajectories expects one vessel's positions; got {len(distinct_mmsi)} "
            "MMSIs. Group by MMSI first."
        )

    ordered = sorted(usable, key=lambda position: position.timestamp)
    groups: list[list[CleanedPosition]] = [[ordered[0]]]
    for previous, current in pairwise(ordered):
        gap_minutes = (current.timestamp - previous.timestamp).total_seconds() / 60.0
        if gap_minutes >= segment_gap_minutes:
            groups.append([current])
        else:
            groups[-1].append(current)

    return [_build_segment(group, segment_gap_minutes=segment_gap_minutes) for group in groups]


def _interpolate_pair(
    first: CleanedPosition, second: CleanedPosition, fraction: float
) -> tuple[float, float]:
    """Linear interpolation in degrees, correct across the antimeridian.

    Over an interval short enough to interpolate at all (≤ 30 minutes), the difference
    between a straight line in degrees and a great circle is far below AIS positional
    accuracy.  The ±360° correction is not optional though: without it a vessel crossing
    180° appears to sprint the long way round the planet.
    """
    lon1, lon2 = first.longitude, second.longitude
    delta_lon = lon2 - lon1
    if delta_lon > 180.0:
        delta_lon -= 360.0
    elif delta_lon < -180.0:
        delta_lon += 360.0
    longitude = lon1 + delta_lon * fraction
    if longitude > 180.0:
        longitude -= 360.0
    elif longitude < -180.0:
        longitude += 360.0
    latitude = first.latitude + (second.latitude - first.latitude) * fraction
    return longitude, latitude


def interpolate_position(segment: TrajectorySegment, when: datetime) -> tuple[float, float] | None:
    """Where the vessel was at ``when``, or ``None`` if we cannot honestly say.

    ``None`` is returned outside the segment's own window, and inside any interval
    longer than the segment's splitting threshold.  Interpolating across a gap would
    manufacture a position from nothing and hand it to the correlation stage as though
    it had been observed; a missing answer is recoverable, a fabricated one is not.
    """
    moment = ensure_utc(when)
    positions = segment.positions
    if not positions:
        return None
    if len(positions) == 1:
        only = positions[0]
        return (only.longitude, only.latitude) if moment == only.timestamp else None
    if moment < segment.start_time or moment > segment.end_time:
        return None

    for first, second in pairwise(positions):
        if not first.timestamp <= moment <= second.timestamp:
            continue
        # Never bridge more than SEGMENT_GAP, even if this segment was built with a
        # looser threshold: 30 minutes is where the specification stops calling a run of
        # positions continuous, and a tighter custom threshold is honoured too.
        limit_minutes = min(segment.segment_gap_minutes, SEGMENT_GAP_MINUTES)
        span_seconds = (second.timestamp - first.timestamp).total_seconds()
        if span_seconds > limit_minutes * 60.0:
            return None
        if span_seconds <= 0.0:
            return (first.longitude, first.latitude)
        fraction = (moment - first.timestamp).total_seconds() / span_seconds
        return _interpolate_pair(first, second, fraction)
    return None


def _closest_point_on_leg(
    first: CleanedPosition, second: CleanedPosition, target_lon: float, target_lat: float
) -> tuple[float, datetime]:
    """Nearest approach on one leg: ``(distance_km, when)``.

    The leg is projected onto a local tangent plane to find the fraction along it, then
    the distance itself is measured geodesically.  The planar step only chooses *where*
    on the leg to measure; any small error in that choice moves the answer by far less
    than the AIS position it is measured from.
    """
    lat_reference = math.radians((first.latitude + second.latitude) / 2.0)
    scale_x = math.cos(lat_reference) * _METRES_PER_DEGREE
    leg_x = (second.longitude - first.longitude) * scale_x
    leg_y = (second.latitude - first.latitude) * _METRES_PER_DEGREE
    target_x = (target_lon - first.longitude) * scale_x
    target_y = (target_lat - first.latitude) * _METRES_PER_DEGREE

    leg_length_squared = leg_x * leg_x + leg_y * leg_y
    if leg_length_squared <= 0.0:
        fraction = 0.0
    else:
        fraction = (target_x * leg_x + target_y * leg_y) / leg_length_squared
        fraction = max(0.0, min(1.0, fraction))

    longitude, latitude = _interpolate_pair(first, second, fraction)
    distance_km = geodesic_distance_m(longitude, latitude, target_lon, target_lat) / 1000.0
    span = (second.timestamp - first.timestamp).total_seconds()
    when = first.timestamp + timedelta(seconds=span * fraction)
    return distance_km, when


def closest_approach(
    segment: TrajectorySegment, target_lon: float, target_lat: float
) -> tuple[float, datetime]:
    """Closest the track came to a point: ``(distance_km, when)``.

    The minimum is taken along the legs, not just at the reported fixes.  With reports
    minutes apart, the true closest approach usually falls between two of them, and
    reporting the nearest *fix* instead would overstate the distance — understating how
    close a vessel came to an origin region is exactly the wrong direction to be wrong
    in for an investigative tool.
    """
    positions = segment.positions
    if not positions:
        raise ValueError("closest_approach requires a segment with at least one position.")
    if len(positions) == 1:
        only = positions[0]
        distance_km = (
            geodesic_distance_m(only.longitude, only.latitude, target_lon, target_lat) / 1000.0
        )
        return distance_km, only.timestamp

    candidates = [
        _closest_point_on_leg(first, second, target_lon, target_lat)
        for first, second in pairwise(positions)
    ]
    return min(candidates, key=lambda candidate: candidate[0])


__all__ = [
    "TrajectorySegment",
    "build_trajectories",
    "closest_approach",
    "interpolate_position",
]
