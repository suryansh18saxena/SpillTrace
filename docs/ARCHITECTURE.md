# SPILLTRACE — Architecture

**Owner:** Agent 0 (Lead Architect) · Traces: all of `docs/REQUIREMENTS.md`

---

## 1. System context

```
                     ┌─────────────────────────────────────────────┐
   Analyst ────────► │  Next.js 15 (App Router, TS, MapLibre GL)    │
   (browser)         │  server-side BFF route handlers only         │
                     └───────────────┬─────────────────────────────┘
                                     │ HTTPS  (JWT)
                     ┌───────────────▼─────────────────────────────┐
                     │  FastAPI  —  API layer (thin)                │
                     │  routers → services → repositories           │
                     └──┬──────────────┬─────────────────────┬──────┘
                        │              │                     │
             enqueue    │              │ SQL/PostGIS         │ presigned URLs
                        ▼              ▼                     ▼
                  ┌──────────┐  ┌──────────────┐     ┌──────────────┐
                  │  Redis   │  │ PostgreSQL   │     │ MinIO (S3)   │
                  │ queue +  │  │  + PostGIS   │     │ object store │
                  │  cache   │  │  metadata    │     │ rasters/NetCDF│
                  └────┬─────┘  └──────▲───────┘     └──────▲───────┘
                       │ dequeue       │                    │
                  ┌────▼──────────────────────────────────────────┐
                  │  Worker pool (same image, different entry)     │
                  │  satellite · preprocess · ml · verify · env    │
                  │  drift · ais · trajectory · correlate · score  │
                  │  · report                                      │
                  └────┬──────────────────────────────────────────┘
                       │ adapters (swappable, config-selected)
        ┌──────────────┼───────────────┬──────────────┬────────────┐
        ▼              ▼               ▼              ▼            ▼
  Copernicus     Copernicus       AISStream      Zenodo       Local fixtures
  Data Space     Marine           WebSocket      dataset      (SYNTHETIC)
  (Sentinel-1)   (wind/current)   (AIS)          (training)
```

## 2. Key architectural decisions

> Full rationale with alternatives considered lives in `docs/DECISIONS.md`.

### AD-1 — One Python package, two runtimes
`backend/src/spilltrace` is a **single installable package** consumed by both the API container and
the worker container. Same image, different entrypoint. This eliminates the classic
`backend/` vs `worker/` code-drift problem that the PRD's flat folder split invites, gives one
dependency lockfile, and lets the pure domain layer be imported by ML training scripts.

```
backend/src/spilltrace/
  core/        pure domain — NO I/O, NO framework, 100% unit-testable
               geometry, scoring, ais cleaning, trajectory building,
               verification rules, drift math, provenance, errors
  adapters/    every external boundary behind a Protocol
               satellite/ environmental/ ais/ drift/ storage/ segmentation/
  db/          SQLAlchemy 2.0 models, repositories, Alembic migrations
  api/         FastAPI routers, schemas, dependencies, auth
  worker/      job handlers + queue runtime
  ml/          inference-side model loading & tiling (training lives in ml/)
  demo/        deterministic SYNTHETIC scenario generators
```

**Dependency rule (enforced by an import-linter test):** `core` imports nothing from
`adapters`/`db`/`api`/`worker`. `adapters` may import `core`. `api`/`worker` may import everything.
Nothing imports `demo` except `demo` adapters and tests.

### AD-2 — Ports and adapters for every external dependency
Each external system is a `typing.Protocol` in `core/ports.py` with at least two implementations:

| Port | Real implementation | Deterministic implementation |
|---|---|---|
| `SatelliteCatalogue` | `CdseCatalogue` (OData/STAC) | `FixtureCatalogue` |
| `ProductDownloader` | `CdseDownloader` | `FixtureDownloader` |
| `EnvironmentalProvider` | `CopernicusMarineProvider` | `SyntheticEnvironmentProvider` |
| `AISProvider` | `AISStreamProvider` (server-side WS) | `SyntheticAISProvider` |
| `DriftEngine` | `OpenOilEngine` | `AnalyticalDriftEngine` |
| `SegmentationModel` | `UNetModel` (torch) | `AnalyticalDetector` |
| `ObjectStore` | `S3ObjectStore` (MinIO/S3) | `LocalObjectStore` |

Selection is by environment variable (`SPILLTRACE_<PORT>_PROVIDER`). **Every artifact produced
carries `data_provenance ∈ {REAL, SYNTHETIC, MIXED}`** which propagates to the UI and the report
(CON-009). This is what makes "dummy-first" (prompt §6) safe rather than dishonest.

### AD-3 — Jobs are first-class, durable, and observable
The job record in PostgreSQL is the source of truth; Redis is only the transport. A worker crash
therefore never loses a job's history. States: `QUEUED → RUNNING → COMPLETED | FAILED | CANCELLED`,
plus `progress` (0–100), `step` (human label), `attempt`, `error_code`, `error_message`,
`result_ref`. A **pipeline** is a DAG of jobs on one case; each stage enqueues the next on success.

Queue library: a thin `JobQueue` abstraction over Redis lists + a reliable-claim pattern
(`BLMOVE` to a processing list, heartbeat, reaper for stale claims). Rationale in DECISIONS.md
(AD-3): avoids Celery's broker/serializer weight while keeping at-least-once delivery, and keeps
handlers as plain functions that are trivially unit-testable.

