#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK_DIR="${ROOT_DIR}/stacks/media"
ENV_FILE="${STACK_DIR}/env/.env"
COMPOSE_FILE="${STACK_DIR}/compose.yaml"
PROWLARR_SCRIPT="${ROOT_DIR}/scripts/configure-prowlarr.py"
QBITTORRENT_SCRIPT="${ROOT_DIR}/scripts/configure-qbittorrent.py"
RADARR_MAINTENANCE_SCRIPT="${ROOT_DIR}/scripts/configure-radarr.py"
RADARR_POLICY_SCRIPT="${ROOT_DIR}/scripts/configure-radarr-policy.py"
RADARR_AUDIT_SCRIPT="${ROOT_DIR}/scripts/audit-radarr-releases.py"
SONARR_LATINO_AUDIT_SCRIPT="${ROOT_DIR}/scripts/media/audit-sonarr-latino.py"
SONARR_LATINO_UPGRADE_SCRIPT="${ROOT_DIR}/scripts/media/upgrade-sonarr-latino.py"
SONARR_DOWNLOAD_CLEANUP_SCRIPT="${ROOT_DIR}/scripts/media/cleanup-sonarr-downloads.py"
RADARR_LATINO_AUDIT_SCRIPT="${ROOT_DIR}/scripts/media/audit-radarr-latino.py"
RADARR_LATINO_UPGRADE_SCRIPT="${ROOT_DIR}/scripts/media/upgrade-radarr-latino.py"
RADARR_DOWNLOAD_CLEANUP_SCRIPT="${ROOT_DIR}/scripts/media/cleanup-radarr-downloads.py"

MEDIA_COMMON_DIR="${ROOT_DIR}/scripts/media/common"
MEDIA_COMMON_INIT="${MEDIA_COMMON_DIR}/__init__.py"
MEDIA_COMMON_ARR="${MEDIA_COMMON_DIR}/arr.py"
MEDIA_COMMON_QBITTORRENT="${MEDIA_COMMON_DIR}/qbittorrent.py"
MEDIA_COMMON_CLEANUP="${MEDIA_COMMON_DIR}/cleanup.py"
MEDIA_COMMON_LATINO="${MEDIA_COMMON_DIR}/latino.py"
MEDIA_COMMON_LANGUAGE="${MEDIA_COMMON_DIR}/language.py"

