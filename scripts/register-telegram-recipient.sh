#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/stacks/media/env/.env"
CODE="${1:-}"

if [[ ! "$CODE" =~ ^[A-Za-z0-9_-]{6,64}$ ]]; then
  echo "ERROR: Provide a 6-64 character registration code."
  echo "Use only letters, numbers, underscores, or hyphens."
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${NAS_HOST:?NAS_HOST is required}"
: "${NAS_USER:?NAS_USER is required}"

# CODE is restricted above to a shell-safe character set.
# shellcheck disable=SC2029
ssh \
  -o ConnectTimeout=15 \
  -o ServerAliveInterval=15 \
  -o ServerAliveCountMax=4 \
  "${NAS_USER}@${NAS_HOST}" \
  "cd /volume1/docker/media-stack && \
   sudo -n python3 ./notify-torrent-completions.py \
     --register-chat '$CODE' --test"
