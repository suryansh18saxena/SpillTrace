# SPILLTRACE — Traceability Matrix

**Owner:** Agent 0 · Maps every requirement in `docs/REQUIREMENTS.md` to its
implementation and its verification. Updated as work lands; `docs/FINAL_AUDIT.md` holds
the pass/fail judgement.

Status: **Done** (implemented and verified) · **Partial** (works, with a stated limit) ·
**Pending** (not yet implemented).

---

## Functional requirements

| ID | Requirement | Implementation | Verification | Status |
|---|---|---|---|---|
| FR-001 | Case with AOI + time window | `api/routers/cases.py`, `db/repositories/cases.py`, `core/geometry.validate_polygon`, `core/time.validate_time_window` | `test_geometry.py`; live `POST /api/v1/cases` | Done |
| FR-002 | Sentinel-1 catalogue search | `adapters/satellite/{cdse,cdse_auth,fixture}.py`, `worker/handlers/satellite.py` | `test_sar_fixture.py`; live: 3 scenes catalogued and ranked | Partial (fixture verified; CDSE unexercised against live credentials) |
| FR-003 | Download GRD to object storage | `worker/handlers/satellite.py`, `adapters/storage/s3.py` | Live: selected scene downloaded, checksummed and registered as an artifact | Partial (fixture source) |
| FR-004 | SAR preprocessing to ML tiles | `ml/preprocess.py`, `ml/tiling.py`, `ml/stitch.py` | `test_sar_preprocess.py`, `test_sar_tiling.py`; live: `[3, 512, 512]` tiles, VV-only product handled with an explicit note | Done |
| FR-005 | U-Net oil probability mask | `ml/inference.py` (`AnalyticalDetector`, `UNetModel`) | `test_sar_inference.py` (torch cases skip when absent); live: probability field produced, output states no trained model was used | Partial (analytical detector; no checkpoint trained) |
| FR-006 | Threshold → polygonise → spill polygon | `core/masking.py`, `core/polygonize.py`, `core/confidence.py` | `test_masking.py`, `test_polygonize.py`; live on both paths (85.3 km² demo, 782.5 km² real), `ST_IsValid` true, geodesic area confirmed | Done |
| FR-007 | Look-alike verification, explainable | `core/lookalike/{features,rules,engine,explain}.py`, `worker/handlers/verify.py` | `test_lookalike.py` (29 tests); live: `VERIFIED` 0.907 at 5.4 m/s | Done |
| FR-008 | Wind and current retrieval | `adapters/environmental/`, `worker/handlers/drift.fetch_environment` | Live env run with summary stats, **and consumed by verification** after the AD-30 ordering fix (`wind_window applicable=true, 5.40 m/s`) | Partial (synthetic provider; CMEMS adapter pending) |
| FR-009 | Reverse drift | `adapters/drift/analytical.py`, `worker/handlers/drift.run_hindcast` | `test_drift_density.py` (19 tests) | Partial (analytical done; OpenOil optional) |
| FR-010 | Origin probability region | `core/density.py`, `core/report` | `test_drift_density.py` nesting/monotonicity; live: 522 km² with 90/75/50% contours | Done |
| FR-011 | AIS ingestion | `adapters/ais/synthetic.py`, `worker/handlers/ais.ingest_ais` | Live: 4 618 positions (demo) and 20 529 across 20 vessels (real path), upserted idempotently | Partial (synthetic done; AISStream adapter pending) |
| FR-012 | AIS cleaning | `core/ais/{validate,clean,gaps}.py`, `worker/handlers/ais.clean_ais` | `test_ais_*.py` (180 tests); live: 4 rejected of 4 618 | Done |
| FR-013 | Trajectories with gap statistics | `core/ais/trajectory.py`, `worker/handlers/ais.build_case_trajectories` | `test_ais_trajectory.py`; live: 8 segments across 6 vessels | Done |
| FR-014 | Vessel correlation | `core/correlation.py`, `worker/handlers/attribution.correlate_vessels` | `test_correlation.py` (24 tests); live: 4 of 6 vessels | Done |
| FR-015 | Six-factor scoring | `core/scoring/`, `worker/handlers/attribution.score_candidates` | `test_scoring*.py` (118 tests) | Done |
| FR-016 | Ranking with reasons | `core/scoring/engine.rank_candidates` | `test_scoring.py`; live ranking with per-factor explanations | Done |
| FR-017 | Investigation dashboard | `api/routers/layers.py`; all ten frontend pages | Live: 8 layers populated; 11/11 routes serve 200 against the live API; basemap makes zero external requests | Done |
| FR-018 | Evidence report | `core/report/`, `worker/handlers/report.py` | `test_report.py` (24 tests); live: 29 KB HTML, 11 sections | Done |
| FR-019 | Every stage is a tracked job | `worker/{queue,runtime,pipeline,context}.py`, `db/repositories/jobs.py` | live: 8-stage DAG QUEUED→RUNNING→COMPLETED | Done |
| FR-020 | Whole chain runs offline | `demo/`, `worker/pipeline.DEMO_ORDER` | live: full pipeline COMPLETED with zero external calls | Done |

## Services

