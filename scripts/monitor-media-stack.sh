#!/usr/bin/env bash

set -euo pipefail

STACK_DIR="${STACK_DIR:-/volume1/docker/media-stack}"
LOG_DIR="${STACK_DIR}/logs"

mkdir -p "${LOG_DIR}"

timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
log_file="${LOG_DIR}/media-observability.log"

run_check() {
  local label="$1"
  shift

  if output="$("$@" 2>&1)"; then
    printf '%s OK %s\n' "${timestamp}" "${label}" >> "${log_file}"
    if [[ -n "${output}" ]]; then
      printf '%s\n' "${output}" >> "${log_file}"
    fi
    return 0
  fi

  printf '%s FAIL %s\n' "${timestamp}" "${label}" >> "${log_file}"
  printf '%s\n' "${output}" >> "${log_file}"
  return 1
}

failed=0

run_check "check-media-live" \
  python3 "${STACK_DIR}/check-media-live.py" || failed=1
run_check "audit-bazarr" \
  python3 "${STACK_DIR}/audit-bazarr.py" || failed=1
run_check "audit-seerr" \
  python3 "${STACK_DIR}/audit-seerr.py" || failed=1
run_check "audit-private-trackers" \
  python3 "${STACK_DIR}/audit-private-trackers.py" || failed=1

if [[ "${failed}" -ne 0 ]]; then
  exit 1
fi
