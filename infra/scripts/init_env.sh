#!/usr/bin/env bash
# Create .env from .env.example, generating strong local secrets.
set -euo pipefail
cd "$(dirname "$0")/../.."

if [[ -f .env ]]; then
  echo ".env already exists — not overwriting. Delete it first if you want a fresh one."
  exit 0
fi

gen() { openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

SECRET_KEY="$(gen)"
PG_PASS="$(gen | cut -c1-24)"
S3_PASS="$(gen | cut -c1-24)"

sed -e "s|^SPILLTRACE_SECRET_KEY=.*|SPILLTRACE_SECRET_KEY=${SECRET_KEY}|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${PG_PASS}|" \
    -e "s|^S3_SECRET_KEY=.*|S3_SECRET_KEY=${S3_PASS}|" \
    .env.example > .env
chmod 600 .env
echo "Created .env with generated local secrets (mode 600)."
echo "Fill in CDSE_/COPERNICUSMARINE_/AISSTREAM_ values only when you connect real providers."
