"""Geodesic geometry helpers.

Storage CRS is EPSG:4326 throughout, so **no distance or area may be computed in
degrees**.  Everything here uses either a geodesic computation (pyproj ``Geod``) or an
equal-area projection centred on the geometry.
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

from pyproj import Geod
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

from spilltrace.core.errors import InvalidGeometryError

WGS84 = "EPSG:4326"
_GEOD = Geod(ellps="WGS84")

EARTH_RADIUS_M = 6_371_008.8
NM_IN_M = 1852.0
KNOT_IN_MS = 0.5144444444444445


# --------------------------------------------------------------------------- basics
def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in metres.

    Used on the AIS hot path where a full geodesic inverse would be needlessly slow;
    the spherical approximation is well within AIS positional accuracy.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def geodesic_distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Ellipsoidal (WGS84) distance in metres."""
    _, _, distance = _GEOD.inv(lon1, lat1, lon2, lat2)
    return float(distance)


def initial_bearing_deg(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Forward azimuth from point 1 to point 2, normalised to [0, 360)."""
    azimuth, _, _ = _GEOD.inv(lon1, lat1, lon2, lat2)
    return azimuth % 360.0


def angular_difference_deg(a: float, b: float) -> float:
    """Smallest absolute difference between two bearings, in [0, 180]."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def destination_point(
    lon: float, lat: float, bearing_deg: float, distance_m: float
) -> tuple[float, float]:
    """Point reached by travelling ``distance_m`` along ``bearing_deg``."""
    new_lon, new_lat, _ = _GEOD.fwd(lon, lat, bearing_deg, distance_m)
    return float(new_lon), float(new_lat)


# --------------------------------------------------------------------------- areas
def geodesic_area_km2(geometry: BaseGeometry) -> float:
    """Area of a polygonal geometry in square kilometres."""
    if geometry.is_empty:
        return 0.0
    area_m2, _ = _GEOD.geometry_area_perimeter(geometry)
    return abs(area_m2) / 1e6


def geodesic_perimeter_km(geometry: BaseGeometry) -> float:
    if geometry.is_empty:
        return 0.0
    _, perimeter_m = _GEOD.geometry_area_perimeter(geometry)
    return abs(perimeter_m) / 1000.0


def geodesic_length_km(line: LineString) -> float:
    if line.is_empty or len(line.coords) < 2:
        return 0.0
    total = 0.0
    coords = list(line.coords)
    for (lon1, lat1), (lon2, lat2) in pairwise(coords):
        total += geodesic_distance_m(lon1, lat1, lon2, lat2)
    return total / 1000.0


# --------------------------------------------------------------------------- projection
def local_azimuthal_crs(geometry: BaseGeometry) -> str:
    """A Lambert azimuthal equal-area CRS centred on the geometry.

    Used for buffering and morphological work that must be metric.
    """
    centroid = geometry.centroid
    return (
        f"+proj=laea +lat_0={centroid.y:.6f} +lon_0={centroid.x:.6f} +datum=WGS84 +units=m +no_defs"
    )


def buffer_m(geometry: BaseGeometry, distance_m: float) -> BaseGeometry:
    """Buffer a WGS84 geometry by a distance in metres."""
    from pyproj import Transformer  # local import keeps module import cheap

    crs = local_azimuthal_crs(geometry)
    to_metric = Transformer.from_crs(WGS84, crs, always_xy=True).transform
    to_wgs84 = Transformer.from_crs(crs, WGS84, always_xy=True).transform
    projected = shapely_transform(to_metric, geometry)
    return shapely_transform(to_wgs84, projected.buffer(distance_m))


# --------------------------------------------------------------------------- validation
def parse_geojson_geometry(payload: dict[str, Any] | BaseGeometry) -> BaseGeometry:
    if isinstance(payload, BaseGeometry):
        return payload
    try:
        geometry = shape(payload)
    except Exception as exc:
        raise InvalidGeometryError(f"Geometry could not be parsed: {exc}") from exc
    return geometry


