#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK_DIR="${ROOT_DIR}/stacks/media"
ENV_FILE="${STACK_DIR}/env/.env"
COMPOSE_FILE="${STACK_DIR}/compose.yaml"
PROWLARR_SCRIPT="${ROOT_DIR}/scripts/configure-prowlarr.py"
SERVARR_SCRIPT="${ROOT_DIR}/scripts/configure-servarr.py"
SERVARR_MODULE_DIR="${ROOT_DIR}/scripts/servarr_config"
SERVARR_CUSTOM_FORMATS_MODULE="${SERVARR_MODULE_DIR}/custom_formats.py"
SERVARR_SETTINGS_MODULE="${SERVARR_MODULE_DIR}/settings.py"
SERVARR_INIT_MODULE="${SERVARR_MODULE_DIR}/__init__.py"
RECYCLARR_CONFIG="${STACK_DIR}/recyclarr/recyclarr.yml"
SONARR_LATINO_CONFIG="${STACK_DIR}/servarr/custom-formats/sonarr-latino.json"
RADARR_LATINO_CONFIG="${STACK_DIR}/servarr/custom-formats/radarr-latino.json"
SONARR_SETTINGS_DIR="${STACK_DIR}/servarr/sonarr"
RADARR_SETTINGS_DIR="${STACK_DIR}/servarr/radarr"

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

for required_file in \
  "$SERVARR_SCRIPT" \
  "$SERVARR_CUSTOM_FORMATS_MODULE" \
  "$SERVARR_SETTINGS_MODULE" \
  "$SERVARR_INIT_MODULE" \
  "$SONARR_LATINO_CONFIG" \
  "$RADARR_LATINO_CONFIG" \
  "$SONARR_SETTINGS_DIR/download-clients.json" \
  "$SONARR_SETTINGS_DIR/root-folders.json" \
  "$SONARR_SETTINGS_DIR/naming.json" \
  "$SONARR_SETTINGS_DIR/media-management.json" \
  "$RADARR_SETTINGS_DIR/download-clients.json" \
  "$RADARR_SETTINGS_DIR/root-folders.json" \
  "$RADARR_SETTINGS_DIR/naming.json" \
  "$RADARR_SETTINGS_DIR/media-management.json"
do
  if [[ ! -f "$required_file" ]]; then
    echo "ERROR: Missing required file:"
    echo "  ${required_file}"
    exit 1
  fi
done

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
REMOTE_SERVARR_TEMP="${REMOTE_STAGING}/configure-servarr-${USER}-$$.py"
REMOTE_SERVARR_CUSTOM_FORMATS_TEMP="${REMOTE_STAGING}/servarr-custom-formats-${USER}-$$.py"
REMOTE_SERVARR_SETTINGS_TEMP="${REMOTE_STAGING}/servarr-settings-${USER}-$$.py"
REMOTE_SERVARR_INIT_TEMP="${REMOTE_STAGING}/servarr-init-${USER}-$$.py"
REMOTE_RECYCLARR_TEMP="${REMOTE_STAGING}/recyclarr-${USER}-$$.yml"
REMOTE_SONARR_LATINO_TEMP="${REMOTE_STAGING}/sonarr-latino-${USER}-$$.json"
REMOTE_RADARR_LATINO_TEMP="${REMOTE_STAGING}/radarr-latino-${USER}-$$.json"
REMOTE_SONARR_DOWNLOAD_CLIENTS_TEMP="${REMOTE_STAGING}/sonarr-download-clients-${USER}-$$.json"
REMOTE_SONARR_ROOT_FOLDERS_TEMP="${REMOTE_STAGING}/sonarr-root-folders-${USER}-$$.json"
REMOTE_SONARR_NAMING_TEMP="${REMOTE_STAGING}/sonarr-naming-${USER}-$$.json"
REMOTE_SONARR_MEDIA_MANAGEMENT_TEMP="${REMOTE_STAGING}/sonarr-media-management-${USER}-$$.json"
REMOTE_RADARR_DOWNLOAD_CLIENTS_TEMP="${REMOTE_STAGING}/radarr-download-clients-${USER}-$$.json"
REMOTE_RADARR_ROOT_FOLDERS_TEMP="${REMOTE_STAGING}/radarr-root-folders-${USER}-$$.json"
REMOTE_RADARR_NAMING_TEMP="${REMOTE_STAGING}/radarr-naming-${USER}-$$.json"
REMOTE_RADARR_MEDIA_MANAGEMENT_TEMP="${REMOTE_STAGING}/radarr-media-management-${USER}-$$.json"

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

