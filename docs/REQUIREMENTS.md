# SPILLTRACE — Requirement Register

**Source of truth:** `prd.pdf` (SIH26143 · Smart India Hackathon 2026 · Team OnlyBans · Team ID 6969).
**Extracted:** 2026-09-10 · **Owner:** Agent 0 (Lead Architect)

Every requirement below is traceable back to a PRD part. Requirement IDs are stable and are
referenced by `docs/TASKS.md`, `docs/TRACEABILITY.md` and `docs/FINAL_AUDIT.md`.

| Prefix | Meaning |
|---|---|
| `FR-` | Functional requirement (pipeline steps, PRD Part D/E) |
| `SVC-` | Backend service (PRD Part I) |
| `DB-` | Database table / schema (PRD Part G) |
| `UI-` | Frontend page (PRD Part H) |
| `DATA-` | External data source + adapter (PRD Part B) |
| `SCORE-` | Scoring model (PRD Part J) |
| `CON-` | Constraint / explicit non-goal (PRD Part K) |
| `NFR-` | Non-functional requirement (derived) |
| `AC-` | Acceptance criterion (PRD Part O) |
| `MVP-` | MVP demonstration criterion (PRD Part F) |

Priority: **P0** = MVP-blocking · **P1** = required for "complete" · **P2** = desirable, degrade gracefully.

---

## 1. Functional requirements — the investigation chain (PRD Part C & D)

The mandated chain, verbatim from PRD Part C:

```
USER -> AOI/DATE -> SENTINEL-1 -> PREPROCESS -> U-NET -> OIL MASK -> LOOK-ALIKE CHECK ->
WIND + CURRENT -> OPENDRIFT/OPENOIL -> ORIGIN PROBABILITY REGION -> AIS -> TRAJECTORIES ->
CORRELATION -> SCORING -> RANKED VESSELS -> DASHBOARD -> EVIDENCE REPORT
```

| ID | Requirement | PRD | Priority | Input | Output artifact |
|---|---|---|---|---|---|
| FR-001 | User selects a geographic AOI and a time window; system persists them as a **case**. | D.1 | P0 | User input | AOI polygon + `[start_time, end_time]` |
| FR-002 | Search the Sentinel-1 catalogue for SAR scenes intersecting the AOI within the time window. | D.2 | P0 | AOI + time | Scene metadata rows |
| FR-003 | Download the selected Sentinel-1 GRD product and store it in object storage. | D.3 | P1 | Scene id | GRD artifact + checksum |
| FR-004 | Preprocess the GRD: calibrate/normalize, extract VV/VH, mask invalid pixels, tile for ML. | D.4 | P1 | GRD raster | ML-ready VV/VH tiles + georeferencing |
| FR-005 | Run U-Net inference producing a per-pixel oil probability mask. | D.5 | P0 | Tiles + model | Probability raster (GeoTIFF) |
| FR-006 | Threshold + clean + georeference + polygonize the mask into a spill polygon. | D.6 | P0 | Probability mask | GeoJSON MultiPolygon + area_km2 + confidence |
| FR-007 | Verify the detection against look-alikes using wind, shape, contrast and optional classifier; emit `VERIFIED` / `UNCERTAIN` / `FALSE_POSITIVE` with a human-readable explanation. | D.7 | P0 | SAR + wind + geometry | Verification result + per-feature evidence |
| FR-008 | Retrieve wind and ocean-current fields for the event time/location. | D.8 | P0 | Location + time | Environmental run + field data |
| FR-009 | Run **reverse (hindcast)** particle drift from the spill polygon under environmental forcing. | D.9 | P0 | Spill + forcing | Particle tracks |
| FR-010 | Aggregate backward particle density into an **origin probability region** (not a point). | D.10 | P0 | Particle tracks | Probability polygon(s) + density grid + inferred discharge time window |
| FR-011 | Ingest AIS positions for the origin region and time window. | D.11 | P0 | Bbox + time | Raw AIS messages |
| FR-012 | Clean AIS: deduplicate, validate coordinates/timestamps, reject impossible jumps, flag gaps. | D.12 | P0 | Raw AIS | Clean positions + quality flags |
| FR-013 | Build time-ordered vessel trajectories as LineStrings with gap statistics. | D.13 | P0 | Clean AIS | Trajectory geometries + stats |
| FR-014 | Correlate: spatial + temporal query for vessels compatible with the origin region and window. | D.14 | P0 | Origin + trajectories | Candidate vessel list + why-included explanation |
| FR-015 | Score every candidate on 6 independent factors and combine into a final score. | D.15 | P0 | All prior outputs | Per-factor scores + explanations |
| FR-016 | Rank candidates by final score and expose the reasons for each rank. | D.16 | P0 | Scores | Ordered ranking |
| FR-017 | Investigation dashboard displaying spill, origin region, vessels, trajectories, timeline and score breakdown. | D.17 | P0 | API | Interactive UI |
| FR-018 | Generate an evidence report packaging artifacts, sources, model versions and uncertainty. | D.18 | P0 | All case artifacts | Report (HTML + PDF) + stored artifact |
| FR-019 | Every pipeline stage must be executed as a tracked **job** with status/progress and must not block HTTP request handlers. | E.5 | P0 | — | Job records |
| FR-020 | The complete chain must be runnable end-to-end on deterministic **synthetic/demo data** with zero external providers. | E (intro) | P0 | — | Demo case |

