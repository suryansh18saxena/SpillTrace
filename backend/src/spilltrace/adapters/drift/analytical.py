"""Deterministic advection-diffusion drift engine.

This is a transparent Lagrangian particle model, not a replacement for OpenOil.  It
integrates

    dx/dt = u_current + alpha * u_wind + turbulent random walk

with a per-particle wind drift factor ``alpha``.  Weathering, vertical mixing,
entrainment and Stokes drift are **not** modelled; the engine reports that in its notes
so nothing downstream can mistake it for a physics-grade simulation.

It exists because the reasoning chain must never be blocked by a heavy optional
dependency (AD-18), and because a deterministic engine makes the reproducibility
requirement (AC-07) directly testable.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from spilltrace.core.enums import DriftMode
from spilltrace.core.errors import ProcessingError
from spilltrace.core.ports import (
    DriftResult,
    EnvironmentalBundle,
    EnvironmentalField,
    ParticleState,
    ProgressCallback,
)

#: Fraction of the 10 m wind speed imparted to surface oil.  OpenDrift documents ~0.033
#: with Stokes drift included and ~0.02 in addition to it; ~0.035 is commonly used for
#: oil and iSphere drifters.  The uncertainty is large, which is why it is sampled.
DEFAULT_WIND_DRIFT_FACTOR = 0.03
DEFAULT_WIND_DRIFT_SIGMA = 0.01

#: Horizontal eddy diffusivity, m² s⁻¹.  10 is the value used in OpenDrift's own
#: examples for coastal work.
DEFAULT_DIFFUSIVITY_M2_S = 10.0

METRES_PER_DEGREE_LAT = 111_320.0


class AnalyticalDriftEngine:
    """Implements :class:`spilltrace.core.ports.DriftEngine`."""

    name = "analytical"

    async def simulate(
        self,
        *,
        seed_geojson: dict[str, Any],
        start_time: datetime,
        mode: DriftMode,
        duration_hours: float,
        time_step_seconds: int,
        number_of_particles: int,
        environment: EnvironmentalBundle,
        seed: int,
        ensemble_members: int = 1,
        parameters: dict[str, Any] | None = None,
        progress: ProgressCallback | None = None,
    ) -> DriftResult:
        params = dict(parameters or {})
        wind_drift_factor = float(params.get("wind_drift_factor", DEFAULT_WIND_DRIFT_FACTOR))
        wind_drift_sigma = float(params.get("wind_drift_sigma", DEFAULT_WIND_DRIFT_SIGMA))
        diffusivity = float(params.get("horizontal_diffusivity", DEFAULT_DIFFUSIVITY_M2_S))

        geometry = shape(seed_geojson)
        if geometry.is_empty:
            raise ProcessingError("Cannot seed a drift run from an empty geometry.")

        rng = np.random.default_rng(seed)
        per_member = max(1, number_of_particles // max(1, ensemble_members))
        # Backward means integrating with a negative step; duration stays positive, which
        # matches OpenDrift's own convention so the two engines are called identically.
        direction = -1.0 if mode is DriftMode.BACKWARD else 1.0
        steps = max(1, round(duration_hours * 3600.0 / time_step_seconds))
        dt = float(time_step_seconds) * direction

        times: list[datetime] = [
            start_time + timedelta(seconds=dt * step) for step in range(steps + 1)
        ]

        particles: list[ParticleState] = []
        particle_id = 0
        for member in range(max(1, ensemble_members)):
            lons, lats = _seed_points(geometry, per_member, rng)
            # Each member gets its own wind-drift factor draw: this is the dominant
            # source of spread in the origin region, and sampling it is what turns a
            # single trajectory into a probability region (AD-20).
            alphas = rng.normal(wind_drift_factor, wind_drift_sigma, size=lons.shape)
            alphas = np.clip(alphas, 0.0, 0.08)

            member_ids = np.arange(particle_id, particle_id + lons.size)
            particle_id += lons.size

            for index, when in enumerate(times):
                if index > 0:
                    lons, lats = _advect(
                        lons,
                        lats,
                        environment=environment,
                        when=times[index - 1],
                        dt_seconds=dt,
                        alphas=alphas,
                        diffusivity=diffusivity,
                        rng=rng,
                    )
                for pid, lon, lat in zip(member_ids, lons, lats, strict=True):
                    particles.append(
                        ParticleState(
                            particle_id=int(pid),
                            step_index=index,
                            timestamp=when,
                            lon=float(lon),
                            lat=float(lat),
                            member=member,
                            status="active",
                        )
                    )
                if progress is not None and index % max(1, steps // 10) == 0:
                    await progress(
                        fraction=(member + index / max(1, steps)) / max(1, ensemble_members),
                        message=f"member {member + 1}/{ensemble_members}, step {index}/{steps}",
                    )

        return DriftResult(
            mode=mode,
            engine=self.name,
            seed=seed,
            particles=particles,
            times=tuple(times),
            parameters={
                "wind_drift_factor": wind_drift_factor,
                "wind_drift_sigma": wind_drift_sigma,
                "horizontal_diffusivity": diffusivity,
                "time_step_seconds": time_step_seconds,
                "duration_hours": duration_hours,
                "ensemble_members": ensemble_members,
                "particles_per_member": per_member,
                "engine": self.name,
            },
            data_provenance=environment.data_provenance,
            notes=[
                "Analytical advection-diffusion engine: surface current plus a sampled "
                "wind drift factor, with a turbulent random walk.",
                "Oil weathering, evaporation, emulsification, entrainment, vertical "
                "mixing and Stokes drift are NOT modelled.",
                "Results indicate a plausible origin area under these assumptions; they "
                "are not a physics-grade oil-spill forecast.",
            ],
        )


def _seed_points(
    geometry: BaseGeometry, count: int, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    """Uniform rejection sampling inside the seed polygon.

    Area-weighted by construction, so a long thin slick seeds along its whole length
    rather than clustering at the centroid.
    """
    from shapely import contains_xy

    min_lon, min_lat, max_lon, max_lat = geometry.bounds
    lons: list[float] = []
    lats: list[float] = []
    attempts = 0
    max_attempts = count * 200
    while len(lons) < count and attempts < max_attempts:
        batch = max(count, 256)
        candidate_lon = rng.uniform(min_lon, max_lon, batch)
        candidate_lat = rng.uniform(min_lat, max_lat, batch)
        inside = contains_xy(geometry, candidate_lon, candidate_lat)
        lons.extend(candidate_lon[inside].tolist())
        lats.extend(candidate_lat[inside].tolist())
        attempts += batch
    if not lons:
        centroid = geometry.centroid
        return (
            np.full(count, centroid.x, dtype=float),
            np.full(count, centroid.y, dtype=float),
        )
    return np.asarray(lons[:count], dtype=float), np.asarray(lats[:count], dtype=float)


def _sample_field(
    field: EnvironmentalField, when: datetime, lons: np.ndarray, lats: np.ndarray
) -> np.ndarray:
    """Nearest-neighbour lookup in time, bilinear in space.

    Nearest in time is adequate at hourly resolution relative to a 15-minute step, and
    keeps the interpolation cheap enough to run tens of thousands of particles on a CPU.
    """
    values = np.asarray(field.values)
    times = field.times
    if len(times) == 1:
        t_index = 0
    else:
        deltas = [abs((t - when).total_seconds()) for t in times]
        t_index = int(np.argmin(deltas))
    plane = values[t_index]

    lat_axis = np.asarray(field.lats)
    lon_axis = np.asarray(field.lons)
    # np.interp on each axis independently gives a separable bilinear sample, which is
    # exact for the smooth fields used here and far faster than a full 2-D interpolator.
    lat_idx = np.interp(lats, lat_axis, np.arange(lat_axis.size))
    lon_idx = np.interp(lons, lon_axis, np.arange(lon_axis.size))
    lat0 = np.clip(np.floor(lat_idx).astype(int), 0, lat_axis.size - 1)
    lon0 = np.clip(np.floor(lon_idx).astype(int), 0, lon_axis.size - 1)
    lat1 = np.clip(lat0 + 1, 0, lat_axis.size - 1)
    lon1 = np.clip(lon0 + 1, 0, lon_axis.size - 1)
    wy = lat_idx - lat0
    wx = lon_idx - lon0
    return (
        plane[lat0, lon0] * (1 - wy) * (1 - wx)
        + plane[lat0, lon1] * (1 - wy) * wx
        + plane[lat1, lon0] * wy * (1 - wx)
        + plane[lat1, lon1] * wy * wx
    )


def _advect(
    lons: np.ndarray,
    lats: np.ndarray,
    *,
    environment: EnvironmentalBundle,
    when: datetime,
    dt_seconds: float,
    alphas: np.ndarray,
    diffusivity: float,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """One explicit Euler step with an added turbulent random walk."""
    cu = _sample_field(environment.current_u, when, lons, lats)
    cv = _sample_field(environment.current_v, when, lons, lats)
    wu = _sample_field(environment.wind_u, when, lons, lats)
    wv = _sample_field(environment.wind_v, when, lons, lats)

    u = cu + alphas * wu
    v = cv + alphas * wv

    # Random-walk step for eddy diffusivity K: sigma = sqrt(2*K*|dt|).  The sign of dt
    # does not affect the diffusion magnitude — diffusion is not reversible, which is
    # exactly why a backward run yields a *region* rather than a point (CON-008).
    sigma = math.sqrt(2.0 * max(0.0, diffusivity) * abs(dt_seconds))
    du = rng.normal(0.0, sigma, size=lons.shape)
    dv = rng.normal(0.0, sigma, size=lats.shape)

    dx = u * dt_seconds + du
    dy = v * dt_seconds + dv

    new_lats = lats + dy / METRES_PER_DEGREE_LAT
    metres_per_degree_lon = METRES_PER_DEGREE_LAT * np.cos(np.radians(np.clip(lats, -89.9, 89.9)))
    metres_per_degree_lon = np.where(
        np.abs(metres_per_degree_lon) < 1.0, 1.0, metres_per_degree_lon
    )
    new_lons = lons + dx / metres_per_degree_lon

    return np.clip(new_lons, -180.0, 180.0), np.clip(new_lats, -90.0, 90.0)


__all__ = [
    "DEFAULT_DIFFUSIVITY_M2_S",
    "DEFAULT_WIND_DRIFT_FACTOR",
    "DEFAULT_WIND_DRIFT_SIGMA",
    "AnalyticalDriftEngine",
]
