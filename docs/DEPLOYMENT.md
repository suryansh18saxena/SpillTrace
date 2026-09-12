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

## 8. AWS EC2 + GitHub Actions (the hosted demo)

One `t2.large` (2 vCPU, 8 GB) runs the whole stack under Docker Compose behind Caddy.
GitHub Actions builds the images and rolls the host forward on every push to `main`.
Nothing is built on the instance; no source tree lives there.

```
push to main ──▶ .github/workflows/deploy.yml
                  ├─ build-api       infra/Dockerfile.backend  (INSTALL_ML=true, INSTALL_DEV=false)  ─▶ ghcr.io/<owner>/spilltrace-api:sha-xxxxxxx
                  ├─ build-frontend  infra/Dockerfile.frontend (NEXT_PUBLIC_API_BASE_URL=PUBLIC_URL) ─▶ ghcr.io/<owner>/spilltrace-frontend:sha-xxxxxxx
                  └─ deploy          scp infra/deploy/* ─▶ /opt/spilltrace ; ssh deploy.sh sha-xxxxxxx

EC2 /opt/spilltrace:  compose.prod.yml  Caddyfile  deploy.sh  init.sql  init-buckets.sh
                      .env (secrets, written once)   .image.env (tag, rewritten per deploy)
                      models/{best.pt, manifest.json, register_model.py}

browser ─▶ :80 caddy ─┬─ /api/*, /health*, /docs* ─▶ api:8000 ─┬─ postgres (PostGIS)
                      └─ /*                       ─▶ frontend:3000  ├─ redis
                                                         worker ────┤─ minio (S3)
                                                         ais-ingestor┘
```

The browser talks to **one origin** (`PUBLIC_URL`), so there is no CORS in play and no
credential ever leaves the instance; MinIO, Postgres and Redis publish no host ports.

### 8.1 One-time: the instance (AWS console)

| Item | Why | Where |
|---|---|---|
| **Root volume ≥ 30 GiB** | the ML image alone is ~3 GB unpacked; the 8 GiB default cannot hold the stack. `deploy.sh` refuses to run with < 5 GB free. | EC2 → Volumes → select → *Modify volume* → 30 GiB. Then `bash infra/deploy/bootstrap.sh` again (it runs `growpart`/`resize2fs`). |
| **Security group inbound: 80/tcp (and 443/tcp)** from `0.0.0.0/0` | Caddy is the only published port. Keep 22 restricted to your IP. | EC2 → Security Groups → `launch-wizard-15` → *Edit inbound rules* |
| **Elastic IP** (recommended) | a stop/start changes the public IP, and `PUBLIC_URL` is baked into the frontend bundle. | EC2 → Elastic IPs → *Allocate* → *Associate* |

### 8.2 One-time: the host

```bash
# 1. prepare Ubuntu: Docker + Compose plugin, 2 GiB swap, /opt/spilltrace, log rotation
ssh -i <key.pem> ubuntu@<host> 'bash -s' < infra/deploy/bootstrap.sh

# 2. write the server .env: fresh secrets, provider keys copied from your local .env
bash infra/deploy/render-env.sh http://<host> > /tmp/server.env
scp -i <key.pem> /tmp/server.env ubuntu@<host>:/opt/spilltrace/.env && shred -u /tmp/server.env

# 3. ship the trained checkpoint (gitignored, 98 MB) so deploy.sh can register it
scp -i <key.pem> ml/runs/colab-resnet34-run3/{best.pt,manifest.json} ml/scripts/register_model.py \
    ubuntu@<host>:/opt/spilltrace/models/
```

`render-env.sh` chooses `SPILLTRACE_ENV=staging` for an `http://` URL on purpose: in
`production` the refresh cookie is `Secure` and a plain-HTTP deployment cannot log in.
An `https://` URL selects `production` and sets `SITE_ADDRESS` to the host name so Caddy
provisions a Let's Encrypt certificate itself (needs a DNS name pointing at the instance
and port 443 open).

### 8.3 One-time: GitHub

*Settings → Secrets and variables → Actions.*

| Kind | Name | Value |
|---|---|---|
| secret | `EC2_HOST` | public IP or DNS name of the instance |
| secret | `EC2_USER` | `ubuntu` |
| secret | `EC2_SSH_KEY` | a private key whose public half is in `~ubuntu/.ssh/authorized_keys` (use a dedicated key, not the console `.pem`) |
| variable | `PUBLIC_URL` | optional: the URL the post-deploy smoke test calls (defaults to `http://EC2_HOST`) |

