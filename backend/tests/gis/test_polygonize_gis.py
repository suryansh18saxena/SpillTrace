"""Polygonised detections, checked against PostGIS rather than against ourselves.

``core.polygonize`` measures area and perimeter with pyproj's geodesic solver.  PostGIS
measures them with its own spheroid implementation.  If the two disagree, one of them is
wrong — and since these numbers end up in an evidence report, "wrong" is not an option.
The geometry is also asserted to be exactly what the ``spill_detections`` column will
accept: a valid ``MULTIPOLYGON`` in SRID 4326.

Skipped when no PostGIS is reachable, so the unit suite still runs anywhere.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from rasterio.transform import from_bounds

from spilltrace.core.geometry import geodesic_area_km2, geodesic_perimeter_km
from spilltrace.core.masking import MaskConfig, build_mask
from spilltrace.core.polygonize import polygonize_mask

pytestmark = pytest.mark.gis

BOUNDS = (68.0, 21.0, 69.0, 22.0)
SIZE = 200
TRANSFORM = from_bounds(*BOUNDS, width=SIZE, height=SIZE)


@pytest.fixture(scope="module")
def connection() -> Any:
    psycopg = pytest.importorskip("psycopg")
    import os

    dsn = (
        f"host={os.environ.get('POSTGRES_HOST', 'postgres')} "
        f"port={os.environ.get('POSTGRES_PORT', '5432')} "
        f"dbname={os.environ.get('POSTGRES_DB', 'spilltrace')} "
        f"user={os.environ.get('POSTGRES_USER', 'spilltrace')} "
        f"password={os.environ.get('POSTGRES_PASSWORD', '')}"
    )
    try:
        conn = psycopg.connect(dsn, connect_timeout=5)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostGIS is not reachable: {exc}")
    with conn.cursor() as cursor:
        cursor.execute("SELECT PostGIS_Version()")
        if cursor.fetchone() is None:  # pragma: no cover
            pytest.skip("PostGIS extension is not installed")
    yield conn
    conn.close()


def _probability_field() -> np.ndarray:
    """A ribbon plus a small blob — one detection with two polygons."""
    grid = np.zeros((SIZE, SIZE), dtype=np.float32)
    rows = np.arange(SIZE)
    centre = (60 + 20 * np.sin(rows / 28.0)).astype(int)
    for row, col in zip(rows[30:170], centre[30:170], strict=True):
        grid[row, max(0, col - 6) : col + 6] = 0.92
    grid[150:170, 150:175] = 0.72
    return grid


def _detection() -> Any:
    probability = _probability_field()
    mask = build_mask(probability, MaskConfig(min_area_px=32))
    return polygonize_mask(
        mask.mask,
        transform=TRANSFORM,
        probability=probability,
        labels=mask.labels,
    )


def test_the_geometry_is_a_valid_multipolygon_in_4326(connection: Any) -> None:
    result = _detection()
    assert len(result.polygons) >= 2
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT ST_IsValid(g), ST_SRID(g), GeometryType(g), ST_NumGeometries(g) "
            "FROM (SELECT ST_GeomFromText(%s, 4326) AS g) AS q",
            (result.multipolygon.wkt,),
        )
        is_valid, srid, geom_type, parts = cursor.fetchone()
    assert is_valid is True
    assert srid == 4326
    assert geom_type == "MULTIPOLYGON"
    assert parts == len(result.polygons)


def test_geodesic_area_agrees_with_postgis(connection: Any) -> None:
    result = _detection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT ST_Area(ST_GeogFromText(%s)) / 1e6", (result.multipolygon.wkt,))
        postgis_km2 = float(cursor.fetchone()[0])
    assert result.area_km2 == pytest.approx(postgis_km2, rel=1e-3)
    # And the pyproj measurement of the same geometry, as a second opinion.
    assert geodesic_area_km2(result.multipolygon) == pytest.approx(postgis_km2, rel=1e-3)


def test_geodesic_perimeter_agrees_with_postgis(connection: Any) -> None:
    result = _detection()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT ST_Perimeter(ST_GeogFromText(%s)) / 1000.0", (result.multipolygon.wkt,)
        )
        postgis_km = float(cursor.fetchone()[0])
    assert geodesic_perimeter_km(result.multipolygon) == pytest.approx(postgis_km, rel=1e-3)


def test_degree_area_would_have_been_wrong_by_four_orders_of_magnitude(
    connection: Any,
) -> None:
    """The mistake this module exists to prevent, demonstrated against PostGIS."""
    result = _detection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT ST_Area(ST_GeomFromText(%s, 4326))", (result.multipolygon.wkt,))
        square_degrees = float(cursor.fetchone()[0])
    assert square_degrees < 1.0
    assert result.area_km2 > 100.0


def test_the_centroid_lies_inside_the_scene_bounds(connection: Any) -> None:
    result = _detection()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT ST_X(c), ST_Y(c) FROM "
            "(SELECT ST_Centroid(ST_GeomFromText(%s, 4326)) AS c) AS q",
            (result.multipolygon.wkt,),
        )
        lon, lat = (float(v) for v in cursor.fetchone())
    assert BOUNDS[0] <= lon <= BOUNDS[2]
    assert BOUNDS[1] <= lat <= BOUNDS[3]


def test_an_empty_detection_is_an_empty_multipolygon(connection: Any) -> None:
    from spilltrace.core.polygonize import polygonize_mask as polygonise

    empty = polygonise(np.zeros((SIZE, SIZE), dtype=bool), transform=TRANSFORM)
    with connection.cursor() as cursor:
        cursor.execute("SELECT ST_IsEmpty(ST_GeomFromText(%s, 4326))", (empty.multipolygon.wkt,))
        assert cursor.fetchone()[0] is True
