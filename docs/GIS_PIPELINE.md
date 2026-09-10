# SPILLTRACE — GIS Specification

**Owner:** Agent 3 (raster) / Agent 4 (vector) · Traces: FR-004, FR-006, FR-010, FR-013, FR-014, AC-04, AC-09
**Storage CRS:** EPSG:4326 everywhere · **Measurement:** always geodesic or equal-area, never degrees

---

## 1. The rule that everything else follows

**A degree is not a distance.** At the Gulf of Kutch (22.4° N) a degree of longitude is
103 km and a degree of latitude is 111 km. Any distance, area, buffer or threshold
computed from raw coordinate differences is wrong by a latitude-dependent factor, and
the error is silent — the number still looks like a number.

So:

| Operation | How it is done | Where |
|---|---|---|
| Distance | `pyproj.Geod.inv` (WGS84 ellipsoid) | `core/geometry.geodesic_distance_m` |
| Distance on the AIS hot path | Haversine — verified within 0.5% of geodesic over inter-fix distances | `core/geometry.haversine_m` |
| Area / perimeter | `Geod.geometry_area_perimeter` | `core/geometry.geodesic_area_km2` |
| Buffer | reproject to a Lambert azimuthal equal-area CRS centred on the geometry, buffer in metres, reproject back | `core/geometry.buffer_m` |
| Bearing | `Geod.inv` forward azimuth, normalised to `[0, 360)` | `core/geometry.initial_bearing_deg` |
| Point-to-geometry distance | nearest point in degree space, then measured geodesically | `core/geometry.point_to_geometry_distance_km` |
| Database distance | `::geography` cast so PostGIS uses the spheroid | `docs/DATABASE.md` §4 |

`backend/tests/unit/test_geometry.py` pins these down, including the property that a
degree of longitude shrinks as `cos(latitude)`.

## 2. Validation at the edge

Every user-supplied polygon passes `validate_polygon` before it reaches a repository:
correct type, non-empty, `ST_IsValid`, coordinates in range, and area under
`SPILLTRACE_MAX_AOI_KM2`. Self-intersection is rejected with the reason from
`shapely.validation.explain_validity` rather than a generic message — an analyst who
drew a bow-tie AOI needs to know that, not "invalid input".

Geometries generated internally are normalised with `as_multipolygon` so the column type
is always satisfied, and repaired with `buffer(0)` only where the repair is documented.

## 3. Raster pipeline

```
GRD (COG)                        window reads only; the whole scene is never materialised
  → σ0 → dB                      10·log10, guarding σ0 ≤ 0
  → per-scene percentile clip    1st/99th, bounds recorded in the run manifest
  → standardise                  (x − mean)/std using the same per-scene statistics
  → no-data mask                 excluded from statistics and from loss
  → tile 128×128 stride 96       each tile keeps its own affine transform
  → model                        ndarray[N, 2, H, W] → probability
  → cosine-window stitch         overlap blended so tile seams are not detection edges
  → GeoTIFF (COG, deflate)       overviews built so map tiling is a range read
```

Rasters are written by `core/raster.write_geotiff`: tiled, deflate-compressed, with
overviews, band descriptions and provenance tags. `array_to_png` renders the probability
field for the map using a ramp that runs transparent → blue-green → amber; **red is
deliberately not used**, because a red slick reads as an accusation rather than a signal
strength.

## 4. Mask → polygon

```
probability → threshold (+ hysteresis) → morphological open/close → min-area filter
            → polygonize → geodesic area & perimeter → MultiPolygon(4326)
```

Every parameter is configurable and recorded in the run manifest. This matters more than
it looks: an undocumented morphological opening will quietly delete a thin discharge
trail, which is exactly the feature the system exists to find.

## 5. Vector pipeline

* **Trajectories** — cleaned, time-ordered positions become one `LineString` per
  continuous segment, split wherever reporting stops for 30 minutes or more. A segment
  with a single fix is recorded with empty geometry and a flag rather than dropped: "we
  saw this vessel once" is an observation.
* **Origin region** — particle positions → 2-D histogram → Gaussian smoothing → normalised
  density → highest-density regions at 90/75/50% probability mass, polygonised as the
  union of the cells that carry that mass. The polygon and the number attached to it
  therefore describe *the same set of cells*, which a marching-squares contour would not.
* **Correlation** — `ST_Intersects` against the origin region buffered by
  `correlation_buffer_km`, with the closest approach measured geodesically.

## 6. Spatial indexing

GiST on all ten geometry columns; BRIN on `ais_positions.timestamp` (append-only, highly
correlated with physical order); btree composites on the query paths in
`docs/DATABASE.md` §4; a partial index on `ais_positions(timestamp) WHERE is_valid`
because every downstream query filters on validity.

Verified against a live PostGIS instance: 10 GiST, 1 BRIN, 77 btree.

## 7. Tests

`backend/tests/unit/test_geometry.py` — 35 tests covering distance, bearing, area,
validation, buffering and unit conversion, including a known-area box and the
`cos(latitude)` property.
`backend/tests/unit/test_drift_density.py` — contour nesting, containment and monotonicity.
`backend/tests/unit/test_correlation.py` — inclusion and exclusion in both space and time.
`backend/tests/gis/` — the representative PostGIS queries from `docs/DATABASE.md` §4,
run against a real database.