The workflow also uses the job-scoped `GITHUB_TOKEN` to push to GHCR and to let the
instance pull. Packages are private by default; that is fine because `deploy.sh` logs the
instance in with the same token for the duration of the job.

### 8.4 Every deploy

```bash
git push origin main            # builds both images (~10 min cold, ~3 min cached), deploys, smoke-tests /health
```

`deploy.sh` on the host: preflight free disk → `docker login ghcr.io` → `compose pull` →
`compose up -d --remove-orphans` (the `migrate` one-shot applies Alembic head and the
idempotent account seed before the API starts) → waits for `/health` → **first run only**:
registers `models/best.pt` as `spilltrace-unet 0.2.0` (active) and creates the SYNTHETIC
`kutch-01` demo case → prunes old images.

**Manual deploy / rollback:** *Actions → Deploy → Run workflow* with an existing tag
(`sha-abc1234`) skips the build, or on the host:

```bash
cd /opt/spilltrace && bash deploy.sh sha-abc1234
```

### 8.5 Operating it

```bash
ssh ubuntu@<host>
cd /opt/spilltrace
alias dc='docker compose --env-file .env --env-file .image.env -f compose.prod.yml'
dc ps                                   # health of every service
dc logs -f --tail=100 api worker        # structured JSON logs
dc exec api python -m spilltrace.db.seed          # re-run the seed (idempotent)
dc --profile tools run --rm register-model         # (re)register the checkpoint
dc exec postgres pg_dump -U spilltrace spilltrace > backup.sql
```

Seeded accounts are `SPILLTRACE_ADMIN_EMAIL` / `SPILLTRACE_ADMIN_PASSWORD` and the analyst
pair in `/opt/spilltrace/.env`. The seed never overwrites an existing user, so changing a
password in `.env` after the first run has no effect; change it in the UI.

**Data lives in Docker volumes** (`spilltrace_postgres-data`, `spilltrace_minio-data`,
`spilltrace_app-data`), so a redeploy keeps cases, scenes and the registered model; only
`docker compose down -v` deletes them. Back up Postgres **and** MinIO together (§5.7).

### 8.6 HTTPS (Let's Encrypt, automatic)

The frontend image is built **same-origin** (`NEXT_PUBLIC_API_BASE_URL=""`): the browser calls
`/api` on whatever host served the page. So HTTP ↔ HTTPS, a new IP or a real domain is an
`.env` change on the server, never a rebuild.

Prerequisites: inbound **80/tcp and 443/tcp** open in the security group (Let's Encrypt validates
on 80; browsers use 443), and ideally an **Elastic IP**, because a stop/start changes the public IP
and with it the sslip.io name.

```bash
ssh ubuntu@<host>
cd /opt/spilltrace
bash enable-https.sh                          # https://<ip-with-dashes>.sslip.io — no domain needed
bash enable-https.sh spilltrace.example.org   # your own domain; its A record must point at the IP
bash enable-https.sh --http                   # back to plain HTTP on the IP
```

The script checks the name resolves to this instance, sets `PUBLIC_URL`, `SITE_ADDRESS`,
`REDIRECT_ADDRESS` and `SPILLTRACE_ENV=production` (Secure refresh cookie, HSTS), recreates the
stack, and waits until a valid certificate answers. Caddy renews it on its own; certificates
persist in the `caddy-data` volume. After switching, set the GitHub variable `PUBLIC_URL` to the
HTTPS URL so the post-deploy smoke test calls it directly (the IP redirects there anyway).

`sslip.io` is a public wildcard DNS service: `18-212-85-28.sslip.io` resolves to `18.212.85.28`.
It is on the Public Suffix List, so Let's Encrypt rate limits apply per name, not to all of
sslip.io. Use a real domain for anything beyond a demo.

### 8.7 Known limits of this topology

* Plain HTTP on a bare IP means no TLS, no HSTS and `SPILLTRACE_ENV=staging`; §8.6 fixes all
  three with one command.
* The instance's SSH host key is trusted on first use by the workflow (`ssh-keyscan`).
  Pin it by replacing that line with a `known_hosts` entry if the instance is long-lived.
* One host, no replicas: the API, worker and AIS ingestor share 2 vCPUs. U-Net inference
  on CPU takes minutes per scene; watch `dc logs worker`.
* Hosting the checkpoint: it is not in git and not in the image, so a **new** instance
  needs step 8.2-3 before its first deploy registers a model. Until then the pipeline
  falls back to the analytical detector and says so.
