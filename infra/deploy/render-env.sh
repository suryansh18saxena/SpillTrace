#!/usr/bin/env bash
# Render the server-side .env for the production stack, to stdout.
#
#   bash infra/deploy/render-env.sh http://18.212.85.28 > /tmp/server.env
#   scp /tmp/server.env ubuntu@18.212.85.28:/opt/spilltrace/.env   # then shred /tmp/server.env
#
# Secrets are generated fresh. Provider credentials (CDSE / CMEMS / AISStream) and
# the adapter selection are copied from the local .env when it exists, because those
# are the only values that cannot be generated. Nothing here is committed (CON-004).
set -euo pipefail
cd "$(dirname "$0")/../.."

PUBLIC_URL="${1:?usage: render-env.sh <public-url e.g. http://18.212.85.28> [image-owner]}"
PUBLIC_URL="${PUBLIC_URL%/}"
OWNER="${2:-$(git remote get-url origin 2>/dev/null | sed -E 's#.*[:/]([^/]+)/[^/]+(\.git)?$#\1#' | tr '[:upper:]' '[:lower:]')}"
OWNER="${OWNER:-suryansh18saxena}"

gen() { openssl rand -hex "${1:-32}"; }
pw()  { openssl rand -base64 24 | tr -d '/+=' | cut -c1-20; }
local_val() { [ -f .env ] && grep -E "^$1=" .env | head -1 | cut -d= -f2- | sed -E 's/[[:space:]]+#.*$//' | xargs || true; }
or_default() { local v; v="$(local_val "$1")"; printf '%s' "${v:-$2}"; }

case "${PUBLIC_URL}" in
  https://*) ENV_MODE=production; SITE_ADDRESS="${PUBLIC_URL#https://}" ;;
  *)         ENV_MODE=staging;    SITE_ADDRESS=":80" ;;
esac
REDIRECT_ADDRESS="http://redirect.invalid"

cat <<ENV
# SPILLTRACE — server environment (generated $(date -u +%FT%TZ) by infra/deploy/render-env.sh)
# Mode 600. Never commit. Regenerate with render-env.sh; edit by hand only for provider keys.

# ---- edge -----------------------------------------------------------------
PUBLIC_URL=${PUBLIC_URL}
SITE_ADDRESS=${SITE_ADDRESS}
REDIRECT_ADDRESS=${REDIRECT_ADDRESS}
# production => Secure refresh cookie, which only works over HTTPS. Plain-HTTP-on-IP
# deployments must stay 'staging' or nobody can log in.
SPILLTRACE_ENV=${ENV_MODE}
SPILLTRACE_LOG_LEVEL=INFO
SPILLTRACE_VERSION=$(or_default SPILLTRACE_VERSION 0.1.0)

# ---- images (tags come from .image.env, written by deploy.sh) --------------
BACKEND_IMAGE=ghcr.io/${OWNER}/spilltrace-api
FRONTEND_IMAGE=ghcr.io/${OWNER}/spilltrace-frontend
MODEL_VERSION=0.2.0

# ---- security ---------------------------------------------------------------
SPILLTRACE_SECRET_KEY=$(gen 32)
SPILLTRACE_ACCESS_TOKEN_TTL_SECONDS=900
SPILLTRACE_REFRESH_TOKEN_TTL_SECONDS=604800

# ---- database / cache / object storage (all container-internal) ------------
POSTGRES_USER=spilltrace
POSTGRES_PASSWORD=$(gen 16)
POSTGRES_DB=spilltrace
REDIS_DB=0
S3_ACCESS_KEY=spilltrace
S3_SECRET_KEY=$(gen 16)
S3_BUCKET=spilltrace
S3_REGION=us-east-1
S3_PUBLIC_ENDPOINT_URL=http://minio:9000

# ---- seeded accounts (seed is idempotent; passwords apply on first creation) --
SPILLTRACE_ADMIN_EMAIL=admin@spilltrace.example.com
SPILLTRACE_ADMIN_PASSWORD=$(pw)
SPILLTRACE_ANALYST_EMAIL=analyst@spilltrace.example.com
SPILLTRACE_ANALYST_PASSWORD=$(pw)

# ---- adapter selection (copied from local .env when present) ----------------
SPILLTRACE_SATELLITE_PROVIDER=$(or_default SPILLTRACE_SATELLITE_PROVIDER fixture)
SPILLTRACE_ENVIRONMENT_PROVIDER=$(or_default SPILLTRACE_ENVIRONMENT_PROVIDER synthetic)
SPILLTRACE_AIS_PROVIDER=$(or_default SPILLTRACE_AIS_PROVIDER synthetic)
SPILLTRACE_DRIFT_ENGINE=$(or_default SPILLTRACE_DRIFT_ENGINE analytical)
SPILLTRACE_SEGMENTATION_MODEL=$(or_default SPILLTRACE_SEGMENTATION_MODEL analytical)

# ---- provider credentials — SERVER SIDE ONLY --------------------------------
CDSE_USERNAME=$(local_val CDSE_USERNAME)
CDSE_PASSWORD=$(local_val CDSE_PASSWORD)
CDSE_CLIENT_ID=$(or_default CDSE_CLIENT_ID cdse-public)
COPERNICUSMARINE_SERVICE_USERNAME=$(local_val COPERNICUSMARINE_SERVICE_USERNAME)
COPERNICUSMARINE_SERVICE_PASSWORD=$(local_val COPERNICUSMARINE_SERVICE_PASSWORD)
AISSTREAM_API_KEY=$(local_val AISSTREAM_API_KEY)

# ---- pipeline limits ----------------------------------------------------------
SPILLTRACE_MAX_AOI_KM2=$(or_default SPILLTRACE_MAX_AOI_KM2 250000)
SPILLTRACE_MAX_TIME_WINDOW_DAYS=$(or_default SPILLTRACE_MAX_TIME_WINDOW_DAYS 30)
SPILLTRACE_JOB_MAX_ATTEMPTS=3
SPILLTRACE_WORKER_CONCURRENCY=2
ENV
