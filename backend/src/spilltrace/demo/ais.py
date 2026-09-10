"""Synthetic AIS message generation.

The messages produced here are deliberately *imperfect*: they carry duplicates, an
impossible position jump, sentinel values and reporting gaps, because a demonstration in
which the cleaning stage has nothing to remove would prove nothing about the cleaning
stage.  Everything is seeded, so the same defects appear every run.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import numpy as np

from spilltrace.core.enums import DataProvenance
from spilltrace.core.geometry import destination_point, initial_bearing_deg
from spilltrace.core.ports import AISMessage
from spilltrace.core.provenance import label_synthetic
from spilltrace.demo.scenarios import Scenario, VesselProfile

#: Class A vessels under way report every 2-10 s; a 3-minute decimation is what a
#: terrestrial/satellite aggregator typically delivers and keeps the volume sane.
REPORT_INTERVAL_SECONDS = 180

#: Fixes to leave between a vessel's closest approach and the start of an injected
#: reporting gap.  6 fixes at a 3-minute rate is 18 minutes.
GAP_MARGIN_STEPS = 6


def _track_points(
    profile: VesselProfile,
    *,
    origin_lon: float,
    origin_lat: float,
    closest_time: datetime,
    window_start: datetime,
    window_end: datetime,
) -> list[tuple[datetime, float, float]]:
    """Straight-line transit passing ``closest_approach_km`` from a given point.

    The closest-approach point is placed perpendicular to the vessel's course, so the
    geometry the correlation stage measures is exactly the geometry the scenario intends.
    """
    # Offset perpendicular to the course; the side alternates by MMSI parity so tracks
    # do not all stack on the same flank.
    perpendicular = (profile.course_deg + (90.0 if profile.mmsi % 2 == 0 else -90.0)) % 360.0
    cpa_lon, cpa_lat = destination_point(
        origin_lon, origin_lat, perpendicular, profile.closest_approach_km * 1000.0
    )

    speed_ms = profile.speed_knots * 0.514444
    points: list[tuple[datetime, float, float]] = []
    step = timedelta(seconds=REPORT_INTERVAL_SECONDS)

    total_seconds = (window_end - window_start).total_seconds()
    steps = int(total_seconds // REPORT_INTERVAL_SECONDS) + 1
    for i in range(steps):
        when = window_start + i * step
        offset_s = (when - closest_time).total_seconds()
        distance_m = speed_ms * offset_s
        bearing = profile.course_deg if distance_m >= 0 else (profile.course_deg + 180.0) % 360.0
        lon, lat = destination_point(cpa_lon, cpa_lat, bearing, abs(distance_m))
        points.append((when, lon, lat))
    return points


def generate_vessel_messages(
    profile: VesselProfile, scenario: Scenario, *, seed: int
) -> list[AISMessage]:
    """Position reports plus one static-data message for a single vessel.

    The vessel's closest approach is placed on the *drift corridor* — where the oil
    actually was at that moment — rather than near the observed slick, so the geometry
    the pipeline solves is physically self-consistent.  See ``spilltrace.demo.origin``.
    """
    from spilltrace.demo.origin import backtracked_position

    rng = np.random.default_rng(seed ^ (profile.mmsi & 0xFFFFFFFF))
    corridor_lon, corridor_lat = backtracked_position(
        scenario, hours_before_acquisition=profile.hours_before_acquisition
    )
    closest_time = scenario.acquisition_time - timedelta(hours=profile.hours_before_acquisition)
    points = _track_points(
        profile,
        origin_lon=corridor_lon,
        origin_lat=corridor_lat,
        closest_time=closest_time,
        window_start=scenario.case_start,
        window_end=scenario.case_end,
    )

    # Reporting gap, placed deterministically just *after* the closest approach.
    #
    # Two failure modes are being avoided.  A randomly placed gap can swallow the
    # closest approach, removing the vessel from correlation entirely and demonstrating
    # nothing about reliability.  A gap placed too late simply truncates the track's
    # tail, which is a shorter track, not a gap.  Anchoring it to the approach gives an
    # interior gap every time — and reproduces the pattern an analyst actually
    # encounters: a vessel is seen in the area and its reporting then stops.
    #
    # That pattern is *not* treated as misconduct anywhere in this system.  It lowers
    # the AIS reliability factor, which lowers the vessel's score (CON-002).
    if profile.gap_minutes > 0 and len(points) > 4:
        gap_steps = int(profile.gap_minutes * 60 // REPORT_INTERVAL_SECONDS)
        cpa_index = min(
            range(len(points)), key=lambda i: abs((points[i][0] - closest_time).total_seconds())
        )
        start = min(cpa_index + GAP_MARGIN_STEPS, len(points) - 3)
        start = max(1, start)
        # Leave at least two fixes after the gap so it is an interior gap, not a truncation.
        gap_steps = min(gap_steps, len(points) - start - 2)
        if gap_steps > 0:
            points = points[:start] + points[start + gap_steps :]

    messages: list[AISMessage] = []
    display_name = label_synthetic(profile.name, DataProvenance.SYNTHETIC)

    for index, (when, lon, lat) in enumerate(points):
        # GNSS-scale jitter: roughly 10 m, which is realistic and small enough that the
        # cleaning rules must not flag it.
        jitter_lon = float(rng.normal(0.0, 0.00010))
        jitter_lat = float(rng.normal(0.0, 0.00009))
        sog = float(profile.speed_knots + rng.normal(0.0, 0.25))
        cog = float((profile.course_deg + rng.normal(0.0, 1.6)) % 360.0)
        heading = float((cog + rng.normal(0.0, 1.1)) % 360.0)

        messages.append(
            AISMessage(
                mmsi=profile.mmsi,
                timestamp=when,
                latitude=round(lat + jitter_lat, 6),
                longitude=round(lon + jitter_lon, 6),
                message_type="PositionReport",
                source="SYNTHETIC",
                sog_knots=round(max(0.0, sog), 2),
                cog_deg=round(cog, 1),
                heading_deg=round(heading, 0),
                nav_status=0,
                name=display_name,
                data_provenance=DataProvenance.SYNTHETIC,
                raw={"synthetic": True, "index": index},
            )
        )

    if profile.inject_defects and len(messages) > 40:
        messages = _inject_defects(messages, rng)

    # One static-data message so vessel identity has a realistic completeness profile.
    if messages:
        mid = messages[len(messages) // 2]
        messages.append(
            AISMessage(
                mmsi=profile.mmsi,
                timestamp=mid.timestamp,
                latitude=mid.latitude,
                longitude=mid.longitude,
                message_type="ShipStaticData",
                source="SYNTHETIC",
                name=display_name,
                imo=profile.imo,
                callsign=f"S{profile.mmsi % 100000:05d}",
                ship_type=profile.ship_type,
                destination="KANDLA" if profile.mmsi % 3 == 0 else "MUNDRA",
                length_m=profile.length_m,
                width_m=profile.width_m,
                draught_m=round(float(profile.length_m / 18.0), 1),
                data_provenance=DataProvenance.SYNTHETIC,
                raw={"synthetic": True},
            )
        )
    return messages


def _inject_defects(messages: list[AISMessage], rng: np.random.Generator) -> list[AISMessage]:
    """Add the defects a real feed contains, so cleaning has real work to do.

    Three kinds, each targeting a different cleaning rule:
    an exact duplicate (multi-receiver relay), an impossible position jump (decoding
    error), and a sentinel SOG of 102.3 knots meaning "not available".
    """
    out = list(messages)

    # 1. Exact duplicates, as produced when two receivers relay the same frame.
    for _ in range(3):
        i = int(rng.integers(5, len(out) - 5))
        out.append(out[i])

    # 2. An impossible jump: ~400 km displacement between consecutive 3-minute fixes.
    i = int(rng.integers(10, len(out) - 10))
    bad = out[i]
    jump_lon, jump_lat = destination_point(bad.longitude, bad.latitude, 45.0, 400_000.0)
    out[i] = replace(
        bad,
        latitude=round(jump_lat, 6),
        longitude=round(jump_lon, 6),
        raw={**bad.raw, "defect": "impossible_jump"},
    )

    # 3. Sentinel speed: 102.3 knots means "speed not available", not a fast ship.
    j = int(rng.integers(10, len(out) - 10))
    sentinel = out[j]
    out[j] = replace(
        sentinel,
        sog_knots=102.3,
        cog_deg=360.0,
        heading_deg=511.0,
        raw={**sentinel.raw, "defect": "sentinel_values"},
    )

    out.sort(key=lambda m: m.timestamp)
    return out


def generate_scenario_messages(scenario: Scenario, *, seed: int) -> list[AISMessage]:
    messages: list[AISMessage] = []
    for profile in scenario.vessels:
        messages.extend(generate_vessel_messages(profile, scenario, seed=seed))
    messages.sort(key=lambda m: (m.timestamp, m.mmsi))
    return messages


def observed_course(points: list[tuple[datetime, float, float]]) -> float | None:
    if len(points) < 2:
        return None
    (_, lon1, lat1), (_, lon2, lat2) = points[0], points[-1]
    return initial_bearing_deg(lon1, lat1, lon2, lat2)


__all__ = [
    "GAP_MARGIN_STEPS",
    "REPORT_INTERVAL_SECONDS",
    "generate_scenario_messages",
    "generate_vessel_messages",
    "observed_course",
]
