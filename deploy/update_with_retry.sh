#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/root/bishe"
MAX_RETRIES=5
RETRY_DELAY_SECONDS=6
DOMAIN_HEALTH_URL="https://openkgfield.duckdns.org:30043/api/health"
LOCAL_HEALTH_URL="http://127.0.0.1:8080/api/health"

cd "${ROOT_DIR}"
git config --global http.version HTTP/1.1 || true

echo "[1/3] Pull latest code (max ${MAX_RETRIES} attempts)..."
pull_ok=0
for attempt in $(seq 1 "${MAX_RETRIES}"); do
  if git pull --rebase --autostash origin main; then
    pull_ok=1
    break
  fi
  echo "pull failed (attempt ${attempt}/${MAX_RETRIES}), retry in ${RETRY_DELAY_SECONDS}s..."
  sleep "${RETRY_DELAY_SECONDS}"
done

if [ "${pull_ok}" -ne 1 ]; then
  echo "WARN: git pull failed after ${MAX_RETRIES} attempts, continue with local code."
fi

echo "[2/4] Pull base image if needed..."
docker pull python:3.12-slim || true

compose_cmd=()
if docker compose version >/dev/null 2>&1; then
  compose_cmd=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  compose_cmd=(docker-compose)
else
  echo "ERROR: neither 'docker compose' nor 'docker-compose' is available."
  exit 1
fi

echo "[3/4] Rebuild community-service + resource-service + api-gateway..."
DOCKER_BUILDKIT=0 "${compose_cmd[@]}" -f docker-compose.yml build community-service resource-service api-gateway

echo "[4/4] Restart community-service + resource-service + gateway + caddy..."
"${compose_cmd[@]}" -f docker-compose.yml -f docker-compose.public.yml up -d --no-build community-service resource-service api-gateway caddy

echo "[5/4] Health check..."
if ! curl -fsS "${DOMAIN_HEALTH_URL}"; then
  echo
  echo "WARN: domain health check failed, fallback to local endpoint."
  curl -fsS "${LOCAL_HEALTH_URL}"
fi

echo
echo "DONE"
