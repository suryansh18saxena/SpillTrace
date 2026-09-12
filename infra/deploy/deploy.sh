#!/usr/bin/env bash
# Roll the SPILLTRACE stack forward to one image tag. Runs ON THE SERVER, from
# /opt/spilltrace, invoked by .github/workflows/deploy.yml (or by hand to roll back:
#   bash deploy.sh sha-abc1234 ).
#
# Expects in the working directory: compose.prod.yml, Caddyfile, init.sql,
# init-buckets.sh, .env (secrets), and optionally models/{best.pt,manifest.json,
# register_model.py}.  Env: GHCR_TOKEN + GHCR_USER to pull private packages.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/spilltrace}"
IMAGE_TAG="${1:?usage: deploy.sh <image-tag> [git-sha]}"
GIT_SHA="${2:-${IMAGE_TAG}}"
PUBLIC_HEALTH="${PUBLIC_HEALTH:-http://127.0.0.1/health}"
MIN_FREE_GB="${MIN_FREE_GB:-5}"

cd "${APP_DIR}"
[ -f .env ] || { echo "deploy: ${APP_DIR}/.env is missing — run infra/deploy/render-env.sh first"; exit 1; }

# Preflight: the ML image alone is ~3 GB unpacked; an 8 GB root disk cannot hold the stack.
avail_gb=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
if [ "${avail_gb}" -lt "${MIN_FREE_GB}" ]; then
  echo "deploy: only ${avail_gb} GB free on / (need >= ${MIN_FREE_GB}). Enlarge the EBS volume, re-run bootstrap.sh."
  exit 1
fi

if [ -n "${GHCR_TOKEN:-}" ]; then
  echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USER:-github}" --password-stdin >/dev/null
fi

printf 'IMAGE_TAG=%s\nSPILLTRACE_GIT_SHA=%s\n' "${IMAGE_TAG}" "${GIT_SHA}" > .image.env
compose() { docker compose --env-file .env --env-file .image.env -f compose.prod.yml "$@"; }

echo "== pull ${IMAGE_TAG}"
compose pull --quiet
echo "== up"
compose up -d --remove-orphans

echo "== waiting for ${PUBLIC_HEALTH}"
for _ in $(seq 1 60); do
  if body=$(curl -fsS "${PUBLIC_HEALTH}" 2>/dev/null); then
    echo "healthy: ${body}"
    break
  fi
  sleep 5
done
curl -fsS "${PUBLIC_HEALTH}" >/dev/null || { echo "deploy: API never became healthy"; compose ps; compose logs --tail=80 api migrate; exit 1; }

# First-deploy extras, each guarded by a marker so they run exactly once.
if [ -f models/best.pt ] && [ -f models/manifest.json ] && [ ! -f .model-registered ]; then
  echo "== registering trained checkpoint"
  compose --profile tools run --rm register-model && touch .model-registered
fi
if [ ! -f .demo-created ]; then
  echo "== creating the SYNTHETIC demo case (kutch-01, seed 42)"
  compose exec -T api python -m spilltrace.demo.create --scenario kutch-01 --seed 42 && touch .demo-created
fi

docker image prune -f >/dev/null
echo "== status"
compose ps
echo "deploy: OK (${IMAGE_TAG})"
