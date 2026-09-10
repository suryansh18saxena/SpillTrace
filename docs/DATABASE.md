# SPILLTRACE — Database Design

**Owner:** Agent 1 (Database + Backend Core) · Traces: `DB-001`…`DB-015`, `NFR-006`, `NFR-013`, `CON-005`
**Engine:** PostgreSQL 16 + PostGIS 3.4 · **SRID:** 4326 everywhere · **ORM:** SQLAlchemy 2.0 async + GeoAlchemy2

---

## 1. Principles

1. **Geometry and metadata only.** No raster, NetCDF or model bytes in a table (CON-005). Large
   objects live in MinIO/S3 and are referenced by `storage_uri` + `checksum_sha256`.
2. **SRID 4326 (WGS84) storage, geodesic measurement.** Distances/areas are computed with
   `::geography` casts or `ST_Transform` to an equal-area CRS, never in raw degrees.
3. **Provenance on every derived row.** `data_provenance ∈ ('REAL','SYNTHETIC','MIXED')` (CON-009).
4. **Reproducibility on every derived row.** `run_manifest jsonb` records software version, git sha,
   provider parameters, seeds and input checksums (NFR-005).
5. **Every geometry column gets a GiST index; every time column used in range filters gets a
   btree or BRIN index** (NFR-013).
6. **Soft delete over hard delete for cases** (`archived_at`), hard cascade for child artifacts.
7. **UUID v4 primary keys** for domain rows (safe to expose); `bigserial` for high-volume append-only
   tables (`ais_positions`, `drift_particles`).

Extensions required: `postgis`, `pgcrypto` (for `gen_random_uuid()`), `btree_gist`, `citext`.

## 2. Entity relationship overview

```
users ──1:N──► cases ──1:N──► case_scenes ──N:1──► satellite_scenes
                 │
                 ├──1:N──► spill_detections ──1:N──► verification_results
                 │                │
                 │                └──1:N──► drift_runs ──1:N──► drift_particles
                 ├──1:N──► environmental_runs ──┘ (forcing)
                 │
                 ├──1:N──► trajectories ──N:1──► vessels ──1:N──► ais_positions
                 │
                 ├──1:N──► attributions  (case × spill × vessel)
                 ├──1:N──► jobs
                 └──1:N──► evidence_artifacts

model_versions ──1:N──► spill_detections
```

## 3. Tables

### 3.1 `users` — DB-014
| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | `gen_random_uuid()` |
| `email` | citext UNIQUE NOT NULL | login identity |
| `password_hash` | text NOT NULL | Argon2id, never logged |
| `full_name` | text | |
| `role` | text NOT NULL | CHECK in (`analyst`,`admin`) |
| `is_active` | boolean NOT NULL DEFAULT true | |
| `created_at`,`updated_at`,`last_login_at` | timestamptz | |

### 3.2 `cases` — DB-001 (FR-001)
| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `case_ref` | text UNIQUE NOT NULL | human ref, e.g. `ST-2026-0001` |
| `title`, `description` | text | |
| `status` | text NOT NULL | `DRAFT`,`QUEUED`,`RUNNING`,`COMPLETED`,`FAILED`,`ARCHIVED` |
| `aoi` | geometry(Polygon,4326) NOT NULL | CHECK `ST_IsValid(aoi)`, area limit enforced in service layer |
| `start_time`,`end_time` | timestamptz NOT NULL | CHECK `end_time > start_time` |
| `owner_id` | uuid FK→users ON DELETE RESTRICT | authorization anchor (NFR-009) |
| `data_provenance` | text NOT NULL DEFAULT `'REAL'` | |
| `created_at`,`updated_at`,`archived_at` | timestamptz | |

Indexes: `GIST(aoi)`, `(owner_id, created_at DESC)`, `(status)`, `(start_time, end_time)`.

### 3.3 `satellite_scenes` — DB-002 (FR-002/FR-003)
Global catalogue rows, deduplicated by `product_id`; linked to cases through `case_scenes`.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `product_id` | text UNIQUE NOT NULL | provider product identifier |
| `provider` | text NOT NULL | e.g. `CDSE`, `FIXTURE` |
| `mission`,`platform` | text | `SENTINEL-1`, `S1A` |
| `product_type`,`sensor_mode` | text | `GRD`, `IW` |
| `acquisition_time` | timestamptz NOT NULL | |
| `footprint` | geometry(Polygon,4326) NOT NULL | true footprint |
| `bbox` | geometry(Polygon,4326) NOT NULL | envelope, for fast prefilter |
| `polarizations` | text[] | e.g. `{VV,VH}` |
| `orbit_direction` | text | `ASCENDING`/`DESCENDING` |
| `relative_orbit`,`absolute_orbit` | integer | |
| `resolution_m` | double precision | |
| `provider_ref` | jsonb | raw catalogue record (reproducibility) |
| `storage_uri`,`size_bytes`,`checksum_sha256` | text/bigint/text | set after download |
| `download_status` | text | `NOT_DOWNLOADED`,`DOWNLOADING`,`DOWNLOADED`,`FAILED` |
| `data_provenance` | text NOT NULL | |
| `created_at`,`updated_at` | timestamptz | |