## 2. Backend services (PRD Part I)

| ID | Service | Responsibility | Priority |
|---|---|---|---|
| SVC-001 | Satellite Service | Search/download Sentinel-1 scenes | P0 |
| SVC-002 | Preprocessing Service | Prepare SAR tiles | P1 |
| SVC-003 | ML Service | Run U-Net inference | P0 |
| SVC-004 | Verification Service | Look-alike checks | P0 |
| SVC-005 | Environmental Service | Wind/current retrieval | P0 |
| SVC-006 | Drift Service | OpenOil/OpenDrift jobs | P0 |
| SVC-007 | AIS Service | Ingest/normalize AIS | P0 |
| SVC-008 | Trajectory Service | Build vessel tracks | P0 |
| SVC-009 | Correlation Service | Find candidate vessels | P0 |
| SVC-010 | Scoring Service | Rank and explain vessels | P0 |
| SVC-011 | Report Service | Generate evidence report | P0 |
| SVC-012 | Case Service *(derived)* | Case lifecycle + orchestration of the pipeline | P0 |
| SVC-013 | Job Service *(derived)* | Enqueue, track, retry, fail jobs | P0 |
| SVC-014 | Auth Service *(derived, from UI-001)* | Login, session, role-based access | P0 |

## 3. Database entities (PRD Part G)

All spatial columns use SRID 4326 unless stated. Full DDL in `docs/DATABASE.md`.

| ID | Table | Main fields (PRD) | Geometry |
|---|---|---|---|
| DB-001 | `cases` | case_id, status, AOI, start_time, end_time, created_at | `Polygon` AOI |
| DB-002 | `satellite_scenes` | product_id, acquisition_time, bbox, polarization, storage_uri | `Polygon` footprint |
| DB-003 | `spill_detections` | spill_id, case_id, confidence, area_km2, polygon, model_version | `MultiPolygon` |
| DB-004 | `verification_results` | spill_id, wind/shape/contrast features, status, confidence | — |
| DB-005 | `environmental_runs` | run_id, source, variables, time range, spatial extent | `Polygon` extent |
| DB-006 | `drift_runs` | run_id, spill_id, model, parameters, origin_geometry, confidence | `MultiPolygon` origin |
| DB-007 | `vessels` | vessel_id, MMSI, IMO, name, type, flag | — |
| DB-008 | `ais_positions` | vessel_id, timestamp, lat, lon, SOG, COG, geometry | `Point` |
| DB-009 | `trajectories` | vessel_id, time range, LineString, gap stats | `LineString` |
| DB-010 | `attributions` | spill_id, vessel_id, all factor scores, final score, rank | — |
| DB-011 | `jobs` | job_id, case_id, job_type, status, progress, error | — |
| DB-012 | `evidence_artifacts` | case_id, artifact_type, storage_uri, checksum | — |
| DB-013 | `model_versions` | name, version, metrics, artifact_uri | — |
| DB-014 | `users` *(derived, required by UI-001 Login)* | user_id, email, password_hash, role | — |
| DB-015 | `drift_particles` *(derived, required by FR-009/FR-010)* | run_id, particle_id, time, position | `Point` |

