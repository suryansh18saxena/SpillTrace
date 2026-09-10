# SPILLTRACE — API Contract

**Owner:** Agent 1 · **Consumers:** Agent 2 (frontend), Agent 3/4 (workers)
**Base path:** `/api/v1` · **Docs:** `/docs` (Swagger), `/redoc`, `/openapi.json`
**Auth:** `Authorization: Bearer <access_token>`; refresh token in an httpOnly cookie.

This document is the **frozen interface** between agents. Changing it requires an entry in
`docs/DECISIONS.md` and an update here in the same commit.

---

## 1. Conventions

* All timestamps are RFC 3339 UTC with a `Z` suffix.
* All geometry is GeoJSON in **EPSG:4326**, longitude first.
* All list endpoints are paginated: `?limit=<1..200,default 50>&offset=<int>` and return
  `{ "items": [...], "total": <int>, "limit": <int>, "offset": <int> }`.
* Errors always use this envelope (never a raw stack trace — NFR-011):

```json
{ "error": { "code": "CASE_NOT_FOUND", "message": "Case not found.",
             "details": {}, "request_id": "01J…" } }
```

| HTTP | When |
|---|---|
| 400 | malformed request |
| 401 | missing/invalid credentials |
| 403 | authenticated but not entitled to this object (NFR-009) |
| 404 | object does not exist **or** caller is not entitled to know it exists |
| 409 | conflicting state (e.g. pipeline already running) |
| 422 | validation error (Pydantic detail) |
| 429 | rate limited |
| 503 | a required downstream provider is unavailable |

* Every response carries `X-Request-ID`; the same id appears in structured logs (NFR-004).
* Every object produced by the pipeline carries `"data_provenance": "REAL" | "SYNTHETIC" | "MIXED"` (CON-009).

## 2. Health & system

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | none | liveness — `{"status":"ok","version":"…"}` |
| GET | `/health/ready` | none | readiness — checks DB, Redis, object store |
| GET | `/api/v1/system/status` | admin | UI-010 payload: component health, providers, model versions, job stats |
| GET | `/api/v1/system/providers` | admin | which adapter implementation is active per port, and whether it is REAL |

`GET /api/v1/system/status` →
```json
{ "components": [{"name":"database","status":"UP","latency_ms":3.1,"detail":null}, …],
  "providers":  [{"port":"satellite","implementation":"FixtureCatalogue","mode":"SYNTHETIC","configured":true}, …],
  "models":     [{"name":"unet-sar-oil","version":"0.1.0","is_active":true,"metrics":{…}}],
  "jobs":       {"queued":0,"running":1,"completed_24h":42,"failed_24h":1},
  "recent_jobs":[…], "failed_jobs":[…] }
```

## 3. Authentication (UI-001, NFR-007, NFR-010)

| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/api/v1/auth/login` | `{email,password}` | → `{access_token, token_type, expires_in, user}`; sets refresh cookie. Rate limited. |
| POST | `/api/v1/auth/refresh` | — (cookie) | rotates refresh token |
| POST | `/api/v1/auth/logout` | — | revokes refresh token |
| GET | `/api/v1/auth/me` | — | current user |

## 4. Cases (FR-001, UI-002, UI-003)

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/cases` | create |
| GET | `/api/v1/cases` | list (filters: `status`, `q`, `from`, `to`) |
| GET | `/api/v1/cases/{case_id}` | detail incl. counts of child artifacts |
| PATCH | `/api/v1/cases/{case_id}` | update title/description/AOI/time window (only while `DRAFT`) |
| POST | `/api/v1/cases/{case_id}/archive` | soft archive |
| DELETE | `/api/v1/cases/{case_id}` | admin-only hard delete |

Create body:
```json
{ "title": "Gulf of Kutch suspected discharge",
  "description": "…",
  "aoi": { "type":"Polygon", "coordinates":[[[68.9,22.3],[70.4,22.3],[70.4,23.2],[68.9,23.2],[68.9,22.3]]] },
  "start_time": "2026-08-01T00:00:00Z",
  "end_time":   "2026-08-03T00:00:00Z" }
```
Validation: AOI must be a valid, non-self-intersecting polygon, area ≤ `SPILLTRACE_MAX_AOI_KM2`
(default 250 000 km²), `end_time > start_time`, window ≤ 30 days.