SERVARR_SCRIPT="${ROOT_DIR}/scripts/configure-servarr.py"
SEERR_SCRIPT="${ROOT_DIR}/scripts/configure-seerr.py"
PROFILARR_SCRIPT="${ROOT_DIR}/scripts/configure-profilarr.py"
PROFILARR_SYNC_SCRIPT="${ROOT_DIR}/scripts/configure-profilarr-sync.py"
CHECK_MEDIA_LIVE_SCRIPT="${ROOT_DIR}/scripts/check-media-live.py"
AUDIT_BAZARR_SCRIPT="${ROOT_DIR}/scripts/audit-bazarr.py"
AUDIT_SEERR_SCRIPT="${ROOT_DIR}/scripts/audit-seerr.py"
AUDIT_PRIVATE_TRACKERS_SCRIPT="${ROOT_DIR}/scripts/audit-private-trackers.py"
AUDIT_HARDLINKS_SCRIPT="${ROOT_DIR}/scripts/audit-hardlinks.py"
VERIFY_HARDLINKS_SCRIPT="${ROOT_DIR}/scripts/verify-hardlinks.py"
MONITOR_MEDIA_STACK_SCRIPT="${ROOT_DIR}/scripts/monitor-media-stack.sh"
BACKUP_SCRIPT="${ROOT_DIR}/scripts/backup.sh"
RESTORE_SCRIPT="${ROOT_DIR}/scripts/restore.sh"
WATCHDOG_SCRIPT="${ROOT_DIR}/scripts/watchdog.sh"
WATCHDOG_SERVICE="${STACK_DIR}/systemd/media-stack-watchdog.service"
WATCHDOG_TIMER="${STACK_DIR}/systemd/media-stack-watchdog.timer"
HEALTHCHECK_SERVICE="${STACK_DIR}/systemd/media-stack-healthcheck.service"
HEALTHCHECK_TIMER="${STACK_DIR}/systemd/media-stack-healthcheck.timer"
HARDLINK_AUDIT_SERVICE="${STACK_DIR}/systemd/media-stack-hardlink-audit.service"
HARDLINK_AUDIT_TIMER="${STACK_DIR}/systemd/media-stack-hardlink-audit.timer"
SERVARR_MODULE_DIR="${ROOT_DIR}/scripts/servarr_config"
SERVARR_COMMON_MODULE="${SERVARR_MODULE_DIR}/common.py"
SERVARR_CUSTOM_FORMATS_MODULE="${SERVARR_MODULE_DIR}/custom_formats.py"
SERVARR_SETTINGS_MODULE="${SERVARR_MODULE_DIR}/settings.py"
SERVARR_INIT_MODULE="${SERVARR_MODULE_DIR}/__init__.py"
RECYCLARR_CONFIG="${STACK_DIR}/recyclarr/recyclarr.yml"
PROFILARR_PILOT_CONFIG="${STACK_DIR}/profilarr/pilot-sync.json"
SONARR_LATINO_CONFIG="${STACK_DIR}/servarr/custom-formats/sonarr-latino.json"
RADARR_LATINO_CONFIG="${STACK_DIR}/servarr/custom-formats/radarr-latino.json"
SONARR_SETTINGS_DIR="${STACK_DIR}/servarr/sonarr"
RADARR_SETTINGS_DIR="${STACK_DIR}/servarr/radarr"
QBITTORRENT_CONFIG_DIR="${STACK_DIR}/qbittorrent"

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
  "$QBITTORRENT_SCRIPT" \
  "$RADARR_MAINTENANCE_SCRIPT" \
  "$RADARR_POLICY_SCRIPT" \
  "$RADARR_AUDIT_SCRIPT" \
  "$SONARR_LATINO_AUDIT_SCRIPT" \
  "$SONARR_LATINO_UPGRADE_SCRIPT" \
  "$SONARR_DOWNLOAD_CLEANUP_SCRIPT" \
  "$RADARR_LATINO_AUDIT_SCRIPT" \
  "$RADARR_LATINO_UPGRADE_SCRIPT" \
  "$RADARR_DOWNLOAD_CLEANUP_SCRIPT" \
  "$MEDIA_COMMON_INIT" \
  "$MEDIA_COMMON_ARR" \
  "$MEDIA_COMMON_QBITTORRENT" \
  "$MEDIA_COMMON_CLEANUP" \
  "$MEDIA_COMMON_LATINO" \
  "$MEDIA_COMMON_LANGUAGE" \
  "$SERVARR_SCRIPT" \
  "$SEERR_SCRIPT" \
  "$PROFILARR_SCRIPT" \
  "$PROFILARR_SYNC_SCRIPT" \
  "$CHECK_MEDIA_LIVE_SCRIPT" \
  "$AUDIT_BAZARR_SCRIPT" \
  "$AUDIT_SEERR_SCRIPT" \
  "$AUDIT_PRIVATE_TRACKERS_SCRIPT" \
  "$AUDIT_HARDLINKS_SCRIPT" \
  "$VERIFY_HARDLINKS_SCRIPT" \
  "$MONITOR_MEDIA_STACK_SCRIPT" \
  "$BACKUP_SCRIPT" \
  "$RESTORE_SCRIPT" \
  "$WATCHDOG_SCRIPT" \
  "$WATCHDOG_SERVICE" \
  "$WATCHDOG_TIMER" \
  "$HEALTHCHECK_SERVICE" \
  "$HEALTHCHECK_TIMER" \
  "$HARDLINK_AUDIT_SERVICE" \
  "$HARDLINK_AUDIT_TIMER" \
  "$SERVARR_COMMON_MODULE" \
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
  "$RADARR_SETTINGS_DIR/media-management.json" \
  "$QBITTORRENT_CONFIG_DIR/categories.json" \
  "$PROFILARR_PILOT_CONFIG" \
  "$QBITTORRENT_CONFIG_DIR/preferences.json"
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

# Reuse one SSH transport for the many short-lived deployment
# sessions, but keep its ControlMaster socket private to this deploy
# instead of depending on the user's persistent SSH configuration.
SSH_CONTROL_DIR="$(mktemp -d)"
SSH_CONTROL_PATH="${SSH_CONTROL_DIR}/master"

cleanup_ssh_control() {
  ssh     -o ControlPath="${SSH_CONTROL_PATH}"     -O exit     "$REMOTE"     >/dev/null 2>&1 || true

  rm -rf "${SSH_CONTROL_DIR}"
}

trap cleanup_ssh_control EXIT

SSH=(
  ssh
  -o ControlMaster=auto
  -o ControlPersist=60
  -o ControlPath="${SSH_CONTROL_PATH}"
)

