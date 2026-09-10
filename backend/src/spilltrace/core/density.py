"""Particle density → origin probability region (FR-010, CON-008).

The output is deliberately a set of **nested probability contours**, not a point.  A
backward drift run cannot resolve a discharge coordinate: diffusion is irreversible, the
wind drift factor is uncertain, and the forcing fields are themselves interpolated.  The
honest representation of that is an area with a stated probability mass.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.ops import unary_union

#: Probability mass enclosed by each contour, highest confidence last.
DEFAULT_CONTOUR_LEVELS: tuple[float, ...] = (0.50, 0.75, 0.90)


@dataclass(slots=True)
class DensityGrid:
    """A normalised probability density over a regular lon/lat grid."""

    values: np.ndarray  # [lat, lon], sums to 1.0
    lons: np.ndarray  # cell centres
    lats: np.ndarray  # cell centres
    resolution_deg: float

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        half = self.resolution_deg / 2.0
        return (
            float(self.lons.min() - half),
            float(self.lats.min() - half),
            float(self.lons.max() + half),
            float(self.lats.max() + half),
        )


def particle_density(
    lons: np.ndarray,
    lats: np.ndarray,
    *,
    resolution_deg: float = 0.01,
    smoothing_cells: float = 1.5,
    padding_cells: int = 8,
) -> DensityGrid:
    """2-D histogram of particle positions, Gaussian-smoothed and normalised.

    Smoothing is a kernel density estimate in all but name: raw histogram counts of a
    finite particle ensemble are noisy, and contouring noise would produce ragged,
    over-confident region boundaries.
    """
    if lons.size == 0:
        raise ValueError("Cannot compute a density from zero particles.")

    pad = padding_cells * resolution_deg
    min_lon, max_lon = float(lons.min()) - pad, float(lons.max()) + pad
    min_lat, max_lat = float(lats.min()) - pad, float(lats.max()) + pad

    n_lon = max(4, math.ceil((max_lon - min_lon) / resolution_deg))
    n_lat = max(4, math.ceil((max_lat - min_lat) / resolution_deg))

    counts, lat_edges, lon_edges = np.histogram2d(
        lats, lons, bins=[n_lat, n_lon], range=[[min_lat, max_lat], [min_lon, max_lon]]
    )
    smoothed = _gaussian_blur(counts.astype(np.float64), sigma=smoothing_cells)
    total = smoothed.sum()
    if total <= 0:
        raise ValueError("Particle density is degenerate (all mass smoothed away).")
    smoothed /= total

    return DensityGrid(
        values=smoothed,
        lons=(lon_edges[:-1] + lon_edges[1:]) / 2.0,
        lats=(lat_edges[:-1] + lat_edges[1:]) / 2.0,
        resolution_deg=resolution_deg,
    )


def _gaussian_blur(grid: np.ndarray, *, sigma: float) -> np.ndarray:
    """Separable Gaussian blur.

    Implemented directly rather than via scipy.ndimage so the density path has no
    optional dependency and behaves identically everywhere.
    """
    if sigma <= 0:
        return grid
    radius = max(1, math.ceil(3.0 * sigma))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-(x**2) / (2.0 * sigma**2))
    kernel /= kernel.sum()

    padded = np.pad(grid, ((0, 0), (radius, radius)), mode="constant")
    blurred = np.apply_along_axis(lambda row: np.convolve(row, kernel, mode="valid"), 1, padded)
    padded = np.pad(blurred, ((radius, radius), (0, 0)), mode="constant")
    return np.apply_along_axis(lambda col: np.convolve(col, kernel, mode="valid"), 0, padded)


def density_threshold_for_mass(grid: DensityGrid, mass: float) -> float:
    """The density value whose super-level set contains ``mass`` of the probability.

    Sorting cells by density and walking down the cumulative sum is the standard
    "highest posterior density region" construction: it yields the *smallest* area
    containing the requested probability, which is the tightest honest statement.
    """
    flat = np.sort(grid.values.ravel())[::-1]
    cumulative = np.cumsum(flat)
    index = int(np.searchsorted(cumulative, min(max(mass, 0.0), 1.0)))
    index = min(index, flat.size - 1)
    return float(flat[index])


def contour_polygons(grid: DensityGrid, threshold: float) -> MultiPolygon:
    """Polygonise the region where density ≥ ``threshold``.

    Marching squares would give smoother boundaries, but a cell-union is exact with
    respect to the grid the probability mass was actually computed on — the polygon and
    the number attached to it describe the same set of cells.
    """
    mask = grid.values >= threshold
    if not mask.any():
        return MultiPolygon()

    half = grid.resolution_deg / 2.0
    cells: list[Polygon] = []
    lat_indices, lon_indices = np.nonzero(mask)
    for lat_i, lon_i in zip(lat_indices, lon_indices, strict=True):
        lon_c = float(grid.lons[lon_i])
        lat_c = float(grid.lats[lat_i])
        cells.append(
            Polygon(
                [
                    (lon_c - half, lat_c - half),
                    (lon_c + half, lat_c - half),
                    (lon_c + half, lat_c + half),
                    (lon_c - half, lat_c + half),
                ]
            )
        )
    merged = unary_union(cells)
    if merged.is_empty:
        return MultiPolygon()
    if isinstance(merged, Polygon):
        return MultiPolygon([merged])
    return MultiPolygon([g for g in merged.geoms if isinstance(g, Polygon)])


def probability_contours(
    grid: DensityGrid, levels: tuple[float, ...] = DEFAULT_CONTOUR_LEVELS
) -> list[tuple[float, MultiPolygon]]:
    """Nested contours ordered outer → inner (largest area first).

    Each region is the *smallest* area containing that much probability mass, so the
    90% region contains the 75% region contains the 50% region.  The order matches how
    the map stacks them: the widest, least certain region underneath.
    """
    out: list[tuple[float, MultiPolygon]] = []
    for level in sorted(levels, reverse=True):
        threshold = density_threshold_for_mass(grid, level)
        polygons = contour_polygons(grid, threshold)
        if not polygons.is_empty:
            out.append((level, polygons))
    return out


def contours_to_geojson(contours: list[tuple[float, MultiPolygon]]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(geometry),
                "properties": {
                    "probability_mass": level,
                    "label": f"{round(level * 100)}% probability region",
                },
            }
            for level, geometry in contours
        ],
    }


def containing_probability(
    contours: list[tuple[float, MultiPolygon]], lon: float, lat: float
) -> float | None:
    """The tightest contour containing a point, expressed as its probability mass.

    Used by the origin-proximity factor: "inside the 50% region" is much stronger
    evidence than "inside the 90% region", and the score must reflect that.
    """
    from shapely.geometry import Point

    point = Point(lon, lat)
    best: float | None = None
    for level, geometry in contours:
        if geometry.covers(point) and (best is None or level < best):
            best = level
    return best


__all__ = [
    "DEFAULT_CONTOUR_LEVELS",
    "DensityGrid",
    "containing_probability",
    "contour_polygons",
    "contours_to_geojson",
    "density_threshold_for_mass",
    "particle_density",
    "probability_contours",
]
