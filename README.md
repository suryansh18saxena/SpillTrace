# SPILLTRACE — Maritime Pollution Attribution System

**SIH26143 · Smart India Hackathon 2026 · Team OnlyBans · Team ID 6969**

SPILLTRACE helps an analyst investigate a suspected oil spill at sea. It detects
oil-like slicks in Sentinel-1 SAR imagery, checks them against the natural phenomena
that look the same, back-tracks the oil through wind and current to a probability region
where the discharge plausibly happened, reconstructs AIS vessel trajectories through that
region, and ranks candidate vessels with a score that can be read factor by factor.

> **Attribution produced by this system is investigative/probabilistic evidence. It is
> not automatic legal proof.** Nearest is not guilty. A gap in AIS reporting is not
> evidence of wrongdoing. An 88% score is not an 88% legal probability. These are not
> caveats bolted on at the end — they are enforced in the code and asserted by tests.

---

## The reasoning chain

```
AOI + time window
  → Sentinel-1 scene search → download → SAR preprocessing
  → U-Net → oil probability mask → spill polygon
  → look-alike verification (wind, shape, contrast)            VERIFIED / UNCERTAIN / FALSE_POSITIVE
  → wind + ocean current
  → reverse drift (OpenOil, or a deterministic analytical engine)
  → origin PROBABILITY REGION + inferred discharge window      never a coordinate
  → AIS ingestion → cleaning → trajectories
  → correlation (space ∩ time)
  → explainable scoring → ranked candidates
  → investigation dashboard → evidence report
```

Every stage runs as a tracked background job, writes an inspectable artifact, and records
enough provenance for the result to be reproduced.

## Quick start

```bash
make init-env    # .env with generated secrets
make up          # the whole stack
make migrate && make seed
make demo        # a fully synthetic demonstration case
```

Frontend at http://localhost:3000, API docs at http://localhost:8000/docs.
Works with Docker or Podman — the `Makefile` detects which you have.
Full instructions, including the production path, are in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Dummy-first, and honest about it

The system runs the **entire chain with no external provider**. That is not a
placeholder mode: `demo.seed` synthesises only the *observations* — a scene, a slick, wind
and current fields, and raw AIS messages complete with duplicates, an impossible position
jump and reporting gaps. Everything after that (verification, reverse drift, AIS cleaning,
trajectory building, correlation, scoring, reporting) runs the **real algorithm** on that
input. A demonstration that faked the conclusions would prove nothing about the system.

Synthetic data is labelled everywhere it appears: `data_provenance = SYNTHETIC`, vessel
names suffixed `(SYNTHETIC)`, a notice on the case, and the synthetic warning leading the
report's limitations section.

## What the demonstration actually shows

From a single seeded run (`kutch-01`, seed 42), the system independently produces:

| | |
|---|---|
| Detection | 85.3 km² slick, valid MultiPolygon, geodesic area confirmed by PostGIS |
| Verification | `VERIFIED`, confidence 0.907, wind 5.4 m/s — inside the 4–10 m/s window where SAR oil detection is reliable |
| Reverse drift | analytical engine, seed 42, 6 000 particles × 6 members, origin region 522 km², inferred discharge window 4.8 h |
| AIS cleaning | 4 618 positions ingested, 4 rejected (3 duplicates, 1 impossible jump) |
| Correlation | 6 vessels considered, 4 became candidates, 2 correctly excluded |
| Ranking | see below |

```
rank  vessel              FINAL   origin  time   traj   head   speed  AIS
 1    SAGAR PRABHA        0.9546  0.960   1.000  1.000  0.877  0.989  0.820
 2    EASTERN ORCHID      0.9307  0.960   1.000  1.000  0.753  0.885  0.776
 3    MATSYA VII          0.8885  0.960   1.000  1.000  0.587  0.990  0.448
 4    ATLANTIC MERIDIAN   0.6860  0.525   1.000  0.350  0.752  0.929  0.817
```

Rank 3 is the interesting one. **MATSYA VII is at 0.00 km from the origin region with a
perfect time and trajectory match — and still ranks third**, because a 14-hour reporting
gap drops its AIS reliability to 0.448. The system does not reward a vessel for going
dark; it becomes *less* confident about it. That is CON-002 working, not a rule written
in a document.

## Repository layout

```
backend/          one Python package, three runtimes (api | worker | ais-ingestor)
  src/spilltrace/
    core/         pure domain — geometry, scoring, AIS cleaning, look-alike rules,
                  density, correlation, report. No I/O, no framework.
    adapters/     every external boundary behind a Protocol, each with a real and a
                  deterministic implementation
    db/           SQLAlchemy 2.0 models, repositories, Alembic migrations
    api/          FastAPI routers, schemas, auth
    worker/       job queue, runtime, pipeline DAG, handlers
    demo/         deterministic synthetic scenario generators
frontend/         Next.js 15 + TypeScript + MapLibre
ml/               U-Net training, dataset tooling
infra/            Dockerfiles, database bootstrap, scripts
docs/             requirements, architecture, decisions, pipelines, audit
```

## Documentation

| | |
|---|---|
| [REQUIREMENTS.md](docs/REQUIREMENTS.md) | every PRD requirement, with a stable id |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | system design and the decisions behind it |
| [DECISIONS.md](docs/DECISIONS.md) | researched technical decisions, each labelled CONFIRMED or UNCERTAIN with sources |
| [DATABASE.md](docs/DATABASE.md) | full schema, indexes, representative spatial queries |
| [API.md](docs/API.md) | the frozen HTTP contract |
| [ML_PIPELINE.md](docs/ML_PIPELINE.md) · [GIS_PIPELINE.md](docs/GIS_PIPELINE.md) · [AIS_PIPELINE.md](docs/AIS_PIPELINE.md) | per-domain specifications with cited thresholds |
| [SECURITY.md](docs/SECURITY.md) | security review, including the gaps |
| [TESTING.md](docs/TESTING.md) | strategy and the failure-mode matrix |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | setup, configuration, production |
| [TASKS.md](docs/TASKS.md) | the task registry — the project's live state |
| [FINAL_AUDIT.md](docs/FINAL_AUDIT.md) | requirement-by-requirement verification |

## Technology

Next.js 15 · React 19 · TypeScript · MapLibre GL · FastAPI · Pydantic v2 ·
SQLAlchemy 2.0 async · PostgreSQL 16 + PostGIS 3.4 · Redis 7 · MinIO ·
rasterio · shapely 2 · pyproj · PyTorch (optional) · OpenDrift/OpenOil (optional) ·
Docker / Podman

## Quality gates

```bash
make quality-gate   # ruff, mypy, pytest, secret audit
```

Currently: **466 backend tests**, **102 frontend tests**, ruff clean, mypy clean across
98 source files.