def validate_polygon(
    payload: dict[str, Any] | BaseGeometry,
    *,
    max_area_km2: float | None = None,
    field: str = "geometry",
) -> Polygon | MultiPolygon:
    """Validate a user-supplied polygon.

    Rejects the failure modes that actually reach a geospatial API: wrong type,
    self-intersection, out-of-range coordinates, empty rings, and AOIs so large that
    downstream providers would refuse or time out.
    """
    geometry = parse_geojson_geometry(payload)

    if not isinstance(geometry, Polygon | MultiPolygon):
        raise InvalidGeometryError(
            f"{field} must be a Polygon or MultiPolygon, got {geometry.geom_type}.",
            field=field,
            geom_type=geometry.geom_type,
        )
    if geometry.is_empty:
        raise InvalidGeometryError(f"{field} is empty.", field=field)
    if not geometry.is_valid:
        from shapely.validation import explain_validity

        raise InvalidGeometryError(
            f"{field} is not a valid polygon: {explain_validity(geometry)}", field=field
        )

    min_lon, min_lat, max_lon, max_lat = geometry.bounds
    if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0):
        raise InvalidGeometryError(f"{field} longitude out of range [-180, 180].", field=field)
    if not (-90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
        raise InvalidGeometryError(f"{field} latitude out of range [-90, 90].", field=field)

    if max_area_km2 is not None:
        area = geodesic_area_km2(geometry)
        if area > max_area_km2:
            raise InvalidGeometryError(
                f"{field} covers {area:,.0f} km² which exceeds the {max_area_km2:,.0f} km² limit.",
                field=field,
                area_km2=round(area, 2),
                max_area_km2=max_area_km2,
            )
    return geometry


def bbox_of(geometry: BaseGeometry, buffer_km: float = 0.0) -> tuple[float, float, float, float]:
    """Bounding box ``(min_lon, min_lat, max_lon, max_lat)``, optionally buffered."""
    if buffer_km > 0:
        geometry = buffer_m(geometry, buffer_km * 1000.0)
    min_lon, min_lat, max_lon, max_lat = geometry.bounds
    return (
        max(-180.0, min_lon),
        max(-90.0, min_lat),
        min(180.0, max_lon),
        min(90.0, max_lat),
    )


def bbox_polygon(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> Polygon:
    return Polygon(
        [
            (min_lon, min_lat),
            (max_lon, min_lat),
            (max_lon, max_lat),
            (min_lon, max_lat),
            (min_lon, min_lat),
        ]
    )


def as_multipolygon(geometry: BaseGeometry) -> MultiPolygon:
    """Normalise to MultiPolygon so the database column type is always satisfied."""
    if isinstance(geometry, MultiPolygon):
        return geometry
    if isinstance(geometry, Polygon):
        return MultiPolygon([geometry])
    raise InvalidGeometryError(f"Cannot convert {geometry.geom_type} to MultiPolygon.")


def point_to_geometry_distance_km(point: Point, geometry: BaseGeometry) -> float:
    """Geodesic distance from a point to the nearest position on a geometry.

    ``shapely.distance`` returns degrees, which is meaningless as a physical distance,
    so the nearest point is found in degree space and then measured geodesically.  The
    small error this introduces is far below AIS positional accuracy at these scales.
    """
    from shapely.ops import nearest_points

    if geometry.is_empty:
        return float("inf")
    if geometry.covers(point):
        return 0.0
    nearest = nearest_points(point, geometry)[1]
    return geodesic_distance_m(point.x, point.y, nearest.x, nearest.y) / 1000.0


def knots_to_ms(knots: float) -> float:
    return knots * KNOT_IN_MS


def ms_to_knots(ms: float) -> float:
    return ms / KNOT_IN_MS


__all__ = [
    "KNOT_IN_MS",
    "NM_IN_M",
    "WGS84",
    "angular_difference_deg",
    "as_multipolygon",
    "bbox_of",
    "bbox_polygon",
    "buffer_m",
    "destination_point",
    "geodesic_area_km2",
    "geodesic_distance_m",
    "geodesic_length_km",
    "geodesic_perimeter_km",
    "haversine_m",
    "initial_bearing_deg",
    "knots_to_ms",
    "local_azimuthal_crs",
    "ms_to_knots",
    "parse_geojson_geometry",
    "point_to_geometry_distance_km",
    "validate_polygon",
]