**Constraints:** spatial indexes (GiST) on every geometry column; temporal indexes on every time column
used for range queries; unique constraints on `(mmsi)`, `(product_id)`, `(vessel_id, timestamp, source)`.

## 4. Frontend pages (PRD Part H)

| ID | Page | Purpose | Priority |
|---|---|---|---|
| UI-001 | Login | User authentication | P0 |
| UI-002 | Case List | Previous investigations | P0 |
| UI-003 | Create Case | Select map area and date/time | P0 |
| UI-004 | Investigation Map | Spill + origin + vessels + trajectories | P0 |
| UI-005 | Spill Details | Detection and verification details | P0 |
| UI-006 | Drift View | Origin simulation / probability region | P0 |
| UI-007 | Vessel Ranking | Rank + score + explanation | P0 |
| UI-008 | Vessel Details | AIS trajectory and event timeline | P0 |
| UI-009 | Evidence Report | All evidence and export | P0 |
| UI-010 | Admin | Model / data source / system status | P0 |

**Required map layers (FR-017):** AOI · scene footprint · spill polygon · oil probability raster ·
origin probability region · drift particles · vessels · vessel trajectories.

## 5. Data sources and adapters (PRD Part B)

| ID | Data | Source (PRD) | Adapter contract | Fallback |
|---|---|---|---|---|
| DATA-001 | Sentinel-1 imagery | Copernicus Data Space | `SatelliteCatalogue.search(aoi, t0, t1)` / `.download(product_id)` | Local fixture scene |
| DATA-002 | Oil/no-oil/look-alike training images | Public Zenodo dataset (685 no-oil + 685 look-alike, 2048x2048x2 VV/VH; test set 150/150/150 with masks) | dataset downloader + validator | Synthetic tiles |
| DATA-003 | Wind | Copernicus Marine / operational atmospheric provider | `EnvironmentalProvider.wind(bbox, t0, t1)` | Deterministic synthetic field |
| DATA-004 | Ocean current | Copernicus Marine | `EnvironmentalProvider.current(bbox, t0, t1)` | Deterministic synthetic field |
| DATA-005 | AIS prototype stream | AISStream (server-side WebSocket, bbox + message-type filters) | `AISProvider.stream(bboxes)` | Deterministic synthetic AIS generator |
| DATA-006 | AIS production | Authorized/contracted/government source | same `AISProvider` interface | n/a |
| DATA-007 | Vessel metadata | AIS static/voyage messages + legally available registry data | `ShipStaticData` ingestion | Synthetic registry |
| DATA-008 | Model output | Our U-Net | `SegmentationModel.predict(tiles)` | Deterministic analytical detector |
| DATA-009 | Drift output | Our OpenOil/OpenDrift run | `DriftEngine.hindcast(...)` | Analytical advection-diffusion engine |
| DATA-010 | Scores | Our scoring engine | pure function, no external dependency | n/a |

**Rule (CON-004):** every adapter is selected at runtime by configuration. Provider credentials are
read server-side only. Every non-real adapter labels its output `SYNTHETIC`.

## 6. Scoring model (PRD Part J)

```
Final Score = 0.35 x Origin Proximity
            + 0.20 x Time Match
            + 0.15 x Trajectory Match
            + 0.10 x Heading Match
            + 0.10 x Speed Match
            + 0.10 x AIS Reliability
```

