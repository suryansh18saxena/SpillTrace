#!/usr/bin/env bash
# Switch the running SPILLTRACE stack between plain HTTP and HTTPS. Runs ON THE SERVER.
#
#   bash enable-https.sh                       # HTTPS on <public-ip-with-dashes>.sslip.io
#   bash enable-https.sh spilltrace.example.org  # HTTPS on your own domain (A record -> this IP)
#   bash enable-https.sh --http                # back to plain HTTP on the IP
#
# Needs inbound 80/tcp and 443/tcp open in the security group: Let's Encrypt validates
# over port 80, and browsers reach the site on 443. Caddy obtains and renews the
# certificate itself; nothing is stored outside the caddy-data volume.
#
# Only .env changes. The frontend image is built same-origin, so no rebuild happens.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/spilltrace}"
cd "${APP_DIR}"
[ -f .env ] || { echo "enable-https: ${APP_DIR}/.env is missing"; exit 1; }
[ -f .image.env ] || { echo "enable-https: nothing deployed yet (.image.env missing); deploy first"; exit 1; }

compose() { docker compose --env-file .env --env-file .image.env -f compose.prod.yml "$@"; }

set_env() {  # set_env KEY VALUE  — replace or append, keeping mode 600
  local key="$1" value="$2"
  if grep -qE "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${value}|" .env
  else
    printf '%s=%s\n' "${key}" "${value}" >> .env
  fi
}

public_ip() {
  local token
  token=$(curl -fsS -m 3 -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null || true)
  curl -fsS -m 3 -H "X-aws-ec2-metadata-token: ${token}" \
    http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null \
    || curl -fsS -m 5 https://checkip.amazonaws.com | tr -d '[:space:]'
}

IP="$(public_ip)"
[ -n "${IP}" ] || { echo "enable-https: could not determine the public IPv4 address"; exit 1; }

if [ "${1:-}" = "--http" ]; then
  set_env PUBLIC_URL "http://${IP}"
  set_env SITE_ADDRESS ":80"
  set_env REDIRECT_ADDRESS "http://redirect.invalid"
  set_env SPILLTRACE_ENV "staging"
  compose up -d --remove-orphans
  echo "enable-https: plain HTTP at http://${IP}"
  exit 0
fi

HOST="${1:-${IP//./-}.sslip.io}"
HOST="${HOST#https://}"; HOST="${HOST#http://}"; HOST="${HOST%%/*}"

echo "== preflight: ${HOST} must resolve to ${IP}"
RESOLVED="$(getent ahostsv4 "${HOST}" | awk 'NR==1{print $1}')"
if [ "${RESOLVED}" != "${IP}" ]; then
  echo "enable-https: ${HOST} resolves to '${RESOLVED:-nothing}', not ${IP}."
  echo "Point an A record at ${IP} (or use the default sslip.io name) and retry."
  exit 1
fi

set_env PUBLIC_URL "https://${HOST}"
set_env SITE_ADDRESS "${HOST}"
set_env REDIRECT_ADDRESS "http://${IP}"
# Secure refresh cookie, HSTS and the production start-up checks.
set_env SPILLTRACE_ENV "production"

echo "== restarting with HTTPS on ${HOST}"
compose up -d --remove-orphans

echo "== waiting for the certificate (Caddy talks to Let's Encrypt)"
for _ in $(seq 1 40); do
  if curl -fsS -m 10 --resolve "${HOST}:443:127.0.0.1" "https://${HOST}/health" >/dev/null 2>&1; then
    echo "certificate: OK"
    curl -fsS --resolve "${HOST}:443:127.0.0.1" "https://${HOST}/health"; echo
    echo | openssl s_client -connect 127.0.0.1:443 -servername "${HOST}" 2>/dev/null \
      | openssl x509 -noout -issuer -subject -enddate 2>/dev/null || true
    curl -s -o /dev/null -w "http://${IP}/ -> %{http_code} %{redirect_url}\n" "http://${IP}/"
    echo "enable-https: https://${HOST}"
    exit 0
  fi
  sleep 6
done

echo "enable-https: no valid certificate after 4 minutes. Caddy's log:"
compose logs --tail=40 caddy
echo "Common causes: port 80 closed in the security group, or a Let's Encrypt rate limit."
exit 1
