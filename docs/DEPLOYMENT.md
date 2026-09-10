# SPILLTRACE — Setup and Deployment

---

## 1. Local development, from nothing

**Requirements:** a container runtime (Docker Desktop, or Podman with `podman-compose`),
`make`, and about 4 GB of free memory. Nothing else — no Python, Node, PostgreSQL or
GDAL on the host.

```bash
git clone <repository> && cd SIH-2026
make init-env     # writes .env with generated secrets, mode 600
make up           # builds images, starts everything, waits for /health
make migrate      # applies the database schema
make seed         # creates an admin and an analyst; prints the generated passwords
make demo         # optional: a fully synthetic demonstration case
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API + Swagger | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 |
| PostgreSQL | localhost:5432 |

`make help` lists every target.

### Podman

This project was developed on a host with **Podman and no Docker**. The `Makefile`
resolves the runtime automatically (`docker compose` → `docker-compose` →
`podman-compose` → `podman compose`), so the same Compose file works either way. If you
have Podman but not `podman-compose`:

```bash
pip install --user podman-compose
```

### One gotcha worth knowing

The source tree is bind-mounted into the containers, and the container user (uid 1001)
is not the host user. Tools that write into the tree — `ruff format`, `alembic revision`
— need `--user root`, and tools that write caches need those caches pointed outside the
mount. The `Makefile` targets already do both; you only meet this if you run a container
command by hand.

## 2. Configuration

Everything is environment variables; see `.env.example` for the annotated list.
`make check-env` validates that required values are present and that no placeholder
survived. It also fails if any `NEXT_PUBLIC_*` variable looks like a credential — that
prefix ships to the browser (CON-004).

**Adapter selection** decides whether the system talks to real providers:

```
SPILLTRACE_SATELLITE_PROVIDER=fixture|cdse
SPILLTRACE_ENVIRONMENT_PROVIDER=synthetic|cmems
SPILLTRACE_AIS_PROVIDER=synthetic|aisstream
SPILLTRACE_DRIFT_ENGINE=analytical|openoil
SPILLTRACE_SEGMENTATION_MODEL=analytical|unet
```

The defaults are the offline ones, so a fresh clone runs end to end with no accounts
anywhere. Switching a value to its real counterpart without supplying credentials is
detected at start-up, logged, and surfaced on the Admin page rather than failing
silently.

**Credentials** (server-side only — never `NEXT_PUBLIC_`):
`CDSE_USERNAME`/`CDSE_PASSWORD`, `COPERNICUSMARINE_SERVICE_USERNAME`/`_PASSWORD`,
`AISSTREAM_API_KEY`.

## 3. Optional heavy dependencies

Two capabilities are deliberately not in the default image, because both are large and
neither is required for the reasoning chain to work:

```bash
make build-ml      # adds PyTorch (CPU wheels) for U-Net inference
```

`INSTALL_DRIFT=true` likewise adds OpenDrift/OpenOil. Without them the system uses the
analytical detector and the analytical drift engine, labels their output, and says so in
the UI and the report (AD-7, AD-18).

## 4. Database operations

```bash
make migrate                    # upgrade to head
make migrate-down               # roll back one revision
make makemigration M="message"  # autogenerate, then post-process
make db-reset                   # drop, re-migrate, re-seed (destructive)
make psql
```

`make makemigration` runs `infra/scripts/postprocess_migration.py` afterwards. That is
not optional: GeoAlchemy2 creates a spatial index automatically for every `Geometry`
column *and* Alembic emits an explicit `CREATE INDEX` for the same column, so an
unprocessed migration fails with `relation "idx_..." already exists`. The script turns
the implicit creation off, keeping the explicit statements, which are the reviewable half.

## 5. Production

1. **Secrets** from a secret manager, not a file. `SPILLTRACE_ENV=production` refuses to
   start with a placeholder secret, a short key, or SQL echo enabled.
2. **TLS** terminated at a reverse proxy; the app emits HSTS once it sees HTTPS.
3. **Images** built with `INSTALL_DEV=false` so test tooling is not shipped.
4. **Database** — managed PostgreSQL 16 with PostGIS 3.4; point-in-time recovery on;
   `ais_positions` and `drift_particles` are the growth tables and warrant a retention
   policy.
5. **Object storage** — S3 with versioning and server-side encryption. Set
   `S3_ENDPOINT_URL`/`S3_PUBLIC_ENDPOINT_URL` accordingly.
6. **Scaling** — the API is stateless; scale it horizontally. Workers scale by replica
   count and `SPILLTRACE_WORKER_CONCURRENCY`. The `ais-ingestor` must stay a **single
   replica per bounding box**: AISStream allows three connections per account and each
   subscription replaces the previous one.
7. **Backups** — the database holds the evidence chain; object storage holds the
   artifacts it references. Back up **both**, or a restored database will point at
   objects that no longer exist.

## 6. Health and observability

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness |
| `GET /health/ready` | readiness: database, Redis, object storage |
| `GET /api/v1/system/status` | full operational view (admin) |
| `GET /api/v1/system/providers` | which adapters are REAL vs SYNTHETIC (any user) |

Workers expose liveness through `/tmp/spilltrace-worker.alive`, whose mtime the container
healthcheck reads. Logs are structured JSON with a `request_id` / `job_id` correlation
key; secrets are redacted by a logging processor rather than by discipline.

## 7. Host used for development

Fedora 44, Podman 5.8.4 rootless, 8 cores, 15 GB RAM, no GPU, no Docker, Python 3.14 on
the host (containers pin 3.12). Every command in this document was run on that machine.
