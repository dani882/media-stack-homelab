#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

STACK_DIR="${ROOT_DIR}/stacks/media"
ENV_FILE="${STACK_DIR}/env/.env"
COMPOSE_FILE="${STACK_DIR}/compose.yaml"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: Missing environment file:"
    echo "  $ENV_FILE"
    echo
    echo "Copy:"
    echo "  stacks/media/.env.example"
    echo "to:"
    echo "  stacks/media/env/.env"
    exit 1
fi

docker compose \
    --env-file "$ENV_FILE" \
    -f "$COMPOSE_FILE" \
    config >/dev/null

echo "✓ Compose configuration is valid."
