#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MAKEFILE="${ROOT}/Makefile"

if [[ -f "$MAKEFILE" ]]; then
  echo "Makefile already exists; leaving it unchanged."
  exit 0
fi

cat > "$MAKEFILE" <<'MAKE_EOF'
.PHONY: validate lint shellcheck bootstrap check

validate:
	@./scripts/validate.sh

shellcheck:
	@shellcheck scripts/*.sh
	@find scripts/bootstrap -name "*.sh" -exec shellcheck {} \;

lint:
	@yamllint .

bootstrap:
	@./scripts/bootstrap.sh

check: shellcheck lint validate
MAKE_EOF

echo "Makefile created."
