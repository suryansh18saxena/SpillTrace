#!/usr/bin/env bash
# Fail the build if a provider credential could reach the browser (CON-004, NFR-007).
set -uo pipefail
cd "$(dirname "$0")/../.."
status=0

SECRET_NAMES='AISSTREAM_API_KEY|CDSE_PASSWORD|CDSE_USERNAME|COPERNICUSMARINE_SERVICE_PASSWORD|COPERNICUSMARINE_SERVICE_USERNAME|POSTGRES_PASSWORD|S3_SECRET_KEY|SPILLTRACE_SECRET_KEY'

echo "== 1. credential names referenced in frontend source =="
if grep -rInE "$SECRET_NAMES" frontend/src frontend/app 2>/dev/null | grep -v '^\s*//' ; then
  echo "FAIL: a server-side credential name appears in frontend source."; status=1
else
  echo "ok"
fi

echo "== 2. credential values present in a built client bundle =="
if [[ -d frontend/.next ]]; then
  if grep -rIlE "$SECRET_NAMES" frontend/.next/static 2>/dev/null; then
    echo "FAIL: credential name found in the built client bundle."; status=1
  else
    echo "ok"
  fi
else
  echo "skipped (no build present)"
fi

echo "== 3. .env is not tracked by git =="
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "FAIL: .env is tracked by git."; status=1
else
  echo "ok"
fi

echo "== 4. no obvious hard-coded secrets in source =="
if grep -rInE "(password|secret|api[_-]?key)\s*[:=]\s*[\"'][A-Za-z0-9/+=_-]{16,}[\"']" \
     backend/src frontend/src ml/src 2>/dev/null \
   | grep -viE '(example|placeholder|change-me|test|fixture|dummy|\.md:)'; then
  echo "FAIL: possible hard-coded secret."; status=1
else
  echo "ok"
fi

[[ $status -eq 0 ]] && echo "audit-secrets: PASS" || echo "audit-secrets: FAIL"
exit $status
