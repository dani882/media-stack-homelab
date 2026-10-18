#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/stacks/media/env/.env"
DUCKDNS_DIR="${ROOT_DIR}/stacks/duckdns"

for required_file in \
  "$ENV_FILE" \
  "${DUCKDNS_DIR}/update-duckdns.sh" \
  "${DUCKDNS_DIR}/configure-duckdns.sh" \
  "${DUCKDNS_DIR}/systemd/duckdns-update.service" \
  "${DUCKDNS_DIR}/systemd/duckdns-update.timer"; do
  if [[ ! -f "$required_file" ]]; then
    echo "ERROR: Missing required file: ${required_file}" >&2
    exit 1
  fi
done

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${NAS_HOST:?NAS_HOST is required}"
: "${NAS_USER:?NAS_USER is required}"

REMOTE="${NAS_USER}@${NAS_HOST}"
REMOTE_STACK_DIR="/volume1/docker/duckdns"
REMOTE_STAGING="/volume1/docker/deploy-staging/${NAS_USER}/duckdns-$$"
SSH=(
  ssh
  -o ControlMaster=auto
  -o ControlPersist=60
  -o ConnectTimeout=15
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=4
)

cleanup() {
  "${SSH[@]}" "$REMOTE" "rm -rf '${REMOTE_STAGING}'" >/dev/null 2>&1 || true
}
trap cleanup EXIT

"${SSH[@]}" "$REMOTE" "mkdir -p '${REMOTE_STAGING}'"
for relative in \
  update-duckdns.sh \
  configure-duckdns.sh \
  systemd/duckdns-update.service \
  systemd/duckdns-update.timer; do
  "${SSH[@]}" "$REMOTE" \
    "cat > '${REMOTE_STAGING}/$(basename "$relative")'" \
    < "${DUCKDNS_DIR}/${relative}"
done

# shellcheck disable=SC2029
"${SSH[@]}" "$REMOTE" "
  set -eu
  sudo -n install -d -o root -g root -m 0700 '${REMOTE_STACK_DIR}'
  sudo -n install -o root -g root -m 0755 \
    '${REMOTE_STAGING}/update-duckdns.sh' \
    '${REMOTE_STACK_DIR}/update-duckdns.sh'
  sudo -n install -o root -g root -m 0755 \
    '${REMOTE_STAGING}/configure-duckdns.sh' \
    '${REMOTE_STACK_DIR}/configure-duckdns.sh'
  sudo -n install -o root -g root -m 0644 \
    '${REMOTE_STAGING}/duckdns-update.service' \
    /etc/systemd/system/duckdns-update.service
  sudo -n install -o root -g root -m 0644 \
    '${REMOTE_STAGING}/duckdns-update.timer' \
    /etc/systemd/system/duckdns-update.timer
  sudo -n systemctl daemon-reload
  if sudo -n test -s '${REMOTE_STACK_DIR}/duckdns.env'; then
    sudo -n systemctl enable --now duckdns-update.timer
    sudo -n systemctl start duckdns-update.service
  fi
"

echo "DuckDNS updater installed on the NAS."
if "${SSH[@]}" "$REMOTE" "sudo -n test -s '${REMOTE_STACK_DIR}/duckdns.env'"; then
  echo "Existing DuckDNS configuration verified and timer enabled."
else
  echo "Run 'make configure-duckdns' to enter the domain and token securely."
fi