echo "Uploading Servarr configuration script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh "$REMOTE" \
  "cat > '${REMOTE_SERVARR_TEMP}'" \
  < "$SERVARR_SCRIPT"

echo "Uploading Servarr configuration modules..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh "$REMOTE" \
  "cat > '${REMOTE_SERVARR_CUSTOM_FORMATS_TEMP}'" \
  < "$SERVARR_CUSTOM_FORMATS_MODULE"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh "$REMOTE" \
  "cat > '${REMOTE_SERVARR_SETTINGS_TEMP}'" \
  < "$SERVARR_SETTINGS_MODULE"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh "$REMOTE" \
  "cat > '${REMOTE_SERVARR_INIT_TEMP}'" \
  < "$SERVARR_INIT_MODULE"

echo "Uploading Sonarr Latino custom formats..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh "$REMOTE" \
  "cat > '${REMOTE_SONARR_LATINO_TEMP}'" \
  < "$SONARR_LATINO_CONFIG"

echo "Uploading Radarr Latino custom formats..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh "$REMOTE" \
  "cat > '${REMOTE_RADARR_LATINO_TEMP}'" \
  < "$RADARR_LATINO_CONFIG"

echo "Uploading Sonarr application settings..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh "$REMOTE" \
  "cat > '${REMOTE_SONARR_DOWNLOAD_CLIENTS_TEMP}'" \
  < "$SONARR_SETTINGS_DIR/download-clients.json"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh "$REMOTE" \
  "cat > '${REMOTE_SONARR_ROOT_FOLDERS_TEMP}'" \
  < "$SONARR_SETTINGS_DIR/root-folders.json"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh "$REMOTE" \
  "cat > '${REMOTE_SONARR_NAMING_TEMP}'" \
  < "$SONARR_SETTINGS_DIR/naming.json"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh "$REMOTE" \
  "cat > '${REMOTE_SONARR_MEDIA_MANAGEMENT_TEMP}'" \
  < "$SONARR_SETTINGS_DIR/media-management.json"

echo "Uploading Radarr application settings..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh "$REMOTE" \
  "cat > '${REMOTE_RADARR_DOWNLOAD_CLIENTS_TEMP}'" \
  < "$RADARR_SETTINGS_DIR/download-clients.json"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh "$REMOTE" \
  "cat > '${REMOTE_RADARR_ROOT_FOLDERS_TEMP}'" \
  < "$RADARR_SETTINGS_DIR/root-folders.json"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh "$REMOTE" \
  "cat > '${REMOTE_RADARR_NAMING_TEMP}'" \
  < "$RADARR_SETTINGS_DIR/naming.json"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