# Pseudo-TTY sessions cannot reliably be opened through the
# multiplexed connection on this NAS/macOS OpenSSH combination.
# Use a direct connection only for the two interactive sudo phases.
SSH_TTY=(
  ssh
  -o ControlMaster=no
  -o ControlPath=none
  -t
)
REMOTE_STAGING="/volume1/docker/deploy-staging/${NAS_USER}"
REMOTE_TEMP="${REMOTE_STAGING}/media-stack-compose-${USER}-$$.yaml"
REMOTE_PROWLARR_TEMP="${REMOTE_STAGING}/configure-prowlarr-${USER}-$$.py"
REMOTE_QBITTORRENT_TEMP="${REMOTE_STAGING}/configure-qbittorrent-${USER}-$$.py"
REMOTE_RADARR_MAINTENANCE_TEMP="${REMOTE_STAGING}/configure-radarr-${USER}-$$.py"
REMOTE_RADARR_POLICY_TEMP="${REMOTE_STAGING}/configure-radarr-policy-${USER}-$$.py"
REMOTE_RADARR_AUDIT_TEMP="${REMOTE_STAGING}/audit-radarr-releases-${USER}-$$.py"
REMOTE_SONARR_LATINO_AUDIT_TEMP="${REMOTE_STAGING}/audit-sonarr-latino-${USER}-$$.py"
REMOTE_SONARR_LATINO_UPGRADE_TEMP="${REMOTE_STAGING}/upgrade-sonarr-latino-${USER}-$$.py"
REMOTE_SONARR_DOWNLOAD_CLEANUP_TEMP="${REMOTE_STAGING}/cleanup-sonarr-downloads-${USER}-$$.py"
REMOTE_RADARR_LATINO_AUDIT_TEMP="${REMOTE_STAGING}/audit-radarr-latino-${USER}-$$.py"
REMOTE_RADARR_LATINO_UPGRADE_TEMP="${REMOTE_STAGING}/upgrade-radarr-latino-${USER}-$$.py"
REMOTE_RADARR_DOWNLOAD_CLEANUP_TEMP="${REMOTE_STAGING}/cleanup-radarr-downloads-${USER}-$$.py"

REMOTE_MEDIA_COMMON_INIT_TEMP="${REMOTE_STAGING}/media-common-init-${USER}-$$.py"
REMOTE_MEDIA_COMMON_ARR_TEMP="${REMOTE_STAGING}/media-common-arr-${USER}-$$.py"
REMOTE_MEDIA_COMMON_QBITTORRENT_TEMP="${REMOTE_STAGING}/media-common-qbittorrent-${USER}-$$.py"
REMOTE_MEDIA_COMMON_CLEANUP_TEMP="${REMOTE_STAGING}/media-common-cleanup-${USER}-$$.py"
REMOTE_MEDIA_COMMON_LATINO_TEMP="${REMOTE_STAGING}/media-common-latino-${USER}-$$.py"
REMOTE_MEDIA_COMMON_LANGUAGE_TEMP="${REMOTE_STAGING}/media-common-language-${USER}-$$.py"

REMOTE_SERVARR_TEMP="${REMOTE_STAGING}/configure-servarr-${USER}-$$.py"
REMOTE_SEERR_TEMP="${REMOTE_STAGING}/configure-seerr-${USER}-$$.py"
REMOTE_PROFILARR_TEMP="${REMOTE_STAGING}/configure-profilarr-${USER}-$$.py"
REMOTE_PROFILARR_SYNC_TEMP="${REMOTE_STAGING}/configure-profilarr-sync-${USER}-$$.py"
REMOTE_CHECK_MEDIA_LIVE_TEMP="${REMOTE_STAGING}/check-media-live-${USER}-$$.py"
REMOTE_AUDIT_BAZARR_TEMP="${REMOTE_STAGING}/audit-bazarr-${USER}-$$.py"
REMOTE_AUDIT_SEERR_TEMP="${REMOTE_STAGING}/audit-seerr-${USER}-$$.py"
REMOTE_AUDIT_PRIVATE_TRACKERS_TEMP="${REMOTE_STAGING}/audit-private-trackers-${USER}-$$.py"
REMOTE_AUDIT_HARDLINKS_TEMP="${REMOTE_STAGING}/audit-hardlinks-${USER}-$$.py"
REMOTE_VERIFY_HARDLINKS_TEMP="${REMOTE_STAGING}/verify-hardlinks-${USER}-$$.py"
REMOTE_MONITOR_MEDIA_STACK_TEMP="${REMOTE_STAGING}/monitor-media-stack-${USER}-$$.sh"
REMOTE_BACKUP_TEMP="${REMOTE_STAGING}/backup-media-stack-${USER}-$$.sh"
REMOTE_RESTORE_TEMP="${REMOTE_STAGING}/restore-media-stack-${USER}-$$.sh"
REMOTE_WATCHDOG_TEMP="${REMOTE_STAGING}/watchdog-media-stack-${USER}-$$.sh"
REMOTE_WATCHDOG_SERVICE_TEMP="${REMOTE_STAGING}/media-stack-watchdog-${USER}-$$.service"
REMOTE_WATCHDOG_TIMER_TEMP="${REMOTE_STAGING}/media-stack-watchdog-${USER}-$$.timer"
REMOTE_HEALTHCHECK_SERVICE_TEMP="${REMOTE_STAGING}/media-stack-healthcheck-${USER}-$$.service"
REMOTE_HEALTHCHECK_TIMER_TEMP="${REMOTE_STAGING}/media-stack-healthcheck-${USER}-$$.timer"
REMOTE_HARDLINK_AUDIT_SERVICE_TEMP="${REMOTE_STAGING}/media-stack-hardlink-audit-${USER}-$$.service"
REMOTE_HARDLINK_AUDIT_TIMER_TEMP="${REMOTE_STAGING}/media-stack-hardlink-audit-${USER}-$$.timer"
REMOTE_SERVARR_COMMON_TEMP="${REMOTE_STAGING}/servarr-common-${USER}-$$.py"
REMOTE_SERVARR_CUSTOM_FORMATS_TEMP="${REMOTE_STAGING}/servarr-custom-formats-${USER}-$$.py"
REMOTE_SERVARR_SETTINGS_TEMP="${REMOTE_STAGING}/servarr-settings-${USER}-$$.py"
REMOTE_SERVARR_INIT_TEMP="${REMOTE_STAGING}/servarr-init-${USER}-$$.py"
REMOTE_RECYCLARR_TEMP="${REMOTE_STAGING}/recyclarr-${USER}-$$.yml"
REMOTE_PROFILARR_PILOT_TEMP="${REMOTE_STAGING}/profilarr-pilot-${USER}-$$.json"
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
REMOTE_QBITTORRENT_CATEGORIES_TEMP="${REMOTE_STAGING}/qbittorrent-categories-${USER}-$$.json"
REMOTE_QBITTORRENT_PREFERENCES_TEMP="${REMOTE_STAGING}/qbittorrent-preferences-${USER}-$$.json"

