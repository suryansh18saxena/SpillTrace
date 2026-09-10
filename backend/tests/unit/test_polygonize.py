"""Polygonisation, geodesic measurement and the definition of detection confidence.

The area assertions are checked against an independently computed value rather than
against the function's own output, because the whole point of this module is that
``shapely.area`` on an EPSG:4326 geometry is *not* an area.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from rasterio.transform import from_bounds
from shapely.geometry import MultiPolygon, box

from spilltrace.core.confidence import (
    DETECTION_CONFIDENCE_DEFINITION,
    ConfidenceComponent,
    confidence_manifest,
    detection_confidence,
)
from spilltrace.core.geometry import geodesic_area_km2
from spilltrace.core.polygonize import as_affine, polygonize_mask, transform_for_bounds

BOUNDS = (68.0, 21.0, 69.0, 22.0)
SIZE = 100
TRANSFORM = from_bounds(*BOUNDS, width=SIZE, height=SIZE)


def _rect_mask(row0: int, row1: int, col0: int, col1: int) -> np.ndarray:
    mask = np.zeros((SIZE, SIZE), dtype=bool)
    mask[row0:row1, col0:col1] = True
    return mask


# --------------------------------------------------------------------------- geometry
def test_a_rectangle_becomes_one_polygon_with_the_right_corners() -> None:
    result = polygonize_mask(_rect_mask(10, 30, 20, 50), transform=TRANSFORM)
    assert len(result.polygons) == 1
    minx, miny, maxx, maxy = result.polygons[0].polygon.bounds
    assert minx == pytest.approx(68.0 + 20 / SIZE)
    assert maxx == pytest.approx(68.0 + 50 / SIZE)
    # Row 0 is the northern edge, so row 10 is *below* the top.
    assert maxy == pytest.approx(22.0 - 10 / SIZE)
    assert miny == pytest.approx(22.0 - 30 / SIZE)


def test_area_is_geodesic_not_square_degrees() -> None:
    mask = _rect_mask(10, 30, 20, 50)
    result = polygonize_mask(mask, transform=TRANSFORM)
    expected = geodesic_area_km2(box(68.2, 22.0 - 0.30, 68.5, 22.0 - 0.10))
    assert result.area_km2 == pytest.approx(expected, rel=1e-6)
    # A degree-space area would be 0.06, which is not a number of square kilometres.
    assert result.area_km2 > 500.0


def test_perimeter_is_geodesic_and_consistent_with_the_area() -> None:
    result = polygonize_mask(_rect_mask(10, 30, 20, 50), transform=TRANSFORM)
    polygon = result.polygons[0]
    # For a rectangle, P >= 2*sqrt(pi*A) with equality only for a circle.
    assert polygon.perimeter_km > 2.0 * math.sqrt(math.pi * polygon.area_km2)
    assert polygon.perimeter_km == pytest.approx(result.perimeter_km)


def test_two_separate_regions_give_two_polygons_in_one_multipolygon() -> None:
    mask = _rect_mask(5, 15, 5, 15) | _rect_mask(60, 80, 60, 85)
    result = polygonize_mask(mask, transform=TRANSFORM)
    assert len(result.polygons) == 2
    assert isinstance(result.multipolygon, MultiPolygon)
    assert len(result.multipolygon.geoms) == 2
    # Largest first: that is the detection an analyst opens.
    assert result.polygons[0].area_km2 >= result.polygons[1].area_km2


def test_an_interior_hole_is_preserved_not_dissolved() -> None:
    mask = _rect_mask(10, 40, 10, 40)
    mask[20:30, 20:30] = False
    result = polygonize_mask(mask, transform=TRANSFORM)
    assert len(result.polygons) == 1
    polygon = result.polygons[0].polygon
    assert len(polygon.interiors) == 1
    solid = polygonize_mask(_rect_mask(10, 40, 10, 40), transform=TRANSFORM)
    assert result.area_km2 < solid.area_km2


def test_output_is_wgs84_and_valid() -> None:
    result = polygonize_mask(_rect_mask(10, 30, 20, 50), transform=TRANSFORM)
    assert result.crs == "EPSG:4326"
    assert result.multipolygon.is_valid
    for polygon in result.polygons:
        assert polygon.polygon.is_valid


def test_an_all_zero_mask_yields_an_empty_result() -> None:
    result = polygonize_mask(np.zeros((SIZE, SIZE), dtype=bool), transform=TRANSFORM)
    assert result.is_empty
    assert result.area_km2 == 0.0
    assert result.detection_confidence == 0.0
    assert result.multipolygon.is_empty


def test_min_area_filter_is_applied_in_square_kilometres() -> None:
    mask = _rect_mask(5, 8, 5, 8) | _rect_mask(50, 80, 50, 80)
    unfiltered = polygonize_mask(mask, transform=TRANSFORM)
    assert len(unfiltered.polygons) == 2
    cutoff = unfiltered.polygons[1].area_km2 * 2
    filtered = polygonize_mask(mask, transform=TRANSFORM, min_area_km2=cutoff)
    assert len(filtered.polygons) == 1


def test_simplification_reduces_vertices_without_destroying_the_shape() -> None:
    mask = _rect_mask(10, 60, 10, 60)
    mask[30, 60] = True  # a one-pixel spur
    plain = polygonize_mask(mask, transform=TRANSFORM)
    simplified = polygonize_mask(mask, transform=TRANSFORM, simplify_pixels=2.0)
    assert len(simplified.polygons[0].polygon.exterior.coords) <= len(
        plain.polygons[0].polygon.exterior.coords
    )
    assert simplified.area_km2 == pytest.approx(plain.area_km2, rel=0.05)


def test_labels_keep_diagonally_touching_regions_separate() -> None:
    mask = np.zeros((SIZE, SIZE), dtype=bool)
    mask[10:20, 10:20] = True
    mask[20:30, 20:30] = True  # touches the first only at a corner
    labels = np.zeros((SIZE, SIZE), dtype=np.int32)
    labels[10:20, 10:20] = 1
    labels[20:30, 20:30] = 2
    result = polygonize_mask(mask, transform=TRANSFORM, labels=labels)
    assert len(result.polygons) == 2


def test_a_two_dimensional_mask_is_required() -> None:
    with pytest.raises(ValueError, match="2-D mask"):
        polygonize_mask(np.zeros((2, 10, 10), dtype=bool), transform=TRANSFORM)


def test_affine_accepts_a_six_tuple() -> None:
    assert as_affine(tuple(TRANSFORM)[:6]) == TRANSFORM
    assert transform_for_bounds(BOUNDS, SIZE, SIZE) == TRANSFORM
    with pytest.raises(ValueError, match="six"):
        as_affine((1.0, 2.0, 3.0))


# --------------------------------------------------------------------------- confidence
def test_detection_confidence_is_the_area_weighted_mean_probability() -> None:
    components = [
        ConfidenceComponent(area_km2=90.0, mean_probability=0.9),
        ConfidenceComponent(area_km2=10.0, mean_probability=0.4),
    ]
    assert detection_confidence(components) == pytest.approx(0.85)
    # A plain mean would be 0.65: the small fragment must not count as much as the trail.
    assert detection_confidence(components) != pytest.approx(0.65)


def test_detection_confidence_of_nothing_is_zero() -> None:
    assert detection_confidence([]) == 0.0


def test_detection_confidence_falls_back_to_an_unweighted_mean_at_zero_area() -> None:
    components = [
        ConfidenceComponent(area_km2=0.0, mean_probability=0.8),
        ConfidenceComponent(area_km2=0.0, mean_probability=0.6),
    ]
    assert detection_confidence(components) == pytest.approx(0.7)


def test_detection_confidence_is_clamped_to_the_unit_interval() -> None:
    assert detection_confidence([ConfidenceComponent(1.0, 1.7)]) == 1.0
    assert detection_confidence([ConfidenceComponent(1.0, -0.5)]) == 0.0


def test_polygonized_confidence_uses_the_probability_raster() -> None:
    mask = _rect_mask(10, 40, 10, 40) | _rect_mask(60, 70, 60, 70)
    probability = np.zeros((SIZE, SIZE), dtype=np.float32)
    probability[10:40, 10:40] = 0.9
    probability[60:70, 60:70] = 0.4
    result = polygonize_mask(mask, transform=TRANSFORM, probability=probability)
    big, small = result.polygons
    expected = (big.area_km2 * 0.9 + small.area_km2 * 0.4) / (big.area_km2 + small.area_km2)
    assert result.detection_confidence == pytest.approx(round(expected, 4), abs=1e-4)
    assert result.max_probability == pytest.approx(0.9)


def test_the_definition_is_documented_and_says_it_is_never_combined() -> None:
    assert "area-weighted" in DETECTION_CONFIDENCE_DEFINITION.lower()
    manifest = confidence_manifest(0.5)["detection_confidence"]
    assert manifest["combined_with_other_confidences"] is False
    assert manifest["threshold"] == 0.5
    assert "AD-28" in manifest["reference"]
