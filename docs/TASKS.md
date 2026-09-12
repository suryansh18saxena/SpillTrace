# SPILLTRACE — Task Registry

**Owner:** Agent 0 · **This file is the persistent task state.** It is updated after every task.

Statuses: `TODO` · `IN_PROGRESS` · `BLOCKED` · `REVIEW` · `TESTING` · `COMPLETED` · `FAILED` · `NEEDS_REWORK`

**A task may only be marked `COMPLETED` when all of these hold** (prompt §27):
implementation exists · error handling · validation · tests written · tests pass · typecheck passes ·
lint passes · build passes (where relevant) · docs updated · traceability updated · integration verified.

> **Progress at last update.** *Both* pipelines run end to end: the 8-stage
> demonstration chain and the full 13-stage chain
> (`scene.search → scene.download → sar.preprocess → ml.detect → env.fetch →
> detect.verify → drift.hindcast → ais.ingest → ais.clean → traj.build → correlate →
> score → report.build`). 638 backend tests and 153 frontend tests pass; ruff, mypy and
> the secret audit are clean; all ten UI routes build and serve against the live API.
> Remaining: a live CDSE run with real credentials, a training run, and a browser pass
> over the map. Statuses below are updated after every verified task.

Owners: **A0** Lead/Architect · **A1** DB+Backend Core · **A2** Frontend/GIS-UI · **A3** Sentinel-1+ML+Look-alike · **A4** AIS/Drift/Scoring · **QA** Test engineer · **SEC** Security · **DEV** DevOps

Columns: `ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status`

---

## Phase 0 — Discovery

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P0-001 | A0 | Inspect repository, tooling, host capabilities | — | — | Findings recorded in DECISIONS.md | COMPLETED |
| P0-002 | A0 | Read complete PRD (7 pages, all parts A–P) | P0-001 | `prd.pdf` | All parts transcribed; no diagrams missed (48 embedded images verified as bullet glyphs) | COMPLETED |
| P0-003 | A0 | Extract functional requirements | P0-002 | `docs/REQUIREMENTS.md` §1 | FR-001…FR-020 defined | COMPLETED |
| P0-004 | A0 | Extract architecture requirements | P0-002 | `docs/ARCHITECTURE.md` | Context diagram + AD-1…AD-7 | COMPLETED |
| P0-005 | A0 | Extract database requirements | P0-002 | `docs/DATABASE.md` | DB-001…DB-015 with full column lists | COMPLETED |
| P0-006 | A0 | Extract frontend requirements | P0-002 | `docs/REQUIREMENTS.md` §4 | UI-001…UI-010 + layer list | COMPLETED |
| P0-007 | A0 | Extract backend/service requirements | P0-002 | `docs/REQUIREMENTS.md` §2, `docs/API.md` | SVC-001…SVC-014; API frozen | COMPLETED |
| P0-008 | A0 | Extract ML requirements | P0-002 | `docs/ML_PIPELINE.md` | Dataset spec, metrics, versioning | COMPLETED |
| P0-009 | A0 | Extract GIS requirements | P0-002 | `docs/GIS_PIPELINE.md` | CRS policy, polygonization, area rules | COMPLETED |
| P0-010 | A0 | Extract AIS requirements | P0-002 | `docs/AIS_PIPELINE.md` | Cleaning rules, trajectory, reliability | COMPLETED |
| P0-011 | A0 | Extract acceptance criteria | P0-002 | `docs/REQUIREMENTS.md` §9–10 | AC-01…AC-13, MVP-01…MVP-11 | COMPLETED |
| P0-012 | A0 | Identify ambiguities | P0-002 | `docs/REQUIREMENTS.md` §11 | A-01…A-10 documented with resolutions | COMPLETED |
| P0-013 | A0 | Architecture document | P0-004 | `docs/ARCHITECTURE.md` | Reviewed, container topology defined | COMPLETED |
| P0-014 | A0 | Task graph / micro-task backlog | P0-003..011 | `docs/TASKS.md` | This file | COMPLETED |
| P0-015 | A0 | Agent ownership + shared-interface freeze | P0-014 | `docs/TASKS.md`, `docs/API.md` | Owners assigned; API.md declared frozen | COMPLETED |
| P0-016 | A0 | External-API research brief (CDSE, Zenodo, CMEMS, OpenDrift, AISStream, SAR ML, look-alike features) | P0-002 | `docs/DECISIONS.md` | Every claim labelled CONFIRMED/UNCERTAIN with sources | COMPLETED |
| P0-017 | A0 | Traceability matrix skeleton | P0-003 | `docs/TRACEABILITY.md` | Every requirement has a row | COMPLETED |

## Phase 1 — Repository + container foundation

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P1-001 | DEV | Monorepo structure (`backend/ frontend/ ml/ infra/ docs/ data/`) | P0-013 | tree | Directories exist, documented in README | COMPLETED |
| P1-002 | DEV | Git init, `.gitignore`, `.gitattributes`, `.editorconfig` | P1-001 | `.gitignore` | No secrets/artifacts/data tracked | COMPLETED |
| P1-003 | DEV | `.env.example` with every variable, documented, no real secrets | P1-001 | `.env.example` | `make check-env` validates | COMPLETED |
| P1-004 | DEV | Compose spec (`docker-compose.yml`) for all 8 services | P1-003 | `docker-compose.yml` | `config` validates | COMPLETED |
| P1-005 | DEV | Backend/worker Dockerfile (python 3.12-slim, non-root, multi-stage) | P1-004 | `infra/Dockerfile.backend` | Image builds; `python -c "import spilltrace"` | COMPLETED |
| P1-006 | DEV | Frontend Dockerfile (node 22, standalone output, non-root) | P1-004 | `infra/Dockerfile.frontend` | Image builds; prod server starts | COMPLETED |
| P1-007 | DEV | PostGIS service + init SQL (extensions) | P1-004 | `infra/postgres/init.sql` | `SELECT postgis_version()` works | COMPLETED |
| P1-008 | DEV | Redis service + healthcheck | P1-004 | `docker-compose.yml` | `redis-cli ping` = PONG | COMPLETED |
| P1-009 | DEV | MinIO + `minio-init` bucket bootstrap | P1-004 | `infra/minio/` | Buckets exist after `up` | COMPLETED |
| P1-010 | DEV | Worker + ais-ingestor services (same image, different entrypoint) | P1-005 | `docker-compose.yml` | Containers start and log readiness | COMPLETED |
| P1-011 | DEV | Network, volumes, dependency ordering (`service_healthy`) | P1-004 | `docker-compose.yml` | api waits for db+redis+minio | COMPLETED |
| P1-012 | DEV | Healthchecks on every service | P1-011 | `docker-compose.yml` | `ps` shows all healthy | COMPLETED |
| P1-013 | DEV | `Makefile` with runtime auto-detection (docker/podman) + all dev targets | P1-004 | `Makefile` | `make help`; `make up` works on this host (podman) | COMPLETED |
| P1-014 | DEV | README + `docs/DEPLOYMENT.md` local setup | P1-013 | `README.md` | A new dev can start with one command | COMPLETED |
| P1-015 | DEV | CI workflow (lint, typecheck, tests, build) | P1-013 | `.github/workflows/ci.yml` | Workflow file valid | COMPLETED |