echo "Validating locally..."
docker compose \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  config >/dev/null

echo "Uploading Compose file through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_TEMP}'" \
  < "$COMPOSE_FILE"

echo "Uploading Prowlarr configuration script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_PROWLARR_TEMP}'" \
  < "$PROWLARR_SCRIPT"

echo "Uploading qBittorrent configuration script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_QBITTORRENT_TEMP}'" \
  < "$QBITTORRENT_SCRIPT"

echo "Uploading Radarr maintenance script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_RADARR_MAINTENANCE_TEMP}'" \
  < "$RADARR_MAINTENANCE_SCRIPT"

echo "Uploading Radarr Latino policy script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_RADARR_POLICY_TEMP}'" \
  < "$RADARR_POLICY_SCRIPT"

echo "Uploading Radarr release audit script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_RADARR_AUDIT_TEMP}'" \
  < "$RADARR_AUDIT_SCRIPT"

echo "Uploading Servarr configuration script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_SERVARR_TEMP}'" \
  < "$SERVARR_SCRIPT"

echo "Uploading Servarr configuration modules..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_SERVARR_COMMON_TEMP}'" \
  < "$SERVARR_COMMON_MODULE"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_SERVARR_CUSTOM_FORMATS_TEMP}'" \
  < "$SERVARR_CUSTOM_FORMATS_MODULE"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_SERVARR_SETTINGS_TEMP}'" \
  < "$SERVARR_SETTINGS_MODULE"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_SERVARR_INIT_TEMP}'" \
  < "$SERVARR_INIT_MODULE"

echo "Uploading Sonarr Latino custom formats..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_SONARR_LATINO_TEMP}'" \
  < "$SONARR_LATINO_CONFIG"

echo "Uploading Radarr Latino custom formats..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_RADARR_LATINO_TEMP}'" \
  < "$RADARR_LATINO_CONFIG"

echo "Uploading Sonarr application settings..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_SONARR_DOWNLOAD_CLIENTS_TEMP}'" \
  < "$SONARR_SETTINGS_DIR/download-clients.json"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_SONARR_ROOT_FOLDERS_TEMP}'" \
  < "$SONARR_SETTINGS_DIR/root-folders.json"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_SONARR_NAMING_TEMP}'" \
  < "$SONARR_SETTINGS_DIR/naming.json"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_SONARR_MEDIA_MANAGEMENT_TEMP}'" \
  < "$SONARR_SETTINGS_DIR/media-management.json"

echo "Uploading Radarr application settings..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_RADARR_DOWNLOAD_CLIENTS_TEMP}'" \
  < "$RADARR_SETTINGS_DIR/download-clients.json"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_RADARR_ROOT_FOLDERS_TEMP}'" \
  < "$RADARR_SETTINGS_DIR/root-folders.json"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_RADARR_NAMING_TEMP}'" \
  < "$RADARR_SETTINGS_DIR/naming.json"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_RADARR_MEDIA_MANAGEMENT_TEMP}'" \
  < "$RADARR_SETTINGS_DIR/media-management.json"

echo "Uploading Sonarr Latino audit script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_SONARR_LATINO_AUDIT_TEMP}'" \
  < "$SONARR_LATINO_AUDIT_SCRIPT"

echo "Uploading Sonarr Latino upgrade script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_SONARR_LATINO_UPGRADE_TEMP}'" \
  < "$SONARR_LATINO_UPGRADE_SCRIPT"

echo "Uploading Sonarr download cleanup script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_SONARR_DOWNLOAD_CLEANUP_TEMP}'" \
  < "$SONARR_DOWNLOAD_CLEANUP_SCRIPT"

echo "Uploading Radarr Latino audit script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_RADARR_LATINO_AUDIT_TEMP}'" \
  < "$RADARR_LATINO_AUDIT_SCRIPT"

