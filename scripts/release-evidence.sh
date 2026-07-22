#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VERSION=${1:-}
EVIDENCE_ROOT=${EVIDENCE_ROOT:-$ROOT/release-evidence}
MANUAL_REVIEW_FILE=${MANUAL_REVIEW_FILE:-$ROOT/release-review.md}

if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]]; then
  printf 'Usage: make release-evidence VERSION=<semver>\n' >&2
  exit 2
fi
if [[ -n "$(git -C "$ROOT" status --porcelain=v1 --untracked-files=all)" ]]; then
  printf 'Release evidence requires a clean committed worktree.\n' >&2
  exit 1
fi
if [[ ! -f "$MANUAL_REVIEW_FILE" ]]; then
  printf 'Missing manual review. Copy scripts/release-review-template.md to release-review.md and complete it.\n' >&2
  exit 1
fi
if grep -q '^- \[ \]' "$MANUAL_REVIEW_FILE"; then
  printf 'Manual release review is incomplete: %s\n' "$MANUAL_REVIEW_FILE" >&2
  exit 1
fi

DESTINATION="$EVIDENCE_ROOT/$VERSION"
if [[ -e "$DESTINATION" ]]; then
  printf 'Evidence already exists and is immutable: %s\n' "$DESTINATION" >&2
  exit 1
fi

TEMP_DIR=$(mktemp -d)
cleanup() { rm -rf "$TEMP_DIR"; }
trap cleanup EXIT

REVISION=$(git -C "$ROOT" rev-parse HEAD)
CREATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
cat > "$TEMP_DIR/manifest.env" <<EOF
schema_version=1
version=$VERSION
revision=$REVISION
created_at=$CREATED_AT
EOF

make -C "$ROOT" acceptance-soak-report > "$TEMP_DIR/real-feed-soak.md"
if ! grep -q '^- Phase: `duration_met`$' "$TEMP_DIR/real-feed-soak.md" \
  || grep -q '| pending |' "$TEMP_DIR/real-feed-soak.md"; then
  printf 'Real-feed soak is not complete; release evidence was not created.\n' >&2
  exit 1
fi
make -C "$ROOT" clean-room-acceptance 2>&1 | tee "$TEMP_DIR/automated-gates.log"
cp "$ROOT/ACCEPTANCE.md" "$TEMP_DIR/acceptance-criteria.md"
cp "$MANUAL_REVIEW_FILE" "$TEMP_DIR/manual-review.md"

(
  cd "$TEMP_DIR"
  shasum -a 256 manifest.env automated-gates.log real-feed-soak.md \
    acceptance-criteria.md manual-review.md > checksums.sha256
)
mkdir -p "$EVIDENCE_ROOT"
mv "$TEMP_DIR" "$DESTINATION"
trap - EXIT
printf 'Release evidence created at %s\n' "$DESTINATION"
