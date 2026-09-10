"""Vessel correlation (FR-014).

Correlation answers a narrow question: *which vessels were compatible, in space and
time, with the inferred origin?*  It deliberately does not rank or judge — that is the
scoring stage — and it records why each candidate was included so an analyst can
disagree with the reasoning rather than only with the answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

from shapely.geometry import LineString, Point, shape
from shapely.geometry.base import BaseGeometry

from spilltrace.core.geometry import (
    buffer_m,
    geodesic_distance_m,
    point_to_geometry_distance_km,
)

#: How far outside the origin region a vessel may still be a candidate.  Set from the
#: scale of AIS positional error plus the spread a short drift adds, not from a desire
#: to catch more vessels: widening it does not find the culprit, it finds more noise.
DEFAULT_BUFFER_KM = 5.0
#: Slack on the inferred discharge window, reflecting that the window itself is inferred.
DEFAULT_TIME_TOLERANCE_HOURS = 2.0


@dataclass(slots=True)
class CandidateEvidence:
    """Why a vessel was included, in numbers an analyst can check."""

    mmsi: int
    closest_approach_km: float
    closest_approach_time: datetime | None
    contour_probability: float | None
    inside_region: bool
    dwell_minutes: float
    positions_in_window: int
    entered: bool
    left: bool
    course_deg: float | None
    speed_knots: float | None
    reason: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mmsi": self.mmsi,
            "closest_approach_km": round(self.closest_approach_km, 3),
            "closest_approach_time": (
                self.closest_approach_time.isoformat() if self.closest_approach_time else None
            ),
            "contour_probability": self.contour_probability,
            "inside_region": self.inside_region,
            "dwell_minutes": round(self.dwell_minutes, 1),
            "positions_in_window": self.positions_in_window,
            "entered": self.entered,
            "left": self.left,
            "course_deg": round(self.course_deg, 1) if self.course_deg is not None else None,
            "speed_knots": round(self.speed_knots, 2) if self.speed_knots is not None else None,
            "reason": self.reason,
            "notes": self.notes,
        }


def correlate_track(
    *,
    mmsi: int,
    samples: list[tuple[datetime, float, float, float | None, float | None]],
    origin_region: BaseGeometry,
    contours: list[tuple[float, dict[str, Any]]],
    window_start: datetime,
    window_end: datetime,
    buffer_km: float = DEFAULT_BUFFER_KM,
    time_tolerance_hours: float = DEFAULT_TIME_TOLERANCE_HOURS,
) -> CandidateEvidence | None:
    """Measure one vessel against the origin region, or return ``None`` if incompatible.

    ``samples`` are ``(timestamp, lon, lat, sog_knots, cog_deg)`` in time order.
    """
    if not samples:
        return None

    tolerance = timedelta(hours=time_tolerance_hours)
    lower, upper = window_start - tolerance, window_end + tolerance
    in_window = [s for s in samples if lower <= s[0] <= upper]
    if not in_window:
        return None

    search_region = buffer_m(origin_region, buffer_km * 1000.0) if buffer_km > 0 else origin_region

    closest_km = float("inf")
    inside_flags: list[bool] = []
    distances: list[float] = []

    for sample in in_window:
        _when, lon, lat, _sog, _cog = sample
        point = Point(lon, lat)
        distance = point_to_geometry_distance_km(point, origin_region)
        distances.append(distance)
        inside_flags.append(bool(search_region.covers(point)))
        closest_km = min(closest_km, distance)

    if not any(inside_flags):
        return None

    # A vessel crossing the region has many fixes at distance zero.  Taking the first
    # would report the moment it clipped the edge; the midpoint of the closest run is
    # the representative moment, and it is what an analyst would point at on a chart.
    closest_indices = [i for i, d in enumerate(distances) if d <= closest_km + 1e-9]
    representative = closest_indices[len(closest_indices) // 2]
    closest_sample = in_window[representative]
    closest_time = closest_sample[0]

    dwell_minutes = _dwell(in_window, inside_flags)
    entered = inside_flags[0] is False and any(inside_flags)
    left = inside_flags[-1] is False and any(inside_flags)

    # The tightest contour the vessel entered *at any point* in the window, not merely
    # the one it happened to be in at the instant of minimum distance.  "Did it cross
    # the high-probability core?" is the question the scoring stage actually asks.
    contour_probability = _tightest_contour_over(contours, in_window)
    inside_region = any(origin_region.covers(Point(sample[1], sample[2])) for sample in in_window)

    reason = _reason(
        inside_region=inside_region,
        contour_probability=contour_probability,
        closest_km=closest_km,
        closest_time=closest_time,
        window_start=window_start,
        window_end=window_end,
        dwell_minutes=dwell_minutes,
        buffer_km=buffer_km,
    )
    notes: list[str] = []
    if not inside_region:
        notes.append(
            f"The vessel did not enter the origin region itself; it came within "
            f"{closest_km:.1f} km of it, inside the {buffer_km:.0f} km search buffer."
        )
    if closest_time is not None and not (window_start <= closest_time <= window_end):
        notes.append(
            "The closest approach falls outside the inferred discharge window but within "
            f"the {time_tolerance_hours:.0f}-hour tolerance applied to it."
        )

    return CandidateEvidence(
        mmsi=mmsi,
        closest_approach_km=closest_km,
        closest_approach_time=closest_time,
        contour_probability=contour_probability,
        inside_region=inside_region,
        dwell_minutes=dwell_minutes,
        positions_in_window=len(in_window),
        entered=entered,
        left=left,
        course_deg=closest_sample[4] if closest_sample else None,
        speed_knots=closest_sample[3] if closest_sample else None,
        reason=reason,
        notes=notes,
    )


def _dwell(
    samples: list[tuple[datetime, float, float, float | None, float | None]],
    inside_flags: list[bool],
) -> float:
    """Minutes spent inside the region, from the intervals between inside fixes."""
    total = 0.0
    for i in range(1, len(samples)):
        if inside_flags[i] and inside_flags[i - 1]:
            total += (samples[i][0] - samples[i - 1][0]).total_seconds() / 60.0
    return total


def _tightest_contour_over(
    contours: list[tuple[float, dict[str, Any]]],
    samples: list[tuple[datetime, float, float, float | None, float | None]],
) -> float | None:
    """The most concentrated contour any of ``samples`` falls inside.

    A lower probability mass means a *tighter*, more concentrated region, so entering
    the 50% contour is stronger evidence than only reaching the 90% one.
    """
    if not samples:
        return None
    parsed: list[tuple[float, Any]] = []
    for level, geojson in contours:
        try:
            parsed.append((level, shape(geojson)))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return None

    best: float | None = None
    for level, geometry in sorted(parsed):  # tightest first, so we can stop early
        if any(geometry.covers(Point(s[1], s[2])) for s in samples):
            best = level
            break
    return best


def _reason(
    *,
    inside_region: bool,
    contour_probability: float | None,
    closest_km: float,
    closest_time: datetime | None,
    window_start: datetime,
    window_end: datetime,
    dwell_minutes: float,
    buffer_km: float,
) -> str:
    parts: list[str] = []
    if inside_region and contour_probability is not None:
        parts.append(f"Entered the {round(contour_probability * 100)}% origin probability contour")
    elif inside_region:
        parts.append("Entered the origin probability region")
    else:
        parts.append(
            f"Passed within {closest_km:.1f} km of the origin region "
            f"(search buffer {buffer_km:.0f} km)"
        )
    if closest_time is not None:
        inside_window = window_start <= closest_time <= window_end
        parts.append(
            f"closest approach at {closest_time:%Y-%m-%d %H:%M} UTC, "
            + ("inside" if inside_window else "just outside")
            + " the inferred discharge window"
        )
    if dwell_minutes > 0:
        parts.append(f"present in the area for about {dwell_minutes:.0f} minutes")
    return "; ".join(parts) + "."


def track_to_samples(
    coordinates: list[tuple[float, float]], times: list[datetime]
) -> list[tuple[datetime, float, float, None, None]]:
    """Utility for tests and for callers holding a bare LineString."""
    return [(t, lon, lat, None, None) for t, (lon, lat) in zip(times, coordinates, strict=True)]


def line_bearing(line: LineString) -> float | None:
    from spilltrace.core.geometry import initial_bearing_deg

    coords = list(line.coords)
    if len(coords) < 2:
        return None
    return initial_bearing_deg(coords[0][0], coords[0][1], coords[-1][0], coords[-1][1])


def segment_length_km(coordinates: list[tuple[float, float]]) -> float:
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in pairwise(coordinates):
        total += geodesic_distance_m(lon1, lat1, lon2, lat2)
    return total / 1000.0


__all__ = [
    "DEFAULT_BUFFER_KM",
    "DEFAULT_TIME_TOLERANCE_HOURS",
    "CandidateEvidence",
    "correlate_track",
    "line_bearing",
    "segment_length_km",
    "track_to_samples",
]