echo "Uploading Radarr Latino upgrade script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_RADARR_LATINO_UPGRADE_TEMP}'" \
  < "$RADARR_LATINO_UPGRADE_SCRIPT"

echo "Uploading Radarr download cleanup script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_RADARR_DOWNLOAD_CLEANUP_TEMP}'" \
  < "$RADARR_DOWNLOAD_CLEANUP_SCRIPT"

echo "Uploading shared media modules..."

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_MEDIA_COMMON_INIT_TEMP}'" \
  < "$MEDIA_COMMON_INIT"

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_MEDIA_COMMON_ARR_TEMP}'" \
  < "$MEDIA_COMMON_ARR"

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_MEDIA_COMMON_QBITTORRENT_TEMP}'" \
  < "$MEDIA_COMMON_QBITTORRENT"

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_MEDIA_COMMON_CLEANUP_TEMP}'" \
  < "$MEDIA_COMMON_CLEANUP"

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_MEDIA_COMMON_LATINO_TEMP}'" \
  < "$MEDIA_COMMON_LATINO"

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_MEDIA_COMMON_LANGUAGE_TEMP}'" \
  < "$MEDIA_COMMON_LANGUAGE"

echo "Uploading Seerr configuration script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_SEERR_TEMP}'" \
  < "$SEERR_SCRIPT"

echo "Uploading Profilarr automation scripts through SSH..."

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_PROFILARR_TEMP}'" \
  < "$PROFILARR_SCRIPT"

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_PROFILARR_SYNC_TEMP}'" \
  < "$PROFILARR_SYNC_SCRIPT"

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_PROFILARR_PILOT_TEMP}'" \
  < "$PROFILARR_PILOT_CONFIG"

echo "Uploading media live validation scripts through SSH..."

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_CHECK_MEDIA_LIVE_TEMP}'" \
  < "$CHECK_MEDIA_LIVE_SCRIPT"

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_AUDIT_BAZARR_TEMP}'" \
  < "$AUDIT_BAZARR_SCRIPT"

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_AUDIT_SEERR_TEMP}'" \
  < "$AUDIT_SEERR_SCRIPT"

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_AUDIT_PRIVATE_TRACKERS_TEMP}'" \
  < "$AUDIT_PRIVATE_TRACKERS_SCRIPT"

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_AUDIT_HARDLINKS_TEMP}'" \
  < "$AUDIT_HARDLINKS_SCRIPT"

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_VERIFY_HARDLINKS_TEMP}'" \
  < "$VERIFY_HARDLINKS_SCRIPT"

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_MONITOR_MEDIA_STACK_TEMP}'" \
  < "$MONITOR_MEDIA_STACK_SCRIPT"

echo "Uploading media backup script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_BACKUP_TEMP}'" \
  < "$BACKUP_SCRIPT"

echo "Uploading media restore script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_RESTORE_TEMP}'" \
  < "$RESTORE_SCRIPT"

echo "Uploading media watchdog script through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_WATCHDOG_TEMP}'" \
  < "$WATCHDOG_SCRIPT"

echo "Uploading media watchdog systemd units through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_WATCHDOG_SERVICE_TEMP}'" \
  < "$WATCHDOG_SERVICE"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_WATCHDOG_TIMER_TEMP}'" \
  < "$WATCHDOG_TIMER"

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_HEALTHCHECK_SERVICE_TEMP}'" \
  < "$HEALTHCHECK_SERVICE"

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_HEALTHCHECK_TIMER_TEMP}'" \
  < "$HEALTHCHECK_TIMER"

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_HARDLINK_AUDIT_SERVICE_TEMP}'" \
  < "$HARDLINK_AUDIT_SERVICE"

"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_HARDLINK_AUDIT_TIMER_TEMP}'" \
  < "$HARDLINK_AUDIT_TIMER"

echo "Uploading qBittorrent configuration files..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_QBITTORRENT_CATEGORIES_TEMP}'" \
  < "$QBITTORRENT_CONFIG_DIR/categories.json"

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_QBITTORRENT_PREFERENCES_TEMP}'" \
  < "$QBITTORRENT_CONFIG_DIR/preferences.json"

echo "Uploading Recyclarr configuration through SSH..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" \
  "cat > '${REMOTE_RECYCLARR_TEMP}'" \
  < "$RECYCLARR_CONFIG"

echo "Installing and validating Compose file on the NAS..."