Indexes: `GIST(footprint)`, `GIST(bbox)`, `(acquisition_time)`, `(product_type, acquisition_time)`.

`case_scenes(case_id, scene_id, is_selected boolean, created_at)` — PK `(case_id, scene_id)`.

### 3.4 `spill_detections` — DB-003 (FR-005/FR-006)
| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `case_id` | uuid FK→cases ON DELETE CASCADE | |
| `scene_id` | uuid FK→satellite_scenes NULL | null for synthetic detections |
| `geometry` | geometry(MultiPolygon,4326) NOT NULL | CHECK `ST_IsValid` |
| `centroid` | geometry(Point,4326) NOT NULL | generated in service layer |
| `area_km2`,`perimeter_km` | double precision | geodesic |
| `detection_confidence` | double precision | CHECK 0..1 — model confidence **only** (A-06) |
| `mean_probability`,`max_probability`,`threshold` | double precision | |
| `pixel_count` | integer | |
| `model_version_id` | uuid FK→model_versions | |
| `probability_raster_uri`,`mask_raster_uri` | text | object storage (CON-005) |
| `detected_at` | timestamptz NOT NULL | = scene acquisition time |
| `run_manifest` | jsonb NOT NULL | |
| `data_provenance` | text NOT NULL | |
| `created_at` | timestamptz | |

Indexes: `GIST(geometry)`, `GIST(centroid)`, `(case_id, detected_at DESC)`.

### 3.5 `verification_results` — DB-004 (FR-007)
| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `spill_id` | uuid FK→spill_detections ON DELETE CASCADE | |
| `is_latest` | boolean NOT NULL DEFAULT true | partial unique index on `(spill_id) WHERE is_latest` |
| `status` | text NOT NULL | `VERIFIED`,`UNCERTAIN`,`FALSE_POSITIVE` |
| `verification_confidence` | double precision | 0..1, distinct from detection confidence (A-06) |
| `wind_speed_ms`,`wind_direction_deg`,`wind_source` | double/double/text | |
| `shape_area_km2`,`shape_perimeter_km`,`shape_complexity`,`shape_compactness`,`shape_elongation` | double precision | |
| `slick_mean_db`,`background_mean_db`,`contrast_db`,`slick_std_db`,`background_std_db`,`gradient_mean` | double precision | |
| `features` | jsonb NOT NULL | full feature vector |
| `rules` | jsonb NOT NULL | `[{rule_id, passed, weight, observed, threshold, message}]` |
| `explanation` | text NOT NULL | plain-language, shown in UI + report |
| `classifier_name`,`classifier_score` | text/double | optional ML classifier (P2) |
| `run_manifest` | jsonb, `created_at` | |

### 3.6 `environmental_runs` — DB-005 (FR-008)
`id`, `case_id`, `source` (`CMEMS`,`ERA5`,`SYNTHETIC`), `provider`, `dataset_id`, `variables text[]`,
`time_start`,`time_end`, `extent geometry(Polygon,4326)`, `grid_resolution_deg`,
`storage_uri`,`checksum_sha256`,`size_bytes`, `status`,`error_message`,
`summary jsonb` (min/mean/max per variable — lets the UI show wind without opening the NetCDF),
`data_provenance`,`run_manifest`,`created_at`. Index: `GIST(extent)`, `(case_id, time_start)`.

