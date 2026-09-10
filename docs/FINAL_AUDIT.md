# SPILLTRACE — Audit Against the PRD

**Owner:** Agent 0 · Evidence is a test that runs or a command whose output is recorded
here. Nothing is marked PASS on the strength of the code merely existing.

**Status of this document:** **both** pipelines now run end to end — the 8-stage
demonstration chain and the full 13-stage chain including Sentinel-1 search, download,
SAR preprocessing and detection. All ten frontend pages build and serve. What remains
unbuilt is named in §"What is not done" and is unchanged in substance: no model has been
trained, and the three live provider adapters (CDSE, CMEMS, AISStream) are specified but
their real implementations are not finished.

---

## PRD Part O — Acceptance criteria

| ID | Criterion | Implementation | Evidence | Status |
|---|---|---|---|---|
| AC-01 | A new case can be created from the UI | `POST /api/v1/cases`; Create Case page (UI-003) | Live: `ST-2026-0001` created with AOI + window; AOI validated, area cap enforced | **PASS** |
| AC-02 | The case can find/select a Sentinel-1 scene | `adapters/satellite/{cdse,cdse_auth,fixture}.py`, `scene.search` | Live: 3 scenes catalogued with product id, footprint, polarizations, orbit; selection and download both completed. CDSE adapter written against the probed OData contract but **not exercised against live credentials** | **PASS (fixture source)** |
| AC-03 | A processed SAR image reaches the ML model | `ml/preprocess.py` → `ml/tiling.py` → `ml/inference.py` | Live: `sar.preprocess` produced `[3, 512, 512]` tiles and recorded `"VH unavailable; VV duplicated"` for a VV-only product; `ml.detect` consumed them and returned a probability field | **PASS** |
| AC-04 | The model returns a georeferenced mask/polygon | `core/masking.py`, `core/polygonize.py`, `core/confidence.py` | Live on both paths: demo 85.35 km², real path 782.5 km², both `ST_MultiPolygon` SRID 4326 with `ST_IsValid = true` and `ST_Area(::geography)` matching the geodesic computation | **PASS** |
| AC-05 | Known look-alikes can be flagged/rejected | `core/lookalike/` | `test_lookalike.py`: glassy sea (<2 m/s), dispersal (>12 m/s) and sub-2 dB contrast each produce `FALSE_POSITIVE` and cannot be out-voted by favourable shape evidence | **PASS** |
| AC-06 | Environmental forcing can be retrieved | `adapters/environmental/`, `env.fetch` | Live: run stored with variables, extent, resolution, checksum and summary statistics. **And it is now actually consumed** — after the AD-30 ordering fix the wind rule reports `applicable=true, observed=5.40 m/s` instead of *not evaluated* | **PASS (synthetic provider)** |
| AC-07 | A drift run produces a **reproducible** origin probability region | `adapters/drift/analytical.py`, `core/density.py` | `test_drift_density.py`: identical seed → identical particle hash; different seed → different hash; seed and full parameter set stored on the row | **PASS** |
| AC-08 | AIS data can be ingested into PostGIS | `adapters/ais/synthetic.py`, `worker/handlers/ais.ingest_ais` | Live: demo path 4 618 positions / 6 vessels; real path 20 529 positions / 20 vessels via `ais.ingest`, deduplicated by `(mmsi, timestamp, source)` and upserted so re-ingestion is idempotent | **PASS (synthetic source)** |
| AC-09 | Candidates can be filtered by time and location | `core/correlation.py` | `test_correlation.py`: a vessel inside the region but three days early is excluded; one 80 km away is excluded; the tolerance boundary is tested both ways. Live: 4 of 6 vessels became candidates | **PASS** |
| AC-10 | The scoring engine produces a factor-by-factor ranking | `core/scoring/` | 118 tests. Live: 4 ranked candidates, each with six factors carrying weight, score, contribution and an explanation sentence | **PASS** |
| AC-11 | The dashboard visualises all major layers | `api/routers/layers.py`; `frontend/src/app/(app)/...` | Live: 8 layers with real counts (aoi 1, footprint 1, spill 1, origin 3 contours, particles 1 182, trajectories 8, vessels 6). All ten pages build and serve — every route probed 200 against the live API, basemap verified to make **zero** external requests | **PASS** |
| AC-12 | The report records sources, timestamps and model versions | `core/report/` | Live: 29 KB HTML, 11 sections; product id, acquisition time, checksums, model name/version, drift seed and parameters, software version and git sha all present. `test_report.py` asserts each section | **PASS** |
| AC-13 | Attribution is clearly labelled investigative/probabilistic | `core/disclaimers.py` | Disclaimer is a **field** on every attribution response, appears twice in the report, and leads the limitations list. `test_disclaimers.py` + `test_report.py` assert presence and absence of prejudicial language | **PASS** |

## PRD Part F — MVP demonstration

