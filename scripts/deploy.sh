#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

docker compose \
  --env-file "${ROOT_DIR}/env/media.env" \
  -f "${ROOT_DIR}/compose/media.yaml" \
  pull

docker compose \
  --env-file "${ROOT_DIR}/env/media.env" \
  -f "${ROOT_DIR}/compose/media.yaml" \
  up -d
