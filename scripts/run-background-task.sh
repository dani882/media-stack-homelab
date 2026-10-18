#!/usr/bin/env bash

set -euo pipefail

STACK_DIR="${STACK_DIR:-/volume1/docker/media-stack}"
STATE_FILE="${STACK_DIR}/state/system-pressure.json"
SERIALIZE=0

if [[ "${1:-}" == "--serialize" ]]; then
  SERIALIZE=1
  shift
fi

if [[ "${1:-}" == "--" ]]; then
  shift
fi

if [[ "$#" -eq 0 ]]; then
  echo "ERROR: background command is required." >&2
  exit 2
fi

set +e
python3 "${STACK_DIR}/check-system-pressure.py" --guard --state-file "${STATE_FILE}"
pressure_status=$?
set -e

if [[ "${pressure_status}" -eq 1 ]]; then
  echo "SKIPPED: NAS pressure is elevated; background work was postponed."
  exit 0
fi

if [[ "${pressure_status}" -ne 0 ]]; then
  echo "ERROR: unable to verify NAS pressure safely." >&2
  exit "${pressure_status}"
fi

if [[ "${SERIALIZE}" -eq 1 ]]; then
  exec 9>/run/lock/media-stack-heavy-audit.lock
  if ! flock -n 9; then
    echo "SKIPPED: another heavy media audit is already running."
    exit 0
  fi
fi

exec "$@"
