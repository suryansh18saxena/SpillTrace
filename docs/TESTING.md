# SPILLTRACE — Testing Strategy

**Owner:** QA · Traces: prompt §28, §29 · **Command:** `make test` (or the per-layer targets)

---

## 1. What we are actually defending against

This system names vessels. The failures that matter are not crashes — they are
**plausible wrong answers**: a distance computed in degrees, a contour whose label does
not match its geometry, a reliability score that rewards a vessel for going dark, an
explanation that says more than the evidence supports. Those produce output that looks
right and is not. The test suite is weighted accordingly.

## 2. Layers

| Layer | Location | Needs services | What it proves |
|---|---|---|---|
| Unit | `backend/tests/unit/` | no | domain logic, in isolation, deterministically |
| GIS | `backend/tests/gis/` | PostGIS | spatial SQL and geometry validity against a real engine |
| Integration | `backend/tests/integration/` | PostgreSQL, Redis, MinIO | repositories, API contracts, worker lifecycle |
| Failure | `backend/tests/failure/` | varies | every degradation path from prompt §29 |
| End-to-end | `backend/tests/e2e/` | full stack | the whole investigation chain |
| Frontend | `frontend/tests/` | no | API client, formatters, component states, disclaimer rendering |
| ML | `ml/tests/` | no (synthetic dataset) | shapes, losses, metrics, determinism |

**No test depends on a live external provider.** Providers are faked at the adapter
boundary, which is the same seam the product uses to run without them (NFR-014).

## 3. Current state — measured, not projected

```
backend  466 passed
frontend 102 passed
ruff     All checks passed
ruff format  115 files already formatted
mypy     Success: no issues found in 98 source files
```

Notable properties under test:

* **Reproducibility (AC-07)** — the same seed, parameters and forcing produce a
  byte-identical particle set, asserted by hashing. A different seed produces a
  different one.
* **Nesting (CON-008)** — the 50% origin region is contained in the 75%, which is
  contained in the 90%, and their areas strictly increase.
* **"Nearest ≠ guilty" (CON-001)** — a vessel closer in space but temporally
  incompatible ranks *below* a more distant, temporally compatible one.
* **"Gap ≠ guilt" (CON-002)** — two otherwise identical vessels differing only in a
  14-hour reporting gap: the gapped one scores **lower**. Asserted both in the scoring
  unit tests and observable in the demo run (`ais_reliability` 0.448 vs 0.820).
* **Language (CON-003, AC-13)** — every generated explanation and the whole rendered
  report are scanned for forbidden phrases; the mandated disclaimers are excluded from
  the scan because they quote those phrases in order to deny them.
* **Physical vetoes** — a detection at 1.2 m/s wind is rejected regardless of how
  convincing its shape and contrast are.
* **Missing evidence** — absent wind data yields `UNCERTAIN` with reduced coverage, not
  a confident verdict in either direction.

## 4. Failure-mode matrix (prompt §29)

Each row is a test or a documented behaviour. Legitimate emptiness is `NoDataError`,
which completes the job with `no_data: true` — reporting "no vessels found" as a
*failure* would be as dishonest as inventing one.

| Scenario | Expected behaviour |
|---|---|
| Sentinel provider unavailable | job `FAILED`, `PROVIDER_UNAVAILABLE`, reason shown |
| Sentinel credentials absent | fixture adapter selected, logged, artifacts labelled SYNTHETIC |
| Download failure / corrupt archive | job `FAILED`, partial file removed, retried with backoff |
| No scenes in the AOI | `NoDataError` → completed with `no_data` |
| ML checkpoint missing | analytical detector used, output labelled, report says so |
| No slick detected | `NoDataError`, chain stops honestly |
| Look-alike detected | `FALSE_POSITIVE`; drift refuses to back-track a rejected detection |
| Wind or current unavailable | wind rule reports "not evaluated"; verdict `UNCERTAIN` |
| OpenDrift unavailable | analytical engine, `engine='analytical'` recorded and displayed |
| AIS unavailable | `NoDataError` with the coverage caveat |
| AIS gaps | flagged, reliability lowered, never treated as wrongdoing |
| Zero candidates | empty ranking + `shortfall_note`; **never padded** |
| Fewer than 3 candidates | short list + `shortfall_note` |
| Database unavailable | `/health/ready` reports DOWN; API returns the error envelope |
| Redis unavailable | rate limiting fails open with a warning; queue reports DOWN |
| Worker crash mid-job | task exception logged; stale-claim reaper requeues |
| Storage unavailable | `StorageError`, job `FAILED`, no partial artifact row |
| Invalid AOI | 422 with the specific reason (self-intersection, range, area cap) |
| Invalid date range | 422; `end_time > start_time` and the window cap enforced |
| Malformed request | 422 with per-field detail |
| Unauthorised object access | 404, not 403 — a caller must not be able to probe which ids exist |
| Duplicate AIS ingestion | database unique constraint plus in-memory dedup |

## 5. Running

```bash
make test              # everything
make test-unit         # no services needed
make test-gis          # PostGIS
make test-integration  # PostgreSQL + Redis + MinIO
make test-e2e          # full chain
make test-frontend
make quality-gate      # lint + typecheck + tests + secret audit
```

## 6. Accessibility checklist (UI-009, NFR-012)

Manual, per release: keyboard-only traversal of every page; visible focus on every
interactive element; contrast ≥ 4.5:1 for text and ≥ 3:1 for UI boundaries; every form
control labelled; landmarks and heading order correct; the map usable without a pointer
(the AOI tool has numeric bounds fields for exactly this reason); no information carried
by colour alone — confidence is a label *and* a position, never just a hue.