# Variables are intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH_TTY[@]}" "$REMOTE" "
  set -e
  sudo mkdir -p '${NAS_STACK_DIR}'
  sudo install -m 0644 \
    '${REMOTE_TEMP}' \
    '${NAS_STACK_DIR}/compose.yaml'
  sudo install -m 0755 \
    '${REMOTE_PROWLARR_TEMP}' \
    '${NAS_STACK_DIR}/configure-prowlarr.py'

  sudo install -m 0755 \
    '${REMOTE_QBITTORRENT_TEMP}' \
    '${NAS_STACK_DIR}/configure-qbittorrent.py'

  sudo install -m 0755 \
    '${REMOTE_RADARR_MAINTENANCE_TEMP}' \
    '${NAS_STACK_DIR}/configure-radarr.py'

  sudo install -m 0755 \
    '${REMOTE_RADARR_POLICY_TEMP}' \
    '${NAS_STACK_DIR}/configure-radarr-policy.py'

  sudo install -m 0755 \
    '${REMOTE_RADARR_AUDIT_TEMP}' \
    '${NAS_STACK_DIR}/audit-radarr-releases.py'

  sudo mkdir -p \
    '${NAS_STACK_DIR}/scripts'

  sudo install -m 0755 \
    '${REMOTE_SONARR_LATINO_AUDIT_TEMP}' \
    '${NAS_STACK_DIR}/scripts/audit-sonarr-latino.py'

  sudo install -m 0755 \
    '${REMOTE_SONARR_LATINO_UPGRADE_TEMP}' \
    '${NAS_STACK_DIR}/scripts/upgrade-sonarr-latino.py'

  sudo install -m 0755 \
    '${REMOTE_SONARR_DOWNLOAD_CLEANUP_TEMP}' \
    '${NAS_STACK_DIR}/scripts/cleanup-sonarr-downloads.py'

  sudo install -m 0755 \
    '${REMOTE_RADARR_LATINO_AUDIT_TEMP}' \
    '${NAS_STACK_DIR}/scripts/audit-radarr-latino.py'

  sudo install -m 0755 \
    '${REMOTE_RADARR_LATINO_UPGRADE_TEMP}' \
    '${NAS_STACK_DIR}/scripts/upgrade-radarr-latino.py'

  sudo install -m 0755 \
    '${REMOTE_RADARR_DOWNLOAD_CLEANUP_TEMP}' \
    '${NAS_STACK_DIR}/scripts/cleanup-radarr-downloads.py'

  sudo mkdir -p \
    '${NAS_STACK_DIR}/scripts/common'

  sudo install -m 0644 \
    '${REMOTE_MEDIA_COMMON_INIT_TEMP}' \
    '${NAS_STACK_DIR}/scripts/common/__init__.py'

  sudo install -m 0644 \
    '${REMOTE_MEDIA_COMMON_ARR_TEMP}' \
    '${NAS_STACK_DIR}/scripts/common/arr.py'

  sudo install -m 0644 \
    '${REMOTE_MEDIA_COMMON_QBITTORRENT_TEMP}' \
    '${NAS_STACK_DIR}/scripts/common/qbittorrent.py'

  sudo install -m 0644 \
    '${REMOTE_MEDIA_COMMON_CLEANUP_TEMP}' \
    '${NAS_STACK_DIR}/scripts/common/cleanup.py'

  sudo install -m 0644 \
    '${REMOTE_MEDIA_COMMON_LATINO_TEMP}' \
    '${NAS_STACK_DIR}/scripts/common/latino.py'

  sudo install -m 0644 \
    '${REMOTE_MEDIA_COMMON_LANGUAGE_TEMP}' \
    '${NAS_STACK_DIR}/scripts/common/language.py'

  sudo install -m 0755 \
    '${REMOTE_SERVARR_TEMP}' \
    '${NAS_STACK_DIR}/configure-servarr.py'

  sudo install -m 0755 \
    '${REMOTE_SEERR_TEMP}' \
    '${NAS_STACK_DIR}/configure-seerr.py'

  sudo install -m 0755 \
    '${REMOTE_PROFILARR_TEMP}' \
    '${NAS_STACK_DIR}/configure-profilarr.py'

  sudo install -m 0755 \
    '${REMOTE_PROFILARR_SYNC_TEMP}' \
    '${NAS_STACK_DIR}/configure-profilarr-sync.py'

  sudo install -m 0755 \
    '${REMOTE_CHECK_MEDIA_LIVE_TEMP}' \
    '${NAS_STACK_DIR}/check-media-live.py'

  sudo install -m 0755 \
    '${REMOTE_AUDIT_BAZARR_TEMP}' \
    '${NAS_STACK_DIR}/audit-bazarr.py'

  sudo install -m 0755 \
    '${REMOTE_AUDIT_SEERR_TEMP}' \
    '${NAS_STACK_DIR}/audit-seerr.py'

  sudo install -m 0755 \
    '${REMOTE_AUDIT_PRIVATE_TRACKERS_TEMP}' \
    '${NAS_STACK_DIR}/audit-private-trackers.py'

  sudo install -m 0755 \
    '${REMOTE_AUDIT_HARDLINKS_TEMP}' \
    '${NAS_STACK_DIR}/audit-hardlinks.py'

  sudo install -m 0755 \
    '${REMOTE_VERIFY_HARDLINKS_TEMP}' \
    '${NAS_STACK_DIR}/verify-hardlinks.py'

  sudo install -m 0755 \
    '${REMOTE_MONITOR_MEDIA_STACK_TEMP}' \
    '${NAS_STACK_DIR}/monitor-media-stack.sh'

  sudo install -m 0755 \
    '${REMOTE_BACKUP_TEMP}' \
    '${NAS_STACK_DIR}/backup.sh'

  sudo install -m 0755 \
    '${REMOTE_RESTORE_TEMP}' \
    '${NAS_STACK_DIR}/restore.sh'

  sudo install -m 0755 \
    '${REMOTE_WATCHDOG_TEMP}' \
    '${NAS_STACK_DIR}/watchdog.sh'

  sudo install -m 0644 \
    '${REMOTE_WATCHDOG_SERVICE_TEMP}' \
    /etc/systemd/system/media-stack-watchdog.service

  sudo install -m 0644 \
    '${REMOTE_WATCHDOG_TIMER_TEMP}' \
    /etc/systemd/system/media-stack-watchdog.timer

  sudo install -m 0644 \
    '${REMOTE_HEALTHCHECK_SERVICE_TEMP}' \
    /etc/systemd/system/media-stack-healthcheck.service

  sudo install -m 0644 \
    '${REMOTE_HEALTHCHECK_TIMER_TEMP}' \
    /etc/systemd/system/media-stack-healthcheck.timer

  sudo install -m 0644 \
    '${REMOTE_HARDLINK_AUDIT_SERVICE_TEMP}' \
    /etc/systemd/system/media-stack-hardlink-audit.service

  sudo install -m 0644 \
    '${REMOTE_HARDLINK_AUDIT_TIMER_TEMP}' \
    /etc/systemd/system/media-stack-hardlink-audit.timer

  sudo systemctl daemon-reload
  sudo systemctl enable --now \
    media-stack-watchdog.timer \
    media-stack-healthcheck.timer \
    media-stack-hardlink-audit.timer

  sudo mkdir -p \
    '${NAS_STACK_DIR}/servarr_config'

  sudo install -m 0644 \
    '${REMOTE_SERVARR_INIT_TEMP}' \
    '${NAS_STACK_DIR}/servarr_config/__init__.py'

  sudo install -m 0644 \
    '${REMOTE_SERVARR_COMMON_TEMP}' \
    '${NAS_STACK_DIR}/servarr_config/common.py'

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

  sudo mkdir -p '${NAS_STACK_DIR}/qbittorrent'

  sudo install -m 0644 \
    '${REMOTE_QBITTORRENT_CATEGORIES_TEMP}' \
    '${NAS_STACK_DIR}/qbittorrent/categories.json'

  sudo install -m 0644 \
    '${REMOTE_QBITTORRENT_PREFERENCES_TEMP}' \
    '${NAS_STACK_DIR}/qbittorrent/preferences.json'

  sudo mkdir -p '${NAS_STACK_DIR}/config/recyclarr'
  sudo install -o 1000 -g 10 -m 0640 \
    '${REMOTE_RECYCLARR_TEMP}' \
    '${NAS_STACK_DIR}/config/recyclarr/recyclarr.yml'

  sudo install -d -m 0755 \
    '${NAS_STACK_DIR}/profilarr'

  sudo install -m 0644 \
    '${REMOTE_PROFILARR_PILOT_TEMP}' \
    '${NAS_STACK_DIR}/profilarr/pilot-sync.json'

  rm -f \
    '${REMOTE_TEMP}' \
    '${REMOTE_PROWLARR_TEMP}' \
    '${REMOTE_QBITTORRENT_TEMP}' \
    '${REMOTE_RADARR_MAINTENANCE_TEMP}' \
    '${REMOTE_RADARR_POLICY_TEMP}' \
    '${REMOTE_RADARR_AUDIT_TEMP}' \
    '${REMOTE_SONARR_LATINO_AUDIT_TEMP}' \
    '${REMOTE_SONARR_LATINO_UPGRADE_TEMP}' \
    '${REMOTE_SONARR_DOWNLOAD_CLEANUP_TEMP}' \
    '${REMOTE_RADARR_LATINO_AUDIT_TEMP}' \
    '${REMOTE_RADARR_LATINO_UPGRADE_TEMP}' \
    '${REMOTE_RADARR_DOWNLOAD_CLEANUP_TEMP}' \
    '${REMOTE_MEDIA_COMMON_INIT_TEMP}' \
    '${REMOTE_MEDIA_COMMON_ARR_TEMP}' \
    '${REMOTE_MEDIA_COMMON_QBITTORRENT_TEMP}' \
    '${REMOTE_MEDIA_COMMON_CLEANUP_TEMP}' \
    '${REMOTE_MEDIA_COMMON_LATINO_TEMP}' \
    '${REMOTE_MEDIA_COMMON_LANGUAGE_TEMP}' \
    '${REMOTE_SERVARR_TEMP}' \
    '${REMOTE_SEERR_TEMP}' \
    '${REMOTE_PROFILARR_TEMP}' \
    '${REMOTE_PROFILARR_SYNC_TEMP}' \
    '${REMOTE_CHECK_MEDIA_LIVE_TEMP}' \
    '${REMOTE_AUDIT_BAZARR_TEMP}' \
    '${REMOTE_AUDIT_SEERR_TEMP}' \
    '${REMOTE_AUDIT_PRIVATE_TRACKERS_TEMP}' \
    '${REMOTE_AUDIT_HARDLINKS_TEMP}' \
    '${REMOTE_VERIFY_HARDLINKS_TEMP}' \
    '${REMOTE_MONITOR_MEDIA_STACK_TEMP}' \
    '${REMOTE_BACKUP_TEMP}' \
    '${REMOTE_RESTORE_TEMP}' \
    '${REMOTE_WATCHDOG_TEMP}' \
    '${REMOTE_WATCHDOG_SERVICE_TEMP}' \
    '${REMOTE_WATCHDOG_TIMER_TEMP}' \
    '${REMOTE_HEALTHCHECK_SERVICE_TEMP}' \
    '${REMOTE_HEALTHCHECK_TIMER_TEMP}' \
    '${REMOTE_HARDLINK_AUDIT_SERVICE_TEMP}' \
    '${REMOTE_HARDLINK_AUDIT_TIMER_TEMP}' \
    '${REMOTE_SERVARR_COMMON_TEMP}' \
    '${REMOTE_SERVARR_CUSTOM_FORMATS_TEMP}' \
    '${REMOTE_SERVARR_SETTINGS_TEMP}' \
    '${REMOTE_SERVARR_INIT_TEMP}' \
    '${REMOTE_RECYCLARR_TEMP}' \
    '${REMOTE_PROFILARR_PILOT_TEMP}' \
    '${REMOTE_SONARR_LATINO_TEMP}' \
    '${REMOTE_RADARR_LATINO_TEMP}' \
    '${REMOTE_SONARR_DOWNLOAD_CLIENTS_TEMP}' \
    '${REMOTE_SONARR_ROOT_FOLDERS_TEMP}' \
    '${REMOTE_SONARR_NAMING_TEMP}' \
    '${REMOTE_SONARR_MEDIA_MANAGEMENT_TEMP}' \
    '${REMOTE_RADARR_DOWNLOAD_CLIENTS_TEMP}' \
    '${REMOTE_RADARR_ROOT_FOLDERS_TEMP}' \
    '${REMOTE_RADARR_NAMING_TEMP}' \
    '${REMOTE_RADARR_MEDIA_MANAGEMENT_TEMP}' \
    '${REMOTE_QBITTORRENT_CATEGORIES_TEMP}' \
    '${REMOTE_QBITTORRENT_PREFERENCES_TEMP}'

  cd '${NAS_STACK_DIR}'
  sudo docker compose config >/dev/null
