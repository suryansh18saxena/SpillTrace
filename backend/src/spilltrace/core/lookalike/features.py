"""Feature extraction for look-alike discrimination.

The feature groups follow the operational literature (Topouzelis 2008, *Sensors*, and
the 2021 SAR oil-spill meta-analysis): geometric, backscatter-statistical, border
gradient, and contextual.  Names are kept close to the published ones so a reviewer can
map our numbers onto theirs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from shapely.geometry.base import BaseGeometry

from spilltrace.core.geometry import geodesic_area_km2, geodesic_perimeter_km


@dataclass(slots=True)
class SlickFeatures:
    """Everything the rule engine reasons about, in one inspectable object."""

    # --- geometric ---
    area_km2: float
    perimeter_km: float
    complexity: float  # P / (2*sqrt(pi*A)); 1.0 for a circle
    compactness: float  # 1 / complexity
    elongation: float  # bounding-box aspect ratio of the principal axes
    part_count: int

    # --- backscatter / statistical ---
    slick_mean_db: float | None = None
    slick_std_db: float | None = None
    background_mean_db: float | None = None
    background_std_db: float | None = None
    contrast_db: float | None = None  # background - slick (positive = darker slick)
    power_to_mean_ratio: float | None = None  # Opm/Bpm, the classic discriminator

    # --- border ---
    gradient_mean: float | None = None
    gradient_max: float | None = None

    # --- environmental context ---
    wind_speed_ms: float | None = None
    wind_direction_deg: float | None = None
    wind_source: str | None = None

    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "area_km2": self.area_km2,
            "perimeter_km": self.perimeter_km,
            "complexity": self.complexity,
            "compactness": self.compactness,
            "elongation": self.elongation,
            "part_count": self.part_count,
            "slick_mean_db": self.slick_mean_db,
            "slick_std_db": self.slick_std_db,
            "background_mean_db": self.background_mean_db,
            "background_std_db": self.background_std_db,
            "contrast_db": self.contrast_db,
            "power_to_mean_ratio": self.power_to_mean_ratio,
            "gradient_mean": self.gradient_mean,
            "gradient_max": self.gradient_max,
            "wind_speed_ms": self.wind_speed_ms,
            "wind_direction_deg": self.wind_direction_deg,
            "wind_source": self.wind_source,
            **self.extra,
        }


def geometric_features(geometry: BaseGeometry) -> dict[str, float]:
    """Area, perimeter and the shape descriptors, all geodesic.

    Complexity is the isoperimetric ratio: 1.0 for a perfect circle, rising with
    boundary irregularity.  It separates the long, ragged trail of a discharge from the
    smooth, rounded patch a low-wind zone produces.
    """
    area = geodesic_area_km2(geometry)
    perimeter = geodesic_perimeter_km(geometry)
    complexity = perimeter / (2.0 * math.sqrt(math.pi * area)) if area > 0 else 0.0
    elongation = _principal_axis_ratio(geometry)
    part_count = len(getattr(geometry, "geoms", [geometry]))
    return {
        "area_km2": round(area, 4),
        "perimeter_km": round(perimeter, 4),
        "complexity": round(complexity, 4),
        "compactness": round(1.0 / complexity, 4) if complexity > 0 else 0.0,
        "elongation": round(elongation, 4),
        "part_count": part_count,
    }


def _principal_axis_ratio(geometry: BaseGeometry) -> float:
    """Aspect ratio of the minimum rotated rectangle.

    Preferred over the axis-aligned bounding box because a slick oriented at 45° would
    otherwise read as almost circular.
    """
    try:
        rect = geometry.minimum_rotated_rectangle
        coords = list(rect.exterior.coords)[:4]
    except (AttributeError, IndexError, ValueError):
        min_x, min_y, max_x, max_y = geometry.bounds
        width = max(max_x - min_x, 1e-9)
        height = max(max_y - min_y, 1e-9)
        return max(width, height) / min(width, height)

    def edge(a: tuple[float, float], b: tuple[float, float]) -> float:
        # Degrees are fine here: this is a ratio of two lengths at the same latitude,
        # and the cos(lat) scaling cancels to first order.
        return math.hypot(b[0] - a[0], (b[1] - a[1]))

    side_a = edge(coords[0], coords[1])
    side_b = edge(coords[1], coords[2])
    longer, shorter = max(side_a, side_b), min(side_a, side_b)
    return longer / shorter if shorter > 1e-12 else 1.0


def backscatter_features(
    slick_values_db: np.ndarray, background_values_db: np.ndarray
) -> dict[str, float]:
    """Contrast statistics between the slick and its surrounding sea.

    ``contrast_db`` is *background minus slick*, so a genuine slick — which is darker
    than the sea around it — gives a positive number.  The power-to-mean ratio
    (variance / mean², computed in linear power) is the classic Solberg-lineage
    discriminator: oil suppresses backscatter uniformly and so has a *lower* relative
    variance than a wind-shadow patch of the same mean brightness.
    """
    slick = np.asarray(slick_values_db, dtype=np.float64).ravel()
    background = np.asarray(background_values_db, dtype=np.float64).ravel()
    slick = slick[np.isfinite(slick)]
    background = background[np.isfinite(background)]
    if slick.size == 0 or background.size == 0:
        return {}

    slick_mean = float(slick.mean())
    background_mean = float(background.mean())

    slick_power = np.power(10.0, slick / 10.0)
    background_power = np.power(10.0, background / 10.0)
    opm = float(slick_power.var() / max(1e-12, slick_power.mean() ** 2))
    bpm = float(background_power.var() / max(1e-12, background_power.mean() ** 2))

    return {
        "slick_mean_db": round(slick_mean, 4),
        "slick_std_db": round(float(slick.std()), 4),
        "background_mean_db": round(background_mean, 4),
        "background_std_db": round(float(background.std()), 4),
        "contrast_db": round(background_mean - slick_mean, 4),
        "power_to_mean_ratio": round(opm / bpm, 4) if bpm > 1e-12 else 0.0,
    }


def border_gradient(probability_grid: np.ndarray) -> dict[str, float]:
    """Sharpness of the slick boundary.

    Oil has a sharp, well-defined edge; a low-wind zone fades gradually into the
    surrounding sea.  Measured on the probability field because that is what is always
    available, whether or not the original raster was retained.
    """
    grid = np.asarray(probability_grid, dtype=np.float64)
    if grid.ndim != 2 or grid.size < 9:
        return {}
    gy, gx = np.gradient(grid)
    magnitude = np.hypot(gx, gy)
    # Only the transition band carries edge information; interior and open sea are flat.
    band = magnitude[(grid > 0.05) & (grid < 0.95)]
    if band.size == 0:
        return {"gradient_mean": 0.0, "gradient_max": round(float(magnitude.max()), 6)}
    return {
        "gradient_mean": round(float(band.mean()), 6),
        "gradient_max": round(float(magnitude.max()), 6),
    }


def extract_features(
    geometry: BaseGeometry,
    *,
    probability_grid: np.ndarray | None = None,
    slick_values_db: np.ndarray | None = None,
    background_values_db: np.ndarray | None = None,
    wind_speed_ms: float | None = None,
    wind_direction_deg: float | None = None,
    wind_source: str | None = None,
) -> SlickFeatures:
    values: dict[str, Any] = geometric_features(geometry)
    if slick_values_db is not None and background_values_db is not None:
        values.update(backscatter_features(slick_values_db, background_values_db))
    if probability_grid is not None:
        values.update(border_gradient(probability_grid))
    values.update(
        wind_speed_ms=wind_speed_ms,
        wind_direction_deg=wind_direction_deg,
        wind_source=wind_source,
    )
    known = set(SlickFeatures.__dataclass_fields__) - {"extra"}
    extra = {k: v for k, v in values.items() if k not in known}
    return SlickFeatures(**{k: v for k, v in values.items() if k in known}, extra=extra)


__all__ = [
    "SlickFeatures",
    "backscatter_features",
    "border_gradient",
    "extract_features",
    "geometric_features",
]