## Phase 2 — Database

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P2-001 | A1 | `pyproject.toml`, dependency pinning, package layout, ruff/mypy config | P1-005 | `backend/pyproject.toml` | `pip install -e .` works | COMPLETED |
| P2-002 | A1 | Settings/config module (pydantic-settings, all env vars, no defaults for secrets) | P2-001 | `…/config.py` | Unit test: missing secret raises | COMPLETED |
| P2-003 | A1 | Async engine/session factory, health probe | P2-002 | `…/db/session.py` | Integration test connects | COMPLETED |
| P2-004 | A1 | SQLAlchemy models for all 15 tables incl. GeoAlchemy2 columns | P2-003 | `…/db/models.py` | Import test; column parity test vs DATABASE.md | COMPLETED |
| P2-005 | A1 | Enums + CHECK constraints (status, provenance, factor ranges) | P2-004 | `…/db/models.py` | Constraint violation tests | COMPLETED |
| P2-006 | A1 | Spatial indexes (GiST) on all geometry columns | P2-004 | migration | `pg_indexes` assertion test | COMPLETED |
| P2-007 | A1 | Temporal + composite indexes | P2-004 | migration | `pg_indexes` assertion test | COMPLETED |
| P2-008 | A1 | Unique constraints (mmsi, product_id, ais dedup, attribution) | P2-004 | migration | Duplicate-insert tests | COMPLETED |
| P2-009 | A1 | Alembic setup + `0001_initial` (up **and** down) | P2-004 | `…/db/migrations/` | `upgrade head` then `downgrade base` clean | COMPLETED |
| P2-010 | A1 | Repository layer (typed, ownership-scoped, paginated) | P2-009 | `…/db/repositories/*.py` | Unit + integration tests | COMPLETED |
| P2-011 | A1 | Seed script (admin, analyst, model version, demo case) | P2-010 | `…/db/seed.py` | `make seed` idempotent | COMPLETED |
| P2-012 | QA | Spatial query test suite (7 representative queries from DATABASE.md §4) | P2-010 | `backend/tests/gis/` | All pass against real PostGIS | TODO |
| P2-013 | QA | Migration up/down/reset tests | P2-009 | `backend/tests/integration/test_migrations.py` | Pass | COMPLETED |

## Phase 3 — FastAPI core

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P3-001 | A1 | App factory, lifespan, CORS, router mounting | P2-003 | `…/api/app.py` | `/health` 200 | COMPLETED |
| P3-002 | A1 | Structured JSON logging + request id middleware | P3-001 | `…/api/middleware.py` | Log contains request_id, no secrets | COMPLETED |
| P3-003 | A1 | Error envelope + exception handlers for domain errors | P3-001 | `…/api/errors.py` | No stack traces leak; 4xx/5xx shapes tested | COMPLETED |
| P3-004 | A1 | Pydantic v2 schemas for every resource in API.md | P3-001 | `…/api/schemas/` | OpenAPI matches API.md | COMPLETED |
| P3-005 | A1 | GeoJSON validation helpers (valid polygon, area cap, ring order) | P3-004 | `…/core/geometry.py` | Unit tests incl. self-intersection | COMPLETED |
| P3-006 | SEC | Auth: Argon2id hashing, JWT access + rotating refresh, deps | P3-004 | `…/api/auth.py` | Unit + integration tests | COMPLETED |
| P3-007 | SEC | Rate limiting on `/auth/*` and job creation | P3-006 | `…/api/ratelimit.py` | 429 test | COMPLETED |
| P3-008 | A1 | Case service + repository + ownership checks | P3-004 | `…/api/routers/cases.py` | CRUD tests + IDOR test | COMPLETED |
| P3-009 | A1 | Case endpoints (create/list/get/patch/archive/delete) | P3-008 | same | Contract tests | COMPLETED |
| P3-010 | A1 | Job model/service/endpoints (+ retry, cancel) | P3-004 | `…/api/routers/jobs.py` | Status transition tests | COMPLETED |
| P3-011 | A1 | SSE event stream for job updates | P3-010 | `…/api/routers/events.py` | Integration test receives events | COMPLETED |
| P3-012 | A1 | System status / providers endpoints (UI-010) | P3-001 | `…/api/routers/system.py` | Reports real component health | COMPLETED |
| P3-013 | A1 | OpenAPI polish: tags, examples, security scheme | P3-009 | `…/api/app.py` | `/docs` renders; schema snapshot test | COMPLETED |
| P3-014 | QA | API integration test suite | P3-013 | `backend/tests/integration/` | All endpoints covered | IN_PROGRESS |

