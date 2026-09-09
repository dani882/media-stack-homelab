#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK_DIR="${ROOT_DIR}/stacks/media"
ENV_FILE="${STACK_DIR}/env/.env"
DEFINITION="${STACK_DIR}/prowlarr/definitions/dreadvault-api.yml"
PROWLARR_SCRIPT="${ROOT_DIR}/scripts/configure-prowlarr.py"
AUDIT_SCRIPT="${ROOT_DIR}/scripts/audit-private-trackers.py"

for required_file in \
  "$ENV_FILE" \
  "$DEFINITION" \
  "$PROWLARR_SCRIPT" \
  "$AUDIT_SCRIPT"
do
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
REMOTE_DEFINITION="${REMOTE_STAGING}/dreadvault-api-${USER}-$$.yml"
REMOTE_PROWLARR="${REMOTE_STAGING}/configure-prowlarr-${USER}-$$.py"
REMOTE_AUDIT="${REMOTE_STAGING}/audit-private-trackers-${USER}-$$.py"
SSH=(ssh -o ControlMaster=auto -o ControlPersist=60)

"${SSH[@]}" "$REMOTE" "mkdir -p '${REMOTE_STAGING}'"
"${SSH[@]}" "$REMOTE" "cat > '${REMOTE_DEFINITION}'" < "$DEFINITION"
"${SSH[@]}" "$REMOTE" "cat > '${REMOTE_PROWLARR}'" < "$PROWLARR_SCRIPT"
"${SSH[@]}" "$REMOTE" "cat > '${REMOTE_AUDIT}'" < "$AUDIT_SCRIPT"

"${SSH[@]}" "$REMOTE" "
  set -e
  sudo -n install -d -m 0755 \
    /volume1/docker/media-stack/config/prowlarr/Definitions/Custom
  sudo -n install -m 0644 \
    '${REMOTE_DEFINITION}' \
    /volume1/docker/media-stack/config/prowlarr/Definitions/Custom/dreadvault-api.yml
  sudo -n install -m 0755 \
    '${REMOTE_PROWLARR}' \
    /volume1/docker/media-stack/configure-prowlarr.py
  sudo -n install -m 0755 \
    '${REMOTE_AUDIT}' \
    /volume1/docker/media-stack/audit-private-trackers.py
  rm -f '${REMOTE_DEFINITION}' '${REMOTE_PROWLARR}' '${REMOTE_AUDIT}'
  sudo -n docker restart prowlarr >/dev/null
  cd /volume1/docker/media-stack
  sudo -n python3 ./configure-prowlarr.py --only-indexer dreadvault-api
  sudo -n python3 ./audit-private-trackers.py --enforce-limits
"
