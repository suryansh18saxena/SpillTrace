"""Mask → ``MultiPolygon(4326)`` with geodesic area and perimeter (FR-005, DB-003).

Two things are easy to get wrong here and both are corrected in this module.

**Area must not be computed in degrees.**  Storage is EPSG:4326, and ``shapely.area`` on
a 4326 geometry returns square degrees, which is not an area — a square degree is about
12 300 km² at the equator and 0 at the pole.  Every measurement here goes through
``core.geometry``'s geodesic helpers.

**Holes are real.**  ``rasterio.features.shapes`` yields a polygon's interior rings, and
a slick with a clear patch in the middle genuinely has one.  The rings are preserved
rather than dissolved, so the reported area is the area of oil, not of its outline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from rasterio.features import shapes as raster_shapes
from rasterio.transform import Affine
from shapely.geometry import MultiPolygon, Point, Polygon, shape

from spilltrace.core.confidence import detection_confidence
from spilltrace.core.geometry import (
    WGS84,
    as_multipolygon,
    geodesic_area_km2,
    geodesic_perimeter_km,
)

#: Rings smaller than this are rasterisation noise, not geometry.
MIN_RING_VERTICES = 4


@dataclass(frozen=True, slots=True)
class DetectedPolygon:
    """One retained connected component, measured on the ellipsoid."""

    label: int
    polygon: Polygon
    area_km2: float
    perimeter_km: float
    pixel_count: int
    mean_probability: float
    max_probability: float

    @property
    def centroid(self) -> Point:
        return self.polygon.centroid

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "area_km2": round(self.area_km2, 6),
            "perimeter_km": round(self.perimeter_km, 6),
            "pixel_count": self.pixel_count,
            "mean_probability": round(self.mean_probability, 4),
            "max_probability": round(self.max_probability, 4),
        }


@dataclass(frozen=True, slots=True)
class PolygonizationResult:
    multipolygon: MultiPolygon
    polygons: tuple[DetectedPolygon, ...]
    area_km2: float
    perimeter_km: float
    pixel_count: int
    detection_confidence: float
    max_probability: float
    crs: str = WGS84

    @property
    def is_empty(self) -> bool:
        return not self.polygons

    def to_dict(self) -> dict[str, Any]:
        return {
            "crs": self.crs,
            "polygon_count": len(self.polygons),
            "area_km2": round(self.area_km2, 6),
            "perimeter_km": round(self.perimeter_km, 6),
            "pixel_count": self.pixel_count,
            "detection_confidence": self.detection_confidence,
            "max_probability": round(self.max_probability, 4),
            "polygons": [p.to_dict() for p in self.polygons],
        }


def as_affine(transform: Affine | tuple[float, ...] | list[float]) -> Affine:
    """Accept a rasterio ``Affine`` or its six-tuple form."""
    if isinstance(transform, Affine):
        return transform
    values = tuple(float(v) for v in transform)
    if len(values) not in (6, 9):
        raise ValueError(f"An affine transform needs six coefficients, got {len(values)}.")
    return Affine(*values[:6])


def polygonize_mask(
    mask: np.ndarray,
    *,
    transform: Affine | tuple[float, ...] | list[float],
    probability: np.ndarray | None = None,
    labels: np.ndarray | None = None,
    min_area_km2: float = 0.0,
    simplify_pixels: float = 0.0,
) -> PolygonizationResult:
    """Vectorise a boolean mask into geodesically-measured polygons.

    ``labels`` keeps touching-but-distinct components apart; without it, two slicks that
    share a diagonal pixel would be reported as one.  ``simplify_pixels`` is expressed in
    pixels rather than degrees so the tolerance means the same thing at any latitude.
    """
    boolean = np.asarray(mask, dtype=bool)
    if boolean.ndim != 2:
        raise ValueError(f"Expected a 2-D mask, got {boolean.ndim} dimensions.")
    affine = as_affine(transform)

    if labels is None:
        from spilltrace.core.masking import filter_small_components

        _, labels, _ = filter_small_components(boolean, min_area_px=1)
    label_array = np.asarray(labels, dtype=np.int32)

    probabilities = (
        np.asarray(probability, dtype=np.float32)
        if probability is not None
        else boolean.astype(np.float32)
    )
    tolerance = abs(affine.a) * simplify_pixels if simplify_pixels > 0 else 0.0

    detected: list[DetectedPolygon] = []
    for geom, value in raster_shapes(label_array, mask=boolean, transform=affine):
        label = int(value)
        if label <= 0:
            continue
        polygon = shape(geom)
        if not isinstance(polygon, Polygon) or polygon.is_empty:
            continue
        if len(polygon.exterior.coords) < MIN_RING_VERTICES:
            continue
        if tolerance > 0:
            simplified = polygon.simplify(tolerance, preserve_topology=True)
            if isinstance(simplified, Polygon) and not simplified.is_empty:
                polygon = simplified
        if not polygon.is_valid:
            repaired = polygon.buffer(0)
            if not isinstance(repaired, Polygon) or repaired.is_empty:
                continue
            polygon = repaired

        area = geodesic_area_km2(polygon)
        if area < min_area_km2:
            continue
        component = label_array == label
        values = probabilities[component]
        detected.append(
            DetectedPolygon(
                label=label,
                polygon=polygon,
                area_km2=area,
                perimeter_km=geodesic_perimeter_km(polygon),
                pixel_count=int(component.sum()),
                mean_probability=float(values.mean()) if values.size else 0.0,
                max_probability=float(values.max()) if values.size else 0.0,
            )
        )

    # Largest first: the detection an analyst opens is the one that dominates the scene.
    detected.sort(key=lambda item: item.area_km2, reverse=True)
    multipolygon = (
        as_multipolygon(MultiPolygon([item.polygon for item in detected]))
        if detected
        else MultiPolygon()
    )
    return PolygonizationResult(
        multipolygon=multipolygon,
        polygons=tuple(detected),
        area_km2=sum(item.area_km2 for item in detected),
        perimeter_km=sum(item.perimeter_km for item in detected),
        pixel_count=sum(item.pixel_count for item in detected),
        detection_confidence=detection_confidence(detected),
        max_probability=max((item.max_probability for item in detected), default=0.0),
    )


def transform_for_bounds(
    bounds: tuple[float, float, float, float], width: int, height: int
) -> Affine:
    """The affine a raster covering ``bounds`` at ``width × height`` has."""
    from rasterio.transform import from_bounds

    return from_bounds(*bounds, width=width, height=height)


__all__ = [
    "MIN_RING_VERTICES",
    "DetectedPolygon",
    "PolygonizationResult",
    "as_affine",
    "polygonize_mask",
    "transform_for_bounds",
]