## Phase 4 — Frontend foundation

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P4-001 | A2 | Next.js 15 app-router project, TS strict, path aliases | P1-006 | `frontend/` | `npm run build` passes | COMPLETED |
| P4-002 | A2 | Design system: tokens, dark/light, typography, spacing | P4-001 | `frontend/src/styles/` | Storybook-free visual check + contrast audit | COMPLETED |
| P4-003 | A2 | UI primitives (Button, Input, Select, Dialog, Table, Badge, Toast, Skeleton, EmptyState, ErrorState) | P4-002 | `frontend/src/components/ui/` | Each has loading/empty/error/disabled states | COMPLETED |
| P4-004 | A2 | App shell: sidebar nav, header, breadcrumbs, responsive | P4-003 | `frontend/src/app/(app)/layout.tsx` | Works desktop/tablet/mobile | COMPLETED |
| P4-005 | A2 | Typed API client generated from OpenAPI + TanStack Query hooks | P3-013 | `frontend/src/lib/api/` | Types match backend; error mapping tested | COMPLETED |
| P4-006 | A2 | Auth flow: login page, session, protected routes, refresh | P3-006 | `frontend/src/app/login/` | UI-001 acceptance | COMPLETED |
| P4-007 | A2 | Case list page with filters/pagination/empty/error states | P4-005 | `…/cases/page.tsx` | UI-002 | COMPLETED |
| P4-008 | A2 | Create case page with map AOI draw + validation | P4-005 | `…/cases/new/page.tsx` | UI-003; invalid AOI rejected client+server | COMPLETED |
| P4-009 | A2 | MapLibre wrapper: basemap, controls, layer registry, hover/click | P4-004 | `frontend/src/components/map/` | Renders, no console errors, keyboard accessible | COMPLETED |
| P4-010 | A2 | Investigation page shell with layer panel + timeline placeholder | P4-009 | `…/cases/[id]/page.tsx` | UI-004 shell | COMPLETED |
| P4-011 | A2 | Global error boundary, 404, loading skeletons, toasts | P4-004 | `frontend/src/app/` | NFR-012 | COMPLETED |
| P4-012 | QA | Frontend unit/component tests (Vitest + Testing Library) | P4-011 | `frontend/tests/` | Pass | COMPLETED |

## Phase 5 — Deterministic demo investigation pipeline (dummy-first)

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P5-001 | A4 | Scenario definition format + `kutch-01` scenario (seeded, reproducible) | P2-011 | `…/demo/scenarios.py` | Same seed → identical output (hash test) | COMPLETED |
| P5-002 | A4 | Synthetic spill polygon generator (realistic elongated slick) | P5-001 | `…/demo/spill.py` | Valid geometry, plausible area | COMPLETED |
| P5-003 | A4 | Synthetic oil probability raster generator (GeoTIFF → MinIO) | P5-002 | `…/demo/raster.py` | Readable by rasterio, correct CRS | COMPLETED |
| P5-004 | A4 | Synthetic origin probability region + density grid | P5-002 | `…/demo/origin.py` | Contours nested, probabilities monotone | COMPLETED |
| P5-005 | A4 | Synthetic AIS generator: ≥6 vessels incl. one strong, two weak candidates, one with a gap | P5-001 | `…/demo/ais.py` | Deterministic; positions physically plausible | COMPLETED |
| P5-006 | A4 | Synthetic environmental fields (wind + current) | P5-001 | `…/demo/environment.py` | Consistent with drift used | COMPLETED |
| P5-007 | A4 | Wire `demo.seed` job that populates every table for a case | P5-002..006 | `…/worker/handlers/demo.py` | All 15 tables populated; provenance SYNTHETIC | COMPLETED |
| P5-008 | A1 | `POST /api/v1/demo/cases` endpoint | P5-007 | `…/api/routers/demo.py` | Returns a complete case | COMPLETED |
| P5-009 | A2 | Map renders all demo layers | P5-008 | `frontend/src/components/map/layers/` | All 8 layers visible & toggleable | COMPLETED |
| P5-010 | A2 | Vessel ranking UI with factor breakdown bars | P5-008 | `…/cases/[id]/ranking/` | UI-007; all 6 factors shown | COMPLETED |
| P5-011 | A2 | Score explanation UI (per-factor text + evidence) | P5-010 | same | SCORE-007 satisfied | COMPLETED |
| P5-012 | A2 | Timeline component (scene time, inferred window, AIS coverage) | P5-009 | `frontend/src/components/timeline/` | Scrub updates map | COMPLETED |
| P5-013 | QA | End-to-end demo investigation test | P5-012 | `backend/tests/e2e/` | Case → … → report with zero external calls (FR-020) | TODO |

## Phase 6 — Redis queue + workers

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P6-001 | A1 | `JobQueue` abstraction (enqueue/claim/ack/nack/heartbeat) | P2-010 | `…/worker/queue.py` | Unit tests with fakeredis | COMPLETED |
| P6-002 | A1 | Worker runtime: registry, dispatch, graceful shutdown, concurrency | P6-001 | `…/worker/runtime.py` | Handles SIGTERM cleanly | COMPLETED |
| P6-003 | A1 | Job persistence + status transitions in DB (source of truth) | P6-002 | `…/worker/state.py` | Transition table tested | COMPLETED |
| P6-004 | A1 | Progress reporting API from handlers | P6-003 | `…/worker/context.py` | Progress visible via API | COMPLETED |
| P6-005 | A1 | Retry with exponential backoff + max attempts | P6-003 | `…/worker/runtime.py` | Retry test | COMPLETED |
| P6-006 | A1 | Failure handling: error codes, no secret leakage, dead-letter | P6-005 | `…/worker/errors.py` | Failure tests | COMPLETED |
| P6-007 | A1 | Stale-claim reaper (crashed worker recovery) | P6-003 | `…/worker/reaper.py` | Kill-worker test recovers job | COMPLETED |
| P6-008 | A1 | Pipeline DAG orchestration (stage chaining, skip, resume) | P6-004 | `…/worker/pipeline.py` | DAG tests incl. partial failure | COMPLETED |
| P6-009 | A2 | Frontend job progress UI + SSE subscription | P3-011 | `frontend/src/components/jobs/` | QUEUED→RUNNING→COMPLETED/FAILED visible | COMPLETED |
| P6-010 | QA | Worker integration tests (real redis + postgres) | P6-008 | `backend/tests/integration/` | Pass | TODO |

| P6-011 | A1 | Worker restart safety: re-enqueue DB-QUEUED jobs missing from Redis at startup (a restart during a retry backoff stranded them) | P6-008 | `backend/src/spilltrace/worker/runtime.py`, `worker/queue.py` | `worker_reconciled_queued count=6` observed; ST-2026-0001 settled COMPLETED | COMPLETED |
| P6-012 | A4 | `ais.ingest` with a live-only provider (AISStream) hands off to positions already stored for the window instead of failing the pipeline | AIS-011 | `backend/src/spilltrace/worker/handlers/ais.py` | Completes as no-data with the stated reason; later stages use stored positions | COMPLETED |