| ID | Factor | Weight | PRD meaning |
|---|---|---|---|
| SCORE-001 | Origin proximity | 0.35 | Ship was close to the high-probability origin area. |
| SCORE-002 | Time match | 0.20 | Ship was there during the inferred discharge window. |
| SCORE-003 | Trajectory match | 0.15 | Ship's path is consistent with entering/leaving the origin. |
| SCORE-004 | Heading match | 0.10 | Direction is compatible with movement/event. |
| SCORE-005 | Speed match | 0.10 | Speed is plausible for the event. |
| SCORE-006 | AIS reliability | 0.10 | How complete/clean the AIS history is; gaps lower confidence. |
| SCORE-007 | Each factor is independently calculated, normalized to `[0,1]`, **stored**, **displayed** and **explained**. | — | Part J + prompt §19 |
| SCORE-008 | Weights are configurable, versioned, and persisted with every attribution for reproducibility. | — | Part J ("engineering defaults ... must be calibrated") |

> **PRD verbatim:** "Initial weights are engineering defaults for the prototype, not scientifically
> validated legal probabilities. They must be calibrated on labelled/validated cases."

## 7. Constraints and explicit non-goals (PRD Part K) — MUST NOT be violated

| ID | Constraint |
|---|---|
| CON-001 | We will **not** say the nearest vessel is automatically responsible. |
| CON-002 | We will **not** treat an AIS gap as proof of illegal activity. |
| CON-003 | We will **not** call an 88% score an 88% legal probability unless scientifically calibrated. |
| CON-004 | We will **not** expose AIS/API keys in the frontend. |
| CON-005 | We will **not** store huge GeoTIFF/NetCDF files directly inside PostgreSQL. |
| CON-006 | We will **not** start by building a huge global real-time system. |
| CON-007 | We will **not** claim public AIS coverage is complete for every Indian-water scenario. |
| CON-008 | Origin region is a probability region, never presented as an exact discharge coordinate. |
| CON-009 | Synthetic/demo data is always visibly labelled and never presented as a real-world observation. |

**Enforcement:** CON-001/002/003/008 are enforced by UI copy + report boilerplate and covered by
tests in `backend/tests/unit/test_disclaimers.py` and frontend tests. CON-004/005 are enforced by
a repository lint (`make audit-secrets`) and schema review. CON-009 is enforced by a
`data_provenance` field (`REAL` / `SYNTHETIC` / `MIXED`) carried on every generated artifact.

## 8. Non-functional requirements (derived from prompt §23, §31–33)

| ID | Requirement |
|---|---|
| NFR-001 | One-command local startup (`make up`) brings the full stack up; documented in README. |
| NFR-002 | Heavy work (download, SAR, ML, drift) runs in workers, never in a request handler. |
| NFR-003 | Every long-running job exposes id, status, progress, timestamps, error, result reference and logs. |
| NFR-004 | Structured JSON logging with a request/job correlation id; secrets are never logged. |
| NFR-005 | Reproducibility: model version, product id, acquisition time, environmental source + range, drift parameters, RNG seed, scoring weights, checksums are stored with every result. |
| NFR-006 | Large binaries in S3-compatible object storage; PostgreSQL keeps metadata, references, checksums, URIs, relationships only. |
| NFR-007 | Authentication on all non-public endpoints; passwords hashed with a modern KDF; JWT with expiry. |
| NFR-008 | Input validation on every endpoint (Pydantic); parameterized SQL only; no string-built queries. |
| NFR-009 | Object-level authorization (no IDOR): a user may only read cases they own or are entitled to. |
| NFR-010 | Rate limiting on authentication and on job-creation endpoints. |
| NFR-011 | Graceful degradation: any unavailable external provider produces a `FAILED` job with a clear reason, never a 500 storm or a silent fake result. |
| NFR-012 | Every screen has loading / empty / error / success / disabled states; keyboard-navigable; readable contrast; responsive desktop/tablet/mobile. |
| NFR-013 | Spatial (GiST) and temporal (btree/BRIN) indexes on all query paths; API pagination on all list endpoints. |
| NFR-014 | Deterministic tests: no test depends on live external services; providers are faked at the adapter boundary. |
| NFR-015 | CI-runnable quality gate: typecheck (mypy + tsc), lint (ruff + eslint), tests, production build. |

## 9. MVP demonstration criteria (PRD Part F)