### 3.7 `drift_runs` — DB-006 (FR-009/FR-010)
| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `case_id`,`spill_id` | uuid FK | |
| `environmental_run_id` | uuid FK NULL | forcing used |
| `engine` | text NOT NULL | `openoil`,`opendrift`,`analytical` (AD-7) |
| `mode` | text NOT NULL | `FORWARD`,`BACKWARD`,`ENSEMBLE` |
| `parameters` | jsonb NOT NULL | full parameter set |
| `seed` | bigint NOT NULL | RNG seed → reproducibility (AC-07) |
| `number_of_particles`,`ensemble_members` | integer | |
| `duration_hours`,`time_step_seconds` | double/integer | |
| `origin_geometry` | geometry(MultiPolygon,4326) | **probability region**, never a point (CON-008) |
| `origin_confidence` | double precision | |
| `density_grid_uri` | text | GeoTIFF density in object storage |
| `inferred_start`,`inferred_end` | timestamptz | inferred discharge window (A-02) |
| `status`,`error_message` | text | |
| `data_provenance`,`run_manifest` | | |
| `created_at`,`completed_at` | timestamptz | |

Indexes: `GIST(origin_geometry)`, `(case_id, created_at DESC)`, `(spill_id, mode)`.

### 3.8 `drift_particles` — DB-015
Decimated, visualization-grade particle states. **Full output stays in object storage.**
`id bigserial`, `drift_run_id`, `particle_id int`, `step_index int`, `timestamp timestamptz`,
`position geometry(Point,4326)`, `member int`, `status text`, `mass_oil double`.
Indexes: `(drift_run_id, step_index)`, `GIST(position)`.

### 3.9 `vessels` — DB-007
`id uuid`, `mmsi bigint UNIQUE NOT NULL` (CHECK 100000000..999999999), `imo bigint NULL`,
`name`,`callsign`,`ship_type int`,`ship_type_name`,`flag_country`,`flag_mid int`,
`length_m`,`width_m`,`draught_m`,`destination`,`eta`,
`first_seen`,`last_seen`,`static_completeness double` (0..1, feeds SCORE-006),
`source`,`data_provenance`,`created_at`,`updated_at`.
Indexes: `(mmsi)` unique, `(imo)`, `(last_seen DESC)`, `gin(name gin_trgm_ops)` for search.

### 3.10 `ais_positions` — DB-008 (FR-011/FR-012)
| Column | Type | Notes |
|---|---|---|
| `id` | bigserial PK | high volume |
| `vessel_id` | uuid FK→vessels ON DELETE CASCADE | |
| `mmsi` | bigint NOT NULL | denormalized for ingest speed |
| `timestamp` | timestamptz NOT NULL | message time (UTC) |
| `position` | geometry(Point,4326) NOT NULL | |
| `sog_knots`,`cog_deg`,`heading_deg`,`rot` | double precision | sentinel values normalized to NULL |
| `nav_status` | smallint | |
| `message_type` | text | `PositionReport`, `StandardClassBPositionReport`, … |
| `source` | text NOT NULL | `AISSTREAM`, `SYNTHETIC`, … |
| `is_valid` | boolean NOT NULL DEFAULT true | set by the cleaner (FR-012) |
| `quality_flags` | text[] | e.g. `{IMPOSSIBLE_JUMP,DUPLICATE,BAD_TIMESTAMP}` |
| `rejection_reason` | text | |
| `raw` | jsonb | original message (evidence) |
| `ingested_at` | timestamptz | |

Constraints: `UNIQUE (mmsi, timestamp, source)` — deduplication at the database level (AIS-010).
Indexes: `GIST(position)`, `(vessel_id, timestamp)`, `BRIN(timestamp)`, partial `(timestamp) WHERE is_valid`.

### 3.11 `trajectories` — DB-009 (FR-013)
`id uuid`, `vessel_id`, `case_id NULL`, `time_start`,`time_end`,
`geometry geometry(LineString,4326)`, `position_count`, `distance_km`, `duration_hours`,
`mean_sog_knots`,`max_sog_knots`,
`gap_count`,`max_gap_minutes`,`total_gap_minutes`,`coverage_ratio`,
`quality_score` (0..1 → SCORE-006), `quality_flags text[]`,
`data_provenance`,`created_at`. Indexes: `GIST(geometry)`, `(vessel_id, time_start)`, `(case_id)`.

### 3.12 `attributions` — DB-010 (FR-015/FR-016)
| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `case_id`,`spill_id`,`drift_run_id`,`vessel_id` | uuid FK | |
| `trajectory_id` | uuid FK NULL | |
| `origin_proximity`,`time_match`,`trajectory_match`,`heading_match`,`speed_match`,`ais_reliability` | double precision NOT NULL | each CHECK 0..1 (SCORE-001…006) |
| `final_score` | double precision NOT NULL | CHECK 0..1 |
| `rank` | integer NOT NULL | |
| `weights` | jsonb NOT NULL | the exact weights used (SCORE-008) |
| `factor_explanations` | jsonb NOT NULL | one plain-language string + evidence per factor (SCORE-007) |
| `evidence` | jsonb NOT NULL | closest approach, overlap %, timings |
| `closest_approach_km`,`closest_approach_time` | double/timestamptz | |
| `scoring_version` | text NOT NULL | e.g. `prd-j-v1` |
| `data_provenance`,`run_manifest`,`created_at` | | |