## Phase 7 — Sentinel-1 catalogue search

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P7-001 | A3 | `SatelliteCatalogue` port + models | P6-002 | `…/core/ports.py` | Protocol typed | COMPLETED |
| P7-002 | A3 | CDSE auth (token acquisition, refresh, caching, server-side only) | P7-001, P0-016 | `…/adapters/satellite/cdse_auth.py` | Unit tests with mocked HTTP | COMPLETED |
| P7-003 | A3 | CDSE catalogue adapter (OData and/or STAC) | P7-002 | `…/adapters/satellite/cdse.py` | Recorded-response tests | COMPLETED |
| P7-004 | A3 | AOI → provider query translation (geometry, WKT, footprint) | P7-003 | same | Unit tests | COMPLETED |
| P7-005 | A3 | Time-window + product-type + polarization filters | P7-003 | same | Unit tests | COMPLETED |
| P7-006 | A3 | Scene ranking/selection heuristic (coverage %, mode, polarization, recency) | P7-005 | `…/core/scene_selection.py` | Unit tests | COMPLETED |
| P7-007 | A3 | Persist scenes + `case_scenes` link | P7-006 | `…/worker/handlers/scene_search.py` | Integration test | COMPLETED |
| P7-008 | A1 | Scene endpoints | P7-007 | `…/api/routers/scenes.py` | Contract tests | COMPLETED |
| P7-009 | A2 | Scene selection UI (list + footprint on map) | P7-008 | `…/cases/[id]/scenes/` | UI works with fixture provider | COMPLETED |
| P7-010 | QA | Fixture catalogue provider + tests; failure tests (provider down, no scenes) | P7-003 | `…/adapters/satellite/fixture.py` | Graceful failures | COMPLETED |

## Phase 8 — Sentinel-1 download

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P8-001 | A3 | `ObjectStore` port + S3/MinIO implementation (multipart, presign) | P1-009 | `…/adapters/storage/` | Integration test against MinIO | COMPLETED |
| P8-002 | A3 | Streaming downloader with resume + progress callbacks | P7-003 | `…/adapters/satellite/download.py` | Progress test | COMPLETED |
| P8-003 | A3 | GRD/ZIP validation (format, manifest, expected bands) | P8-002 | `…/core/product_validation.py` | Corrupt-file test | COMPLETED |
| P8-004 | A3 | Checksum (sha256) + size + artifact registration | P8-003 | `…/worker/handlers/scene_download.py` | Checksum recorded | COMPLETED |
| P8-005 | A3 | Retry/backoff + partial-download cleanup | P8-002 | same | Failure tests | COMPLETED |
| P8-006 | QA | Failure tests: 401, 404, network drop, disk full, corrupt archive | P8-005 | `backend/tests/integration/` | All fail gracefully | IN_PROGRESS |

## Phase 9 — SAR preprocessing

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P9-001 | A3 | Raster reader abstraction (rasterio, windowed reads) | P8-004 | `…/ml/raster.py` | Unit tests on fixture GeoTIFF | COMPLETED |
| P9-002 | A3 | CRS handling + geotransform preservation | P9-001 | `…/core/geo.py` | Round-trip pixel↔lonlat test | COMPLETED |
| P9-003 | A3 | VV/VH band extraction incl. missing-band handling | P9-001 | `…/ml/preprocess.py` | Single-pol scene handled | COMPLETED |
| P9-004 | A3 | Calibration to σ0 / dB conversion + documented normalization | P9-003 | same | Value-range tests | COMPLETED |
| P9-005 | A3 | Invalid/no-data/land masking | P9-004 | same | Mask correctness test | COMPLETED |
| P9-006 | A3 | Tiling with overlap + tile georeferencing metadata | P9-005 | `…/ml/tiling.py` | Reconstruct-from-tiles test | COMPLETED |
| P9-007 | A3 | Tile artifacts to object storage + metadata rows | P9-006 | `…/worker/handlers/sar_preprocess.py` | Integration test | COMPLETED |
| P9-008 | QA | Preprocessing tests incl. corrupt raster, wrong CRS, empty scene | P9-007 | `backend/tests/gis/` | Graceful failure | IN_PROGRESS |

## Phase 10 — ML dataset

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P10-001 | A3 | Dataset downloader (Zenodo record, resumable, checksum) | P0-016 | `ml/scripts/download_dataset.py` | Dry-run + checksum test | COMPLETED |
| P10-002 | A3 | Dataset validator (counts, shapes, channels, mask values) — fails loudly | P10-001 | `ml/src/dataset/validate.py` | Reports actual vs expected | COMPLETED |
| P10-003 | A3 | On-disk organization + manifest with per-file hash | P10-002 | `ml/src/dataset/manifest.py` | Manifest reproducible | COMPLETED |
| P10-004 | A3 | PyTorch `Dataset`/`DataLoader` (VV/VH + mask, tiling, caching) | P10-003 | `ml/src/dataset/sar_dataset.py` | Shape/dtype tests | COMPLETED |
| P10-005 | A3 | Augmentation (flips, rot90, speckle-aware) — train split only | P10-004 | `ml/src/dataset/augment.py` | Determinism-with-seed test | IN_PROGRESS |
| P10-006 | A3 | Split policy preventing leakage (scene-level, not tile-level) | P10-003 | `ml/src/dataset/splits.py` | No overlap test | IN_PROGRESS |
| P10-007 | A3 | Synthetic fallback dataset so ML tests run without the download | P10-004 | `ml/src/dataset/synthetic.py` | Tests pass offline | COMPLETED |
| P10-008 | QA | Dataset tests | P10-007 | `ml/tests/` | Pass | IN_PROGRESS |

## Phase 11 — U-Net

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P11-001 | A3 | U-Net architecture (configurable depth/width, 2-channel in) | P10-004 | `ml/src/models/unet.py` | Shape test; param count logged | COMPLETED |
| P11-002 | A3 | Config system (YAML) covering device/CPU-GPU switch | P11-001 | `ml/configs/` | GPU run = config change only | COMPLETED |
| P11-003 | A3 | Losses: BCE, Dice, Focal-Tversky, combo | P11-001 | `ml/src/losses.py` | Known-value unit tests | COMPLETED |
| P11-004 | A3 | Training loop (AMP-ready, deterministic seed, resumable) | P11-003 | `ml/src/train.py` | Overfit-10-samples test | COMPLETED |
| P11-005 | A3 | Validation loop + early stopping | P11-004 | same | Runs | COMPLETED |
| P11-006 | A3 | Metrics: Dice, IoU, Precision, Recall (+ threshold sweep) | P11-004 | `ml/src/metrics.py` | Verified against hand-computed values | COMPLETED |
| P11-007 | A3 | Checkpointing + best-model selection | P11-005 | `ml/src/checkpoint.py` | Resume test | COMPLETED |
| P11-008 | A3 | Model registry write-back (`model_versions` row, artifact to MinIO) | P11-007 | `ml/src/registry.py` | Row + artifact + checksum | IN_PROGRESS |
| P11-009 | A3 | Experiment manifest (config, git sha, data hash, seed, env) | P11-004 | `ml/src/manifest.py` | Reproducibility fields present | COMPLETED |
| P11-010 | A3 | Inference script (tiles → mask) | P11-008 | `ml/src/infer.py` | Matches training preprocessing | COMPLETED |
| P11-011 | A3 | **Honest** metrics report — measured only, never fabricated | P11-006 | `docs/ML_PIPELINE.md` | Reported numbers reproducible from checkpoint | IN_PROGRESS |

