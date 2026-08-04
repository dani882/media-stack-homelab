#!/usr/bin/env bash

set -e

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo
echo "Validating repository..."
echo

test -f "$ROOT/README.md"

test -f "$ROOT/.gitignore"

test -d "$ROOT/stacks"

test -d "$ROOT/scripts"

echo "Repository looks good."
