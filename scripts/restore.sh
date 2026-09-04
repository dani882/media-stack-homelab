#!/usr/bin/env bash

set -euo pipefail

DEFAULT_STACK_DIR="/volume1/docker/media-stack"

STACK_DIR="${STACK_DIR:-$DEFAULT_STACK_DIR}"
BACKUP_DIR="${BACKUP_DIR:-${STACK_DIR}/backups}"
MAINTENANCE_LOCK="${MAINTENANCE_LOCK:-/run/lock/media-stack-maintenance.lock}"

DRY_RUN=false
TEST_PRE_RESTORE_BACKUP=false
ARCHIVE=""

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
  dominican-iptv-monitor
)

usage() {
  cat <<'USAGE'
Usage:
  restore.sh [--dry-run] ARCHIVE

Arguments:
  ARCHIVE  Path to a media-stack-*.tar.zst backup archive.

Environment:
  STACK_DIR   Media stack root.
  BACKUP_DIR  Backup directory.

Examples:
  ./restore.sh --dry-run \
    /volume1/docker/media-stack/backups/media-stack-20260814T015732Z.tar.zst

  ./restore.sh \
    /volume1/docker/media-stack/backups/media-stack-20260814T015732Z.tar.zst
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --test-pre-restore-backup)
      TEST_PRE_RESTORE_BACKUP=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "ERROR: Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      if [[ -n "$ARCHIVE" ]]; then
        echo "ERROR: Only one archive may be specified." >&2
        usage >&2
        exit 1
      fi

      ARCHIVE="$1"
      shift
      ;;
  esac
done

if [[ -z "$ARCHIVE" ]]; then
  echo "ERROR: Backup archive is required." >&2
  usage >&2
  exit 1
fi

CHECKSUM="${ARCHIVE}.sha256"
RESTORE_ID="$(date -u '+%Y%m%dT%H%M%SZ')"

WORK_DIR="${BACKUP_DIR}/.restore-${RESTORE_ID}.tmp"
ROLLBACK_DIR="${BACKUP_DIR}/.restore-${RESTORE_ID}.rollback"

CONFIG_DIR="${STACK_DIR}/config"
SECRETS_DIR="${STACK_DIR}/secrets"

STOPPED=false
RESTORE_STARTED=false
RESTORE_COMMITTED=false

RUNNING_SERVICES=()
SWAPPED_TARGETS=()
SWAPPED_ROLLBACKS=()

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: Required command not found: $1" >&2
    exit 1
  fi
}

for command in tar zstd sha256sum docker find awk stat flock; do
  require_command "$command"
done

if [[ ! -d "$STACK_DIR" ]]; then
  echo "ERROR: Stack directory not found: $STACK_DIR" >&2
  exit 1
fi

if [[ ! -f "$ARCHIVE" ]]; then
  echo "ERROR: Backup archive not found: $ARCHIVE" >&2
  exit 1
fi

if [[ ! -f "$CHECKSUM" ]]; then
  echo "ERROR: Backup checksum not found: $CHECKSUM" >&2
  exit 1
fi

# Invoked indirectly by the exit handler.
# shellcheck disable=SC2329
cleanup() {
  if [[ -d "$WORK_DIR" ]]; then
    rm -rf "$WORK_DIR"
  fi

  if "$RESTORE_COMMITTED" && [[ -d "$ROLLBACK_DIR" ]]; then
    rm -rf "$ROLLBACK_DIR"
  fi
}

detect_running_services() {
  local running
  local service

  running="$(
    cd "$STACK_DIR"
    docker compose ps \
      --status running \
      --services
  )"

  RUNNING_SERVICES=()

  for service in "${SERVICES[@]}"; do
    if grep -Fxq "$service" <<<"$running"; then
      RUNNING_SERVICES+=("$service")
    fi
  done
}

