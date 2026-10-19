#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK_DIR="${ROOT_DIR}/stacks/media"
ENV_FILE="${STACK_DIR}/env/.env"
COMPOSE_FILE="${STACK_DIR}/compose.yaml"
CADDYFILE="${STACK_DIR}/caddy/Caddyfile"
CONFIGURE_SCRIPT="${ROOT_DIR}/scripts/configure-public-access.py"

for required_file in \
  "$ENV_FILE" \
  "$COMPOSE_FILE" \
  "$CADDYFILE" \
  "$CONFIGURE_SCRIPT"; do
  if [[ ! -f "$required_file" ]]; then
    echo "ERROR: Missing required file: ${required_file}" >&2
    exit 1
  fi
done

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${NAS_HOST:?NAS_HOST is required}"
: "${NAS_USER:?NAS_USER is required}"
: "${NAS_STACK_DIR:?NAS_STACK_DIR is required}"

REMOTE="${NAS_USER}@${NAS_HOST}"
REMOTE_STAGING="/volume1/docker/deploy-staging/${NAS_USER}/public-access-$$"
SSH=(
  ssh
  -o ControlMaster=auto
  -o ControlPersist=60
  -o ConnectTimeout=15
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=4
)

cleanup() {
  "${SSH[@]}" "$REMOTE" "rm -rf '${REMOTE_STAGING}'" >/dev/null 2>&1 || true
}
trap cleanup EXIT

"${SSH[@]}" "$REMOTE" "mkdir -p '${REMOTE_STAGING}'"
"${SSH[@]}" "$REMOTE" "cat > '${REMOTE_STAGING}/compose.yaml'" < "$COMPOSE_FILE"
"${SSH[@]}" "$REMOTE" "cat > '${REMOTE_STAGING}/Caddyfile'" < "$CADDYFILE"
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_STAGING}/configure-public-access.py'" \
  < "$CONFIGURE_SCRIPT"

# shellcheck disable=SC2029
"${SSH[@]}" -t "$REMOTE" "
  set -euo pipefail
  if [[ ! -s /volume1/docker/duckdns/duckdns.env ]]; then
    echo 'ERROR: DuckDNS must be configured before public media access.' >&2
    exit 1
  fi

  sudo -n python3 '${NAS_STACK_DIR}/check-nas-preflight.py'
  sudo -n install -d -m 0755 '${NAS_STACK_DIR}/caddy'
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/compose.yaml' \
    '${NAS_STACK_DIR}/compose.yaml'
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/Caddyfile' \
    '${NAS_STACK_DIR}/caddy/Caddyfile'
  sudo -n install -m 0755 \
    '${REMOTE_STAGING}/configure-public-access.py' \
    '${NAS_STACK_DIR}/configure-public-access.py'

  sudo -n python3 '${NAS_STACK_DIR}/configure-public-access.py' --prepare
  cd '${NAS_STACK_DIR}'
  sudo -n docker compose config >/dev/null
  sudo -n timeout -k 30s 10m docker compose pull caddy
  sudo -n timeout -k 30s 5m docker compose up -d --no-deps caddy

  sudo -n python3 '${NAS_STACK_DIR}/configure-public-access.py'
  sudo -n python3 '${NAS_STACK_DIR}/configure-public-access.py' --apply
  sudo -n timeout -k 15s 3m docker compose restart jellyfin seerr

  for attempt in {1..30}; do
    if curl --silent --fail --max-time 5 \
      http://127.0.0.1:8899/health >/dev/null; then
      break
    fi
    if [[ \"\${attempt}\" -eq 30 ]]; then
      echo 'ERROR: Jellyfin did not recover after network configuration.' >&2
      exit 1
    fi
    sleep 2
  done

  for attempt in {1..30}; do
    if curl --silent --fail --max-time 5 \
      http://127.0.0.1:5055/api/v1/status >/dev/null; then
      break
    fi
    if [[ \"\${attempt}\" -eq 30 ]]; then
      echo 'ERROR: Seerr did not recover cleanly after network configuration.' >&2
      exit 1
    fi
    sleep 2
  done

  sudo -n python3 '${NAS_STACK_DIR}/configure-public-access.py'
  sudo -n docker compose ps caddy jellyfin seerr
"

echo "Secure public media proxy installed."
echo "Router mappings still required: TCP 80 -> proxy 10.0.0.254:80, TCP 443 -> proxy 10.0.0.254:443."