## 5. Pipeline & jobs (FR-019, NFR-003)

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/cases/{case_id}/pipeline` | start the full chain — body `{ "mode": "DEMO"\|"REAL", "stages": [...]?, "params": {...}? }` → `{pipeline_id, jobs:[…]}` |
| GET | `/api/v1/cases/{case_id}/pipeline` | current pipeline + per-stage status |
| POST | `/api/v1/cases/{case_id}/jobs` | run a single stage — `{ "job_type": "drift.hindcast", "payload": {...} }` |
| GET | `/api/v1/jobs/{job_id}` | job detail |
| GET | `/api/v1/cases/{case_id}/jobs` | job list |
| POST | `/api/v1/jobs/{job_id}/cancel` | cancel |
| POST | `/api/v1/jobs/{job_id}/retry` | retry a `FAILED` job |
| GET | `/api/v1/cases/{case_id}/events` | **SSE** stream of job status changes |

Job types (stable identifiers):
`scene.search`, `scene.download`, `sar.preprocess`, `ml.detect`, `detect.verify`, `env.fetch`,
`drift.hindcast`, `ais.ingest`, `ais.clean`, `traj.build`, `correlate`, `score`, `report.build`,
`demo.seed`.

Job object:
```json
{ "id":"…","case_id":"…","pipeline_id":"…","job_type":"drift.hindcast",
  "status":"RUNNING","progress":42,"step":"advecting particles (t-6h)",
  "attempt":1,"max_attempts":3,
  "queued_at":"…","started_at":"…","finished_at":null,
  "error_code":null,"error_message":null,
  "result_ref":{"drift_run_id":"…"} }
```

## 6. Satellite scenes (FR-002/FR-003, UI-003)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/cases/{case_id}/scenes` | scenes found for this case |
| POST | `/api/v1/cases/{case_id}/scenes/search` | enqueue `scene.search` |
| POST | `/api/v1/cases/{case_id}/scenes/{scene_id}/select` | mark as the scene to process |
| POST | `/api/v1/cases/{case_id}/scenes/{scene_id}/download` | enqueue `scene.download` |
| GET | `/api/v1/scenes/{scene_id}` | scene detail incl. footprint GeoJSON |

## 7. Detections & verification (FR-005/006/007, UI-005)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/cases/{case_id}/detections` | list |
| GET | `/api/v1/detections/{spill_id}` | detail: geometry, area, confidences, model version, raster URIs |
| GET | `/api/v1/detections/{spill_id}/verification` | verification result incl. `rules[]` + `explanation` |
| POST | `/api/v1/detections/{spill_id}/verify` | re-run verification with overrides |
| GET | `/api/v1/detections/{spill_id}/probability-tiles/{z}/{x}/{y}.png` | probability raster tiles for the map |

## 8. Environmental & drift (FR-008/009/010, UI-006)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/cases/{case_id}/environment` | environmental runs + summary stats |
| POST | `/api/v1/cases/{case_id}/environment/fetch` | enqueue `env.fetch` |
| GET | `/api/v1/cases/{case_id}/drift-runs` | list |
| POST | `/api/v1/cases/{case_id}/drift-runs` | enqueue `drift.hindcast` with parameters |
| GET | `/api/v1/drift-runs/{run_id}` | parameters, seed, engine, origin confidence, inferred window |
| GET | `/api/v1/drift-runs/{run_id}/origin` | `FeatureCollection` of origin probability contours with `probability` property |
| GET | `/api/v1/drift-runs/{run_id}/particles?step={n}` | particle positions for animation |

## 9. AIS, vessels, trajectories (FR-011/012/013, UI-008)

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/cases/{case_id}/ais/ingest` | enqueue `ais.ingest` for the case bbox/time window |
| GET | `/api/v1/cases/{case_id}/vessels` | vessels seen in this case |
| GET | `/api/v1/vessels/{vessel_id}` | static data + AIS quality summary |
| GET | `/api/v1/vessels/{vessel_id}/positions` | positions (`from`,`to`,`include_invalid`) |
| GET | `/api/v1/vessels/{vessel_id}/trajectory` | LineString + gap statistics |
| GET | `/api/v1/cases/{case_id}/trajectories` | all case trajectories as a `FeatureCollection` |

## 10. Correlation, scoring, ranking (FR-014/015/016, UI-007)

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/cases/{case_id}/correlate` | enqueue `correlate` |
| GET | `/api/v1/cases/{case_id}/candidates` | candidate vessels + why each was included |
| POST | `/api/v1/cases/{case_id}/score` | enqueue `score` (optional `weights` override) |
| GET | `/api/v1/cases/{case_id}/attributions` | **ranked** list |
| GET | `/api/v1/attributions/{id}` | full factor-by-factor breakdown |

