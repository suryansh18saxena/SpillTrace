"""Where the synthetic vessels should be placed.

The slick is *observed* where the oil has drifted to; the discharge happened somewhere
upstream of it.  A scenario that arranged its vessels around the observed slick would
put them nowhere near the region the reverse-drift stage actually produces, and the
demonstration would show a working pipeline arriving at a meaningless answer.

So the generator computes the same displacement the drift engine will undo — mean
current plus a wind-drift fraction of the mean wind, integrated over the back-track
duration — and places the cast around *that* point.  The drift stage is still doing real
work: it recovers a probability region, with spread and uncertainty, from a slick it was
never told the origin of.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from spilltrace.adapters.drift.analytical import DEFAULT_WIND_DRIFT_FACTOR
from spilltrace.core.geometry import destination_point
from spilltrace.demo.scenarios import Scenario


def mean_drift_vector(
    scenario: Scenario, *, wind_drift_factor: float = DEFAULT_WIND_DRIFT_FACTOR
) -> tuple[float, float]:
    """Return ``(speed_ms, bearing_deg)`` of the combined surface drift.

    Wind direction is meteorological (the direction it blows *from*), current direction
    is oceanographic (the direction it flows *towards*).  Both are converted here so the
    two vectors can be added.
    """
    current_to = math.radians(scenario.current_direction_deg)
    wind_to = math.radians((scenario.wind_direction_deg + 180.0) % 360.0)

    u = scenario.current_speed_ms * math.sin(current_to) + (
        wind_drift_factor * scenario.wind_speed_ms * math.sin(wind_to)
    )
    v = scenario.current_speed_ms * math.cos(current_to) + (
        wind_drift_factor * scenario.wind_speed_ms * math.cos(wind_to)
    )
    speed = math.hypot(u, v)
    bearing = math.degrees(math.atan2(u, v)) % 360.0
    return speed, bearing


def expected_origin_centre(
    scenario: Scenario,
    *,
    hindcast_hours: float,
    wind_drift_factor: float = DEFAULT_WIND_DRIFT_FACTOR,
) -> tuple[float, float]:
    """The point the slick centre back-tracks to under the mean drift.

    ``hindcast_hours`` must match the drift stage's duration, otherwise the vessels sit
    at a different distance upstream than the region the drift run recovers.
    """
    speed, bearing = mean_drift_vector(scenario, wind_drift_factor=wind_drift_factor)
    distance_m = speed * hindcast_hours * 3600.0
    reverse_bearing = (bearing + 180.0) % 360.0
    lon, lat = scenario.slick_centre
    return destination_point(lon, lat, reverse_bearing, distance_m)


def expected_origin_time(scenario: Scenario, *, hindcast_hours: float) -> datetime:
    """The time the back-track reaches the expected origin centre."""
    return scenario.acquisition_time - timedelta(hours=hindcast_hours)


def backtracked_position(
    scenario: Scenario,
    *,
    hours_before_acquisition: float,
    wind_drift_factor: float = DEFAULT_WIND_DRIFT_FACTOR,
) -> tuple[float, float]:
    """Where the oil was ``hours_before_acquisition`` before the slick was observed.

    This is what makes the scenario physically self-consistent: a vessel that discharged
    at time *t* must have been where the oil was at time *t*, not near where the oil was
    eventually seen.  Placing the cast along this corridor means the correlation and
    scoring stages are solving a real geometry rather than one arranged around them.
    """
    speed, bearing = mean_drift_vector(scenario, wind_drift_factor=wind_drift_factor)
    distance_m = speed * max(0.0, hours_before_acquisition) * 3600.0
    lon, lat = scenario.slick_centre
    return destination_point(lon, lat, (bearing + 180.0) % 360.0, distance_m)


__all__ = [
    "backtracked_position",
    "expected_origin_centre",
    "expected_origin_time",
    "mean_drift_vector",
]