## Phase 12 — Real inference

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P12-001 | A3 | Inference worker handler | P11-010, P9-007 | `…/worker/handlers/ml_detect.py` | Integration test | COMPLETED |
| P12-002 | A3 | Probability raster assembly (tile stitching, overlap blending) | P12-001 | `…/ml/stitch.py` | Seam test | COMPLETED |
| P12-003 | A3 | Configurable threshold + hysteresis | P12-002 | `…/core/masking.py` | Unit tests | COMPLETED |
| P12-004 | A3 | Mask + probability raster stored to object storage | P12-002 | `…/worker/handlers/ml_detect.py` | Artifacts registered | COMPLETED |
| P12-005 | A3 | Morphological cleanup (open/close, min-area) — justified & configurable | P12-003 | `…/core/masking.py` | Before/after tests | COMPLETED |
| P12-006 | A3 | Polygonization + geodesic area/perimeter | P12-005 | `…/core/polygonize.py` | GIS tests vs known shapes | COMPLETED |
| P12-007 | A3 | Detection confidence definition + computation | P12-006 | `…/core/confidence.py` | Documented formula, unit tested | COMPLETED |
| P12-008 | A3 | Model version tracking on every detection | P12-001 | same | FK non-null test | COMPLETED |
| P12-009 | A2 | Probability raster tiles on the map | P12-004 | `frontend/src/components/map/` | Layer renders | COMPLETED |
| P12-010 | QA | Tests: no detection, whole-scene detection, missing model, invalid mask | P12-006 | `backend/tests/` | Graceful | IN_PROGRESS |

| P12-010 | A3 | Integrate the Colab-trained ResNet-34 smp U-Net checkpoint (`ml/runs/colab-resnet34-run3`) | P12-001 | `backend/src/spilltrace/ml/resnet_unet.py`, `ml/inference.py`, `worker/handlers/sar.py`, `ml/scripts/register_model.py` | Bit-exact vs smp 0.5.0 (max |Δ| 0.0); registered as spilltrace-unet 0.2.0 (active, validation metrics labelled); ml.detect on ST-2026-0001: 9 tiles @256/192, max p 0.99, 1014 km², MIXED; 7 unit tests (AD-33) | COMPLETED |

## Phase 13 — Look-alike verification

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P13-001 | A3 | Feature extraction from mask + raster (geometry, contrast, texture) | P12-006 | `…/core/lookalike/features.py` | Unit tests vs synthetic shapes | COMPLETED |
| P13-002 | A3 | Wind-based verification rule (low-wind and high-wind exclusion windows) | P13-001, DATA-003 | `…/core/lookalike/rules.py` | Threshold tests with cited values | COMPLETED |
| P13-003 | A3 | Shape rules (area, complexity, compactness, elongation) | P13-001 | same | Unit tests | COMPLETED |
| P13-004 | A3 | Contrast/backscatter rules (slick-vs-background dB, gradient) | P13-001 | same | Unit tests | COMPLETED |
| P13-005 | A3 | Transparent rule engine (weighted, each rule reports observed vs threshold) | P13-002..004 | `…/core/lookalike/engine.py` | Deterministic; explanations non-empty | COMPLETED |
| P13-006 | A3 | Verification confidence + status mapping | P13-005 | same | Boundary tests | COMPLETED |
| P13-007 | A3 | Plain-language explanation generator | P13-005 | `…/core/lookalike/explain.py` | Snapshot tests | COMPLETED |
| P13-008 | A3 | Optional classifier abstraction (pluggable, off by default) | P13-005 | `…/core/lookalike/classifier.py` | Interface test | COMPLETED |
| P13-009 | A2 | Verification UI on Spill Details | P13-006 | `…/cases/[id]/spill/` | UI-005 | COMPLETED |
| P13-010 | QA | Evaluate on the public look-alike test set; report real numbers | P13-005, P10-002 | `ml/scripts/eval_lookalike.py` | AC-05; honest metrics | IN_PROGRESS |

## Phase 14 — Environmental data

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P14-001 | A4 | `EnvironmentalProvider` port + data model (grid, units, CRS, time axis) | P6-002 | `…/core/ports.py` | Typed | COMPLETED |
| P14-002 | A4 | Wind adapter (configured source) | P14-001, P0-016 | `…/adapters/environmental/wind.py` | Mocked-response tests | COMPLETED |
| P14-003 | A4 | Current adapter (Copernicus Marine) | P14-001 | `…/adapters/environmental/current.py` | Mocked-response tests | COMPLETED |
| P14-004 | A4 | Spatial subsetting (bbox + buffer) | P14-002 | `…/core/env_subset.py` | Unit tests | COMPLETED |
| P14-005 | A4 | Temporal subsetting incl. backward window for hindcast | P14-004 | same | Unit tests | COMPLETED |
| P14-006 | A4 | Storage of NetCDF subsets + summary stats to DB (CON-005) | P14-005 | `…/worker/handlers/env_fetch.py` | No blobs in Postgres | COMPLETED |
| P14-007 | A4 | Reproducibility metadata (dataset id, version, request params) | P14-006 | same | Manifest complete | COMPLETED |
| P14-008 | A4 | Synthetic environmental provider (deterministic, labelled) | P14-001 | `…/adapters/environmental/synthetic.py` | Deterministic test | COMPLETED |
| P14-009 | QA | Failure tests: credentials missing, dataset unavailable, empty subset | P14-006 | `backend/tests/` | Graceful | IN_PROGRESS |

