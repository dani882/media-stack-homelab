#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK_DIR="${ROOT_DIR}/stacks/media"
ENV_FILE="${STACK_DIR}/env/.env"
PROWLARR_SCRIPT="${ROOT_DIR}/scripts/configure-prowlarr.py"
AUDIT_SCRIPT="${ROOT_DIR}/scripts/audit-private-trackers.py"
LEARNING_SCRIPT="${ROOT_DIR}/scripts/import-docspedia-learning.py"
LEARNING_SERVICE="${STACK_DIR}/systemd/media-stack-docspedia-learning.service"
LEARNING_TIMER="${STACK_DIR}/systemd/media-stack-docspedia-learning.timer"

for required_file in \
  "$ENV_FILE" \
  "$PROWLARR_SCRIPT" \
  "$AUDIT_SCRIPT" \
  "$LEARNING_SCRIPT" \
  "$LEARNING_SERVICE" \
  "$LEARNING_TIMER"; do
  if [[ ! -f "$required_file" ]]; then
    echo "ERROR: Missing required file: ${required_file}"
    exit 1
  fi
done

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${NAS_HOST:?NAS_HOST is required}"
: "${NAS_USER:?NAS_USER is required}"

REMOTE="${NAS_USER}@${NAS_HOST}"
REMOTE_STAGING="/volume1/docker/deploy-staging/${NAS_USER}"
REMOTE_PROWLARR="${REMOTE_STAGING}/configure-prowlarr-${USER}-$$.py"
REMOTE_AUDIT="${REMOTE_STAGING}/audit-private-trackers-${USER}-$$.py"
REMOTE_LEARNING="${REMOTE_STAGING}/import-docspedia-learning-${USER}-$$.py"
REMOTE_LEARNING_SERVICE="${REMOTE_STAGING}/media-stack-docspedia-learning-${USER}-$$.service"
REMOTE_LEARNING_TIMER="${REMOTE_STAGING}/media-stack-docspedia-learning-${USER}-$$.timer"
SSH=(
  ssh
  -o ControlMaster=auto
  -o ControlPersist=60
  -o ConnectTimeout=15
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=4
)

"${SSH[@]}" "$REMOTE" "mkdir -p '${REMOTE_STAGING}'"
"${SSH[@]}" "$REMOTE" "cat > '${REMOTE_PROWLARR}'" < "$PROWLARR_SCRIPT"
"${SSH[@]}" "$REMOTE" "cat > '${REMOTE_AUDIT}'" < "$AUDIT_SCRIPT"
"${SSH[@]}" "$REMOTE" "cat > '${REMOTE_LEARNING}'" < "$LEARNING_SCRIPT"
"${SSH[@]}" "$REMOTE" "cat > '${REMOTE_LEARNING_SERVICE}'" < "$LEARNING_SERVICE"
"${SSH[@]}" "$REMOTE" "cat > '${REMOTE_LEARNING_TIMER}'" < "$LEARNING_TIMER"

"${SSH[@]}" "$REMOTE" "
  set -e
  sudo -n install -m 0755 \
    '${REMOTE_PROWLARR}' \
    /volume1/docker/media-stack/configure-prowlarr.py
  sudo -n install -m 0755 \
    '${REMOTE_AUDIT}' \
    /volume1/docker/media-stack/audit-private-trackers.py
  sudo -n install -m 0755 \
    '${REMOTE_LEARNING}' \
    /volume1/docker/media-stack/import-docspedia-learning.py
  sudo -n install -m 0644 \
    '${REMOTE_LEARNING_SERVICE}' \
    /etc/systemd/system/media-stack-docspedia-learning.service
  sudo -n install -m 0644 \
    '${REMOTE_LEARNING_TIMER}' \
    /etc/systemd/system/media-stack-docspedia-learning.timer
  rm -f \
    '${REMOTE_PROWLARR}' \
    '${REMOTE_AUDIT}' \
    '${REMOTE_LEARNING}' \
    '${REMOTE_LEARNING_SERVICE}' \
    '${REMOTE_LEARNING_TIMER}'
  sudo -n systemctl daemon-reload
  sudo -n systemctl enable --now media-stack-docspedia-learning.timer
  cd /volume1/docker/media-stack
  sudo -n python3 ./configure-prowlarr.py --only-indexer docspedia
  sudo -n python3 ./import-docspedia-learning.py --dry-run
  sudo -n python3 ./audit-private-trackers.py
"
