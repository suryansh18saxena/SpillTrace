"""Geodesy helpers.

The failure mode these guard against is measuring in degrees: a degree of longitude is
111 km at the equator and 103 km in the Gulf of Kutch, so any distance or area computed
from raw coordinates is wrong by an amount that varies with latitude.
"""

from __future__ import annotations

import math

import pytest
from shapely.geometry import LineString, MultiPolygon, Point, Polygon

from spilltrace.core.errors import InvalidGeometryError
from spilltrace.core.geometry import (
    angular_difference_deg,
    as_multipolygon,
    bbox_of,
    bbox_polygon,
    buffer_m,
    destination_point,
    geodesic_area_km2,
    geodesic_distance_m,
    geodesic_length_km,
    haversine_m,
    initial_bearing_deg,
    knots_to_ms,
    ms_to_knots,
    point_to_geometry_distance_km,
    validate_polygon,
)

KUTCH = (69.42, 22.44)


class TestDistance:
    def test_zero_distance(self) -> None:
        assert geodesic_distance_m(*KUTCH, *KUTCH) == pytest.approx(0.0, abs=1e-6)

    def test_one_degree_of_latitude_is_about_111km(self) -> None:
        metres = geodesic_distance_m(69.0, 22.0, 69.0, 23.0)
        assert 110_500 < metres < 111_100

    def test_one_degree_of_longitude_shrinks_with_latitude(self) -> None:
        at_equator = geodesic_distance_m(69.0, 0.0, 70.0, 0.0)
        at_kutch = geodesic_distance_m(69.0, 22.44, 70.0, 22.44)
        assert at_kutch < at_equator
        # cos(22.44 deg) = 0.924
        assert at_kutch / at_equator == pytest.approx(math.cos(math.radians(22.44)), rel=1e-3)

    def test_haversine_agrees_with_geodesic_within_ais_accuracy(self) -> None:
        # The spherical approximation is used on the AIS hot path; it must be well
        # inside AIS positional accuracy over the distances between consecutive fixes.
        a, b = (69.40, 22.40), (69.45, 22.43)
        spherical = haversine_m(*a, *b)
        ellipsoidal = geodesic_distance_m(*a, *b)
        assert abs(spherical - ellipsoidal) < 0.005 * ellipsoidal

    def test_destination_point_round_trips(self) -> None:
        lon, lat = destination_point(*KUTCH, 118.0, 42_000.0)
        assert geodesic_distance_m(*KUTCH, lon, lat) == pytest.approx(42_000.0, rel=1e-6)
        assert initial_bearing_deg(*KUTCH, lon, lat) == pytest.approx(118.0, abs=1e-6)


class TestBearing:
    @pytest.mark.parametrize(
        ("a", "b", "expected"),
        [
            (0.0, 10.0, 10.0),
            (350.0, 10.0, 20.0),
            (10.0, 350.0, 20.0),
            (0.0, 180.0, 180.0),
            (90.0, 270.0, 180.0),
            (45.0, 45.0, 0.0),
        ],
    )
    def test_angular_difference_wraps(self, a: float, b: float, expected: float) -> None:
        assert angular_difference_deg(a, b) == pytest.approx(expected)

    def test_angular_difference_never_exceeds_180(self) -> None:
        for a in range(0, 360, 7):
            for b in range(0, 360, 11):
                assert 0.0 <= angular_difference_deg(float(a), float(b)) <= 180.0

    def test_bearing_is_normalised(self) -> None:
        assert 0.0 <= initial_bearing_deg(69.0, 22.0, 68.0, 21.0) < 360.0


class TestArea:
    def test_area_of_a_known_box(self) -> None:
        # 0.1 deg lat x 0.1 deg lon at 22.44 N: 11.06 km x 10.29 km ~= 113.8 km2
        polygon = bbox_polygon(69.0, 22.40, 69.1, 22.50)
        assert geodesic_area_km2(polygon) == pytest.approx(114.0, rel=0.02)

    def test_area_is_orientation_independent(self) -> None:
        ring = [(69.0, 22.4), (69.1, 22.4), (69.1, 22.5), (69.0, 22.5), (69.0, 22.4)]
        assert geodesic_area_km2(Polygon(ring)) == pytest.approx(
            geodesic_area_km2(Polygon(list(reversed(ring)))), rel=1e-9
        )

    def test_empty_geometry_has_zero_area(self) -> None:
        assert geodesic_area_km2(Polygon()) == 0.0

    def test_line_length(self) -> None:
        line = LineString([(69.0, 22.0), (69.0, 22.5), (69.0, 23.0)])
        assert geodesic_length_km(line) == pytest.approx(110.8, rel=0.01)

    def test_single_point_line_has_zero_length(self) -> None:
        assert geodesic_length_km(LineString()) == 0.0