## Phase 15 — OpenDrift / OpenOil

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P15-001 | A4 | `DriftEngine` port (forward/backward/ensemble, seeded) | P14-001 | `…/core/ports.py` | Typed | COMPLETED |
| P15-002 | A4 | Analytical drift engine (advection + diffusion, fully deterministic) | P15-001 | `…/adapters/drift/analytical.py` | Conservation + determinism tests | COMPLETED |
| P15-003 | A4 | OpenOil adapter: readers, seeding, config | P15-001, P0-016 | `…/adapters/drift/openoil.py` | Runs in the drift image | IN_PROGRESS |
| P15-004 | A4 | Environmental forcing injection from env runs | P15-003 | same | Field-value test | IN_PROGRESS |
| P15-005 | A4 | Particle initialization from spill polygon (area-weighted) | P15-002 | `…/core/seeding.py` | Distribution test | COMPLETED |
| P15-006 | A4 | Forward simulation (validation of the setup) | P15-005 | `…/worker/handlers/drift.py` | Sanity test vs known drift | COMPLETED |
| P15-007 | A4 | Backward/hindcast simulation | P15-006 | same | Reverses a forward run within tolerance | COMPLETED |
| P15-008 | A4 | Ensemble runs (seed + parameter perturbation) | P15-007 | `…/core/ensemble.py` | Spread increases with uncertainty | COMPLETED |
| P15-009 | A4 | Particle persistence (decimated to DB, full to object storage) | P15-008 | `…/worker/handlers/drift.py` | CON-005 respected | COMPLETED |
| P15-010 | A4 | Kernel density → probability grid → nested contours | P15-009 | `…/core/density.py` | Monotone contours; sum-to-1 test | COMPLETED |
| P15-011 | A4 | Origin probability region + `origin_confidence` + inferred discharge window (A-02) | P15-010 | `…/core/origin.py` | Documented method, unit tested | COMPLETED |
| P15-012 | A4 | Reproducibility: same seed+params+forcing → identical region (AC-07) | P15-011 | `backend/tests/unit/test_drift_repro.py` | Hash equality | IN_PROGRESS |
| P15-013 | A2 | Drift view: particle animation + contour rendering | P15-011 | `…/cases/[id]/drift/` | UI-006 | COMPLETED |
| P15-014 | QA | Failure tests: OpenDrift unavailable, no forcing, degenerate polygon | P15-011 | `backend/tests/` | Falls back with clear labelling | IN_PROGRESS |

## Phase 16 — AIS ingestion

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| AIS-001 | A4 | `AISProvider` port + normalized message model | P6-002 | `…/core/ports.py` | Typed | COMPLETED |
| AIS-002 | A4 | AISStream configuration (server-side key handling, never to client) | AIS-001 | `…/adapters/ais/config.py` | Secret-leak test | COMPLETED |
| AIS-003 | A4 | Server-side WebSocket client with backoff/reconnect | AIS-002 | `…/adapters/ais/aisstream.py` | Reconnect test | IN_PROGRESS |
| AIS-004 | A4 | Bounding-box subscription builder | AIS-003 | same | Unit tests | COMPLETED |
| AIS-005 | A4 | Message parser (PositionReport, ShipStaticData, ClassB) | AIS-003 | `…/adapters/ais/parser.py` | Fixture-message tests | COMPLETED |
| AIS-006 | A4 | MMSI validation (9 digits, MID lookup, non-ship ranges) | AIS-005 | `…/core/ais/validate.py` | Unit tests | COMPLETED |
| AIS-007 | A4 | Timestamp validation + normalization to UTC | AIS-005 | same | Unit tests | COMPLETED |
| AIS-008 | A4 | Coordinate + sentinel-value validation (lat 91 / lon 181 / COG 360 / HDG 511) | AIS-005 | same | Unit tests | COMPLETED |
| AIS-009 | A4 | Position persistence with upsert + vessel upsert | AIS-008 | `…/db/repositories/ais.py` | Integration test | COMPLETED |
| AIS-010 | A4 | Duplicate detection (DB unique + in-memory window) | AIS-009 | same | Duplicate test | COMPLETED |
| AIS-011 | A4 | Ingestor service lifecycle (long-lived, health, metrics) | AIS-003 | `…/worker/ais_ingestor.py` | Runs as its own container; idles with a stated reason when unconfigured, streams AISStream into `vessels`/`ais_positions` in batches when configured (verified: subscribed 2026-09-12) | COMPLETED |
| AIS-012 | A4 | Synthetic AIS provider implementing the same port | AIS-001 | `…/adapters/ais/synthetic.py` | Deterministic | COMPLETED |
| AIS-013 | QA | Unit tests for parser/validators | AIS-008 | `backend/tests/unit/` | Pass | COMPLETED |
| AIS-014 | QA | Integration tests (fake WS server → PostGIS) | AIS-011 | `backend/tests/integration/` | Pass | IN_PROGRESS |
| AIS-015 | A4 | Monitoring: messages/sec, rejects, last-message age | AIS-011 | `…/api/routers/system.py` | Visible on Admin page | IN_PROGRESS |
| AIS-016 | QA | End-to-end AIS verification (ingest → clean → trajectory → map) | AIS-014 | `backend/tests/e2e/` | AC-08 | IN_PROGRESS |

## Phase 17 — AIS cleaning + trajectories

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P17-001 | A4 | Deduplication (exact + near-duplicate within tolerance) | AIS-009 | `…/core/ais/clean.py` | Unit tests | COMPLETED |
| P17-002 | A4 | Coordinate validation (range, land check optional, null island) | P17-001 | same | Unit tests | COMPLETED |
| P17-003 | A4 | Temporal validation (future, epoch-zero, out-of-order) | P17-001 | same | Unit tests | COMPLETED |
| P17-004 | A4 | Impossible-jump detection (implied speed vs threshold, cited) | P17-003 | same | Unit tests | COMPLETED |
| P17-005 | A4 | Gap detection + gap statistics (**never labelled as wrongdoing** — CON-002) | P17-004 | `…/core/ais/gaps.py` | Wording asserted by test | COMPLETED |
| P17-006 | A4 | SOG plausibility + smoothing | P17-004 | `…/core/ais/clean.py` | Unit tests | COMPLETED |
| P17-007 | A4 | COG/heading consistency vs computed bearing | P17-006 | same | Unit tests | COMPLETED |
| P17-008 | A4 | Trajectory construction (ordering, segmentation on gaps, LineString) | P17-005 | `…/core/ais/trajectory.py` | GIS tests | COMPLETED |
| P17-009 | A4 | Trajectory statistics + quality score (feeds SCORE-006) | P17-008 | same | Unit tests | COMPLETED |
| P17-010 | A4 | PostGIS storage + case linkage | P17-009 | `…/worker/handlers/traj_build.py` | Integration test | COMPLETED |
| P17-011 | QA | Cleaning/trajectory test suite incl. pathological inputs | P17-010 | `backend/tests/unit/`, `gis/` | Pass | COMPLETED |

