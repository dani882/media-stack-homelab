#!/usr/bin/env bash

set -euo pipefail

DEFAULT_STACK_DIR="/volume1/docker/media-stack"
DEFAULT_RETENTION_DAYS=14

STACK_DIR="${STACK_DIR:-$DEFAULT_STACK_DIR}"
BACKUP_DIR="${BACKUP_DIR:-${STACK_DIR}/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-$DEFAULT_RETENTION_DAYS}"
MAINTENANCE_LOCK="${MAINTENANCE_LOCK:-/run/lock/media-stack-maintenance.lock}"
MEDIA_STACK_LOCK_HELD="${MEDIA_STACK_LOCK_HELD:-false}"

DRY_RUN=false

usage() {
  cat <<'USAGE'
Usage:
  backup.sh [--dry-run]

Environment:
  STACK_DIR       Media stack root.
  BACKUP_DIR      Backup destination.
  RETENTION_DAYS  Remove backups older than this many days.

Examples:
  ./backup.sh
  ./backup.sh --dry-run
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

CONFIG_DIR="${STACK_DIR}/config"
SECRETS_DIR="${STACK_DIR}/secrets"

TIMESTAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
BACKUP_NAME="media-stack-${TIMESTAMP}"
WORK_DIR="${BACKUP_DIR}/.${BACKUP_NAME}.tmp"
ARCHIVE="${BACKUP_DIR}/${BACKUP_NAME}.tar.zst"
CHECKSUM="${ARCHIVE}.sha256"

SERVICES=(
  prowlarr
  sonarr
  radarr
  bazarr
  seerr
  qbittorrent
  jellyfin
  dispatcharr
  dominican-iptv
)

cleanup() {
  if [[ -d "$WORK_DIR" ]]; then
    rm -rf "$WORK_DIR"
  fi
}

trap cleanup EXIT

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: Required command not found: $1" >&2
    exit 1
  fi
}

for command in tar zstd sha256sum docker find flock; do
  require_command "$command"
done

if [[ ! -d "$STACK_DIR" ]]; then
  echo "ERROR: Stack directory not found: $STACK_DIR" >&2
  exit 1
fi

if [[ ! -d "$CONFIG_DIR" ]]; then
  echo "ERROR: Config directory not found: $CONFIG_DIR" >&2
  exit 1
fi

echo "Media stack backup"
echo "Stack directory: $STACK_DIR"
echo "Backup directory: $BACKUP_DIR"
echo "Retention: ${RETENTION_DAYS} days"
echo "Dry run: $DRY_RUN"

echo
echo "Included application data:"
cat <<'LIST'
- Prowlarr
- Sonarr
- Radarr
- Bazarr
- Seerr
- qBittorrent
- Jellyfin configuration and metadata
- Dispatcharr channels, playlists, EPG mappings, and settings
- Recyclarr state/configuration
- NAS-local media-stack secrets
LIST

echo
echo "Excluded regenerable data:"
cat <<'LIST'
- logs
- caches
- internal application backups
- Sonarr/Radarr MediaCover
- Sentry data
- Recyclarr downloaded resources
- PID files
- Jellyfin cache
- Jellyfin generated keyframes
LIST

STOPPED=false
RUNNING_SERVICES=()

detect_running_services() {
  local running
  local service

  running="$(
    cd "$STACK_DIR"
    docker compose ps       --status running       --services
  )"

  RUNNING_SERVICES=()

  for service in "${SERVICES[@]}"; do
    if grep -Fxq "$service" <<<"$running"; then
      RUNNING_SERVICES+=("$service")
    fi
  done
}

