#!/usr/bin/env bash
# One-time host preparation for SPILLTRACE on Ubuntu (tested on Ubuntu 26.04 / EC2 t2.large).
# Idempotent: safe to re-run after the EBS volume is enlarged.
#
#   ssh ubuntu@<host> 'bash -s' < infra/deploy/bootstrap.sh
set -euo pipefail

APP_DIR=/opt/spilltrace
ROOT_DISK="${ROOT_DISK:-/dev/xvda}"
ROOT_PART="${ROOT_PART:-1}"

echo "== 1/5 root filesystem"
# If the EBS volume was enlarged in the console, claim the space. growpart exits 1
# with NOCHANGE when there is nothing to do, which is fine.
if command -v growpart >/dev/null 2>&1 && [ -b "${ROOT_DISK}" ]; then
  sudo growpart "${ROOT_DISK}" "${ROOT_PART}" 2>&1 | tail -1 || true
  sudo resize2fs "${ROOT_DISK}${ROOT_PART}" 2>&1 | tail -1 || true
fi
df -h / | tail -1

echo "== 2/5 docker engine + compose plugin (Ubuntu repositories)"
if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io docker-compose-v2 curl
fi
sudo systemctl enable --now docker >/dev/null
sudo usermod -aG docker "${USER}"
docker --version
sudo docker compose version

echo "== 3/5 swap (2 GiB; the worker loads a 24M-parameter U-Net on CPU)"
if ! swapon --show --noheadings | grep -q '/swapfile'; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi
free -h | sed -n '1,3p'

echo "== 4/5 application directory ${APP_DIR}"
sudo mkdir -p "${APP_DIR}/models"
sudo chown -R "${USER}:${USER}" "${APP_DIR}"
chmod 750 "${APP_DIR}"

echo "== 5/5 log rotation for container logs"
if [ ! -f /etc/docker/daemon.json ]; then
  printf '{\n  "log-driver": "json-file",\n  "log-opts": { "max-size": "20m", "max-file": "5" }\n}\n' | sudo tee /etc/docker/daemon.json >/dev/null
  sudo systemctl restart docker
fi

echo
echo "bootstrap: OK"
echo "next: write ${APP_DIR}/.env (infra/deploy/render-env.sh), copy the checkpoint into ${APP_DIR}/models, then push to main."
