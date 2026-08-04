#!/usr/bin/env bash

set -e

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

mkdir -p \
"$ROOT/stacks/media/configs" \
"$ROOT/stacks/media/docs" \
"$ROOT/stacks/media/scripts" \
"$ROOT/stacks/media/env" \
"$ROOT/stacks/media/backups" \
"$ROOT/stacks/ai" \
"$ROOT/stacks/networking" \
"$ROOT/stacks/monitoring" \
"$ROOT/stacks/security" \
"$ROOT/docs/adr" \
"$ROOT/docs/runbooks" \
"$ROOT/docs/services" \
"$ROOT/docs/architecture" \
"$ROOT/templates" \
"$ROOT/.github/workflows" \
"$ROOT/.vscode"

echo "Folders OK"