start_services() {
  if "$STOPPED"; then
    if [[ ${#RUNNING_SERVICES[@]} -gt 0 ]]; then
      echo
      echo "Restoring previously running services..."
      (
        cd "$STACK_DIR"
        docker compose start "${RUNNING_SERVICES[@]}"
      )
    fi

    STOPPED=false
  fi
}

on_exit() {
  status=$?

  if "$STOPPED"; then
    start_services || true
  fi

  cleanup
  exit "$status"
}

trap on_exit EXIT INT TERM

detect_running_services

if "$DRY_RUN"; then
  echo
  echo "Would create:"
  echo "  $ARCHIVE"
  echo "  $CHECKSUM"

  echo
  echo "Currently running managed services:"

  if [[ ${#RUNNING_SERVICES[@]} -gt 0 ]]; then
    printf '  %s\n' "${RUNNING_SERVICES[@]}"
  else
    echo "  none"
  fi

  echo
  echo "Only these currently running services would be"
  echo "temporarily stopped and restarted."

  exit 0
fi

mkdir -p "$BACKUP_DIR"
mkdir -p "$WORK_DIR"

if ! "$MEDIA_STACK_LOCK_HELD"; then
  exec 9>"$MAINTENANCE_LOCK"
  echo
  echo "Waiting for media-stack maintenance lock..."
  flock 9
fi

echo
echo "Stopping currently running database-writing services..."

if [[ ${#RUNNING_SERVICES[@]} -gt 0 ]]; then
  (
    cd "$STACK_DIR"
    docker compose stop "${RUNNING_SERVICES[@]}"
  )
  STOPPED=true
else
  echo "No managed services are currently running."
fi

echo
echo "Creating backup staging tree..."

mkdir -p \
  "$WORK_DIR/config" \
  "$WORK_DIR/secrets"

copy_config_tree() {
  local service="$1"

  if [[ ! -d "${CONFIG_DIR}/${service}" ]]; then
    echo "SKIPPED missing config: $service"
    return
  fi

  mkdir -p "${WORK_DIR}/config/${service}"

  tar \
    -C "${CONFIG_DIR}/${service}" \
    --exclude='logs' \
    --exclude='*/logs' \
    --exclude='*/logs/*' \
    --exclude='log' \
    --exclude='*/log' \
    --exclude='*/log/*' \
    --exclude='cache' \
    --exclude='*/cache' \
    --exclude='*/cache/*' \
    --exclude='.cache' \
    --exclude='*/.cache' \
    --exclude='*/.cache/*' \
    --exclude='Backups' \
    --exclude='*/Backups' \
    --exclude='*/Backups/*' \
    --exclude='backup' \
    --exclude='*/backup' \
    --exclude='*/backup/*' \
    --exclude='MediaCover' \
    --exclude='*/MediaCover' \
    --exclude='*/MediaCover/*' \
    --exclude='Sentry' \
    --exclude='*/Sentry' \
    --exclude='*/Sentry/*' \
    --exclude='*.pid' \
    --exclude='*/*.pid' \
    -cf - . \
  | tar \
      -C "${WORK_DIR}/config/${service}" \
      -xf -

  echo "COPIED: $service"
}

for service in \
  prowlarr \
  sonarr \
  radarr \
  bazarr \
  jellyseerr \
  qbittorrent \
  dispatcharr \
  dominican-iptv
do
  copy_config_tree "$service"
done

echo "Copying Jellyfin..."

mkdir -p "$WORK_DIR/config/jellyfin"

if [[ -d "${CONFIG_DIR}/jellyfin/config" ]]; then
  tar \
    -C "${CONFIG_DIR}/jellyfin/config" \
    --exclude='./log' \
    --exclude='./log/*' \
    --exclude='./logs' \
    --exclude='./logs/*' \
    --exclude='./cache' \
    --exclude='./cache/*' \
    --exclude='./data/keyframes' \
    --exclude='./data/keyframes/*' \
    -cf - . \
  | tar \
      -C "$WORK_DIR/config/jellyfin" \
      -xf -
fi

if [[ -d "${CONFIG_DIR}/jellyfin/plugins" ]]; then
  mkdir -p "$WORK_DIR/config/jellyfin-plugins"

  tar \
    -C "${CONFIG_DIR}/jellyfin/plugins" \
    -cf - . \
  | tar \
      -C "$WORK_DIR/config/jellyfin-plugins" \
      -xf -
fi

echo "COPIED: jellyfin"

echo "Copying Recyclarr state..."

mkdir -p "$WORK_DIR/config/recyclarr"

if [[ -d "${CONFIG_DIR}/recyclarr" ]]; then
  tar \
    -C "${CONFIG_DIR}/recyclarr" \
    --exclude='./logs' \
    --exclude='./logs/*' \
    --exclude='./resources' \
    --exclude='./resources/*' \
    -cf - . \
  | tar \
      -C "$WORK_DIR/config/recyclarr" \
      -xf -
fi

echo "COPIED: recyclarr"

if [[ -d "$SECRETS_DIR" ]]; then
  echo "Copying NAS-local secrets..."

  tar \
    -C "$SECRETS_DIR" \
    -cf - . \
  | tar \
      -C "$WORK_DIR/secrets" \
      -xf -

  chown root:root "$WORK_DIR/secrets"
  chmod 0700 "$WORK_DIR/secrets"

  find "$WORK_DIR/secrets" \
    -type f \
    -exec chown root:root {} + \
    -exec chmod 0600 {} +
fi

echo
echo "Creating manifest..."

{
  echo "backup_name=${BACKUP_NAME}"
  echo "created_utc=${TIMESTAMP}"
  echo "hostname=$(hostname)"
  echo "stack_dir=${STACK_DIR}"
  echo "format=tar.zst"
  echo "compression=zstd"
  echo
  echo "[files]"
  (
    cd "$WORK_DIR"
    find . -type f -print | sort
  )
} > "${WORK_DIR}/manifest.txt"

echo
echo "Creating compressed archive..."

tar \
  -C "$WORK_DIR" \
  -cf - . \
| zstd \
    -T0 \
    -6 \
    -q \
    -o "$ARCHIVE"

echo "Creating checksum..."

(
  cd "$BACKUP_DIR"
  sha256sum "$(basename "$ARCHIVE")" \
    > "$(basename "$CHECKSUM")"
)

chmod 0600 "$ARCHIVE" "$CHECKSUM"

echo
echo "Verifying archive checksum..."

(
  cd "$BACKUP_DIR"
  sha256sum -c "$(basename "$CHECKSUM")"
)

echo
echo "Verifying archive contents..."

ARCHIVE_CONTENTS="${WORK_DIR}/archive-contents.txt"

zstd -dc "$ARCHIVE" \
| tar -tf - \
> "$ARCHIVE_CONTENTS"

if ! grep -Fx './manifest.txt' "$ARCHIVE_CONTENTS" >/dev/null; then
  echo "ERROR: Archive manifest was not found." >&2
  exit 1
fi

start_services

echo
echo "Applying retention policy..."

find "$BACKUP_DIR" \
  -maxdepth 1 \
  -type f \
  \( \
    -name 'media-stack-*.tar.zst' \
    -o \
    -name 'media-stack-*.tar.zst.sha256' \
  \) \
  -mtime "+${RETENTION_DAYS}" \
  -print \
  -delete

echo
echo "Backup completed successfully."
echo "Archive:"
echo "  $ARCHIVE"
echo "Checksum:"
echo "  $CHECKSUM"

du -h "$ARCHIVE"
