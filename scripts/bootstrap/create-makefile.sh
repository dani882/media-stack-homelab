#!/usr/bin/env bash

set -e

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

cat > "$ROOT/Makefile" <<'EOF'
.PHONY: validate

validate:
	@echo "Validating..."
	@./scripts/validate.sh
EOF

echo "Makefile created."
