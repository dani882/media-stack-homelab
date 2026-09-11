#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK_DIR="${ROOT_DIR}/stacks/media"
ENV_FILE="${STACK_DIR}/env/.env"
PROWLARR_SCRIPT="${ROOT_DIR}/scripts/configure-prowlarr.py"
AUDIT_SCRIPT="${ROOT_DIR}/scripts/audit-private-trackers.py"
CLEANUP_SCRIPT="${ROOT_DIR}/scripts/cleanup-public-imported.py"
BTARG_SERIES_SCRIPT="${ROOT_DIR}/scripts/dispatch-btarg-series.py"
BTARG_SERIES_MODULE="${ROOT_DIR}/scripts/media/btarg_series_pack.py"
BTARG_SERIES_SERVICE="${STACK_DIR}/systemd/media-stack-btarg-series.service"
BTARG_SERIES_TIMER="${STACK_DIR}/systemd/media-stack-btarg-series.timer"

for required_file in \
  "$ENV_FILE" \
  "$PROWLARR_SCRIPT" \
  "$AUDIT_SCRIPT" \
  "$CLEANUP_SCRIPT" \
  "$BTARG_SERIES_SCRIPT" \
  "$BTARG_SERIES_MODULE" \
  "$BTARG_SERIES_SERVICE" \
  "$BTARG_SERIES_TIMER"
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
REMOTE_PROWLARR="${REMOTE_STAGING}/configure-prowlarr-${USER}-$$.py"
REMOTE_AUDIT="${REMOTE_STAGING}/audit-private-trackers-${USER}-$$.py"
REMOTE_CLEANUP="${REMOTE_STAGING}/cleanup-public-imported-${USER}-$$.py"
REMOTE_BTARG_SERIES="${REMOTE_STAGING}/dispatch-btarg-series-${USER}-$$.py"
REMOTE_BTARG_SERIES_MODULE="${REMOTE_STAGING}/btarg-series-pack-${USER}-$$.py"
REMOTE_BTARG_SERIES_SERVICE="${REMOTE_STAGING}/media-stack-btarg-series-${USER}-$$.service"
REMOTE_BTARG_SERIES_TIMER="${REMOTE_STAGING}/media-stack-btarg-series-${USER}-$$.timer"
SSH=(ssh -o ControlMaster=auto -o ControlPersist=60)

"${SSH[@]}" "$REMOTE" "mkdir -p '${REMOTE_STAGING}'"
"${SSH[@]}" "$REMOTE" "cat > '${REMOTE_PROWLARR}'" < "$PROWLARR_SCRIPT"
"${SSH[@]}" "$REMOTE" "cat > '${REMOTE_AUDIT}'" < "$AUDIT_SCRIPT"
"${SSH[@]}" "$REMOTE" "cat > '${REMOTE_CLEANUP}'" < "$CLEANUP_SCRIPT"
"${SSH[@]}" "$REMOTE" "cat > '${REMOTE_BTARG_SERIES}'" < "$BTARG_SERIES_SCRIPT"
"${SSH[@]}" "$REMOTE" "cat > '${REMOTE_BTARG_SERIES_MODULE}'" < "$BTARG_SERIES_MODULE"
"${SSH[@]}" "$REMOTE" "cat > '${REMOTE_BTARG_SERIES_SERVICE}'" < "$BTARG_SERIES_SERVICE"
"${SSH[@]}" "$REMOTE" "cat > '${REMOTE_BTARG_SERIES_TIMER}'" < "$BTARG_SERIES_TIMER"

"${SSH[@]}" "$REMOTE" "
  set -e
  sudo -n install -m 0755 \
    '${REMOTE_PROWLARR}' \
    /volume1/docker/media-stack/configure-prowlarr.py
  sudo -n install -m 0755 \
    '${REMOTE_AUDIT}' \
    /volume1/docker/media-stack/audit-private-trackers.py
  sudo -n install -m 0755 \
    '${REMOTE_CLEANUP}' \
    /volume1/docker/media-stack/cleanup-public-imported.py
  sudo -n install -m 0755 \
    '${REMOTE_BTARG_SERIES}' \
    /volume1/docker/media-stack/dispatch-btarg-series.py
  sudo -n install -d -m 0755 /volume1/docker/media-stack/scripts
  sudo -n install -m 0644 \
    '${REMOTE_BTARG_SERIES_MODULE}' \
    /volume1/docker/media-stack/scripts/btarg_series_pack.py
  sudo -n install -m 0644 \
    '${REMOTE_BTARG_SERIES_SERVICE}' \
    /etc/systemd/system/media-stack-btarg-series.service
  sudo -n install -m 0644 \
    '${REMOTE_BTARG_SERIES_TIMER}' \
    /etc/systemd/system/media-stack-btarg-series.timer
  rm -f '${REMOTE_PROWLARR}' '${REMOTE_AUDIT}' '${REMOTE_CLEANUP}' \
    '${REMOTE_BTARG_SERIES}' '${REMOTE_BTARG_SERIES_MODULE}' \
    '${REMOTE_BTARG_SERIES_SERVICE}' '${REMOTE_BTARG_SERIES_TIMER}'
  cd /volume1/docker/media-stack
  sudo -n python3 ./configure-prowlarr.py --only-indexer btarg
  sudo -n python3 ./audit-private-trackers.py
  sudo -n systemctl daemon-reload
  sudo -n systemctl enable --now media-stack-btarg-series.timer
"