| ID | Criterion |
|---|---|
| MVP-01 | User selects a case area and time. |
| MVP-02 | A real or prepared Sentinel-1 scene is loaded. |
| MVP-03 | U-Net detects an oil-like region. |
| MVP-04 | System verifies/flags look-alikes. |
| MVP-05 | Wind/current are loaded. |
| MVP-06 | OpenOil/OpenDrift produces an origin probability region. |
| MVP-07 | AIS positions/trajectories are shown. |
| MVP-08 | At least 3 candidate vessels are ranked. |
| MVP-09 | Each score is explained factor-by-factor. |
| MVP-10 | A report is generated. |
| MVP-11 | UI clearly says "investigative probability", not legal guilt. |

## 10. Acceptance criteria (PRD Part O) — the final gate

| ID | Criterion | Verified by |
|---|---|---|
| AC-01 | A new case can be created from the UI. | e2e |
| AC-02 | The case can find/select a Sentinel-1 scene. | integration + e2e |
| AC-03 | A processed SAR image can reach the ML model. | integration |
| AC-04 | The model returns a georeferenced spill mask/polygon. | gis + integration |
| AC-05 | The system can flag/reject at least known look-alike examples. | unit + dataset eval |
| AC-06 | Environmental forcing can be retrieved for a case. | integration |
| AC-07 | A drift run produces a **reproducible** origin probability region. | unit (seeded) + integration |
| AC-08 | AIS data can be ingested into PostGIS. | integration |
| AC-09 | Candidate vessels can be filtered by time and location. | gis + integration |
| AC-10 | The scoring engine produces a factor-by-factor ranking. | unit + e2e |
| AC-11 | The dashboard visualizes all major layers. | frontend test + manual checklist |
| AC-12 | The evidence report records data sources, timestamps and model versions. | unit + e2e |
| AC-13 | The product clearly labels attribution as investigative/probabilistic. | unit + frontend test |

## 11. Ambiguities in the PRD (P0-012) and the decisions taken

Recorded here, resolved in `docs/DECISIONS.md`.

| # | Ambiguity | Resolution |
|---|---|---|
| A-01 | PRD says "Docker" but names no orchestrator beyond Compose; no Kubernetes requirement. | Compose-spec `docker-compose.yml`; runtime auto-detected (`docker compose` \| `podman compose` \| `podman-compose`). Dev host here has Podman only. |
| A-02 | "Inferred discharge time window" is used by SCORE-002 but never defined. | Derived from the reverse-drift run: the time interval over which back-tracked particle density in the origin region exceeds a configured percentile. Stored on `drift_runs`. |
| A-03 | "AIS Reliability" is a per-vessel factor but the PRD does not define its inputs. | Composite of: position count in window, median reporting interval vs expected, longest gap, fraction of positions rejected by cleaning, static-data completeness. Documented in `docs/AIS_PIPELINE.md`. |
| A-04 | The PRD does not say whether look-alike verification blocks the pipeline. | It does not block. `FALSE_POSITIVE` still runs the chain but the UI and report lead with the rejection, and attribution results are suppressed from ranking headline. |
| A-05 | No auth model specified beyond a Login page. | Email + password (Argon2id), JWT access token + rotating refresh token, roles `analyst` / `admin`. Cases owned by a user; admin sees all. |
| A-06 | "Confidence" appears on spills, verification and drift runs with no definition. | Three separately named, separately documented quantities — `detection_confidence`, `verification_confidence`, `origin_confidence`. Never multiplied together or shown as one number. |
| A-07 | Wind source is "Copernicus Marine ... operational atmospheric provider can be added". | Provider interface with pluggable implementations; default configured implementation documented in `docs/DECISIONS.md` after source verification. |
| A-08 | Report format unspecified ("PDF/report"). | HTML canonical (accessible, linkable) + server-rendered PDF export; both stored as evidence artifacts with checksums. |
| A-09 | Dataset internal format not described in the PRD. | Validated at download time by a dataset validator that fails loudly on mismatch rather than assuming. |
| A-10 | "At least 3 candidate vessels" — unclear whether to pad the list when fewer exist. | Never pad. If fewer than 3 real candidates exist, the UI states that explicitly. The demo scenario is authored to contain more than 3. |
