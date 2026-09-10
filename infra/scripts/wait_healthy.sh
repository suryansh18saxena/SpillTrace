#!/usr/bin/env bash
# Block until the API answers /health, then print a summary.
set -uo pipefail
URL="${1:-http://localhost:${API_PORT_HOST:-8000}/health}"
DEADLINE=$(( $(date +%s) + ${TIMEOUT:-180} ))

printf 'waiting for %s ' "$URL"
while (( $(date +%s) < DEADLINE )); do
  if body=$(curl -fsS "$URL" 2>/dev/null); then
    printf '\nAPI healthy: %s\n' "$body"
    exit 0
  fi
  printf '.'
  sleep 3
done
printf '\nTIMEOUT: API did not become healthy.\n'
exit 1