class TestValidation:
    def test_accepts_a_valid_polygon(self) -> None:
        result = validate_polygon(
            {
                "type": "Polygon",
                "coordinates": [
                    [[68.9, 22.3], [70.4, 22.3], [70.4, 23.2], [68.9, 23.2], [68.9, 22.3]]
                ],
            }
        )
        assert isinstance(result, Polygon)

    def test_rejects_a_point(self) -> None:
        with pytest.raises(InvalidGeometryError, match="Polygon or MultiPolygon"):
            validate_polygon({"type": "Point", "coordinates": [69.0, 22.0]})

    def test_rejects_self_intersection(self) -> None:
        bowtie = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}
        with pytest.raises(InvalidGeometryError, match="not a valid polygon"):
            validate_polygon(bowtie)

    def test_rejects_out_of_range_longitude(self) -> None:
        with pytest.raises(InvalidGeometryError, match="longitude out of range"):
            validate_polygon(
                {
                    "type": "Polygon",
                    "coordinates": [[[181.0, 22.0], [182.0, 22.0], [182.0, 23.0], [181.0, 22.0]]],
                }
            )

    def test_rejects_an_area_over_the_limit(self) -> None:
        with pytest.raises(InvalidGeometryError, match="exceeds"):
            validate_polygon(bbox_polygon(60.0, 10.0, 80.0, 30.0), max_area_km2=1000.0)

    def test_accepts_an_area_under_the_limit(self) -> None:
        validate_polygon(bbox_polygon(69.0, 22.4, 69.1, 22.5), max_area_km2=1000.0)

    def test_rejects_empty_geometry(self) -> None:
        with pytest.raises(InvalidGeometryError, match="empty"):
            validate_polygon(Polygon())

    def test_rejects_unparseable_input(self) -> None:
        with pytest.raises(InvalidGeometryError):
            validate_polygon({"type": "Nonsense", "coordinates": []})


class TestBufferAndDistance:
    def test_buffer_produces_the_requested_radius(self) -> None:
        buffered = buffer_m(Point(*KUTCH), 10_000.0)
        # Sample the boundary in several directions; each should be ~10 km out.
        for bearing in (0.0, 90.0, 180.0, 270.0):
            edge = destination_point(*KUTCH, bearing, 10_000.0)
            assert buffered.covers(Point(*edge)) or geodesic_distance_m(
                *KUTCH, *edge
            ) == pytest.approx(10_000.0, rel=1e-6)
        assert geodesic_area_km2(buffered) == pytest.approx(math.pi * 100.0, rel=0.02)

    def test_point_inside_geometry_is_zero_distance(self) -> None:
        polygon = bbox_polygon(69.0, 22.4, 69.5, 22.6)
        assert point_to_geometry_distance_km(Point(69.2, 22.5), polygon) == 0.0

    def test_point_outside_geometry_measures_to_the_boundary(self) -> None:
        polygon = bbox_polygon(69.0, 22.4, 69.5, 22.6)
        distance = point_to_geometry_distance_km(Point(69.25, 22.7), polygon)
        assert distance == pytest.approx(11.1, rel=0.05)

    def test_distance_to_empty_geometry_is_infinite(self) -> None:
        assert point_to_geometry_distance_km(Point(*KUTCH), Polygon()) == float("inf")


class TestConversions:
    def test_knots_round_trip(self) -> None:
        assert ms_to_knots(knots_to_ms(12.5)) == pytest.approx(12.5)

    def test_one_knot_is_one_nautical_mile_per_hour(self) -> None:
        assert knots_to_ms(1.0) * 3600.0 == pytest.approx(1852.0, rel=1e-9)

    def test_as_multipolygon_wraps_a_polygon(self) -> None:
        result = as_multipolygon(bbox_polygon(69.0, 22.0, 69.1, 22.1))
        assert isinstance(result, MultiPolygon)
        assert len(result.geoms) == 1

    def test_as_multipolygon_rejects_a_line(self) -> None:
        with pytest.raises(InvalidGeometryError):
            as_multipolygon(LineString([(0, 0), (1, 1)]))

    def test_bbox_of_clamps_to_valid_ranges(self) -> None:
        min_lon, min_lat, max_lon, max_lat = bbox_of(Point(179.99, 89.99), buffer_km=200.0)
        assert min_lon >= -180.0 and max_lon <= 180.0
        assert min_lat >= -90.0 and max_lat <= 90.0
