#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/stacks/media/env/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: Missing environment file: ${ENV_FILE}" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${NAS_HOST:?NAS_HOST is required}"
: "${NAS_USER:?NAS_USER is required}"
: "${NAS_STACK_DIR:?NAS_STACK_DIR is required}"

REMOTE="${NAS_USER}@${NAS_HOST}"
SSH=(
  ssh
  -o ConnectTimeout=15
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=4
)
STAGING="/volume1/docker/deploy-staging/${NAS_USER}/media-reliability-$$"

LOCAL_FILES=(
  "scripts/audit-imported-audio.py"
  "scripts/build-health-dashboard.py"
  "scripts/check-nas-preflight.py"
  "scripts/check-media-live.py"
  "scripts/monitor-media-stack.sh"
  "stacks/media/systemd/media-stack-archive-spanish-dispatch.service"
  "stacks/media/systemd/media-stack-btarg-series.service"
  "stacks/media/systemd/media-stack-hardlink-audit.service"
  "stacks/media/systemd/media-stack-healthcheck.service"
  "stacks/media/systemd/media-stack-imported-audio-audit.service"
  "stacks/media/systemd/media-stack-imported-audio-audit.timer"
  "stacks/media/systemd/media-stack-private-dispatch.service"
  "stacks/media/systemd/media-stack-public-cleanup.service"
  "stacks/media/systemd/media-stack-stalled-public-cleanup.service"
  "stacks/media/systemd/media-stack-torrent-notifications.service"
  "stacks/media/systemd/media-stack-watchdog.service"
)

"${SSH[@]}" "$REMOTE" "mkdir -p '${STAGING}'"
for relative in "${LOCAL_FILES[@]}"; do
  name="$(basename "$relative")"
  "${SSH[@]}" "$REMOTE" "cat > '${STAGING}/${name}'" < "${ROOT_DIR}/${relative}"
done

# shellcheck disable=SC2029
"${SSH[@]}" -t "$REMOTE" "
  set -e
  sudo install -m 0755 '${STAGING}/audit-imported-audio.py' '${NAS_STACK_DIR}/audit-imported-audio.py'
  sudo install -m 0755 '${STAGING}/build-health-dashboard.py' '${NAS_STACK_DIR}/build-health-dashboard.py'
  sudo install -m 0755 '${STAGING}/check-nas-preflight.py' '${NAS_STACK_DIR}/check-nas-preflight.py'
  sudo install -m 0755 '${STAGING}/check-media-live.py' '${NAS_STACK_DIR}/check-media-live.py'
  sudo install -m 0755 '${STAGING}/monitor-media-stack.sh' '${NAS_STACK_DIR}/monitor-media-stack.sh'
  for unit in '${STAGING}'/*.service '${STAGING}'/*.timer; do
    sudo install -m 0644 \"\${unit}\" \"/etc/systemd/system/\$(basename \"\${unit}\")\"
  done
  sudo systemctl daemon-reload
  sudo systemctl enable --now media-stack-imported-audio-audit.timer
  rm -rf '${STAGING}'
"

echo "Focused reliability deployment completed."
