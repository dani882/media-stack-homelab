#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK_DIR="${ROOT_DIR}/stacks/media"
ENV_FILE="${STACK_DIR}/env/.env"
COMPOSE_FILE="${STACK_DIR}/compose.yaml"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: Missing environment file:"
  echo "  ${ENV_FILE}"
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
REMOTE_STAGING="/volume1/docker/deploy-staging/${NAS_USER}"
REMOTE_TEMP="${REMOTE_STAGING}/media-stack-compose-${USER}-$$.yaml"

echo "Validating locally..."
docker compose \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  config >/dev/null

echo "Uploading Compose file through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh "$REMOTE" \
  "cat > '${REMOTE_TEMP}'" \
  < "$COMPOSE_FILE"

echo "Installing and validating Compose file on the NAS..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh -t "$REMOTE" "
  set -e
  sudo mkdir -p '${NAS_STACK_DIR}'
  sudo install -m 0644 \
    '${REMOTE_TEMP}' \
    '${NAS_STACK_DIR}/compose.yaml'
  rm -f '${REMOTE_TEMP}'
  cd '${NAS_STACK_DIR}'
  sudo docker compose config >/dev/null
"

echo "Pulling images and applying the stack..."

# NAS_STACK_DIR is intentionally expanded locally.
# shellcheck disable=SC2029
ssh -t "$REMOTE" "
  set -e
  cd '${NAS_STACK_DIR}'
  sudo docker compose pull
  sudo docker compose up -d
  sudo docker compose ps
"

echo "Deployment completed successfully."
