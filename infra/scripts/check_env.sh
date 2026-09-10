#!/usr/bin/env bash
# Fail if .env is missing a required variable or still holds a placeholder.
set -euo pipefail
cd "$(dirname "$0")/../.."

REQUIRED=(SPILLTRACE_SECRET_KEY POSTGRES_PASSWORD POSTGRES_USER POSTGRES_DB S3_ACCESS_KEY S3_SECRET_KEY S3_BUCKET)
status=0

for key in "${REQUIRED[@]}"; do
  value="$(grep -E "^${key}=" .env | head -1 | cut -d= -f2- || true)"
  if [[ -z "${value}" ]]; then
    echo "MISSING : ${key}"; status=1
  elif [[ "${value}" == change-me* ]]; then
    echo "PLACEHOLDER: ${key} is still '${value}'. Run 'make init-env' or set a real value."; status=1
  fi
done

# Any variable exposed to the browser must not look like a credential.
while IFS='=' read -r key _; do
  case "${key}" in
    NEXT_PUBLIC_*KEY|NEXT_PUBLIC_*SECRET|NEXT_PUBLIC_*PASSWORD|NEXT_PUBLIC_*TOKEN)
      echo "UNSAFE  : ${key} would ship a credential to the browser (CON-004)."; status=1 ;;
  esac
done < <(grep -E '^[A-Z_]+=' .env || true)

[[ $status -eq 0 ]] && echo "env: OK"
exit $status
