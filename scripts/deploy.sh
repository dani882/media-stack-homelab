#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK_DIR="${ROOT_DIR}/stacks/media"
ENV_FILE="${STACK_DIR}/env/.env"
COMPOSE_FILE="${STACK_DIR}/compose.yaml"
PROWLARR_SCRIPT="${ROOT_DIR}/scripts/configure-prowlarr.py"
RECYCLARR_CONFIG="${STACK_DIR}/recyclarr/recyclarr.yml"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: Missing environment file:"
  echo "  ${ENV_FILE}"
  exit 1
fi

if [[ ! -f "$RECYCLARR_CONFIG" ]]; then
  echo "ERROR: Missing Recyclarr configuration:"
  echo "  ${RECYCLARR_CONFIG}"
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
REMOTE_PROWLARR_TEMP="${REMOTE_STAGING}/configure-prowlarr-${USER}-$$.py"
REMOTE_RECYCLARR_TEMP="${REMOTE_STAGING}/recyclarr-${USER}-$$.yml"

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

echo "Uploading Prowlarr configuration script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh "$REMOTE" \
  "cat > '${REMOTE_PROWLARR_TEMP}'" \
  < "$PROWLARR_SCRIPT"

echo "Uploading Recyclarr configuration through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh "$REMOTE" \
  "cat > '${REMOTE_RECYCLARR_TEMP}'" \
  < "$RECYCLARR_CONFIG"

echo "Installing and validating Compose file on the NAS..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh -t "$REMOTE" "
  set -e
  sudo mkdir -p '${NAS_STACK_DIR}'
  sudo install -m 0644 \
    '${REMOTE_TEMP}' \
    '${NAS_STACK_DIR}/compose.yaml'
  sudo install -m 0755 \
    '${REMOTE_PROWLARR_TEMP}' \
    '${NAS_STACK_DIR}/configure-prowlarr.py'

  sudo mkdir -p '${NAS_STACK_DIR}/config/recyclarr'
  sudo install -o 1000 -g 10 -m 0640 \
    '${REMOTE_RECYCLARR_TEMP}' \
    '${NAS_STACK_DIR}/config/recyclarr/recyclarr.yml'

  rm -f \
    '${REMOTE_TEMP}' \
    '${REMOTE_PROWLARR_TEMP}' \
    '${REMOTE_RECYCLARR_TEMP}'

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

  echo
  echo "Configuring Prowlarr indexers..."
  sudo python3 '${NAS_STACK_DIR}/configure-prowlarr.py'

  echo
  echo "Synchronizing Recyclarr with Sonarr..."
  sudo docker exec recyclarr \
    recyclarr sync sonarr --instance series

  echo
  echo "Synchronizing Recyclarr with Radarr..."
  sudo docker exec recyclarr \
    recyclarr sync radarr --instance movies
"

echo "Deployment completed successfully."