stop_managed_services() {
  if [[ ${#RUNNING_SERVICES[@]} -eq 0 ]]; then
    echo "No managed services are currently running."
    return
  fi

  (
    cd "$STACK_DIR"
    docker compose stop "${RUNNING_SERVICES[@]}"
  )

  STOPPED=true
}

# Invoked by the exit handler and successful restore path.
# shellcheck disable=SC2329
start_services() {
  if ! "$STOPPED"; then
    return
  fi

  if [[ ${#RUNNING_SERVICES[@]} -gt 0 ]]; then
    echo
    echo "Restoring previously running services..."

    (
      cd "$STACK_DIR"
      docker compose start "${RUNNING_SERVICES[@]}"
    )
  fi

  STOPPED=false
}

swap_tree() {
  local label="$1"
  local source="$2"
  local target="$3"
  local rollback="$4"

  if [[ ! -d "$source" ]]; then
    echo "SKIPPED missing backup tree: $label"
    return
  fi

  echo "RESTORING: $label"

  mkdir -p "$(dirname "$target")"
  mkdir -p "$(dirname "$rollback")"

  SWAPPED_TARGETS+=("$target")
  SWAPPED_ROLLBACKS+=("$rollback")

  if [[ -e "$target" ]]; then
    mv "$target" "$rollback"
  fi

  mv "$source" "$target"
}

rollback_restore() {
  local index
  local target
  local rollback

  if ! "$RESTORE_STARTED" || "$RESTORE_COMMITTED"; then
    return
  fi

  echo
  echo "Restore failed. Rolling back live configuration..."

  (
    cd "$STACK_DIR"
    docker compose stop "${SERVICES[@]}"
  ) || true

  for ((index=${#SWAPPED_TARGETS[@]} - 1; index >= 0; index--)); do
    target="${SWAPPED_TARGETS[$index]}"
    rollback="${SWAPPED_ROLLBACKS[$index]}"

    rm -rf "$target"

    if [[ -e "$rollback" ]]; then
      mv "$rollback" "$target"
    fi
  done

  if [[ ${#RUNNING_SERVICES[@]} -gt 0 ]]; then
    echo
    echo "Restarting services with pre-restore configuration..."

    (
      cd "$STACK_DIR"
      docker compose start "${RUNNING_SERVICES[@]}"
    ) || true
  fi

  STOPPED=false

  echo "Rollback completed."
}

# Invoked indirectly through trap.
# shellcheck disable=SC2329
on_exit() {
  status=$?

  if [[ $status -ne 0 ]]; then
    rollback_restore || true
  elif "$STOPPED"; then
    start_services || true
  fi

  cleanup

  exit "$status"
}

trap on_exit EXIT INT TERM

echo "Media stack restore"
echo "Stack directory: $STACK_DIR"
echo "Backup directory: $BACKUP_DIR"
echo "Archive: $ARCHIVE"
echo "Checksum: $CHECKSUM"
echo "Dry run: $DRY_RUN"
echo "Test pre-restore backup: $TEST_PRE_RESTORE_BACKUP"

echo
echo "Verifying archive checksum..."

(
  cd "$(dirname "$ARCHIVE")"
  sha256sum -c "$(basename "$CHECKSUM")"
)

echo
echo "Inspecting archive paths..."

ARCHIVE_CONTENTS="$(mktemp)"

zstd -dc "$ARCHIVE" \
| tar -tf - \
> "$ARCHIVE_CONTENTS"

if grep -Eq '(^/|(^|/)\.\.(/|$))' "$ARCHIVE_CONTENTS"; then
  rm -f "$ARCHIVE_CONTENTS"
  echo "ERROR: Archive contains unsafe paths." >&2
  exit 1
fi

rm -f "$ARCHIVE_CONTENTS"

mkdir -p "$WORK_DIR"

echo
echo "Extracting archive to staging..."

zstd -dc "$ARCHIVE" \
| tar \
    --numeric-owner \
    -C "$WORK_DIR" \
    -xf -

MANIFEST="${WORK_DIR}/manifest.txt"

if [[ ! -f "$MANIFEST" ]]; then
  echo "ERROR: Backup manifest was not found." >&2
  exit 1
fi

echo
echo "Backup manifest:"
sed -n '1,12p' "$MANIFEST"

echo
echo "Validating expected backup content..."

REQUIRED_PATHS=(
  "config/prowlarr/prowlarr.db"
  "config/sonarr/sonarr.db"
  "config/radarr/radarr.db"
  "config/bazarr/db/bazarr.db"
  "config/jellyseerr/settings.json"
  "config/qbittorrent/qBittorrent/qBittorrent.conf"
  "config/jellyfin/data/jellyfin.db"
  "config/jellyfin/data/library.db"
  "config/recyclarr/recyclarr.yml"
  "secrets/qbittorrent.json"
)

for path in "${REQUIRED_PATHS[@]}"; do
  if [[ ! -e "${WORK_DIR}/${path}" ]]; then
    echo "ERROR: Required backup content missing: $path" >&2
    exit 1
  fi

  echo "OK: $path"
done

detect_running_services

echo
echo "Currently running managed services:"

if [[ ${#RUNNING_SERVICES[@]} -gt 0 ]]; then
  printf '  %s\n' "${RUNNING_SERVICES[@]}"
else
  echo "  none"
fi

echo
echo "Restore plan:"
cat <<'PLAN'
- verify backup checksum
- reject unsafe archive paths
- validate backup manifest and critical files
- preserve numeric UID/GID ownership from the archive
- create a pre-restore safety backup
- stop currently running managed services
- move current application data into rollback storage
- restore backed-up application data
- restore Jellyfin configuration and plugins
- restore Recyclarr state
- restore NAS-local secrets
- restart only services that were running before restore
- automatically rollback if the restore fails
PLAN

if "$DRY_RUN"; then
  echo
  echo "Dry run completed successfully."
  echo "No files were modified."
  echo "No services were stopped."
  exit 0
fi

if [[ ! -x "${STACK_DIR}/backup.sh" ]]; then
  echo "ERROR: Installed backup script not found:" >&2
  echo "  ${STACK_DIR}/backup.sh" >&2
  exit 1
fi

exec 9>"$MAINTENANCE_LOCK"

echo
echo "Waiting for media-stack maintenance lock..."
flock 9

echo
echo "Creating pre-restore safety backup..."

BACKUP_SCRIPT="${STACK_DIR}/backup.sh"

STACK_DIR="$STACK_DIR" \
BACKUP_DIR="$BACKUP_DIR" \
MAINTENANCE_LOCK="$MAINTENANCE_LOCK" \
MEDIA_STACK_LOCK_HELD=true \
"$BACKUP_SCRIPT"

if "$TEST_PRE_RESTORE_BACKUP"; then
  echo
  echo "Pre-restore backup test completed successfully."
  echo "Restore phase was not started."
  exit 0
fi

echo
echo "Stopping currently running managed services..."

stop_managed_services

mkdir -p "$ROLLBACK_DIR"

RESTORE_STARTED=true

echo
echo "Applying restored configuration..."

swap_tree \
  "Prowlarr" \
  "${WORK_DIR}/config/prowlarr" \
  "${CONFIG_DIR}/prowlarr" \
  "${ROLLBACK_DIR}/config/prowlarr"

swap_tree \
  "Sonarr" \
  "${WORK_DIR}/config/sonarr" \
  "${CONFIG_DIR}/sonarr" \
  "${ROLLBACK_DIR}/config/sonarr"

swap_tree \
  "Radarr" \
  "${WORK_DIR}/config/radarr" \
  "${CONFIG_DIR}/radarr" \
  "${ROLLBACK_DIR}/config/radarr"

swap_tree \
  "Bazarr" \
  "${WORK_DIR}/config/bazarr" \
  "${CONFIG_DIR}/bazarr" \
  "${ROLLBACK_DIR}/config/bazarr"

swap_tree \
  "Seerr" \
  "${WORK_DIR}/config/jellyseerr" \
  "${CONFIG_DIR}/jellyseerr" \
  "${ROLLBACK_DIR}/config/jellyseerr"

swap_tree \
  "qBittorrent" \
  "${WORK_DIR}/config/qbittorrent" \
  "${CONFIG_DIR}/qbittorrent" \
  "${ROLLBACK_DIR}/config/qbittorrent"

swap_tree \
  "Dispatcharr" \
  "${WORK_DIR}/config/dispatcharr" \
  "${CONFIG_DIR}/dispatcharr" \
  "${ROLLBACK_DIR}/config/dispatcharr"

swap_tree \
  "Dominican IPTV state" \
  "${WORK_DIR}/config/dominican-iptv" \
  "${CONFIG_DIR}/dominican-iptv" \
  "${ROLLBACK_DIR}/config/dominican-iptv"

swap_tree \
  "Jellyfin configuration" \
  "${WORK_DIR}/config/jellyfin" \
  "${CONFIG_DIR}/jellyfin/config" \
  "${ROLLBACK_DIR}/config/jellyfin/config"

swap_tree \
  "Jellyfin plugins" \
  "${WORK_DIR}/config/jellyfin-plugins" \
  "${CONFIG_DIR}/jellyfin/plugins" \
  "${ROLLBACK_DIR}/config/jellyfin/plugins"

swap_tree \
  "Recyclarr" \
  "${WORK_DIR}/config/recyclarr" \
  "${CONFIG_DIR}/recyclarr" \
  "${ROLLBACK_DIR}/config/recyclarr"

swap_tree \
  "NAS-local secrets" \
  "${WORK_DIR}/secrets" \
  "${SECRETS_DIR}" \
  "${ROLLBACK_DIR}/secrets"


if [[ -d "$SECRETS_DIR" ]]; then
  echo "Hardening restored secrets..."

  chown root:root "$SECRETS_DIR"
  chmod 0700 "$SECRETS_DIR"

  find "$SECRETS_DIR" \
    -type f \
    -exec chown root:root {} + \
    -exec chmod 0600 {} +
fi

echo
echo "Validating restored live content..."

REQUIRED_LIVE_PATHS=(
  "config/prowlarr/prowlarr.db"
  "config/sonarr/sonarr.db"
  "config/radarr/radarr.db"
  "config/bazarr/db/bazarr.db"
  "config/jellyseerr/settings.json"
  "config/qbittorrent/qBittorrent/qBittorrent.conf"
  "config/jellyfin/config/data/jellyfin.db"
  "config/jellyfin/config/data/library.db"
  "config/recyclarr/recyclarr.yml"
  "secrets/qbittorrent.json"
)

for path in "${REQUIRED_LIVE_PATHS[@]}"; do
  if [[ ! -e "${STACK_DIR}/${path}" ]]; then
    echo "ERROR: Restored live content missing: $path" >&2
    exit 1
  fi

  echo "OK: $path"
done

echo
echo "Validating restored secret permissions..."

while IFS= read -r secret; do
  mode="$(stat -c '%a' "$secret")"
  owner="$(stat -c '%u:%g' "$secret")"

  if [[ "$mode" != "600" || "$owner" != "0:0" ]]; then
    echo "ERROR: Unsafe restored secret permissions:" >&2
    echo "  ${mode} ${owner} ${secret}" >&2
    exit 1
  fi

  echo "SECURE: ${secret}"
done < <(
  find "$SECRETS_DIR" \
    -type f \
    -print
)

echo
echo "Verifying restored file integrity..."

INTEGRITY_PAIRS=(
  "config/prowlarr/prowlarr.db|config/prowlarr/prowlarr.db"
  "config/sonarr/sonarr.db|config/sonarr/sonarr.db"
  "config/radarr/radarr.db|config/radarr/radarr.db"
  "config/bazarr/db/bazarr.db|config/bazarr/db/bazarr.db"
  "config/jellyseerr/settings.json|config/jellyseerr/settings.json"
  "config/qbittorrent/qBittorrent/qBittorrent.conf|config/qbittorrent/qBittorrent/qBittorrent.conf"
  "config/jellyfin/data/jellyfin.db|config/jellyfin/config/data/jellyfin.db"
  "config/jellyfin/data/library.db|config/jellyfin/config/data/library.db"
  "config/recyclarr/recyclarr.yml|config/recyclarr/recyclarr.yml"
  "secrets/qbittorrent.json|secrets/qbittorrent.json"
)

for pair in "${INTEGRITY_PAIRS[@]}"; do
  source_path="${pair%%|*}"
  live_path="${pair#*|}"

  source_hash="$(
    sha256sum "${WORK_DIR}/${source_path}" |
    awk '{print $1}'
  )"

  live_hash="$(
    sha256sum "${STACK_DIR}/${live_path}" |
    awk '{print $1}'
  )"

  if [[ "$source_hash" != "$live_hash" ]]; then
    echo "ERROR: Restored file integrity mismatch:" >&2
    echo "  source: ${source_path}" >&2
    echo "  live:   ${live_path}" >&2
    exit 1
  fi

  echo "MATCH: ${live_path}"
done

echo
echo "Starting previously running services..."

start_services

echo
echo "Verifying restored services..."

sleep 3

running_after="$(
  cd "$STACK_DIR"
  docker compose ps \
    --status running \
    --services
)"

for service in "${RUNNING_SERVICES[@]}"; do
  if ! grep -Fxq "$service" <<<"$running_after"; then
    echo "ERROR: Service did not return to running state: $service" >&2
    exit 1
  fi

  echo "RUNNING: $service"
done

RESTORE_COMMITTED=true

echo
echo "Restore completed successfully."
echo "Archive:"
echo "  $ARCHIVE"