Attribution object (the heart of the product — SCORE-007):
```json
{ "id":"…","rank":1,"vessel":{"id":"…","mmsi":419001234,"name":"DEMO CARRIER (SYNTHETIC)"},
  "final_score":0.81,
  "confidence_label":"HIGH",
  "factors":[
    {"key":"origin_proximity","label":"Origin proximity","weight":0.35,"score":0.92,
     "contribution":0.322,
     "explanation":"Closest approach to the origin probability region was 1.4 km at 2026-08-01T18:20Z, inside the 80th-percentile contour.",
     "evidence":{"closest_approach_km":1.4,"contour_percentile":80}},
    …six factors total…],
  "weights":{"origin_proximity":0.35,"time_match":0.20,"trajectory_match":0.15,
             "heading_match":0.10,"speed_match":0.10,"ais_reliability":0.10},
  "scoring_version":"prd-j-v1",
  "disclaimer":"Investigative/probabilistic evidence — not automatic legal proof.",
  "discrimination_note":null,
  "data_provenance":"SYNTHETIC" }
```

`discrimination_note` is `null` when the ranking genuinely separates its candidates. It
carries a sentence when it does not — for example when a diffuse origin region contains
many vessels at effectively the same proximity. In that case every candidate's
`confidence_label` is **capped at MODERATE** and the note says why. The numeric scores
are never altered; only the at-a-glance label is prevented from over-claiming, because
"thirteen strong candidates" is the system reporting that it could not tell them apart,
phrased as if it could (CON-001).
The `disclaimer` field is **mandatory and non-empty** on every attribution response and is asserted
by `backend/tests/unit/test_disclaimers.py` (CON-003, AC-13).

## 11. Map layers (UI-004, FR-017)

`GET /api/v1/cases/{case_id}/layers` → layer manifest the map builds itself from:

```json
{ "layers":[
  {"id":"aoi","title":"Area of interest","type":"geojson","url":"/api/v1/cases/…/layers/aoi","visible":true},
  {"id":"scene_footprint","title":"Sentinel-1 scene footprint","type":"geojson","url":"…"},
  {"id":"spill","title":"Detected slick","type":"geojson","url":"…"},
  {"id":"oil_probability","title":"Oil probability","type":"raster","url":"…/{z}/{x}/{y}.png"},
  {"id":"origin_region","title":"Origin probability region","type":"geojson","url":"…"},
  {"id":"drift_particles","title":"Reverse-drift particles","type":"geojson","url":"…"},
  {"id":"vessels","title":"Vessels","type":"geojson","url":"…"},
  {"id":"trajectories","title":"Vessel trajectories","type":"geojson","url":"…"}]}
```
Individual layer endpoints: `/api/v1/cases/{case_id}/layers/{layer_id}` returning GeoJSON
`FeatureCollection`.

## 12. Evidence report (FR-018, UI-009, AC-12)

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/cases/{case_id}/report` | enqueue `report.build` |
| GET | `/api/v1/cases/{case_id}/report` | latest report as structured JSON |
| GET | `/api/v1/cases/{case_id}/report.html` | rendered HTML |
| GET | `/api/v1/cases/{case_id}/report.pdf` | PDF export |
| GET | `/api/v1/cases/{case_id}/artifacts` | evidence artifacts with checksums |
| GET | `/api/v1/artifacts/{artifact_id}/download` | presigned/streamed download |

## 13. Demo / synthetic data (FR-020, CON-009)

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/demo/cases` | create a fully-populated deterministic **SYNTHETIC** case (`{"scenario":"kutch-01","seed":42}`) |
| GET | `/api/v1/demo/scenarios` | available scenarios |

Every object created by these endpoints has `data_provenance: "SYNTHETIC"` and vessel names are
suffixed `(SYNTHETIC)` so they can never be mistaken for real observations.