## Phase 18 — Vessel correlation

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P18-001 | A4 | Spatial candidate query (positions/trajectory ∩ origin region + buffer) | P15-011, P17-010 | `…/db/repositories/correlation.py` | GIS tests | COMPLETED |
| P18-002 | A4 | Temporal candidate query (inferred discharge window ± tolerance) | P18-001 | same | Unit tests | COMPLETED |
| P18-003 | A4 | Origin-overlap measures (min distance, contour percentile, dwell time) | P18-002 | `…/core/correlation.py` | Unit tests | COMPLETED |
| P18-004 | A4 | Trajectory compatibility (entering/leaving geometry relative to origin) | P18-003 | same | Unit tests | COMPLETED |
| P18-005 | A4 | Candidate generation + configurable inclusion thresholds | P18-004 | `…/worker/handlers/correlate.py` | Integration test | COMPLETED |
| P18-006 | A4 | Candidate filtering + **no padding** when fewer than 3 exist (A-10) | P18-005 | same | Test asserts honest empty/short lists | COMPLETED |
| P18-007 | A4 | Per-candidate inclusion explanation | P18-005 | `…/core/correlation.py` | Non-empty explanation test | COMPLETED |
| P18-008 | QA | Correlation tests incl. zero-candidate and many-candidate cases | P18-006 | `backend/tests/` | Pass | TODO |

## Phase 19 — Scoring

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P19-001 | A4 | Scoring domain model (factors, weights, versioned config) | P18-005 | `…/core/scoring/model.py` | Weights sum to 1.0 test | COMPLETED |
| P19-002 | A4 | Origin proximity factor (0.35) — normalized, documented | P19-001 | `…/core/scoring/factors.py` | Boundary + monotonicity tests | COMPLETED |
| P19-003 | A4 | Time match  factor (0.20) | P19-001 | same | Same | COMPLETED |
| P19-004 | A4 | Trajectory match factor (0.15) | P19-001 | same | Same | COMPLETED |
| P19-005 | A4 | Heading match factor (0.10) | P19-001 | same | Same | COMPLETED |
| P19-006 | A4 | Speed match factor (0.10) | P19-001 | same | Same | COMPLETED |
| P19-007 | A4 | AIS reliability factor (0.10) — definition per A-03 | P19-001 | same | Same; gaps lower but never zero unfairly | COMPLETED |
| P19-008 | A4 | Aggregation + rank + tie-breaking | P19-002..007 | `…/core/scoring/engine.py` | Golden-case tests | COMPLETED |
| P19-009 | A4 | Per-factor explanation + evidence generation | P19-008 | `…/core/scoring/explain.py` | Every factor has non-empty text | COMPLETED |
| P19-010 | A4 | Persistence of all factors + weights + version | P19-008 | `…/worker/handlers/score.py` | DB round-trip test | COMPLETED |
| P19-011 | SEC/A0 | Disclaimer enforcement in API + UI + report (CON-001/003, AC-13) | P19-010 | `…/api/schemas/attribution.py` | `test_disclaimers.py` | COMPLETED |
| P19-012 | QA | Scoring test suite incl. adversarial cases (nearest≠guilty, gap≠guilt) | P19-011 | `backend/tests/unit/test_scoring.py` | Pass | COMPLETED |

## Phase 20 — Investigation dashboard

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P20-001 | A2 | Investigation map: all 8 layers, ordering, legend, opacity | P5-009 | `frontend/src/components/map/` | UI-004 / FR-017 | COMPLETED |
| P20-002 | A2 | Timeline with playback synchronized to map | P20-001 | `…/timeline/` | Scrubbing updates particles + vessels | COMPLETED |
| P20-003 | A2 | Spill details page | P13-009 | `…/cases/[id]/spill/` | UI-005 | COMPLETED |
| P20-004 | A2 | Drift view page | P15-013 | `…/cases/[id]/drift/` | UI-006 | COMPLETED |
| P20-005 | A2 | Vessel ranking page | P5-010 | `…/cases/[id]/ranking/` | UI-007 with all 6 factors | COMPLETED |
| P20-006 | A2 | Vessel details page (trajectory + AIS quality + timeline) | P20-005 | `…/vessels/[id]/` | UI-008 | COMPLETED |
| P20-007 | A2 | Evidence report page + export | P21-004 | `…/cases/[id]/report/` | UI-009 | COMPLETED |
| P20-008 | A2 | Admin page (health, providers, models, jobs) | P3-012 | `…/admin/` | UI-010 | COMPLETED |
| P20-009 | A2 | Accessibility pass (keyboard, focus, contrast, semantics, labels) | P20-008 | frontend | Audit checklist in TESTING.md | IN_PROGRESS |
| P20-010 | A2 | Responsive pass (desktop/tablet/mobile) | P20-009 | frontend | Manual + viewport tests | IN_PROGRESS |
| P20-011 | A2 | Remove all placeholders/dead links/fake buttons | P20-010 | frontend | Lint rule + review | IN_PROGRESS |

## Phase 21 — Evidence report

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P21-001 | A1 | Report data assembler (collects every case artifact + manifests) | P19-010 | `…/core/report/assemble.py` | All required sections present | COMPLETED |
| P21-002 | A1 | HTML renderer (accessible, printable, self-contained) | P21-001 | `…/core/report/html.py` | Snapshot test | COMPLETED |
| P21-003 | A1 | PDF export | P21-002 | `…/core/report/pdf.py` | File is valid PDF | COMPLETED |
| P21-004 | A1 | Store as evidence artifacts with checksums | P21-003 | `…/worker/handlers/report.py` | Artifact rows created | COMPLETED |
| P21-005 | A0 | Mandatory limitations/uncertainty section + disclaimer | P21-002 | `…/core/report/sections.py` | Asserted by test (AC-12/13) | COMPLETED |
| P21-006 | QA | Report content tests (sources, timestamps, model versions present) | P21-005 | `backend/tests/unit/test_report.py` | AC-12 | TODO |

