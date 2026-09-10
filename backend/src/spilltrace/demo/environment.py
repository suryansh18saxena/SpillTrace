"""Synthetic wind and current fields.

Physically plausible rather than physically correct: a slowly-rotating background flow
with a spatial gradient and mild temporal variability.  That is enough for the drift
engine to produce a spread-out, non-degenerate origin region, which is what the demo has
to demonstrate.  It is not, and is never presented as, a forecast.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np

from spilltrace.core.enums import DataProvenance
from spilltrace.core.ports import EnvironmentalBundle, EnvironmentalField


def _axis(minimum: float, maximum: float, resolution: float) -> tuple[float, ...]:
    count = max(2, round((maximum - minimum) / resolution) + 1)
    return tuple(float(v) for v in np.linspace(minimum, maximum, count))


def synthetic_environment(
    *,
    bbox: tuple[float, float, float, float],
    start: datetime,
    end: datetime,
    wind_speed_ms: float,
    wind_direction_deg: float,
    current_speed_ms: float,
    current_direction_deg: float,
    seed: int,
    resolution_deg: float = 0.05,
    time_step_hours: float = 1.0,
) -> EnvironmentalBundle:
    """Build a seeded wind + current bundle over ``bbox`` and ``[start, end]``.

    Meteorological convention note: ``wind_direction_deg`` is the direction the wind
    comes **from**, so the vector it imparts points 180° away.  Ocean current direction
    is the direction the water flows **towards**.  Mixing these up is the classic drift
    bug, so both are converted explicitly here.
    """
    rng = np.random.default_rng(seed + 5501)
    min_lon, min_lat, max_lon, max_lat = bbox
    lons = _axis(min_lon, max_lon, resolution_deg)
    lats = _axis(min_lat, max_lat, resolution_deg)

    hours = max(1, math.ceil((end - start).total_seconds() / 3600.0 / time_step_hours))
    times = tuple(start + timedelta(hours=i * time_step_hours) for i in range(hours + 1))

    shape = (len(times), len(lats), len(lons))
    lat_grid = np.asarray(lats)[None, :, None]
    lon_grid = np.asarray(lons)[None, None, :]
    t_index = np.arange(len(times))[:, None, None]

    # Wind blows *from* wind_direction_deg.
    wind_to = math.radians((wind_direction_deg + 180.0) % 360.0)
    # A slow veer over the window plus a gentle spatial shear.
    veer = np.radians(6.0) * np.sin(2 * math.pi * t_index / max(12.0, len(times)))
    speed = wind_speed_ms * (
        1.0
        + 0.10 * np.sin(2 * math.pi * t_index / max(9.0, len(times)))
        + 0.05 * (lat_grid - float(np.mean(lats))) / max(1e-6, (max_lat - min_lat))
    )
    speed = speed + rng.normal(0.0, wind_speed_ms * 0.03, shape)
    wind_u = (speed * np.sin(wind_to + veer)).astype(np.float32)
    wind_v = (speed * np.cos(wind_to + veer)).astype(np.float32)

    # Current flows *towards* current_direction_deg.
    current_to = math.radians(current_direction_deg)
    c_speed = current_speed_ms * (
        1.0
        + 0.18 * np.sin(2 * math.pi * t_index / max(12.4, len(times)))  # semi-diurnal-ish
        + 0.12 * (lon_grid - float(np.mean(lons))) / max(1e-6, (max_lon - min_lon))
    )
    c_speed = c_speed + rng.normal(0.0, current_speed_ms * 0.05, shape)
    current_u = (c_speed * np.sin(current_to)).astype(np.float32)
    current_v = (c_speed * np.cos(current_to)).astype(np.float32)

    def field(name: str, values: np.ndarray) -> EnvironmentalField:
        return EnvironmentalField(
            variable=name,
            units="m s-1",
            times=times,
            lats=lats,
            lons=lons,
            values=values,
            source="SYNTHETIC",
            dataset_id=None,
            data_provenance=DataProvenance.SYNTHETIC,
        )

    return EnvironmentalBundle(
        wind_u=field("eastward_wind", wind_u),
        wind_v=field("northward_wind", wind_v),
        current_u=field("eastward_current", current_u),
        current_v=field("northward_current", current_v),
        source="SYNTHETIC",
        dataset_ids={},
        data_provenance=DataProvenance.SYNTHETIC,
    )


def summarise(bundle: EnvironmentalBundle) -> dict[str, dict[str, float]]:
    """Min/mean/max per variable, stored on the run so the UI need not open the grid."""
    out: dict[str, dict[str, float]] = {}
    for field_obj in (bundle.wind_u, bundle.wind_v, bundle.current_u, bundle.current_v):
        values = np.asarray(field_obj.values)
        out[field_obj.variable] = {
            "min": round(float(values.min()), 4),
            "mean": round(float(values.mean()), 4),
            "max": round(float(values.max()), 4),
            "units": field_obj.units,  # type: ignore[dict-item]
        }
    wind_speed = np.hypot(np.asarray(bundle.wind_u.values), np.asarray(bundle.wind_v.values))
    current_speed = np.hypot(
        np.asarray(bundle.current_u.values), np.asarray(bundle.current_v.values)
    )
    out["wind_speed"] = {
        "min": round(float(wind_speed.min()), 4),
        "mean": round(float(wind_speed.mean()), 4),
        "max": round(float(wind_speed.max()), 4),
        "units": "m s-1",  # type: ignore[dict-item]
    }
    out["current_speed"] = {
        "min": round(float(current_speed.min()), 4),
        "mean": round(float(current_speed.mean()), 4),
        "max": round(float(current_speed.max()), 4),
        "units": "m s-1",  # type: ignore[dict-item]
    }
    return out


__all__ = ["summarise", "synthetic_environment"]
