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
REMOTE_STAGING="/volume1/docker/deploy-staging/${NAS_USER}/language-priority-$$"
SSH=(
  ssh
  -o ControlMaster=auto
  -o ControlPersist=60
  -o ConnectTimeout=15
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=4
)

FILES=(
  "scripts/configure-servarr.py"
  "scripts/servarr_config/__init__.py"
  "scripts/servarr_config/common.py"
  "scripts/servarr_config/custom_formats.py"
  "scripts/servarr_config/settings.py"
  "scripts/media/common/language.py"
  "scripts/media/common/arr.py"
  "scripts/media/common/btarg.py"
  "scripts/media/upgrade-sonarr-latino.py"
  "scripts/media/upgrade-radarr-latino.py"
  "stacks/media/servarr/custom-formats/sonarr-latino.json"
  "stacks/media/servarr/custom-formats/radarr-latino.json"
  "stacks/media/servarr/sonarr/naming.json"
  "stacks/media/servarr/radarr/naming.json"
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
    /volume1/docker/media-stack/servarr_config \
    /volume1/docker/media-stack/scripts/common \
    /volume1/docker/media-stack/servarr/custom-formats \
    /volume1/docker/media-stack/servarr/sonarr \
    /volume1/docker/media-stack/servarr/radarr
  sudo -n install -m 0755 \
    '${REMOTE_STAGING}/scripts/configure-servarr.py' \
    /volume1/docker/media-stack/configure-servarr.py
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/scripts/servarr_config/__init__.py' \
    '${REMOTE_STAGING}/scripts/servarr_config/common.py' \
    '${REMOTE_STAGING}/scripts/servarr_config/custom_formats.py' \
    '${REMOTE_STAGING}/scripts/servarr_config/settings.py' \
    /volume1/docker/media-stack/servarr_config/
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/scripts/media/common/language.py' \
    '${REMOTE_STAGING}/scripts/media/common/arr.py' \
    '${REMOTE_STAGING}/scripts/media/common/btarg.py' \
    /volume1/docker/media-stack/scripts/common/
  sudo -n install -m 0755 \
    '${REMOTE_STAGING}/scripts/media/upgrade-sonarr-latino.py' \
    '${REMOTE_STAGING}/scripts/media/upgrade-radarr-latino.py' \
    /volume1/docker/media-stack/scripts/
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/stacks/media/servarr/custom-formats/sonarr-latino.json' \
    /volume1/docker/media-stack/servarr/custom-formats/sonarr-latino.json
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/stacks/media/servarr/custom-formats/radarr-latino.json' \
    /volume1/docker/media-stack/servarr/custom-formats/radarr-latino.json
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/stacks/media/servarr/sonarr/naming.json' \
    /volume1/docker/media-stack/servarr/sonarr/naming.json
  sudo -n install -m 0644 \
    '${REMOTE_STAGING}/stacks/media/servarr/radarr/naming.json' \
    /volume1/docker/media-stack/servarr/radarr/naming.json
  rm -rf '${REMOTE_STAGING}'
  cd /volume1/docker/media-stack
  sudo -n python3 ./configure-servarr.py
"
