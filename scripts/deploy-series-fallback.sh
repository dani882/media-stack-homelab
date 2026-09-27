#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK_DIR="${ROOT_DIR}/stacks/media"
ENV_FILE="${STACK_DIR}/env/.env"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${NAS_HOST:?NAS_HOST is required}"
: "${NAS_USER:?NAS_USER is required}"

REMOTE="${NAS_USER}@${NAS_HOST}"
REMOTE_STAGING="/volume1/docker/deploy-staging/${NAS_USER}/series-fallback-$$"
SSH=(
  ssh
  -o ControlMaster=auto
  -o ControlPersist=60
  -o ConnectTimeout=15
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=4
)

FILES=(
  "scripts/dispatch-series-fallback.py"
  "scripts/grab-prowlarr-release.py"
  "scripts/notify-torrent-completions.py"
  "scripts/media/common/btarg.py"
  "scripts/media/common/language.py"
  "scripts/media/common/qbittorrent.py"
  "scripts/media/common/release_safety.py"
  "stacks/media/private-release-policy.json"
  "stacks/media/systemd/media-stack-series-fallback.service"
  "stacks/media/systemd/media-stack-series-fallback.timer"
)

"${SSH[@]}" "$REMOTE" "mkdir -p '${REMOTE_STAGING}'"
for relative_path in "${FILES[@]}"; do
  remote_file="${REMOTE_STAGING}/${relative_path}"
  "${SSH[@]}" "$REMOTE" "mkdir -p '$(dirname "$remote_file")'"
  "${SSH[@]}" "$REMOTE" "cat > '${remote_file}'" < "${ROOT_DIR}/${relative_path}"
done

"${SSH[@]}" "$REMOTE" "
  set -e
  sudo -n install -d -m 0755 /volume1/docker/media-stack/scripts/common
  sudo -n install -m 0755 \
    '${REMOTE_STAGING}/scripts/dispatch-series-fallback.py' \
    /volume1/docker/media-stack/dispatch-series-fallback.py
  sudo -n install -m 0755 \
    '${REMOTE_STAGING}/scripts/grab-prowlarr-release.py' \
    /volume1/docker/media-stack/grab-prowlarr-release.py
  sudo -n install -m 0755 \
    '${REMOTE_STAGING}/scripts/notify-torrent-completions.py' \
    /volume1/docker/media-stack/notify-torrent-completions.py
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/scripts/media/common/btarg.py' \
    '${REMOTE_STAGING}/scripts/media/common/language.py' \
    '${REMOTE_STAGING}/scripts/media/common/qbittorrent.py' \
    '${REMOTE_STAGING}/scripts/media/common/release_safety.py' \
    /volume1/docker/media-stack/scripts/common/
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/stacks/media/private-release-policy.json' \
    /volume1/docker/media-stack/private-release-policy.json
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/stacks/media/systemd/media-stack-series-fallback.service' \
    /etc/systemd/system/media-stack-series-fallback.service
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/stacks/media/systemd/media-stack-series-fallback.timer' \
    /etc/systemd/system/media-stack-series-fallback.timer
  sudo -n systemctl daemon-reload
  sudo -n systemctl enable media-stack-series-fallback.timer
  rm -rf '${REMOTE_STAGING}'
"

echo "Series fallback installed; this deploy does not change the timer's running state."