## Phase 22 — Testing, failure modes, security, deployment

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P22-001 | QA | Failure-mode test matrix (all 22 scenarios from prompt §29) | P21-006 | `backend/tests/failure/` | All fail gracefully | IN_PROGRESS |
| P22-002 | QA | GIS test suite consolidation (CRS, validity, intersections, geodesy) | P12-006 | `backend/tests/gis/` | Pass | IN_PROGRESS |
| P22-003 | QA | ML test suite (shapes, channels, loading, determinism) | P11-010 | `ml/tests/` | Pass | IN_PROGRESS |
| P22-004 | QA | End-to-end suite: demo path **and** real path when credentials exist | P22-001 | `backend/tests/e2e/` | Pass/skip-with-reason | IN_PROGRESS |
| P22-005 | SEC | Security review against prompt §23 checklist | P22-001 | `docs/SECURITY.md` | All items assessed | IN_PROGRESS |
| P22-006 | SEC | Secret-leak audit of frontend bundle + repo | P22-005 | `infra/scripts/audit_secrets.sh` | `make audit-secrets` passes | COMPLETED |
| P22-007 | DEV | Production build + image build for all services | P22-004 | `infra/` | Images build | IN_PROGRESS |
| P22-008 | DEV | Deployment documentation | P22-007 | `docs/DEPLOYMENT.md` | Complete | IN_PROGRESS |
| P22-009 | A0 | Traceability matrix completion | P22-004 | `docs/TRACEABILITY.md` | Every requirement mapped | COMPLETED |
| P22-010 | A0 | Final audit | P22-009 | `docs/FINAL_AUDIT.md` | Every requirement: implementation + test + evidence | COMPLETED |

## Phase 23 — UI redesign ("Abyssal radar")

Conventions: `docs/DESIGN_SYSTEM.md`. Every figure on the new screens is computed from API data;
cross-case screens aggregate case-scoped endpoints via `useCaseUniverse` (`lib/api/aggregate.ts`).

| ID | Owner | Description | Deps | Primary files | Acceptance & tests | Status |
|---|---|---|---|---|---|---|
| P23-001 | A2 | Design tokens v2, self-hosted Geist / Instrument Serif, validated confidence ramp | — | `frontend/src/styles/tokens.css`, `app/layout.tsx` | Ordinal ramp passes the palette validator in both themes | COMPLETED |
| P23-002 | A2 | Motion system: GSAP (ScrollTrigger, SplitText, DrawSVG, MotionPath) + Lenis, reduced-motion safe | P23-001 | `frontend/src/lib/motion/`, `components/motion/` | Final state rendered under `prefers-reduced-motion`; no flash of hidden content | COMPLETED |
| P23-003 | A2 | UI kit, map overlays and shared page styles restyled (same class API) | P23-001 | `components/ui/ui.module.css`, `styles/pages.module.css`, `components/map/map.module.css` | Existing vitest suite green | COMPLETED |
| P23-004 | A2 | App shell: grouped nav registry, collapsible rail, command palette, notification centre, user menu, onboarding tour, route transitions | P23-003 | `components/layout/`, `components/shell/`, `app/(app)/template.tsx` | Tour, palette and notifications verified in headless Chrome | COMPLETED |
| P23-005 | A2 | Public landing: parallax hero, scrollytelling chain, pinned 13-stage rail; figures quoted from the live kutch-01 demo | P23-002 | `app/page.tsx`, `app/_landing/` | Claims re-verified against the running system on 2026-09-11 | COMPLETED |
| P23-006 | A2 | Sign-in redesign | P23-004 | `app/login/` | Redirect safety unchanged | COMPLETED |
| P23-007 | A2 | New screens: dashboard, situational map, analytics, vessel registry, activity feed, compare, ML Ops, help, transparency (public) | P23-004 | `app/(app)/{dashboard,map,analytics,vessels,activity,compare,ml-ops,help}/`, `app/transparency/` | Unknown values render as "—"; truncation stated | COMPLETED |
| P23-008 | A0 | Ranking evidence: band meter honouring server caps, contribution breakdown, rule-based plain-language reading, cross-case history, discrimination note verbatim | P23-007 | `app/(app)/cases/[caseId]/ranking/`, `components/attribution/PlainLanguageSummary.tsx` | Banned-vocabulary test still green | COMPLETED |
| P23-009 | A2 | Spill page before/after reveal of the oil-probability field | P23-003 | `components/detection/ModelOutputReveal.tsx` | Uses the manifest's `oil_probability` tiles | COMPLETED |
| P23-010 | A2 | Hindi / English language toggle | P23-007 | — | Server notices must stay verbatim; needs reviewed legal wording in Hindi | TODO |
| P23-011 | A1 | Backend: case ST-2026-0001 labelled REAL while its detections/vessels are SYNTHETIC | — | `backend/src/spilltrace/db/provenance.py`, `worker/pipeline.py` | Roll-up on pipeline settlement + backfill CLI; ST-2026-0001 now MIXED (AD-34) | COMPLETED |
| P23-012 | A1 | Backend: serve the `oil_probability` raster tiles the layer manifest already advertises | P13-009 | `backend/src/spilltrace/api/routers/probability.py` | Web-Mercator tiles from the latest PROBABILITY_RASTER artifact, confidence ramp, transparent outside footprint, 401 unauthenticated — verified with curl on ST-2026-0001 | COMPLETED |
| P23-013 | A2 | Imagery basemaps (Esri World Imagery / Ocean, CARTO Dark/Light, Offline) + globe projection + basemap switcher | P23-007 | `frontend/src/lib/map/basemaps.ts`, `components/map/{BasemapControl,useMap,MapView}.tsx`, `next.config.ts` | Tiles load under the CSP (593×200 in headless Chrome), attribution follows the basemap, Offline fallback on tile failure, preference persisted (AD-5 amendment) | COMPLETED |
| P23-014 | A2 | Admin page crash: `providers[].requires` is a string, frontend expected a list | — | `app/(app)/admin/page.tsx`, `lib/api/types.ts` | `/admin` renders; nested metric groups render as text | COMPLETED |
| P23-015 | A1 | `make demo` called a missing module | — | `backend/src/spilltrace/demo/create.py`, `Makefile` | Creates the kutch-01 case and queues the DEMO pipeline from the CLI | COMPLETED |
| P23-016 | A2 | UI v3 "glass & instrument": glass/neumorphic tokens, aurora backdrop, kit + shell restyle, new motion primitives, landing/login polish, dark default | P23-004 | `styles/tokens.css`, `components/ui`, `components/shell`, `components/motion`, `app/(app)/template.tsx` | vitest 154/154, tsc + eslint clean; screenshots reviewed in both themes; reduced-motion falls back to static CSS | COMPLETED |
