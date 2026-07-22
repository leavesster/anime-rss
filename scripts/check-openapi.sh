#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON="$ROOT/.venv/bin/python"
GENERATOR="$ROOT/web/node_modules/.bin/openapi-typescript"
CHECKED_DIR="$ROOT/web/src/generated/api"
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

if [[ ! -x "$PYTHON" ]]; then
  printf 'Missing Python environment: %s\n' "$PYTHON" >&2
  exit 1
fi
if [[ ! -x "$GENERATOR" ]]; then
  printf 'Missing frontend dependencies; run make bootstrap-web.\n' >&2
  exit 1
fi

"$PYTHON" "$ROOT/backend/scripts/export_openapi.py" --output "$TEMP_DIR/openapi.json"
"$GENERATOR" "$TEMP_DIR/openapi.json" -o "$TEMP_DIR/schema.d.ts" >/dev/null

failed=0
for name in openapi.json schema.d.ts; do
  if ! cmp -s "$CHECKED_DIR/$name" "$TEMP_DIR/$name"; then
    printf 'Checked API artifact is stale: web/src/generated/api/%s\n' "$name" >&2
    diff -u "$CHECKED_DIR/$name" "$TEMP_DIR/$name" || true
    failed=1
  fi
done
if ((failed)); then
  printf 'Run npm --prefix web run generate:api and commit both generated files.\n' >&2
  exit 1
fi
printf 'Checked OpenAPI contract and TypeScript schema are current.\n'
