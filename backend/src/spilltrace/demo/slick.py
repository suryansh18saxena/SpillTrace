"""Synthetic slick geometry and oil-probability raster.

Shape matters here.  An operational discharge produces a long, thin, slightly sinuous
feature aligned with the vessel's track — not a blob.  Getting that right means the
look-alike verification stage sees realistic elongation and complexity values instead of
numbers that trivially pass.
"""

from __future__ import annotations

import math

import numpy as np
from shapely.geometry import MultiPolygon, Polygon

from spilltrace.core.geometry import destination_point, geodesic_area_km2


def synthetic_slick(
    *,
    centre: tuple[float, float],
    length_km: float,
    width_km: float,
    bearing_deg: float,
    seed: int,
    vertices_per_side: int = 40,
) -> MultiPolygon:
    """A ribbon-shaped slick with an irregular boundary.

    Built as a centreline with a slow lateral meander, then offset to both sides by a
    width profile that tapers at the ends — a discharge trail is widest where the oil has
    had longest to spread and narrowest at the fresh end.
    """
    rng = np.random.default_rng(seed)
    lon0, lat0 = centre

    # Centreline, from one end to the other through the centre.
    half = length_km / 2.0
    along = np.linspace(-half, half, vertices_per_side)

    # Meander: two low-frequency sinusoids so the line curves without looking synthetic.
    phase = rng.uniform(0, 2 * math.pi, size=2)
    amp = width_km * rng.uniform(0.5, 0.9)
    lateral = amp * (
        0.6 * np.sin(2 * math.pi * along / (length_km * 0.8) + phase[0])
        + 0.4 * np.sin(2 * math.pi * along / (length_km * 0.31) + phase[1])
    )

    # Width profile: taper to ~25% at both ends, widest just past the middle.
    t = (along + half) / length_km
    width_profile = width_km * (0.25 + 0.75 * np.sin(np.pi * np.clip(t, 0, 1)) ** 0.7)
    width_profile *= 1.0 + rng.normal(0, 0.06, size=width_profile.shape)

    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    for d_along, d_lat, w in zip(along, lateral, width_profile, strict=True):
        # Move along the slick axis, then offset perpendicular to it.
        cx, cy = destination_point(lon0, lat0, bearing_deg, d_along * 1000.0)
        cx, cy = destination_point(cx, cy, (bearing_deg + 90.0) % 360.0, d_lat * 1000.0)
        lx, ly = destination_point(cx, cy, (bearing_deg + 90.0) % 360.0, (w / 2.0) * 1000.0)
        rx, ry = destination_point(cx, cy, (bearing_deg - 90.0) % 360.0, (w / 2.0) * 1000.0)
        left.append((lx, ly))
        right.append((rx, ry))

    ring = [*left, *reversed(right), left[0]]
    polygon = Polygon(ring)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if isinstance(polygon, MultiPolygon):
        return polygon
    return MultiPolygon([polygon])


def probability_grid(
    geometry: MultiPolygon,
    *,
    seed: int,
    resolution_deg: float = 0.002,
    padding_deg: float = 0.05,
) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """A per-pixel oil-probability raster consistent with ``geometry``.

    Probability is high inside the polygon, decays across its boundary, and carries
    speckle-like noise so the downstream statistics are not degenerate.
    Returns ``(array, (min_lon, min_lat, max_lon, max_lat))``.
    """
    rng = np.random.default_rng(seed + 977)
    min_lon, min_lat, max_lon, max_lat = geometry.bounds
    min_lon -= padding_deg
    min_lat -= padding_deg
    max_lon += padding_deg
    max_lat += padding_deg

    lons = np.arange(min_lon, max_lon, resolution_deg)
    lats = np.arange(max_lat, min_lat, -resolution_deg)
    grid: np.ndarray = np.zeros((lats.size, lons.size), dtype=np.float32)

    # Rasterise by point-in-polygon on a coarse stride, then smooth: much cheaper than a
    # full GDAL rasterise and entirely adequate for a demonstration raster.
    from shapely import contains_xy
    from shapely.geometry import box

    lon_mesh, lat_mesh = np.meshgrid(lons, lats)
    inside = contains_xy(geometry, lon_mesh, lat_mesh)
    grid[inside] = 1.0

    # Soften the edge over ~3 pixels using a separable box blur applied twice.
    for _ in range(3):
        padded = np.pad(grid, 1, mode="edge")
        grid = (
            padded[:-2, 1:-1]
            + padded[2:, 1:-1]
            + padded[1:-1, :-2]
            + padded[1:-1, 2:]
            + 2.0 * padded[1:-1, 1:-1]
        ) / 6.0

    grid = np.clip(grid * 0.94 + rng.normal(0.0, 0.02, grid.shape).astype(np.float32), 0.0, 1.0)
    # Suppress background noise so the map does not look like static.
    grid[grid < 0.08] = 0.0
    assert box(min_lon, min_lat, max_lon, max_lat).is_valid
    return grid.astype(np.float32), (min_lon, min_lat, max_lon, max_lat)


def slick_metrics(geometry: MultiPolygon) -> dict[str, float]:
    """Geodesic area, perimeter and the shape descriptors verification will use."""
    from spilltrace.core.geometry import geodesic_perimeter_km

    area = geodesic_area_km2(geometry)
    perimeter = geodesic_perimeter_km(geometry)
    # Complexity (P / (2*sqrt(pi*A))) is 1 for a circle and grows with boundary
    # irregularity; oil trails sit well above 1, low-wind patches near it.
    complexity = perimeter / (2.0 * math.sqrt(math.pi * area)) if area > 0 else 0.0
    min_lon, min_lat, max_lon, max_lat = geometry.bounds
    span_x = max(max_lon - min_lon, 1e-9)
    span_y = max(max_lat - min_lat, 1e-9)
    elongation = max(span_x, span_y) / min(span_x, span_y)
    return {
        "area_km2": round(area, 4),
        "perimeter_km": round(perimeter, 4),
        "complexity": round(complexity, 4),
        "compactness": round(1.0 / complexity if complexity else 0.0, 4),
        "elongation": round(elongation, 4),
    }


__all__ = ["probability_grid", "slick_metrics", "synthetic_slick"]
