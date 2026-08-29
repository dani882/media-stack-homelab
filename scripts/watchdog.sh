#!/usr/bin/env bash

set -euo pipefail

DEFAULT_STACK_DIR="/volume1/docker/media-stack"

STACK_DIR="${STACK_DIR:-$DEFAULT_STACK_DIR}"
MAINTENANCE_LOCK="${MAINTENANCE_LOCK:-/run/lock/media-stack-maintenance.lock}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: Required command not found: $1" >&2
    exit 1
  fi
}

for command in docker flock grep; do
  require_command "$command"
done

if [[ ! -d "$STACK_DIR" ]]; then
  echo "ERROR: Stack directory not found: $STACK_DIR" >&2
  exit 1
fi

if [[ ! -f "${STACK_DIR}/compose.yaml" ]]; then
  echo "ERROR: Compose file not found: ${STACK_DIR}/compose.yaml" >&2
  exit 1
fi

exec 9>"$MAINTENANCE_LOCK"

if ! flock -n 9; then
  echo "SKIPPED: media-stack maintenance is in progress."
  exit 0
fi

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker is not available." >&2
  exit 1
fi

cd "$STACK_DIR"

mapfile -t EXPECTED_SERVICES < <(
  docker compose config --services
)

if [[ ${#EXPECTED_SERVICES[@]} -eq 0 ]]; then
  echo "ERROR: Compose returned no expected services." >&2
  exit 1
fi

mapfile -t RUNNING_SERVICES < <(
  docker compose ps --status running --services
)

MISSING_SERVICES=()

for service in "${EXPECTED_SERVICES[@]}"; do
  if ! printf "%s\\n" "${RUNNING_SERVICES[@]}" | grep -Fxq "$service"; then
    MISSING_SERVICES+=("$service")
  fi
done

if [[ ${#MISSING_SERVICES[@]} -eq 0 ]]; then
  echo "HEALTHY: all ${#EXPECTED_SERVICES[@]} media-stack services are running."
  exit 0
fi

echo "RECOVERY: services not running:"
printf "  %s\\n" "${MISSING_SERVICES[@]}"

echo "RECOVERY: starting media stack..."

docker compose up -d --no-recreate

mapfile -t RUNNING_AFTER < <(
  docker compose ps --status running --services
)

FAILED_SERVICES=()

for service in "${EXPECTED_SERVICES[@]}"; do
  if ! printf "%s\\n" "${RUNNING_AFTER[@]}" | grep -Fxq "$service"; then
    FAILED_SERVICES+=("$service")
  fi
done

if [[ ${#FAILED_SERVICES[@]} -gt 0 ]]; then
  echo "ERROR: services still not running after recovery:" >&2
  printf "  %s\\n" "${FAILED_SERVICES[@]}" >&2
  exit 1
fi

echo "RECOVERED: all ${#EXPECTED_SERVICES[@]} media-stack services are running."
