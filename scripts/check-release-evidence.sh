#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VERSION=${1:-}
EVIDENCE_ROOT=${EVIDENCE_ROOT:-$ROOT/release-evidence}
EVIDENCE="$EVIDENCE_ROOT/$VERSION"

if [[ -z "$VERSION" ]]; then
  printf 'Usage: make release-evidence-check VERSION=<semver>\n' >&2
  exit 2
fi
for name in manifest.env automated-gates.log real-feed-soak.md acceptance-criteria.md manual-review.md checksums.sha256; do
  if [[ ! -f "$EVIDENCE/$name" ]]; then
    printf 'Missing release evidence: %s\n' "$EVIDENCE/$name" >&2
    exit 1
  fi
done

(
  cd "$EVIDENCE"
  shasum -a 256 --check checksums.sha256
)

recorded_version=$(sed -n 's/^version=//p' "$EVIDENCE/manifest.env")
recorded_revision=$(sed -n 's/^revision=//p' "$EVIDENCE/manifest.env")
current_revision=$(git -C "$ROOT" rev-parse HEAD)
if [[ "$recorded_version" != "$VERSION" || "$recorded_revision" != "$current_revision" ]]; then
  printf 'Evidence does not match requested version and current revision.\n' >&2
  exit 1
fi
if ! grep -q '^Clean-room acceptance passed for ' "$EVIDENCE/automated-gates.log"; then
  printf 'Automated clean-room acceptance evidence is incomplete.\n' >&2
  exit 1
fi
if ! grep -q '^- Phase: `duration_met`$' "$EVIDENCE/real-feed-soak.md"; then
  printf 'Seven-day real-feed soak has not reached duration_met.\n' >&2
  exit 1
fi
if grep -q '| pending |' "$EVIDENCE/real-feed-soak.md"; then
  printf 'Real-feed soak has pending preconditions.\n' >&2
  exit 1
fi
if grep -q '^- \[ \]' "$EVIDENCE/manual-review.md"; then
  printf 'Manual release review is incomplete.\n' >&2
  exit 1
fi
if [[ -n "$(git -C "$ROOT" status --porcelain=v1 --untracked-files=all)" ]]; then
  printf 'Release evidence check requires a clean worktree.\n' >&2
  exit 1
fi

printf 'Release evidence is complete for %s at %s.\n' "$VERSION" "$current_revision"