Constraint: `UNIQUE (case_id, spill_id, vessel_id, scoring_version)`.
Index: `(case_id, spill_id, rank)`.

### 3.13 `jobs` — DB-011 (FR-019, NFR-003)
`id uuid`, `case_id NULL`, `pipeline_id uuid NULL`, `job_type text NOT NULL`,
`status text NOT NULL` (`QUEUED`,`RUNNING`,`COMPLETED`,`FAILED`,`CANCELLED`),
`progress smallint 0..100`, `step text`, `priority smallint`,
`attempt smallint`,`max_attempts smallint`,
`payload jsonb`,`result_ref jsonb`,
`error_code text`,`error_message text`,
`depends_on uuid[]`,
`queued_at`,`started_at`,`finished_at`,`heartbeat_at`,`worker_id text`,
`created_at`,`updated_at`.
Indexes: `(case_id, created_at DESC)`, `(status, priority DESC, queued_at)`, `(pipeline_id)`,
partial `(heartbeat_at) WHERE status='RUNNING'` (stale-claim reaper).

### 3.14 `evidence_artifacts` — DB-012 (NFR-005/NFR-006)
`id uuid`, `case_id`, `artifact_type text` (`GRD`,`TILE`,`PROBABILITY_RASTER`,`MASK`,`ENV_NETCDF`,
`DRIFT_OUTPUT`,`DENSITY_GRID`,`REPORT_HTML`,`REPORT_PDF`,`GEOJSON`), `label text`,
`storage_uri text NOT NULL`,`media_type text`,`size_bytes bigint`,`checksum_sha256 text NOT NULL`,
`related_table text`,`related_id uuid`,`metadata jsonb`,`data_provenance`,`created_at`.
Index: `(case_id, artifact_type)`, `(checksum_sha256)`.

### 3.15 `model_versions` — DB-013
`id uuid`, `name text`,`version text`,`framework text`,`task text`,
`metrics jsonb` (dice/iou/precision/recall — **measured, never fabricated**),
`params jsonb`,`training_manifest jsonb`,
`artifact_uri text`,`checksum_sha256 text`,
`input_channels int`,`input_size int`,`normalization jsonb`,
`is_active boolean`,`notes text`,`created_at`.
Constraint: `UNIQUE (name, version)`; partial unique `(name) WHERE is_active`.

## 4. Representative spatial/temporal queries (tested in `backend/tests/gis/`)

```sql
-- Scenes intersecting a case AOI within its time window
SELECT s.* FROM satellite_scenes s
JOIN cases c ON c.id = :case_id
WHERE ST_Intersects(s.footprint, c.aoi)
  AND s.acquisition_time BETWEEN c.start_time AND c.end_time;

-- Candidate vessels: any valid position inside the origin probability region
-- during the inferred discharge window  (FR-014)
SELECT DISTINCT p.vessel_id
FROM ais_positions p
JOIN drift_runs d ON d.id = :drift_run_id
WHERE p.is_valid
  AND p.timestamp BETWEEN d.inferred_start AND d.inferred_end
  AND ST_Intersects(p.position, d.origin_geometry);

-- Closest approach of a vessel trajectory to the origin region (geodesic metres)
SELECT t.vessel_id,
       ST_Distance(t.geometry::geography, d.origin_geometry::geography) AS distance_m
FROM trajectories t, drift_runs d
WHERE d.id = :drift_run_id AND t.case_id = :case_id
ORDER BY distance_m ASC;

-- Geodesic spill area in km²
SELECT ST_Area(geometry::geography) / 1e6 AS area_km2 FROM spill_detections WHERE id = :id;
```

## 5. Migrations & seeding

* Alembic, one migration per schema change, both `upgrade()` and `downgrade()` implemented.
* `0001_initial` creates extensions + all tables + indexes.
* Seed (`make seed`) inserts: an admin user, a demo analyst, one fully-populated **SYNTHETIC** demo
  case exercising every table, and the `analytical-detector@1.0.0` model version row.
* `make db-reset` drops and recreates from migrations, then seeds — verified by
  `backend/tests/integration/test_migrations.py`.
