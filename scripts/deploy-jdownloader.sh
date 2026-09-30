#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEDIA_ENV_FILE="${ROOT_DIR}/stacks/media/env/.env"
STACK_DIR="${ROOT_DIR}/stacks/jdownloader"
COMPOSE_FILE="${STACK_DIR}/compose.yaml"
ENV_EXAMPLE="${STACK_DIR}/.env.example"

if [[ ! -f "$MEDIA_ENV_FILE" ]]; then
  echo "ERROR: Missing NAS connection settings:"
  echo "  ${MEDIA_ENV_FILE}"
  exit 1
fi

for required_file in "$COMPOSE_FILE" "$ENV_EXAMPLE"; do
  if [[ ! -f "$required_file" ]]; then
    echo "ERROR: Missing required file:"
    echo "  ${required_file}"
    exit 1
  fi
done

set -a
# shellcheck disable=SC1090
source "$MEDIA_ENV_FILE"
set +a

: "${NAS_HOST:?NAS_HOST is required}"
: "${NAS_USER:?NAS_USER is required}"

PUID="${PUID:-1000}"
PGID="${PGID:-10}"
TZ="${TZ:-America/Toronto}"
REMOTE_STACK_DIR="${JDOWNLOADER_STACK_DIR:-/volume1/docker/jdownloader}"
REMOTE_DOWNLOADS_DIR="${JDOWNLOADER_DOWNLOADS_DIR:-/volume1/Family/Downloads/jdownloader}"
REMOTE="${NAS_USER}@${NAS_HOST}"
SSH=(
  ssh
  -o ConnectTimeout=15
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=4
)

case "$PUID:$PGID" in
  *[!0-9:]* | :* | *:) echo "ERROR: PUID and PGID must be numeric."; exit 1 ;;
esac

case "$REMOTE_STACK_DIR" in
  /volume1/docker/*) ;;
  *) echo "ERROR: JDOWNLOADER_STACK_DIR must be below /volume1/docker."; exit 1 ;;
esac

case "$REMOTE_DOWNLOADS_DIR" in
  /volume1/Family/Downloads/*) ;;
  *) echo "ERROR: JDOWNLOADER_DOWNLOADS_DIR must be below /volume1/Family/Downloads."; exit 1 ;;
esac

echo "Validating the isolated JDownloader Compose stack..."
docker compose --env-file "$ENV_EXAMPLE" -f "$COMPOSE_FILE" config >/dev/null

REMOTE_TEMP="/tmp/jdownloader-compose-${USER}-$$.yaml"
cleanup() {
  "${SSH[@]}" "$REMOTE" "rm -f '$REMOTE_TEMP'" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Uploading the JDownloader Compose definition..."
# REMOTE_TEMP is composed from fixed text plus the local user and process ID.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" "cat > '$REMOTE_TEMP'" < "$COMPOSE_FILE"

echo "Creating persistent folders and applying the stack..."
# Values interpolated below are validated paths, numeric IDs, or existing
# deployment settings. The NAS-local .env is created only on first deploy.
# shellcheck disable=SC2029
"${SSH[@]}" -t "$REMOTE" "
  set -e
  if ! command -v timeout >/dev/null 2>&1; then
    echo 'ERROR: the NAS timeout utility is required for bounded deploys.' >&2
    exit 1
  fi

  sudo install -d -m 0755 '$REMOTE_STACK_DIR'
  sudo install -d -o '$PUID' -g '$PGID' -m 0775 \
    '$REMOTE_STACK_DIR/config' \
    '$REMOTE_DOWNLOADS_DIR'
  sudo install -m 0644 '$REMOTE_TEMP' '$REMOTE_STACK_DIR/compose.yaml'

  if [[ ! -f '$REMOTE_STACK_DIR/.env' ]]; then
    umask 077
    sudo sh -c \"cat > '$REMOTE_STACK_DIR/.env'\" <<'JDOWNLOADER_ENV'
JDOWNLOADER_TAG=v26.09.1
PUID=$PUID
PGID=$PGID
TZ=$TZ
JDOWNLOADER_BIND_ADDRESS=0.0.0.0
JDOWNLOADER_WEB_PORT=5800
JDOWNLOADER_CONFIG_DIR=$REMOTE_STACK_DIR/config
JDOWNLOADER_DOWNLOADS_DIR=$REMOTE_DOWNLOADS_DIR
DISPLAY_WIDTH=1920
DISPLAY_HEIGHT=1080
DARK_MODE=1
JDOWNLOADER_MAX_MEM=2G
JDOWNLOADER_ENV
    sudo chmod 0600 '$REMOTE_STACK_DIR/.env'
  fi

  if sudo grep -qx 'JDOWNLOADER_TAG=26.09.1' '$REMOTE_STACK_DIR/.env'; then
    sudo sed -i 's/^JDOWNLOADER_TAG=26\.09\.1$/JDOWNLOADER_TAG=v26.09.1/' \
      '$REMOTE_STACK_DIR/.env'
  fi

  cd '$REMOTE_STACK_DIR'
  sudo docker compose config >/dev/null

  if sudo ss -H -ltn 'sport = :5800' | grep -q . && \
     ! sudo docker compose ps --format '{{.Service}}' | grep -qx jdownloader; then
    echo 'ERROR: port 5800 is already used by another service.' >&2
    exit 1
  fi

  sudo timeout -k 30s 20m docker compose pull
  sudo timeout -k 30s 10m docker compose up -d
  sudo timeout -k 10s 2m docker compose ps
"

echo
echo "JDownloader is deployed independently from the media stack."
echo "Open: http://${NAS_HOST}:5800"
