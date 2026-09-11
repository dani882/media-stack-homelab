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
REMOTE_STAGING="/volume1/docker/deploy-staging/${NAS_USER}/download-reliability-$$"
SSH=(ssh -o ControlMaster=auto -o ControlPersist=60)

FILES=(
  "scripts/cleanup-stalled-public.py"
  "scripts/dispatch-private-seerr.py"
  "scripts/grab-prowlarr-release.py"
  "scripts/configure-servarr.py"
  "scripts/media/common/arr.py"
  "scripts/media/common/btarg.py"
  "scripts/media/common/language.py"
  "scripts/media/common/qbittorrent.py"
  "scripts/media/common/release_safety.py"
  "scripts/servarr_config/__init__.py"
  "scripts/servarr_config/common.py"
  "scripts/servarr_config/custom_formats.py"
  "scripts/servarr_config/settings.py"
  "stacks/media/private-release-policy.json"
  "stacks/media/servarr/custom-formats/sonarr-latino.json"
  "stacks/media/servarr/custom-formats/radarr-latino.json"
  "stacks/media/systemd/media-stack-private-dispatch.service"
  "stacks/media/systemd/media-stack-private-dispatch.timer"
  "stacks/media/systemd/media-stack-stalled-public-cleanup.service"
  "stacks/media/systemd/media-stack-stalled-public-cleanup.timer"
)

"${SSH[@]}" "$REMOTE" "mkdir -p '${REMOTE_STAGING}'"
for relative_path in "${FILES[@]}"; do
  remote_file="${REMOTE_STAGING}/${relative_path}"
  "${SSH[@]}" "$REMOTE" "mkdir -p '$(dirname "$remote_file")'"
  "${SSH[@]}" "$REMOTE" "cat > '${remote_file}'" < "${ROOT_DIR}/${relative_path}"
done

"${SSH[@]}" "$REMOTE" "
  set -e
  sudo -n install -d -m 0755 \
    /volume1/docker/media-stack/scripts/common \
    /volume1/docker/media-stack/servarr_config \
    /volume1/docker/media-stack/servarr/custom-formats
  sudo -n install -m 0755 \
    '${REMOTE_STAGING}/scripts/cleanup-stalled-public.py' \
    /volume1/docker/media-stack/cleanup-stalled-public.py
  sudo -n install -m 0755 \
    '${REMOTE_STAGING}/scripts/dispatch-private-seerr.py' \
    /volume1/docker/media-stack/dispatch-private-seerr.py
  sudo -n install -m 0755 \
    '${REMOTE_STAGING}/scripts/grab-prowlarr-release.py' \
    /volume1/docker/media-stack/grab-prowlarr-release.py
  sudo -n install -m 0755 \
    '${REMOTE_STAGING}/scripts/configure-servarr.py' \
    /volume1/docker/media-stack/configure-servarr.py
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/scripts/media/common/arr.py' \
    '${REMOTE_STAGING}/scripts/media/common/btarg.py' \
    '${REMOTE_STAGING}/scripts/media/common/language.py' \
    '${REMOTE_STAGING}/scripts/media/common/qbittorrent.py' \
    '${REMOTE_STAGING}/scripts/media/common/release_safety.py' \
    /volume1/docker/media-stack/scripts/common/
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/scripts/servarr_config/__init__.py' \
    '${REMOTE_STAGING}/scripts/servarr_config/common.py' \
    '${REMOTE_STAGING}/scripts/servarr_config/custom_formats.py' \
    '${REMOTE_STAGING}/scripts/servarr_config/settings.py' \
    /volume1/docker/media-stack/servarr_config/
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/stacks/media/private-release-policy.json' \
    /volume1/docker/media-stack/private-release-policy.json
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/stacks/media/servarr/custom-formats/sonarr-latino.json' \
    /volume1/docker/media-stack/servarr/custom-formats/sonarr-latino.json
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/stacks/media/servarr/custom-formats/radarr-latino.json' \
    /volume1/docker/media-stack/servarr/custom-formats/radarr-latino.json
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/stacks/media/systemd/media-stack-private-dispatch.service' \
    /etc/systemd/system/media-stack-private-dispatch.service
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/stacks/media/systemd/media-stack-private-dispatch.timer' \
    /etc/systemd/system/media-stack-private-dispatch.timer
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/stacks/media/systemd/media-stack-stalled-public-cleanup.service' \
    /etc/systemd/system/media-stack-stalled-public-cleanup.service
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/stacks/media/systemd/media-stack-stalled-public-cleanup.timer' \
    /etc/systemd/system/media-stack-stalled-public-cleanup.timer
  sudo -n systemctl daemon-reload
  sudo -n systemctl enable --now \
    media-stack-private-dispatch.timer \
    media-stack-stalled-public-cleanup.timer
  cd /volume1/docker/media-stack
  sudo -n python3 ./configure-servarr.py
  rm -rf '${REMOTE_STAGING}'
"
