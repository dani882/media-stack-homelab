#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo
echo "=========================================="
echo "      Homelab Bootstrap"
echo "=========================================="
echo

for script in \
    create-folders.sh \
    create-files.sh \
    create-vscode.sh \
    create-makefile.sh \
    create-github.sh \
    validate.sh
do
    echo "Running ${script}..."
    "${ROOT_DIR}/scripts/bootstrap/${script}"
done

echo
echo "Bootstrap completed successfully."