ssh "$REMOTE" \
  "cat > '${REMOTE_RADARR_MEDIA_MANAGEMENT_TEMP}'" \
  < "$RADARR_SETTINGS_DIR/media-management.json"

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

  sudo install -m 0755 \
    '${REMOTE_SERVARR_TEMP}' \
    '${NAS_STACK_DIR}/configure-servarr.py'

  sudo mkdir -p \
    '${NAS_STACK_DIR}/servarr_config'

  sudo install -m 0644 \
    '${REMOTE_SERVARR_INIT_TEMP}' \
    '${NAS_STACK_DIR}/servarr_config/__init__.py'

  sudo install -m 0755 \
    '${REMOTE_SERVARR_CUSTOM_FORMATS_TEMP}' \
    '${NAS_STACK_DIR}/servarr_config/custom_formats.py'

  sudo install -m 0755 \
    '${REMOTE_SERVARR_SETTINGS_TEMP}' \
    '${NAS_STACK_DIR}/servarr_config/settings.py'

  sudo mkdir -p \
    '${NAS_STACK_DIR}/servarr/custom-formats' \
    '${NAS_STACK_DIR}/servarr/sonarr' \
    '${NAS_STACK_DIR}/servarr/radarr'

  sudo install -m 0644 \
    '${REMOTE_SONARR_LATINO_TEMP}' \
    '${NAS_STACK_DIR}/servarr/custom-formats/sonarr-latino.json'

  sudo install -m 0644 \
    '${REMOTE_RADARR_LATINO_TEMP}' \
    '${NAS_STACK_DIR}/servarr/custom-formats/radarr-latino.json'

  sudo install -m 0644 \
    '${REMOTE_SONARR_DOWNLOAD_CLIENTS_TEMP}' \
    '${NAS_STACK_DIR}/servarr/sonarr/download-clients.json'

  sudo install -m 0644 \
    '${REMOTE_SONARR_ROOT_FOLDERS_TEMP}' \
    '${NAS_STACK_DIR}/servarr/sonarr/root-folders.json'

  sudo install -m 0644 \
    '${REMOTE_SONARR_NAMING_TEMP}' \
    '${NAS_STACK_DIR}/servarr/sonarr/naming.json'

  sudo install -m 0644 \
    '${REMOTE_SONARR_MEDIA_MANAGEMENT_TEMP}' \
    '${NAS_STACK_DIR}/servarr/sonarr/media-management.json'

  sudo install -m 0644 \
    '${REMOTE_RADARR_DOWNLOAD_CLIENTS_TEMP}' \
    '${NAS_STACK_DIR}/servarr/radarr/download-clients.json'

  sudo install -m 0644 \
    '${REMOTE_RADARR_ROOT_FOLDERS_TEMP}' \
    '${NAS_STACK_DIR}/servarr/radarr/root-folders.json'

  sudo install -m 0644 \
    '${REMOTE_RADARR_NAMING_TEMP}' \
    '${NAS_STACK_DIR}/servarr/radarr/naming.json'

  sudo install -m 0644 \
    '${REMOTE_RADARR_MEDIA_MANAGEMENT_TEMP}' \
    '${NAS_STACK_DIR}/servarr/radarr/media-management.json'

  sudo mkdir -p '${NAS_STACK_DIR}/config/recyclarr'
  sudo install -o 1000 -g 10 -m 0640 \
    '${REMOTE_RECYCLARR_TEMP}' \
    '${NAS_STACK_DIR}/config/recyclarr/recyclarr.yml'

  rm -f \
    '${REMOTE_TEMP}' \
    '${REMOTE_PROWLARR_TEMP}' \
    '${REMOTE_SERVARR_TEMP}' \
    '${REMOTE_SERVARR_CUSTOM_FORMATS_TEMP}' \
    '${REMOTE_SERVARR_SETTINGS_TEMP}' \
    '${REMOTE_SERVARR_INIT_TEMP}' \
    '${REMOTE_RECYCLARR_TEMP}' \
    '${REMOTE_SONARR_LATINO_TEMP}' \
    '${REMOTE_RADARR_LATINO_TEMP}' \
    '${REMOTE_SONARR_DOWNLOAD_CLIENTS_TEMP}' \
    '${REMOTE_SONARR_ROOT_FOLDERS_TEMP}' \
    '${REMOTE_SONARR_NAMING_TEMP}' \
    '${REMOTE_SONARR_MEDIA_MANAGEMENT_TEMP}' \
    '${REMOTE_RADARR_DOWNLOAD_CLIENTS_TEMP}' \
    '${REMOTE_RADARR_ROOT_FOLDERS_TEMP}' \
    '${REMOTE_RADARR_NAMING_TEMP}' \
    '${REMOTE_RADARR_MEDIA_MANAGEMENT_TEMP}'

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
  echo "Configuring Sonarr and Radarr..."
  sudo python3 '${NAS_STACK_DIR}/configure-servarr.py'

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
