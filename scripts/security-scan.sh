#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

for tool in "$ROOT/.venv/bin/bandit" "$ROOT/.venv/bin/pip-audit"; do
  if [[ ! -x "$tool" ]]; then
    printf 'Missing security tool: %s; run make bootstrap.\n' "$tool" >&2
    exit 1
  fi
done

uv export \
  --directory "$ROOT" \
  --locked \
  --no-dev \
  --no-editable \
  --no-emit-project \
  --output-file "$TEMP_DIR/runtime-requirements.txt" >/dev/null

"$ROOT/.venv/bin/pip-audit" \
  --requirement "$TEMP_DIR/runtime-requirements.txt" \
  --require-hashes \
  --disable-pip
"$ROOT/.venv/bin/bandit" \
  --quiet \
  --recursive \
  --severity-level medium \
  "$ROOT/backend/src"
npm --prefix "$ROOT/web" audit --audit-level=high

printf 'Python dependencies, backend source, and npm dependency graph passed security scan.\n'