| ID | Service | Implementation | Status |
|---|---|---|---|
| SVC-001 | Satellite | `adapters/satellite/` | Partial |
| SVC-002 | Preprocessing | `ml/preprocess.py` | Done |
| SVC-003 | ML | `ml/inference.py` | Partial |
| SVC-004 | Verification | `core/lookalike/` | Done |
| SVC-005 | Environmental | `adapters/environmental/` | Partial |
| SVC-006 | Drift | `adapters/drift/` | Partial |
| SVC-007 | AIS | `adapters/ais/`, `core/ais/` | Partial |
| SVC-008 | Trajectory | `core/ais/trajectory.py` | Done |
| SVC-009 | Correlation | `core/correlation.py` | Done |
| SVC-010 | Scoring | `core/scoring/` | Done |
| SVC-011 | Report | `core/report/` | Done |
| SVC-012 | Case | `api/routers/cases.py` | Done |
| SVC-013 | Job | `worker/`, `api/routers/jobs.py` | Done |
| SVC-014 | Auth | `api/auth.py`, `core/security.py` | Done |

## Database

All 15 entities plus `case_scenes` exist and are verified against a live PostGIS
instance: **17 application tables, 10 geometry columns (all SRID 4326), 10 GiST + 1 BRIN
+ 77 btree indexes, 31 check constraints, 8 unique constraints, 23 foreign keys, 4
partial unique indexes**, with a clean `upgrade → downgrade → upgrade` round trip.
DB-001…DB-015: **Done**.

## Frontend

| ID | Page | Status |
|---|---|---|
| UI-001 Login · UI-002 Case list · UI-003 Create case · UI-010 Admin | built, 102 tests | Done |
| UI-004 Investigation map | all 8 layers, timeline, particle animation | Done |
| UI-005 Spill · UI-006 Drift · UI-007 Ranking · UI-008 Vessel · UI-009 Report | built; 153 frontend tests | Done |

## Scoring

| ID | Requirement | Verification | Status |
|---|---|---|---|
| SCORE-001…006 | six factors at the PRD weights | `test_scoring_factors.py`; weights asserted to sum to 1.0 | Done |
| SCORE-007 | each factor stored, displayed, explained | `attributions` columns + `factor_explanations`; API returns all six with explanation text | Done |
| SCORE-008 | weights versioned and persisted | `scoring_version` + `weights` on every row | Done |

## Constraints

| ID | Constraint | How it is enforced | Status |
|---|---|---|---|
| CON-001 | nearest ≠ responsible | `PROXIMITY_DISCLAIMER` on every candidate list; a temporally incompatible near vessel ranks below a compatible distant one; no candidate without temporal overlap can reach HIGH; **and** `core/scoring/discrimination.py` caps every label when the origin region cannot separate the field (AD-31), verified live on 8 tied candidates | Done |
| CON-002 | AIS gap ≠ illegality | gaps lower `ais_reliability`; `AIS_GAP_DISCLAIMER` wherever a gap appears; a name-scan test forbids accusatory identifiers in `core/ais/gaps.py`; live demo shows 0.448 vs 0.820 | Done |
| CON-003 | score ≠ legal probability | `SCORE_DISCLAIMER` on every scored response and in the report | Done |
| CON-004 | no keys in the frontend | browser reaches only our API; CSP `connect-src`; `make audit-secrets` | Done |
| CON-005 | no large binaries in PostgreSQL | rasters/NetCDF/reports in MinIO; only `storage_uri` + checksum in the database | Done |
| CON-006 | no giant global system first | one case, one region, one scenario | Done |
| CON-007 | AIS coverage not complete | `AIS_COVERAGE_DISCLAIMER`; "absence is not evidence of absence" | Done |
| CON-008 | origin is a region | `origin_geometry` is a MultiPolygon with nested probability contours; no coordinate is ever emitted as "the origin" | Done |
| CON-009 | synthetic data labelled | `data_provenance` on every row and response; `(SYNTHETIC)` name suffix; notice leads the report | Done |

## Non-functional

| ID | Verification | Status |
|---|---|---|
| NFR-001 one-command startup | `make up` on a Podman-only host | Done |
| NFR-002 no heavy work in handlers | every stage is a job | Done |
| NFR-003 job observability | id/status/progress/step/attempt/error/result + SSE | Done |
| NFR-004 structured logs, no secrets | structlog + redaction processor | Done |
| NFR-005 reproducibility | `run_manifest` with seed, versions, checksums; drift fingerprint test | Done |
| NFR-006 blobs in object storage | verified | Done |
| NFR-007 auth | Argon2id + rotating JWT | Done |
| NFR-008 input validation | Pydantic + domain validators; bound parameters only | Done |
| NFR-009 no IDOR | ownership enforced in the repository; 404 not 403 | Done |
| NFR-010 rate limiting | auth and job creation | Done |
| NFR-011 graceful degradation | failure matrix in `docs/TESTING.md` §4; missing credentials fall back to fixtures with a logged reason; SSE returns 503 past its cap rather than degrading | Done |
| NFR-012 UI states / a11y / responsive | 153 frontend tests incl. all-states coverage; **no browser pass yet** | Partial |
| NFR-013 indexes and pagination | verified against live PostGIS | Done |
| NFR-014 deterministic tests | no test touches a live provider | Done |
| NFR-015 CI-runnable gate | `make quality-gate` verified locally; `.github/workflows/ci.yml` written but never executed on a runner | Partial |
