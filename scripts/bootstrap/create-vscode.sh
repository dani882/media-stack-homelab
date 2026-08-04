#!/usr/bin/env bash

set -e

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

mkdir -p "$ROOT/.vscode"

cat > "$ROOT/.vscode/extensions.json" <<'EOF'
{
  "recommendations": [
    "ms-azuretools.vscode-docker",
    "redhat.vscode-yaml",
    "eamodio.gitlens",
    "timonwong.shellcheck"
  ]
}
EOF

echo "VS Code configuration created."