### AD-4 — PostGIS holds geometry + metadata only; MinIO holds bytes
Hard rule from CON-005/NFR-006. Rasters (GRD, VV/VH tiles, probability masks), NetCDF
environmental subsets, drift outputs and reports live in object storage, addressed by
`storage_uri` + `sha256` recorded in `evidence_artifacts`. Nothing larger than a geometry or a
small JSON blob is stored in a table.

### AD-5 — Frontend never talks to a third party
The browser talks to exactly one host: the SPILLTRACE API, authenticated with the user's own bearer
token. It never contacts Copernicus, CMEMS, AISStream or a basemap provider, so there is no code
path by which a provider credential can reach the client bundle (CON-004). Concretely:

* the MapLibre basemap is a self-hosted style with **no external tile, glyph or sprite URL** —
  the map renders with zero third-party requests;
* provider calls happen only in the API and worker processes, which read credentials from the
  environment;
* the frontend's CSP pins `connect-src` to `'self'` plus the configured API origin, so the
  restriction is enforced by the browser rather than by convention;
* `make audit-secrets` greps the built client bundle for credential-shaped names and fails the
  build.

Calling our own API directly from the browser is deliberate: a Next.js BFF proxy in front of it
would add a hop and a second place to keep authorisation correct, without changing what a
credential can reach.

### AD-6 — Reproducibility envelope
Every derived artifact stores a `run_manifest` JSON: software version, git sha, model name+version,
provider ids and query parameters, time ranges, RNG seed, parameter set, input artifact checksums.
The evidence report renders this verbatim (NFR-005, AC-12).

### AD-7 — Degradation is designed, not accidental
`OpenDrift` is a heavy scientific dependency. `DriftEngine` therefore has a documented analytical
fallback so that the reasoning chain never breaks; when the fallback is used, the drift run is
tagged `engine=analytical`, `data_provenance=SYNTHETIC`, and the UI/report say so explicitly. Same
pattern for the segmentation model when no trained checkpoint is present. This is what keeps the
demo honest **and** always working.

## 3. Container topology (`docker-compose.yml`)

| Service | Image | Ports | Purpose |
|---|---|---|---|
| `postgres` | `postgis/postgis:16-3.4` | 5432 | metadata + geometry |
| `redis` | `redis:7-alpine` | 6379 | queue + cache |
| `minio` | `minio/minio` | 9000/9001 | S3-compatible object storage |
| `minio-init` | `minio/mc` | — | one-shot bucket creation |
| `api` | `infra/Dockerfile.backend` | 8000 | FastAPI |
| `worker` | same image, `worker` entrypoint | — | job execution |
| `ais-ingestor` | same image, `ais` entrypoint | — | long-lived AIS WebSocket consumer |
| `frontend` | `infra/Dockerfile.frontend` | 3000 | Next.js |

All services declare healthchecks and `depends_on: condition: service_healthy`. Runtime is
auto-detected by the `Makefile` so the identical file works with Docker or Podman.

## 4. Request/job flow — creating and running an investigation

```
POST /api/v1/cases                        → case (DRAFT)
POST /api/v1/cases/{id}/pipeline          → creates a job DAG, returns pipeline id
     └─ scene.search → scene.download → sar.preprocess → ml.detect → detect.verify
        → env.fetch  → drift.hindcast   → ais.ingest    → ais.clean → traj.build
        → correlate  → score            → report.build
GET  /api/v1/cases/{id}/jobs              → poll (SSE stream also available)
GET  /api/v1/cases/{id}/layers/*          → GeoJSON / TileJSON for the map
GET  /api/v1/cases/{id}/report            → evidence report
```

Each stage is independently re-runnable with different parameters, which is what makes the system
an *investigation tool* rather than a one-shot batch script.

## 5. Technology choices

| Layer | Choice | Version |
|---|---|---|
| Frontend | Next.js (App Router) + React + TypeScript strict | 15.x / 19.x / 5.x |
| Map | MapLibre GL JS | 4.x |
| Frontend state/data | TanStack Query | 5.x |
| Backend | FastAPI + Pydantic v2 + Uvicorn | 0.11x / 2.x |
| ORM | SQLAlchemy 2.0 (async) + GeoAlchemy2 | 2.0.x |
| Migrations | Alembic | 1.13.x |
| DB | PostgreSQL 16 + PostGIS 3.4 | |
| Queue | Redis 7 + custom `JobQueue` | |
| Raster | rasterio (bundled GDAL wheels), numpy, shapely 2, pyproj | |
| ML | PyTorch (CPU wheels by default, CUDA by config) | 2.x |
| Drift | OpenDrift/OpenOil (optional extra) + analytical fallback | |
| Object store | MinIO + boto3 | |
| Python | 3.12 in all containers | |

**Note on the dev host:** it runs Python 3.14 and has no GDAL/Postgres/Redis installed. All Python
work therefore happens inside containers pinned to 3.12, which is also the correct engineering
answer for reproducibility. See `docs/DEPLOYMENT.md`.

## 6. Security architecture

See `docs/SECURITY.md`. Summary: Argon2id password hashing; short-lived JWT access + rotating
refresh tokens in httpOnly cookies; per-object ownership checks in the repository layer (NFR-009);
Pydantic validation at the edge; SQLAlchemy parameter binding everywhere; secrets only from
environment/secret files; rate limits on `/auth/*` and job creation; strict CSP on the frontend.