"

echo "Pulling images and applying the stack..."

# NAS_STACK_DIR is intentionally expanded locally.
# shellcheck disable=SC2029
"${SSH_TTY[@]}" "$REMOTE" "
  set -e
  cd '${NAS_STACK_DIR}'
  sudo docker compose pull
  sudo docker compose up -d
  sudo docker compose ps

  echo
  echo "Configuring Prowlarr indexers..."
  sudo python3 '${NAS_STACK_DIR}/configure-prowlarr.py'

  echo
  echo "Configuring qBittorrent..."
  sudo python3 '${NAS_STACK_DIR}/configure-qbittorrent.py'

  echo
  echo "Configuring Sonarr and Radarr..."
  sudo python3 '${NAS_STACK_DIR}/configure-servarr.py'

  echo
  echo "Configuring Seerr..."
  sudo python3 '${NAS_STACK_DIR}/configure-seerr.py'

  echo
  echo "Synchronizing Recyclarr with Sonarr..."
  sudo docker compose run --rm recyclarr \
    sync sonarr --instance series

  echo
  echo "Synchronizing Recyclarr with Radarr..."
  sudo docker compose run --rm recyclarr \
    sync radarr --instance movies

  echo
  echo "Applying post-Recyclarr Radarr Latino policy..."
  sudo python3 '${NAS_STACK_DIR}/configure-radarr-policy.py'

  if [[ \"\${PROFILARR_SYNC_ON_DEPLOY:-0}\" == \"1\" ]]; then
    echo
    echo \"Starting Profilarr pilot profile...\"
    sudo docker compose --profile profilarr up -d profilarr profilarr-parser

    echo
    echo \"Bootstrapping Profilarr admin state...\"
    sudo python3 '${NAS_STACK_DIR}/configure-profilarr.py'

    echo
    echo \"Synchronizing Profilarr pilot...\"
    sudo python3 '${NAS_STACK_DIR}/configure-profilarr-sync.py' \
      --config '${NAS_STACK_DIR}/profilarr/pilot-sync.json' \
      --run-sync \
      --wait
  else
    echo
    echo \"Skipping Profilarr deploy sync (set PROFILARR_SYNC_ON_DEPLOY=1 to enable).\"
  fi
"

echo "Deployment completed successfully."