| ID | Criterion | Status | Evidence |
|---|---|---|---|
| MVP-01 | User selects area and time | **PASS** | demo case and manual case creation both verified |
| MVP-02 | A real or prepared Sentinel-1 scene is loaded | **PASS (prepared)** | `scene.search` catalogued 3, `scene.download` stored the selected one, `sar.preprocess` tiled it |
| MVP-03 | Model detects an oil-like region | **PASS (analytical detector)** | 782.5 km² polygon on the real path; the U-Net loader exists and is skipped when torch is absent |
| MVP-04 | Look-alikes verified/flagged | **PASS** | `VERIFIED` 0.907 with a seven-rule breakdown |
| MVP-05 | Wind and current loaded | **PASS** | environmental run with summary statistics |
| MVP-06 | Drift produces an origin probability region | **PASS** | 522 km², contours at 90/75/50%, inferred window 4.8 h |
| MVP-07 | AIS positions and trajectories shown | **PASS** | 4 618 positions, 8 trajectory segments, both served as GeoJSON |
| MVP-08 | At least 3 candidate vessels ranked | **PASS** | 4 ranked, 2 correctly excluded, never padded |
| MVP-09 | Each score explained factor by factor | **PASS** | six factors with weight, score, contribution, explanation |
| MVP-10 | A report is generated | **PASS** | stored as an evidence artifact with a checksum |
| MVP-11 | UI says investigative probability, not guilt | **PASS** | disclaimers enforced in code and asserted by tests; the AD-31 guard additionally stops the UI showing a wall of HIGH labels when the evidence cannot separate candidates |

## PRD Part K — Things we said we would not do

| ID | Constraint | Verdict |
|---|---|---|
| CON-001 | nearest ≠ responsible | **HELD, and strengthened.** With `time_match = 0` the arithmetic ceiling is 0.79 against a 0.80 threshold, so a temporally incompatible vessel cannot be HIGH. Integration then exposed a second route to over-claiming — a diffuse origin region labelling 13 vessels HIGH at once — closed by the AD-31 discrimination guard. Both are asserted by test. |
| CON-002 | AIS gap ≠ illegal activity | **HELD.** A 14-hour gap moves `ais_reliability` from 0.820 to 0.448 — downward. The demo's third-ranked vessel is at 0.00 km from the origin with a perfect time match and still ranks third for exactly this reason. |
| CON-003 | 88% ≠ 88% legal probability | **HELD.** Every scored response carries `SCORE_DISCLAIMER`; `scoring_version` and the exact weights are persisted so the number is always attributable to a model. |
| CON-004 | no API keys in the frontend | **HELD.** The browser reaches only our API; CSP `connect-src` enforces it; `make audit-secrets` checks source, bundle, git and hard-coded literals. |
| CON-005 | no large files in PostgreSQL | **HELD.** Rasters, NetCDF and reports live in MinIO; the database holds `storage_uri` + `sha256`. |
| CON-006 | no giant global real-time system first | **HELD.** One region, one scenario, one case at a time. |
| CON-007 | public AIS is not complete | **HELD.** `AIS_COVERAGE_DISCLAIMER` on every AIS view; "absence of a vessel is not evidence of absence" stated in the report. |
| CON-008 | origin is a probability region | **HELD.** `origin_geometry` is a MultiPolygon with nested probability contours; no code path emits a discharge coordinate. |
| CON-009 | synthetic data never presented as real | **HELD.** `data_provenance` on every row and response, `(SYNTHETIC)` in vessel names, and the synthetic notice is the **first** limitation in the report. |

## Quality gate — measured

```
$ podman exec -w /app/backend spilltrace_api_1 python -m pytest -q
638 passed, 2 skipped        (2 skipped: torch absent, correctly guarded)

$ podman exec -w /app/backend spilltrace_api_1 ruff check src tests
All checks passed!

$ podman exec -w /app/backend spilltrace_api_1 ruff format --check src tests
149 files already formatted

$ podman exec -w /app/backend spilltrace_api_1 mypy src
Success: no issues found in 122 source files

$ cd frontend && npm run typecheck && npm run lint && npm run format:check
clean

$ cd frontend && npm run test -- --run
153 passed

$ cd frontend && npm run build
Compiled successfully — 11 routes

$ bash infra/scripts/audit_secrets.sh
audit-secrets: PASS

DEMO pipeline  (8 stages)  COMPLETED
REAL pipeline (13 stages)  COMPLETED
Frontend routes probed against the live API: 11/11 served
SSE load: 30 concurrent streams -> Redis connections 3 -> 4, API stayed healthy
```

## What is not done, stated plainly

1. **The CDSE adapter has never run against Copernicus.** It is written against the
   OData contract probed live during research (AD-06…AD-08) and unit-tested with mocked
   HTTP, but no request has been made with real credentials, so the auth flow, the
   redirect-with-auth behaviour and the COG node paths are **unverified in practice**.
   With no credentials configured the system selects the fixture adapter and logs why.
2. **No trained model, and therefore no metrics.** `model_versions.metrics` is `{}`, the
   Admin page renders that as *no evaluation recorded* rather than as a number, and the
   report states it. Detection runs on the deterministic analytical detector, whose own
   output says so: *"No trained model was used… treat the probabilities as a contrast
   statistic, not as a learned likelihood."* **No number has been invented.**
3. **The U-Net training code is untested end to end.** `ml/` has the model, losses,
   metrics, config and training loop with offline tests against a synthetic dataset, but
   no training run has been executed and the Zenodo download (~96 GB) has not been
   performed.
4. **Frontend pages have not been driven in a browser.** Every route builds and serves
   200 against the live API and 153 component tests pass, but no one has clicked through
   the map, scrubbed the timeline, or checked the layer toggles visually.
5. **OpenDrift/OpenOil** — the adapter interface and fallback are in place; the real
   engine is an optional build. Drift runs are labelled `engine='analytical'`.
6. **CMEMS and AISStream adapters** — specified in detail (AD-17, AD-21…AD-26); the
   synthetic implementations of the same ports are complete and in use.
7. **CI workflow** — `make quality-gate` runs everything locally; the GitHub Actions
   file is not yet written.
8. **Security gaps** — enumerated in `docs/SECURITY.md` §4: no dependency scanning in
   CI, `unsafe-inline` in the CSP, a query-parameter token on the SSE endpoint, no read
   audit log, no MFA.
